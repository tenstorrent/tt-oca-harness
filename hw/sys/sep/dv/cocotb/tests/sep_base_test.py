# SPDX-License-Identifier: Apache-2.0
"""SEP UVM base test helpers.

Concrete tests inherit this class for common import setup, environment build,
clock/reset bring-up, CPU hold/run controls, and fuse-sense synchronization.
Real fuse-sense runs that stage an eFuse image automatically compare the sensed
shadow array against that image after sense-done.
"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path
from typing import Awaitable, Callable

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles, ReadOnly, RisingEdge, with_timeout
from pyuvm import ConfigDB, uvm_test

# Intentional OSS exception: this JTAG AXI-Lite helper must run on the public
from ocah_axi_vip import OcahAxiLiteMasterAgent

try:  # cocotb < 2.0
    from cocotb.result import SimTimeoutError
except ImportError:  # cocotb >= 2.0
    from cocotb.triggers import SimTimeoutError

# The cocotb runner only puts the test dir on sys.path. Make the cocotb root
# (env/, seq_lib/) and shared OSS VIP root importable before concrete tests
# import env/seq_lib/VIP modules.
_COCOTB_ROOT = Path(__file__).resolve().parents[1]
_OSS_HW_ROOT = Path(__file__).resolve().parents[5]
for _path in (_COCOTB_ROOT, _OSS_HW_ROOT / "common" / "dv" / "vip"):
    _path_str = str(_path)
    if _path_str not in sys.path:
        sys.path.insert(0, _path_str)

from env.sep_env import SepEnv
from env.sep_env_cfg import SepEnvCfg
from env.sep_efuse_image import SepEfuseImage


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


class sep_base_test(uvm_test):
    """Shared SEP test: env build, clock/reset bring-up, scenario hook."""

    build_env = True

    @staticmethod
    def random_seed() -> int:
        """Runner-provided seed (run_dv.py --seed -> RANDOM_SEED); default 1."""
        return int(os.environ.get("RANDOM_SEED", "1"), 0)

    @staticmethod
    def rd(sig) -> int:
        """Read a DUT signal as int, resolving X/Z to zero via the env policy."""
        try:
            return int(sig.value)
        except Exception:
            return 0

    @staticmethod
    def _set_if_exists(dut, name: str, value: int) -> None:
        try:
            getattr(dut, name).value = value
        except AttributeError:
            pass

    def build_phase(self) -> None:
        self.cfg = SepEnvCfg("cfg")
        self._efuse_compare_image: SepEfuseImage | None = None
        self.cfg.randomize_timing(self.random_seed())
        self.logger.info(
            "SEP timing: sys_clk_period=%dns (seed=%d)",
            self.cfg.sys_clk_period_ns,
            self.random_seed(),
        )
        ConfigDB().set(None, "*", "cfg", self.cfg)
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

    def drive_idle_defaults(self, dut=None, *, cpu_run: bool = False, rst_vec: int = 0) -> None:
        """Drive stable top-level controls before reset is released."""
        if dut is None:
            dut = cocotb.top
        dut.ext_boot_seq_done_i.value = 1
        dut.mpc_reset_run_req.value = 1 if cpu_run else 0
        # eFuse program-fail injection is seeded via the +sep_efuse_prog_fail_seed
        # plusarg inside the generic efuse model (the old efuse_prog_fail_seed_i port
        # was retired with the bare-sep responders).
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

        check_efuse_shadow_backdoor(self.logger, self._efuse_compare_image)

    async def _wait_fuse_sense(self, max_cycles: int) -> None:
        """Poll sep_fuse_sense_done_o until it asserts (or time out), then settle.

        This is the canonical "fabric released" gate for every bring-up. It is
        correct in both modes: with +skip_fuse_sense the RTL asserts the done
        flop ~1 cycle after reset release (no wasted time), and without it we sit
        through the real 256-word sense and compare the sensed shadow against the
        staged eFuse image. Gating on the DUT's actual done signal is more robust
        than a guessed fixed cycle count.
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

    async def bring_up_no_cpu(self, *, max_cycles: int = 20_000) -> None:
        """Bring up the DUT (CPU held off; the stub drives the LSU AXI from the
        cocotb master), gating on fuse-sense-done before releasing stimulus."""
        dut = cocotb.top
        self.logger.info("Bringing up clocks and reset (CPU held off)")
        dut.rst_ni.value = 0
        self.drive_idle_defaults(dut, cpu_run=False)
        self.start_clocks(dut)
        await ClockCycles(dut.clk_i, 20)
        self.logger.info("Releasing rst_ni")
        dut.rst_ni.value = 1
        await self._wait_fuse_sense(max_cycles)
        self.cfg.reset_done.set()

    async def bring_up_and_wait_fuse_sense(self, *, max_cycles: int = 20_000) -> None:
        """Alias for bring_up_no_cpu, kept for eFuse-test intent. Both gate on
        real fuse-sense-done."""
        await self.bring_up_no_cpu(max_cycles=max_cycles)

    async def resense(self, *, hold_cycles: int = 20, max_cycles: int = 20_000) -> None:
        """Re-pulse rst_ni to trigger a fresh fuse-sense (clocks already running).

        The OTP responder reloads its image on reset assertion, so a test can
        regenerate the eFuse image between sense cycles and resense to pick up
        the new contents.
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
    ) -> None:
        """Bring up the DUT with the CPU owning its master buses."""
        dut = cocotb.top
        self.logger.info("Bringing up clocks and reset (CPU run, rst_vec=0x%x)", rst_vec)
        dut.rst_ni.value = 0
        self.drive_idle_defaults(dut, cpu_run=True, rst_vec=rst_vec)
        # Match the old tb wiring for CPU boot: EL2 debug reset followed cold reset.
        self._set_if_exists(dut, "dbg_rstb_i", 0)
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
        self.logger.info(
            "CPU boot: post-fuse reset state sep_rst_n=%d cpu_rst_n=%d run_ack=%d iccm_act=%d",
            self.rd(dut.dbg_sep_reset_n_o),
            self.rd(dut.sep_cpu_reset_n_o),
            self.rd(dut.o_cpu_run_ack_o),
            self.rd(dut.dbg_iccm_active_o),
        )
        await ClockCycles(dut.clk_i, wait_after_reset_cycles)
        if post_reset_run_pulse:
            self.logger.info("CPU boot: asserting i_cpu_run_req_i for %d cycles", run_pulse_cycles)
            dut.i_cpu_run_req_i.value = 1
            await ClockCycles(dut.clk_i, run_pulse_cycles)
            dut.i_cpu_run_req_i.value = 0
            self.logger.info(
                "CPU boot: deasserted run request run_ack=%d trace_valid=%d iccm_act=%d iccm_addr=0x%x",
                self.rd(dut.o_cpu_run_ack_o),
                self.rd(dut.cpu_trace_valid_o),
                self.rd(dut.dbg_iccm_active_o),
                self.rd(dut.dbg_iccm_addr_o),
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
    ) -> None:
        """Stage a firmware TCM image, boot the EL2 core, and sample boot
        observables into the boot scoreboard ``sb`` until the firmware signals
        completion. Shared by every CPU firmware-boot test so the TCM staging and
        boot-poll live in one place (do not duplicate this in concrete tests).

        The TCM responder backdoor-loads ``sep_itcm.hex`` / ``sep_dtcm.hex`` from
        the sim CWD, so the images are staged there. (CWD-shared: only one CPU
        firmware test runs per sim, so they do not collide; a future per-run path
        would need a responder plusarg like the eFuse model's +sep_efuse_hex.)
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

        async def _load_tcm() -> None:
            self.logger.info("CPU boot: pulsing tcm_load_i")
            dut.tcm_load_i.value = 1
            await ClockCycles(dut.clk_i, 4)
            dut.tcm_load_i.value = 0
            await ClockCycles(dut.clk_i, 4)
            self.logger.info("CPU boot: tcm_load_i pulse complete")

        await self.bring_up_cpu_boot(
            rst_vec, pre_reset_hook=_load_tcm, run_pulse_cycles=run_pulse_cycles
        )

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

        Split out of ``boot_firmware`` so a test that must do work CONCURRENTLY
        with the running firmware (e.g. drive a second master while the CPU loops)
        can ``bring_up_cpu_boot`` itself, ``cocotb.start_soon(self.poll_boot(...))``,
        and run its own stimulus alongside.
        """
        dut = cocotb.top
        last_log = 0
        self.logger.info(
            "boot poll start run_ack=%d cpu_rst_n=%d trace_valid=%d iccm_act=%d iccm_addr=0x%x",
            self.rd(dut.o_cpu_run_ack_o),
            self.rd(dut.sep_cpu_reset_n_o),
            self.rd(dut.cpu_trace_valid_o),
            self.rd(dut.dbg_iccm_active_o),
            self.rd(dut.dbg_iccm_addr_o),
        )
        for cycle in range(max_run_cycles):
            await RisingEdge(dut.clk_i)
            sb.note_trace(self.rd(dut.cpu_trace_valid_o), self.rd(dut.cpu_trace_addr_o))
            sb.note_run_ack(self.rd(dut.o_cpu_run_ack_o))
            if self.rd(dut.fw_char_valid_o):
                sb.note_char(self.rd(dut.fw_char_o))
            if self.rd(dut.fw_done_o):
                sb.note_fw(True, self.rd(dut.fw_pass_o))
                self.logger.info("firmware signaled completion at cycle %d", cycle)
                break
            if cycle - last_log >= progress_every:
                last_log = cycle
                self.logger.info(
                    "boot progress cyc=%d retired=%d pcs=%d last_pc=0x%08x con=%dB rst_n=%s "
                    "iccm_act=%s exc=%s",
                    cycle, sb.trace_count, len(sb.pcs), sb.last_pc, len(sb.console),
                    self.rd(dut.dbg_sep_reset_n_o), self.rd(dut.dbg_iccm_active_o),
                    self.rd(dut.dbg_cpu_trace_exc_o),
                )
            if cycle >= no_boot_cycles and sb.trace_count == 0:
                self.logger.error(
                    "core retired no instructions in %d cycles; aborting", no_boot_cycles
                )
                break
        if sb.console:
            self.logger.info("firmware console: %r", sb.console_text())

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

    # No spi_mux_release_cs() helper on the Python side. The SPI pad mux
    # (och_sep_spi_mux_ctrl_ot SPI_MUX_CTRL: spi_sel + cs_force_high) is a NONFREE
    # shim block inside sep_axi_extension, so a pure-open SEP -- what these cocotb
    # tests build -- has no mux at all: the generated open register export contains
    # no SPI_MUX symbol, tb_top drives the pads straight off the wrapper's struct
    # port, and nothing holds chip-select deasserted. There is nothing to release.
    # The old helper wrote a fixed 0x2000_0000 aperture, which DECERRs here.
    #
    # This is deliberately NOT symmetric with the firmware side: fw/drivers/spi_mux.h
    # keeps a spi_mux_select_ot() that is #ifdef-gated on the mux register existing,
    # because CPU firmware also runs in overlay builds where the mux IS present and
    # must be pointed at the OT host (spi_sel=1), not merely CS-released. If these
    # Python tests ever run against an overlay build, they need that same select.

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
    # Driving a real DUT port is frontdoor, not a backdoor. Shared here so any
    # JTAG/eFuse test reuses one master + op helper rather than re-rolling them.
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
            ).sequence
        return self._jtag_axil

    async def jtag_axil_op(self, *, write: bool, addr: int, wdata: int = 0,
                           timeout_ns: int = 50_000) -> tuple[int, int]:
        """Drive one JTAG AXI-Lite op; return (resp_code, rdata).

        resp_code is the AXI response (OKAY=0, SLVERR=2, DECERR=3; -1 if
        unreadable). A non-completing access (wedge) fails the test rather than
        hanging silently. Uses init_read/init_write so the caller inspects the
        response code itself (a denied access returns DECERR, not an exception).
        """
        m = self.jtag_axil_master()
        if write:
            event = m.init_write(address=addr, data=wdata.to_bytes(4, "little"))
        else:
            event = m.init_read(address=addr, length=4)
        try:
            await with_timeout(event.wait(), timeout_ns, "ns")
        except SimTimeoutError as exc:
            raise AssertionError(
                f"JTAG AXI-Lite op @ 0x{addr:08x} did not complete within {timeout_ns} ns"
            ) from exc
        resp = event.data
        code = getattr(resp, "resp", None)
        try:
            code = int(code[0] if isinstance(code, (list, tuple)) else code)
        except Exception:
            code = -1
        rdata = 0 if write else int.from_bytes(resp.data, "little")
        return code, rdata

    # --- entropy (ESRC->DRBG->CSRNG->EDN->KM) bring-up observers --------------
    # Shared poll/check helpers for any entropy-consumer test (the SEQUENCES that
    # drive the bring-up live in seq_lib/sep_esrc_bringup_seq.py). They read the
    # tb_top entropy probe ports, so they ride on the standard model.
    async def _wait_high(self, sig, timeout: int) -> bool:
        for _ in range(timeout):
            await RisingEdge(cocotb.top.clk_i)
            await ReadOnly()
            if self.rd(sig):
                return True
        return False

    async def wait_seed_ready(self, timeout: int = 60_000) -> bool:
        """Wait until ESRC accumulates a seed and presents it to CSRNG."""
        return await self._wait_high(cocotb.top.drbg_seed_valid_o, timeout)

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
                counts[name] += 1 if self.rd(sig) else 0

        self.logger.error(
            "entropy stall over %d cycles: %s (noise_active=%d ro_enable=0x%03x "
            "last_compress_data=0x%08x)",
            window,
            " ".join(f"{k}={v}" for k, v in counts.items()),
            self.rd(dut.esrc_noise_active_o),
            self.rd(dut.esrc_ro_enable_o),
            self.rd(dut.esrc_compress_data_o),
        )

        # Frontdoor status: FIFO level and health-test result decide whether the
        # ESRC itself is stuck or the DRBG side is not draining.
        #
        # Every read is BOUNDED and failure-tolerant. One plausible cause of the
        # stall is a fabric that never released, in which case these reads would
        # never retire -- and an unbounded diagnostic would turn an attributed
        # failure into a bare sim timeout, the exact outcome a bounded wait exists
        # to prevent. The strobe counts above always survive, so a wedged CSR path
        # degrades to "counts logged, CSR unreadable" instead of taking the whole
        # report down with it.
        from seq_lib.sep_esrc_bringup_seq import (
            ESRC_FIFO_STATUS,
            ESRC_HEALTH_TEST_CTRL,
            ESRC_HEALTH_TEST_STATUS,
            ESRC_MAIN_SM_STATUS,
            ESRC_CTRL,
        )
        from seq_lib.sep_axi_access_seq import SepAxiAccessSeq
        from env.sep_axi_agent import SepAxiOp

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
        """After the EDN->KM handshake, the KM firmware stores the consumed
        entropy word to KM SRAM word0. Poll for it to land -- end-to-end proof
        the word reached KM memory, not just the stream boundary. (A genbits word
        is 0 with probability 2^-32, so nonzero is a sound liveness marker.)"""
        return await self._wait_high(cocotb.top.km_sram_word0_o, timeout)

    async def check_entropy_alerts_zero(self):
        """Read + assert CSRNG/EDN err_code + recov_alert are all zero."""
        from seq_lib.sep_esrc_bringup_seq import SepEsrcAlertReadSeq

        seq = SepEsrcAlertReadSeq()
        await self.start_seq(seq)
        assert seq.csrng_err == 0, f"CSRNG ERR_CODE=0x{seq.csrng_err:08x}"
        assert seq.csrng_alert == 0, f"CSRNG RECOV_ALERT=0x{seq.csrng_alert:08x}"
        assert seq.edn_err == 0, f"EDN ERR_CODE=0x{seq.edn_err:08x}"
        assert seq.edn_alert == 0, f"EDN RECOV_ALERT=0x{seq.edn_alert:08x}"
        return seq

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

    async def bring_up_entropy(self, cfg=None, *, strict: bool = True,
                               score_km: bool | str = True, score_sinks: dict | None = None):
        """Bring up the real ESRC->DRBG->CSRNG->EDN entropy stack and return the
        started CHK1..CHK5 scoreboard (also stored as ``self.drbg_sb``).

        Shared by every entropy-consumer test: starts the golden-vs-probe
        scoreboard (which drives the deterministic ESRC noise so the ring
        oscillators are alive under Verilator), proves the noise force took, then
        runs the OCAH bring-up order (configure ESRC generators-off, enable CSRNG,
        stage EDN, enable generators, wait for a seed, enable EDN). The caller does
        the consumer-specific steps afterwards (fork the FIFO drain, wait_genbits,
        release/boot its consumer). ``cfg`` defaults to ``SepEntropyCfg()``.

        ``strict=True`` makes the scoreboard ``report()`` raise on any golden
        mismatch or under-evidence stream. ``score_km`` defaults to True for
        bit-exact CHK5_km golden-match. Set ``score_km="observe"`` for a consumer
        whose pull order is not golden-predictable (e.g. real ``rom_main``): CHK1..CHK4
        stay strict, and CHK5 requires real KM tvalid&&tready beats without a
        bit-exact value compare.

        ``score_sinks`` is an optional name->mode map for the crypto EDN sinks
        (``aes``/``kmac``/``otbn_rnd``/``otbn_urnd``), each ``"observe"`` or
        ``"disabled"`` (omitted sinks default disabled). A sink set to ``"observe"``
        requires >=1 real post-adapter EDN beat to that client, proving the SEP EDN
        crypto leg delivers entropy -- used by tests that release a crypto consumer
        (e.g. the OTBN KAT releases OTBN, whose secure wipe pulls URND).
        """
        from env.sep_drbg_scoreboard import SepDrbgScoreboard
        from seq_lib.sep_esrc_bringup_seq import (
            SepEntropyCfg,
            SepEsrcConfigSeq,
            SepEsrcEnableGeneratorsSeq,
            SepEsrcEnableEdnSeq,
        )

        if cfg is None:
            cfg = SepEntropyCfg()
        self.entropy_cfg = cfg
        self.drbg_sb = SepDrbgScoreboard(
            cocotb.top, self.logger, strict=strict,
            golden_kwargs=cfg.golden_kwargs(), chk2_backdoor=cfg.chk2_backdoor,
            score_km=score_km, score_sinks=score_sinks,
        )
        self.drbg_sb.start()
        await self.assert_noise_force_active()
        await self.start_seq(SepEsrcConfigSeq("esrc_config", cfg=cfg))
        await self.start_seq(SepEsrcEnableGeneratorsSeq("esrc_enable_gens"))
        if not await self.wait_seed_ready():
            await self.report_entropy_stall()
            raise AssertionError("ESRC never produced a seed (drbg_seed_valid_o)")
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
            None if getattr(self, "entropy_cfg", None) and self.entropy_cfg.chk2_backdoor
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

    async def run_phase(self) -> None:
        self.raise_objection()
        await self.run_scenario()
        self.drop_objection()
