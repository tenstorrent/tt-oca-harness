# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Shared clock/reset bring-up and AXI access for the dual-SMC OCCP tests."""

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
from env.smc_env_cfg import (
    PLL_PERIPH_CLK_PERIOD_NS,
    PLL_REF_CLK_PERIOD_NS,
    SYS_OUT_AXI_GEOMETRY,
    SYS_OUT_MEM_SIZE,
    check_pll_clock_periods,
    pll_sys_clk_period_ns,
)
from ocah_axi_vip import OcahAxiMasterAgent, OcahAxiSlaveAgent, OcahAxiSlaveSequence
from ocah_lib import require_file_plusargs
from smc_base_test import FILE_PLUSARGS, _EvidenceRecorder, log_build_model_identity

_DV_ROOT = Path(__file__).resolve().parents[2]
_EFUSE_DIR = _DV_ROOT / "efuse_preload"
assert _EFUSE_DIR.is_dir(), f"eFuse tooling not found at {_EFUSE_DIR}"

# Clock periods in ns, the pll_wrap values of hw/sys/smc/dv/cocotb/env/
# smc_env_cfg.py; the bench drives both instances' oscillators from one set.
# The settle is 500 ref cycles because powergood_stable is the end of a
# reset-sync chain and is still low at 200.
REF_CLK_PERIOD_NS = PLL_REF_CLK_PERIOD_NS
SMC_CLK_PERIOD_NS = pll_sys_clk_period_ns()
PERIPH_CLK_PERIOD_NS = PLL_PERIPH_CLK_PERIOD_NS

# powergood_stable ends a reset-sync chain and is still low 200 ref cycles after cold release.
POST_RESET_SETTLE_CYCLES = 500

STRAP_CAPTURE_TIMEOUT_CYCLES = 4000
STRAP_CAPTURE_SETTLE_CYCLES = 16


AXI_TIMEOUT_NS = 20_000

# The port carries {diff_n, diff_p}; halves that are not complements raise lc_sigint_err_o.
LC_STATE_WIDTH = 4

LC_STATE_TEST_DEV_VALUE = 0
LC_STATE_SECURE_VALUES = (1, 8)


def encode_lc_state(value: int) -> int:
    value &= (1 << LC_STATE_WIDTH) - 1
    return ((~value & ((1 << LC_STATE_WIDTH) - 1)) << LC_STATE_WIDTH) | value


LC_STATE_TEST_DEV = encode_lc_state(LC_STATE_TEST_DEV_VALUE)

# A 256-beat burst never completes through the AXI-to-TileLink bridge into the CPU cluster.
BULK_CHUNK_BYTES = 64

DUAL_TARGET = "dual"


def random_seed() -> int:
    return int(os.environ.get("RANDOM_SEED", "1"), 0)


FUSE_TRANSPORT_TIMEOUT_MIN = 400


def regenerate_efuse_image(seed: int) -> dict[int, int]:
    img = cocotb.plusargs.get("smc_efuse_hex")
    if img is None:
        return {}
    img_path = Path(str(img))

    randomized = img_path.parent / "efuse_config_randomized.toml"
    forced_timeout = cocotb.plusargs.get("fuse_transport_timeout")
    timeout_args = (
        [] if forced_timeout is None else ["--transport-timeout", str(int(str(forced_timeout), 0))]
    )
    i2c_args = ["--i2c-ids"] if cocotb.plusargs.get("fuse_i2c_ids") is not None else []
    # The generator needs Python 3.11+ (tomllib); a PATH python3 may be older than the venv.
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
        # Otherwise the stale image from the build stage runs under a seed it does not match.
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


_I2C_ID_RE = re.compile(r"I2C_I3C_ID\[(\d)\]=(0x[0-9a-fA-F]+)")


def _parse_i2c_ids(stdout: str) -> dict[int, int]:
    return {int(slot): int(addr, 0) for slot, addr in _I2C_ID_RE.findall(stdout)}


class DualCsr:
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

    # Only the *_result APIs check BRESP/RRESP; the bulk helpers below drive
    # init_write/init_read and grade the response themselves.
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

    def _require_okay(self, what: str, addr: int, raw) -> None:
        resp = getattr(raw, "resp", None)
        codes = resp if isinstance(resp, (list, tuple)) else [resp]
        if resp is None or any(int(c) > 1 for c in codes):
            raise AssertionError(f"{self.prefix} {what} @ {addr:#010x} returned resp={resp}")

    async def write_bytes(self, name: str, addr: int, data: bytes) -> None:
        # The scratch banks answer AXI only once the CPU cluster is out of reset.
        for off in range(0, len(data), BULK_CHUNK_BYTES):
            chunk = data[off : off + BULK_CHUNK_BYTES]
            event = self.seq.init_write(address=addr + off, data=chunk, size=3, prot=0)
            await with_timeout(event.wait(), AXI_TIMEOUT_NS, "ns")
            self._require_okay(f"write_bytes {name}", addr + off, event.data)
        cocotb.log.info(
            "%s write_bytes %s %#010x <- %d bytes in %d-byte chunks",
            self.prefix,
            name,
            addr,
            len(data),
            BULK_CHUNK_BYTES,
        )

    async def read_bytes(self, name: str, addr: int, length: int) -> bytes:
        out = bytearray()
        for off in range(0, length, BULK_CHUNK_BYTES):
            n = min(BULK_CHUNK_BYTES, length - off)
            event = self.seq.init_read(address=addr + off, length=n, size=3, prot=0)
            await with_timeout(event.wait(), AXI_TIMEOUT_NS, "ns")
            self._require_okay(f"read_bytes {name}", addr + off, event.data)
            out += bytes(event.data.data)
        cocotb.log.debug("%s read_bytes %s %#010x -> %d bytes", self.prefix, name, addr, length)
        return bytes(out)


class SmcDualHarness:
    def __init__(
        self,
        *,
        test_name: str = "",
        required_evidence: tuple[str, ...] = (),
        require_clean_tree: bool = True,
    ) -> None:
        self.dut = cocotb.top
        self.log = cocotb.log
        self.require_clean_tree = require_clean_tree
        self.test_name = test_name
        self.required_evidence = tuple(required_evidence)
        self._evidence = _EvidenceRecorder()
        self._evidence.install()
        self.cpu_trace = {
            inst: SmcCpuTraceState(f"{inst}-hart0", cocotb.log) for inst in ("dut", "bfm")
        }
        self.fuse_i2c_ids: dict[int, int] = {}
        self.boot_i2c = False
        self.straps: dict[str, int] = {"dut": 0, "bfm": 0}
        self.chip_id = 0
        self.sys_out_mem: dict[str, OcahAxiSlaveSequence] = {}

    def _attach_cpu_symbols(self) -> None:
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

        dut.tb_i3c0_scl_ext_low.value = 0
        dut.tb_i3c0_sda_ext_low.value = 0

        dut.dut_chiplet_is_primary.value = 1
        dut.bfm_chiplet_is_primary.value = 1

        # Boot stall is held from t=0 so reset vectors are programmed before either core fetches.
        dut.dut_boot_stall_hold.value = 1 if hold_dut_boot else 0
        dut.bfm_boot_stall_hold.value = 1 if hold_bfm_boot else 0

        dut.dut_gpio_ext_drive_en.value = 0
        dut.dut_gpio_ext_drive_value.value = 0
        dut.bfm_gpio_ext_drive_en.value = 0
        dut.bfm_gpio_ext_drive_value.value = 0

        dut.dut_lc_state.value = LC_STATE_TEST_DEV
        dut.bfm_lc_state.value = LC_STATE_TEST_DEV

        # STATUS_SMU bits stick at 1 until reset, so dft_low lines must be 0 before cold release.
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
        log_build_model_identity(
            require_clean_tree=self.require_clean_tree, expect_target=DUAL_TARGET
        )
        dut = self.dut
        smc_clk_period_ns = SMC_CLK_PERIOD_NS
        self.log.info(
            "dual bring-up (pll_wrap): ref=%sns smc=%sns periph=%sns (seed=%d)",
            REF_CLK_PERIOD_NS,
            smc_clk_period_ns,
            PERIPH_CLK_PERIOD_NS,
            random_seed(),
        )
        self.idle_pins(hold_dut_boot=hold_dut_boot, hold_bfm_boot=hold_bfm_boot, dft_low=dft_low)

        # After idle_pins, which resets both to TEST_DEV, and before cold reset is released.
        if dut_lc_state is not None:
            self.set_lc_state("dut", dut_lc_state)
        if bfm_lc_state is not None:
            self.set_lc_state("bfm", bfm_lc_state)

        # The eFuse bank reads its image when rst_ni releases, so regenerate it before any reset.
        self.fuse_i2c_ids = regenerate_efuse_image(random_seed())

        # A cool reset must drop in-flight responses, not return them into the reset cluster.
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
        cocotb.start_soon(Clock(dut.clk_smc_i, smc_clk_period_ns, unit="ns").start())
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

        # A force issued at time 0 is accepted but has no effect, so straps wait until here.
        self._apply_straps()

        self.log.info("asserting powergood on both instances")
        dut.powergood_i.value = 1
        await ClockCycles(dut.clk_ref_i, 10)
        self.log.info("releasing cold reset on both instances")
        dut.rst_cold_ni.value = 1
        await self._await_strap_capture()
        await ClockCycles(dut.clk_ref_i, POST_RESET_SETTLE_CYCLES)
        await check_pll_clock_periods(
            self.log,
            {
                "clk_ref_o": (dut.clk_ref_o, REF_CLK_PERIOD_NS),
                "clk_smc_o": (dut.clk_smc_o, smc_clk_period_ns),
                "clk_periph_o": (dut.clk_periph_o, PERIPH_CLK_PERIOD_NS),
            },
        )

    async def release_cpu(
        self,
        csr: DualCsr,
        instance: str,
        reset_vector: int,
        *,
        seed_firmware_rng: bool = True,
    ) -> None:
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
        # The core latches RESET_VECTOR only at tile reset, so write it before boot_stall drops.
        for idx, addr in enumerate(CPU_CTRL_RESET_VECTOR):
            await csr.write(f"RESET_VECTOR_{idx}", addr, reset_vector, length=8)
        # Release every core; one left in reset holds isolate_req high and clamps MMIO.
        await csr.write("RESET_RELEASE", CPU_CTRL_RESET_CTRL, CPU_RESET_CTRL_DEFAULT, length=8)
        await ClockCycles(dut.clk_smc_i, 64)

        # Cores are out of reset (scratch answers AXI) and boot_stall is up (seed not yet latched).
        if seed_firmware_rng:
            await self._seed_firmware_rng(csr, instance, SCRATCH_FW_SEED)
            await self._publish_i2c_target_ids(csr, instance)
            await self._check_boot_interface_strap(csr, instance)

        getattr(dut, f"{instance}_boot_stall_hold").value = 0
        await ClockCycles(dut.clk_smc_i, 256)
        self.log.info("%s: released boot_stall with reset_vector=%#010x", instance, reset_vector)

    async def _await_strap_capture(self) -> None:
        dut = self.dut
        # Straps latch on rst_cold_stable_ref_clk_no, which rises well after rst_cold_ni.
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
        inst = getattr(self.dut, f"u_{instance}")
        # Without forceable on rom_straps in smc_public_scope.vlt this force is a silent no-op.
        inst.u_smc_wrapper.u_smc_ip_integration.rom_straps.value = Force(value)
        self.straps[instance] = value

    def set_strap_bit(self, instance: str, bit: int) -> None:
        self.set_straps(instance, self.straps[instance] | (1 << bit))

    def _apply_straps(self) -> None:
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

        # This tree instantiates no PLL, so BL0_PLLCLK must stay clear.
        named = {name for name in STRAP_BITS if cocotb.plusargs.get(name) is not None}
        target = sum(1 << STRAP_BITS[name] for name in named)
        if named:
            self.log.info("straps set by plusarg: %s", ", ".join(sorted(named)))

        if cocotb.plusargs.get("FORCE_STATUS_REPORTING") is not None:
            status_rpt_disable = 0
        elif "STATUS_RPT_DISABLE" in named:
            status_rpt_disable = 1
        else:
            status_rpt_disable = random.choice([0, 1])
        target |= status_rpt_disable << STRAP_BITS["STATUS_RPT_DISABLE"]
        controller = status_rpt_disable << STRAP_BITS["STATUS_RPT_DISABLE"]
        self.log.info("STATUS_RPT_DISABLE strap: %d", status_rpt_disable)

        # Set, the ROM zeroes SRAM in software, which costs sim time; only a plusarg sets it.
        if cocotb.plusargs.get("FORCE_HW_AUTO_ZERO") is not None or random.choice([True, False]):
            target &= ~(1 << STRAP_BITS["SRAM_AUTO_ZERO_DISABLE"])
        self.log.info(
            "SRAM_AUTO_ZERO_DISABLE strap: %d",
            (target >> STRAP_BITS["SRAM_AUTO_ZERO_DISABLE"]) & 1,
        )

        for name in ("TEST_EN", "SPI_USE_FUSED_CONFIG", "BOOT_RECOVERY", "ROTATE_UPDATE"):
            if name not in named:
                target |= random.choice([0, 1]) << STRAP_BITS[name]

        self.chip_id = random.randint(0, 0xF)
        target |= chip_id_straps(self.chip_id)
        self.log.info("CHIP_ID straps: %#x", self.chip_id)

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

        # PRIMARY_CHIPLET must match chiplet_is_primary_i or firmware misreads the boot master.
        for instance, value in (("dut", target), ("bfm", controller)):
            self.set_straps(instance, value | (1 << STRAP_PRIMARY_CHIPLET))
        self.log.info("straps forced: dut=%#x bfm=%#x", self.straps["dut"], self.straps["bfm"])

    async def _check_boot_interface_strap(self, csr: DualCsr, instance: str) -> None:
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
        # Zero is the firmware LFSR's dead state (every draw returns 0), so force a non-zero seed.
        seed = (random_seed() * 2_654_435_761) & 0xFFFF_FFFF or 0x1234_5678
        await csr.write("FW_SEED", addr, seed, length=8)
        readback = await csr.read("FW_SEED_RDBK", addr, length=8)
        assert readback == seed, (
            f"{instance}: RNG seed readback {readback:#x} != {seed:#x}; the firmware "
            "would fall back to a frozen LFSR"
        )
        self.log.info("%s: firmware RNG seeded %#010x", instance, seed)

    async def _publish_i2c_target_ids(self, csr: DualCsr, instance: str) -> None:
        from smc_occp_dual_defs import SCRATCH_I2C_TARGET_IDS, occp_i2c_address

        # On the target this index is SCRATCH_JUMP_BASE, so writing addresses there collides.
        if instance != "bfm":
            return
        packed = 0
        if self.fuse_i2c_ids:
            for byte, slot in enumerate(sorted(self.fuse_i2c_ids)):
                packed |= (self.fuse_i2c_ids[slot] & 0x7F) << (8 * byte)
        else:
            # Unprogrammed slots: the target's ROM falls back to the CHIP_ID-derived address.
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
        # Call before bring_up() releases cold reset; the ROM reads LC_STATE during its init.
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
    def register(leaf: Callable[[SmcDualHarness], Awaitable[None]]) -> Test:
        @functools.wraps(leaf)
        async def run(_dut: object) -> None:
            require_file_plusargs(FILE_PLUSARGS)
            harness = SmcDualHarness(test_name=leaf.__name__, required_evidence=required_evidence)
            await leaf(harness)
            harness.finalize_evidence()

        return cocotb.test()(run)

    return register
