# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SEP Secure-DMA vs CPU-LSU SRAM contention test (PyUVM).

The dma_cpu_contention firmware starts a long SRAM->SRAM Secure-DMA copy and, while it runs, a CPU
store loop into a disjoint SRAM region, so both masters arbitrate at the SRAM slave on the
SEP-local xbar with no testbench injection. The firmware checks overlap (STATUS BUSY and not DONE
mid-flight), DONE with no error, the STATUS RW1C clear, and bit-exact DMA and CPU data; start.S
emits PASS/FAIL magic that the boot scoreboard gates on.

The TB counts cycles where the CPU-LSU and DMA crossbar inputs both present an SRAM request on
the same address channel; a positive count is the contention proof, which DMA BUSY alone is not.

No fuse data is read, so the testlist entry uses ``+skip_fuse_sense``.
"""

from __future__ import annotations

import os
from pathlib import Path

import cocotb
import pyuvm
from env.sep_boot_scoreboard import SepBootScoreboard
from sep_base_test import sep_base_test
from sep_reg_meta import sym

_DV_ROOT = str(Path(__file__).resolve().parents[3])
_FW_DIR = os.path.join(_DV_ROOT, "fw", "build", "tests", "dma_cpu_contention_test")
_ITCM_HEX = os.path.join(_FW_DIR, "dma_cpu_contention_test.itcm.hex")
_DTCM_HEX = os.path.join(_FW_DIR, "dma_cpu_contention_test.dtcm.hex")

_ICCM_BASE = sym("SEP_ICCM_MEM_BASE_ADDR")
# 2 KiB SRAM->SRAM copy + a 256 B CPU loop + two full-region verifies; the run
# loop early-exits on fw_done, so this is an upper bound.
_MAX_RUN_CYCLES = 4_000_000
_NO_BOOT_CYCLES = 80_000
_PROGRESS_EVERY = 5_000
# The clauses of the firmware's single verdict line, one per card row. A stale image
# that dropped a leg loses its clause, which fails here rather than at the PASS magic.
_VERDICT_CLAUSES = (
    (
        "overlap STATUS=0x00000001",
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


@pyuvm.test()
class sep_dma_cpu_contention_test(sep_base_test):
    """Boot VeeR EL2 and run the Secure-DMA / CPU-LSU SRAM contention firmware."""

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
        # emit the record the VPLAN card names for it.
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
