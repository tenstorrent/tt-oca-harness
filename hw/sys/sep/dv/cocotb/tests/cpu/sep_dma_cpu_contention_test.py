# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Secure-DMA and CPU-LSU traffic overlap at SRAM and DCCM; both land bit-exact with no DMA error.

The dma_cpu_contention firmware starts a long SRAM->SRAM Secure-DMA copy and, while it runs, a CPU
store loop into a disjoint SRAM region, so both masters arbitrate at the SRAM slave on the
SEP-local xbar with no testbench injection. The firmware checks overlap (STATUS BUSY and not DONE
mid-flight), DONE with no error, the STATUS RW1C clear, and bit-exact DMA and CPU data;
fw/startup/crt0.s emits PASS/FAIL magic that the boot scoreboard gates on.

The TB counts cycles where the CPU-LSU and DMA crossbar inputs both present an SRAM request on
the same address channel; a positive count is the contention proof, which DMA BUSY alone is not.

The DCCM leg copies an SRAM block into one DCCM array through the core DMA slave port while the
CPU stores a pass-unique pattern to a second DCCM array until the DMA reports done. Each pass reads
its words back and counts mismatches, and samples DMA BUSY before its stores. The firmware logs the
mismatch total, the busy-pass count and the pass count, dumps both arrays and the DMA STATUS and
ERROR_CODE readbacks; the host grades every word, the mismatch total and the status
(CHK-DCCM-DMA-DATA, CHK-DCCM-CPU-DATA, CHK-DCCM-NOERR). At least one pass must begin with the DMA
busy (CTRL-DCCM-BUSY-PASS, stimulus reach). The TB counts clocks where the
VeeR LSU sees a DMA DCCM write request and a store-buffer DCCM write request together; a positive
count is logged as CTRL-DCCM-OVERLAP (stimulus reach, not a DUT contract).

No fuse data is read, so the testlist entry uses ``+skip_fuse_sense``.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

import cocotb
import pyuvm
from env.sep_boot_scoreboard import SepBootScoreboard
from sep_base_test import sep_base_test
from sep_reg_meta import RegBlock, sym

_DV_ROOT = str(Path(__file__).resolve().parents[3])
_FW_DIR = os.path.join(_DV_ROOT, "fw", "build", "tests", "dma_cpu_contention_test")
_ITCM_HEX = os.path.join(_FW_DIR, "dma_cpu_contention_test.itcm.hex")
_DTCM_HEX = os.path.join(_FW_DIR, "dma_cpu_contention_test.dtcm.hex")

_ICCM_BASE = sym("SEP_ICCM_MEM_BASE_ADDR")
# 2 KiB SRAM->SRAM copy + a 256 B CPU loop + two full-region verifies, then a 1 KiB
# SRAM->DCCM copy under CPU store passes and a console dump of both DCCM arrays; the
# run loop early-exits on fw_done, so this is an upper bound.
_MAX_RUN_CYCLES = 4_000_000
_NO_BOOT_CYCLES = 80_000
_PROGRESS_EVERY = 5_000
_DMA = RegBlock("SECURE_DMA")
_ST_BUSY = _DMA.field_mask("STATUS", "busy")

# The clauses of the firmware's single verdict line, one per VPLAN checker. An image
# without a leg loses its clause, which fails here rather than at the PASS magic.
_VERDICT_CLAUSES = (
    (
        f"overlap STATUS=0x{_ST_BUSY:08x}",
        "CHK-IN-FLIGHT",
        "the DMA busy and not done at store-loop exit",
    ),
    ("ERROR_CODE=0", "CHK-NOERR", "the DMA completing with no error"),
    (
        "DONE+RW1C clear",
        "CHK-RW1C",
        "the done status holding after the poll and clearing on write-one-to-clear",
    ),
    ("dst==src", "CHK-DMA-DATA", "the DMA destination matching its source"),
    ("cont==cpu", "CHK-CPU-DATA", "the CPU region holding exactly what the CPU wrote"),
)
_BANNER = "SEP DMA/CPU contention test"

# DCCM leg stimulus, mirrored from the firmware; the firmware echoes each value on its
# DCCM-LEG line and the host requires the echo to match.
_DCCM_DMA_WORDS = 256
_DCCM_CPU_WORDS = 64
_DCCM_SRC_SEED = 0xD0CC0000
_DCCM_CPU_SEED = 0x3C000000
_MASK32 = 0xFFFFFFFF
_DCCM_LEG_RE = re.compile(
    r"DCCM-LEG STATUS=0x(?P<status>[0-9a-f]{8}) ERROR_CODE=0x(?P<err>[0-9a-f]{8})"
    r" mismatches=0x(?P<mismatches>[0-9a-f]{8}) busy_passes=0x(?P<busy_passes>[0-9a-f]{8})"
    r" passes=0x(?P<passes>[0-9a-f]{8}) src_seed=0x(?P<src_seed>[0-9a-f]{8})"
    r" cpu_seed=0x(?P<cpu_seed>[0-9a-f]{8}) dma_words=0x(?P<dma_words>[0-9a-f]{8})"
    r" cpu_words=0x(?P<cpu_words>[0-9a-f]{8})"
)
_ST_DONE = _DMA.field_mask("STATUS", "done")
_ST_ERROR = _DMA.field_mask("STATUS", "error")


def _dump_words(console: str, tag: str) -> list[int]:
    """Words of every ``<tag> 0x........`` console line, in order."""
    words: list[int] = []
    for ln in console.splitlines():
        if ln.startswith(tag + " "):
            words.extend(int(tok, 16) for tok in ln.split()[1:])
    return words


def _first_mismatch(got: list[int], exp: list[int]) -> str:
    for i, (g, e) in enumerate(zip(got, exp, strict=True)):
        if g != e:
            return f"word {i}: got 0x{g:08x}, expected 0x{e:08x}"
    return ""


@pyuvm.test()
class sep_dma_cpu_contention_test(sep_base_test):
    """DMA and CPU traffic meet at SRAM and at DCCM, and both land bit-exact with no DMA error."""

    build_env = False

    def build_phase(self) -> None:
        super().build_phase()
        self.sb = SepBootScoreboard("sb", self)

    async def run_scenario(self) -> None:
        # Override the boot scoreboard's expected banner here (after its own
        # build_phase, which resets it to the hello_world default).
        self.sb.expected_line = _BANNER
        await self.boot_firmware(
            self.sb,
            _ITCM_HEX,
            _DTCM_HEX,
            rst_vec=_ICCM_BASE >> 1,
            max_run_cycles=_MAX_RUN_CYCLES,
            no_boot_cycles=_NO_BOOT_CYCLES,
            progress_every=_PROGRESS_EVERY,
        )

        # The firmware scores five contracts into one verdict line. The PASS magic
        # cannot say which of them ran, so gate on each clause the line carries and
        # emit the record the VPLAN row names for it.
        console = self.sb.console_text()
        verdict = next((ln for ln in console.splitlines() if ln.startswith("PASS: DMA(")), "")
        assert verdict, (
            f"firmware console has no 'PASS: DMA(...' verdict line. Console was:\n{console}"
        )
        for needle, chk, what in _VERDICT_CLAUSES:
            assert needle in verdict, (
                f"firmware verdict line has no {needle!r}, so {what} was not "
                f"checked. Line was: {verdict!r}"
            )
            self.logger.info("%s PASS: firmware reported %s", chk, what)

        overlap = cocotb.top.dma_cpu_sram_overlap_count_o.value
        assert overlap.is_resolvable, f"dma_cpu_sram_overlap_count_o is unresolvable ({overlap})"
        overlap_count = int(overlap)
        assert overlap_count > 0, (
            "CHK-OVERLAP FAIL: CPU-LSU and DMA never presented simultaneous "
            "SRAM requests on the same local-crossbar address channel"
        )
        self.logger.info(
            "CHK-OVERLAP PASS: CPU-LSU and DMA SRAM request windows overlapped for %d cycle(s)",
            overlap_count,
        )

        self._grade_dccm_leg(console)

    def _grade_dccm_leg(self, console: str) -> None:
        m = _DCCM_LEG_RE.search(console)
        assert m, f"firmware console has no DCCM-LEG line. Console was:\n{console}"
        f = {k: int(v, 16) for k, v in m.groupdict().items()}
        stim = {
            "src_seed": _DCCM_SRC_SEED,
            "cpu_seed": _DCCM_CPU_SEED,
            "dma_words": _DCCM_DMA_WORDS,
            "cpu_words": _DCCM_CPU_WORDS,
        }
        for key, want in stim.items():
            assert f[key] == want, (
                f"DCCM-LEG {key}=0x{f[key]:x} but the host expects 0x{want:x}: "
                "the firmware image and this test disagree on the DCCM leg stimulus"
            )
        passes = f["passes"]
        assert passes >= 1, f"DCCM-LEG passes={passes}: the CPU store loop never ran"

        status, err = f["status"], f["err"]
        assert (status & _ST_DONE) and not (status & _ST_ERROR) and err == 0, (
            f"CHK-DCCM-NOERR FAIL: SRAM->DCCM copy ended with STATUS=0x{status:08x} "
            f"ERROR_CODE=0x{err:08x}; expected done set, error clear and ERROR_CODE=0"
        )
        self.logger.info(
            "CHK-DCCM-NOERR PASS: SRAM->DCCM copy done with no error "
            "(STATUS=0x%08x ERROR_CODE=0x%08x)",
            status,
            err,
        )

        dst = _dump_words(console, "DCCM-DST")
        dst_exp = [(_DCCM_SRC_SEED + i) & _MASK32 for i in range(_DCCM_DMA_WORDS)]
        assert len(dst) == _DCCM_DMA_WORDS, (
            f"CHK-DCCM-DMA-DATA FAIL: {len(dst)} DCCM-DST words dumped, expected {_DCCM_DMA_WORDS}"
        )
        bad = _first_mismatch(dst, dst_exp)
        assert not bad, (
            f"CHK-DCCM-DMA-DATA FAIL: DMA DCCM destination differs from its source, {bad}"
        )
        self.logger.info(
            "CHK-DCCM-DMA-DATA PASS: all %d DMA-written DCCM words equal the SRAM source",
            _DCCM_DMA_WORDS,
        )

        mismatches, busy_passes = f["mismatches"], f["busy_passes"]
        assert mismatches == 0, (
            f"CHK-DCCM-CPU-DATA FAIL: {mismatches} CPU DCCM word(s) read back different from "
            f"their pass's pattern over {passes} passes"
        )
        last = passes - 1
        cpu = _dump_words(console, "DCCM-CPU")
        cpu_exp = [(_DCCM_CPU_SEED + (last << 16) + i) & _MASK32 for i in range(_DCCM_CPU_WORDS)]
        assert len(cpu) == _DCCM_CPU_WORDS, (
            f"CHK-DCCM-CPU-DATA FAIL: {len(cpu)} DCCM-CPU words dumped, expected {_DCCM_CPU_WORDS}"
        )
        bad = _first_mismatch(cpu, cpu_exp)
        assert not bad, (
            f"CHK-DCCM-CPU-DATA FAIL: CPU DCCM region differs from the last-pass pattern "
            f"(pass {last}), {bad}"
        )
        self.logger.info(
            "CHK-DCCM-CPU-DATA PASS: every pass read back its %d words with 0 mismatches over "
            "%d passes, and the region holds the pass-%d pattern",
            _DCCM_CPU_WORDS,
            passes,
            last,
        )

        assert busy_passes >= 1, (
            f"CTRL-MISSING CTRL-DCCM-BUSY-PASS: none of the {passes} graded CPU passes began "
            "with DMA STATUS.BUSY set"
        )
        self.logger.info(
            "CTRL-DCCM-BUSY-PASS: %d of %d graded CPU passes began with DMA STATUS.BUSY set",
            busy_passes,
            passes,
        )

        ov = cocotb.top.dma_cpu_dccm_overlap_count_o.value
        assert ov.is_resolvable, f"dma_cpu_dccm_overlap_count_o is unresolvable ({ov})"
        ov_count = int(ov)
        assert ov_count > 0, (
            "CTRL-MISSING CTRL-DCCM-OVERLAP: the VeeR LSU never saw a DMA DCCM write "
            "request and a store-buffer DCCM write request in the same clock"
        )
        self.logger.info(
            "CTRL-DCCM-OVERLAP: DMA and store-buffer DCCM write requests coincided for %d clock(s)",
            ov_count,
        )
