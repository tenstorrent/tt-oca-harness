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

from sep_reg_meta import sym

import cocotb
from cocotb.triggers import ClockCycles
from pyuvm import uvm_sequence

from env.sep_axi_agent import SepAxiItem, SepAxiOp

# EFUSE interface-controller MMRs (SEP-local shadow base 0x1093_0000 + 0x400 block).
_EFUSE_READ_CTRL = sym("SEP_EFUSE_MAP_REG_MAP_BASE_ADDR") + 0x400 + 0x8
_EFUSE_READ_DATA = sym("SEP_EFUSE_MAP_REG_MAP_BASE_ADDR") + 0x400 + 0x10

# EFUSE_READ_CTRL field encoding (efuse_interface_ctrl.rdl).
_EFUSE_READ_GO_BIT = 1 << 16       # efuse_read_go (singlepulse)
_EFUSE_READ_BUSY_BIT = 1 << 24     # read_busy (status)
_EFUSE_READ_DONE_BIT = 1 << 25     # read_done (status)
_EFUSE_READ_STATUS_BIT = 1 << 26   # read_status: 1 = logic error (go w/o enable)
_EFUSE_READ_ENABLE_BIT = 1 << 28   # read_enable

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
        bit_addr = (self.word_index * 32) & 0xFFFF
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
                    f"EFUSE_READ_CTRL logic error (read_status=1) reading word "
                    f"{self.word_index}"
                )
                self.rdata = await self._access(SepAxiOp.READ, _EFUSE_READ_DATA, label="read_data")
                # Clear read_enable before returning (clear-after-read discipline).
                await self._access(SepAxiOp.WRITE, _EFUSE_READ_CTRL, data=0, label="read_ctrl_clear")
                return
        raise AssertionError(
            f"EFUSE direct read of word {self.word_index} never signaled read_done "
            f"within {_POLL_CYCLES} cycles"
        )
