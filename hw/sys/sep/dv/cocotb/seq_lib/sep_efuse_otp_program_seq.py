# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Frontdoor OTP single-bit program sequence (write-one-to-set).

Programs one eFuse bit through the ``EFUSE_PROGRAM_CTRL`` MMR and enforces the
clear-after-program discipline (leaving ``program_enable`` asserted
while a later read is issued starves the shared efuse command channel and hangs
the read FSM). The generic efuse model's persistent W1S ``field_storage`` retains
programmed bits across reset/resense, so a program followed by a resense proves
the persistence path.

Parameterize ``bit_addr`` (global fuse bit index = word*32 + bit).
``retry_count`` records how many injected program failures forced a retry, so a
test can prove the retry path was exercised rather than passing vacuously.
``expect_err`` is the write-lock / token-gate path: one attempt, require
PROGRAM_ERR, then W1C the sticky ``efuse_req_error`` so a later command is
not starved.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import ClockCycles
from env.sep_axi_agent import SepAxiItem, SepAxiOp
from pyuvm import uvm_sequence
from sep_reg_meta import EFUSE_INTERFACE_CTRL

_EFUSE_PROGRAM_CTRL = EFUSE_INTERFACE_CTRL.addr("EFUSE_PROGRAM_CTRL")
_EFUSE_IFACE_STATUS = EFUSE_INTERFACE_CTRL.addr("EFUSE_INTERFACE_CTRL_STATUS")
_EFUSE_REQ_ERROR_BIT = EFUSE_INTERFACE_CTRL.field_mask(
    "EFUSE_INTERFACE_CTRL_STATUS", "efuse_req_error"
)
_EFUSE_REQ_ERROR_CLEAR = EFUSE_INTERFACE_CTRL.field_mask(
    "EFUSE_INTERFACE_CTRL_STATUS", "efuse_req_error_clear"
)

_EFUSE_DATA_BIT = EFUSE_INTERFACE_CTRL.field_mask("EFUSE_PROGRAM_CTRL", "efuse_data")
_EFUSE_PROGRAM_GO_BIT = EFUSE_INTERFACE_CTRL.field_mask("EFUSE_PROGRAM_CTRL", "efuse_program_go")
_EFUSE_PROGRAM_READ_BACK_BIT = EFUSE_INTERFACE_CTRL.field_mask(
    "EFUSE_PROGRAM_CTRL", "efuse_program_read_back"
)
_EFUSE_PROGRAM_ENABLE_BIT = EFUSE_INTERFACE_CTRL.field_mask("EFUSE_PROGRAM_CTRL", "program_enable")
_EFUSE_PROGRAM_DONE_BIT = EFUSE_INTERFACE_CTRL.field_mask("EFUSE_PROGRAM_CTRL", "program_done")
_EFUSE_PROGRAM_ERR_BIT = EFUSE_INTERFACE_CTRL.field_mask("EFUSE_PROGRAM_CTRL", "program_status")

_EFUSE_ADDR_MASK = EFUSE_INTERFACE_CTRL.field_mask("EFUSE_PROGRAM_CTRL", "efuse_addr")
_EFUSE_ADDR_LSB = EFUSE_INTERFACE_CTRL.field_lsb("EFUSE_PROGRAM_CTRL", "efuse_addr")

_POLL_CYCLES = 200


def _place_addr(bit_addr: int) -> int:
    """Place a fuse bit address in EFUSE_PROGRAM_CTRL.efuse_addr."""
    placed = bit_addr << _EFUSE_ADDR_LSB
    if bit_addr < 0 or placed & ~_EFUSE_ADDR_MASK:
        raise ValueError(f"bit address {bit_addr:#x} does not fit efuse_addr")
    return placed


class sep_efuse_otp_program_seq(uvm_sequence):
    """W1S one OTP bit via the frontdoor, retrying past injected program failures."""

    def __init__(
        self,
        bit_addr: int,
        *,
        max_attempts: int = 10,
        expect_err: bool = False,
        name: str = "sep_efuse_otp_program_seq",
    ) -> None:
        super().__init__(name)
        self.bit_addr = bit_addr
        self.max_attempts = 1 if expect_err else max_attempts
        self.expect_err = expect_err
        self.retry_count = 0
        self.saw_err = False

    async def _access(self, op: SepAxiOp, addr: int, *, data: int = 0, label: str = "axi") -> int:
        item = SepAxiItem(f"{label}_0x{addr:08x}")
        item.op = op
        item.addr = addr
        item.length = 4
        item.wdata = data
        await self.start_item(item)
        await self.finish_item(item)
        return item.rdata

    async def body(self) -> None:
        wdata = (
            _place_addr(self.bit_addr)
            | _EFUSE_DATA_BIT
            | _EFUSE_PROGRAM_GO_BIT
            | _EFUSE_PROGRAM_READ_BACK_BIT
            | _EFUSE_PROGRAM_ENABLE_BIT
        )
        for attempt in range(1, self.max_attempts + 1):
            await self._access(
                SepAxiOp.WRITE, _EFUSE_PROGRAM_CTRL, data=wdata, label="program_ctrl"
            )

            for _ in range(_POLL_CYCLES):
                await ClockCycles(cocotb.top.clk_i, 1)
                status = await self._access(
                    SepAxiOp.READ, _EFUSE_PROGRAM_CTRL, label="program_status"
                )
                if not (status & _EFUSE_PROGRAM_DONE_BIT):
                    continue
                # Clear program_enable BEFORE any subsequent read .
                await self._access(
                    SepAxiOp.WRITE, _EFUSE_PROGRAM_CTRL, data=0, label="program_ctrl_clear"
                )
                if status & _EFUSE_PROGRAM_ERR_BIT:
                    self.saw_err = True
                    if self.expect_err:
                        await self._clear_req_error()
                        cocotb.log.info(
                            "[efuse] OTP bit[%d] rejected (PROGRAM_ERR) as expected",
                            self.bit_addr,
                        )
                        return
                    # Read-back mismatch (injected or real): retry this bit.
                    self.retry_count += 1
                    break
                if self.expect_err:
                    raise AssertionError(
                        f"OTP program bit {self.bit_addr} succeeded; expected "
                        "PROGRAM_ERR (write-lock or token gate)"
                    )
                if self.retry_count:
                    cocotb.log.info(
                        "CHK-OTP-RETRY PASS: OTP bit[%d] programmed after %d retr(ies)",
                        self.bit_addr,
                        self.retry_count,
                    )
                cocotb.log.info("[efuse] OTP bit[%d] programmed via frontdoor", self.bit_addr)
                return
            else:
                raise AssertionError(
                    f"OTP program bit {self.bit_addr} never signaled DONE within "
                    f"{_POLL_CYCLES} cycles on attempt {attempt}"
                )

        raise AssertionError(
            f"OTP program bit {self.bit_addr} failed after {self.max_attempts} attempts"
        )

    async def _clear_req_error(self) -> None:
        """W1C the sticky guard error so a later program/read is not starved."""
        await self._access(
            SepAxiOp.WRITE,
            _EFUSE_IFACE_STATUS,
            data=_EFUSE_REQ_ERROR_CLEAR,
            label="iface_err_clear",
        )
        status = await self._access(SepAxiOp.READ, _EFUSE_IFACE_STATUS, label="iface_status")
        if status & _EFUSE_REQ_ERROR_BIT:
            raise AssertionError(
                f"EFUSE_INTERFACE_CTRL_STATUS.efuse_req_error stuck after clear "
                f"(status=0x{status:08x})"
            )
