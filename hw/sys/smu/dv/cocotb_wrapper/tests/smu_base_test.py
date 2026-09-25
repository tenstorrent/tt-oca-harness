# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Shared PyUVM base test for the production SMU wrapper OSS environment."""

from __future__ import annotations

import logging
import os
import re
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
    _DV_ROOT / "cocotb",
    _OSS_HW_ROOT / "common" / "dv" / "vip",
):
    _path_text = str(_path)
    if _path_text not in sys.path:
        sys.path.insert(0, _path_text)

from env.smu_env import SmuEnv  # noqa: E402
from env.smu_env_cfg import SmuEnvCfg, check_pll_clock_periods  # noqa: E402
from env.smu_evidence_map import TEST_EVIDENCE  # noqa: E402
from env.smu_sep_cpu_trace_monitor import SmuSepCpuTraceMonitor  # noqa: E402
from ocah_axi_vip import OcahAxiSlaveAgent  # noqa: E402
from seq_lib.sep_fw_common import load_syms  # noqa: E402


class _EvidenceRecorder:
    """Collect every ``EVIDENCE: <TOKEN>`` line a run logs, whichever logger emits it.

    The wrapper-native leaves stamp their verdict tokens from three places: a
    sequence's own logger after its ``assert not errors``, a boot scoreboard
    after its verdict, and the leaf itself. Those are pyuvm loggers, which do
    not propagate to the root handler, so a filter on any one of them would
    miss part of the run. The log-record factory sees every record regardless
    of logger, and reading the token from the record keeps the log line the
    single source of what was proved.

    Only a token at the start of the message counts: prose that quotes a token
    is not an emission. Both spellings ``EVIDENCE: T`` and ``EVIDENCE:T`` are
    read, so the recorder matches what the evidence map and its consumers grep.
    """

    _TOKEN = re.compile(r"^\s*EVIDENCE:\s*(\S+)")

    def __init__(self) -> None:
        self.seen: set[str] = set()
        self._previous_factory = logging.getLogRecordFactory()

    def install(self) -> None:
        logging.setLogRecordFactory(self._factory)

    def _factory(self, *args, **kwargs) -> logging.LogRecord:
        record = self._previous_factory(*args, **kwargs)
        try:
            message = record.getMessage()
        except Exception:  # a broken format string is the caller's failure, not ours
            return record
        match = self._TOKEN.match(message)
        if match:
            self.seen.add(match.group(1))
        return record


#: Wrapper-native leaves allowed to finish with no declared evidence token,
#: each with the reason. Mirrors ``UNMAPPED_TESTS`` for the shared-env leaves:
#: a leaf that declares nothing and is not listed here fails its run. Empty
#: means every wrapper-native leaf names at least one token it must log.
NO_EVIDENCE_LEAVES: dict[str, str] = {}


class smu_base_test(uvm_test):
    """Clock/reset bring-up and scenario hook shared by every SMU OSS test."""

    #: Set True by a leaf that scores through self.env.scoreboard, the
    #: SmuEnv under cocotb/env.
    use_shared_env = False

    #: Evidence tokens a wrapper-native leaf (use_shared_env=False) must log
    #: through an ``EVIDENCE: <TOKEN>`` line before it may pass, in addition to
    #: the tokens its sequence declares through ``declare_evidence`` and the
    #: leaf's ``TEST_EVIDENCE`` rows. Set by a leaf whose verdict lives outside
    #: a sequence ``EVIDENCE`` tuple -- a boot scoreboard or the leaf itself.
    required_evidence: tuple[str, ...] = ()

    #: Minimum jtag_period_ns / smu_clk_period_ns this leaf will run at, or
    #: None to take whatever randomize_timing drew for the JTAG period.
    #:
    #: Only the SMC-fabric SERIES-write leaves set it: an SMC JTAG2AXI SERIES
    #: write returns zeros or parks in BUSY whenever that ratio is under 4. The
    #: clamp is per leaf; randomize_timing itself is not clamped.
    min_jtag_smu_ratio: float | None = None

    #: Set by a leaf whose checks compare clk_ref_i against clk_smu_i at the
    #: boundary. With +pll_sys_period_ns=10 both domains run at the reference
    #: period, and an equality observation cannot then tell one clock from the
    #: other, so such a leaf cannot prove separation on a correct design and
    #: refuses that period instead of reporting a false failure.
    require_distinct_ref_smu: bool = False

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

        Verilator two-state
        powers jtag_trst up at 0, which is not a falling edge, and the IC_RESET
        reset_hold flop resets only on TRST with RESET_VAL=1. Left at 0 it
        keeps the override asserted and SMC cold reset never releases.
        bring_up() performs the same pre-drive inline; this method serves a
        leaf that re-arms mid-test.
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

        Mirrors seq_lib.smu_axi_helpers.wait_signal_high; the base test carries
        no dependency on the AXI helpers.
        """
        for cycle in range(timeout_cycles):
            if self.read_int(signal, name, allow_xz=True):
                return cycle
            await ClockCycles(clk, 1)
        raise AssertionError(f"{name} still low after {timeout_cycles} cycles")

    def build_phase(self) -> None:
        self._evidence = _EvidenceRecorder()
        self._evidence.install()
        self._declared_evidence: list[str] = []
        self.cfg = SmuEnvCfg("cfg")
        self.cfg.resolve_pll_timing()
        self.cfg.randomize_timing(self.random_seed())
        if self.min_jtag_smu_ratio is not None:
            needed = self.min_jtag_smu_ratio * self.cfg.smu_clk_period_ns
            if self.cfg.jtag_period_ns < needed:
                raised = int(-(-needed // 1))  # ceil, keeping an integer period
                # WARNING, not INFO: the clamp is visible in every affected run's log.
                self.logger.warning(
                    "jtag_period_ns %s -> %d to hold jtag/smu >= %s "
                    "(SMC JTAG2AXI SERIES-write clamp)",
                    self.cfg.jtag_period_ns,
                    raised,
                    self.min_jtag_smu_ratio,
                )
                self.cfg.jtag_period_ns = raised
        if self.require_distinct_ref_smu and self.cfg.ref_clk_period_ns == (
            self.cfg.smu_clk_period_ns
        ):
            raise AssertionError(
                f"{type(self).__name__} compares clk_ref_i against clk_smu_i and needs "
                f"distinct periods; +pll_sys_period_ns={self.cfg.smu_clk_period_ns} runs "
                f"both at {self.cfg.ref_clk_period_ns} ns"
            )
        ConfigDB().set(None, "*", "cfg", self.cfg)
        # Built ahead of any scoreboard so the ConfigDB entry exists when a
        # concrete test's build_phase looks it up; idles unless +sep_itcm_hex
        # names a SEP image.
        self.sep_trace_mon = SmuSepCpuTraceMonitor("sep_trace_mon", self)
        ConfigDB().set(None, "*", "sep_trace_mon", self.sep_trace_mon)
        self._attach_sep_symbols()
        # The PyUVM env under cocotb/env. Opt-in: SmuScoreboard
        # refuses a run that registered no checks ("zero checks executed -
        # refusing vacuous PASS"), and the wrapper-native leaves carry their own
        # scoreboard.
        if self.use_shared_env:
            self.env = SmuEnv("env", self)
        self.logger.info(
            "SMU seed=%d clocks(ref/smu/periph/wdt)=%s/%s/%s/%sns "
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

    #: TB inputs no leaf drives unless it exercises that interface. Verilator
    #: two-state reads an undriven input as 0, but this config also lists vcs
    #: and xcelium, where it is X -- and an X on AxPROT, on an AXI handshake
    #: valid or ready (the fabric's clock-gate snoop and hang detector fold
    #: those into their known-value assertions), or on a cross-trigger request
    #: reaches the DUT. Driven here so the idle value is the same on every
    #: simulator; a leaf that wants them takes them over afterwards.
    IDLE_INPUTS = (
        "ext_in_awvalid",
        "ext_in_wvalid",
        "ext_in_arvalid",
        "ext_in_bready",
        "ext_in_rready",
        "ext_in_awlock",
        "ext_in_awcache",
        "ext_in_awprot",
        "ext_in_awqos",
        "ext_in_awregion",
        "ext_in_arlock",
        "ext_in_arcache",
        "ext_in_arprot",
        "ext_in_arqos",
        "ext_in_arregion",
        "ext_in_wuser",
        "gpio_boot_stall_drive_i",
        "xtrig_ctm_dst_req",
        "xtrig_ctm_src_ack",
        "xtrig_clk_stop_req",
        "tb_telemetry_atdata",
        "tb_telemetry_atid",
        "tb_telemetry_atvalid",
        "tb_telemetry_afready",
        "tb_smc_ext_interrupts",
        "tb_smc_ndmreset_request",
        "tb_cfg_flr_pf_active",
        "tb_mem_repair_abort",
        "tb_mbist_abort",
        "tb_mem_repair_hold",
        "tb_mbist_hold",
        "tb_ss_reset_incomplete",
        "tb_chiplet_secondary",
        "tb_cool_reset_pin",
        "tb_secure_tm_req",
        "tb_gpio0_drive_en",
        "tb_gpio0_drive_val",
        "tb_gpio_drive_en",
        "tb_gpio_drive_val",
        "tb_xtrig_ctp_req_out_din",
        "tb_xtrig_ctp_req_in_din",
        "tb_xtrig_ctp_ack_in_din",
    )

    def drive_idle_inputs(self) -> None:
        dut = cocotb.top
        for name in self.IDLE_INPUTS:
            handle = getattr(dut, name, None)
            if handle is not None:
                handle.value = 0

    def start_clocks(self) -> None:
        dut = cocotb.top
        cocotb.start_soon(Clock(dut.clk_ref_i, self.cfg.ref_clk_period_ns, unit="ns").start())
        cocotb.start_soon(Clock(dut.clk_smu_i, self.cfg.smu_clk_period_ns, unit="ns").start())
        cocotb.start_soon(Clock(dut.clk_periph_i, self.cfg.periph_clk_period_ns, unit="ns").start())
        cocotb.start_soon(
            Clock(dut.clk_sep_wdt_i, self.cfg.sep_wdt_clk_period_ns, unit="ns").start()
        )
        # ESRC ring-oscillator sample clock, matching hw/sys/sep/dv's 3 ns. The
        # entropy source samples its noise lanes on this clock, so any test that
        # exercises entropy needs it running; with it static the source produces
        # nothing however the stack is programmed.
        #
        # Started only under +esrc_noise_force: the ring oscillators do not
        # self-oscillate under Verilator, so the sample clock samples nothing
        # without driven noise, and at 3 ns against clk_smu's 10 ns it adds
        # edges to every SEP=1 run. The entropy-consuming sequences assert the
        # plusarg is present.
        if cocotb.plusargs.get("esrc_noise_force") is not None:
            cocotb.start_soon(
                Clock(
                    dut.entropy_rosc_sample_clk_i,
                    self.cfg.entropy_clk_period_ns,
                    unit="ns",
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
        # A driven input, so smu_ext_boot_seq_gate_test can hold it low; every
        # other leaf needs the asserted default set here or it sees the boot
        # sequence incomplete.
        dut.ext_boot_seq_done_i.value = 1
        # TRST follows cold reset.
        dut.jtag_tck.value = 0
        dut.jtag_tms.value = 1
        dut.jtag_trst.value = 1
        dut.jtag_tdi.value = 0
        # ESRC raw-noise stimulus starts quiet; a test that wants entropy drives
        # it (see SmuEsrcNoiseDriver).
        if hasattr(dut, "esrc_noise_ext_i"):
            dut.esrc_noise_ext_i.value = 0
        self.drive_idle_inputs()
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
        # read issued at this point gets no response and times out. Bring-up
        # blocks on both releases so a test does not have to.
        cold_cycles = await self.wait_signal_high(
            dut.rst_cold_n_o, dut.clk_ref_i, timeout_cycles=2000, name="rst_cold_n_o"
        )
        smc_cycles = await self.wait_signal_high(
            dut.rst_primary_smc_clk_n_o,
            dut.clk_smu_i,
            timeout_cycles=2000,
            name="rst_primary_smc_clk_n_o",
        )
        # The peripheral domain is a third primary reset and has to be waited
        # on for the same reason as the other two: its deglitch chain runs on
        # its own clock and finishes on its own schedule.
        periph_cycles = await self.wait_signal_high(
            dut.rst_primary_periph_clk_no,
            dut.clk_periph_i,
            timeout_cycles=2000,
            name="rst_primary_periph_clk_no",
        )
        self.logger.info(
            "Primary resets released: rst_cold_n_o after %d clk_ref, "
            "rst_primary_smc_clk_n_o after %d clk_smu, "
            "rst_primary_periph_clk_no after %d clk_periph",
            cold_cycles,
            smc_cycles,
            periph_cycles,
        )
        await check_pll_clock_periods(
            self.logger,
            {
                "clk_ref_o": (dut.clk_ref_o, self.cfg.ref_clk_period_ns),
                "clk_smu_o": (dut.clk_smu_o, self.cfg.smu_clk_period_ns),
                "clk_periph_o": (dut.clk_periph_o, self.cfg.periph_clk_period_ns),
            },
        )
        self.cfg.reset_done.set()

    def declare_evidence(self, *tokens: str) -> None:
        """Register tokens this run must log before it may pass.

        A sequence calls it from its constructor with its ``EVIDENCE`` tuple, so
        the contract is declared before the scenario runs and the gate after
        the scenario cannot be satisfied by a run that never reached the
        sequence's verdict.
        """
        for token in tokens:
            if token not in self._declared_evidence:
                self._declared_evidence.append(token)

    def _required_evidence(self, tc: str) -> list[str]:
        required: list[str] = []
        for token in (
            *self.required_evidence,
            *self._declared_evidence,
            *(token for _, token, _ in TEST_EVIDENCE.get(tc, [])),
        ):
            if token not in required:
                required.append(token)
        return required

    def _prove_declared_evidence(self, tc: str) -> None:
        """Require every declared token to have been logged during this run.

        Runs only after run_scenario() returned normally: a run that already
        failed raised there, and this must not turn that into a different
        complaint. A token reaches the recorder only through an ``EVIDENCE:``
        line, and every wrapper-native emitter logs those after its verdict
        asserts, so a missing token means the verdict was never reached.
        """
        required = self._required_evidence(tc)
        if not required:
            reason = NO_EVIDENCE_LEAVES.get(tc)
            if reason is None:
                raise AssertionError(
                    f"EVIDENCE GATE {tc}: the leaf declares no evidence token -- give its "
                    "sequence an EVIDENCE tuple, set required_evidence on the test, or add "
                    "TEST_EVIDENCE rows; a clean exit that proves nothing is not a pass"
                )
            self.logger.info("EVIDENCE GATE EXEMPT %s: %s", tc, reason)
            return
        seen = [token for token in required if token in self._evidence.seen]
        missing = [token for token in required if token not in self._evidence.seen]
        self.logger.info(
            "EVIDENCE GATE %s: required=%d seen=%d missing=%d ids=%s",
            tc,
            len(required),
            len(seen),
            len(missing),
            ",".join(required),
        )
        if missing:
            raise AssertionError(
                f"EVIDENCE GATE {tc}: never logged {missing} -- the run exited cleanly "
                "without reaching the verdict that stamps them"
            )

    async def run_scenario(self) -> None:
        raise NotImplementedError

    async def run_phase(self) -> None:
        self.raise_objection()
        tc = self.get_type_name()
        if self.use_shared_env:
            # Bound before any expect_* runs so a check name can attach to its
            # mapped token.
            self.env.scoreboard.bind_testcase(tc)
        await self.bring_up()
        try:
            await self.run_scenario()
            # A cover property samples a handshake at one clock and records it at
            # the next; a scenario whose last access completes in its final cycle
            # loses that record if the run ends in the same time step.
            await ClockCycles(cocotb.top.clk_smu_i, 2)
            if self.use_shared_env:
                self.env.scoreboard.prove_mapped_features()
            else:
                self._prove_declared_evidence(tc)
        except Exception:  # noqa: BLE001 -- re-raised once the SEP state is in the log
            self.sep_trace_mon.dump_diagnostics(logging.ERROR)
            raise
        self.drop_objection()
