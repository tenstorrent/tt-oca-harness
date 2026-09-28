# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Sequence for smu_smc_wdt_boundary_timeout_test. SEP=0, no Force.

smu_smc_wdt_timeout_irq_test proves the CORE0 watchdog's pending bit, and
says so: it programs WDOGENALWAYS and WDOGZEROCMP but not WDOGRSTEN, and
``OCAH4CORECluster_WatchdogTimer.sv`` gates the reset-output register with
``rsten & elapsed``, so its watchdog can never drive the SMU boundary.

This leaf sets WDOGRSTEN as well and follows the timeout out to the two
wrapper outputs:

S1  With the watchdog disarmed, both ``smc_wdt_first_timeout_o`` and
    ``smc_wdt_second_timeout_o`` read low and ``WDOGIP0`` is clear -- a
    starting point the checks below can move away from.

S2  ``smc_wdt_first_timeout_o`` is ``|cpu_wdt_timeout_cluster_i``
    (``smc_base.sv:228``), so arming CORE0 with WDOGRSTEN has to raise it, and
    ``WDOGIP0`` has to be set at the same time.

S3  The second stage is a down-counter reloaded from ``CPU_CTRL.WDT_TIMEOUT``
    while the cluster timeout is low (``smc_cpu_ctrl_wrap.sv:147-178``), so
    with the first timeout held it has to expire and raise
    ``smc_wdt_second_timeout_o``. ``smc_reset_ctrl.sv:133-136`` makes that the
    warm-reset term, so the SMC warm reset has to drop with it -- which is
    what separates the output from a dangling pin.

S4  Both events are transient: the warm reset clears the cluster watchdog
    that held the first timeout, which reloads the second stage. The second
    timeout, the SMC warm reset and the SMC watchdog reset it drives
    (``rst_wdt_smc_clk_no``, ``smc.sv``) all return to their released levels.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import ClockCycles, RisingEdge
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
from seq_lib.smu_tb_pins import smu_scope

WDT_CTRL = smc_addr("SMC_TOP_SMC_CLUSTER_CORE0_WDT_CTRL_BASE_ADDR")
WDT_CMP = smc_addr("SMC_TOP_SMC_CLUSTER_CORE0_WDT_CMP_BASE_ADDR")
CPU_CTRL_WDT_TIMEOUT = smc_addr("SMC_TOP_SMC_CPU_CTRL_WDT_TIMEOUT_BASE_ADDR")

WDT_IP0_BM = wdt_bm("WDT__CTRL__WDOGIP0_bm")
WDT_ALWAYS_BM = wdt_bm("WDT__CTRL__WDOGENALWAYS_bm")
WDT_ZEROCMP_BM = wdt_bm("WDT__CTRL__WDOGZEROCMP_bm")
WDT_RSTEN_BM = wdt_bm("WDT__CTRL__WDOGRSTEN_bm")
WDT_CMP_BM = wdt_bm("WDT__CMP__WDOGCMP0_bm")
WDT_TIMEOUT_BM = cpu_ctrl_bm("CPU_CTRL__WDT_TIMEOUT__DATA_bm")

CMP_SMALL = 0x10
WDT_TIMEOUT_RESET = c_header_u32(_CPU_CTRL_H, "CPU_CTRL__WDT_TIMEOUT__DATA_reset")
# smu_smc_wdt_timeout_irq_test needs up to ~17k clk_smu to see the same
# watchdog reach its pending bit, so the bound here is well past that and the
# poll steps in blocks: both outputs are levels, not pulses.
POLL_STEP = 32
FIRST_TIMEOUT_BOUND = 65536
SECOND_TIMEOUT_BOUND = 32768
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

    async def _wait_pin(self, name: str, want: int, bound: int, what: str) -> int:
        for cycle in range(0, bound, POLL_STEP):
            if self._bit(name) == want:
                return cycle
            await ClockCycles(self.dut.clk_smu_i, POLL_STEP)
        raise AssertionError(
            f"TIMEOUT {what}: {name} stayed {1 - want} for {bound} clk_smu cycles; "
            f"{self._cpu_state()}"
        )

    async def run(self) -> None:
        dut = self.dut
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
            "smc_wdt_first_timeout_o low before the watchdog is armed",
            self._bit("tb_smc_wdt_first_timeout"),
            0,
            evidence="CHK-SMU-WDT-FIRST",
        )
        self.sb.expect_eq(
            "smc_wdt_second_timeout_o low before the watchdog is armed",
            self._bit("tb_smc_wdt_second_timeout"),
            0,
            evidence="CHK-SMU-WDT-SECOND",
        )

        # The second stage counts down from CPU_CTRL.WDT_TIMEOUT once the
        # cluster timeout stops reloading it, and the reset value is the count
        # this leaf waits out; it is read, not rewritten.
        timeout_rb = await self._rd32(CPU_CTRL_WDT_TIMEOUT, "CPU_CTRL WDT_TIMEOUT")
        self.sb.expect_eq(
            "the second-stage counter is at its reset count",
            timeout_rb & WDT_TIMEOUT_BM,
            WDT_TIMEOUT_RESET,
            evidence="CHK-SMU-WDT-SECOND",
        )

        # S2: arm CORE0 with the reset enable the pending-bit leaf omits.
        status = await wdt_unlock(self.jtag)
        if status != J2A_STATUS_SUCCESS:
            raise AssertionError(f"WDT unlock status={status}")
        await self._wr32(WDT_CMP, CMP_SMALL, "CORE0 WDT CMP")
        cmp_rb = await self._rd32(WDT_CMP, "CORE0 WDT CMP")
        self.sb.expect_eq(
            "the compare value holds",
            cmp_rb & WDT_CMP_BM,
            CMP_SMALL,
            evidence="CHK-SMU-WDT-FIRST",
        )
        status = await wdt_unlock(self.jtag)
        if status != J2A_STATUS_SUCCESS:
            raise AssertionError(f"WDT unlock status={status}")
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
        cycles = await self._wait_pin(
            "tb_smc_wdt_first_timeout", 1, FIRST_TIMEOUT_BOUND, "first watchdog timeout"
        )
        self.log.info("smc_wdt_first_timeout_o rose %d clk_smu after arming", cycles)
        self.sb.expect_eq(
            "arming CORE0 with WDOGRSTEN raises smc_wdt_first_timeout_o",
            self._bit("tb_smc_wdt_first_timeout"),
            1,
            evidence="CHK-SMU-WDT-FIRST",
        )
        ctrl = await self._rd32(WDT_CTRL, "CORE0 WDT CTRL")
        self.sb.expect_eq(
            "the same timeout shows as the watchdog's pending bit",
            ctrl & WDT_IP0_BM,
            WDT_IP0_BM,
            evidence="CHK-SMU-WDT-FIRST",
        )

        # S3: the held first timeout runs the second stage down. Both events
        # are transient by construction -- smc_reset_ctrl.sv makes the second
        # timeout a warm-reset term, and the warm reset clears the cluster
        # watchdog that was holding the first timeout, which reloads the
        # second-stage counter -- so they are recorded cycle by cycle rather
        # than sampled after the fact.
        warm = hier(smu_scope(dut), WARM_RESET_PATH)
        self.sb.expect_eq(
            "the SMC warm reset is released while only the first stage has fired",
            sample(warm, WARM_RESET_PATH),
            1,
            evidence="CHK-SMU-WDT-SECOND",
        )
        second_seen = 0
        warm_low_seen = 0
        second_cycle = None
        for cycle in range(SECOND_TIMEOUT_BOUND):
            await RisingEdge(dut.clk_smu_i)
            if self._bit("tb_smc_wdt_second_timeout"):
                if second_cycle is None:
                    second_cycle = cycle
                second_seen = 1
            if sample(warm, WARM_RESET_PATH) == 0:
                warm_low_seen = 1
            if second_seen and warm_low_seen:
                break
        if not second_seen:
            raise AssertionError(
                f"TIMEOUT second watchdog timeout: tb_smc_wdt_second_timeout never rose "
                f"in {SECOND_TIMEOUT_BOUND} clk_smu cycles; {self._cpu_state()}"
            )
        self.log.info(
            "smc_wdt_second_timeout_o rose %d clk_smu after the first timeout was confirmed",
            second_cycle,
        )
        self.sb.expect_eq(
            "the held first timeout runs the second stage out",
            second_seen,
            1,
            evidence="CHK-SMU-WDT-SECOND",
        )
        self.sb.expect_eq(
            "the second timeout drops the SMC warm reset",
            warm_low_seen,
            1,
            evidence="CHK-SMU-WDT-SECOND",
        )

        # S4: the warm reset clears what held the timeouts.
        wdt_reset = hier(smu_scope(dut), WDT_RESET_PATH)
        released = None
        for _ in range(SECOND_TIMEOUT_BOUND):
            await RisingEdge(dut.clk_smu_i)
            released = (
                self._bit("tb_smc_wdt_second_timeout"),
                sample(warm, WARM_RESET_PATH),
                sample(wdt_reset, WDT_RESET_PATH),
            )
            if released == (0, 1, 1):
                break
        self.log.info("CHK-SMU-WDT-RELEASE second/warm/wdt-reset=%s", released)
        self.sb.expect_eq(
            "CHK-SMU-WDT-RELEASE the second timeout drops and both SMC resets release",
            released,
            (0, 1, 1),
            evidence="CHK-SMU-WDT-RELEASE",
        )
