# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Sequence for smu_smc_wdt_boundary_timeout_test. No force.

smu_smc_wdt_timeout_irq_test proves the CORE0 watchdog's pending bit; it
programs WDOGENALWAYS and WDOGZEROCMP but not WDOGRSTEN, the bit that "enables
a sticky reset signal to outputted to top level" (``wdt.rdl``), so its
watchdog does not drive the SMU boundary.

This leaf sets WDOGRSTEN as well and follows the timeout out to the two
wrapper outputs:

S1  With the watchdog disarmed, both ``smc_ras_o.wdt_first_timeout`` and
    ``smc_ras_o.wdt_second_timeout`` read low and ``WDOGIP0`` is clear -- a
    starting point the checks below can move away from.

S2  ``smc_ras_o.wdt_first_timeout`` is the CPU cluster watchdog's first timeout
    (``hw/sys/smc/doc/port_table.adoc``), so arming CORE0 with WDOGRSTEN has
    to raise it, and ``WDOGIP0`` has to be set at the same time. The compare
    ``CMP.wdogcmp0`` is drawn from the seed over the whole 16-bit field
    (1 to 0xFFFF; ``wdt.rdl``), written after the KEY unlock and read back
    masked to the field. ``hw/sys/smc/doc/watchdog.adoc`` ("Hardware sets it
    on every cycle the scaled count is at or above ``CMP``") with ``wdogscale``
    at its reset 0 puts the first timeout ``cmp`` ``clk_smu`` cycles after the
    arming write lands in the watchdog, so the pin is polled every ``clk_smu``
    from the AW handshake of the arming write on the DTP's SMC debug port (the
    bench counter ``dtp_smc_dbg_aw_count_o``) and the cycles to its rise have
    to lie in [cmp, cmp + FIRST_TIMEOUT_SLACK], 16 ``clk_smu``, which covers
    the write's path from the DTP to the watchdog register and the watchdog's
    pending-bit and sticky-reset registers.

S3  The second stage times out at the cycle count in ``CPU_CTRL.WDT_TIMEOUT``
    (``cpu_ctrl.rdl``: "Cycle count value that 2nd stage watchdog timer
    timeout should occur at"), so with the first timeout held
    ``smc_ras_o.wdt_second_timeout`` has to rise. A watchdog timeout is a warm
    reset source (``hw/sys/smc/doc/clk_rst.adoc``, "Watchdog Timeout":
    "Internal or external watchdog expiration"; ``hw/sys/smc/doc/cpu.adoc``:
    "a Warm Reset from a watchdog timeout"), so the SMC warm reset has to
    drop. Which stage asserts it is not stated, so the cycles of the second
    timeout and of the warm-reset drop are recorded.

S4  The warm reset covers the per-core watchdog timers (``clk_rst.adoc``,
    "Warm Reset"), so the first timeout they drive has to fall. The levels
    the second timeout, the SMC warm reset and the SMC watchdog reset
    (``rst_wdt_smc_clk_no``) settle at, and whether the watchdog reset
    asserted, are recorded: no specification states them.
"""

from __future__ import annotations

import random

import cocotb
from cocotb.triggers import RisingEdge
from ocah_jtag_vip import OcahJtagState

from seq_lib.smu_addr_map import _CPU_CTRL_H, c_header_u32, cpu_ctrl_bm, smc_addr, wdt_bm
from seq_lib.smu_compose_helpers import hier, sample
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
    wdt_unlock,
)
from seq_lib.smu_tb_pins import smu_scope, tb_pin

WDT_CTRL = smc_addr("SMC_TOP_SMC_CLUSTER_CORE0_WDT_CTRL_BASE_ADDR")
WDT_CMP = smc_addr("SMC_TOP_SMC_CLUSTER_CORE0_WDT_CMP_BASE_ADDR")
CPU_CTRL_WDT_TIMEOUT = smc_addr("SMC_TOP_SMC_CPU_CTRL_WDT_TIMEOUT_BASE_ADDR")

WDT_IP0_BM = wdt_bm("WDT__CTRL__WDOGIP0_bm")
WDT_ALWAYS_BM = wdt_bm("WDT__CTRL__WDOGENALWAYS_bm")
WDT_ZEROCMP_BM = wdt_bm("WDT__CTRL__WDOGZEROCMP_bm")
WDT_RSTEN_BM = wdt_bm("WDT__CTRL__WDOGRSTEN_bm")
WDT_CMP_BM = wdt_bm("WDT__CMP__WDOGCMP0_bm")
WDT_TIMEOUT_BM = cpu_ctrl_bm("CPU_CTRL__WDT_TIMEOUT__DATA_bm")

# Second-stage count at a 5 ns sys clock, the register's reset value; scaled to
# the period in use so the window between the two timeouts keeps its length
# and the JTAG read of the pending bit lands inside it.
WDT_TIMEOUT_5NS_CYCLES = 16384
WDT_TIMEOUT_RESET = c_header_u32(_CPU_CTRL_H, "CPU_CTRL__WDT_TIMEOUT__DATA_reset")
# Bound on the first timeout, in time; the poll converts it to clk_smu cycles.
# It covers the JTAG round trip of the arming write and the largest compare.
FIRST_TIMEOUT_BOUND_NS = 650_000
# The first timeout is expected cmp to cmp + FIRST_TIMEOUT_SLACK clk_smu after
# the AW handshake of the arming write on the DTP's SMC debug port: the write
# crosses the SMU and SMC fabrics into the cluster, the count starts on the
# cycle the register takes it, and the pending bit and the sticky reset are
# one register each.
FIRST_TIMEOUT_SLACK = 16
AW_COUNT_PIN = "dtp_smc_dbg_aw_count_o"
# Bound on the second timeout, in time; the wait converts it to clk_smu cycles.
SECOND_TIMEOUT_BOUND_NS = 330_000
WARM_RESET_PATH = "u_smc.rst_warm_smc_clk_n"
WDT_RESET_PATH = "u_smc.rst_wdt_smc_clk_no"
CPU_PATH = "u_smc.u_smc_cpu_wrapper.u_smc_cpu"


class smu_smc_wdt_boundary_timeout_seq:
    """The CORE0 watchdog followed out to the two SMU watchdog outputs."""

    def __init__(self, test) -> None:
        self.test = test
        self.dut = cocotb.top
        self.cfg = test.cfg
        self.log = test.logger
        self.sb = test.env.scoreboard
        self.seed = test.random_seed()
        self.rng = random.Random(self.seed)
        # The whole field; a compare of 0 raises the timeout on the arming
        # write, a leg the checkers do not have.
        self.cmp = self.rng.randint(1, WDT_CMP_BM)

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
            self.jtag, addr, size=SMC_DBG_AXSIZE_4B, require_complete=True
        )
        require_jtag_tdo_resolved(f"{what} RD @0x{addr:08x}")
        if status != J2A_STATUS_SUCCESS:
            raise AssertionError(f"{what} read @0x{addr:08x} status={status}")
        return axi64_unpack32(addr, rdata)

    async def _wr32(self, addr: int, data: int, what: str) -> None:
        wstrb, beat = axi64_pack32(addr, data)
        status, _ = await jtag2axi_single_write(
            self.jtag, addr, beat, wstrb=wstrb, size=SMC_DBG_AXSIZE_4B, require_complete=True
        )
        require_jtag_tdo_resolved(f"{what} WR @0x{addr:08x}")
        if status != J2A_STATUS_SUCCESS:
            raise AssertionError(f"{what} write @0x{addr:08x} status={status}")

    def _cpu_state(self) -> str:
        """The cluster gating terms the watchdog outputs pass through."""
        smu = smu_scope(self.dut)
        out = []
        for leaf in (
            "cluster_boundary_isolate",
            "cluster_boundary_ready",
            "init_mem_complete",
            "wdt_reset_raw",
            "wdt_reset_o",
        ):
            try:
                out.append(f"{leaf}={sample(hier(smu, f'{CPU_PATH}.{leaf}'), leaf)}")
            except Exception as exc:  # noqa: BLE001 - diagnostic only
                out.append(f"{leaf}=<{exc}>")
        return " ".join(out)

    async def _time_first_timeout(self, bound: int) -> tuple[int | None, int | None]:
        """Poll every clk_smu: the cycle of the next AW handshake on the DTP's SMC
        debug port (the arming write) and the cycle smc_ras_o.wdt_first_timeout rises."""
        aw_count = tb_pin(self.dut, AW_COUNT_PIN)
        aw_before = sample(aw_count, AW_COUNT_PIN)
        armed_at = None
        for cycle in range(bound):
            await RisingEdge(self.dut.clk_smu_i)
            if armed_at is None and sample(aw_count, AW_COUNT_PIN) != aw_before:
                armed_at = cycle
            if armed_at is not None and self._bit("tb_smc_wdt_first_timeout"):
                return armed_at, cycle
        return armed_at, None

    async def run(self) -> None:
        dut = self.dut
        drawn = f"drawn wdogcmp0=0x{self.cmp:04x}"
        self.log.info("SEED: RANDOM_SEED=%d %s", self.seed, drawn)
        await self.cfg.reset_done.wait()
        self.jtag = make_smu_jtag_tap(dut, self.cfg.jtag_period_ns)
        await self.jtag.reset_tap()
        await self.jtag.goto_state(OcahJtagState.RUN_TEST_IDLE)
        for _ in range(8):
            await self.jtag.step_tms(0)
        idcode = await self.jtag.read_idcode()
        if idcode != DTP_DEFAULT_IDCODE:
            raise AssertionError(f"IDCODE want 0x{DTP_DEFAULT_IDCODE:x} got 0x{idcode:08x}")
        if self._bit("tb_smc_jtag2axi_security_disable"):
            raise AssertionError("SMC JTAG2AXI still gated; no CSR leg can run")

        # S1: disarmed starting point.
        ctrl = await self._rd32(WDT_CTRL, "CORE0 WDT CTRL")
        self.sb.expect_eq(
            "the CORE0 watchdog is not pending before it is armed",
            ctrl & WDT_IP0_BM,
            0,
            evidence="CHK-SMU-WDT-FIRST",
        )
        self.sb.expect_eq(
            "smc_ras_o.wdt_first_timeout low before the watchdog is armed",
            self._bit("tb_smc_wdt_first_timeout"),
            0,
            evidence="CHK-SMU-WDT-FIRST",
        )
        self.sb.expect_eq(
            "smc_ras_o.wdt_second_timeout low before the watchdog is armed",
            self._bit("tb_smc_wdt_second_timeout"),
            0,
            evidence="CHK-SMU-WDT-SECOND",
        )

        # The second stage counts down from CPU_CTRL.WDT_TIMEOUT once the
        # cluster timeout stops reloading it. Its reset value is checked, then
        # the count this leaf waits out is written scaled to the sys period.
        timeout_rb = await self._rd32(CPU_CTRL_WDT_TIMEOUT, "CPU_CTRL WDT_TIMEOUT")
        self.sb.expect_eq(
            "the second-stage counter is at its reset count",
            timeout_rb & WDT_TIMEOUT_BM,
            WDT_TIMEOUT_RESET,
            evidence="CHK-SMU-WDT-SECOND",
        )
        second_stage = int(WDT_TIMEOUT_5NS_CYCLES * 5 / self.cfg.smu_clk_period_ns)
        await self._wr32(CPU_CTRL_WDT_TIMEOUT, second_stage, "CPU_CTRL WDT_TIMEOUT")

        # S2: arm CORE0 with the reset enable the pending-bit leaf omits.
        status = await wdt_unlock(self.jtag)
        if status != J2A_STATUS_SUCCESS:
            raise AssertionError(f"WDT unlock status={status}")
        await self._wr32(WDT_CMP, self.cmp, "CORE0 WDT CMP")
        cmp_rb = await self._rd32(WDT_CMP, "CORE0 WDT CMP")
        self.sb.expect_eq(
            f"the compare value holds {drawn}",
            cmp_rb & WDT_CMP_BM,
            self.cmp,
            evidence="CHK-SMU-WDT-FIRST",
        )
        status = await wdt_unlock(self.jtag)
        if status != J2A_STATUS_SUCCESS:
            raise AssertionError(f"WDT unlock status={status}")
        first_bound = int(FIRST_TIMEOUT_BOUND_NS / self.cfg.smu_clk_period_ns)
        timer = cocotb.start_soon(self._time_first_timeout(first_bound))
        await self._wr32(WDT_CTRL, WDT_ALWAYS_BM | WDT_ZEROCMP_BM | WDT_RSTEN_BM, "CORE0 WDT CTRL")
        armed = await self._rd32(WDT_CTRL, "CORE0 WDT CTRL")
        self.log.info(
            "CORE0 WDT CTRL after arming = 0x%08x (rsten=%d always=%d zerocmp=%d)",
            armed,
            bool(armed & WDT_RSTEN_BM),
            bool(armed & WDT_ALWAYS_BM),
            bool(armed & WDT_ZEROCMP_BM),
        )
        self.sb.expect_eq(
            "CORE0 WDT CTRL holds the arming word, WDOGRSTEN included",
            armed & (WDT_ALWAYS_BM | WDT_ZEROCMP_BM | WDT_RSTEN_BM),
            WDT_ALWAYS_BM | WDT_ZEROCMP_BM | WDT_RSTEN_BM,
            evidence="CHK-SMU-WDT-FIRST",
        )
        armed_at, rose_at = await timer
        if armed_at is None:
            raise AssertionError(
                f"TIMEOUT first watchdog timeout: no AW handshake on {AW_COUNT_PIN} within "
                f"{first_bound} clk_smu cycles of the arming write"
            )
        if rose_at is None:
            raise AssertionError(
                f"TIMEOUT first watchdog timeout: tb_smc_wdt_first_timeout stayed 0 for "
                f"{first_bound} clk_smu cycles; {self._cpu_state()}"
            )
        cycles = rose_at - armed_at
        self.log.info(
            "OBSERVATION smc_ras_o.wdt_first_timeout rose %d clk_smu after the AW handshake of the "
            "arming write (cmp + %d) %s",
            cycles,
            cycles - self.cmp,
            drawn,
        )
        self.sb.expect_eq(
            f"the first timeout lands cmp to cmp + {FIRST_TIMEOUT_SLACK} clk_smu after the "
            f"arming write's AW handshake ({cycles} clk_smu) {drawn}",
            self.cmp <= cycles <= self.cmp + FIRST_TIMEOUT_SLACK,
            True,
            evidence="CHK-SMU-WDT-FIRST",
        )
        self.sb.expect_eq(
            f"arming CORE0 with WDOGRSTEN raises smc_ras_o.wdt_first_timeout {drawn}",
            self._bit("tb_smc_wdt_first_timeout"),
            1,
            evidence="CHK-SMU-WDT-FIRST",
        )
        ctrl = await self._rd32(WDT_CTRL, "CORE0 WDT CTRL")
        self.sb.expect_eq(
            f"the same timeout shows as the watchdog's pending bit {drawn}",
            ctrl & WDT_IP0_BM,
            WDT_IP0_BM,
            evidence="CHK-SMU-WDT-FIRST",
        )

        # S3: the held first timeout runs the second stage down. Both events
        # are transient, so they are recorded cycle by cycle.
        warm = hier(smu_scope(dut), WARM_RESET_PATH)
        self.sb.expect_eq(
            "the SMC warm reset is released while only the first stage has fired",
            sample(warm, WARM_RESET_PATH),
            1,
            evidence="CHK-SMU-WDT-SECOND",
        )
        second_cycle = None
        second_bound = int(SECOND_TIMEOUT_BOUND_NS / self.cfg.smu_clk_period_ns)
        warm_cycle = None
        for cycle in range(second_bound):
            await RisingEdge(dut.clk_smu_i)
            if second_cycle is None and self._bit("tb_smc_wdt_second_timeout"):
                second_cycle = cycle
            if warm_cycle is None and sample(warm, WARM_RESET_PATH) == 0:
                warm_cycle = cycle
            if second_cycle is not None and warm_cycle is not None:
                break
        if second_cycle is None:
            raise AssertionError(
                f"TIMEOUT second watchdog timeout: tb_smc_wdt_second_timeout never rose "
                f"in {second_bound} clk_smu cycles; {self._cpu_state()}"
            )
        self.log.info(
            "OBSERVATION smc_ras_o.wdt_second_timeout rose %s and the SMC warm reset fell %s "
            "clk_smu after the first timeout was confirmed",
            second_cycle,
            warm_cycle,
        )
        self.sb.expect_eq(
            f"the held first timeout runs the second stage out {drawn}",
            second_cycle is not None,
            True,
            evidence="CHK-SMU-WDT-SECOND",
        )
        self.sb.expect_eq(
            f"the watchdog timeout drops the SMC warm reset {drawn}",
            warm_cycle is not None,
            True,
            evidence="CHK-SMU-WDT-SECOND",
        )

        # S4: the warm reset clears the per-core watchdog holding the first timeout.
        wdt_reset = hier(smu_scope(dut), WDT_RESET_PATH)
        first_dropped = False
        wdt_reset_low = False
        released = None
        for _ in range(second_bound):
            await RisingEdge(dut.clk_smu_i)
            first_dropped |= self._bit("tb_smc_wdt_first_timeout") == 0
            wdt_reset_low |= sample(wdt_reset, WDT_RESET_PATH) == 0
            released = (
                self._bit("tb_smc_wdt_second_timeout"),
                sample(warm, WARM_RESET_PATH),
                sample(wdt_reset, WDT_RESET_PATH),
            )
            if first_dropped and released == (0, 1, 1):
                break
        self.log.info(
            "OBSERVATION second/warm/wdt-reset settle at %s; the watchdog reset asserted: %s",
            released,
            wdt_reset_low,
        )
        self.sb.expect_eq(
            f"CHK-SMU-WDT-RELEASE the warm reset clears the first timeout {drawn}",
            first_dropped,
            True,
            evidence="CHK-SMU-WDT-RELEASE",
        )
