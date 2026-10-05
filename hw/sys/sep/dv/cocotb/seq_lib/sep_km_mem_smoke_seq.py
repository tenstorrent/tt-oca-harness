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

# Scrambled read-back in the same image: with the KMCSR SRAM scrambler enabled,
# km_rom.S stores these four plaintexts to four different SRAM words, reads
# them back with four consecutive loads, clears the scrambler enable, and
# stores the loaded values to SRAM words KM_SMOKE_SCR_RESULT_WORDS, where the
# test reads them through km_sram_probe_o. DV-owned values, carried as the
# same literals by km_rom.S; the compare fails if the two diverge.
KM_SMOKE_SCRAMBLER_KEY = 0x6C8E_3A5B
KM_SMOKE_SCR_PLAINTEXT = (0x1E2D_3C4B, 0xA596_8778, 0x0F1E_2D3C, 0xC3B4_A596)
KM_SMOKE_SCR_RESULT_WORDS = (1, 2, 3, 4)
# The four cells km_rom.S (.equ CELL0..CELL3) stores the plaintexts to with the
# scrambler enabled, as byte offsets from KEY_MANAGER_SRAM_BASE_ADDR. The
# km_sram_probe_o word index of an offset is offset // 4.
KM_SMOKE_SCR_CELL_OFFSETS = (0x0100, 0x0104, 0x3FF8, 0x7FFC)


class sep_km_release_seq(uvm_sequence):
    async def body(self) -> None:
        item = SepAxiItem("release_km_sw_reset")
        item.op = SepAxiOp.WRITE
        item.addr = SEP_RESET_CTRL_SW_RESET_N
        item.length = 4
        item.wdata = SW_RESET_N_RELEASE_KM
        await self.start_item(item)
        await self.finish_item(item)
