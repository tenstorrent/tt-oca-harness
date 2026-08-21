# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Sequence helpers for sep_km_mem_smoke_test."""

from __future__ import annotations

from pyuvm import uvm_sequence

from env.sep_axi_agent import SepAxiItem, SepAxiOp
from seq_lib.sep_sw_reset_seq import SEP_RESET_CTRL_SW_RESET_N

SW_RESET_N_RELEASE_KM = 0x0000_001F  # release all engines (km|otbn|aes|hmac|kmac)

# The word the KM smoke ROM stores to SRAM[0]. sep_km_mem_smoke_test value-compares
# the probed word against this, which is what makes that test more than a set of
# liveness counters.
#
# HARDCODED DELIBERATELY: it comes from cocotb/tests/km_rom.parhex, a COMMITTED
# image with no tracked assembly source in cocotb/tests/km_fw/ (only
# km_rom_entropy.S and km_rom_coexist.S are tracked there), so there is nothing to
# derive it from. If that image is ever rebuilt from tracked source, this constant
# must move with it -- the compare fails loudly if they diverge, which is intended.
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
