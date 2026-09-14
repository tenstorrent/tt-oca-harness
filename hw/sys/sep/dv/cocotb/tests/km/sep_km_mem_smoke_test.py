# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SEP Key Manager memory smoke test."""

from __future__ import annotations

import cocotb
import pyuvm
from cocotb.triggers import RisingEdge
from sep_base_test import sep_base_test
from seq_lib.sep_km_mem_smoke_seq import KM_SMOKE_SRAM_WORD0, sep_km_release_seq

_MAX_KM_CYCLES = 20_000


@pyuvm.test()
class sep_km_mem_smoke_test(sep_base_test):
    """Boot a tiny KM ROM image and observe KM SRAM traffic."""

    async def run_scenario(self) -> None:
        dut = cocotb.top
        await self.bring_up_no_cpu()

        seq = sep_km_release_seq("km_release_seq")
        await self.start_seq(seq)

        polled = 0
        for polled in range(1, _MAX_KM_CYCLES + 1):
            await RisingEdge(dut.clk_i)
            if self.rd(dut.km_rom_req_count_o) > 0 and self.rd(dut.km_sram_write_count_o) > 0:
                break
        self.logger.info(
            "STEP KM activity observed after %d polled cycles (bound %d)",
            polled,
            _MAX_KM_CYCLES,
        )

        rom_count = self.rd(dut.km_rom_req_count_o)
        sram_count = self.rd(dut.km_sram_req_count_o)
        sram_writes = self.rd(dut.km_sram_write_count_o)
        sram_word0 = self.rd(dut.km_sram_word0_o)
        self.logger.info(
            "KM memory counters: rom=%d sram=%d writes=%d word0=0x%08x",
            rom_count,
            sram_count,
            sram_writes,
            sram_word0,
        )
        assert rom_count > 0, "KM ROM responder saw no fetches"
        assert sram_count > 0, "KM SRAM responder saw no requests"
        assert sram_writes > 0, "KM SRAM responder saw no writes from the KM ROM smoke image"
        assert sram_word0 == KM_SMOKE_SRAM_WORD0, (
            f"KM SRAM word0 = 0x{sram_word0:08x}, expected 0x{KM_SMOKE_SRAM_WORD0:08x}"
        )
