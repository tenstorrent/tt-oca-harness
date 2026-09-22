# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Shared bring-up for the dual-SMC OCCP tests.

Thinner than hw/sys/smc/dv/cocotb/tests/smc_base_test.py: that harness builds
the whole single-instance SmcEnv against tb_top.sv's single-instance port
surface, none of which exists on the SMC_DUAL half of tb_top.sv. Here both
instances share one clock/reset bring-up and each gets its own inbound AXI
master.
"""

from __future__ import annotations

import functools
import logging
import os
import random
import re
import subprocess
import sys
from collections.abc import Awaitable, Callable
from pathlib import Path

import cocotb
from cocotb.clock import Clock
from cocotb.handle import Force
from cocotb.regression import Test
from cocotb.triggers import ClockCycles, with_timeout
from env.smc_cpu_trace_monitor import SmcCpuTraceState, symbol_file_for_image, watch_cpu_trace
from env.smc_env_cfg import SYS_OUT_AXI_GEOMETRY, SYS_OUT_MEM_SIZE
from ocah_axi_vip import OcahAxiMasterAgent, OcahAxiSlaveAgent, OcahAxiSlaveSequence
from smc_base_test import _EvidenceRecorder, log_build_model_identity

# This file lives in the DV tree's cocotb/tests/, so the DV root is two
# directories up. Anchored on the DV root rather than the repo root: it is the
# nearer landmark, so a future move of hw/sys/ does not silently retarget this.
_DV_ROOT = Path(__file__).resolve().parents[2]
_EFUSE_DIR = _DV_ROOT / "efuse_preload"
assert _EFUSE_DIR.is_dir(), f"eFuse tooling not found at {_EFUSE_DIR}"

# Clock periods in ns and the post-reset settle, taken from the single-instance
# defaults in hw/sys/smc/dv/cocotb/env/smc_env_cfg.py. The dual top shares one
# clock tree across both instances, so one set applies to both. The settle is
# 500 ref cycles because powergood_stable is the end of a reset-sync chain and
# is still low at 200.
REF_CLK_PERIOD_NS = 10
SMC_CLK_PERIOD_NS = 5
PERIPH_CLK_PERIOD_NS = 10

POST_RESET_SETTLE_CYCLES = 500

# Bound on waiting for the strap-capture gate. smc_reset_ctrl needs a >=32-cycle
# cold deglitch plus a 255-cycle extender on clk_ref, so ~300 is the real figure
# and this is an order of magnitude of headroom rather than a target.
STRAP_CAPTURE_TIMEOUT_CYCLES = 4000
# Extra reference cycles held after the gate rises, matching the reference's own
# margin before it releases its GPIO forces.
STRAP_CAPTURE_SETTLE_CYCLES = 16


AXI_TIMEOUT_NS = 20_000

# Product lifecycle state, smc_pkg::LC_STATE_WIDTH. The port carries the
# complementary pair {diff_n, diff_p}; a value whose halves are not complements
# raises the wrapper's lc_sigint_err_o instead of being decoded.
LC_STATE_WIDTH = 4

# Lifecycle encodings the firmware names. is_secure_mode() in
# fw/common/occp/occp_interfaces.c reads CHIP_CONFIG.LC_STATE and treats 1 and 8
# as secure; the DV firmware and the production ROM agree on TEST_DEV = 0.
LC_STATE_TEST_DEV_VALUE = 0
LC_STATE_SECURE_VALUES = (1, 8)


def encode_lc_state(value: int) -> int:
    """Pack one lifecycle value into the {diff_n, diff_p} pair the port expects."""
    value &= (1 << LC_STATE_WIDTH) - 1
    return ((~value & ((1 << LC_STATE_WIDTH) - 1)) << LC_STATE_WIDTH) | value


LC_STATE_TEST_DEV = encode_lc_state(LC_STATE_TEST_DEV_VALUE)

# Bytes per bulk AXI transaction. One 64-byte scratch-bank stripe, and small
# enough that the AXI-to-TileLink bridge into the CPU cluster carries it; see
# DualCsr.write_bytes for the burst length that does not.
BULK_CHUNK_BYTES = 64

# The smc_sim_cfg.toml target whose model every dual leaf must run on. The
# identity stamp fails a run whose exported build directory belongs to any
# other target, so a dual log can never be backed by a single-instance model.
DUAL_TARGET = "dual"


def random_seed() -> int:
    return int(os.environ.get("RANDOM_SEED", "1"), 0)


# Lowest programmed OCCP transport timeout, TIMEOUT_MIN in
# efuse_preload/randomize_efuse.py. The reference pins the fuse here with
# +FORCE_MIN_TRANSPORT_TIMEOUT on the tests that should not pay for a longer one.
FUSE_TRANSPORT_TIMEOUT_MIN = 400


def regenerate_efuse_image(seed: int) -> dict[int, int]:
    """Rewrite this run's eFuse image, seeded, before reset is released.

    Returns {slot: address} for the OCCP I2C target addresses it programmed,
    empty unless +fuse_i2c_ids asked for them.

    +smc_efuse_hex carries a PATH, fixed when the simulator launched; the file
    at that path is not read until reset release, because the preload block in
    hw/ip/efuse/dv/models/efuse_bank_model.sv waits on rst_ni. That is the whole
    window this function lives in: overwrite the file now and the bank picks up
    the new contents; overwrite it after reset and nothing changes.

    Silently does nothing when +smc_efuse_hex is absent, so a test that does not
    care about fuse contents is unaffected.

    The image is derived from `seed`, so a failing run is reproducible from its
    RANDOM_SEED. The OCCP transport timeout varies -- see
    efuse_preload/randomize_efuse.py for the field list.
    """
    img = cocotb.plusargs.get("smc_efuse_hex")
    if img is None:
        return {}
    img_path = Path(str(img))

    # The generator needs tomllib (3.11+). The interpreter running cocotb is the
    # repo venv, which satisfies that; sys.executable keeps us on it rather than
    # whatever `python3` resolves to on PATH.
    randomized = img_path.parent / "efuse_config_randomized.toml"
    # +fuse_transport_timeout pins the OCCP transport timeout fuse instead of
    # letting it randomise, mapping the reference's +FORCE_MIN_TRANSPORT_TIMEOUT.
    forced_timeout = cocotb.plusargs.get("fuse_transport_timeout")
    timeout_args = (
        [] if forced_timeout is None else ["--transport-timeout", str(int(str(forced_timeout), 0))]
    )
    # +fuse_i2c_ids programs the two OCCP I2C target addresses instead of leaving
    # both channels on the ROM's 0x55 fallback, which a test needs when it puts
    # them on one bus and has to tell them apart.
    i2c_args = ["--i2c-ids"] if cocotb.plusargs.get("fuse_i2c_ids") is not None else []
    try:
        randomize = subprocess.run(
            [
                sys.executable,
                str(_EFUSE_DIR / "randomize_efuse.py"),
                str(_EFUSE_DIR / "configurations/default_efuse.toml"),
                "--output_file",
                str(randomized),
                "--seed",
                str(seed),
                *timeout_args,
                *i2c_args,
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        result = subprocess.run(
            [
                sys.executable,
                str(_EFUSE_DIR / "generate_efuse_preload.py"),
                str(randomized),
                "--output_file",
                str(img_path),
            ],
            check=True,
            capture_output=True,
            text=True,
        )
    except subprocess.CalledProcessError as exc:
        # Loud, not silent: a stale image from the c_build stage would still be
        # on disk, so the run would carry on with fuse contents that do not
        # match the seed it reports.
        raise AssertionError(
            f"eFuse image regeneration failed for seed {seed}:\n"
            f"  {exc.cmd}\n  stdout: {exc.stdout}\n  stderr: {exc.stderr}"
        ) from exc

    cocotb.log.info(
        "eFuse image regenerated for RANDOM_SEED=%d -> %s (%s)",
        seed,
        img_path,
        result.stdout.strip(),
    )
    return _parse_i2c_ids(randomize.stdout)


# The generator prints what it programmed; parsing that is what keeps the
# testbench and the fuse image on one source of truth. Deriving the addresses
# a second time here would let the two drift apart silently, and the failure
# would look like a bus problem rather than a mismatch.
_I2C_ID_RE = re.compile(r"I2C_I3C_ID\[(\d)\]=(0x[0-9a-fA-F]+)")


def _parse_i2c_ids(stdout: str) -> dict[int, int]:
    """{slot: address} for the I2C slots the generator programmed, if any."""
    return {int(slot): int(addr, 0) for slot, addr in _I2C_ID_RE.findall(stdout)}


class DualCsr:
    """One inbound AXI manager, bound by flat signal prefix.

    Thin wrapper over ocah_axi_vip rather than the single-instance
    SmcSysAxiAgent: that agent is a UVM component wired into SmcEnv, and the
    dual top has no SmcEnv. Same underlying VIP either way.
    """

    def __init__(self, prefix: str, reset_signal) -> None:
        dut = cocotb.top
        self.prefix = prefix
        self.seq = OcahAxiMasterAgent.from_prefix(
            dut,
            prefix,
            dut.clk_smc_i,
            reset_signal,
            name=f"smc_dual_{prefix}",
            reset_active_level=False,
        ).sequence

    @staticmethod
    def _axi_size(length: int) -> int:
        return max(0, length.bit_length() - 1)

    # The VIP's *_result APIs, not init_write/init_read: those return the raw
    # driver event, whose payload carries RRESP/BRESP that nobody was reading. A
    # DECERR then arrived as data 0x0 and every caller treated it as a real
    # register value -- which is how an unmapped window looked like a cleared
    # register. check_response=True turns that into a failure at the access.
    async def write(self, name: str, addr: int, data: int, length: int = 4) -> None:
        result = await self.seq.write_result(
            addr,
            data,
            size=self._axi_size(length),
            prot=0,
            timeout_ns=AXI_TIMEOUT_NS,
        )
        cocotb.log.debug(
            "%s write %s %#x <- %#x (resp=%d)", self.prefix, name, addr, data, result.resp
        )

    async def read(self, name: str, addr: int, length: int = 4) -> int:
        result = await self.seq.read_result(
            addr,
            size=self._axi_size(length),
            prot=0,
            timeout_ns=AXI_TIMEOUT_NS,
        )
        value = int.from_bytes(result.data_bytes[:length], "little")
        cocotb.log.debug(
            "%s read %s %#x -> %#x (resp=%d)", self.prefix, name, addr, value, result.resp
        )
        return value

    async def write_bytes(self, name: str, addr: int, data: bytes) -> None:
        """Bulk front-door write, for staging a firmware image in scratch SRAM.

        Reaches the CPU scratch window at 0xC006_xxxx; see
        smc_dual_axi_sram_probe_test for the measurement that this path works,
        and note it only works with the instance's warm reset domain released
        (boot_stall low), because the scratch banks hang off the CPU cluster.

        Chunked at BULK_CHUNK_BYTES rather than handed to the VIP as one
        transfer. Letting cocotbext-axi size the burst itself produces
        awlen=255, and the AXI-to-TileLink bridge does not carry a 256-beat
        burst into the cluster's front port: the write never completes. Each
        transaction therefore stays inside one 64-byte line, which is also the
        scratch banks' stripe granularity.
        """
        for off in range(0, len(data), BULK_CHUNK_BYTES):
            chunk = data[off : off + BULK_CHUNK_BYTES]
            event = self.seq.init_write(address=addr + off, data=chunk, size=3, prot=0)
            await with_timeout(event.wait(), AXI_TIMEOUT_NS, "ns")
        cocotb.log.info(
            "%s write_bytes %s %#010x <- %d bytes in %d-byte chunks",
            self.prefix,
            name,
            addr,
            len(data),
            BULK_CHUNK_BYTES,
        )

    async def read_bytes(self, name: str, addr: int, length: int) -> bytes:
        """Bulk front-door read. Same chunking constraint as write_bytes()."""
        out = bytearray()
        for off in range(0, length, BULK_CHUNK_BYTES):
            n = min(BULK_CHUNK_BYTES, length - off)
            event = self.seq.init_read(address=addr + off, length=n, size=3, prot=0)
            await with_timeout(event.wait(), AXI_TIMEOUT_NS, "ns")
            out += bytes(event.data.data)
        cocotb.log.debug("%s read_bytes %s %#010x -> %d bytes", self.prefix, name, addr, length)
        return bytes(out)


class SmcDualHarness:
    """Clock/reset bring-up, per-instance idle pin defaults, and CPU trace state."""

    def __init__(
        self,
        *,
        test_name: str = "",
        required_evidence: tuple[str, ...] = (),
        require_clean_tree: bool = True,
    ) -> None:
        self.dut = cocotb.top
        self.log = cocotb.log
        # Same provenance gate as smc_base_test.require_clean_tree: the identity
        # line names the commit the model was built from, and uncommitted
        # changes on the model or bench sources fail the run unless allowed.
        self.require_clean_tree = require_clean_tree
        # The CHK-* lines this run emits are read off the log records the way
        # smc_base_test._finalize_evidence reads them; finalize_evidence()
        # grades them against the IDs the test owes, with no min_evidence
        # floor and no NO_OWN_EVIDENCE exemption.
        self.test_name = test_name
        self.required_evidence = tuple(required_evidence)
        self._evidence = _EvidenceRecorder()
        self._evidence.install()
        # One hart-0 processor-state reconstruction per instance, sampled from
        # bring_up onward; failure messages embed cpu_trace_report().
        self.cpu_trace = {
            inst: SmcCpuTraceState(f"{inst}-hart0", cocotb.log) for inst in ("dut", "bfm")
        }
        # {slot: address} the eFuse image was built with, filled in by bring_up.
        self.fuse_i2c_ids: dict[int, int] = {}
        # Which transport the controller was strapped to this run.
        self.boot_i2c = False
        # Captured straps per instance, as firmware reads them in STRAPS_LO/HI.
        self.straps: dict[str, int] = {"dut": 0, "bfm": 0}
        # CHIP_ID nibble strapped this run; the OCCP address falls back to it.
        self.chip_id = 0
        # One SYS_OUT responder per instance, bound in bring_up before the
        # clocks start; the slave sequences give backdoor access and faults.
        self.sys_out_mem: dict[str, OcahAxiSlaveSequence] = {}

    def _attach_cpu_symbols(self) -> None:
        """Attach the staged listings of each instance's image, when present.

        The target boots the production ROM (``+rom_bin64`` -> ``prod_rom.sym``)
        and may later run the OCCP payload (``+occp_payload_sym``); the
        controller runs the DV rom-mode image (``+bfm_rom_hex`` -> ``.rom.sym``).
        A missing listing leaves that instance's PCs numeric.
        """
        rom = cocotb.plusargs.get("rom_bin64")
        if rom is not None:
            derived = symbol_file_for_image("rom_bin64", str(rom))
            if derived is not None:
                self.cpu_trace["dut"].attach_symbol_file(derived)
        payload_sym = cocotb.plusargs.get("occp_payload_sym")
        if payload_sym is not None:
            self.cpu_trace["dut"].attach_symbol_file(str(payload_sym))
        ctrl = cocotb.plusargs.get("bfm_rom_hex")
        if ctrl is not None:
            derived = symbol_file_for_image("bfm_rom_hex", str(ctrl))
            if derived is not None:
                self.cpu_trace["bfm"].attach_symbol_file(derived)

    def cpu_trace_report(self) -> str:
        """Both instances' symbolized processor state, for assertion messages."""
        lines: list[str] = []
        for state in self.cpu_trace.values():
            lines.extend(f"    {line}" for line in state.report_lines(ring_tail=16))
        return "\n".join(lines)

    def dump_cpu_trace(self, level: int = logging.INFO) -> None:
        for state in self.cpu_trace.values():
            state.dump(level)

    def idle_pins(
        self, *, hold_dut_boot: bool, hold_bfm_boot: bool, dft_low: tuple[str, ...] = ()
    ) -> None:
        dut = self.dut
        dut.powergood_i.value = 0
        dut.rst_cold_ni.value = 0
        dut.rst_cool_ni.value = 1

        # Shared I3C0: no external third driver by default, so both ext_low
        # votes are released and the bus is owned by the two instances.
        dut.tb_i3c0_scl_ext_low.value = 0
        dut.tb_i3c0_sda_ext_low.value = 0

        # Both instances come up as primary chiplets, matching the
        # single-instance TB default. The controller/target split in this flow
        # is decided by which image each one runs, not by this strap.
        dut.dut_chiplet_is_primary.value = 1
        dut.bfm_chiplet_is_primary.value = 1

        # Boot stall held from t=0 so reset vectors can be programmed before
        # either core fetches.
        dut.dut_boot_stall_hold.value = 1 if hold_dut_boot else 0
        dut.bfm_boot_stall_hold.value = 1 if hold_bfm_boot else 0

        dut.dut_gpio_ext_drive_en.value = 0
        dut.dut_gpio_ext_drive_value.value = 0
        dut.bfm_gpio_ext_drive_en.value = 0
        dut.bfm_gpio_ext_drive_value.value = 0

        # Unsecure lifecycle on both instances, the same complementary TEST_DEV
        # the single-instance TB drives onto tb_lc_state. Tests that need the
        # secure branch or an illegal encoding call set_lc_state() before
        # bring_up() releases cold reset.
        dut.dut_lc_state.value = LC_STATE_TEST_DEV
        dut.bfm_lc_state.value = LC_STATE_TEST_DEV

        # BISR/MBIST reported complete and passing, which is the "no external DFT agent"
        # posture every ordinary test needs.
        #
        # An instance named in `dft_low` gets all six lines at 0 instead. Every
        # DFX_CTRL_STATUS.STATUS_SMU field is a stickybit that holds a 1 until reset, so an
        # instance that is going to report a failure must never show the passing posture
        # while cold reset is released -- the 1 would latch and no later drive could clear
        # it.
        for instance in ("dut", "bfm"):
            passing = instance not in dft_low
            getattr(dut, f"{instance}_mem_repair_done").value = 1 if passing else 0
            getattr(dut, f"{instance}_mem_repair_success").value = 1 if passing else 0
            getattr(dut, f"{instance}_mem_repair_abort").value = 0
            getattr(dut, f"{instance}_mbist_done").value = 1 if passing else 0
            getattr(dut, f"{instance}_mbist_pass").value = 1 if passing else 0
            getattr(dut, f"{instance}_mbist_abort").value = 0

    async def bring_up(
        self,
        *,
        hold_dut_boot: bool = True,
        hold_bfm_boot: bool = True,
        dut_lc_state: int | None = None,
        bfm_lc_state: int | None = None,
        dft_low: tuple[str, ...] = (),
    ) -> None:
        # First line of every dual log: which model this run simulated, and
        # that it is the dual target's ([BUILD-MODEL-IDENTITY]). Raises rather
        # than logging a placeholder.
        log_build_model_identity(
            require_clean_tree=self.require_clean_tree, expect_target=DUAL_TARGET
        )
        dut = self.dut
        self.log.info(
            "dual bring-up: ref=%dns smc=%dns periph=%dns (seed=%d)",
            REF_CLK_PERIOD_NS,
            SMC_CLK_PERIOD_NS,
            PERIPH_CLK_PERIOD_NS,
            random_seed(),
        )
        self.idle_pins(hold_dut_boot=hold_dut_boot, hold_bfm_boot=hold_bfm_boot, dft_low=dft_low)

        # After idle_pins, which would otherwise put both back to TEST_DEV, and
        # before cold reset is released below.
        if dut_lc_state is not None:
            self.set_lc_state("dut", dut_lc_state)
        if bfm_lc_state is not None:
            self.set_lc_state("bfm", bfm_lc_state)

        # Before any reset is released -- the eFuse bank reads its image on
        # rst_ni, so this is the last point at which the contents can still be
        # chosen for this run.
        # Kept so release_cpu() can hand the controller the addresses the target
        # will actually answer on. Both sides read the same source; deriving them
        # twice would let the fuse image and the testbench drift apart.
        self.fuse_i2c_ids = regenerate_efuse_image(random_seed())

        # Each responder follows its instance's primary reset so a cool reset
        # drops the outstanding responses instead of returning them into the
        # reset CPU cluster.
        for inst in ("dut", "bfm"):
            self.sys_out_mem[inst] = OcahAxiSlaveAgent(
                SYS_OUT_AXI_GEOMETRY.bus(getattr(dut, f"u_{inst}_output_axi_if")),
                dut.clk_smc_i,
                getattr(dut, f"{inst}_rst_primary_smc_clk_no"),
                reset_active_level=False,
                size=SYS_OUT_MEM_SIZE,
                name=f"smc_{inst}_sys_out",
            ).sequence

        cocotb.start_soon(Clock(dut.clk_ref_i, REF_CLK_PERIOD_NS, unit="ns").start())
        cocotb.start_soon(Clock(dut.clk_smc_i, SMC_CLK_PERIOD_NS, unit="ns").start())
        cocotb.start_soon(Clock(dut.clk_periph_i, PERIPH_CLK_PERIOD_NS, unit="ns").start())
        self._attach_cpu_symbols()
        for inst, state in self.cpu_trace.items():
            cocotb.start_soon(
                watch_cpu_trace(
                    dut,
                    dut.clk_smc_i,
                    state,
                    prefix=f"{inst}_cpu_trace",
                    reset_name=f"{inst}_cpu_core_reset_n",
                )
            )

        await ClockCycles(dut.clk_ref_i, 10)

        # Straps are applied here rather than before the clocks start: a force
        # issued at time 0 is accepted and then does nothing, so it has to wait
        # until simulation has advanced. Still ahead of cold reset release and of
        # the capture point _await_strap_capture() waits for.
        self._apply_straps()

        self.log.info("asserting powergood on both instances")
        dut.powergood_i.value = 1
        await ClockCycles(dut.clk_ref_i, 10)
        self.log.info("releasing cold reset on both instances")
        dut.rst_cold_ni.value = 1
        await self._await_strap_capture()
        await ClockCycles(dut.clk_ref_i, POST_RESET_SETTLE_CYCLES)

    async def release_cpu(
        self,
        csr: DualCsr,
        instance: str,
        reset_vector: int,
        *,
        seed_firmware_rng: bool = True,
    ) -> None:
        """Program the reset vector, release RESET_CTRL, then drop boot_stall.

        Mirrors the held-boot first-boot path in
        hw/sys/smc/dv/cocotb/seq_lib/smc_cpu_vip_utils.py
        (_release_held_cpu_boot): the Rocket frontend latches RESET_VECTOR only
        on tile reset, so the vector has to be in place before boot_stall drops,
        and every core must be released or isolate_req stays high and clamps
        MMIO.
        """
        from smc_occp_dual_defs import (
            CPU_CTRL_RESET_CTRL,
            CPU_CTRL_RESET_TIMEOUT,
            CPU_CTRL_RESET_VECTOR,
            CPU_RESET_CTRL_DEFAULT,
            CPU_RESET_TIMEOUT_FORCE,
            SCRATCH_FW_SEED,
        )

        dut = self.dut
        await csr.write(
            "RESET_TIMEOUT_FORCE",
            CPU_CTRL_RESET_TIMEOUT,
            CPU_RESET_TIMEOUT_FORCE,
            length=8,
        )
        for idx, addr in enumerate(CPU_CTRL_RESET_VECTOR):
            await csr.write(f"RESET_VECTOR_{idx}", addr, reset_vector, length=8)
        await csr.write("RESET_RELEASE", CPU_CTRL_RESET_CTRL, CPU_RESET_CTRL_DEFAULT, length=8)
        await ClockCycles(dut.clk_smc_i, 64)

        # The one window where both conditions hold: the cores are out of reset, so the
        # scratch bank answers AXI, and boot_stall is still up, so init_test() has not
        # latched the seed yet. The reference does the same job from its shared
        # init_and_reset(); doing it here means no test can forget to.
        if seed_firmware_rng:
            await self._seed_firmware_rng(csr, instance, SCRATCH_FW_SEED)
            await self._publish_i2c_target_ids(csr, instance)
            await self._check_boot_interface_strap(csr, instance)

        getattr(dut, f"{instance}_boot_stall_hold").value = 0
        await ClockCycles(dut.clk_smc_i, 256)
        self.log.info("%s: released boot_stall with reset_vector=%#010x", instance, reset_vector)

    async def _await_strap_capture(self) -> None:
        """Hold on until the padring has latched the straps on both instances.

        The capture latch is gated by rst_cold_stable_ref_clk_no, not by
        rst_cold_ni: smc_reset_ctrl deglitches cold reset and then extends it, so
        the latch is still transparent for a long time after rst_cold_ni rises.
        A strap released at rst_cold_ni is therefore never sampled.

        The reference waits on the same signal in init_and_reset, then gives the
        capture 16 more reference cycles before releasing its GPIO forces.
        """
        dut = self.dut
        for _ in range(STRAP_CAPTURE_TIMEOUT_CYCLES):
            if int(dut.dut_rst_cold_stable_ref_clk_no.value) and int(
                dut.bfm_rst_cold_stable_ref_clk_no.value
            ):
                break
            await ClockCycles(dut.clk_ref_i, 1)
        else:
            raise AssertionError(
                "rst_cold_stable_ref_clk_no never deasserted on both instances within "
                f"{STRAP_CAPTURE_TIMEOUT_CYCLES} clk_ref_i; the padring would never latch "
                "the straps, so every smc_strap_is_set() would read false"
            )
        await ClockCycles(dut.clk_ref_i, STRAP_CAPTURE_SETTLE_CYCLES)
        self.log.info("strap capture window closed on both instances")

    def set_straps(self, instance: str, value: int) -> None:
        """Drive one instance's captured straps, which firmware reads as STRAPS_LO/HI.

        A force, not a deposit: rom_straps carries a continuous tie-off. It needs
        both public_flat_rw and forceable in smc_public_scope.vlt -- without the
        second the force is a silent no-op.
        """
        inst = getattr(self.dut, f"u_{instance}")
        inst.u_smc_wrapper.u_smc_ip_integration.rom_straps.value = Force(value)
        self.straps[instance] = value

    def set_strap_bit(self, instance: str, bit: int) -> None:
        self.set_straps(instance, self.straps[instance] | (1 << bit))

    def _apply_straps(self) -> None:
        """Draw this run's straps, the way the reference environment draws them.

        The two instances do not get the same set. The controller gets only the
        straps its own firmware reads -- BOOT_I2C, which picks its OCCP driver,
        and STATUS_RPT_DISABLE -- while the target, whose production ROM is what
        the run exercises, gets the randomised set. PRIMARY_CHIPLET is on both to
        match chiplet_is_primary_i, which stays the RTL's own source: the port
        feeds the design and the strap feeds firmware, so they have to agree or
        the two disagree about which instance is the boot master.

        BL0_PLLCLK stays clear on both. The reference randomises it to cover the
        ROM's PLL programming path, and this tree instantiates no PLL.
        """
        from smc_occp_dual_defs import (
            STRAP_BITS,
            STRAP_BOOT_I2C,
            STRAP_PRIMARY_CHIPLET,
            chip_id_straps,
        )

        force_i3c = cocotb.plusargs.get("BOOT_I3C") is not None
        force_i2c = cocotb.plusargs.get("BOOT_I2C") is not None
        if force_i3c and force_i2c:
            raise AssertionError("+BOOT_I3C and +BOOT_I2C both given; they select opposite paths")

        # Straps a test asks for by name. This runs first so the randomisation
        # below can see what the test already pinned.
        named = {name for name in STRAP_BITS if cocotb.plusargs.get(name) is not None}
        target = sum(1 << STRAP_BITS[name] for name in named)
        if named:
            self.log.info("straps set by plusarg: %s", ", ".join(sorted(named)))

        # Status reporting is the one randomised strap the controller shares,
        # because both firmwares gate their own reporting on it.
        if cocotb.plusargs.get("FORCE_STATUS_REPORTING") is not None:
            status_rpt_disable = 0
        elif "STATUS_RPT_DISABLE" in named:
            status_rpt_disable = 1
        else:
            status_rpt_disable = random.choice([0, 1])
        target |= status_rpt_disable << STRAP_BITS["STATUS_RPT_DISABLE"]
        controller = status_rpt_disable << STRAP_BITS["STATUS_RPT_DISABLE"]
        self.log.info("STATUS_RPT_DISABLE strap: %d", status_rpt_disable)

        # Bit 26 set means auto-zero is disabled and the ROM zeroes the SRAM
        # itself, which costs sim time; the reference only ever clears it, so a
        # test that wants the slow path has to ask for it by plusarg.
        if cocotb.plusargs.get("FORCE_HW_AUTO_ZERO") is not None or random.choice([True, False]):
            target &= ~(1 << STRAP_BITS["SRAM_AUTO_ZERO_DISABLE"])
        self.log.info(
            "SRAM_AUTO_ZERO_DISABLE strap: %d",
            (target >> STRAP_BITS["SRAM_AUTO_ZERO_DISABLE"]) & 1,
        )

        # The reference calls these out as having no effect on the ROM; they are
        # randomised for coverage, not to steer a path.
        for name in ("TEST_EN", "SPI_USE_FUSED_CONFIG", "BOOT_RECOVERY", "ROTATE_UPDATE"):
            if name not in named:
                target |= random.choice([0, 1]) << STRAP_BITS[name]

        # CHIP_ID decides the address the target's ROM answers on when its eFuse
        # slot is unprogrammed (smc_occp_determine_i3c_address in occp.c). The
        # controller learns the same address through scratch 4 rather than a
        # strap, as it does in the reference.
        self.chip_id = random.randint(0, 0xF)
        target |= chip_id_straps(self.chip_id)
        self.log.info("CHIP_ID straps: %#x", self.chip_id)

        # The interface is a per-run draw unless the test names one, which is how
        # the reference spreads I2C and I3C coverage over a regression.
        if force_i2c:
            self.boot_i2c = True
        elif force_i3c:
            self.boot_i2c = False
        else:
            self.boot_i2c = bool(random.choice([0, 1]))
        controller |= int(self.boot_i2c) << STRAP_BOOT_I2C
        self.log.info(
            "controller OCCP boot interface: %s (%s)",
            "I2C" if self.boot_i2c else "I3C",
            "+BOOT_I2C" if force_i2c else "+BOOT_I3C" if force_i3c else "randomised",
        )

        for instance, value in (("dut", target), ("bfm", controller)):
            self.set_straps(instance, value | (1 << STRAP_PRIMARY_CHIPLET))
        self.log.info("straps forced: dut=%#x bfm=%#x", self.straps["dut"], self.straps["bfm"])

    async def _check_boot_interface_strap(self, csr: DualCsr, instance: str) -> None:
        """Prove the BOOT_I2C strap the testbench forced is what the firmware will read.

        Read back through STRAPS_LO, which is the register smc_strap_is_set() reads,
        so this is the firmware's own view rather than a peek at the forced signal.
        Only +BOOT_I2C reaches this: it is the only case where a strap was driven,
        and without the check the log could claim I2C while the firmware took the
        I3C fallback.
        """
        from smc_occp_dual_defs import STRAP_BOOT_I2C, strap_reg_addr

        if instance != "bfm" or not self.boot_i2c:
            return
        addr, bit = strap_reg_addr(STRAP_BOOT_I2C)
        value = await csr.read("STRAPS_BOOT_I2C", addr)
        strapped = bool(value & (1 << bit))
        self.log.info(
            "controller BOOT_I2C strap readback: %#010x=%#010x (bit %d = %d)",
            addr,
            value,
            bit,
            strapped,
        )
        assert strapped, (
            f"BOOT_I2C strap did not take: {addr:#010x}={value:#010x} has bit {bit} clear "
            "after the testbench forced it. The firmware reads this register, so it would "
            "fall back to I3C. A read of 0 also means rom_straps is not forceable in "
            "smc_public_scope.vlt"
        )

    async def _seed_firmware_rng(self, csr: DualCsr, instance: str, addr: int) -> None:
        """Give this instance's DV firmware a usable RNG seed.

        get_random_int() in fw/include/smc_test.h is an XOR-feedback LFSR, and
        all-zero is its dead state: the feedback bit is 0, so the state stays 0
        and every draw returns 0 forever. init_test() loads the seed from this
        register in the first instructions of main(), so an unwritten register
        leaves the firmware with frozen randomness -- which pins the I3C channel
        and the body-CRC choice, and hangs outright in any caller that draws
        distinct values, such as flip_n_random_bits() in occp_commands.c.

        Derived from RANDOM_SEED so a failing run is reproducible, and forced
        non-zero for the reason above.
        """
        seed = (random_seed() * 2_654_435_761) & 0xFFFF_FFFF or 0x1234_5678
        await csr.write("FW_SEED", addr, seed, length=8)
        readback = await csr.read("FW_SEED_RDBK", addr, length=8)
        assert readback == seed, (
            f"{instance}: RNG seed readback {readback:#x} != {seed:#x}; the firmware "
            "would fall back to a frozen LFSR"
        )
        self.log.info("%s: firmware RNG seeded %#010x", instance, seed)

    async def _publish_i2c_target_ids(self, csr: DualCsr, instance: str) -> None:
        """Tell this instance's firmware which I2C addresses the target answers on.

        occp_interface_latch_test/main.c reads them out of scratch 4, packed one
        per byte in channel order, and has no other way to learn them: the
        addresses live in the *target's* eFuse. Skipped when the image left the
        slots unprogrammed, so scratch 4 stays 0 and any firmware that reads it
        sees the same "not provided" it saw before.

        Controller only. On the target that index is the JUMP base
        (SCRATCH_JUMP_BASE), which smc_occp_random_jump_test publishes there;
        writing addresses into it would collide. The reference writes the master
        BFM's scratch 4 for the same reason.
        """
        from smc_occp_dual_defs import SCRATCH_I2C_TARGET_IDS, occp_i2c_address

        if instance != "bfm":
            return
        packed = 0
        if self.fuse_i2c_ids:
            for byte, slot in enumerate(sorted(self.fuse_i2c_ids)):
                packed |= (self.fuse_i2c_ids[slot] & 0x7F) << (8 * byte)
        else:
            # Unprogrammed slots: the ROM derives both channels from the CHIP_ID
            # straps instead, so the controller has to be told the same address
            # rather than left with zero.
            derived = occp_i2c_address(self.chip_id)
            packed = derived | (derived << 8)
        await csr.write("I2C_TARGET_IDS", SCRATCH_I2C_TARGET_IDS, packed, length=8)
        self.log.info(
            "%s: OCCP I2C target addresses published %#06x (%s)",
            instance,
            packed,
            (
                ", ".join(f"slot{s}={self.fuse_i2c_ids[s]:#04x}" for s in sorted(self.fuse_i2c_ids))
                if self.fuse_i2c_ids
                else f"from CHIP_ID straps {self.chip_id:#x}, slots unprogrammed"
            ),
        )

    def assert_no_fault_latched(self, label: str) -> None:
        """Require both instances' sticky fault latches to still read 0.

        ``dut_/bfm_{cluster_ded,wdt_first_timeout,wdt_second_timeout}_seen_o``
        latch the wrapper's fault outputs until cold reset, so a DED or a
        watchdog timeout at any point of the run is visible here even after
        the warm reset a second timeout causes has cleared the live pins.
        """
        dut = self.dut
        latched = [
            f"{inst}_{name}_seen_o"
            for inst in ("dut", "bfm")
            for name in ("cluster_ded", "wdt_first_timeout", "wdt_second_timeout")
            if int(getattr(dut, f"{inst}_{name}_seen_o").value) != 0
        ]
        assert not latched, f"{label}: fault outputs latched during the run: {latched}"
        self.log.info(
            "%s: no cluster DED or WDT timeout latched on either instance "
            "(dut/bfm cluster_ded, wdt_first_timeout, wdt_second_timeout all 0)",
            label,
        )

    def set_gpio_override(self, instance: str, pad: int, value: int | None) -> None:
        """Drive (or release) one pad on one instance.

        ``value=None`` releases the override so the pad returns to its idle
        pull-up / DUT-owned state.
        """
        dut = self.dut
        en_sig = getattr(dut, f"{instance}_gpio_ext_drive_en")
        val_sig = getattr(dut, f"{instance}_gpio_ext_drive_value")
        en = int(en_sig.value)
        val = int(val_sig.value)
        mask = 1 << pad
        if value is None:
            en &= ~mask
        else:
            en |= mask
            if value:
                val |= mask
            else:
                val &= ~mask
        en_sig.value = en
        val_sig.value = val

    def set_lc_state(self, instance: str, value: int) -> None:
        """Drive one instance's lifecycle state, by value not by encoded pair.

        Call before bring_up() releases cold reset: the wrapper samples this
        into CHIP_CONFIG.LC_STATE, and the ROM reads it during its own init.
        """
        encoded = encode_lc_state(value)
        getattr(self.dut, f"{instance}_lc_state").value = encoded
        self.log.info(
            "%s lifecycle state = %#x (encoded {diff_n, diff_p} = %#04x)",
            instance,
            value,
            encoded,
        )

    def set_dft_result(
        self,
        instance: str,
        *,
        mem_repair_done: int | None = None,
        mem_repair_success: int | None = None,
        mem_repair_abort: int | None = None,
        mbist_done: int | None = None,
        mbist_pass: int | None = None,
        mbist_abort: int | None = None,
    ) -> None:
        """Drive one instance's BISR/MBIST reporting lines; None leaves a line alone.

        Withholding `done` is how a timeout is expressed -- there is no separate
        timeout input, the boot sequencer simply never sees completion.
        """
        for name, value in (
            ("mem_repair_done", mem_repair_done),
            ("mem_repair_success", mem_repair_success),
            ("mem_repair_abort", mem_repair_abort),
            ("mbist_done", mbist_done),
            ("mbist_pass", mbist_pass),
            ("mbist_abort", mbist_abort),
        ):
            if value is None:
                continue
            getattr(self.dut, f"{instance}_{name}").value = value
            self.log.info("%s %s = %d", instance, name, value)

    def finalize_evidence(self) -> None:
        """Report the evidence this run produced, and grade it.

        ``dual_test`` runs it once the leaf has returned, after every compare
        has held: a leaf that already failed raised, and this must not turn
        that into a different complaint.
        """
        seen = sorted(self._evidence.seen)
        own = [check_id for check_id in seen if not _EvidenceRecorder.is_base(check_id)]
        missing = [check_id for check_id in self.required_evidence if check_id not in seen]
        self.log.info(
            "EVIDENCE_SUMMARY test=%s observed=%d own=%d required=%d missing=%d ids=%s",
            self.test_name,
            len(seen),
            len(own),
            len(self.required_evidence),
            len(missing),
            ",".join(seen) or "-",
        )
        problems: list[str] = []
        if not own:
            problems.append(
                "no CHK-* line of its own -- a run that grades nothing cannot be a pass"
            )
        if missing:
            problems.append("never emitted: " + ", ".join(missing))
        if problems:
            raise AssertionError(
                f"EVIDENCE FAIL {self.test_name}: "
                + "; ".join(problems)
                + " -- the run exited cleanly without grading what it claims to grade"
            )


def dual_test(
    required_evidence: tuple[str, ...],
) -> Callable[[Callable[[SmcDualHarness], Awaitable[None]]], Test]:
    """Register a plain cocotb leaf that runs over ``SmcDualHarness``.

    The leaf receives, in place of the DUT handle, a harness named after it
    and carrying ``required_evidence``. The evidence gate runs once the leaf
    returns, so no leaf has to remember it; a leaf that raised keeps its own
    failure.
    """

    def register(leaf: Callable[[SmcDualHarness], Awaitable[None]]) -> Test:
        @functools.wraps(leaf)
        async def run(_dut: object) -> None:
            harness = SmcDualHarness(test_name=leaf.__name__, required_evidence=required_evidence)
            await leaf(harness)
            harness.finalize_evidence()

        return cocotb.test()(run)

    return register
