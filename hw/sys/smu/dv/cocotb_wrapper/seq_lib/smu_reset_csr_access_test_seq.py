# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Sequence for smu_reset_csr_access_test. No Force.

Steps S1-S9,
checkers CHK-CSR-RESET-VALUES-S2..S4, CHK-CSR-ACCESS-S1..S3 and CHK-SYNC-IRQ-S1..S2.
Spec: hw/sys/smc/regs/blocks/reset_unit/reset_unit.rdl,
hw/sys/smc/regs/blocks/ndm_reset/ndm_reset.rdl, hw/sys/smc/doc/clk_rst.adoc,
hw/sys/smu/doc/port_table.adoc, doc/integrator/src/smu-smc.adoc.

Every CSR access goes over the SMC JTAG2AXI frontdoor. Read-only registers and
offsets with no register instance are written with the access status captured
and logged, not asserted.
"""

from __future__ import annotations

import os
import random

import cocotb
from cocotb.triggers import ClockCycles, RisingEdge
from ocah_jtag_vip import OcahJtagState

from seq_lib.smu_addr_map import reset_unit_u32, smc_addr
from seq_lib.smu_boundary_regs import ndm_reset_u32
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

RESET_UNIT_BASE = smc_addr("SMC_TOP_SMC_RESET_UNIT_BASE_ADDR")


def _ru(name: str) -> int:
    return smc_addr(f"SMC_TOP_SMC_RESET_UNIT_{name}_BASE_ADDR")


SS_CONFIG = _ru("SS_CONFIG")
SS_CONFIG_LOCK = _ru("SS_CONFIG_LOCK")
SS_WARM_RESET_N = _ru("SS_WARM_RESET_N")
SS_COLD_RESET_N = _ru("SS_COLD_RESET_N")
SS_CONFIG_HOLD = _ru("SS_CONFIG_HOLD")
SS_SRAM_HOLD = _ru("SS_SRAM_HOLD")
SS_CRITICAL_HOLD = _ru("SS_CRITICAL_HOLD")
SS_DEBUG_HOLD = _ru("SS_DEBUG_HOLD")
SS_COLD_RESET_LOCK = _ru("SS_COLD_RESET_LOCK")
SS_FORCE_TO_REF_CLK = _ru("SS_FORCE_TO_REF_CLK")
SS_RESET_COMPLETE = _ru("SS_RESET_COMPLETE")
SYNC_REG = _ru("SYNC_REG")
ISOLATE_REQ_REG = _ru("ISOLATE_REQ_REG")
ISOLATE_REQ_PINEN_REG = _ru("ISOLATE_REQ_PINEN_REG")
ISOLATE_REQ_SMC_REG = _ru("ISOLATE_REQ_SMC_REG")
ISOLATE_REQ_SMCEN_REG = _ru("ISOLATE_REQ_SMCEN_REG")
ISOLATE_REQ_VIS = _ru("ISOLATE_REQ_VIS")
FLR_COUNTER = _ru("ISOLATE_REQ_FLR_COUNTER_VALUE")
FLR_RESET_COUNTER = _ru("ISOLATE_REQ_FLR_RESET_COUNTER_VALUE")
NDMRESET_REQUEST = smc_addr("SMC_TOP_SMC_MISC_WRAP_NDM_RESET_NDMRESET_REQUEST_BASE_ADDR")
NDMRESET_PROCESS = smc_addr("SMC_TOP_SMC_MISC_WRAP_NDM_RESET_NDMRESET_PROCESS_BASE_ADDR")
NDMRESET_CLUSTER_COUNT = smc_addr(
    "SMC_TOP_SMC_MISC_WRAP_NDM_RESET_NDMRESET_CLUSTER_COUNT_BASE_ADDR"
)

SS_CONFIG_BM = reset_unit_u32("RESET_UNIT__SS_CONFIG__SS_CONFIG_bm")
SS_CONFIG_RESET = reset_unit_u32("RESET_UNIT__SS_CONFIG__SS_CONFIG_reset")
LOCK_BM = reset_unit_u32("RESET_UNIT__SS_CONFIG_LOCK__CONFIG_LOCK_bm")
LOCK_RESET = reset_unit_u32("RESET_UNIT__SS_CONFIG_LOCK__CONFIG_LOCK_reset")
WARM_BM = reset_unit_u32("RESET_UNIT__SS_WARM_RESET_N__RESET_N_N0_SCAN_bm")
WARM_RESET = reset_unit_u32("RESET_UNIT__SS_WARM_RESET_N__RESET_N_N0_SCAN_reset")
SYNC_BM = reset_unit_u32("RESET_UNIT__SYNC_REG__SYNC_bm")
SYNC_RESET = reset_unit_u32("RESET_UNIT__SYNC_REG__SYNC_reset")
VIS_PIN_BP = reset_unit_u32("RESET_UNIT__ISOLATE_REQ_VIS__ISOLATE_REQ_PIN_bp")
VIS_COOL_I_BP = reset_unit_u32("RESET_UNIT__ISOLATE_REQ_VIS__COOL_RESET_N_I_bp")
VIS_COOL_O_BP = reset_unit_u32("RESET_UNIT__ISOLATE_REQ_VIS__COOL_RESET_N_O_bp")
COUNTER_BM = reset_unit_u32(
    "RESET_UNIT__ISOLATE_REQ_FLR_COUNTER_VALUE__ISOLATE_REQ_FLR_COUNTER_VALUE_bm"
)
COUNTER_RESET = reset_unit_u32(
    "RESET_UNIT__ISOLATE_REQ_FLR_COUNTER_VALUE__ISOLATE_REQ_FLR_COUNTER_VALUE_reset"
)
PROCESS_BM = ndm_reset_u32("NDM_RESET__NDMRESET_PROCESS__NDMRESET_PROCESS_bm")
PROCESS_RESET = ndm_reset_u32("NDM_RESET__NDMRESET_PROCESS__NDMRESET_PROCESS_reset")

RESET_UNIT_REGS = {
    "SS_CONFIG": SS_CONFIG,
    "SS_CONFIG_LOCK": SS_CONFIG_LOCK,
    "SS_WARM_RESET_N": SS_WARM_RESET_N,
    "SS_COLD_RESET_N": SS_COLD_RESET_N,
    "SS_CONFIG_HOLD": SS_CONFIG_HOLD,
    "SS_SRAM_HOLD": SS_SRAM_HOLD,
    "SS_CRITICAL_HOLD": SS_CRITICAL_HOLD,
    "SS_DEBUG_HOLD": SS_DEBUG_HOLD,
    "SS_COLD_RESET_LOCK": SS_COLD_RESET_LOCK,
    "SS_FORCE_TO_REF_CLK": SS_FORCE_TO_REF_CLK,
    "SS_RESET_COMPLETE": SS_RESET_COMPLETE,
    "SYNC_REG": SYNC_REG,
    "ISOLATE_REQ_REG": ISOLATE_REQ_REG,
    "ISOLATE_REQ_PINEN_REG": ISOLATE_REQ_PINEN_REG,
    "ISOLATE_REQ_SMC_REG": ISOLATE_REQ_SMC_REG,
    "ISOLATE_REQ_SMCEN_REG": ISOLATE_REQ_SMCEN_REG,
    "ISOLATE_REQ_VIS": ISOLATE_REQ_VIS,
    "ISOLATE_REQ_FLR_COUNTER_VALUE": FLR_COUNTER,
    "ISOLATE_REQ_FLR_RESET_COUNTER_VALUE": FLR_RESET_COUNTER,
}

ISOLATION_RESET_REGS = {
    "ISOLATE_REQ_REG": (
        ISOLATE_REQ_REG,
        reset_unit_u32("RESET_UNIT__ISOLATE_REQ_REG__ISOLATE_REQ_REG_reset"),
    ),
    "ISOLATE_REQ_PINEN_REG": (
        ISOLATE_REQ_PINEN_REG,
        reset_unit_u32("RESET_UNIT__ISOLATE_REQ_PINEN_REG__ISOLATE_REQ_PINEN_REG_reset"),
    ),
    "ISOLATE_REQ_SMC_REG": (
        ISOLATE_REQ_SMC_REG,
        reset_unit_u32("RESET_UNIT__ISOLATE_REQ_SMC_REG__ISOLATE_REQ_SMC_REG_reset"),
    ),
    "ISOLATE_REQ_SMCEN_REG": (
        ISOLATE_REQ_SMCEN_REG,
        reset_unit_u32("RESET_UNIT__ISOLATE_REQ_SMCEN_REG__ISOLATE_REQ_SMCEN_REG_reset"),
    ),
    "ISOLATE_REQ_FLR_COUNTER_VALUE": (FLR_COUNTER, COUNTER_RESET),
    "ISOLATE_REQ_FLR_RESET_COUNTER_VALUE": (
        FLR_RESET_COUNTER,
        reset_unit_u32(
            "RESET_UNIT__ISOLATE_REQ_FLR_RESET_COUNTER_VALUE__"
            "ISOLATE_REQ_FLR_RESET_COUNTER_VALUE_reset"
        ),
    ),
}

# doc/integrator/src/smu-smc.adoc, External CPU cluster NDM reset: "This harness sets it to 4".
CLUSTER_COUNT = 4
UNMAPPED_OFFSETS = (0x28, 0x2C, 0x3C, 0xCC)
UNMAPPED_WRITE_DATA = 0xA5A5_A5A5
ALL_ONES = 0xFFFF_FFFF

ISOLATION_PIN_GPIO = 53
RESET_PULSE_REF_CYCLES = 64
RESET_ASSERT_BOUND_REF_CYCLES = 128
RESET_RELEASE_BOUND_REF_CYCLES = 8192
POLL_BOUND_SMU_CYCLES = 64
VIS_POLL_READS = 4
SYNC_CYCLES = 32

STEP_ORDER = ["S1", "S2", "S3", "S4", "S5", "S6", "S7", "S8", "S9", "PASS"]


class smu_reset_csr_access_test_seq:
    """Reset-unit and NDM CSR reset values, access rules and sync_irq_o."""

    def __init__(self, test) -> None:
        self.test = test
        self.dut = cocotb.top
        self.cfg = test.cfg
        self.log = test.logger
        self.sb = test.env.scoreboard
        self.steps: list[str] = []
        self.observed: dict[str, int] = {}
        self.accesses = 0
        seed = int(os.environ.get("RANDOM_SEED", "1"), 0)
        self.rng = random.Random(seed ^ 0x5EC5_A027)

    def _bit(self, name: str) -> int:
        pin = getattr(self.dut, name, None)
        if pin is None:
            raise AssertionError(f"{name} unobservable on this TB top")
        val = pin.value
        if not val.is_resolvable:
            raise AssertionError(f"X/Z on {name}: {val}")
        return int(val) & 1

    async def _rd32(self, addr: int, what: str) -> int:
        self.accesses += 1
        status, rdata = await jtag2axi_single_read(
            self.jtag,
            addr,
            size=SMC_DBG_AXSIZE_4B,
            require_complete=True,
        )
        require_jtag_tdo_resolved(f"{what} RD @0x{addr:08x}")
        if status != J2A_STATUS_SUCCESS:
            raise AssertionError(f"{what} read @0x{addr:08x} status={status}")
        value = axi64_unpack32(addr, rdata)
        if what in RESET_UNIT_REGS:
            self.observed[what] = value
        return value

    async def _wr32(self, addr: int, data: int, what: str) -> None:
        status = await self._wr32_status(addr, data, what)
        if status != J2A_STATUS_SUCCESS:
            raise AssertionError(f"{what} write @0x{addr:08x} status={status}")

    async def _wr32_status(self, addr: int, data: int, what: str) -> int:
        self.accesses += 1
        self.observed.pop(what, None)
        wstrb, beat = axi64_pack32(addr, data)
        status, _ = await jtag2axi_single_write(
            self.jtag,
            addr,
            beat,
            wstrb=wstrb,
            size=SMC_DBG_AXSIZE_4B,
            require_complete=False,
        )
        require_jtag_tdo_resolved(f"{what} WR @0x{addr:08x}")
        return status

    async def _rd32_status(self, addr: int, what: str) -> tuple[int, int]:
        self.accesses += 1
        status, rdata = await jtag2axi_single_read(
            self.jtag,
            addr,
            size=SMC_DBG_AXSIZE_4B,
            require_complete=False,
        )
        require_jtag_tdo_resolved(f"{what} RD @0x{addr:08x}")
        return status, axi64_unpack32(addr, rdata)

    async def _wait_level(self, name: str, level: int, bound: int, what: str) -> None:
        for _ in range(bound):
            if self._bit(name) == level:
                return
            await RisingEdge(self.dut.clk_ref_i)
        raise AssertionError(f"TIMEOUT {what}: {name} never read {level} within {bound} clk_ref")

    def _require_csr_path(self) -> None:
        if self._bit("tb_smc_jtag2axi_security_disable"):
            raise AssertionError("SMC JTAG2AXI gated; the reset CSRs cannot be accessed")

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

    async def _poll_sync_irq(self, level: int) -> int:
        """Sample tb_sync_irq each clk_smu cycle until it reads ``level``; return the last read."""
        sample = self._bit("tb_sync_irq")
        for _ in range(POLL_BOUND_SMU_CYCLES):
            sample = self._bit("tb_sync_irq")
            if sample == level:
                return sample
            await RisingEdge(self.dut.clk_smu_i)
        return sample

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

    async def run(self) -> None:
        sb = self.sb
        await self.cfg.reset_done.wait()
        await self._open_tap()
        self._drive_isolation_pin(0)
        pin_level = 0
        self.steps.append("S1")

        # S2: isolation registers and FLR counters at their reset values.
        for name, (addr, reset) in ISOLATION_RESET_REGS.items():
            sb.expect_eq(
                f"{name} reads its reset value 0x{reset:x} after the bring-up cold reset",
                await self._rd32(addr, name),
                reset,
                evidence="CSR_RESET_VALUES_S2",
            )
        self.steps.append("S2")

        # S3: NDM registers with the request inputs low.
        ndm_seen = {
            "NDMRESET_REQUEST": await self._rd32(NDMRESET_REQUEST, "NDMRESET_REQUEST"),
        }
        sb.expect_eq(
            "NDMRESET_REQUEST reads 0 with the request inputs low",
            ndm_seen["NDMRESET_REQUEST"],
            0,
            evidence="CSR_RESET_VALUES_S3",
        )
        sb.expect_eq(
            f"NDMRESET_PROCESS reads its reset value {PROCESS_RESET}",
            await self._rd32(NDMRESET_PROCESS, "NDMRESET_PROCESS"),
            PROCESS_RESET,
            evidence="CSR_RESET_VALUES_S3",
        )
        ndm_seen["NDMRESET_CLUSTER_COUNT"] = await self._rd32(
            NDMRESET_CLUSTER_COUNT, "NDMRESET_CLUSTER_COUNT"
        )
        sb.expect_eq(
            f"NDMRESET_CLUSTER_COUNT reads {CLUSTER_COUNT}",
            ndm_seen["NDMRESET_CLUSTER_COUNT"],
            CLUSTER_COUNT,
            evidence="CSR_RESET_VALUES_S3",
        )
        self.steps.append("S3")

        # S4: SYNC_REG and the visibility bits.
        sb.expect_eq(
            f"SYNC_REG reads its reset value {SYNC_RESET}",
            await self._rd32(SYNC_REG, "SYNC_REG"),
            SYNC_RESET,
            evidence="CSR_RESET_VALUES_S4",
        )
        for _ in range(VIS_POLL_READS):
            vis = await self._rd32(ISOLATE_REQ_VIS, "ISOLATE_REQ_VIS")
            if (vis >> VIS_PIN_BP) & 1 == pin_level:
                break
        sb.expect_eq(
            f"ISOLATE_REQ_VIS[{VIS_PIN_BP}] equals the synchronized GPIO {ISOLATION_PIN_GPIO} "
            f"level {pin_level}",
            (vis >> VIS_PIN_BP) & 1,
            pin_level,
            evidence="CSR_RESET_VALUES_S4",
        )
        sb.expect_eq(
            f"ISOLATE_REQ_VIS[{VIS_COOL_I_BP}] reads 1",
            (vis >> VIS_COOL_I_BP) & 1,
            1,
            evidence="CSR_RESET_VALUES_S4",
        )
        sb.expect_eq(
            f"ISOLATE_REQ_VIS[{VIS_COOL_O_BP}] reads 1",
            (vis >> VIS_COOL_O_BP) & 1,
            1,
            evidence="CSR_RESET_VALUES_S4",
        )
        self.steps.append("S4")

        # S5: random data written to read-write registers and read back, then restored.
        lock = await self._rd32(SS_CONFIG_LOCK, "SS_CONFIG_LOCK")
        sb.expect_eq(
            "SS_CONFIG_LOCK reads unlocked before the SS_CONFIG write",
            lock,
            LOCK_RESET,
            evidence="CSR_ACCESS_S1",
        )
        rw_regs = (
            ("SS_CONFIG", SS_CONFIG, SS_CONFIG_BM, SS_CONFIG_RESET),
            ("SS_WARM_RESET_N", SS_WARM_RESET_N, WARM_BM, WARM_RESET),
            ("NDMRESET_PROCESS", NDMRESET_PROCESS, PROCESS_BM, PROCESS_RESET),
            ("ISOLATE_REQ_FLR_COUNTER_VALUE", FLR_COUNTER, COUNTER_BM, COUNTER_RESET),
        )
        for name, addr, mask, reset in rw_regs:
            patterns = [self.rng.getrandbits(32)]
            if name == "SS_CONFIG":
                field_bits = [bit for bit in range(32) if (mask >> bit) & 1]
                patterns.append(1 << self.rng.choice(field_bits))
            for data in patterns:
                await self._wr32(addr, data, name)
                readback = await self._rd32(addr, name)
                self.observed.pop(name, None)
                sb.expect_eq(
                    f"{name} reads back 0x{data & mask:08x} after writing 0x{data:08x}",
                    readback,
                    data & mask,
                    evidence="CSR_ACCESS_S1",
                )
            await self._wr32(addr, reset, name)
        self.steps.append("S5")

        # S6: read-only registers ignore a write of all ones.
        before = await self._rd32(SS_RESET_COMPLETE, "SS_RESET_COMPLETE")
        inverse = ~before & ALL_ONES
        for data in (ALL_ONES, inverse):
            status = await self._wr32_status(SS_RESET_COMPLETE, data, "SS_RESET_COMPLETE")
            self.log.info(
                "OBSERVED resp write 0x%08x SS_RESET_COMPLETE @0x%08x status=%d",
                data,
                SS_RESET_COMPLETE,
                status,
            )
        sb.expect_eq(
            f"SS_RESET_COMPLETE reads 0x{before:08x} after writes of 0x{ALL_ONES:08x} "
            f"and 0x{inverse:08x}",
            await self._rd32(SS_RESET_COMPLETE, "SS_RESET_COMPLETE"),
            before,
            evidence="CSR_ACCESS_S2",
        )
        for name, addr, before in (
            ("ISOLATE_REQ_VIS", ISOLATE_REQ_VIS, vis),
            ("NDMRESET_REQUEST", NDMRESET_REQUEST, ndm_seen["NDMRESET_REQUEST"]),
            (
                "NDMRESET_CLUSTER_COUNT",
                NDMRESET_CLUSTER_COUNT,
                ndm_seen["NDMRESET_CLUSTER_COUNT"],
            ),
        ):
            status = await self._wr32_status(addr, ALL_ONES, name)
            self.log.info("OBSERVED resp write all-ones %s @0x%08x status=%d", name, addr, status)
            sb.expect_eq(
                f"{name} reads 0x{before:08x} after a write of 0x{ALL_ONES:08x}",
                await self._rd32(addr, name),
                before,
                evidence="CSR_ACCESS_S2",
            )
        self.steps.append("S6")

        # S7: offsets between defined registers; no register instance sits at them.
        defined = {addr - RESET_UNIT_BASE for addr in RESET_UNIT_REGS.values()}
        overlap = defined & set(UNMAPPED_OFFSETS)
        if overlap:
            raise AssertionError(f"offsets {sorted(overlap)} hold a defined register")
        for name, addr in RESET_UNIT_REGS.items():
            if name not in self.observed:
                await self._rd32(addr, name)
        before = dict(self.observed)
        for offset in UNMAPPED_OFFSETS:
            addr = RESET_UNIT_BASE + offset
            rstatus, rdata = await self._rd32_status(addr, f"offset 0x{offset:x}")
            self.log.info(
                "OBSERVED resp read offset 0x%x status=%d data=0x%08x", offset, rstatus, rdata
            )
            wstatus = await self._wr32_status(addr, UNMAPPED_WRITE_DATA, f"offset 0x{offset:x}")
            self.log.info("OBSERVED resp write offset 0x%x status=%d", offset, wstatus)
        after = {name: await self._rd32(addr, name) for name, addr in RESET_UNIT_REGS.items()}
        for name, value in before.items():
            sb.expect_eq(
                f"{name} keeps 0x{value:08x} across the unmapped-offset accesses",
                after[name],
                value,
                evidence="CSR_ACCESS_S3",
            )
        self.steps.append("S7")

        # S8: SYNC_REG.sync drives sync_irq_o.
        await self._wr32(SYNC_REG, SYNC_BM, "SYNC_REG")
        sb.expect_eq(
            "sync_irq_o reads 1 after SYNC_REG.sync is written 1",
            await self._poll_sync_irq(1),
            1,
            evidence="SYNC_IRQ_S1",
        )
        await self._wr32(SYNC_REG, 0, "SYNC_REG")
        sb.expect_eq(
            "sync_irq_o reads 0 after SYNC_REG.sync is written 0",
            await self._poll_sync_irq(0),
            0,
            evidence="SYNC_IRQ_S1",
        )
        self.steps.append("S8")

        # S9: primary reset clears SYNC_REG and sync_irq_o.
        await self._wr32(SYNC_REG, SYNC_BM, "SYNC_REG")
        sb.expect_eq(
            "sync_irq_o reads 1 before the primary reset",
            await self._poll_sync_irq(1),
            1,
            evidence="SYNC_IRQ_S2",
        )
        await self._cool_reset()
        sb.expect_eq(
            f"SYNC_REG reads its reset value {SYNC_RESET} after the primary reset",
            await self._rd32(SYNC_REG, "SYNC_REG"),
            SYNC_RESET,
            evidence="SYNC_IRQ_S2",
        )
        sb.expect_eq(
            "sync_irq_o reads 0 after the primary reset",
            await self._poll_sync_irq(0),
            0,
            evidence="SYNC_IRQ_S2",
        )
        self.steps.append("S9")

        self.log.info("JTAG2AXI accesses issued: %d", self.accesses)
        self.steps.append("PASS")
        if self.steps != STEP_ORDER:
            raise AssertionError(f"CHK-NONVAC order fail: {self.steps} != {STEP_ORDER}")
        self.log.info("CHK-NONVAC: PASS (ordered fence S1<S2<S3<S4<S5<S6<S7<S8<S9<PASS)")
