# SPDX-License-Identifier: Apache-2.0
"""Sequence helpers for sep_km_mem_smoke_test."""

from __future__ import annotations

from pyuvm import uvm_sequence

from env.sep_axi_agent import SepAxiItem, SepAxiOp
from seq_lib.sep_sw_reset_seq import SEP_RESET_CTRL_SW_RESET_N

SW_RESET_N_RELEASE_KM = 0x0000_001F  # release all engines (km|otbn|aes|hmac|kmac)
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
