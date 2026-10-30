# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""The Secure-DMA zero fill clears SEP SRAM, DCCM and ICCM, and sub-word TCM fills are rejected.

The dma_zero_test firmware drives the zero fill (CONTROL.OPCODE 4) into SEP SRAM at 4-byte and
1-byte width, into a DCCM buffer and into ICCM, the last two through the core's DMA slave port,
and checks the cleared bytes and their neighbours. ICCM is read back through a DMA copy to SRAM.
A 2-byte-wide fill into ICCM must end in BUS_ERROR with the exclusive host-path error, because the
core accepts only whole words there (hw/sys/sep/doc/dma.adoc:118-121). So must a 4-byte-wide fill of
4n + 2 bytes into ICCM and into DCCM, whose last write covers only the remaining bytes
(dma.adoc:113-114), and a 2-byte-wide fill into DCCM; the words past TOTAL_DATA_SIZE keep their
pattern (dma.adoc:115). The words such a fill targets have no stated value and are logged on the
firmware's OBS-ZERO-TCM-SPAN lines only. The leaf draws n for each 4n + 2 fill from the run seed
and patches it into the firmware parameter block; each PASS line echoes its n. The firmware
returns its error count and fw/startup/crt0.s emits PASS/FAIL magic that the boot scoreboard gates
on.

The host gates on each checker's PASS line, so an image without a leg fails here rather than at
the PASS magic. The core's DMA slave port exists only on the full-CPU target, which is why the
TCM legs live in firmware and not in the no_cpu ``sep_dma_zero_fill_rand_test``.

FCOV: ``sep_dma_zero_cg.cp_tcm_outcome`` samples each cell at the DONE or ERROR rise of a TCM zero
fill, before the firmware has graded that fill, so the sampler holds the cell and samples it only
when the pass label ``dma_zero_tcm_pass`` (``env/sep_fcov_gate.set_dma_zero_tcm_pass``) rises. The
leaf writes the label 0 before the boot and the cell mask after the firmware completed with PASS and
every console check passed.

No fuse data is read, so the testlist entry uses ``+skip_fuse_sense``.
"""

from __future__ import annotations

import os
from pathlib import Path

import cocotb
import pyuvm
from cocotb.triggers import ClockCycles, RisingEdge
from env.sep_boot_scoreboard import SepBootScoreboard
from env.sep_dtcm_param_patch import patch_param_block
from env.sep_fcov_gate import (
    DMA_ZERO_TCM_PASS_ALL,
    close_graded_window,
    open_graded_window,
    set_dma_zero_tcm_pass,
)
from env.sep_seeded_rng import SepSeededRng
from sep_base_test import sep_base_test
from sep_reg_meta import sym

_DV_ROOT = str(Path(__file__).resolve().parents[3])
_FW_DIR = os.path.join(_DV_ROOT, "fw", "build", "tests", "dma_zero_test")
_ITCM_HEX = os.path.join(_FW_DIR, "dma_zero_test.itcm.hex")
_DTCM_HEX = os.path.join(_FW_DIR, "dma_zero_test.dtcm.hex")

_ICCM_BASE = sym("SEP_ICCM_MEM_BASE_ADDR")
# Twelve short fills and four 72-byte copies; the run loop early-exits on fw_done, so this is an
# upper bound.
_MAX_RUN_CYCLES = 6_000_000
_NO_BOOT_CYCLES = 80_000
_PROGRESS_EVERY = 5_000
_BANNER = "SEP DMA zero fill test"
# g_zero_params in fw/tests/dma_zero_test/dma_zero_test.c: the magic, then n of the ICCM and of the
# DCCM 4n + 2 fill.
_PARAM_MAGIC = 0xDA2E40C5
# The largest n the firmware accepts: its buffers hold NWORDS + 2 words (dma_zero_test.c), n + 1
# of them inside the fill and at least one past it. The firmware FAILs an n outside [1, NWORDS].
_N_MAX = 16
_CHECKS = (
    ("PASS: CHK-ZERO-SRAM ", "CHK-ZERO-SRAM", "the SRAM word and byte fills"),
    ("PASS: CHK-ZERO-DCCM ", "CHK-ZERO-DCCM", "the DCCM fill through the core's DMA port"),
    ("PASS: CHK-ZERO-ICCM ", "CHK-ZERO-ICCM", "the ICCM fill through the core's DMA port"),
    (
        "PASS: CHK-ZERO-TCM-NARROW ",
        "CHK-ZERO-TCM-NARROW",
        "the rejected 2-byte-wide ICCM fill and its recovery",
    ),
)
# 4n + 2 fills: the PASS line must also carry the patched n.
_CHECKS_N = (
    ("CHK-ZERO-ICCM-4N2", "n_iccm", "the rejected 4n + 2 ICCM fill, its guards and its recovery"),
    ("CHK-ZERO-DCCM-4N2", "n_dccm", "the rejected 4n + 2 DCCM fill, its guards and its recovery"),
)
_CHECK_DCCM_NARROW = (
    "PASS: CHK-ZERO-DCCM-NARROW ",
    "CHK-ZERO-DCCM-NARROW",
    "the rejected 2-byte-wide DCCM fill, its guards and its recovery",
)


def _draw_n(seed: int) -> dict[str, int]:
    """n of each 4n + 2 fill, a pure function of the seed."""
    rng = SepSeededRng(seed)
    return {"n_iccm": rng.randrange(1, _N_MAX + 1), "n_dccm": rng.randrange(1, _N_MAX + 1)}


@pyuvm.test()
class sep_dma_zero_test(sep_base_test):
    """Zero fills clear SRAM, DCCM and ICCM; sub-word TCM fills end in BUS_ERROR."""

    build_env = False
    required_evidence = (
        tuple(chk for _, chk, _ in _CHECKS)
        + tuple(chk for chk, _, _ in _CHECKS_N)
        + (_CHECK_DCCM_NARROW[1],)
    )

    def build_phase(self) -> None:
        super().build_phase()
        self.sb = SepBootScoreboard("sb", self)

    def _stage_dtcm(self) -> tuple[str, dict[str, int]]:
        seed = self.random_seed()
        n = _draw_n(seed)
        patched = os.path.join(os.getcwd(), "sep_dtcm_dma_zero.hex")
        patch_param_block(
            _DTCM_HEX, patched, _PARAM_MAGIC, [_PARAM_MAGIC, n["n_iccm"], n["n_dccm"]]
        )
        self.logger.info(
            "DMA zero RANDCFG seed=%d n_iccm=%d n_dccm=%d", seed, n["n_iccm"], n["n_dccm"]
        )
        return patched, n

    def _fail(self, msg: str) -> None:
        """Drop the held cells and fail the leaf (the window is already closed)."""
        close_graded_window(self.logger)
        set_dma_zero_tcm_pass(0, self.logger)
        raise AssertionError(msg)

    async def run_scenario(self) -> None:
        dut = cocotb.top
        # Override the boot scoreboard's expected banner here (after its own
        # build_phase, which resets it to the hello_world default).
        self.sb.expected_line = _BANNER
        dtcm, n = self._stage_dtcm()
        set_dma_zero_tcm_pass(0, self.logger)

        async def _open_window() -> None:
            # The CPU is released; every fill the firmware runs from here is
            # the graded stimulus of this leaf.
            open_graded_window("sep_dma_zero_test", self.logger)

        try:
            await self.boot_firmware(
                self.sb,
                _ITCM_HEX,
                dtcm,
                rst_vec=_ICCM_BASE >> 1,
                max_run_cycles=_MAX_RUN_CYCLES,
                no_boot_cycles=_NO_BOOT_CYCLES,
                progress_every=_PROGRESS_EVERY,
                after_bring_up_hook=_open_window,
            )
        finally:
            close_graded_window(self.logger)
        console = self.sb.console_text()
        lines = console.splitlines()
        for ln in lines:
            if ln.startswith("OBS-"):
                self.logger.info("%s LOG (firmware)", ln)
        self.logger.info(
            "OBS-ZERO-TCM-MISALIGN LOG not_run: a 4-byte-wide fill to a TCM destination that is "
            "not 4-byte aligned is not run; hw/sys/sep/doc/dma.adoc:118-121 states BUS_ERROR "
            "for it, and vendor/lowRISC/opentitan/overlay/regs/secure_dma/regs/secure_dma.rdl:91 "
            "asks DST_ADDR_LO aligned to the transfer width, with no stated error class"
        )
        needles = list(_CHECKS)
        for chk, key, what in _CHECKS_N:
            needles.append((f"PASS: {chk} n=0x{n[key]:08x} ", chk, f"{what} (n={n[key]})"))
        needles.append(_CHECK_DCCM_NARROW)
        for needle, chk, what in needles:
            if not any(ln.startswith(needle) for ln in lines):
                self._fail(
                    f"{chk} FAIL: firmware console has no {needle.strip()!r} line, so {what} did "
                    f"not run or did not pass. Console was:\n{console}"
                )
            self.logger.info("%s PASS: firmware reported %s", chk, what)
        if not (self.sb.fw_done and self.sb.fw_pass):
            # The boot scoreboard grades the verdict in check_phase; the held
            # cells stay unreleased here.
            self._fail(
                f"firmware did not complete with PASS: fw_done={self.sb.fw_done} "
                f"fw_pass={self.sb.fw_pass}"
            )
        # Every check of the run passed: release the held cp_tcm_outcome cells.
        await RisingEdge(dut.clk_i)
        set_dma_zero_tcm_pass(DMA_ZERO_TCM_PASS_ALL, self.logger)
        await ClockCycles(dut.clk_i, 2)
        set_dma_zero_tcm_pass(0, self.logger)
        await RisingEdge(dut.clk_i)
