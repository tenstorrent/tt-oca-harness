# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SEP Key Manager memory smoke test.

no_cpu / +skip_fuse_sense / +km_rom_hex=km_rom.parhex. RAND-NONE.

The KM ROM image (cocotb/tests/km_fw/km_rom.S) fetches from the KM ROM, reads
KM SRAM back through the enabled SRAM scrambler, and stores a marker to SRAM
word0 as its last store.

Checkers:
  CHK-KM-MEM         the KM fetched from its ROM, requested and wrote its
                     SRAM, and SRAM word0 holds the marker the image stores
  CHK-KM-SRAM-SCR-RT four consecutive loads of four different SRAM words,
                     each holding a different plaintext written through the
                     enabled scrambler, return those plaintexts. At least
                     four SRAM reads are accepted while the scrambler enable
                     is set, so the loads go through the descrambler.
                     km_sram_interface descrambles a response with the address
                     of the read it accepted; a descramble with the address of
                     the previous read returns a different word
  CHK-KM-SRAM-RD-LAT every KM SRAM read the wrapper accepts gets its rvalid
                     exactly one cycle later, and no rvalid arrives without an
                     accept one cycle earlier. This is the read latency the
                     descrambler address capture relies on. The count of
                     rvalid cycles that also accept a new read of a different
                     address is logged, not graded
"""

from __future__ import annotations

import cocotb
import pyuvm
from cocotb.triggers import ClockCycles, RisingEdge
from sep_base_test import sep_base_test
from seq_lib.sep_km_mem_smoke_seq import (
    KM_SMOKE_SCR_PLAINTEXT,
    KM_SMOKE_SCR_RESULT_WORDS,
    KM_SMOKE_SRAM_WORD0,
    sep_km_release_seq,
)

_MAX_KM_CYCLES = 20_000


@pyuvm.test()
class sep_km_mem_smoke_test(sep_base_test):
    """Boot a tiny KM ROM image and observe KM SRAM traffic."""

    async def run_scenario(self) -> None:
        dut = cocotb.top
        await self.bring_up_no_cpu()

        seq = sep_km_release_seq("km_release_seq")
        await self.start_seq(seq)

        # The marker is the image's last store, so the results are in place
        # once it is seen.
        polled = 0
        done = False
        for polled in range(1, _MAX_KM_CYCLES + 1):
            await RisingEdge(dut.clk_i)
            if self.rd(dut.km_sram_word0_o, allow_unknown=True) == KM_SMOKE_SRAM_WORD0:
                done = True
                break
        assert done, (
            f"CHK-KM-MEM FAIL: KM SRAM word0 did not reach the marker "
            f"0x{KM_SMOKE_SRAM_WORD0:08x} within {_MAX_KM_CYCLES} cycles "
            f"(word0=0x{self.rd(dut.km_sram_word0_o, allow_unknown=True):08x})"
        )
        self.logger.info(
            "STEP KM image done after %d polled cycles (bound %d)", polled, _MAX_KM_CYCLES
        )
        await ClockCycles(dut.clk_i, 4)

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
        self.logger.info(
            "CHK-KM-MEM PASS: rom=%d sram=%d writes=%d word0=0x%08x",
            rom_count,
            sram_count,
            sram_writes,
            sram_word0,
        )

        self._chk_scrambled_readback()
        self._chk_read_latency()

    def _chk_scrambled_readback(self) -> None:
        dut = cocotb.top
        n = len(KM_SMOKE_SCR_PLAINTEXT)
        assert len(set(KM_SMOKE_SCR_PLAINTEXT)) == n, "test bug: plaintexts are not distinct"
        scr_reads = self.rd(dut.km_sram_scr_rd_count_o)
        assert scr_reads >= n, (
            f"CHK-KM-SRAM-SCR-RT FAIL: {scr_reads} KM SRAM reads were accepted with the "
            f"scrambler enabled, expected at least {n}: the loads did not go through "
            "the descrambler"
        )
        probe = dut.km_sram_probe_o
        got = [
            self.rd(probe, mask=0xFFFF_FFFF << (32 * word)) >> (32 * word)
            for word in KM_SMOKE_SCR_RESULT_WORDS
        ]
        for i, (actual, expected) in enumerate(zip(got, KM_SMOKE_SCR_PLAINTEXT, strict=True)):
            assert actual == expected, (
                f"CHK-KM-SRAM-SCR-RT FAIL: scrambled load {i} returned 0x{actual:08x}, "
                f"expected the plaintext 0x{expected:08x} (all loads: "
                f"{[hex(v) for v in got]})"
            )
        self.logger.info(
            "CHK-KM-SRAM-SCR-RT PASS: %d consecutive scrambled loads of different words "
            "returned their plaintexts %s; %d reads accepted with the scrambler enabled",
            n,
            [hex(v) for v in got],
            scr_reads,
        )

    def _chk_read_latency(self) -> None:
        dut = cocotb.top
        accepts = self.rd(dut.km_sram_rd_accept_count_o)
        lat1 = self.rd(dut.km_sram_rd_lat1_count_o)
        lat_err = self.rd(dut.km_sram_rd_lat_err_count_o)
        b2b_diff = self.rd(dut.km_sram_rd_b2b_diff_count_o)
        n = len(KM_SMOKE_SCR_PLAINTEXT)
        assert accepts >= n, (
            f"CHK-KM-SRAM-RD-LAT FAIL: {accepts} KM SRAM reads accepted, expected at "
            f"least the image's {n} loads"
        )
        assert lat_err == 0 and lat1 == accepts, (
            f"CHK-KM-SRAM-RD-LAT FAIL: {accepts} reads accepted, {lat1} answered one "
            f"cycle later, {lat_err} cycles where rvalid and the one-cycle-earlier "
            "accept disagree"
        )
        self.logger.info(
            "CHK-KM-SRAM-RD-LAT PASS: all %d accepted KM SRAM reads returned rvalid "
            "exactly one cycle after the accept (0 mismatched cycles); rvalid cycles "
            "that also accepted a read of a different address: %d (logged)",
            accepts,
            b2b_diff,
        )
