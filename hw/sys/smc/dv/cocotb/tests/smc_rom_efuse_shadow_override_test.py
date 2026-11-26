# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""A shadow override written during boot stall must be what the production ROM uses.

Boot stall holds the CPU in reset but lets fuse sensing finish (clk_rst.adoc). Once
fuse_sense_done is up, the JTAG-facing eFuse port (``ej_axi`` on this bench, port_table.adoc)
can rewrite a shadow register in TEST_DEV while its write lock is clear; the OTP is not
programmed, so the next sense reloads it. The ROM programs I2C0 TARGET_ID.ADDRESS0 from the low
seven bits of I2C_I3C_ID slot 6 (interfaces.adoc).

    1. The seeded image programs slot 6 with a legal address A and slot 7 with C.
    2. With the CPU still stalled and sensing done, ej_axi writes a different legal B to slot 6
       and reads it back.
    3. The ROM boots to OCCP_PROC; I2C0 ADDRESS0 must be B, not A or the 0x55 fallback, and
       I2C1 ADDRESS0 must be C.
    4. A cold reset re-senses the OTP and slot 6 reads A again. No OTP program request is
       seen in the whole run.

This needs the single-SMC target: the dual target ties ej_axi off. It proves the JTAG-facing
AXI-Lite port only, not a JTAG TAP or JTAG-to-AXI bridge in front of it.

Plusargs:
    +rom_bin64=<prod_rom.bin64>      production ROM                      (required)
    +smc_hold_cpu_boot               stall the CPU from t=0              (required)
    +fuse_i2c_ids                    program slots 6 and 7               (required)
    +smc_efuse_hex=<relative path>   image this leaf writes and senses   (required)
"""

from __future__ import annotations

import random

import cocotb
import pyuvm
from cocotb.triggers import ClockCycles, RisingEdge
from env.smc_efuse_stimulus import regenerate_efuse_image
from env.smc_sys_axi_agent import idle_axil_master_inputs
from ocah_axi_vip import OcahAxiLiteMasterAgent
from seq_lib.smc_prod_rom_boot_seq import smc_prod_rom_boot_seq
from seq_lib.smc_prod_rom_defs import describe_post_code
from smc_base_test import smc_base_test
from smc_reg import (
    SMC_EFUSE_MAP_HARNESS_LOCKS_REG_ADDR,
    SMC_EFUSE_MAP_I2C_I3C_ID_6__REG_ADDR,
    SMC_I2C_WRAP_I2C_0__TARGET_ID_REG_ADDR,
    SMC_I2C_WRAP_I2C_1__TARGET_ID_REG_ADDR,
)

I2C_ADDR_MIN = 0x08
I2C_ADDR_MAX = 0x77
I2C_ADDR_FALLBACK = 0x55
ADDRESS0_MASK = 0x7F
LOCKS_I2C_I3C_ID_WRITE_LOCK = 1 << 2
# lc_state_i = {diff_n, diff_p} for TEST_DEV (port_table.adoc).
LC_STATE_TEST_DEV = 0xF0
AXI_OKAY = 0
JTAG_ACCESS_TIMEOUT_NS = 2000

SENSE_BOUND_CYCLES = 200_000
RESET_ASSERT_BOUND_REF = 400
RESET_HOLD_REF = 32
RESET_RELEASE_BOUND_REF = 4000


def pick_override(seed: int, original: int, other: int) -> int:
    rng = random.Random(f"smc-efuse-shadow-{seed}")
    excluded = {original, other, I2C_ADDR_FALLBACK}
    return rng.choice([a for a in range(I2C_ADDR_MIN, I2C_ADDR_MAX + 1) if a not in excluded])


async def _wait_level(clk, signal, level: int, bound: int, what: str) -> int:
    for cycle in range(bound + 1):
        if signal.value.is_resolvable and int(signal.value) == level:
            return cycle
        await RisingEdge(clk)
    raise AssertionError(f"{what}: the signal never reached {level} within {bound} cycles")


class _ProgramRequestCounter:
    """Counts eFuse program requests from before bring-up; any one would touch the OTP."""

    def __init__(self, dut) -> None:
        self.dut = dut
        self.count = 0
        self.unresolved = 0
        cocotb.start_soon(self._watch())

    async def _watch(self) -> None:
        dut = self.dut
        last = 0
        while True:
            await RisingEdge(dut.clk_smc_i)
            value = dut.tb_efuse_program_req_valid.value
            if not value.is_resolvable:
                # Out of reset, an X/Z valid can hide a request.
                reset_n = dut.rst_primary_smc_clk_no.value
                if reset_n.is_resolvable and int(reset_n):
                    self.unresolved += 1
                continue
            now = int(value)
            if now and not last:
                self.count += 1
            last = now

    def require_none(self, span: str) -> None:
        if self.count or self.unresolved:
            raise AssertionError(
                f"{span}: {self.count} eFuse program request(s) and {self.unresolved} X/Z "
                "tb_efuse_program_req_valid sample(s) out of reset; the OTP may have been touched"
            )


class _ShadowOverrideSeq(smc_prod_rom_boot_seq):
    def __init__(self, name: str, *, jtag, slot6: int, slot7: int, override: int, programs):
        super().__init__(name)
        self.jtag = jtag
        self.slot6 = slot6
        self.slot7 = slot7
        self.override = override
        self.programs = programs

    async def _jtag_read(self, label: str, addr: int) -> int:
        result = await self.jtag.read_result(
            addr, check_response=False, timeout_ns=JTAG_ACCESS_TIMEOUT_NS
        )
        if int(result.resp) != AXI_OKAY:
            raise AssertionError(f"ej_axi read {label} @ {addr:#010x} returned resp={result.resp}")
        return int(result.data) & 0xFFFF_FFFF

    async def _jtag_write(self, label: str, addr: int, data: int) -> None:
        result = await self.jtag.write_result(
            addr, data, check_response=False, timeout_ns=JTAG_ACCESS_TIMEOUT_NS
        )
        if int(result.resp) != AXI_OKAY:
            raise AssertionError(
                f"ej_axi write {label} {data:#x} @ {addr:#010x} returned resp={result.resp}"
            )

    async def _slot6(self) -> tuple[int, int]:
        low = await self._jtag_read("I2C_I3C_ID_6_LO", SMC_EFUSE_MAP_I2C_I3C_ID_6__REG_ADDR)
        high = await self._jtag_read("I2C_I3C_ID_6_HI", SMC_EFUSE_MAP_I2C_I3C_ID_6__REG_ADDR + 4)
        return low, high

    async def _override_during_stall(self) -> None:
        dut = cocotb.top
        sensed = await _wait_level(
            dut.clk_smc_i, dut.tb_fuse_sense_done, 1, SENSE_BOUND_CYCLES, "fuse sense"
        )
        stalled = int(dut.tb_boot_stall_combined_o.value)
        rom_reads = int(dut.tb_cpu_rom_read_count.value)
        if stalled != 1 or rom_reads != 0:
            raise AssertionError(
                f"fuse sense finished with boot_stall_combined_o={stalled} and {rom_reads} CPU ROM "
                "reads; the override must land before the CPU fetches"
            )
        cocotb.log.info(
            "CHK-EFUSE-SHADOW-STALL: fuse_sense_done=1 (after %d clk_smc_i of waiting) while "
            "boot_stall_combined_o=1 and tb_cpu_rom_read_count=0",
            sensed,
        )

        lc_state = int(dut.tb_lc_state.value)
        locks = await self._jtag_read("LOCKS", SMC_EFUSE_MAP_HARNESS_LOCKS_REG_ADDR)
        before = await self._slot6()
        if lc_state != LC_STATE_TEST_DEV or locks & LOCKS_I2C_I3C_ID_WRITE_LOCK:
            raise AssertionError(
                f"override precondition: lc_state_i={lc_state:#04x} (TEST_DEV is "
                f"{LC_STATE_TEST_DEV:#04x}), LOCKS={locks:#010x} (I2C_I3C_ID write lock bit 2)"
            )
        if before != (self.slot6, 0):
            raise AssertionError(f"slot 6 sensed {before}, the image programs ({self.slot6:#x}, 0)")
        await self._jtag_write(
            "I2C_I3C_ID_6_LO", SMC_EFUSE_MAP_I2C_I3C_ID_6__REG_ADDR, self.override
        )
        await self._jtag_write("I2C_I3C_ID_6_HI", SMC_EFUSE_MAP_I2C_I3C_ID_6__REG_ADDR + 4, 0)
        after = await self._slot6()
        if after != (self.override, 0):
            raise AssertionError(f"slot 6 reads back {after} after writing ({self.override:#x}, 0)")
        cocotb.log.info(
            "CHK-EFUSE-SHADOW-WRITE: lc_state_i=%#04x (TEST_DEV), LOCKS=%#010x (I2C_I3C_ID write "
            "lock clear); ej_axi rewrote slot 6 from A=%#04x to B=%#04x, OKAY, read back %#x",
            lc_state,
            locks,
            self.slot6,
            self.override,
            after[0],
        )
        self.programs.require_none("from bring-up through the override")
        cocotb.log.info(
            "CHK-EFUSE-SHADOW-NO-OTP-PROGRAM: no eFuse program request from bring-up through "
            "the override (tb_efuse_program_req_valid never rose and never read X/Z out of reset)"
        )

    async def _rom_addresses(self) -> tuple[int, int]:
        i2c0 = await self.csr_read("I2C0_TARGET_ID", SMC_I2C_WRAP_I2C_0__TARGET_ID_REG_ADDR)
        i2c1 = await self.csr_read("I2C1_TARGET_ID", SMC_I2C_WRAP_I2C_1__TARGET_ID_REG_ADDR)
        return i2c0 & ADDRESS0_MASK, i2c1 & ADDRESS0_MASK

    async def _resense(self) -> tuple[int, int]:
        dut = cocotb.top
        dut.rst_cold_ni.value = 0
        await _wait_level(
            dut.clk_ref_i, dut.rst_primary_smc_clk_no, 0, RESET_ASSERT_BOUND_REF, "cold assert"
        )
        cleared = await _wait_level(
            dut.clk_smc_i, dut.tb_fuse_sense_done, 0, SENSE_BOUND_CYCLES, "fuse sense clear"
        )
        await ClockCycles(dut.clk_ref_i, RESET_HOLD_REF)
        dut.rst_cold_ni.value = 1
        await _wait_level(
            dut.clk_ref_i, dut.rst_primary_smc_clk_no, 1, RESET_RELEASE_BOUND_REF, "release"
        )
        resensed = await _wait_level(
            dut.clk_smc_i, dut.tb_fuse_sense_done, 1, SENSE_BOUND_CYCLES, "fuse re-sense"
        )
        return cleared, resensed

    async def body(self) -> None:
        await self._override_during_stall()
        await super().body()
        i2c0, i2c1 = await self._rom_addresses()
        if i2c0 != self.override or i2c0 in (self.slot6, I2C_ADDR_FALLBACK) or i2c1 != self.slot7:
            raise AssertionError(
                f"ROM programmed I2C0 ADDRESS0={i2c0:#04x} (want override B={self.override:#04x}, "
                f"not A={self.slot6:#04x} or {I2C_ADDR_FALLBACK:#04x}) and I2C1 ADDRESS0="
                f"{i2c1:#04x} (want slot 7 C={self.slot7:#04x})"
            )
        cocotb.log.info(
            "CHK-EFUSE-SHADOW-ROM-USED: at POST %s the ROM had programmed I2C0 ADDRESS0=%#04x "
            "(override B; A=%#04x) and I2C1 ADDRESS0=%#04x (untouched slot 7)",
            describe_post_code(self.post_code),
            i2c0,
            self.slot6,
            i2c1,
        )

        cleared, resensed = await self._resense()
        restored = await self._slot6()
        if restored != (self.slot6, 0):
            raise AssertionError(
                f"after the cold reset slot 6 reads {restored}, want ({self.slot6:#x}, 0)"
            )
        self.programs.require_none("in the run")
        cocotb.log.info(
            "CHK-EFUSE-SHADOW-RESENSE: cold reset cleared fuse_sense_done (%d clk_smc_i) and "
            "sensing finished again (%d clk_smc_i); slot 6 reads A=%#04x again; no eFuse program "
            "request in the run",
            cleared,
            resensed,
            restored[0],
        )


@pyuvm.test()
class smc_rom_efuse_shadow_override_test(smc_base_test):
    """Boot-stall ej_axi override of I2C slot 6 reaches the ROM; re-sense restores the OTP."""

    required_evidence = (
        "CHK-EFUSE-SHADOW-STALL",
        "CHK-EFUSE-SHADOW-WRITE",
        "CHK-EFUSE-SHADOW-NO-OTP-PROGRAM",
        "CHK-EFUSE-SHADOW-ROM-USED",
        "CHK-EFUSE-SHADOW-RESENSE",
    )
    min_evidence = 5
    auto_protocol_vip = False
    run_written_file_plusargs = ("smc_efuse_hex",)

    def build_phase(self) -> None:
        super().build_phase()
        for name in ("smc_hold_cpu_boot", "fuse_i2c_ids", "smc_efuse_hex"):
            if name not in cocotb.plusargs:
                raise AssertionError(f"smc_rom_efuse_shadow_override_test requires +{name}")
        # The bank model reads the image at its first reset release, after build_phase.
        self.stim = regenerate_efuse_image(self.random_seed(), cocotb.plusargs)
        slot6 = self.stim.i2c_ids.get(6)
        if slot6 is None or not I2C_ADDR_MIN <= slot6 <= I2C_ADDR_MAX:
            raise AssertionError(f"image slot 6 = {slot6!r}, not a legal I2C address")

    async def _bring_up(self) -> None:
        self.programs = _ProgramRequestCounter(cocotb.top)
        await super()._bring_up()

    async def run_scenario(self) -> None:
        dut = cocotb.top
        idle_axil_master_inputs(dut, "ej_axi")
        jtag = OcahAxiLiteMasterAgent.from_prefix(
            dut,
            "ej_axi",
            dut.clk_smc_i,
            dut.rst_primary_smc_clk_no,
            name="smc_ej_axil",
            reset_active_level=False,
        ).sequence
        slot6, slot7 = self.stim.i2c_ids[6], self.stim.i2c_ids[7]
        override = pick_override(self.random_seed(), slot6, slot7)
        self.logger.info(
            "slot 6 A=%#04x, slot 7 C=%#04x, override B=%#04x (seed %d)",
            slot6,
            slot7,
            override,
            self.random_seed(),
        )
        seq = _ShadowOverrideSeq(
            "efuse_shadow_override_seq",
            jtag=jtag,
            slot6=slot6,
            slot7=slot7,
            override=override,
            programs=self.programs,
        )
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
