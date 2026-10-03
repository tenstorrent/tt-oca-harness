# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SEP UVM base test helpers.

Concrete tests inherit this class for common import setup, environment build,
clock/reset bring-up, CPU hold/run controls, and fuse-sense synchronization.
Real fuse-sense runs that stage an eFuse image automatically compare the sensed
shadow array against that image after sense-done.
"""

from __future__ import annotations

import hashlib
import logging
import os
import re
import shutil
import sys
from pathlib import Path
from typing import Awaitable, Callable

# A log record carrying a non-ASCII character raises UnicodeEncodeError inside the
# logging handler when the interpreter's stdio encoding follows an ASCII locale,
# and the traceback is reported as a simulation error rather than the failed print
# it is. Shared VIP log strings outside this tree carry such characters, so escape
# unencodable output instead of aborting on it. Nothing is suppressed: the record
# still prints, with the offending character shown escaped.
for _log_stream in (sys.stdout, sys.stderr):
    try:
        _log_stream.reconfigure(errors="backslashreplace")
    except (AttributeError, OSError, ValueError):
        pass


import cocotb
from cocotb.clock import Clock
from cocotb.triggers import (
    ClockCycles,
    NextTimeStep,
    ReadOnly,
    RisingEdge,
    SimTimeoutError,
    Timer,
    with_timeout,
)
from ocah_axi_vip import OcahAxiLiteMasterAgent, OcahAxiSlaveAgent
from pyuvm import ConfigDB, uvm_test

# The cocotb runner only puts the test dir on sys.path. Make the cocotb root
# (env/, seq_lib/) and shared OSS VIP root importable before concrete tests
# import env/seq_lib/VIP modules.
_COCOTB_ROOT = Path(__file__).resolve().parents[1]
_OSS_HW_ROOT = Path(__file__).resolve().parents[5]
for _path in (_COCOTB_ROOT, _OSS_HW_ROOT / "common" / "dv" / "vip"):
    _path_str = str(_path)
    if _path_str not in sys.path:
        sys.path.insert(0, _path_str)

from env.sep_cpu_trace_monitor import SepCpuTraceMonitor
from env.sep_efuse_image import SepEfuseImage
from env.sep_env import SepEnv
from env.sep_env_cfg import SepEnvCfg
from env.sep_smc_mem import SMC_AXI_GEOMETRY, SMC_MEM_SIZE, preload_smc_mem
from env.sep_verdict import decode_verdict
from models.entropy_noise_model import EntropyNoiseModel

# Committed default OTP image loaded when a test passes `+sep_efuse_preload` with
# no path (see select_efuse_image()). Real-fuse-sense tests (no +skip_fuse_sense)
# depend on it: without the file they would sense a zero OTP.
_DEFAULT_EFUSE_PRELOAD = (
    Path(__file__).resolve().parents[2] / "tb" / "efuse_preloads" / "sep_efuse_default.hex"
)

# Bound for the per-CSR reads in report_entropy_stall(). Generous versus a healthy
# AXI round trip (which is tens of ns) but finite, so a wedged fabric cannot turn
# the diagnostic itself into a sim timeout.
_STALL_CSR_TIMEOUT_NS = 50_000
# Cap on the dirty-file list in RUN-IDENTITY-DIRTY. The digest covers the whole
# diff; the paths are there to be read, so a 400-file rebase does not bury the log.
_RUN_IDENTITY_MAX_PATHS = 40
# Above this the simulator binary is named and sized but not hashed, so a
# pathological build cannot add minutes to every run's time 0.
_SIM_BINARY_HASH_MAX_BYTES = 512 << 20


class _EvidenceFilter(logging.Filter):
    """Collect the named evidence a test emits, by watching its own log.

    Tests already report each graded contract as ``CHK-<ID> PASS``. Reading the
    records as they pass keeps that the single source of the ID -- a separate
    call to register the check could drift from the line the log actually
    carries, and then the summary would describe a check nobody ran.

    Never filters: every record is returned unchanged.
    """

    _CHK = re.compile(r"\b(CHK-[A-Z0-9_-]+)\b\s*(?:\([^)]*\)\s*)?(PASS|OK)\b")

    # IDs sep_base_test itself emits. Counted in `observed` but excluded from
    # `own`, which is what a floor grades. Empty: bring-up logs no named CHK.
    BASE_IDS: frozenset[str] = frozenset()

    # Leaves allowed to pass with no own CHK record. A new entry hides a logging gap.
    NO_OWN_EVIDENCE: dict[str, str] = {}

    def __init__(self) -> None:
        super().__init__()
        self.seen: set[str] = set()

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            message = record.getMessage()
        except Exception:  # a broken format string is the caller's failure, not ours
            return True
        for check_id, _status in self._CHK.findall(message):
            self.seen.add(check_id)
        return True


class sep_base_test(uvm_test):
    """Shared SEP test: env build, clock/reset bring-up, scenario hook."""

    build_env = True

    # Which channel poll_boot() gates completion on.
    #
    #   "mailbox"  -- fw_done_o/fw_pass_o from the outbound mailbox decoder
    #                 (dv/tb/sep_outbound_mbx.sv). The default. spi/km/cpu
    #                 payloads report through the mailbox.
    #   "scratch0" -- the ROM/BL1 verdict word in cold_scratch[0]
    #                 (env/sep_verdict.py). Opt-in, set by rom_fw tests only.
    #
    # Opt-in rather than a global switch: this attribute decides how a test
    # concludes it passed. Flipping it for firmware that never writes
    # cold_scratch[0] does not fail loudly -- the test never completes.
    verdict_source = "mailbox"

    # Evidence gate. A clean exit is not a pass: a test whose stimulus stopped
    # reaching the DUT compares nothing, asserts nothing, and returns normally.
    # Every leaf reports its graded contracts as `CHK-<ID> PASS`, so the base
    # class counts what this run actually emitted and fails a silent one.
    #
    #   required_evidence -- IDs this test must emit. Missing any one fails.
    #   min_evidence      -- fewest distinct IDs of the test's OWN (records the
    #                        base class emits do not count). 0 disables it.
    #
    # Both default to off. They tighten a leaf that already emits records; they
    # do not replace the unconditional floor in `_finalize_evidence`. A leaf
    # whose `own` count is zero fails unless it is named in NO_OWN_EVIDENCE.
    # Graded contracts the floor accepts log `CHK-<ID> PASS` (or OK) after the
    # check. A colon-only `CHK-<ID>:` line does not match the counter, even when
    # an assert already sat in front of it.
    required_evidence: tuple[str, ...] = ()
    min_evidence = 0

    @staticmethod
    def random_seed() -> int:
        """Runner-provided seed (run_dv.py --seed -> RANDOM_SEED); default 1."""
        return int(os.environ.get("RANDOM_SEED", "1"), 0)

    @staticmethod
    def rd(sig, mask: int | None = None, *, allow_unknown: bool = False) -> int:
        """Read a DUT signal as int. Raise if a bit selected by ``mask`` is not 0 or 1.

        ``mask`` selects the bits the caller reads; the default is every bit
        the signal carries. The return carries only the masked bits, so a
        compare cannot match on a bit that was never required to be known.
        Pass a mask on a wide probe whose other lanes can legitimately be X,
        for example one 32-bit word of ``scratch_cold_probe_o``.

        An unknown bit raises by default because a zero-expecting compare on an
        X/Z node would otherwise pass: resolved to 0, an undriven or unknown
        node is indistinguishable from a node the device drove low.

        ``allow_unknown=True`` resolves X/Z/U/W/- to 0 and weak H/L to 1/0 per
        bit instead of raising. Use it only where an unknown value is legal for
        the read: a diagnostic log line, or a poll that waits for a nonzero
        value and so fails closed on X (it times out rather than passing).

        Two cocotb versions are in use here: the Verilator flow runs 2.x and
        the VCS flow runs 1.x. Both expose the per-bit string (``binstr`` on
        1.x, ``str()`` on 2.x), which is what is inspected. Verilator is built
        two-state here, so an unknown bit can only occur under VCS.
        """
        value = sig.value
        if isinstance(value, int):
            result = int(value)
        else:
            bits = getattr(value, "binstr", None)
            if bits is None:
                bits = str(value)
            bits = bits.strip()
            if not bits or any(c not in "01xXzZuUwWhHlL-" for c in bits):
                # Not a bit string (for example a real or string handle).
                result = int(value)
            else:
                unknown = [
                    i
                    for i, c in enumerate(reversed(bits))
                    if c not in "01" and (mask is None or (mask >> i) & 1)
                ]
                if unknown and not allow_unknown:
                    raise AssertionError(
                        f"{getattr(sig, '_path', sig)} is not fully known at the bits this "
                        f"read selects: bits={bits!r}, unknown bit indices {unknown[:16]}"
                        f"{' ...' if len(unknown) > 16 else ''}. A compare on an unknown "
                        "node can pass for free, so the read raises. Pass a mask that "
                        "selects only the bits the caller uses, or allow_unknown=True "
                        "where an unknown value is legal for this read."
                    )
                result = int("".join("1" if c in "1hH" else "0" for c in bits), 2)
        return result if mask is None else result & mask

    @staticmethod
    def rd_known(sig, mask: int | None = None) -> int:
        """Read a signal, raising if any bit selected by ``mask`` is not 0 or 1.

        Same contract as ``rd`` with ``allow_unknown=False``. Kept as the
        explicit name at zero-expecting compares.
        """
        return sep_base_test.rd(sig, mask)

    @staticmethod
    def _set_if_exists(dut, name: str, value: int) -> None:
        try:
            getattr(dut, name).value = value
        except AttributeError:
            pass

    def build_phase(self) -> None:
        # Installed before anything can log, so no evidence predates the filter.
        self._evidence = _EvidenceFilter()
        self._install_evidence_filter(self._evidence)
        self.cfg = SepEnvCfg("cfg")
        self._efuse_compare_image: SepEfuseImage | None = None
        self.logger.info(
            "SEP timing: sys_clk_period=%s ns ref_clk_period=%s ns",
            self.cfg.sys_clk_period_ns,
            self.cfg.ref_clk_period_ns,
        )
        ConfigDB().set(None, "*", "cfg", self.cfg)
        self.bind_smc_responder(cocotb.top)
        # Processor-state monitor on the EL2 retirement trace. Built for every
        # test (concrete tests build their scoreboards after super().build_phase(),
        # so the ConfigDB entry is in place); it self-idles unless the +cpu_boot
        # run mode is active.
        self.cpu_trace_mon = SepCpuTraceMonitor("cpu_trace_mon", self)
        ConfigDB().set(None, "*", "cpu_trace_mon", self.cpu_trace_mon)
        if self.build_env:
            self.env = SepEnv("env", self)

    def start_clocks(self, dut=None) -> None:
        """Start the clocks exposed by tb_top."""
        if dut is None:
            dut = cocotb.top
        cocotb.start_soon(Clock(dut.clk_i, self.cfg.sys_clk_period_ns, units="ns").start())
        cocotb.start_soon(Clock(dut.clk_wdt_i, self.cfg.wdt_clk_period_ns, units="ns").start())
        cocotb.start_soon(
            Clock(dut.entropy_rosc_sample_clk_i, self.cfg.entropy_clk_period_ns, units="ns").start()
        )
        cocotb.start_soon(Clock(dut.clk_ref_i, self.cfg.ref_clk_period_ns, units="ns").start())

    def bind_smc_responder(self, dut) -> None:
        """Attach the shared AXI slave agent to the SEP->SMC boundary.

        Only the ``rom_boot`` target instantiates ``u_smc_axi_if``; every other
        build leaves ``cfg.smc_mem`` at None. Bound in ``build_phase`` so the
        responder exists before the first clock edge (the boundary's READY
        signals are driven from time zero) and before any test-owned monitor
        that samples its memory starts; the preload here means the Boot ROM's
        first fetch already sees the scratch, status, strap, and image words.
        """
        if self.cfg.smc_mem is not None or not hasattr(dut, "u_smc_axi_if"):
            return
        self.cfg.smc_mem = OcahAxiSlaveAgent(
            SMC_AXI_GEOMETRY.bus(dut.u_smc_axi_if),
            dut.clk_i,
            dut.rst_ni,
            reset_active_level=False,
            size=SMC_MEM_SIZE,
            name="sep_smc_mem",
        ).sequence
        preload_smc_mem(self.cfg.smc_mem, cocotb.plusargs, self.logger)

    def drive_idle_defaults(self, dut=None, *, cpu_run: bool = False, rst_vec: int = 0) -> None:
        """Drive stable top-level controls before reset is released."""
        if dut is None:
            dut = cocotb.top
        dut.ext_boot_seq_done_i.value = 1
        dut.mpc_reset_run_req.value = 1 if cpu_run else 0
        # eFuse program-fail injection is seeded via the +sep_efuse_prog_fail_seed
        # plusarg inside the generic efuse model.
        self._set_if_exists(dut, "i_cpu_run_req_i", 0)
        self._set_if_exists(dut, "tcm_load_i", 0)
        # WDT reset input deasserted by default (sep_cpu_reset_n then follows
        # sep_reset_n); the wdt-reset-path test pulses it low itself.
        self._set_if_exists(dut, "wdt_rst_ni_i", 1)
        # EL2 debugger reset deasserted by default; the CPU debug-reset isolation
        # test pulses it low itself.
        self._set_if_exists(dut, "dbg_rstb_i", 1)
        self._set_if_exists(dut, "rst_vec_i", rst_vec)
        self._set_if_exists(dut, "esrc_noise_ext_i", 0)
        self._set_if_exists(dut, "spi_miso_i", 1)
        # TEST_EN strap / LC sigint inject default off. Tests that need either
        # polarity raise the port themselves after bring-up (or before sense).
        self._set_if_exists(dut, "test_en_strap_i", 0)
        self._set_if_exists(dut, "jtag_otbn_rst_hold_i", 0)
        self._set_if_exists(dut, "jtag_aes_rst_hold_i", 0)
        self._set_if_exists(dut, "jtag_hmac_rst_hold_i", 0)
        self._set_if_exists(dut, "jtag_kmac_rst_hold_i", 0)
        self._set_if_exists(dut, "jtag_trng_rst_hold_i", 0)
        self._set_if_exists(dut, "jtag_abr_rst_hold_i", 0)
        self._set_if_exists(dut, "jtag_sep_reset_n_ovrd_i", 0)
        self._set_if_exists(dut, "jtag_sep_reset_n_val_i", 0)
        self._set_if_exists(dut, "jtag_ic_reset_tdr_en_i", 0)
        self._set_if_exists(dut, "jtag_ic_reset_tck_i", 0)
        self._set_if_exists(dut, "jtag_ic_reset_select_i", 0)
        self._set_if_exists(dut, "jtag_ic_reset_capture_en_i", 0)
        self._set_if_exists(dut, "jtag_ic_reset_shift_en_i", 0)
        self._set_if_exists(dut, "jtag_ic_reset_update_en_i", 0)
        self._set_if_exists(dut, "jtag_ic_reset_rst_n_i", 1)
        self._set_if_exists(dut, "jtag_ic_reset_trst_n_i", 1)
        self._set_if_exists(dut, "jtag_ic_reset_tdi_i", 0)
        self._set_if_exists(dut, "lc_sigint_inject_i", 0)
        self._set_if_exists(dut, "token_cmp_fault_inject_i", 0)
        self._set_if_exists(dut, "token_cmp_fault_sel_i", 0)
        self._set_if_exists(dut, "token_digest_test_en_inject_i", 0)
        self._set_if_exists(dut, "dma_host_intg_inject_i", 0)
        self._set_if_exists(dut, "hmac_fifo_drain_stall_i", 0)
        # Idle the master strobes from t=0 (valid=0, ready=1) so a test that
        # does not construct OcahAxiMasterAgent still presents a resolved idle
        # bus. Called before start_clocks. Env-built tests drive the same idle.
        for prefix in ("s_axi", "m_axi"):
            self._set_if_exists(dut, f"{prefix}_awvalid", 0)
            self._set_if_exists(dut, f"{prefix}_wvalid", 0)
            self._set_if_exists(dut, f"{prefix}_arvalid", 0)
            self._set_if_exists(dut, f"{prefix}_bready", 1)
            self._set_if_exists(dut, f"{prefix}_rready", 1)

        # Hold the TB-owned drbg_axil64_lane_adapter arbitration vehicle in
        # reset with its request channels idle. It is a live instance in every
        # build, so leaving its inputs unresolved would drive X into its
        # ASSERT_KNOWN checks in tests that never use it.
        # sep_drbg_axil_adapter_port_arbitration_test and
        # sep_drbg_axil_adapter_refusal_test release it themselves.
        self._set_if_exists(dut, "tbadp_rst_ni_i", 0)
        for pin in ("aw_valid", "w_valid", "ar_valid"):
            self._set_if_exists(dut, f"tbadp_{pin}_i", 0)
        for pin in ("aw_addr", "ar_addr", "w_data", "w_strb"):
            self._set_if_exists(dut, f"tbadp_{pin}_i", 0)
        for pin in ("b_ready", "r_ready"):
            self._set_if_exists(dut, f"tbadp_{pin}_i", 1)

    def _check_efuse_shadow_after_sense(self) -> None:
        """Backdoor-compare sensed shadow data for real eFuse-image sense runs."""
        if "skip_fuse_sense" in cocotb.plusargs:
            return
        if self._efuse_compare_image is None:
            raise AssertionError(
                "real fuse-sense completed without an eFuse golden image; "
                "call write_efuse_image(image) before waiting for sense-done"
            )
        from seq_lib.sep_efuse_backdoor_check import check_efuse_shadow_backdoor

        # The strap the DUT latched, not what the test intended: reading secure_tm_o
        # keeps the golden's secret-blanking tied to the DUT rather than to a flag the
        # test could set wrongly.
        secure_tm = 0
        probe = getattr(cocotb.top, "secure_tm_o", None)
        if probe is not None:
            secure_tm = int(probe.value) & 0x1
        check_efuse_shadow_backdoor(self.logger, self._efuse_compare_image, secure_tm=secure_tm)

    async def _wait_fuse_sense(self, max_cycles: int) -> None:
        """Poll sep_fuse_sense_done_o until it asserts (or time out), then settle.

        Every bring-up gates on this signal. With +skip_fuse_sense the RTL asserts
        the done flop ~1 cycle after reset release; without it the real 256-word
        sense runs and the sensed shadow is compared against the staged eFuse
        image. A skip without ``+sep_efuse_preload`` leaves the shadow at its
        reset (zero). That is the intended default: no skip-mode leaf grades a
        shadow value.
        """
        dut = cocotb.top
        for cycle in range(max_cycles):
            await RisingEdge(dut.clk_i)
            if self.rd(dut.sep_fuse_sense_done_o):
                self.logger.info("SEP fuse sense done at cycle %d", cycle)
                await ClockCycles(dut.clk_i, 20)
                self._check_efuse_shadow_after_sense()
                return
        raise AssertionError("sep_fuse_sense_done_o never asserted (fabric not released)")

    _JTAG_SW_RST_HOLD = {
        "otbn": "jtag_otbn_rst_hold_i",
        "aes": "jtag_aes_rst_hold_i",
        "hmac": "jtag_hmac_rst_hold_i",
        "kmac": "jtag_kmac_rst_hold_i",
        "trng": "jtag_trng_rst_hold_i",
        "abr": "jtag_abr_rst_hold_i",
    }

    def _jtag_sw_rst_hold(self, engines: tuple[str, ...], hold: bool) -> None:
        """Drive the JTAG SW-reset override so named engines never leave reset.

        Applied before ``rst_ni`` release so AES/KMAC/OTBN cannot raise
        crypto ``edn_req`` (CSR reset 0x7E would release them). The caller
        drops the override after the hold window. Empty ``engines`` is a no-op.
        """
        dut = cocotb.top
        val = 1 if hold else 0
        for eng in engines:
            port = self._JTAG_SW_RST_HOLD.get(eng)
            if port is not None:
                self._set_if_exists(dut, port, val)
        if engines:
            self.logger.info(
                "JTAG SW-reset hold %s -> %s",
                ",".join(engines),
                "on" if hold else "off",
            )

    async def assert_cold_reset(self, dut) -> None:
        """Assert ``rst_ni`` with a real falling edge, before any clock runs.

        An async-reset flop is written ``always_ff @(posedge clk or negedge
        rst_ni)``, so it only ever executes on an edge. Driving ``rst_ni`` low
        from an undriven net gives the flops nothing to trigger on, and they
        hold X for the whole run. Presenting 1 first makes the assertion a
        genuine 1->0, so every async reset in the design fires and loads its
        reset value.

        No clock is running across this window, so nothing sequential advances.
        The bus request nets are idled before this runs, because the reset
        rules sample VALID against a low reset and an undriven net fails them
        on stimulus that does not exist.
        """
        dut.rst_ni.value = 1
        await Timer(1, units="ns")
        dut.rst_ni.value = 0
        await Timer(1, units="ns")

    async def release_no_cpu_reset(self, *, park: tuple[str, ...] = ()) -> None:
        """Clocks + ``rst_ni`` release, CPU held off. Does not wait for sense.

        The local AXI xbar and LCC sit on ``rst_ni``, so a test can issue a
        CPU-LSU beat before ``sep_fuse_sense_done_o``. Sets ``reset_done`` so
        the AXI agent will start. Call ``wait_fuse_sense`` afterwards.
        ``park`` names engines to JTAG-hold through this ``rst_ni`` release
        (``bring_up_no_cpu`` drops the override after sense + CSR park).
        """
        dut = cocotb.top
        self.logger.info("Bringing up clocks and reset (CPU held off)")
        self.drive_idle_defaults(dut, cpu_run=False)
        await self.assert_cold_reset(dut)
        self._jtag_sw_rst_hold(park, True)
        self.start_clocks(dut)
        await ClockCycles(dut.clk_i, 20)
        self.logger.info("Releasing rst_ni")
        dut.rst_ni.value = 1
        await ClockCycles(dut.clk_i, 2)
        self.cfg.reset_done.set()

    async def wait_fuse_sense(self, *, max_cycles: int = 20_000) -> None:
        """Poll ``sep_fuse_sense_done_o`` and run the post-sense shadow compare."""
        await self._wait_fuse_sense(max_cycles)

    async def check_pre_sense_fail_closed(self) -> None:
        """AXI-read ``FEAT_CTRL`` while sense is still running; expect fail-closed.

        ``hw/sys/sep/doc/lifecycle_controller.adoc`` (LC State Machine): the
        OTP controller holds the LC-state shadow output at the INVALID
        encoding (4'b1111) until fuse sensing completes, so the LCC produces
        the INVALID feature-control profile, which the DV golden decodes to
        ``FEAT_CTRL`` = 0. The read must land before ``sep_fuse_sense_done_o``.
        """
        from env.sep_lcc_golden import feat_ctrl_expected
        from seq_lib.sep_lcc_inbound_filter_gating_seq import SepLccFeatCtrlCheckSeq

        dut = cocotb.top
        assert not self.rd_known(dut.sep_fuse_sense_done_o), (
            "CHK-PRE-SENSE-FAIL-CLOSED FAIL: sep_fuse_sense_done_o already 1; no pre-sense window"
        )
        # LC_STATE_INVALID low nibble is 4'hF — not a legal raw state.
        closed = feat_ctrl_expected(0xF, 0, 0)
        assert closed == 0, "CHK-PRE-SENSE-FAIL-CLOSED FAIL: invalid-LC golden is not 0"
        seq = SepLccFeatCtrlCheckSeq(closed)
        mark = self.sb_mark()
        await self.start_seq(seq)
        assert not self.rd_known(dut.sep_fuse_sense_done_o), (
            "CHK-PRE-SENSE-FAIL-CLOSED FAIL: sense completed during the FEAT_CTRL "
            "read; the closed side was not observed"
        )
        self.assert_sb_judged(mark, "CHK-PRE-SENSE-FAIL-CLOSED")
        assert seq.feat_ctrl == closed, (
            f"CHK-PRE-SENSE-FAIL-CLOSED FAIL: FEAT_CTRL=0x{seq.feat_ctrl:016x} before "
            f"sense-done, expected 0x{closed:016x}"
        )
        self.logger.info(
            "CHK-PRE-SENSE-FAIL-CLOSED PASS: FEAT_CTRL=0x%016x while sep_fuse_sense_done_o=0",
            seq.feat_ctrl,
        )

    async def bring_up_no_cpu(
        self,
        *,
        max_cycles: int = 20_000,
        park: tuple[str, ...] = (),
    ) -> None:
        """Bring up the DUT (CPU held off; the stub drives the LSU AXI from the
        cocotb master), gating on fuse-sense-done before returning.

        ``park`` names SW_RESET_N engines to JTAG-hold through ``rst_ni``
        release and fuse sense, then park in the CSR, then drop the override.
        AES/KMAC/OTBN power up released (reset 0x7E) and would assert crypto
        ``edn_req``; dropping that ungranted ``req`` fails the arbiter
        hold-until-grant assume. The CSR write waits until sense has opened
        the fabric — an in-flight ``SW_RESET_N`` beat across sense-done
        underflows the LSU demux ID counter. An empty tuple leaves the
        hardware reset default.
        """
        await self.release_no_cpu_reset(park=park)
        await self.wait_fuse_sense(max_cycles=max_cycles)
        if park:
            from seq_lib.sep_sw_reset_seq import SepSwReset

            if getattr(self, "swrst", None) is None:
                self.swrst = SepSwReset(self)
            await self.swrst.park(*park)
            await ClockCycles(cocotb.top.clk_i, 2)
            self._jtag_sw_rst_hold(park, False)

    async def bring_up_and_wait_fuse_sense(self, *, max_cycles: int = 20_000) -> None:
        """Alias for ``bring_up_no_cpu``; both gate on real fuse-sense-done."""
        await self.bring_up_no_cpu(max_cycles=max_cycles)

    async def resense(self, *, hold_cycles: int = 20, max_cycles: int = 20_000) -> None:
        """Re-pulse rst_ni to trigger a fresh fuse-sense (clocks already running).

        This re-senses whatever the OTP bank currently holds. It does NOT reload
        the image file: ``efuse_bank_model`` deposits the hex in a time-0
        ``initial`` and a fuse holds its state across every reset (the bank
        register field has no reset value), so rewriting ``out/sep_efuse.hex``
        between senses changes only the golden, not the DUT. To change what the
        DUT senses, either program the OTP bits for real -- W1S, so only a
        superset is reachable -- or start a new leaf with the image staged at
        t=0 by ``dv_sim_prestage.py``.
        """
        dut = cocotb.top
        self.logger.info("Re-sensing: pulsing rst_ni")
        dut.rst_ni.value = 0
        await ClockCycles(dut.clk_i, hold_cycles)
        dut.rst_ni.value = 1
        await self._wait_fuse_sense(max_cycles)
        self.cfg.reset_done.set()

    async def bring_up_cpu_boot(
        self,
        rst_vec: int,
        *,
        pre_reset_hook: Callable[[], Awaitable[None]] | None = None,
        post_reset_run_pulse: bool = True,
        wait_after_reset_cycles: int = 30,
        run_pulse_cycles: int = 20,
        max_cycles: int = 20_000,
        park: tuple[str, ...] = (),
        release_park: bool = True,
    ) -> None:
        """Bring up the DUT with the CPU owning its master buses.

        ``park`` JTAG-holds named engines through ``rst_ni`` and fuse-sense.
        With ``release_park`` (the default) the override drops after sense;
        with ``release_park=False`` the hold stays for the rest of the run
        so those engines never raise crypto ``edn_req``. The SW_RESET_N CSR
        stays at reset 0x7E either way (JTAG is an override). Empty ``park``
        leaves the hardware reset default.
        """
        dut = cocotb.top
        self.logger.info("Bringing up clocks and reset (CPU run, rst_vec=0x%x)", rst_vec)
        self.drive_idle_defaults(dut, cpu_run=True, rst_vec=rst_vec)
        await self.assert_cold_reset(dut)
        # CPU boot: EL2 debug reset follows cold reset.
        self._set_if_exists(dut, "dbg_rstb_i", 0)
        self._jtag_sw_rst_hold(park, True)
        self.start_clocks(dut)
        await ClockCycles(dut.clk_i, 20)
        if pre_reset_hook is not None:
            self.logger.info("CPU boot: running pre-reset hook")
            await pre_reset_hook()
            self.logger.info("CPU boot: pre-reset hook complete")
        self.logger.info("Releasing rst_ni")
        dut.rst_ni.value = 1
        self._set_if_exists(dut, "dbg_rstb_i", 1)
        # Gate on the real fabric-release signal, then a small CPU settle margin.
        await self._wait_fuse_sense(max_cycles)
        if park and release_park:
            await ClockCycles(dut.clk_i, 2)
            self._jtag_sw_rst_hold(park, False)
        elif park:
            self.logger.info(
                "CPU boot: JTAG SW-reset hold stays asserted for %s",
                ",".join(park),
            )
        self.logger.info(
            "CPU boot: post-fuse reset state sep_rst_n=%d cpu_rst_n=%d run_ack=%d iccm_act=%d",
            self.rd(dut.dbg_sep_reset_n_o, allow_unknown=True),
            self.rd(dut.sep_cpu_reset_n_o, allow_unknown=True),
            self.rd(dut.o_cpu_run_ack_o, allow_unknown=True),
            self.rd(dut.dbg_iccm_active_o, allow_unknown=True),
        )
        await ClockCycles(dut.clk_i, wait_after_reset_cycles)
        if post_reset_run_pulse:
            self.logger.info("CPU boot: asserting i_cpu_run_req_i for %d cycles", run_pulse_cycles)
            dut.i_cpu_run_req_i.value = 1
            await ClockCycles(dut.clk_i, run_pulse_cycles)
            dut.i_cpu_run_req_i.value = 0
            self.logger.info(
                "CPU boot: deasserted run request run_ack=%d trace_valid=%d iccm_act=%d iccm_addr=0x%x",
                self.rd(dut.o_cpu_run_ack_o, allow_unknown=True),
                self.rd(dut.cpu_trace_valid_o, allow_unknown=True),
                self.rd(dut.dbg_iccm_active_o, allow_unknown=True),
                self.rd(dut.dbg_iccm_addr_o, allow_unknown=True),
            )
        self.cfg.reset_done.set()

    async def boot_firmware(
        self,
        sb,
        itcm_hex: str,
        dtcm_hex: str,
        *,
        rst_vec: int,
        max_run_cycles: int,
        no_boot_cycles: int = 80_000,
        progress_every: int = 2_000,
        run_pulse_cycles: int = 40,
        park: tuple[str, ...] = (),
        release_park: bool = True,
        after_bring_up_hook: Callable[[], Awaitable[None]] | None = None,
    ) -> None:
        """Stage a firmware TCM image, boot the EL2 core, and sample boot
        observables into the boot scoreboard ``sb`` until the firmware signals
        completion. Shared by every CPU firmware-boot test so the TCM staging and
        boot-poll live in one place (do not duplicate this in concrete tests).

        ``park`` / ``release_park`` are forwarded to ``bring_up_cpu_boot``.
        ``after_bring_up_hook`` runs after the CPU is released and before the
        boot poll, so a test can sample an idle output before firmware programs
        it. The SW_RESET_N CSR stays at reset 0x7E.

        The TCM responder backdoor-loads ``sep_itcm.hex`` / ``sep_dtcm.hex`` from
        the sim CWD, so the images are staged there. (CWD-shared: one CPU firmware
        test runs per sim, so the images do not collide.)
        """
        dut = cocotb.top
        for src, dst in ((itcm_hex, "sep_itcm.hex"), (dtcm_hex, "sep_dtcm.hex")):
            if not os.path.isfile(src):
                raise FileNotFoundError(
                    f"firmware image not found: {src}\n"
                    f"  build it first (RISC-V GCC on PATH): make -C {os.path.dirname(src)}"
                )
            shutil.copyfile(src, os.path.join(os.getcwd(), dst))
        self.logger.info("staged firmware TCM images into %s", os.getcwd())
        self._log_firmware_identity(itcm_hex, dtcm_hex)

        # Feed the firmware's nm listing (built next to the hex images by
        # compile.mk) to the trace monitor so backtraces symbolize. Best-effort:
        # a missing listing degrades to numeric PCs, never fails the test.
        fw_dir = Path(itcm_hex).parent
        fw_name = Path(itcm_hex).name.split(".", 1)[0]
        # <name>.<mode>.sym for TCM firmware (compile.mk), <name>.sym for the
        # Boot ROM (bootrom/prod/Makefile) -- the ROM boot tests come through
        # here too, with itcm_hex pointing into the ROM build dir.
        sym_files = sorted(
            set(fw_dir.glob(f"{fw_name}.sym")) | set(fw_dir.glob(f"{fw_name}.*.sym"))
        )
        if sym_files:
            for sym in sym_files:
                self.cpu_trace_mon.add_symbols(sym)
        else:
            self.logger.info("no %s.*.sym next to %s; trace PCs stay numeric", fw_name, itcm_hex)

        async def _load_tcm() -> None:
            self.logger.info("CPU boot: pulsing tcm_load_i")
            dut.tcm_load_i.value = 1
            await ClockCycles(dut.clk_i, 4)
            dut.tcm_load_i.value = 0
            await ClockCycles(dut.clk_i, 4)
            self.logger.info("CPU boot: tcm_load_i pulse complete")

        await self.bring_up_cpu_boot(
            rst_vec,
            pre_reset_hook=_load_tcm,
            run_pulse_cycles=run_pulse_cycles,
            park=park,
            release_park=release_park,
        )
        if after_bring_up_hook is not None:
            await after_bring_up_hook()

        await self.poll_boot(
            sb,
            max_run_cycles=max_run_cycles,
            no_boot_cycles=no_boot_cycles,
            progress_every=progress_every,
        )

    async def poll_boot(
        self,
        sb,
        *,
        max_run_cycles: int,
        no_boot_cycles: int = 80_000,
        progress_every: int = 2_000,
    ) -> None:
        """Sample boot observables into the boot scoreboard ``sb`` until the
        firmware signals completion (or the no-boot/max-run bounds trip).

        ``boot_firmware`` calls this last; a test that must do work CONCURRENTLY
        with the running firmware (e.g. drive a second master while the CPU loops)
        can ``bring_up_cpu_boot`` itself, ``cocotb.start_soon(self.poll_boot(...))``,
        and run its own stimulus alongside.
        """
        dut = cocotb.top
        mon = self.cpu_trace_mon
        last_log = 0
        self.logger.info(
            "boot poll start run_ack=%d cpu_rst_n=%d trace_valid=%d iccm_act=%d iccm_addr=0x%x",
            self.rd(dut.o_cpu_run_ack_o, allow_unknown=True),
            self.rd(dut.sep_cpu_reset_n_o, allow_unknown=True),
            self.rd(dut.cpu_trace_valid_o, allow_unknown=True),
            self.rd(dut.dbg_iccm_active_o, allow_unknown=True),
            self.rd(dut.dbg_iccm_addr_o, allow_unknown=True),
        )
        gate_on_scratch = self.verdict_source == "scratch0"
        for cycle in range(max_run_cycles):
            await RisingEdge(dut.clk_i)
            # Trace sampling lives in the CPU trace monitor; this loop owns
            # only the console/verdict observables.
            sb.note_run_ack(self.rd(dut.o_cpu_run_ack_o))
            if self.rd(dut.fw_char_valid_o):
                sb.note_char(self.rd(dut.fw_char_o))
            if gate_on_scratch:
                # cold_scratch[0] only; the other scratch words are not read.
                verdict = decode_verdict(self.rd(dut.scratch_cold_probe_o, mask=0xFFFF_FFFF))
                if verdict is not None:
                    sb.note_fw(True, verdict[1])
                    self.logger.info(
                        "CHK-VERDICT: firmware signaled completion at cycle %d "
                        "via cold_scratch[0], pass=%d",
                        cycle,
                        verdict[1],
                    )
                    break
            elif self.rd(dut.fw_done_o):
                sb.note_fw(True, self.rd(dut.fw_pass_o))
                self.logger.info("firmware signaled completion at cycle %d", cycle)
                break
            if cycle - last_log >= progress_every:
                last_log = cycle
                self.logger.info(
                    "boot progress cyc=%d retired=%d pcs=%d last_pc=0x%08x con=%dB rst_n=%s "
                    "iccm_act=%s exc=%s",
                    cycle,
                    mon.trace_count,
                    len(mon.pcs),
                    mon.last_pc,
                    len(sb.console),
                    self.rd(dut.dbg_sep_reset_n_o, allow_unknown=True),
                    self.rd(dut.dbg_iccm_active_o, allow_unknown=True),
                    self.rd(dut.dbg_cpu_trace_exc_o, allow_unknown=True),
                )
            if cycle >= no_boot_cycles and mon.trace_count == 0:
                self.logger.error(
                    "core retired no instructions in %d cycles; aborting", no_boot_cycles
                )
                break
        if sb.console:
            self.logger.info("firmware console: %r", sb.console_text())
        if sb.fw_done and sb.fw_pass:
            if gate_on_scratch:
                self.logger.info("CHK-VERDICT PASS: firmware completed through cold_scratch[0]")
            else:
                self.logger.info("CHK-FW-CONSOLE PASS: firmware mailbox completion with PASS magic")
        if not (sb.fw_done and sb.fw_pass):
            # Hang, no-boot, run-cycle exhaustion, or firmware FAIL: put the
            # symbolized backtrace in the log before the scoreboard's
            # check_phase assertion ends the run.
            mon.dump_diagnostics(logging.ERROR)

    def select_efuse_image(
        self,
        *,
        seed_offset: int = 0,
        default_preload: str | Path = _DEFAULT_EFUSE_PRELOAD,
        lc_raw: int | None = None,
        lock_prob: float = 0.0,
        fixed: dict[str, int] | None = None,
    ) -> SepEfuseImage:
        """Select an eFuse image for any eFuse test.

        Constrained-random is the default. To pin a fixed image instead:
          * +sep_efuse_preload=<path> loads that preload/hex file.
          * +sep_efuse_preload (no path) loads the committed default preload.
        """
        if "sep_efuse_preload" in cocotb.plusargs:
            preload = cocotb.plusargs.get("sep_efuse_preload")
            path = str(default_preload if preload in (None, "", True) else preload)
            image = SepEfuseImage().load(path)
            self.logger.info("[efuse] selected preload image: %s", path)
            return image

        seed = self.random_seed() + seed_offset
        image = SepEfuseImage().randomize(
            seed,
            lc_raw=lc_raw,
            lock_prob=lock_prob,
            fixed=fixed,
        )
        self.logger.info(
            "[efuse] selected random image (seed=%d, LC raw=0x%x)",
            seed,
            image.lc_raw(),
        )
        return image

    def write_efuse_image(self, image) -> str:
        """Write an eFuse OTP image to ``<run_cwd>/out/sep_efuse.hex``.

        The responder loads that default path unless ``+sep_efuse_hex=<path>``
        overrides it for a special run. The image is also kept as
        the golden for the automatic post-sense shadow comparison.
        """
        out_dir = os.path.join(os.getcwd(), "out")
        os.makedirs(out_dir, exist_ok=True)
        path = os.path.join(out_dir, "sep_efuse.hex")
        image.write_hex(path)
        # The CWD copy above (loaded by the responder) lives in the test dir and
        # is overwritten every run. Archive a per-run copy under the run output
        # dir (next to results.xml) so a specific run's sensed image is findable
        # after the fact. cocotb exports COCOTB_RESULTS_FILE = <run>/results/results.xml.
        results = os.environ.get("COCOTB_RESULTS_FILE")
        run_copy = None
        if results:
            try:
                run_copy = os.path.join(os.path.dirname(results), "sep_efuse.hex")
                image.write_hex(run_copy)
            except OSError:
                run_copy = None
        self.logger.info(
            "wrote eFuse image -> %s%s (LC raw=0x%x)",
            path,
            f" (run copy: {run_copy})" if run_copy else "",
            image.lc_raw(),
        )
        self._efuse_compare_image = image
        return path

    async def start_seq(self, seq) -> None:
        """Run a sequence on the primary CPU-LSU AXI sequencer (s_axi)."""
        await seq.start(self.env.axi_agent.sequencer)

    def sb_mark(self) -> tuple[int, int]:
        """Scoreboard error and judged-read counts, taken before a checked sequence."""
        sb = self.env.scoreboard
        return len(sb.errors), sb.value_checks

    def assert_sb_judged(self, mark: tuple[int, int], chk: str) -> None:
        """Fail ``chk`` unless the scoreboard judged a read and rejected none since ``mark``.

        SepScoreboard.write compares every read that carries ``item.expected``:
        a mismatch goes to ``errors`` and fails the test only at check_phase, and
        a match counts in ``value_checks``. A CHK PASS line logged after this
        call rests on that judgment, so it cannot print for a value the
        scoreboard rejected.
        """
        errs, judged = mark
        sb = self.env.scoreboard
        new = sb.errors[errs:]
        assert not new, f"{chk} FAIL: scoreboard rejected {len(new)} read(s): " + "; ".join(new)
        assert sb.value_checks > judged, f"{chk} FAIL: the scoreboard judged no read value"

    def watch_sys_csr_lite(self, *, write: bool) -> tuple[object, list[int]]:
        """Record system-CSR AXI-Lite handshakes until the caller kills the task.

        Returns ``(task, addrs)``. ``addrs`` is appended in place while the
        task runs, one entry per AW (``write``) or AR handshake at the
        ``sys_csr_axil_*`` observation ports. Lite has no AxLEN; each handshake
        is one converted single.
        """
        return self._watch_handshakes("sys_csr_axil", write=write)

    def watch_xbar_ext_in(self, *, write: bool) -> tuple[object, list[int]]:
        """Record AW (``write``) or AR handshakes at the local crossbar's ``ext``
        initiator (``xbar_ext_in_*``) until the caller kills the task.

        Returns ``(task, addrs)`` as ``watch_sys_csr_lite`` does. The port carries
        what ``sep_system_peripherals`` forwards into the local crossbar.
        """
        return self._watch_handshakes("xbar_ext_in", write=write)

    def _watch_handshakes(self, port: str, *, write: bool) -> tuple[object, list[int]]:
        dut = cocotb.top
        ch = "aw" if write else "ar"
        valid = getattr(dut, f"{port}_{ch}valid_o")
        ready = getattr(dut, f"{port}_{ch}ready_o")
        addr = getattr(dut, f"{port}_{ch}addr_o")
        addrs: list[int] = []

        async def _mon() -> None:
            while True:
                await RisingEdge(dut.clk_i)
                await ReadOnly()
                if self.rd_known(valid) and self.rd_known(ready):
                    addrs.append(self.rd_known(addr) & 0xFFFF_FFFF)

        return cocotb.start_soon(_mon()), addrs

    async def start_ext_seq(self, seq) -> None:
        """Run a sequence on the SMN-inbound EXTERNAL AXI sequencer (m_axi).

        This master traverses the inbound filter (block-by-default; skipped only
        when feat_ctrl.sep_debug=1), so it is the path the inbound-filter-gating
        test uses to prove external AXI is blocked (PROD) / allowed (PROD_DBG_1).
        """
        await seq.start(self.env.ext_axi_agent.sequencer)

    # --- SEP-OTP JTAG AXI-Lite master (j_axi) ---------------------------------
    # The DUT's real axil_sep_otp_jtag port, brought out flat as j_axi_* in
    # tb_top: the debug/JTAG path into the eFuse interface controller (arbitrates
    # with the CPU eFuse-MMR path at the eFuse AXI-Lite mux; LC-state-gated).
    # One master and one op helper, shared by every JTAG/eFuse test.
    def jtag_axil_master(self):
        """Construct (once) and return the AXI-Lite master sequence on j_axi."""
        if getattr(self, "_jtag_axil", None) is None:
            dut = cocotb.top
            self._jtag_axil = OcahAxiLiteMasterAgent.from_prefix(
                dut,
                "j_axi",
                dut.clk_i,
                dut.rst_ni,
                name="sep_jtag_axil",
                reset_active_level=False,
                raise_on_error=False,
            ).sequence
        return self._jtag_axil

    async def jtag_axil_op(
        self, *, write: bool, addr: int, wdata: int = 0, timeout_ns: int = 50_000
    ) -> tuple[int, int]:
        """Drive one JTAG AXI-Lite op; return (resp_code, rdata).

        resp_code is the AXI response (OKAY=0, SLVERR=2, DECERR=3; -1 if
        unreadable). A non-completing access (wedge) fails the test rather than
        hanging silently. Uses the common VIP ``*_result`` API with
        ``check_response=False`` so a denied access returns DECERR instead of
        raising.
        """
        m = self.jtag_axil_master()
        kwargs = {"check_response": False, "timeout_ns": timeout_ns}
        if write:
            result = await m.write_result(addr, wdata, **kwargs)
            return result.resp, 0
        result = await m.read_result(addr, **kwargs)
        return result.resp, result.data

    # --- entropy (ESRC->DRBG->CSRNG->EDN->KM) bring-up observers --------------
    # Shared poll/check helpers for any entropy-consumer test (the SEQUENCES that
    # drive the bring-up live in seq_lib/sep_esrc_bringup_seq.py). They read the
    # tb_top entropy probe ports, so they ride on the standard model.
    async def _wait_high(self, sig, timeout: int) -> bool:
        for _ in range(timeout):
            await RisingEdge(cocotb.top.clk_i)
            await ReadOnly()
            # A poll for a nonzero value fails closed on X: an unknown node
            # never reads as set, so the wait times out. KM SRAM word0 is
            # memory content and is legitimately X before its first store.
            if self.rd(sig, allow_unknown=True):
                return True
        return False

    async def wait_seed_ready(self, timeout: int = 60_000) -> bool:
        """Wait until ESRC accumulates a seed and presents it to CSRNG."""
        return await self._wait_high(cocotb.top.drbg_seed_valid_o, timeout)

    async def poll_internal_irq(self, idx: int, expect: int, *, timeout: int = 400) -> int:
        """Poll ``sep_internal_interrupts_probe_o[idx]`` until it equals ``expect``.

        Returns the last sampled vector. The aggregate has no CSR mirror, so
        this is the frontdoor-equivalent observation of one PIC wire.
        """
        sample = 0
        for _ in range(timeout):
            await RisingEdge(cocotb.top.clk_i)
            await ReadOnly()
            sample = self.rd_known(cocotb.top.sep_internal_interrupts_probe_o, mask=1 << idx)
            if ((sample >> idx) & 1) == expect:
                return sample
        raise AssertionError(
            f"sep_internal_interrupts[{idx}] did not become {expect} in "
            f"{timeout} cycles (vec=0x{sample:x})"
        )

    async def report_entropy_stall(self, window: int = 4_000) -> None:
        """Log WHERE the ESRC->DRBG chain stopped after a seed/genbits timeout.

        A bounded wait must name the handshake that did not
        retire, not just report "no seed". The chain is
        decor -> BIW/whitener -> compressor -> ESRC FIFO -> DRBG seed packer, and
        tb_top exposes a strobe at each stage, so counting them over one window
        attributes the stall to a specific stage instead of the whole datapath.
        """
        dut = cocotb.top
        strobes = {
            "esrc_decor_valid": dut.esrc_decor_valid_o,
            "esrc_whiten_push": dut.esrc_whiten_push_o,
            "esrc_compress_vld": dut.esrc_compress_vld_o,
            "drbg_seed_valid": dut.drbg_seed_valid_o,
        }
        counts = dict.fromkeys(strobes, 0)
        for _ in range(window):
            await RisingEdge(dut.clk_i)
            await ReadOnly()
            for name, sig in strobes.items():
                counts[name] += 1 if self.rd(sig, allow_unknown=True) else 0

        self.logger.error(
            "entropy stall over %d cycles: %s (noise_active=%d ro_enable=0x%03x "
            "last_compress_data=0x%08x)",
            window,
            " ".join(f"{k}={v}" for k, v in counts.items()),
            self.rd(dut.esrc_noise_active_o, allow_unknown=True),
            self.rd(dut.esrc_ro_enable_o, allow_unknown=True),
            self.rd(dut.esrc_compress_data_o, allow_unknown=True),
        )

        # Frontdoor status: FIFO level and health-test result decide whether the
        # ESRC itself is stuck or the DRBG side is not draining.
        #
        # Every read is bounded and failure-tolerant: a fabric that never released
        # is one cause of the stall, and an unbounded read here would turn the
        # attributed failure into a bare sim timeout. The strobe counts above are
        # already logged, so a wedged CSR path degrades to "counts logged, CSR
        # unreadable".
        from env.sep_axi_agent import SepAxiOp
        from seq_lib.sep_axi_access_seq import SepAxiAccessSeq
        from seq_lib.sep_esrc_bringup_seq import (
            ESRC_CTRL,
            ESRC_FIFO_STATUS,
            ESRC_HEALTH_TEST_CTRL,
            ESRC_HEALTH_TEST_STATUS,
            ESRC_MAIN_SM_STATUS,
        )

        for label, addr in (
            ("ESRC_CTRL", ESRC_CTRL),
            ("ESRC_FIFO_STATUS", ESRC_FIFO_STATUS),
            ("ESRC_HEALTH_TEST_CTRL", ESRC_HEALTH_TEST_CTRL),
            ("ESRC_HEALTH_TEST_STATUS", ESRC_HEALTH_TEST_STATUS),
            ("ESRC_MAIN_SM_STATUS", ESRC_MAIN_SM_STATUS),
        ):
            seq = SepAxiAccessSeq(op=SepAxiOp.READ, addr=addr)
            try:
                await with_timeout(self.start_seq(seq), _STALL_CSR_TIMEOUT_NS, "ns")
            except SimTimeoutError:
                self.logger.error(
                    "entropy stall: %s (0x%08x) = <no AXI response within %d ns> -- the "
                    "CSR path is wedged too, not just the entropy chain; skipping the "
                    "remaining status reads",
                    label,
                    addr,
                    _STALL_CSR_TIMEOUT_NS,
                )
                break
            self.logger.error("entropy stall: %s (0x%08x) = 0x%08x", label, addr, seq.rdata)

    async def wait_genbits(self, timeout: int = 60_000) -> bool:
        """Wait until the CSRNG CTR_DRBG produces a genbits block."""
        return await self._wait_high(cocotb.top.drbg_genbits_vld_o, timeout)

    async def wait_km_entropy_handshake(self, timeout: int = 60_000) -> bool:
        """Wait for a post-mux tvalid && tready -- the KM consumed an entropy word."""
        dut = cocotb.top
        for _ in range(timeout):
            await RisingEdge(dut.clk_i)
            await ReadOnly()
            if self.rd(dut.km_entropy_tvalid_o) and self.rd(dut.km_entropy_tready_o):
                return True
        return False

    async def wait_km_consumed_word(self, timeout: int = 2_000) -> bool:
        """Poll KM SRAM word0 for the store the KM firmware issues after its
        DRBG-sampler DATA read. Non-zero only: a liveness marker that the KM CPU
        got past the blocking read and reached its store, NOT a check that the
        right word landed. Follow it with check_km_sram_word_matches_consumed()
        for that. (A genbits word is 0 with probability 2^-32.)"""
        return await self._wait_high(cocotb.top.km_sram_word0_o, timeout)

    def check_km_sram_word_matches_consumed(self) -> int:
        """Value-compare KM SRAM word0 against the word the DUT delivered on the
        EDN->KM AXIS endpoint.

        `km_rom_entropy.S` reads one DRBG-sampler DATA word and stores exactly
        that word to KM SRAM base + 0, which `km_sram_word0_o` probes. So the
        first CHK5_km AXIS beat the scoreboard tapped is the expected SRAM
        content: a wrong-word store, a dropped store, or a store to the wrong
        offset all fail here, where the non-zero poll passes. Logged under
        `CHK-KM-SRAM` so the plan can cite it apart from the handshake row.
        """
        delivered = self.drbg_sb.km_words()
        assert delivered, (
            "CHK-KM-SRAM: no EDN->KM AXIS beat was tapped, so there is no "
            "delivered word to compare KM SRAM word0 against"
        )
        expected = delivered[0]
        actual = self.rd(cocotb.top.km_sram_word0_o)
        assert actual == expected, (
            f"CHK-KM-SRAM FAIL: KM SRAM word0 = 0x{actual:08x}, but the KM "
            f"consumed 0x{expected:08x} on the AXIS endpoint "
            f"({len(delivered)} beat(s) tapped)"
        )
        self.logger.info(
            "CHK-KM-SRAM PASS: KM SRAM word0 = 0x%08x == the delivered "
            "EDN->KM AXIS word (beat 1 of %d)",
            actual,
            len(delivered),
        )
        return actual

    async def check_entropy_alerts_zero(self):
        """Read + assert CSRNG/EDN err_code + recov_alert are all zero."""
        from seq_lib.sep_esrc_bringup_seq import SepEsrcAlertReadSeq

        seq = SepEsrcAlertReadSeq()
        await self.start_seq(seq)
        assert seq.csrng_err == 0, f"CSRNG ERR_CODE=0x{seq.csrng_err:08x}"
        assert seq.csrng_alert == 0, f"CSRNG RECOV_ALERT=0x{seq.csrng_alert:08x}"
        assert seq.edn_err == 0, f"EDN ERR_CODE=0x{seq.edn_err:08x}"
        assert seq.edn_alert == 0, f"EDN RECOV_ALERT=0x{seq.edn_alert:08x}"
        self.logger.info(
            "CHK-ALERTS-ZERO PASS: CSRNG/EDN ERR_CODE=0 RECOV_ALERT=0 (0x%x 0x%x 0x%x 0x%x)",
            seq.csrng_err,
            seq.csrng_alert,
            seq.edn_err,
            seq.edn_alert,
        )
        return seq

    def start_esrc_noise_driver(
        self, *, noise_mode: str = "unbiased", seed_base: int = 0x1234_5678
    ):
        """Drive tb_top.esrc_noise_ext_i every cycle and return the forked task.

        ``+esrc_noise_force`` only routes this port onto the ring-oscillator
        noise input; it does not generate anything. A test that brings the
        entropy stack up WITHOUT the DRBG scoreboard -- firmware doing its own
        ESRC/CSRNG/EDN programming, for instance -- still needs the raw bits
        driven, or the health window never fills and the boot gate never opens.

        This is the drive half of ``SepDrbgScoreboard`` with no golden chain and
        no scoring: the caller gets entropy that moves, not entropy that is
        graded. A test that needs the values checked wants ``bring_up_entropy``.

        Kill the returned task before the test ends. A forked task still writing
        a DUT port while the simulator tears down segfaults the run, which shows
        up as a non-zero exit on an otherwise passing test.
        """
        dut = cocotb.top
        gen = EntropyNoiseModel()
        gen.configure(noise_mode, seed_base=seed_base)

        async def _drive() -> None:
            while True:
                await RisingEdge(dut.clk_i)
                await NextTimeStep()
                dut.esrc_noise_ext_i.value = gen.step_all()

        return cocotb.start_soon(_drive())

    async def assert_noise_force_active(self, cycles: int = 16) -> None:
        """Prove +esrc_noise_force took: lane-0's actual DUT noise_i tracks the
        driven raw-noise bit, and the driven noise actually toggles (not stuck)."""
        dut = cocotb.top
        toggled = False
        prev = self.rd(dut.esrc_noise_o)
        for _ in range(cycles):
            await RisingEdge(dut.clk_i)
            await ReadOnly()
            drv = self.rd(dut.esrc_noise_o)
            act = self.rd(dut.esrc_noise_active_o)
            assert act == (drv & 0x1), (
                f"+esrc_noise_force not active: lane0 noise_i={act} != driven bit {drv & 0x1}"
            )
            toggled = toggled or (drv != prev)
            prev = drv
        assert toggled, "driven ESRC noise is static (LFSR not toggling)"

    async def assert_noise_force_routed(self) -> None:
        """Prove +esrc_noise_force routed the port, without needing live noise.

        The drive half of ``assert_noise_force_active`` requires a running
        generator, so a test that holds the raw noise at a constant on purpose
        -- the persistent-failure trips, which need a degenerate stream --
        cannot use it. This drives both values by hand and checks lane-0's
        actual DUT noise_i follows each, which is the routing contract alone.
        """
        dut = cocotb.top
        for bit in (1, 0):
            dut.esrc_noise_ext_i.value = bit
            await RisingEdge(dut.clk_i)
            await ReadOnly()
            act = self.rd(dut.esrc_noise_active_o)
            assert act == bit, (
                f"+esrc_noise_force not active: drove raw noise {bit} and lane0 "
                f"noise_i read {act}; the plusarg did not route the port"
            )
            # Leave ReadOnly before the next iteration drives the port again:
            # a write in that phase is a RuntimeError, not a DUT failure.
            await NextTimeStep()
        self.logger.info(
            "CHK-NOISE-FORCE PASS: lane0 noise_i followed the driven bit both ways, "
            "so +esrc_noise_force routed esrc_noise_ext_i"
        )

    async def bring_up_entropy(
        self,
        cfg=None,
        *,
        strict: bool = True,
        score_km: bool | str = True,
        score_sinks: dict | None = None,
    ):
        """Bring up the ESRC->DRBG->CSRNG->EDN stack and return the started CHK1..CHK5
        scoreboard (also ``self.drbg_sb``), which drives deterministic ESRC noise.

        The caller does the consumer-specific steps afterwards: FIFO drain, ``wait_genbits``,
        and consumer release. ``cfg`` defaults to ``SepEntropyCfg()``.

        ``strict=True`` makes the scoreboard ``report()`` raise on any golden
        mismatch or under-evidence stream. ``score_km`` defaults to True for
        bit-exact CHK5_km golden-match. Set ``score_km="observe"`` for a consumer
        whose pull order is not golden-predictable (e.g. real ``rom_main``): CHK1..CHK4
        stay strict, and CHK5 requires real KM tvalid&&tready beats without a
        bit-exact value compare.

        ``score_sinks`` is an optional name->mode map for the crypto EDN sinks
        (``aes``/``kmac``/``otbn_rnd``/``otbn_urnd``) and the entropy-pool sink
        (``pool``, EDN endpoint [2]). Each is ``"golden"`` (bit-exact ROUTING:
        each post-adapter beat equals the AXIS1/AXIS2 word granted that cycle;
        one or more live crypto clients are legal), ``"membership"`` (each
        word is a CHK4 genbits word), ``"observe"`` (>=1 real beat, no value
        compare), or omitted (disabled). The pool is a sole client of mux [2],
        so ``{"pool": "golden"}`` is always legal.
        """
        from env.sep_drbg_scoreboard import SepDrbgScoreboard
        from seq_lib.sep_esrc_bringup_seq import (
            SepEntropyCfg,
            SepEsrcConfigSeq,
            SepEsrcEnableEdnSeq,
            SepEsrcEnableGeneratorsSeq,
        )

        if cfg is None:
            cfg = SepEntropyCfg()
        self.entropy_cfg = cfg
        self.drbg_sb = SepDrbgScoreboard(
            cocotb.top,
            self.logger,
            strict=strict,
            golden_kwargs=cfg.golden_kwargs(),
            chk2_backdoor=cfg.chk2_backdoor,
            score_km=score_km,
            score_sinks=score_sinks,
        )
        self.drbg_sb.start()
        await self.assert_noise_force_active()
        await self.start_seq(SepEsrcConfigSeq("esrc_config", cfg=cfg))
        await self.start_seq(SepEsrcEnableGeneratorsSeq("esrc_enable_gens"))
        if not await self.wait_seed_ready():
            await self.report_entropy_stall()
            raise AssertionError("ESRC never produced a seed (drbg_seed_valid_o)")
        self.drbg_sb.enable_chk5()
        await self.start_seq(SepEsrcEnableEdnSeq("esrc_enable_edn"))
        return self.drbg_sb

    # --- CHK2 frontdoor: concurrent ESRC FIFO_RDATA drain ---------------------
    # Shared by entropy tests so the FIFO never overflows during a long genbits
    # phase (the DRBG taps the pre-FIFO whitener, so the frontdoor drain is
    # non-invasive) and CHK2 sees every post-whitener word.
    async def _drain_fifo_once(self) -> None:
        from seq_lib.sep_esrc_bringup_seq import SepEsrcFifoDrainSeq

        batch = SepEsrcFifoDrainSeq("esrc_fifo_drain")
        await self.start_seq(batch)
        if batch.words:
            self.drbg_sb.check_fifo_frontdoor(batch.words)

    async def _fifo_drain_loop(self) -> None:
        while not self._drain_stop:
            await self._drain_fifo_once()
            await ClockCycles(cocotb.top.clk_i, 40)

    def start_fifo_drain(self) -> None:
        """Fork the concurrent FIFO drain (no-op for backdoor-CHK2 configs)."""
        self._drain_stop = False
        self._drain_task = (
            None
            if getattr(self, "entropy_cfg", None) and self.entropy_cfg.chk2_backdoor
            else cocotb.start_soon(self._fifo_drain_loop())
        )

    async def stop_fifo_drain(self) -> None:
        """Stop the drain and sweep the FIFO tail for the final CHK2 words."""
        if getattr(self, "_drain_task", None) is not None:
            self._drain_stop = True
            await self._drain_task
            await self._drain_fifo_once()

    async def run_scenario(self) -> None:
        """Override with the per-test stimulus."""
        raise NotImplementedError

    @staticmethod
    def _sha256_file(path: str) -> tuple[str, int]:
        """Return ``(hexdigest, size)`` for ``path``. Raises if the file is missing."""
        digest = hashlib.sha256()
        with open(path, "rb") as fh:
            for chunk in iter(lambda: fh.read(1 << 20), b""):
                digest.update(chunk)
        return digest.hexdigest(), os.path.getsize(path)

    def _log_firmware_identity(self, itcm_hex: str, dtcm_hex: str) -> None:
        """Record sha256 of the staged TCM images, then check their build identity.

        Firmware checkers live in the image. A log that names only the path
        cannot prove which bytes were loaded, and the bytes alone cannot prove
        which source they came from; CHK-FW-IDENTITY closes that.
        """
        parts = []
        for label, path in (("itcm", itcm_hex), ("dtcm", dtcm_hex)):
            digest, nbytes = self._sha256_file(path)
            parts.append(f"{label}={path} sha256={digest} bytes={nbytes}")
        self.logger.info("RUN-IDENTITY-FW: %s", " ".join(parts))
        self._check_firmware_identity(itcm_hex, dtcm_hex)

    @staticmethod
    def _tcm_hex_bytes(path: str) -> bytes:
        """Byte stream of a ``objcopy -O verilog`` image, address lines dropped."""
        out = bytearray()
        with open(path) as fh:
            for line in fh:
                if not line.startswith("@"):
                    out.extend(int(tok, 16) for tok in line.split())
        return bytes(out)

    def _check_firmware_identity(self, itcm_hex: str, dtcm_hex: str) -> None:
        """CHK-FW-IDENTITY: the loaded image was built from the source at this commit.

        The firmware build (``fw/fw.mk``) compiles ``FW-BUILD-ID:<digest>`` into
        every EL2 TCM image, where ``<digest>`` is ``fw/fw_src_digest.py`` over
        the firmware source tree at build time. This reads that string out of
        the same files RUN-IDENTITY-FW hashed and compares it with the digest of
        the tree this test runs from, which RUN-IDENTITY binds to a commit. An
        image left over from other source, or built without the identity,
        fails here.
        """
        import importlib.util

        script = _OSS_HW_ROOT / "sys" / "sep" / "dv" / "fw" / "fw_src_digest.py"
        spec = importlib.util.spec_from_file_location("sep_fw_src_digest", script)
        assert spec is not None and spec.loader is not None, f"cannot load {script}"
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        expected = mod.digest(_OSS_HW_ROOT.parent)

        # Both images must carry it: the firmware's checkers run from ICCM, so a
        # current DCCM image beside a stale ICCM image is not a current build.
        for label, path in (("itcm", itcm_hex), ("dtcm", dtcm_hex)):
            data = self._tcm_hex_bytes(path)
            at = data.find(mod.MARKER)
            assert at >= 0, (
                f"CHK-FW-IDENTITY FAIL: no FW-BUILD-ID string in the {label} image "
                f"{path}; it was not built by the current fw/fw.mk"
            )
            start = at + len(mod.MARKER)
            got = data[start : start + 64].decode("ascii", "replace")
            assert got == expected, (
                f"CHK-FW-IDENTITY FAIL: the {label} image {path} was built from source "
                f"digest {got}, but the firmware source at this commit digests to "
                f"{expected}; the image is stale"
            )
        self.logger.info(
            "CHK-FW-IDENTITY PASS: the itcm and dtcm images both carry FW-BUILD-ID %s, "
            "equal to the digest of the firmware source at this commit (%d files)",
            expected,
            len(mod.source_files(_OSS_HW_ROOT.parent)),
        )

    def _log_run_identity(self) -> None:
        """Record the commit, tree state and run directory in the log.

        A log that names no commit cannot be bound to the sources it is
        offered as evidence for, and the identity cannot be recovered after
        the run.
        """
        import os
        import subprocess

        git_dir = os.path.dirname(os.path.abspath(__file__))

        def _git(*args, timeout=15):
            """Run one git command. Returns (ok, stdout_bytes).

            ok is False for a failed spawn, a nonzero exit AND a timeout, so a
            caller can tell "git said no" from "git said nothing". Treating
            those as an empty answer is what lets an unanswered question read
            as a negative answer.
            """
            # GIT_OPTIONAL_LOCKS=0 stops `git status` from taking the index
            # lock to refresh it, so concurrent leaves of one regression do
            # not contend on the lock.
            try:
                cp = subprocess.run(
                    ["git", *args],
                    cwd=git_dir,
                    capture_output=True,
                    timeout=timeout,
                    env={**os.environ, "GIT_OPTIONAL_LOCKS": "0"},
                )
            except (OSError, subprocess.SubprocessError):
                return False, b""
            return cp.returncode == 0, cp.stdout

        head_ok, head_out = _git("rev-parse", "HEAD", timeout=10)
        head = head_out.decode("utf-8", "replace").strip() if head_ok else ""
        # An env override names the commit the CALLER believes was built. It is
        # reported next to live HEAD rather than in place of it: a stale export
        # would otherwise pair commit A with tree B's dirtiness, and nothing in
        # the log would show it.
        env_rev = os.environ.get("SEP_DV_GIT_REV") or ""
        rev = env_rev or head
        rev_note = ""
        if env_rev and head_ok and env_rev != head:
            rev_note = f" (SEP_DV_GIT_REV; live HEAD={head} -- THEY DISAGREE)"
        elif env_rev and not head_ok:
            rev_note = " (SEP_DV_GIT_REV; live HEAD unavailable, not corroborated)"

        # Tree state comes from two independent git commands. `git diff HEAD`
        # binds the tracked sources: an empty diff is a clean tracked tree, and
        # a non-empty diff is hashed. `git status` adds the untracked files,
        # which the diff does not cover. `--binary` puts the content of a
        # changed binary file in the digest; `--no-ext-diff` and `--no-color`
        # keep the bytes independent of the user's git config.
        #
        # The leaf fails when neither answer is available: a log that cannot
        # say which sources ran is not evidence for them.
        diff_ok, diff_out = _git(
            "diff", "HEAD", "--binary", "--no-ext-diff", "--no-color", timeout=120
        )
        dirty_ok, dirty_out = _git("status", "--porcelain", "-uall", timeout=120)
        dirty = dirty_out.decode("utf-8", "replace") if dirty_ok else ""
        status_clean = dirty_ok and not dirty.strip()
        diff_digest = hashlib.sha256(diff_out).hexdigest()[:16] if diff_ok else ""
        if not diff_ok and not status_clean:
            raise AssertionError(
                "RUN-IDENTITY FAIL: `git diff HEAD` failed and `git status` "
                + ("reports uncommitted files" if dirty_ok else "failed")
                + f" (cwd {git_dir}), so this run cannot be bound to the sources it ran"
            )
        if status_clean:
            state = ""
        elif diff_ok and not diff_out:
            state = (
                " (tracked tree clean"
                + (
                    "; untracked files present"
                    if dirty_ok
                    else "; untracked files not checked: git status failed"
                )
                + ")"
            )
        else:
            state = f" (tree dirty: tracked-diff-sha256={diff_digest or 'unavailable'})"
        self.logger.info(
            "RUN-IDENTITY: commit=%s%s%s work-dir=%s",
            rev or "unknown",
            rev_note,
            state,
            os.environ.get("SEP_DV_RUN_DIR") or os.getcwd(),
        )
        plus_parts = []
        for key in sorted(cocotb.plusargs):
            val = cocotb.plusargs[key]
            plus_parts.append(f"+{key}" if val is True or val == "" else f"+{key}={val}")
        self.logger.info("RUN-IDENTITY-PLUSARGS: %s", " ".join(plus_parts) or "(none)")
        # KM ROM is loaded by tb_backdoor_mem from +km_rom_hex. A path-only
        # plusarg cannot join those bytes, so the staged file is hashed. The
        # c_compile log line KM-ROM-IDENTITY (sep_sim_cfg.toml
        # [c_build.km_rom_main] / [c_build.km_rom_blob]) prints the same image
        # sha256 next to its source, which joins this run to that build.
        km_rom = cocotb.plusargs.get("km_rom_hex")
        if km_rom and km_rom is not True:
            km_path = (
                km_rom if os.path.isabs(str(km_rom)) else os.path.join(os.getcwd(), str(km_rom))
            )
            if os.path.isfile(km_path):
                digest, nbytes = self._sha256_file(km_path)
                self.logger.info(
                    "RUN-IDENTITY-FW: km_rom=%s sha256=%s bytes=%d", km_path, digest, nbytes
                )
            else:
                self.logger.info("RUN-IDENTITY-FW: km_rom=%s missing -- bytes not hashed", km_path)
        # Build identity: the binary this process IS. A commit names the
        # sources on disk at time 0, which is not the same claim as "the model
        # executing was compiled from them" -- a reused simv, or a rebuild that
        # landed after the flist was read, produces a truthful-looking commit
        # line for a run that executed something else. The digest is the part
        # that cannot be recovered after the fact.
        #
        # Hashed ONCE PER BUILD, not once per test. A regression reuses one
        # binary across every leaf, and sha256 runs at ~45 MB/s here, so a
        # 512 MiB VCS simv would cost ~11 s on every one of them. The digest is
        # a property of the binary, so it is cached beside it, keyed on size
        # and mtime; an unwritable or mismatched cache costs a rehash, never a
        # wrong answer. The line says which it was: `cached` is trusted on
        # (size, mtime) rather than on content, so a reader chasing a
        # provenance question knows to delete the sidecar and rerun to get a
        # digest computed from the bytes.
        try:
            exe = os.path.realpath("/proc/self/exe")
            st = os.stat(exe)
            key = f"{st.st_size} {int(st.st_mtime)}"
            cache = Path(f"{exe}.sha256")
            exe_digest = ""
            digest_src = "computed"
            try:
                cached_key, cached_digest = cache.read_text().split("\n")[0].rsplit(" ", 1)
                if cached_key == key:
                    exe_digest = cached_digest.strip()
                    digest_src = "cached"
            except (OSError, ValueError):
                pass
            if not exe_digest:
                if st.st_size <= _SIM_BINARY_HASH_MAX_BYTES:
                    h = hashlib.sha256()
                    with open(exe, "rb") as fh:
                        for chunk in iter(lambda: fh.read(1 << 20), b""):
                            h.update(chunk)
                    exe_digest = h.hexdigest()[:16]
                    try:
                        # Atomic, because concurrent leaves of one regression
                        # race here; a torn file would be read back as a
                        # mismatched key and simply rehashed.
                        tmp = cache.with_suffix(f".sha256.{os.getpid()}")
                        tmp.write_text(f"{key} {exe_digest}\n")
                        os.replace(tmp, cache)
                    except OSError:
                        pass
                else:
                    exe_digest = f"not-hashed(>{_SIM_BINARY_HASH_MAX_BYTES}B)"
            self.logger.info(
                "RUN-IDENTITY-BUILD: sim-binary=%s sha256=%s (%s) bytes=%d mtime=%d git-head=%s",
                exe,
                exe_digest,
                digest_src,
                st.st_size,
                int(st.st_mtime),
                rev or "unknown",
            )
        except (OSError, ValueError) as exc:
            # Say so rather than omit the line: a missing build identity is a
            # gap a reader must see, not one they should have to infer.
            self.logger.info(
                "RUN-IDENTITY-BUILD: unavailable (%s) -- this log cannot be "
                "bound to the build that produced it",
                type(exc).__name__,
            )
        # WHICH files, not just that some were. "tree dirty" alone cannot be
        # acted on after the run: a reader has to decide whether any
        # uncommitted file was on this test's proof path, and the boolean makes
        # that unanswerable from the artifact.
        #
        # Untracked files are included. The question is what the run executed,
        # and an untracked module on a proof path is as unrecorded as a
        # modified one -- `--untracked-files=no` would hide exactly the new
        # test or generated image most likely to matter.
        if diff_ok and diff_out and not dirty_ok:
            # Paths from the diff headers, so a failed `git status` still names
            # the modified files.
            tracked = [
                line[len(b"diff --git a/") :].split(b" b/", 1)[0].decode("utf-8", "replace")
                for line in diff_out.splitlines()
                if line.startswith(b"diff --git a/")
            ]
            shown = tracked[:_RUN_IDENTITY_MAX_PATHS]
            self.logger.info(
                "RUN-IDENTITY-DIRTY: %d tracked file(s) modified, "
                "tracked-diff-sha256=%s%s paths=%s (untracked files not checked: "
                "git status failed)",
                len(tracked),
                diff_digest,
                "" if len(tracked) == len(shown) else f" (first {len(shown)} shown)",
                ",".join(shown) or "none",
            )
        if dirty_ok and dirty.strip():
            # Tracked modifications and untracked files are reported
            # separately, because they answer the proof-path question
            # differently and mixing them buries the answer: `-uall` expands a
            # single untracked venv/ into four figures of paths, and a 40-path
            # cap then hides the one modified source that mattered. Tracked
            # paths are listed; untracked are counted and named by top-level
            # area, which is enough to see whether a new module could be on the
            # proof path.
            tracked, untracked = [], []
            for line in dirty.splitlines():
                # Porcelain v1: two status characters, a space, then the path.
                # Slice the RAW line -- stripping the block first eats the
                # leading space of an unstaged-only first entry (" M path") and
                # cuts a character off that path, which is precisely the name a
                # reader greps against the proof path.
                if len(line) <= 3:
                    continue
                path = line[3:].strip().strip('"')
                (untracked if line.startswith("??") else tracked).append(path)
            digest = diff_digest or "unavailable"
            shown = tracked[:_RUN_IDENTITY_MAX_PATHS]
            self.logger.info(
                "RUN-IDENTITY-DIRTY: %d tracked file(s) modified, "
                "tracked-diff-sha256=%s%s paths=%s",
                len(tracked),
                digest,
                "" if len(tracked) == len(shown) else f" (first {len(shown)} shown)",
                ",".join(shown) or "none",
            )
            if untracked:
                # Group by the first two path components, so "venv/bin" is one
                # area rather than 300, and a new DV module still shows as
                # "hw/sys" -- specific enough to ask "could that be on my
                # proof path?" without reprinting the list.
                areas = sorted({"/".join(u.split("/")[:2]) for u in untracked})
                shown_areas = areas[:_RUN_IDENTITY_MAX_PATHS]
                self.logger.info(
                    "RUN-IDENTITY-UNTRACKED: %d file(s) in %d area(s)%s: %s "
                    "(not covered by tracked-diff-sha256)",
                    len(untracked),
                    len(areas),
                    "" if len(areas) == len(shown_areas) else f", first {len(shown_areas)} shown",
                    ",".join(shown_areas),
                )

    def _install_evidence_filter(self, filt: "_EvidenceFilter") -> None:
        """Put the evidence filter where every CHK-* record passes through it.

        A logger-level filter sees only records logged on that exact logger --
        it is not applied to records propagating up from children. Sequences
        grade their own contracts on their own loggers (`cocotb.log`, the
        component tree), so filtering `self.logger` alone drops them and the
        leaf reads as grading nothing. Handler-level filters do see propagated
        records, so the handlers the simulator already installed are the one
        place that observes the whole run.
        """
        handlers = list(logging.getLogger().handlers)
        for name in ("cocotb", "test", "gpi", "uvm"):
            handlers.extend(logging.getLogger(name).handlers)
        installed = 0
        for handler in handlers:
            if filt not in handler.filters:
                handler.addFilter(filt)
                installed += 1
        # No handler yet means nothing has emitted and the run would grade
        # nothing at all, so fall back to the loggers a check is logged on.
        if not installed:
            for name in ("cocotb", "test", "uvm"):
                logging.getLogger(name).addFilter(filt)
        self.logger.addFilter(filt)

    def _finalize_evidence(self) -> None:
        """Report the evidence this run produced, and grade it if the leaf asked.

        Runs only after run_scenario() returns normally. A test that already
        failed raised, and this must not turn that into a different complaint.

        `own` excludes the records sep_base_test emits itself, so a declared
        floor grades what the leaf proved rather than what bring-up logged.
        """
        seen = sorted(getattr(self, "_evidence", _EvidenceFilter()).seen)
        own = [c for c in seen if c not in _EvidenceFilter.BASE_IDS]
        required = tuple(self.required_evidence)
        missing = [check_id for check_id in required if check_id not in seen]

        self.logger.info(
            "EVIDENCE_SUMMARY test=%s observed=%d own=%d required=%d missing=%d ids=%s",
            self.get_type_name(),
            len(seen),
            len(own),
            len(required),
            len(missing),
            ",".join(seen) or "-",
        )

        problems: list[str] = []
        if not own and self.get_type_name() not in _EvidenceFilter.NO_OWN_EVIDENCE:
            problems.append(
                "no CHK-* PASS record of its own -- a run that grades nothing cannot "
                "be a pass. If this leaf's checks live in its sequence, log them "
                "there; if it genuinely checks nothing, that is the finding"
            )
        if self.min_evidence and len(own) < self.min_evidence:
            problems.append(
                f"{len(own)} distinct CHK-* PASS record(s) of its own, "
                f"expected at least {self.min_evidence}"
            )
        if missing:
            problems.append("never emitted: " + ", ".join(missing))
        if problems:
            raise AssertionError(
                f"EVIDENCE FAIL {self.get_type_name()}: "
                + "; ".join(problems)
                + " -- the run exited cleanly without grading what it claims to grade"
            )

    async def run_phase(self) -> None:
        self.raise_objection()
        self._log_run_identity()
        await self.run_scenario()
        self._finalize_evidence()
        self.drop_objection()
