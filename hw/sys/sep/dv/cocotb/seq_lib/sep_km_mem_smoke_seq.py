# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Sequence helpers for sep_km_mem_smoke_test."""

from __future__ import annotations

from env.sep_axi_agent import SepAxiItem, SepAxiOp
from pyuvm import uvm_sequence

from seq_lib.sep_sw_reset_seq import (
    SEP_RESET_CTRL_SW_RESET_N,
    SW_RESET_N_BIT,
    SW_RESET_N_RESET_DEFAULT,
)

# Preserve every generated reset-domain default and additionally release KM.
SW_RESET_N_RELEASE_KM = SW_RESET_N_RESET_DEFAULT | (1 << SW_RESET_N_BIT["km"])

# The word the KM smoke ROM stores to SRAM[0]. sep_km_mem_smoke_test value-compares
# the probed word against this, which is what makes that test more than a set of
# liveness counters.
#
# The image is built from cocotb/tests/km_fw/km_rom.S, which carries the same
# literal; the compare fails if the two diverge.
KM_SMOKE_SRAM_WORD0 = 0x0000_005A


class sep_km_release_seq(uvm_sequence):
    async def body(self) -> None:
        item = SepAxiItem("release_km_sw_reset")
        item.op = SepAxiOp.WRITE
        item.addr = SEP_RESET_CTRL_SW_RESET_N
        item.length = 4
        item.wdata = SW_RESET_N_RELEASE_KM
        await self.start_item(item)
        await self.finish_item(item)
