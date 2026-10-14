# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Sequence for smu_isolation_retention_test. No Force.

Steps S1-S5, checkers CHK-ISO-RETAIN-S1..S4.
Spec: hw/sys/smc/doc/clk_rst.adoc (Isolation Controls, Isolation Connections, Timing and Recovery).

The isolation registers and the FLR counters are cold-reset state: a cool
(primary) reset keeps them and a stable cold reset clears them.
``ISOLATE_REQ_PINEN_REG`` clears on cold reset only while the synchronized
isolation pin, GPIO 53, is low. ``ISOLATE_REQ_SMC_REG`` is set by an FLR edge on
``cfg_flr_pf_active_i``. Both FLR counters stay at zero while an FLR edge is
driven, so the timed FLR cool reset never starts.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import ClockCycles, RisingEdge
from ocah_jtag_vip import OcahJtagState

from seq_lib.smu_addr_map import reset_unit_u32, smc_addr
from seq_lib.smu_jtag_helpers import (
    DTP_DEFAULT_IDCODE,
    J2A_STATUS_SUCCESS,
    SMC_DBG_AXSIZE_4B,
    axi64_pack32,
    axi64_unpack32,
    jtag2axi_single_read,
    jtag2axi_single_write,
    make_smu_jtag_tap,
    require_jtag_tdo_resolved,
)

ISOLATE_REQ_REG = smc_addr("SMC_TOP_SMC_RESET_UNIT_ISOLATE_REQ_REG_BASE_ADDR")
ISOLATE_REQ_PINEN_REG = smc_addr("SMC_TOP_SMC_RESET_UNIT_ISOLATE_REQ_PINEN_REG_BASE_ADDR")
ISOLATE_REQ_SMC_REG = smc_addr("SMC_TOP_SMC_RESET_UNIT_ISOLATE_REQ_SMC_REG_BASE_ADDR")
ISOLATE_REQ_SMCEN_REG = smc_addr("SMC_TOP_SMC_RESET_UNIT_ISOLATE_REQ_SMCEN_REG_BASE_ADDR")
FLR_COUNTER = smc_addr("SMC_TOP_SMC_RESET_UNIT_ISOLATE_REQ_FLR_COUNTER_VALUE_BASE_ADDR")
FLR_RESET_COUNTER = smc_addr("SMC_TOP_SMC_RESET_UNIT_ISOLATE_REQ_FLR_RESET_COUNTER_VALUE_BASE_ADDR")

REG_BM = reset_unit_u32("RESET_UNIT__ISOLATE_REQ_REG__ISOLATE_REQ_REG_bm")
PINEN_BM = reset_unit_u32("RESET_UNIT__ISOLATE_REQ_PINEN_REG__ISOLATE_REQ_PINEN_REG_bm")
SMC_BM = reset_unit_u32("RESET_UNIT__ISOLATE_REQ_SMC_REG__ISOLATE_REQ_SMC_REG_bm")
SMCEN_BM = reset_unit_u32("RESET_UNIT__ISOLATE_REQ_SMCEN_REG__ISOLATE_REQ_SMCEN_REG_bm")
COUNTER_BM = reset_unit_u32(
    "RESET_UNIT__ISOLATE_REQ_FLR_COUNTER_VALUE__ISOLATE_REQ_FLR_COUNTER_VALUE_bm"
)
RESET_COUNTER_BM = reset_unit_u32(
    "RESET_UNIT__ISOLATE_REQ_FLR_RESET_COUNTER_VALUE__ISOLATE_REQ_FLR_RESET_COUNTER_VALUE_bm"
)
REG_RESET = reset_unit_u32("RESET_UNIT__ISOLATE_REQ_REG__ISOLATE_REQ_REG_reset")
SMC_RESET = reset_unit_u32("RESET_UNIT__ISOLATE_REQ_SMC_REG__ISOLATE_REQ_SMC_REG_reset")
SMCEN_RESET = reset_unit_u32("RESET_UNIT__ISOLATE_REQ_SMCEN_REG__ISOLATE_REQ_SMCEN_REG_reset")
PINEN_RESET = reset_unit_u32("RESET_UNIT__ISOLATE_REQ_PINEN_REG__ISOLATE_REQ_PINEN_REG_reset")
COUNTER_RESET = reset_unit_u32(
    "RESET_UNIT__ISOLATE_REQ_FLR_COUNTER_VALUE__ISOLATE_REQ_FLR_COUNTER_VALUE_reset"
)
RESET_COUNTER_RESET = reset_unit_u32(
    "RESET_UNIT__ISOLATE_REQ_FLR_RESET_COUNTER_VALUE__ISOLATE_REQ_FLR_RESET_COUNTER_VALUE_reset"
)

REG_VALUE = 0xA5A5_A5A5 & REG_BM
PINEN_VALUE = 0x5A5A_5A5A & PINEN_BM
SMCEN_VALUE = 0x3C3C_3C3C & SMCEN_BM
FLR_COUNTER_VALUE = 5
FLR_RESET_COUNTER_VALUE = 7

ISOLATION_PIN_GPIO = 53
RESET_PULSE_REF_CYCLES = 64
RESET_ASSERT_BOUND_REF_CYCLES = 128
RESET_RELEASE_BOUND_REF_CYCLES = 8192
POLL_BOUND_SMU_CYCLES = 64
SYNC_CYCLES = 32

STEP_ORDER = ["S1", "S2", "S3", "S4", "S5", "PASS"]


class smu_isolation_retention_test_seq:
    """Isolation registers and FLR counters against cool reset and cold reset."""

    def __init__(self, test) -> None:
        self.test = test
        self.dut = cocotb.top
        self.cfg = test.cfg
        self.log = test.logger
        self.sb = test.env.scoreboard
        self.steps: list[str] = []

    def _bit(self, name: str) -> int:
        pin = getattr(self.dut, name, None)
        if pin is None:
            raise AssertionError(f"{name} unobservable on this TB top")
        val = pin.value
        if not val.is_resolvable:
            raise AssertionError(f"X/Z on {name}: {val}")
        return int(val) & 1

    async def _rd32(self, addr: int, what: str) -> int:
        status, rdata = await jtag2axi_single_read(
            self.jtag,
            addr,
            size=SMC_DBG_AXSIZE_4B,
            require_complete=True,
        )
        require_jtag_tdo_resolved(f"{what} RD @0x{addr:08x}")
        if status != J2A_STATUS_SUCCESS:
            raise AssertionError(f"{what} read @0x{addr:08x} status={status}")
        return axi64_unpack32(addr, rdata)

    async def _wr32(self, addr: int, data: int, what: str) -> None:
        wstrb, beat = axi64_pack32(addr, data)
        status, _ = await jtag2axi_single_write(
            self.jtag,
            addr,
            beat,
            wstrb=wstrb,
            size=SMC_DBG_AXSIZE_4B,
            require_complete=True,
        )
        require_jtag_tdo_resolved(f"{what} WR @0x{addr:08x}")
        if status != J2A_STATUS_SUCCESS:
            raise AssertionError(f"{what} write @0x{addr:08x} status={status}")

    async def _wait_level(self, name: str, level: int, bound: int, what: str) -> int:
        for cycle in range(bound):
            if self._bit(name) == level:
                return cycle
            await RisingEdge(self.dut.clk_ref_i)
        raise AssertionError(f"TIMEOUT {what}: {name} never read {level} within {bound} clk_ref")

    def _require_csr_path(self) -> None:
        if self._bit("tb_smc_jtag2axi_security_disable"):
            raise AssertionError("SMC JTAG2AXI gated; the isolation CSRs cannot be accessed")

    async def _open_tap(self) -> None:
        self.jtag = make_smu_jtag_tap(self.dut, self.cfg.jtag_period_ns)
        await self.jtag.reset_tap()
        await self.jtag.goto_state(OcahJtagState.RUN_TEST_IDLE)
        for _ in range(8):
            await self.jtag.step_tms(0)
        idcode = await self.jtag.read_idcode()
        if idcode != DTP_DEFAULT_IDCODE:
            raise AssertionError(f"IDCODE want 0x{DTP_DEFAULT_IDCODE:x} got 0x{idcode:08x}")
        self._require_csr_path()

    def _drive_isolation_pin(self, level: int) -> None:
        dut = self.dut
        mask = 1 << ISOLATION_PIN_GPIO
        en = int(dut.tb_gpio_drive_en.value) | mask
        val = int(dut.tb_gpio_drive_val.value) & ~mask
        if level:
            val |= mask
        dut.tb_gpio_drive_val.value = val
        dut.tb_gpio_drive_en.value = en

    async def _cool_reset(self) -> None:
        dut = self.dut
        dut.tb_cool_reset_pin.value = 1
        await self._wait_level(
            "obs_smc_rst_n_o", 0, RESET_ASSERT_BOUND_REF_CYCLES, "cool reset assert"
        )
        await ClockCycles(dut.clk_ref_i, RESET_PULSE_REF_CYCLES)
        dut.tb_cool_reset_pin.value = 0
        await self._wait_level(
            "obs_smc_rst_n_o", 1, RESET_RELEASE_BOUND_REF_CYCLES, "cool reset release"
        )
        await ClockCycles(dut.clk_smu_i, SYNC_CYCLES)
        await self._open_tap()

    async def _cold_reset(self) -> None:
        dut = self.dut
        dut.rst_cold_ni.value = 0
        await ClockCycles(dut.clk_ref_i, RESET_PULSE_REF_CYCLES)
        dut.rst_cold_ni.value = 1
        await self._wait_level(
            "rst_cold_n_o", 1, RESET_RELEASE_BOUND_REF_CYCLES, "cold reset release"
        )
        await self._wait_level(
            "obs_smc_rst_n_o", 1, RESET_RELEASE_BOUND_REF_CYCLES, "cold reset SMC release"
        )
        await ClockCycles(dut.clk_smu_i, SYNC_CYCLES)
        await self._open_tap()

    async def _program_isolation(self) -> None:
        dut = self.dut
        await self._wr32(ISOLATE_REQ_REG, REG_VALUE, "ISOLATE_REQ_REG")
        await self._wr32(ISOLATE_REQ_PINEN_REG, PINEN_VALUE, "ISOLATE_REQ_PINEN_REG")
        await self._wr32(ISOLATE_REQ_SMCEN_REG, SMCEN_VALUE, "ISOLATE_REQ_SMCEN_REG")
        dut.tb_cfg_flr_pf_active.value = 0
        await ClockCycles(dut.clk_smu_i, SYNC_CYCLES)
        dut.tb_cfg_flr_pf_active.value = 1
        await ClockCycles(dut.clk_smu_i, SYNC_CYCLES)
        dut.tb_cfg_flr_pf_active.value = 0
        await ClockCycles(dut.clk_smu_i, SYNC_CYCLES)

    async def _read_isolation(self) -> dict[str, int]:
        return {
            "ISOLATE_REQ_REG": await self._rd32(ISOLATE_REQ_REG, "ISOLATE_REQ_REG"),
            "ISOLATE_REQ_PINEN_REG": await self._rd32(
                ISOLATE_REQ_PINEN_REG, "ISOLATE_REQ_PINEN_REG"
            ),
            "ISOLATE_REQ_SMC_REG": await self._rd32(ISOLATE_REQ_SMC_REG, "ISOLATE_REQ_SMC_REG"),
            "ISOLATE_REQ_SMCEN_REG": await self._rd32(
                ISOLATE_REQ_SMCEN_REG, "ISOLATE_REQ_SMCEN_REG"
            ),
        }

    async def _read_counters(self) -> tuple[int, int]:
        return (
            await self._rd32(FLR_COUNTER, "ISOLATE_REQ_FLR_COUNTER_VALUE"),
            await self._rd32(FLR_RESET_COUNTER, "ISOLATE_REQ_FLR_RESET_COUNTER_VALUE"),
        )

    async def run(self) -> None:
        dut = self.dut
        sb = self.sb
        await self.cfg.reset_done.wait()
        await self._open_tap()
        self._drive_isolation_pin(0)
        await ClockCycles(dut.clk_smu_i, SYNC_CYCLES)
        self.steps.append("S1")

        # S2: cool reset keeps all four isolation registers.
        await self._program_isolation()
        pre = await self._read_isolation()
        self.log.info("S2 pre-image: %s", {k: f"0x{v:08x}" for k, v in pre.items()})
        await self._cool_reset()
        post = await self._read_isolation()
        expect_s2 = {
            "ISOLATE_REQ_REG": REG_VALUE,
            "ISOLATE_REQ_PINEN_REG": PINEN_VALUE,
            "ISOLATE_REQ_SMC_REG": SMC_BM,
            "ISOLATE_REQ_SMCEN_REG": SMCEN_VALUE,
        }
        for name, want in expect_s2.items():
            sb.expect_eq(
                f"{name} keeps its programmed value 0x{want:x} across the cool reset",
                post[name],
                want,
                evidence="ISO_RETAIN_S1",
            )
        self.steps.append("S2")

        # S3: stable cold reset with the isolation pin low clears the registers.
        await self._program_isolation()
        await self._cold_reset()
        post = await self._read_isolation()
        for name, want in (
            ("ISOLATE_REQ_REG", REG_RESET),
            ("ISOLATE_REQ_SMC_REG", SMC_RESET),
            ("ISOLATE_REQ_SMCEN_REG", SMCEN_RESET),
        ):
            sb.expect_eq(
                f"{name} reads {want} after a cold reset with GPIO {ISOLATION_PIN_GPIO} low",
                post[name],
                want,
                evidence="ISO_RETAIN_S2",
            )
        self.steps.append("S3")

        # S4: PINEN clears on cold reset only while the isolation pin is low.
        await self._wr32(ISOLATE_REQ_PINEN_REG, PINEN_VALUE, "ISOLATE_REQ_PINEN_REG")
        self._drive_isolation_pin(0)
        await self._cold_reset()
        low = await self._rd32(ISOLATE_REQ_PINEN_REG, "ISOLATE_REQ_PINEN_REG")
        sb.expect_eq(
            f"ISOLATE_REQ_PINEN_REG reads {PINEN_RESET} after a cold reset with "
            f"GPIO {ISOLATION_PIN_GPIO} low",
            low,
            PINEN_RESET,
            evidence="ISO_RETAIN_S3",
        )
        await self._wr32(ISOLATE_REQ_PINEN_REG, PINEN_VALUE, "ISOLATE_REQ_PINEN_REG")
        self._drive_isolation_pin(1)
        await ClockCycles(dut.clk_smu_i, SYNC_CYCLES)
        await self._cold_reset()
        high = await self._rd32(ISOLATE_REQ_PINEN_REG, "ISOLATE_REQ_PINEN_REG")
        sb.expect_eq(
            f"ISOLATE_REQ_PINEN_REG keeps 0x{PINEN_VALUE:x} across a cold reset with "
            f"GPIO {ISOLATION_PIN_GPIO} high",
            high,
            PINEN_VALUE,
            evidence="ISO_RETAIN_S3",
        )
        self._drive_isolation_pin(0)
        await ClockCycles(dut.clk_smu_i, SYNC_CYCLES)
        self.steps.append("S4")

        # S5: FLR counters survive cool reset and clear on cold reset. PINEN is
        # cleared by the cold reset with the pin low again.
        await self._wr32(FLR_COUNTER, FLR_COUNTER_VALUE & COUNTER_BM, "FLR_COUNTER_VALUE")
        await self._wr32(
            FLR_RESET_COUNTER, FLR_RESET_COUNTER_VALUE & RESET_COUNTER_BM, "FLR_RESET_COUNTER"
        )
        await self._cool_reset()
        counter, reset_counter = await self._read_counters()
        sb.expect_eq(
            f"ISOLATE_REQ_FLR_COUNTER_VALUE keeps {FLR_COUNTER_VALUE} across the cool reset",
            counter,
            FLR_COUNTER_VALUE,
            evidence="ISO_RETAIN_S4",
        )
        sb.expect_eq(
            f"ISOLATE_REQ_FLR_RESET_COUNTER_VALUE keeps {FLR_RESET_COUNTER_VALUE} "
            "across the cool reset",
            reset_counter,
            FLR_RESET_COUNTER_VALUE,
            evidence="ISO_RETAIN_S4",
        )
        await self._cold_reset()
        counter, reset_counter = await self._read_counters()
        sb.expect_eq(
            "ISOLATE_REQ_FLR_COUNTER_VALUE reads its reset value after the cold reset",
            counter,
            COUNTER_RESET,
            evidence="ISO_RETAIN_S4",
        )
        sb.expect_eq(
            "ISOLATE_REQ_FLR_RESET_COUNTER_VALUE reads its reset value after the cold reset",
            reset_counter,
            RESET_COUNTER_RESET,
            evidence="ISO_RETAIN_S4",
        )
        self.steps.append("S5")

        self.steps.append("PASS")
        if self.steps != STEP_ORDER:
            raise AssertionError(f"CHK-NONVAC order fail: {self.steps} != {STEP_ORDER}")
        self.log.info("CHK-NONVAC: PASS (ordered fence S1<S2<S3<S4<S5<PASS)")
