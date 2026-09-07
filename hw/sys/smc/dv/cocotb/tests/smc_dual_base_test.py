# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Shared bring-up for the dual-SMC OCCP tests.

Thinner than hw/sys/smc/dv/cocotb/tests/smc_base_test.py: that
harness builds the whole single-instance SmcEnv against tb_top.sv's ~400-port
surface, none of which exists on tb_top.sv (SMC_DUAL half). Here both instances share one
clock/reset bring-up and each gets its own inbound AXI master.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles, with_timeout
from ocah_axi_vip import OcahAxiMasterAgent

# This file lives at hw/sys/smc/dv/cocotb/tests/<this>.py, so the DV root is six
# levels up from the file and one below the repo root. Anchored on the DV root
# rather than the repo root: it is the nearer landmark, so a future move of
# hw/sys/ does not silently retarget this.
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


AXI_TIMEOUT_NS = 20_000

# Bytes per bulk AXI transaction. One 64-byte scratch-bank stripe, and small
# enough that the AXI-to-TileLink bridge into the CPU cluster carries it; see
# DualCsr.write_bytes for the 256-beat burst that did not.
BULK_CHUNK_BYTES = 64


def random_seed() -> int:
    return int(os.environ.get("RANDOM_SEED", "1"), 0)


def regenerate_efuse_image(seed: int) -> None:
    """Rewrite this run's eFuse image, seeded, before reset is released.

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
        return
    img_path = Path(str(img))

    # The generator needs tomllib (3.11+). The interpreter running cocotb is the
    # repo venv, which satisfies that; sys.executable keeps us on it rather than
    # whatever `python3` resolves to on PATH.
    randomized = img_path.parent / "efuse_config_randomized.toml"
    try:
        subprocess.run(
            [
                sys.executable,
                str(_EFUSE_DIR / "randomize_efuse.py"),
                str(_EFUSE_DIR / "configurations/default_efuse.toml"),
                "--output_file",
                str(randomized),
                "--seed",
                str(seed),
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

    async def write(self, name: str, addr: int, data: int, length: int = 4) -> None:
        event = self.seq.init_write(
            address=addr,
            data=data.to_bytes(length, "little"),
            size=self._axi_size(length),
            prot=0,
        )
        await with_timeout(event.wait(), AXI_TIMEOUT_NS, "ns")
        cocotb.log.debug("%s write %s %#x <- %#x", self.prefix, name, addr, data)

    async def read(self, name: str, addr: int, length: int = 4) -> int:
        event = self.seq.init_read(
            address=addr,
            length=length,
            size=self._axi_size(length),
            prot=0,
        )
        await with_timeout(event.wait(), AXI_TIMEOUT_NS, "ns")
        value = int.from_bytes(event.data.data, "little")
        cocotb.log.debug("%s read %s %#x -> %#x", self.prefix, name, addr, value)
        return value

    async def write_bytes(self, name: str, addr: int, data: bytes) -> None:
        """Bulk front-door write, for staging a firmware image in scratch SRAM.

        Reaches the CPU scratch window at 0xC006_xxxx; see
        smc_dual_axi_sram_probe_test for the measurement that this path works,
        and note it only works with the instance's warm reset domain released
        (boot_stall low), because the scratch banks hang off the CPU cluster.

        Chunked at BULK_CHUNK_BYTES rather than handed to the VIP as one
        transfer. Letting cocotbext-axi size the burst itself produces
        awlen=255, and a 256-beat burst into the cluster's front port never
        completes -- measured: the write went out at 377760ns and no response
        ever came back. The AXI-to-TileLink bridge does not carry bursts that
        long, so keep each transaction inside one 64-byte line, which is also
        the scratch banks' stripe granularity.
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
    """Clock/reset bring-up plus per-instance idle pin defaults."""

    def __init__(self) -> None:
        self.dut = cocotb.top
        self.log = cocotb.log

    def idle_pins(self, *, hold_dut_boot: bool, hold_bfm_boot: bool) -> None:
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

    async def bring_up(self, *, hold_dut_boot: bool = True, hold_bfm_boot: bool = True) -> None:
        dut = self.dut
        self.log.info(
            "dual bring-up: ref=%dns smc=%dns periph=%dns (seed=%d)",
            REF_CLK_PERIOD_NS,
            SMC_CLK_PERIOD_NS,
            PERIPH_CLK_PERIOD_NS,
            random_seed(),
        )
        self.idle_pins(hold_dut_boot=hold_dut_boot, hold_bfm_boot=hold_bfm_boot)

        # Before any reset is released -- the eFuse bank reads its image on
        # rst_ni, so this is the last point at which the contents can still be
        # chosen for this run.
        regenerate_efuse_image(random_seed())

        cocotb.start_soon(Clock(dut.clk_ref_i, REF_CLK_PERIOD_NS, unit="ns").start())
        cocotb.start_soon(Clock(dut.clk_smc_i, SMC_CLK_PERIOD_NS, unit="ns").start())
        cocotb.start_soon(Clock(dut.clk_periph_i, PERIPH_CLK_PERIOD_NS, unit="ns").start())

        await ClockCycles(dut.clk_ref_i, 10)
        self.log.info("asserting powergood on both instances")
        dut.powergood_i.value = 1
        await ClockCycles(dut.clk_ref_i, 10)
        self.log.info("releasing cold reset on both instances")
        dut.rst_cold_ni.value = 1
        await ClockCycles(dut.clk_ref_i, POST_RESET_SETTLE_CYCLES)

    async def release_cpu(self, csr: DualCsr, instance: str, reset_vector: int) -> None:
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

        getattr(dut, f"{instance}_boot_stall_hold").value = 0
        await ClockCycles(dut.clk_smc_i, 256)
        self.log.info("%s: released boot_stall with reset_vector=%#010x", instance, reset_vector)

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
