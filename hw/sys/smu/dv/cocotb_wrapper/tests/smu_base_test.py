# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Shared PyUVM base test for the production SMU wrapper OSS environment."""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles, Timer
from pyuvm import ConfigDB, uvm_test

_COCOTB_ROOT = Path(__file__).resolve().parents[1]
_DV_ROOT = Path(__file__).resolve().parents[2]
_OSS_HW_ROOT = Path(__file__).resolve().parents[5]
for _path in (
    _COCOTB_ROOT,
    _DV_ROOT / "common",
    _OSS_HW_ROOT / "common" / "dv" / "vip",
):
    _path_text = str(_path)
    if _path_text not in sys.path:
        sys.path.insert(0, _path_text)

from env.smu_env_cfg import SmuEnvCfg  # noqa: E402
from env.smu_sep_cpu_trace_monitor import SmuSepCpuTraceMonitor  # noqa: E402
from ocah_axi_vip import OcahAxiSlaveAgent  # noqa: E402
from seq_lib.sep_fw_common import load_syms  # noqa: E402
from smu_dv_env.smu_env import SmuEnv  # noqa: E402


class smu_base_test(uvm_test):
    """Clock/reset bring-up and scenario hook shared by every SMU OSS test."""

    #: Set True by a leaf migrated from the bare-smu catalog to get
    #: self.env.scoreboard, the shared SmuEnv the bare tests score against.
    use_shared_env = False

    @staticmethod
    def random_seed() -> int:
        return int(os.environ.get("RANDOM_SEED", "1"), 0)

    @staticmethod
    def read_int(signal, name: str, *, allow_xz: bool = False) -> int:
        value = signal.value
        if hasattr(value, "is_resolvable") and not value.is_resolvable:
            if allow_xz:
                return 0
            raise AssertionError(f"{name} contains X/Z: {value}")
        return int(value)

    async def arm_async_resets(self) -> None:
        """Create a falling TRST edge so IC_RESET TDR reset-values load.

        Same contract as the bare tb_top.sv base test: Verilator two-state
        powers jtag_trst up at 0, which is not a falling edge, and the IC_RESET
        reset_hold flop resets only on TRST with RESET_VAL=1. Left at 0 it
        keeps the override asserted and SMC cold reset never releases. This
        bring-up does the same pre-drive inline; the method exists so a
        migrated leaf that re-arms mid-test finds it here too.
        """
        dut = cocotb.top
        dut.powergood_i.value = 1
        dut.rst_cold_ni.value = 1
        dut.jtag_tck.value = 0
        dut.jtag_tms.value = 1
        dut.jtag_trst.value = 1
        dut.jtag_tdi.value = 0
        await self.jtag_tap_reset()
        await ClockCycles(dut.clk_ref_i, 2)

    async def wait_signal_high(self, signal, clk, *, timeout_cycles: int, name: str) -> int:
        """Block until `signal` reads 1, and say how long it took.

        Mirrors seq_lib.smu_axi_helpers.wait_signal_high in the bare-smu tree.
        Kept here rather than imported so the base test does not depend on an
        AXI helper for a generic wait.
        """
        for cycle in range(timeout_cycles):
            if self.read_int(signal, name, allow_xz=True):
                return cycle
            await ClockCycles(clk, 1)
        raise AssertionError(f"{name} still low after {timeout_cycles} cycles")

    def build_phase(self) -> None:
        self.cfg = SmuEnvCfg("cfg")
        self.cfg.randomize_timing(self.random_seed())
        ConfigDB().set(None, "*", "cfg", self.cfg)
        # Built ahead of any scoreboard so the ConfigDB entry exists when a
        # concrete test's build_phase looks it up; idles unless +sep_itcm_hex
        # names a SEP image.
        self.sep_trace_mon = SmuSepCpuTraceMonitor("sep_trace_mon", self)
        ConfigDB().set(None, "*", "sep_trace_mon", self.sep_trace_mon)
        self._attach_sep_symbols()
        # The same PyUVM env the bare-smu tests score against, so a leaf
        # migrated onto this DUT keeps its self.env.scoreboard checks instead
        # of being rewritten. Opt-in, not automatic: SmuScoreboard refuses a
        # run that registered no checks ("zero checks executed - refusing
        # vacuous PASS"), which is right for a leaf that scores through it and
        # wrong for the wrapper leaves that carry their own scoreboard.
        if self.use_shared_env:
            self.env = SmuEnv("env", self)
        self.logger.info(
            "SMU seed=%d clocks(ref/smu/periph/wdt)=%d/%d/%d/%dns "
            "reset(powergood/hold/post)=%d/%d/%d cycles",
            self.random_seed(),
            self.cfg.ref_clk_period_ns,
            self.cfg.smu_clk_period_ns,
            self.cfg.periph_clk_period_ns,
            self.cfg.sep_wdt_clk_period_ns,
            self.cfg.powergood_delay_cycles,
            self.cfg.reset_hold_cycles,
            self.cfg.post_reset_cycles,
        )

    def _attach_sep_symbols(self) -> None:
        """Feed the staged nm listing of the SEP image to the trace monitor.

        ``+sep_sym`` names it explicitly; otherwise the ``+sep_itcm_hex`` stem
        selects ``<stem>.tcm.sym`` (SEP firmware engine) or ``<stem>.sym``
        (``fw/build_firmware.py``) in the simulator cwd. A missing listing
        degrades to numeric PCs and never fails the test.
        """
        explicit = cocotb.plusargs.get("sep_sym")
        itcm = cocotb.plusargs.get("sep_itcm_hex")
        if explicit is not None:
            candidates = [str(explicit)]
        elif itcm is not None:
            stem = Path(str(itcm)).name.split(".", 1)[0]
            candidates = [f"{stem}.tcm.sym", f"{stem}.sym"]
        else:
            return
        for path in candidates:
            syms = load_syms(path, include_weak=True)
            if syms:
                self.sep_trace_mon.attach_symbols(syms, path)
                return
        self.logger.info("no SEP symbol listing among %s; trace PCs stay numeric", candidates)

    def start_clocks(self) -> None:
        dut = cocotb.top
        cocotb.start_soon(Clock(dut.clk_ref_i, self.cfg.ref_clk_period_ns, units="ns").start())
        cocotb.start_soon(Clock(dut.clk_smu_i, self.cfg.smu_clk_period_ns, units="ns").start())
        cocotb.start_soon(
            Clock(dut.clk_periph_i, self.cfg.periph_clk_period_ns, units="ns").start()
        )
        cocotb.start_soon(
            Clock(dut.clk_sep_wdt_i, self.cfg.sep_wdt_clk_period_ns, units="ns").start()
        )
        # ESRC ring-oscillator sample clock, matching hw/sys/sep/dv's 3 ns. The
        # entropy source samples its noise lanes on this clock, so any test that
        # exercises entropy needs it running; with it static the source produces
        # nothing however the stack is programmed.
        #
        # Started only under +esrc_noise_force, which is not a convenience: this
        # clock is 3 ns against clk_smu's 10 ns, so leaving it on adds edges to
        # every SEP=1 run, and it is useless on its own anyway -- the ring
        # oscillators do not self-oscillate under Verilator, so a sample clock
        # with no driven noise samples nothing. The two belong together, and both
        # entropy-consuming sequences already assert the plusarg is present.
        if cocotb.plusargs.get("esrc_noise_force") is not None:
            cocotb.start_soon(
                Clock(
                    dut.entropy_rosc_sample_clk_i,
                    self.cfg.entropy_clk_period_ns,
                    units="ns",
                ).start()
            )

    async def jtag_tap_reset(self, pulses: int = 8) -> None:
        """Walk the primary TAP into Test-Logic-Reset with TMS high.

        The DTP IC_RESET TDR powers up in a state that can assert SMC cold and
        fuse overrides under Verilator two-state and VCS X-init; left alone it
        holds the SEP in reset and no CPU ever fetches. Clearing it needs real
        TCK edges with TMS high, which is why every wrapper test does this even
        when it never touches JTAG again.
        """
        dut = cocotb.top
        dut.jtag_tms.value = 1
        dut.jtag_tdi.value = 0
        for _ in range(pulses):
            dut.jtag_tck.value = 0
            await Timer(5, unit="ns")
            dut.jtag_tck.value = 1
            await Timer(5, unit="ns")
        dut.jtag_tck.value = 0
        await Timer(5, unit="ns")

    async def bring_up(self) -> None:
        """Apply the production wrapper power-good and cold-reset sequence."""
        dut = cocotb.top
        # The outbound SMN responder exists before the first clock edge so the
        # boundary's READY signals are driven from time zero.
        self.cfg.axi_out_mem = OcahAxiSlaveAgent(
            self.cfg.axi_out_geometry.bus(dut.u_axi_out_if),
            dut.clk_smu_i,
            dut.rst_cold_n_o,
            reset_active_level=False,
            size=self.cfg.axi_out_mem_size,
            name="smu_axi_out",
        ).sequence
        # Verilator two-state simulation initializes every signal to 0, so a
        # reset input that starts low never produces the falling edge that
        # fires async-reset flops. Flops with nonzero reset values (e.g. the
        # DTP IC_RESET TDR default of "override disabled") would keep their
        # power-up zeros and hold SEP in reset. Pre-drive the resets high for
        # two cycles so the subsequent assertion is a real falling edge, as
        # the X->0 transition would be in a four-state simulator.
        self.logger.info("Step 0: pre-drive resets high to arm async resets")
        dut.powergood_i.value = 1
        dut.rst_cold_ni.value = 1
        # This pin used to be tied to 1'b1 inside the TB. It is a driven input
        # now, so that smu_ext_boot_seq_gate_test can hold it low, and the
        # default has to be restored here or every leaf that expects the boot
        # sequence complete sees it deasserted. The bare bring-up does the same.
        dut.ext_boot_seq_done_i.value = 1
        # TRST follows cold reset, as it did when this TB tied trst_n to
        # rst_cold_ni internally.
        dut.jtag_tck.value = 0
        dut.jtag_tms.value = 1
        dut.jtag_trst.value = 1
        dut.jtag_tdi.value = 0
        # ESRC raw-noise stimulus starts quiet; a test that wants entropy drives
        # it (see SmuEsrcNoiseDriver).
        if hasattr(dut, "esrc_noise_ext_i"):
            dut.esrc_noise_ext_i.value = 0
        self.start_clocks()
        await self.jtag_tap_reset()
        await ClockCycles(dut.clk_ref_i, 2)

        self.logger.info("Step 1: assert power-good low and cold reset")
        dut.powergood_i.value = 0
        dut.rst_cold_ni.value = 0
        dut.jtag_trst.value = 0
        await ClockCycles(dut.clk_ref_i, self.cfg.powergood_delay_cycles)
        self.pre_release_sep_reset = self.read_int(
            dut.sep_reset_n_o, "sep_reset_n_o during cold reset"
        )
        self.pre_release_sep_fuse = self.read_int(
            dut.sep_fuse_sense_done_o,
            "sep_fuse_sense_done_o during cold reset",
        )
        self.logger.info(
            "Reset-state SEP evidence: reset_n=%d fuse_done=%d",
            self.pre_release_sep_reset,
            self.pre_release_sep_fuse,
        )

        self.logger.info("Step 2: assert power-good while retaining cold reset")
        dut.powergood_i.value = 1
        await ClockCycles(dut.clk_ref_i, self.cfg.reset_hold_cycles)

        self.logger.info("Step 3: release cold reset and wait for resolved outputs")
        dut.rst_cold_ni.value = 1
        dut.jtag_trst.value = 1
        # Reload the TDR defaults with a real TRST->TCK sequence before any
        # observer samples fuse/primary reset.
        await self.jtag_tap_reset(16)
        # Extra settle so the TB JTAG TCK reload (after TRST rise) can clear
        # IC_RESET TDR overrides before observers sample fuse/primary reset.
        await ClockCycles(dut.clk_ref_i, self.cfg.post_reset_cycles + 40)
        self.post_release_sep_reset = self.read_int(
            dut.sep_reset_n_o, "sep_reset_n_o after cold reset"
        )
        self.post_release_sep_fuse = self.read_int(
            dut.sep_fuse_sense_done_o,
            "sep_fuse_sense_done_o after cold reset",
        )
        self.logger.info(
            "Post-reset SEP evidence: reset_n=%d fuse_done=%d",
            self.post_release_sep_reset,
            self.post_release_sep_fuse,
        )

        # post_reset_cycles is a settle, not a release. The SMC primary reset
        # runs a 32-cycle cold deglitch and then a 255-cycle extender on
        # clk_ref, so it is still asserted when that settle expires -- an AXI
        # read issued at this point gets no response and times out. The bare
        # tb_top.sv bring-up has always blocked on these two; this one now does
        # too, so a test does not have to know.
        cold_cycles = await self.wait_signal_high(
            dut.rst_cold_n_o, dut.clk_ref_i, timeout_cycles=2000, name="rst_cold_n_o"
        )
        smc_cycles = await self.wait_signal_high(
            dut.rst_primary_smc_clk_n_o,
            dut.clk_smu_i,
            timeout_cycles=2000,
            name="rst_primary_smc_clk_n_o",
        )
        self.logger.info(
            "Primary resets released: rst_cold_n_o after %d clk_ref, "
            "rst_primary_smc_clk_n_o after %d clk_smu",
            cold_cycles,
            smc_cycles,
        )
        self.cfg.reset_done.set()

    async def run_scenario(self) -> None:
        raise NotImplementedError

    async def run_phase(self) -> None:
        self.raise_objection()
        await self.bring_up()
        try:
            await self.run_scenario()
        except Exception:  # noqa: BLE001 -- re-raised once the SEP state is in the log
            self.sep_trace_mon.dump_diagnostics(logging.ERROR)
            raise
        self.drop_objection()
