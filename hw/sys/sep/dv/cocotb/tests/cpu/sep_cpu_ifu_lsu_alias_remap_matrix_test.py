# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""CPU LSU and IFU accesses at 0xD000_xxxx reach SEP SRAM at 0x1000_xxxx; others pass through.

OCAH provenance: ``sep_cpu_ifu_lsu_alias_remap_matrix_test`` checks IFU and
LSU local-alias remapping.

The test boots VeeR EL2 with the cpu_alias_remap firmware. The firmware programs the CPU-side
alias window base (SEP_LOCAL_BASE_ADDR = 0xD000_0000, its reset value) and checks the LSU and
IFU remap in hw/sys/sep/rtl/sep_cpu.sv (axi_window_remap): 0xD000_xxxx maps to SEP SRAM at
0x1000_xxxx and accesses outside the window pass through. The window is a fixed 768 MiB
(memory_map.adoc, SEP Local Alias) positioned by the base CSR only; REGION_SIZE does not size
it. The IFU check fetches and executes an instruction through the alias.

This must be a CPU-firmware test: the no_cpu AXI splice is after the remap, so a no_cpu driver
bypasses the remapper. Firmware-self-checking (fw/startup/crt0.s PASS/FAIL magic); no fuse data
is read, so the testlist entry uses +skip_fuse_sense.

The host grades the IFU AXI port of the core over the run:

* CHK-IFU-AXPROT: every PR-CPU-IFU read carries AxPROT ``0b101``
  (hw/sys/sep/doc/cpu.adoc, table sep-cpu-axprot-table), at least one read.
* CHK-IFU-SINGLE-BEAT: every PR-IFU read handshake inside the graded window
  carries AxLEN 0, at least one read (hw/sys/sep/doc/fabric.adoc:38-39, "The
  CPU masters and the DMA issue single-beat transactions only"). An X or Z
  AxLEN fails.

The graded window opens after the CPU is released and closes when the run
ends. Its points (sep_master_axprot_cg ifu_ar_101, cp_cpu_single_beat ifu_ar)
hold each IFU read handshake inside the window and sample only when
``ifu_remap_pass`` (``env/sep_fcov_gate.set_ifu_remap_pass``) rises: the leaf
writes 0 when it opens the window, and 1 after CHK-IFU-AXPROT and
CHK-IFU-SINGLE-BEAT passed, so a run whose check fails leaves both cells at 0.
An IFU AxPROT other than ``0b101`` samples an illegal bin at once.
"""

from __future__ import annotations

import os
from pathlib import Path

import cocotb
import pyuvm
from cocotb.triggers import ClockCycles, RisingEdge
from env.sep_boot_scoreboard import SepBootScoreboard
from env.sep_fabric_tap import AXPROT_IFU_AR, SepFabricTap, check_axprot, log_axprot
from env.sep_fcov_gate import close_graded_window, open_graded_window, set_ifu_remap_pass
from sep_base_test import sep_base_test
from sep_reg_meta import sym

_TEST = "sep_cpu_ifu_lsu_alias_remap_matrix_test"
_DV_ROOT = str(Path(__file__).resolve().parents[3])
_FW_DIR = os.path.join(_DV_ROOT, "fw", "build", "tests", "cpu_alias_remap_test")
_ITCM_HEX = os.path.join(_FW_DIR, "cpu_alias_remap_test.itcm.hex")
_DTCM_HEX = os.path.join(_FW_DIR, "cpu_alias_remap_test.dtcm.hex")

_ICCM_BASE = sym("SEP_ICCM_MEM_BASE_ADDR")
_MAX_RUN_CYCLES = 2_000_000
_NO_BOOT_CYCLES = 80_000
_PROGRESS_EVERY = 5_000
_BANNER = "SEP CPU IFU/LSU alias-remap test"
# AxLEN of a single-beat transaction: the AXI beat count minus one (AMBA AXI,
# AxLEN). hw/sys/sep/doc/fabric.adoc:38-39 states single-beat CPU transactions.
_SINGLE_BEAT_LEN = 0
# Clocks the leaf holds ifu_remap_pass at 1 before it writes 0.
_LABEL_CLK = 2


@pyuvm.test()
class sep_cpu_ifu_lsu_alias_remap_matrix_test(sep_base_test):
    """Alias-window LSU and IFU accesses reach SEP SRAM; other accesses pass through unchanged."""

    build_env = False
    # The leaf's own graded record; the base-class records do not count.
    required_evidence = ("CHK-IFU-AXPROT", "CHK-IFU-SINGLE-BEAT")

    def build_phase(self) -> None:
        super().build_phase()
        self.sb = SepBootScoreboard("sb", self)

    async def _open_window(self) -> None:
        # The CPU is released; every IFU read from here is graded stimulus.
        # ifu_remap_pass 0 starts the instance.
        open_graded_window(_TEST, self.logger)
        set_ifu_remap_pass(False, self.logger)
        self._ifu.start()

    async def _release(self) -> None:
        """Every check of the run passed: ifu_remap_pass 1 samples the held cells."""
        clk = cocotb.top.clk_i
        await RisingEdge(clk)
        set_ifu_remap_pass(True, self.logger)
        await ClockCycles(clk, _LABEL_CLK)
        set_ifu_remap_pass(False, self.logger)
        await RisingEdge(clk)

    async def run_scenario(self) -> None:
        self.sb.expected_line = _BANNER
        # CHK-IFU-AXPROT: the AxPROT the core drives on IFU fetches.
        cpu_ifu = SepFabricTap("PR-CPU-IFU").start()
        # CHK-IFU-SINGLE-BEAT: the AxLEN on the IFU AXI port, over the window.
        self._ifu = SepFabricTap("PR-IFU")
        try:
            await self.boot_firmware(
                self.sb,
                _ITCM_HEX,
                _DTCM_HEX,
                rst_vec=_ICCM_BASE >> 1,
                max_run_cycles=_MAX_RUN_CYCLES,
                no_boot_cycles=_NO_BOOT_CYCLES,
                progress_every=_PROGRESS_EVERY,
                after_bring_up_hook=self._open_window,
            )
        finally:
            close_graded_window(self.logger)
            await cpu_ifu.stop()
            await self._ifu.stop()
            log_axprot(self.logger, cpu_ifu, "ifu", "ar", "M")
        check_axprot(self.logger, "CHK-IFU-AXPROT", cpu_ifu, "ifu", "ar", AXPROT_IFU_AR)
        self._check_single_beat(self._ifu)
        await self._release()

    def _check_single_beat(self, ifu: SepFabricTap) -> None:
        """CHK-IFU-SINGLE-BEAT: AxLEN 0 on every PR-IFU read handshake, at least one."""
        expect = _SINGLE_BEAT_LEN
        beats = ifu.since(0, "ar")
        bad = [b for b in beats if b.len != expect]
        lens = "{" + ",".join(sorted({"X" if b.len is None else str(b.len) for b in beats})) + "}"
        line = (
            f"master=ifu tap=PR-IFU ch=ar count={len(beats)} len={lens} "
            f"mismatches={len(bad)} expect={expect}"
        )
        if not beats or bad:
            first = "; ".join(b.fmt() for b in bad[:4])
            msg = f"CHK-IFU-SINGLE-BEAT FAIL: {line} first_mismatch=[{first}] (fabric.adoc:38-39)"
            self.logger.error(msg)
            raise AssertionError(msg)
        self.logger.info("CHK-IFU-SINGLE-BEAT PASS: %s", line)
