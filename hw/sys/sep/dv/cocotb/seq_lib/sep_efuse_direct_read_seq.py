# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Direct OTP word read through the eFuse controller EFUSE_READ_CTRL interface.

Reads a raw fuse word straight from the OTP array (EFUSE_READ_CTRL -> poll
read_done -> EFUSE_READ_INTERFACE_READ_DATA.dout), BYPASSING the sense->shadow
datapath. This is distinct from ``sep_efuse_shadow_check_seq`` (which reads the
sensed shadow registers): a direct read proves a value is in persistent OTP
independent of any resense. Enforces the clear-after-read discipline (drop
read_enable when done), mirroring the program path's clear-after-program
rule (leaving an enable asserted starves the shared efuse command channel).

Result word is left in ``self.rdata`` for the caller to check.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import ClockCycles
from env.sep_axi_agent import SepAxiItem, SepAxiOp
from pyuvm import uvm_sequence
from sep_reg_meta import EFUSE_INTERFACE_CTRL

_EFUSE_READ_CTRL = EFUSE_INTERFACE_CTRL.addr("EFUSE_READ_CTRL")
_EFUSE_READ_DATA = EFUSE_INTERFACE_CTRL.addr("EFUSE_READ_INTERFACE_READ_DATA")

_EFUSE_READ_GO_BIT = EFUSE_INTERFACE_CTRL.field_mask("EFUSE_READ_CTRL", "efuse_read_go")
_EFUSE_READ_BUSY_BIT = EFUSE_INTERFACE_CTRL.field_mask("EFUSE_READ_CTRL", "read_busy")
_EFUSE_READ_DONE_BIT = EFUSE_INTERFACE_CTRL.field_mask("EFUSE_READ_CTRL", "read_done")
_EFUSE_READ_STATUS_BIT = EFUSE_INTERFACE_CTRL.field_mask("EFUSE_READ_CTRL", "read_status")
_EFUSE_READ_ENABLE_BIT = EFUSE_INTERFACE_CTRL.field_mask("EFUSE_READ_CTRL", "read_enable")
_EFUSE_ADDR_MASK = EFUSE_INTERFACE_CTRL.field_mask("EFUSE_READ_CTRL", "efuse_addr")
_EFUSE_ADDR_LSB = EFUSE_INTERFACE_CTRL.field_lsb("EFUSE_READ_CTRL", "efuse_addr")

_POLL_CYCLES = 200


class sep_efuse_direct_read_seq(uvm_sequence):
    """Read one 32-bit OTP word directly from the read interface.

    ``word_index`` is the fuse WORD index; efuse_addr is a bit address, so the
    word-aligned bit address is ``word_index * 32``. The 32-bit result is stored in
    ``self.rdata``.
    """

    def __init__(self, word_index: int, *, name: str = "sep_efuse_direct_read_seq") -> None:
        super().__init__(name)
        self.word_index = word_index
        self.rdata: int | None = None

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
        bit_addr = (self.word_index * 32) << _EFUSE_ADDR_LSB
        if self.word_index < 0 or bit_addr & ~_EFUSE_ADDR_MASK:
            raise ValueError(f"word {self.word_index} is outside the efuse_addr range")
        await self._access(
            SepAxiOp.WRITE,
            _EFUSE_READ_CTRL,
            data=bit_addr | _EFUSE_READ_GO_BIT | _EFUSE_READ_ENABLE_BIT,
            label="read_ctrl",
        )
        for _ in range(_POLL_CYCLES):
            await ClockCycles(cocotb.top.clk_i, 1)
            status = await self._access(SepAxiOp.READ, _EFUSE_READ_CTRL, label="read_status")
            if status & _EFUSE_READ_DONE_BIT:
                assert not (status & _EFUSE_READ_STATUS_BIT), (
                    f"EFUSE_READ_CTRL logic error (read_status=1) reading word {self.word_index}"
                )
                self.rdata = await self._access(SepAxiOp.READ, _EFUSE_READ_DATA, label="read_data")
                # Clear read_enable before returning (clear-after-read discipline).
                await self._access(
                    SepAxiOp.WRITE, _EFUSE_READ_CTRL, data=0, label="read_ctrl_clear"
                )
                return
        raise AssertionError(
            f"EFUSE direct read of word {self.word_index} never signaled read_done "
            f"within {_POLL_CYCLES} cycles"
        )
