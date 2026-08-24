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
"""

from __future__ import annotations

from sep_reg_meta import sym

import cocotb
from cocotb.triggers import ClockCycles
from pyuvm import uvm_sequence

from env.sep_axi_agent import SepAxiItem, SepAxiOp

# EFUSE control MMR aperture (SEP-local shadow base + 0x400).
_EFUSE_PROGRAM_CTRL = sym("SEP_EFUSE_MAP_REG_MAP_BASE_ADDR") + 0x400 + 0x4

# EFUSE_PROGRAM_CTRL field encoding.
_EFUSE_DATA_BIT = 1 << 16          # program the addressed bit to 1 (W1S)
_EFUSE_PROGRAM_GO_BIT = 1 << 17
_EFUSE_PROGRAM_READ_BACK_BIT = 1 << 18
_EFUSE_PROGRAM_ENABLE_BIT = 1 << 27
_EFUSE_PROGRAM_DONE_BIT = 1 << 25  # status: program cycle complete
_EFUSE_PROGRAM_ERR_BIT = 1 << 26   # status: read-back mismatch (injected/real fail)

_POLL_CYCLES = 200


class sep_efuse_otp_program_seq(uvm_sequence):
    """W1S one OTP bit via the frontdoor, retrying past injected program failures."""

    def __init__(
        self,
        bit_addr: int,
        *,
        max_attempts: int = 10,
        name: str = "sep_efuse_otp_program_seq",
    ) -> None:
        super().__init__(name)
        self.bit_addr = bit_addr
        self.max_attempts = max_attempts
        self.retry_count = 0

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
            (self.bit_addr & 0xFFFF)
            | _EFUSE_DATA_BIT
            | _EFUSE_PROGRAM_GO_BIT
            | _EFUSE_PROGRAM_READ_BACK_BIT
            | _EFUSE_PROGRAM_ENABLE_BIT
        )
        for attempt in range(1, self.max_attempts + 1):
            await self._access(SepAxiOp.WRITE, _EFUSE_PROGRAM_CTRL, data=wdata, label="program_ctrl")

            for _ in range(_POLL_CYCLES):
                await ClockCycles(cocotb.top.clk_i, 1)
                status = await self._access(SepAxiOp.READ, _EFUSE_PROGRAM_CTRL, label="program_status")
                if not (status & _EFUSE_PROGRAM_DONE_BIT):
                    continue
                # Clear program_enable BEFORE any subsequent read .
                await self._access(SepAxiOp.WRITE, _EFUSE_PROGRAM_CTRL, data=0, label="program_ctrl_clear")
                if not (status & _EFUSE_PROGRAM_ERR_BIT):
                    if self.retry_count:
                        cocotb.log.info(
                            "CHK-OTP-RETRY PASS: OTP bit[%d] programmed after %d retr(ies)",
                            self.bit_addr, self.retry_count,
                        )
                    cocotb.log.info("[efuse] OTP bit[%d] programmed via frontdoor", self.bit_addr)
                    return
                # Read-back mismatch (injected or real): retry this bit.
                self.retry_count += 1
                break
            else:
                raise AssertionError(
                    f"OTP program bit {self.bit_addr} never signaled DONE within "
                    f"{_POLL_CYCLES} cycles on attempt {attempt}"
                )

        raise AssertionError(
            f"OTP program bit {self.bit_addr} failed after {self.max_attempts} attempts"
        )
