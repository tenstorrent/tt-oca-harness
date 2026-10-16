# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""CORE0 watchdog warm reset: which SMC registers keep their value and which return to reset.

``hw/sys/smc/doc/clk_rst.adoc`` ("Reset equations", "Reset Unit") gives the warm reset as
``rst_primary_n AND rst_wdt_n AND fuse_reset_ni`` with the watchdog term ``rst_ext_wdt_ni AND
NOT smc_wdt_second_timeout_i``; the primary reset carries no watchdog term. ``SS_CONFIG`` and
``SS_COLD_RESET_N`` are reset by the primary reset and the isolation registers and FLR counters
by the stable cold reset, so a watchdog warm reset leaves all four. The CORE0 watchdog timer is
covered by the warm reset ("Warm Reset"), so its ``CMP`` and ``CTRL`` return to the reset values
of ``hw/sys/smc/regs/blocks/wdt/wdt.rdl``. ``SS_WARM_RESET_N``, a CPU_CTRL ``SCRATCH`` word and a
``SCRATCH_COLD_WARM`` word sit in no domain a chapter names, so they are measured and logged only.

Every register access is a JTAG2AXI access on the SMC fabric; nothing is forced. A free-running
monitor samples the watchdog second timeout, the warm reset probe and the primary and stable cold
reset outputs on every ``clk_smu_i`` edge.
"""

from __future__ import annotations

from collections import Counter
from typing import NamedTuple

import cocotb
from cocotb.triggers import ClockCycles, RisingEdge
from cocotb.utils import get_sim_time
from ocah_jtag_vip import OcahJtagState

from seq_lib.smu_addr_map import reset_unit_u32, smc_addr, smc_indexed_addr, wdt_u32
from seq_lib.smu_compose_helpers import hier
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
from seq_lib.smu_tb_pins import cold_stable_reset, smc_primary_reset, smu_scope

SS_CONFIG = smc_addr("SMC_TOP_SMC_RESET_UNIT_SS_CONFIG_BASE_ADDR")
SS_COLD_RESET_N = smc_addr("SMC_TOP_SMC_RESET_UNIT_SS_COLD_RESET_N_BASE_ADDR")
SS_WARM_RESET_N = smc_addr("SMC_TOP_SMC_RESET_UNIT_SS_WARM_RESET_N_BASE_ADDR")
ISOLATE_REQ_REG = smc_addr("SMC_TOP_SMC_RESET_UNIT_ISOLATE_REQ_REG_BASE_ADDR")
FLR_COUNTER = smc_addr("SMC_TOP_SMC_RESET_UNIT_ISOLATE_REQ_FLR_COUNTER_VALUE_BASE_ADDR")
WDT_CTRL = smc_addr("SMC_TOP_SMC_CLUSTER_CORE0_WDT_CTRL_BASE_ADDR")
WDT_CMP = smc_addr("SMC_TOP_SMC_CLUSTER_CORE0_WDT_CMP_BASE_ADDR")
CPU_CTRL_SCRATCH = smc_indexed_addr("SMC_TOP_SMC_CPU_CTRL_SCRATCH_BASE_ADDR", 0)
COLD_WARM_SCRATCH = smc_indexed_addr("SMC_TOP_SMC_MISC_WRAP_SCRATCH_COLD_WARM_SCRATCH_BASE_ADDR", 0)

# reset_unit.rdl and the generated reset_unit.h: reset value of each retained register.
SS_CONFIG_RESET = reset_unit_u32("RESET_UNIT__SS_CONFIG__SS_CONFIG_reset")
SS_COLD_RESET = reset_unit_u32("RESET_UNIT__SS_COLD_RESET_N__RESET_N_N0_SCAN_reset")
ISOLATE_REG_RESET = reset_unit_u32("RESET_UNIT__ISOLATE_REQ_REG__ISOLATE_REQ_REG_reset")
FLR_COUNTER_RESET = reset_unit_u32(
    "RESET_UNIT__ISOLATE_REQ_FLR_COUNTER_VALUE__ISOLATE_REQ_FLR_COUNTER_VALUE_reset"
)
SS_WARM_RESET = reset_unit_u32("RESET_UNIT__SS_WARM_RESET_N__RESET_N_N0_SCAN_reset")

# Non-zero patterns, each different from its reset value; the isolation pair holds the values
# the isolation register and FLR counter are written with elsewhere in this bench.
SS_CONFIG_PATTERN = 0x5A5A_5A5A
SS_COLD_PATTERN = 0xA5A5_A5A5
ISOLATE_REG_PATTERN = 0xA5A5_A5A5
FLR_COUNTER_PATTERN = 5
# Measured-only registers: SS_WARM_RESET_N differs from 0xFFFFFFFF, the scratch words from 0.
SS_WARM_PATTERN = 0x7FFF_FFFF
CPU_SCRATCH_PATTERN = 0x1357_9BDF
COLD_WARM_SCRATCH_PATTERN = 0x2468_ACE0

# wdt.rdl / generated wdt.h: CORE0 CMP reset 0x1000 and the CTRL field reset values.
WDT_CMP_BM = wdt_u32("WDT__CMP__WDOGCMP0_bm")
WDT_CMP_RESET = wdt_u32("WDT__CMP__WDOGCMP0_reset")
WDT_RSTEN_BM = wdt_u32("WDT__CTRL__WDOGRSTEN_bm")
WDT_ALWAYS_BM = wdt_u32("WDT__CTRL__WDOGENALWAYS_bm")
WDT_ZEROCMP_BM = wdt_u32("WDT__CTRL__WDOGZEROCMP_bm")
WDT_ARM_BITS = WDT_RSTEN_BM | WDT_ALWAYS_BM | WDT_ZEROCMP_BM
WDT_CTRL_FIELDS = (
    "WDOGSCALE",
    "RSVD0",
    "WDOGRSTEN",
    "WDOGZEROCMP",
    "RSVD1",
    "WDOGENALWAYS",
    "WDOGCOREAWAKE",
    "RSVD2",
    "WDOGIP0",
    "RSVD3",
)
WDT_CTRL_RESET = sum(
    wdt_u32(f"WDT__CTRL__{f}_reset") << wdt_u32(f"WDT__CTRL__{f}_bp") for f in WDT_CTRL_FIELDS
)
# A compare value different from the 0x1000 reset value, small enough for the first stage to
# expire soon after arming.
WDT_CMP_ARMED = 0x10

# clk_rst.adoc reset equations: every reset net is active low, so 1 is released and 0 asserted.
NET_RELEASED = 1
NET_ASSERTED = 0
# wdt.rdl WDOGRSTEN: the second timeout is a sticky level that reads 0 until it expires.
SECOND_TIMEOUT_IDLE = 0
SECOND_TIMEOUT_RAISED = 1

WARM_RESET_PATH = "u_smc.rst_warm_smc_clk_n"

# Bounds of the waits, in time for the watchdog stages and in clk_smu_i cycles for the rest.
EVENT_RISE_BOUND_NS = 980_000
EVENT_FALL_BOUND = 4096
RELEASE_BOUND = 20000
STEP_CLOCK_GAP = 2

# Wait sites per kind: the second timeout rise and warm reset fall, and the two releases.
EXPECTED_SITE_KINDS = {"event": 2, "release": 2}
EXPECTED_SITES = 4

STEPS = ("S1", "S2", "S3", "S4", "S5", "S7", "S8", "S9", "S10", "S11")


class Sample(NamedTuple):
    """One clk_smu_i sample; -1 marks an unresolved level."""

    t_ps: int
    second: int
    warm: int
    primary: int
    cold: int


def _level(signal) -> int:
    val = signal.value
    if hasattr(val, "is_resolvable") and not val.is_resolvable:
        return -1
    return int(val)


class smu_smc_warm_reset_register_retention_test_seq:
    """Retained and returned SMC registers across the CORE0 watchdog warm reset."""

    def __init__(self, test) -> None:
        self.test = test
        self.dut = cocotb.top
        self.cfg = test.cfg
        self.log = test.logger
        self.sb = test.env.scoreboard
        self.clk = self.dut.clk_smu_i
        self.smu = smu_scope(self.dut)
        self.warm = hier(self.smu, WARM_RESET_PATH)
        self.primary = smc_primary_reset(self.dut)
        self.cold = cold_stable_reset(self.dut)
        self.period_ps = round(self.cfg.smu_clk_period_ns * 1000)
        self.trace: list[Sample] = []
        self.sites: list[dict] = []
        self.stamp_ps: dict[str, int] = {}
        self.done = False

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

    async def _unlock(self) -> None:
        status = await wdt_unlock(self.jtag)
        if status != J2A_STATUS_SUCCESS:
            raise AssertionError(f"WDT unlock status={status}")

    def _record(self) -> Sample:
        now = int(get_sim_time(unit="ps"))
        if self.trace and self.trace[-1].t_ps == now:
            return self.trace[-1]
        entry = Sample(
            now,
            _level(self.dut.tb_smc_wdt_second_timeout),
            _level(self.warm),
            _level(self.primary),
            _level(self.cold),
        )
        self.trace.append(entry)
        return entry

    async def _tick(self) -> Sample:
        await RisingEdge(self.clk)
        return self._record()

    async def _monitor(self) -> None:
        while True:
            await RisingEdge(self.clk)
            self._record()

    async def _mark(self, step: str, text: str) -> None:
        await RisingEdge(self.clk)
        self._record()
        self.stamp_ps[step] = int(get_sim_time(unit="ps"))
        self.log.info("STEP %s @%.3fns: %s", step, self.stamp_ps[step] / 1000, text)

    @staticmethod
    def _state(s: Sample) -> str:
        return f"second={s.second} rst_warm={s.warm} primary={s.primary} cold={s.cold}"

    def _first(self, pred, start: int) -> int:
        for idx in range(start, len(self.trace)):
            if pred(self.trace[idx]):
                return idx
        return -1

    async def _wait(self, kind: str, label: str, pred, bound: int) -> tuple[bool, int]:
        """Tick until ``pred`` holds; the site is recorded with its bound and last state."""
        used = 0
        s = await self._tick()
        met = pred()
        while not met and used < bound:
            s = await self._tick()
            used += 1
            met = pred()
        self.sites.append(
            {
                "kind": kind,
                "label": label,
                "bound": bound,
                "used": used,
                "last": self._state(s),
                "expired": int(not met),
            }
        )
        return met, used

    async def _event_wait(self, label: str, pred, bound: int) -> int:
        met, used = await self._wait("event", label, pred, bound)
        if not met:
            rec = self.sites[-1]
            raise AssertionError(
                f"TIMEOUT {label}: bound={rec['bound']} used={used} last_state={rec['last']}"
            )
        return used

    async def _write_readback(self, addr: int, value: int, what: str) -> int:
        await self._wr32(addr, value, what)
        return await self._rd32(addr, what)

    async def run(self) -> None:
        sb = self.sb
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
        monitor = cocotb.start_soon(self._monitor())
        await self._mark("S1", "TAP reset, IDCODE read, JTAG2AXI open, sampling started")

        retained = (
            ("SS_CONFIG", SS_CONFIG, SS_CONFIG_PATTERN, SS_CONFIG_RESET),
            ("SS_COLD_RESET_N", SS_COLD_RESET_N, SS_COLD_PATTERN, SS_COLD_RESET),
            ("ISOLATE_REQ_REG", ISOLATE_REQ_REG, ISOLATE_REG_PATTERN, ISOLATE_REG_RESET),
            ("ISOLATE_REQ_FLR_COUNTER_VALUE", FLR_COUNTER, FLR_COUNTER_PATTERN, FLR_COUNTER_RESET),
        )
        before = {}
        for name, addr, pattern, _reset in retained:
            before[name] = await self._write_readback(addr, pattern, name)
        await self._mark("S2", "retained patterns written and read back")

        measured = (
            ("SS_WARM_RESET_N", SS_WARM_RESET_N, SS_WARM_PATTERN),
            ("CPU_CTRL SCRATCH[0]", CPU_CTRL_SCRATCH, CPU_SCRATCH_PATTERN),
            ("SCRATCH_COLD_WARM SCRATCH[0]", COLD_WARM_SCRATCH, COLD_WARM_SCRATCH_PATTERN),
        )
        measured_before = {}
        for name, addr, pattern in measured:
            measured_before[name] = await self._write_readback(addr, pattern, name)
            self.log.info(
                "OBSERVATION %s before the warm reset measured=0x%08x (written 0x%08x)",
                name,
                measured_before[name],
                pattern,
            )
        await self._mark("S3", "measured-only registers written and read back")

        await self._unlock()
        cmp_before = await self._write_readback(WDT_CMP, WDT_CMP_ARMED, "CORE0 WDT CMP")
        await self._unlock()
        await self._wr32(WDT_CTRL, WDT_ARM_BITS, "CORE0 WDT CTRL")
        ctrl_before = await self._rd32(WDT_CTRL, "CORE0 WDT CTRL")
        await self._mark("S4", "CORE0 armed with WDOGRSTEN, WDOGENALWAYS and WDOGZEROCMP")

        arm_idx = len(self.trace)
        at_arm = self.trace[-1]
        rise_used = await self._event_wait(
            "second timeout rise",
            lambda: self._first(lambda s: s.second == SECOND_TIMEOUT_RAISED, arm_idx) >= 0,
            int(EVENT_RISE_BOUND_NS / self.cfg.smu_clk_period_ns),
        )
        fall_used = await self._event_wait(
            "warm reset fall",
            lambda: self._first(lambda s: s.warm == NET_ASSERTED, arm_idx) >= 0,
            EVENT_FALL_BOUND,
        )
        i_rise = self._first(lambda s: s.second == SECOND_TIMEOUT_RAISED, arm_idx)
        i_fall = self._first(lambda s: s.warm == NET_ASSERTED, arm_idx)
        self.log.info(
            "OBSERVATION second timeout rose %d samples and warm reset fell %d samples after "
            "the arming access; wait cycles used %d and %d",
            i_rise - arm_idx,
            i_fall - arm_idx,
            rise_used,
            fall_used,
        )
        await self._mark("S5", "second timeout raised and warm reset fell")

        released, release_used = await self._wait(
            "release",
            "warm reset return",
            lambda: self._first(lambda s: s.warm == NET_RELEASED, i_fall) >= 0,
            RELEASE_BOUND,
        )
        cleared, clear_used = await self._wait(
            "release",
            "second timeout return",
            lambda: self._first(lambda s: s.second == SECOND_TIMEOUT_IDLE, i_rise) >= 0,
            RELEASE_BOUND,
        )
        await self._mark("S7", "release waits finished")

        after = {}
        for name, addr, _pattern, _reset in retained:
            after[name] = await self._rd32(addr, name)
        await self._mark("S8", "retained registers read after the event")

        cmp_after = await self._rd32(WDT_CMP, "CORE0 WDT CMP")
        ctrl_after = await self._rd32(WDT_CTRL, "CORE0 WDT CTRL")
        await self._mark("S9", "CORE0 CMP and CTRL read after the event")

        measured_after = {}
        for name, addr, _pattern in measured:
            measured_after[name] = await self._rd32(addr, name)
            self.log.info(
                "OBSERVATION %s after the warm reset measured=0x%08x (before 0x%08x)",
                name,
                measured_after[name],
                measured_before[name],
            )
        await self._mark("S10", "measured-only registers read after the event")
        await ClockCycles(self.clk, STEP_CLOCK_GAP)
        self.stamp_ps["S11"] = int(get_sim_time(unit="ps"))
        self.log.info("STEP S11 @%.3fns: PASS stamp", self.stamp_ps["S11"] / 1000)
        monitor.cancel()

        self._check_retained(sb, retained, before, after)
        self._check_wdt_return(sb, cmp_before, ctrl_before, cmp_after, ctrl_after)
        self._check_event(sb, at_arm, arm_idx, i_rise, i_fall)
        self._check_primary_stay(sb, i_fall)
        self._check_measured(sb, measured_before, measured_after)
        self._check_release(sb, (released, release_used), (cleared, clear_used), self.sites[-2:])
        self._check_integrity(sb)
        self.done = True

    def _check_retained(self, sb, retained, before, after) -> None:
        tokens = {
            "SS_CONFIG": "CHK-WARM-RET-SSCFG",
            "SS_COLD_RESET_N": "CHK-WARM-RET-SSCOLD",
        }
        for name, _addr, pattern, reset in retained[:2]:
            token = tokens[name]
            self.log.info(
                "%s: %s before=0x%08x after=0x%08x expected=0x%08x (reset value 0x%08x)",
                token,
                name,
                before[name],
                after[name],
                pattern,
                reset,
            )
            sb.expect_eq(
                f"{token} {name} keeps its pattern across the warm reset",
                (before[name], after[name]),
                (pattern, pattern),
                evidence=token,
            )
        iso = retained[2:]
        got = tuple(v for name, *_ in iso for v in (before[name], after[name]))
        want = tuple(p for _n, _a, p, _r in iso for _ in range(2))
        self.log.info(
            "CHK-WARM-RET-ISO: (ISOLATE_REQ_REG before, after, FLR counter before, after)="
            "%s expected=%s (reset values %s)",
            tuple(f"0x{v:08x}" for v in got),
            tuple(f"0x{v:08x}" for v in want),
            tuple(f"0x{r:08x}" for _n, _a, _p, r in iso),
        )
        sb.expect_eq(
            "CHK-WARM-RET-ISO isolation request and FLR counter keep their values",
            got,
            want,
            evidence="CHK-WARM-RET-ISO",
        )

    def _check_wdt_return(self, sb, cmp_before, ctrl_before, cmp_after, ctrl_after) -> None:
        got = (cmp_before & WDT_CMP_BM, ctrl_before & WDT_ARM_BITS, cmp_after, ctrl_after)
        want = (WDT_CMP_ARMED, WDT_ARM_BITS, WDT_CMP_RESET, WDT_CTRL_RESET)
        self.log.info(
            "CHK-WARM-RET-WDT-RETURN: (CMP before, CTRL arm bits before, CMP after, CTRL after)="
            "%s expected=%s",
            tuple(f"0x{v:08x}" for v in got),
            tuple(f"0x{v:08x}" for v in want),
        )
        sb.expect_eq(
            "CHK-WARM-RET-WDT-RETURN CORE0 CMP and CTRL hold armed values, then reset values",
            got,
            want,
            evidence="CHK-WARM-RET-WDT-RETURN",
        )

    def _check_event(self, sb, at_arm, arm_idx, i_rise, i_fall) -> None:
        got = (at_arm.second, at_arm.warm, i_rise >= arm_idx, i_fall >= arm_idx)
        want = (SECOND_TIMEOUT_IDLE, NET_RELEASED, True, True)
        self.log.info(
            "CHK-WARM-RET-EVENT: (second timeout, warm reset) before arming=%s expected=%s; "
            "second timeout read %d at sample %d and warm reset read %d at sample %d, both "
            "after arming sample %d: %s",
            got[:2],
            want[:2],
            SECOND_TIMEOUT_RAISED,
            i_rise,
            NET_ASSERTED,
            i_fall,
            arm_idx,
            got[2:],
        )
        sb.expect_eq(
            "CHK-WARM-RET-EVENT second timeout rises and warm reset falls after arming",
            got,
            want,
            evidence="CHK-WARM-RET-EVENT",
        )

    def _check_primary_stay(self, sb, i_fall) -> None:
        lo, hi = self.stamp_ps["S2"], self.stamp_ps["S10"]
        window = [s for s in self.trace if lo <= s.t_ps <= hi]
        primary_bad = sum(1 for s in window if s.primary != NET_RELEASED)
        cold_bad = sum(1 for s in window if s.cold != NET_RELEASED)
        gaps = sum(1 for a, b in zip(window, window[1:]) if b.t_ps - a.t_ps != self.period_ps)
        warm_low = sum(1 for s in window if s.warm == NET_ASSERTED)
        got = (primary_bad, cold_bad, gaps, warm_low > 0)
        want = (0, 0, 0, True)
        self.log.info(
            "STEP S6: %d clk_smu_i samples from S2 to S10; the warm reset read 0 in %d of them",
            len(window),
            warm_low,
        )
        self.log.info(
            "CHK-WARM-RET-PRIMARY-STAY: samples with rst_primary_smc_clk_n_o not 1=%d, "
            "rst_cold_n_o not 1=%d, sampling gaps=%d expected 0 each; the warm reset net read 0 "
            "inside the window: %s",
            primary_bad,
            cold_bad,
            gaps,
            warm_low > 0,
        )
        sb.expect_eq(
            "CHK-WARM-RET-PRIMARY-STAY primary and cold outputs read 1 at every sample",
            got,
            want,
            evidence="CHK-WARM-RET-PRIMARY-STAY",
        )

    def _check_measured(self, sb, measured_before, measured_after) -> None:
        self.log.info(
            "CHK-WARM-RET-MEASURED: measured and logged only, not compared; values logged "
            "before=%d after=%d",
            len(measured_before),
            len(measured_after),
        )
        sb.expect_eq(
            "CHK-WARM-RET-MEASURED before and after values logged for each measured register",
            (len(measured_before), len(measured_after)),
            (3, 3),
            evidence="CHK-WARM-RET-MEASURED",
        )

    def _check_release(self, sb, warm_wait, second_wait, records) -> None:
        for rec in records:
            self.log.info(
                "OBSERVATION release wait %s bound=%d used=%d %s last=%s",
                rec["label"],
                rec["bound"],
                rec["used"],
                "EXPIRED" if rec["expired"] else "released",
                rec["last"],
            )
        unresolved = sum(1 for s in self.trace if -1 in (s.second, s.warm, s.primary, s.cold))
        self.log.info(
            "CHK-WARM-RET-RELEASE: warm reset return %s after %d cycles; second timeout return "
            "%s after %d cycles; release waits logged=%d expected=2; unresolved samples=%d "
            "expected=0; the retention compares do not depend on either outcome",
            "seen" if warm_wait[0] else "expired",
            warm_wait[1],
            "seen" if second_wait[0] else "expired",
            second_wait[1],
            len(records),
            unresolved,
        )
        sb.expect_eq(
            "CHK-WARM-RET-RELEASE both release waits logged and no unresolved sample",
            (len(records), unresolved),
            (2, 0),
            evidence="CHK-WARM-RET-RELEASE",
        )

    def _check_integrity(self, sb) -> None:
        for rec in self.sites:
            self.log.info(
                "TIMEOUT-PATH %s %s: bound=%d used=%d %s last=%s",
                rec["kind"],
                rec["label"],
                rec["bound"],
                rec["used"],
                "EXPIRED" if rec["expired"] else "ok",
                rec["last"],
            )
        event_expired = sum(r["expired"] for r in self.sites if r["kind"] == "event")
        kinds = dict(Counter(rec["kind"] for rec in self.sites))
        self.log.info(
            "CHK-TIMEOUT-PATHS: sites=%d expected=%d kinds=%s event expiries=%d expected=0; "
            "release expiries are recorded and not failures",
            len(self.sites),
            EXPECTED_SITES,
            kinds,
            event_expired,
        )
        sb.expect_eq("expired event waits", event_expired, 0, evidence="CHK-TIMEOUT-PATHS")
        sb.expect_eq(
            "bounded wait sites per kind",
            (len(self.sites), kinds),
            (EXPECTED_SITES, EXPECTED_SITE_KINDS),
            evidence="CHK-TIMEOUT-PATHS",
        )

        stamps = [self.stamp_ps[s] for s in STEPS]
        fence = "<".join(f"{s}@{t / 1000:.1f}" for s, t in zip(STEPS, stamps))
        pass_gap = round((stamps[-1] - stamps[-2]) / self.period_ps)
        self.log.info("CHK-NONVAC: ordered sim-time fence %s pass_gap_cycles=%d", fence, pass_gap)
        sb.expect_eq(
            "CHK-NONVAC ordered sim-time fence, PASS stamp two cycles after S10",
            (all(b > a for a, b in zip(stamps, stamps[1:])), pass_gap),
            (True, STEP_CLOCK_GAP),
            evidence="CHK-NONVAC",
        )
