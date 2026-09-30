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
                     the previous read returns a different word. This image
                     issues no read in the same cycle as a response to a read
                     of a different word (KM-SRAM-RD-LAT logs that count), so
                     a descramble that takes the address at response time is
                     not exercised here
  CHK-KM-SRAM-SCR-STORED
                     with the scrambler enabled, a store does not leave its
                     plaintext in the SRAM array. The scrambler moves the
                     address as well as the data, so the tb_top monitor at the
                     wrapper port keeps the physical address and data of each
                     write accepted while the enable is set. Exactly the four
                     plaintext stores are kept, at four different physical
                     rows that are not all their logical words; no kept write
                     carries a plaintext; and the macro
                     array word at each kept row equals the kept data. No word
                     of km_sram_probe_o (SRAM words 0..97) other than the
                     result words 1..4 holds a plaintext. A scrambler that
                     passes the data through writes a plaintext and fails

KM-SRAM-RD-LAT is a measurement, not a checker. km_sram_interface descrambles a
read response with the address it captures on the accepting edge, so it relies
on a one-cycle SRAM read latency. No specification states that latency, so the
accept, one-cycle-later and mismatch counts are logged as the measured
precondition. The data round trip in CHK-KM-SRAM-SCR-RT is the verdict.
"""

from __future__ import annotations

import cocotb
import pyuvm
from cocotb.triggers import ClockCycles, RisingEdge
from sep_base_test import sep_base_test
from seq_lib.sep_km_mem_smoke_seq import (
    KM_SMOKE_SCR_CELL_OFFSETS,
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
        self._chk_scrambled_store()
        self._log_read_latency()

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

    def _chk_scrambled_store(self) -> None:
        dut = cocotb.top
        n = len(KM_SMOKE_SCR_PLAINTEXT)
        aw = len(dut.km_sram_scr_wr_addr_o) // n
        tag = "CHK-KM-SRAM-SCR-STORED"
        try:
            wr_count = self.rd_known(dut.km_sram_scr_wr_count_o)
            addrs = self.rd_known(dut.km_sram_scr_wr_addr_o)
            packed_data = self.rd_known(dut.km_sram_scr_wr_data_o)
            cells = self.rd_known(dut.km_sram_scr_wr_cell_o)
        except AssertionError as exc:
            raise AssertionError(f"{tag} FAIL: scrambled-write monitor not known: {exc}") from exc
        assert wr_count == n, (
            f"{tag} FAIL: {wr_count} SRAM writes accepted with the scrambler enabled, "
            f"want the image's {n} plaintext stores"
        )
        rows = [(addrs >> (aw * i)) & ((1 << aw) - 1) for i in range(n)]
        data = [(packed_data >> (32 * i)) & 0xFFFF_FFFF for i in range(n)]
        held = [(cells >> (32 * i)) & 0xFFFF_FFFF for i in range(n)]
        logical = [off // 4 for off in KM_SMOKE_SCR_CELL_OFFSETS]
        faults = []
        if rows == logical:
            faults.append(
                f"every store reached its own logical word {[hex(r) for r in rows]}, so the "
                "address was not scrambled"
            )
        if len(set(rows)) != n:
            faults.append(f"the {n} stores reached physical rows {[hex(r) for r in rows]}")
        for i, pt in enumerate(KM_SMOKE_SCR_PLAINTEXT):
            if data[i] in KM_SMOKE_SCR_PLAINTEXT:
                faults.append(
                    f"store {i} (plaintext 0x{pt:08x}) wrote 0x{data[i]:08x} to row "
                    f"0x{rows[i]:x}, a plaintext"
                )
            if held[i] != data[i]:
                faults.append(
                    f"row 0x{rows[i]:x} holds 0x{held[i]:08x}, not the written 0x{data[i]:08x}"
                )
        probe = dut.km_sram_probe_o
        count = len(probe) // 32
        words = [
            self.rd(probe, mask=0xFFFF_FFFF << (32 * i), allow_unknown=True) >> (32 * i)
            for i in range(count)
        ]
        faults += [
            f"word {i} holds plaintext 0x{w:08x}"
            for i, w in enumerate(words)
            if i not in KM_SMOKE_SCR_RESULT_WORDS and w in KM_SMOKE_SCR_PLAINTEXT
        ]
        assert not faults, (
            f"{tag} FAIL: a store with the scrambler enabled left its plaintext in the "
            "SRAM array, or the array does not hold what was written: " + "; ".join(faults)
        )
        self.logger.info(
            "%s PASS: %d writes with the scrambler enabled; plaintexts %s at logical "
            "words %s were written as %s to physical rows %s, and the array holds %s. "
            "No word of SRAM words 0..%d outside the result words 1..4 holds a plaintext",
            tag,
            wr_count,
            [hex(v) for v in KM_SMOKE_SCR_PLAINTEXT],
            [hex(w) for w in logical],
            [hex(v) for v in data],
            [hex(r) for r in rows],
            [hex(v) for v in held],
            count - 1,
        )

    def _log_read_latency(self) -> None:
        dut = cocotb.top
        accepts = self.rd(dut.km_sram_rd_accept_count_o)
        lat1 = self.rd(dut.km_sram_rd_lat1_count_o)
        lat_err = self.rd(dut.km_sram_rd_lat_err_count_o)
        b2b_diff = self.rd(dut.km_sram_rd_b2b_diff_count_o)
        self.logger.info(
            "KM-SRAM-RD-LAT (measured precondition, not graded): %d KM SRAM reads "
            "accepted, %d returned rvalid one cycle after the accept, %d cycles where "
            "rvalid and the one-cycle-earlier accept disagree; rvalid cycles that also "
            "accepted a read of a different address: %d",
            accepts,
            lat1,
            lat_err,
            b2b_diff,
        )
