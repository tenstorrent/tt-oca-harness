# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
# DV-TESTCASE-CONTRACT: SMU_SEP_SCN_013 ANCHOR: smu_dtp_jtag2axi_smc_reset_inflight_test
# DV-TESTCASE-CONTRACT-REVISION: 1 RECORD-SHA256: b0c97d3966fed33fbf0796b2fc3f3393c65c9632c843d61d61a3b78cdec78e5d
# DV-TESTCASE-CONTRACT-SOURCE: hw/sys/smu/dv/ai/dv_vplan_gen/SMU_SEP_SCN_VPLAN_DETAIL_RESET.md @ artifact_revision 3 ENV: cocotb
"""DTP JTAG2AXI accesses into the SMC fabric across SMC cool, FLR-timed cool and warm resets.

No signal is forced. The resets come from ``rst_cool_n_from_pin_i``, ``cfg_flr_pf_active_i``
and the CORE0 watchdog; ``obs_smc_rst_n_o`` and the read-only warm probe
``u_smc.rst_warm_smc_clk_n`` are sampled on every ``clk_smu_i`` edge.

Expected values: ``hw/sys/smc/regs/gen/adoc/blocks/cpu_ctrl.adoc`` (RESET_VECTOR reset
0xC0040000), ``reset_unit.adoc`` (SS_CONFIG reset 0x0; ISOLATE_REQ_REG) and
``hw/sys/smc/doc/clk_rst.adoc`` (the cool-reset pin and the FLR cool reset feed the primary
reset; SS_CONFIG is on the primary reset, the isolation registers on the stable cold reset; the
watchdog second timeout asserts warm reset and not the primary reset).

An access issued inside a reset may never complete; its outcome is an ``OBS-`` line
and only its launch inside the window is graded. A launch is the TCK falling edge in
Update-DR of the SMC_AXI_SINGLE_OP scan. The warm-reset read is shifted in and held in
Pause-DR until the warm probe reads 0, then updated.

S1 SETUP: TAP reset, IDCODE, JTAG2AXI gate and CAPS; sampling starts.
S2 BASELINE: RESET_VECTOR[0] read; ISOLATE_REQ_REG and SS_CONFIG written and read back.
S3 DURING_COOL: RESET_VECTOR[0] read and SCRATCH[0] write inside a pin cool reset released
   20000 clk_ref after the hold starts, then inside an FLR-timed cool reset (counters 0 / 4096).
S4 MID_RELEASE: a read launched with the pin held; the pin releases 0, 8 and 32 TCK after it.
S5 POST: SS_CONFIG and ISOLATE_REQ_REG.
S6 FRESH: SCRATCH[0] write and read, RESET_VECTOR[0] read.
S7 DURING_WARM: SS_CONFIG pattern, CORE0 watchdog armed with WDOGRSTEN, SS_CONFIG read
   launched while the warm probe reads 0.
S8 TIMEOUT: every capture poll, reset level wait and warm wait is bounded and logged.
"""

from __future__ import annotations

import bisect
from collections import Counter

import cocotb
from cocotb.triggers import ClockCycles, RisingEdge
from cocotb.utils import get_sim_time
from dtp_types import DTP_IR_WIDTH
from ocah_jtag_vip import OcahJtagMasterDriverError, OcahJtagState

from seq_lib.smu_addr_map import cpu_ctrl_bm, reset_unit_u32, smc_addr, smc_indexed_addr, wdt_u32
from seq_lib.smu_compose_helpers import hier
from seq_lib.smu_jtag_helpers import (
    DTP_DEFAULT_IDCODE,
    DTP_EXPECTED_SMC_JTAG2AXI_CAPS,
    DTP_IR_SMC_AXI_SINGLE_OP,
    J2A_OP_READ,
    J2A_OP_WRITE,
    J2A_STATUS_BUSY,
    J2A_STATUS_SUCCESS,
    SMC_DBG_AXSIZE_4B,
    SMC_DBG_AXSIZE_8B,
    SMC_DBG_SINGLE_OP_LEN,
    WDT_KEY_MAGIC,
    axi64_pack32,
    axi64_unpack32,
    make_smu_jtag_tap,
    pack_single_op,
    require_jtag_tdo_resolved,
    unpack_single_op,
)
from seq_lib.smu_tb_pins import smu_scope

RV0 = smc_indexed_addr("SMC_TOP_SMC_CPU_CTRL_RESET_VECTOR_BASE_ADDR", 0)
SCRATCH0 = smc_indexed_addr("SMC_TOP_SMC_CPU_CTRL_SCRATCH_BASE_ADDR", 0)
SS_CONFIG = smc_addr("SMC_TOP_SMC_RESET_UNIT_SS_CONFIG_BASE_ADDR")
ISOLATE_REQ_REG = smc_addr("SMC_TOP_SMC_RESET_UNIT_ISOLATE_REQ_REG_BASE_ADDR")
FLR_COUNTER = smc_addr("SMC_TOP_SMC_RESET_UNIT_ISOLATE_REQ_FLR_COUNTER_VALUE_BASE_ADDR")
FLR_RESET_COUNTER = smc_addr("SMC_TOP_SMC_RESET_UNIT_ISOLATE_REQ_FLR_RESET_COUNTER_VALUE_BASE_ADDR")
WDT_KEY = smc_addr("SMC_TOP_SMC_CLUSTER_CORE0_WDT_KEY_BASE_ADDR")
WDT_CTRL = smc_addr("SMC_TOP_SMC_CLUSTER_CORE0_WDT_CTRL_BASE_ADDR")
WDT_CMP = smc_addr("SMC_TOP_SMC_CLUSTER_CORE0_WDT_CMP_BASE_ADDR")

# cpu_ctrl.adoc RESET_VECTOR[4]: field `vector` [55:0], reset 0xC0040000.
RV_BM = cpu_ctrl_bm("CPU_CTRL__RESET_VECTOR__VECTOR_bm")
RV_RESET = 0xC004_0000
SS_CONFIG_RESET = reset_unit_u32("RESET_UNIT__SS_CONFIG__SS_CONFIG_reset")
WDT_ARM_BITS = (
    wdt_u32("WDT__CTRL__WDOGRSTEN_bm")
    | wdt_u32("WDT__CTRL__WDOGENALWAYS_bm")
    | wdt_u32("WDT__CTRL__WDOGZEROCMP_bm")
)
WDT_CMP_ARMED = 0x10

# Patterns, each different from its register's reset value 0.
ISO_PAT = 0xA5A5_A5A5
SS_CONFIG_PAT = 0x5A5A_5A5A
SS_CONFIG_WARM_PAT = 0x3C3C_C3C3
SCRATCH_DURING = {"pin": 0x0C00_1D01, "flr": 0x0C00_1D02}
SCRATCH_FRESH = 0x5C0F_2E55
FLR_COUNTER_VALUE = 0
FLR_HOLD_REF = 4096

# Bench bounds. The capture poll is the jtag2axi_single_* poll: 32 clk_smu, then up to 128
# captures 16 clk_smu apart.
POLL_LIMIT = 128
FIRST_POLL_GAP_SMU = 32
POLL_GAP_SMU = 16
IDLE_TCK = 2
COOL_HOLD_REF = 20000
ASSERT_BOUND_REF = 128
RELEASE_BOUND_REF = 8192
WARM_EVENT_BOUND_NS = 980_000
WARM_RISE_BOUND_SMU = 20000
MID_OFFSETS_TCK = (0, 8, 32)
STEP_CLOCK_GAP = 2

TERMS = ("SETUP", "BASELINE", "DURING_COOL", "MID_RELEASE", "POST", "FRESH", "DURING_WARM")
# Wait sites per kind, from the step list: graded capture polls (S2 5, S3 FLR counters 2,
# S5 2, S6 3, S7 arming 5), in-reset capture polls (S3 4, S4 3, S7 1), reset level waits
# (S3 2 + 2, S4 3 x 2) and warm waits (fall, rise).
EXPECTED_SITE_KINDS = {"capture": 17, "obs_capture": 8, "reset": 10, "warm": 2}

STATUS_NAME = {0: "OKAY", 1: "SLVERR", 2: "DECERR", 3: "BUSY"}


def _level(signal) -> int:
    val = signal.value
    if hasattr(val, "is_resolvable") and not val.is_resolvable:
        return -1
    return int(val)


def _now_ps() -> int:
    return int(get_sim_time(unit="ps"))


class smu_dtp_jtag2axi_smc_reset_inflight_test_seq:
    """JTAG2AXI SINGLE_OP accesses into the SMC fabric across SMC cool, FLR and warm resets."""

    def __init__(self, test) -> None:
        self.test = test
        self.dut = cocotb.top
        self.cfg = test.cfg
        self.log = test.logger
        self.sb = test.env.scoreboard
        self.clk = self.dut.clk_smu_i
        self.warm = hier(smu_scope(self.dut), "u_smc.rst_warm_smc_clk_n")
        self.primary = self.dut.obs_smc_rst_n_o
        self.smu_ps = round(self.cfg.smu_clk_period_ns * 1000)
        self.ref_ps = round(self.cfg.ref_clk_period_ns * 1000)
        self.tck_ps = round(self.cfg.jtag_period_ns * 1000)
        self.t: list[int] = []
        self.p: list[int] = []
        self.w: list[int] = []
        self.sites: list[dict] = []
        self.stamps: dict[str, int] = {}
        self.counts: Counter = Counter()
        self.term = "SETUP"
        self.pin_release_ps = 0
        self.watch_warm = False
        self.warm_fell = False
        self.done = False

    # ---- probes ------------------------------------------------------------------------

    def _bit(self, name: str) -> int:
        pin = getattr(self.dut, name, None)
        if pin is None:
            raise AssertionError(f"{name} unobservable on this TB top")
        val = pin.value
        if not val.is_resolvable:
            raise AssertionError(f"X/Z on {name}: {val}")
        return int(val) & 1

    async def _monitor(self) -> None:
        while True:
            await RisingEdge(self.clk)
            self.t.append(_now_ps())
            self.p.append(_level(self.primary))
            self.w.append(_level(self.warm))
            if self.watch_warm and self.w[-1] == 0:
                self.warm_fell = True

    def _window(self, lo_ps: int, hi_ps: int) -> range:
        return range(bisect.bisect_left(self.t, lo_ps), bisect.bisect_right(self.t, hi_ps))

    def _first_level(self, level: int, after_ps: int) -> int:
        for i in range(bisect.bisect_left(self.t, after_ps), len(self.t)):
            if self.p[i] == level:
                return self.t[i]
        return -1

    def _first_rise(self, after_ps: int) -> int:
        return self._first_level(1, after_ps)

    def _state(self) -> str:
        return (
            f"primary={_level(self.primary)} warm={_level(self.warm)} "
            f"pin={int(self.dut.tb_cool_reset_pin.value)} tap={self.jtag.get_current_state().name}"
        )

    async def _mark(self, term: str, text: str) -> None:
        await RisingEdge(self.clk)
        self.stamps[term] = _now_ps()
        self.log.info(
            "STEP %s @%.3fns n=%d: %s", term, self.stamps[term] / 1000, self.counts[term], text
        )

    def _site(self, kind: str, label: str, bound: int, used: int, met: bool) -> None:
        self.sites.append(
            {
                "kind": kind,
                "label": label,
                "bound": bound,
                "used": used,
                "met": met,
                "last": self._state(),
            }
        )

    # ---- bounded waits -----------------------------------------------------------------

    async def _wait_obs(self, level: int, bound: int, label: str) -> int:
        used = 0
        while _level(self.primary) != level and used < bound:
            await RisingEdge(self.dut.clk_ref_i)
            used += 1
        met = _level(self.primary) == level
        self._site("reset", label, bound, used, met)
        if not met:
            raise AssertionError(
                f"TIMEOUT reset {label}: obs_smc_rst_n_o never read {level}; bound={bound} "
                f"clk_ref used={used} last_state={self.sites[-1]['last']}"
            )
        return used

    async def _wait_warm(self, level: int, bound: int, label: str) -> int:
        used = 0
        while _level(self.warm) != level and used < bound:
            await RisingEdge(self.clk)
            used += 1
        met = _level(self.warm) == level
        self._site("warm", label, bound, used, met)
        if not met:
            raise AssertionError(
                f"TIMEOUT warm {label}: warm probe never read {level}; bound={bound} clk_smu "
                f"used={used} last_state={self.sites[-1]['last']}"
            )
        return used

    # ---- JTAG2AXI ----------------------------------------------------------------------

    async def _open_tap(self) -> None:
        """S1 bring-up: TAP reset, IDCODE, gate closed-check, SMC JTAG2AXI CAPS."""
        self.jtag = make_smu_jtag_tap(self.dut, self.cfg.jtag_period_ns)
        await self.jtag.reset_tap()
        await self.jtag.goto_state(OcahJtagState.RUN_TEST_IDLE)
        for _ in range(8):
            await self.jtag.step_tms(0)
        idcode = await self.jtag.read_idcode()
        if idcode != DTP_DEFAULT_IDCODE:
            raise AssertionError(f"IDCODE want 0x{DTP_DEFAULT_IDCODE:x} got 0x{idcode:08x}")
        gate = self._bit("tb_smc_jtag2axi_security_disable")
        if gate != 0:
            raise AssertionError(f"SMC J2A still gated after TCK sync: security_disable={gate}")
        caps = int(await self.jtag.read("SMC_JTAG2AXI_CAPS")) & ((1 << 14) - 1)
        require_jtag_tdo_resolved("SMC J2A CAPS")
        if caps != DTP_EXPECTED_SMC_JTAG2AXI_CAPS:
            raise AssertionError(
                f"SMC J2A CAPS=0x{caps:04x} want 0x{DTP_EXPECTED_SMC_JTAG2AXI_CAPS:04x}"
            )
        self.counts[self.term] += 1

    async def _ensure_tap(self, leg: str, last_complete: bool) -> None:
        """Repeat the S1 bring-up when the TAP or the bridge did not come through the reset."""
        try:
            idcode = await self.jtag.read_idcode()
        except OcahJtagMasterDriverError:
            idcode = 0xFFFF_FFFF
        gate = _level(self.dut.tb_smc_jtag2axi_security_disable)
        reasons = []
        if not last_complete:
            reasons.append("capture-none")
        if idcode != DTP_DEFAULT_IDCODE:
            reasons.append("idcode")
        if gate != 0:
            reasons.append("gate")
        self.log.info(
            "OBS-J2A-REBRINGUP: leg=%s needed=%d reason=%s idcode=0x%08x gate=%d",
            leg,
            int(bool(reasons)),
            ",".join(reasons) or "-",
            idcode,
            gate,
        )
        if reasons:
            await self._open_tap()

    async def _launch(self, op: int, addr: int, data: int, wstrb: int, size: int, park=None):
        """Shift one SMC_AXI_SINGLE_OP; return at the TCK falling edge in Update-DR."""
        jtag = self.jtag
        raw = pack_single_op(op, addr, data, wstrb=wstrb, size=size)
        await jtag.shift_ir(DTP_IR_SMC_AXI_SINGLE_OP, width=DTP_IR_WIDTH, back_to_rti=False)
        await jtag.goto_state(OcahJtagState.SHIFT_DR)
        for i in range(SMC_DBG_SINGLE_OP_LEN):
            await jtag.step(1 if i == SMC_DBG_SINGLE_OP_LEN - 1 else 0, (raw >> i) & 1)
        if park is not None:
            cond, bound, label = park
            await jtag.step_tms(0)  # EXIT1_DR -> PAUSE_DR
            used = 0
            while not cond() and used < bound and not self.warm_fell:
                await jtag.step_tms(0)
                used += 1
            met = cond()
            if not met and self.warm_fell:
                raise AssertionError(
                    f"{label}: the warm reset fell and released before the read reached "
                    f"Pause-DR ({used} TCK parked); last_state={self._state()}"
                )
            self._site("warm", label, bound, used, met)
            if not met:
                raise AssertionError(
                    f"TIMEOUT warm {label}: bound={bound} TCK used={used} "
                    f"last_state={self.sites[-1]['last']}"
                )
            await jtag.step_tms(1)  # PAUSE_DR -> EXIT2_DR
        await jtag.step_tms(1)  # -> UPDATE_DR; the step ends on the updating falling edge
        self.counts[self.term] += 1
        return {
            "op": op,
            "addr": addr,
            "t_upd": _now_ps(),
            "p_upd": _level(self.primary),
            "w_upd": _level(self.warm),
        }

    async def _idle(self, steps: int, at: int = -1, action=None) -> None:
        """``steps`` TCK cycles from Update-DR (the first enters Run-Test/Idle); ``action``
        runs after ``at`` of them."""
        if at == 0 and action is not None:
            action()
        for k in range(1, steps + 1):
            await self.jtag.step_tms(0)
            if k == at and action is not None:
                action()

    async def _poll(self, rec: dict, label: str, graded: bool, deadline_ps=None) -> dict:
        """Bounded SINGLE_OP capture poll; graded expiry fails, in-reset expiry is an outcome."""
        await ClockCycles(self.clk, FIRST_POLL_GAP_SMU)
        scan_ps = (DTP_IR_WIDTH + SMC_DBG_SINGLE_OP_LEN + 12) * self.tck_ps
        reserve_ps = 2 * scan_ps + (FIRST_POLL_GAP_SMU + POLL_GAP_SMU) * self.smu_ps
        status, rdata, used, resolved = J2A_STATUS_BUSY, 0, 0, True
        while used < POLL_LIMIT:
            if deadline_ps is not None and _now_ps() + reserve_ps > deadline_ps:
                break
            capt = await self.jtag.read("SMC_AXI_SINGLE_OP", shift_value=0)
            used += 1
            resolved = _level(self.dut.jtag_tdo) >= 0
            if graded:
                require_jtag_tdo_resolved(f"J2A poll {label} @0x{rec['addr']:08x}")
            status, rdata = unpack_single_op(capt)
            if status != J2A_STATUS_BUSY:
                break
            await ClockCycles(self.clk, POLL_GAP_SMU)
        complete = status != J2A_STATUS_BUSY and resolved
        self._site("capture" if graded else "obs_capture", label, POLL_LIMIT, used, complete)
        if graded and not complete:
            raise AssertionError(
                f"TIMEOUT capture {label} @0x{rec['addr']:08x}: bound={POLL_LIMIT} used={used} "
                f"status={STATUS_NAME[status]} last_state={self.sites[-1]['last']}"
            )
        rec.update(
            status=status if complete else None,
            rdata=rdata,
            used=used,
            complete=complete,
            t_end=_now_ps(),
            p_end=_level(self.primary),
        )
        return rec

    async def _access(
        self, op, addr, data=0, *, size=SMC_DBG_AXSIZE_4B, label, graded=True, deadline_ps=None
    ) -> dict:
        if size == SMC_DBG_AXSIZE_4B:
            wstrb, beat = axi64_pack32(addr, data) if op == J2A_OP_WRITE else (0, 0)
        else:
            wstrb, beat = (0xFF, data) if op == J2A_OP_WRITE else (0, 0)
        rec = await self._launch(op, addr, beat, wstrb, size)
        await self._idle(1 + IDLE_TCK)
        rec = await self._poll(rec, label, graded, deadline_ps)
        if graded:
            require_jtag_tdo_resolved(f"J2A {label} @0x{addr:08x}")
        if size == SMC_DBG_AXSIZE_4B:
            rec["value"] = axi64_unpack32(addr, rec["rdata"])
        else:
            rec["value"] = rec["rdata"] & RV_BM
        return rec

    async def _wr_ok(self, addr: int, data: int, label: str) -> None:
        rec = await self._access(J2A_OP_WRITE, addr, data, label=label)
        if rec["status"] != J2A_STATUS_SUCCESS:
            raise AssertionError(f"{label} write @0x{addr:08x} status={rec['status']}")

    def _obs_status(self, rec: dict) -> str:
        return "none" if rec["status"] is None else str(rec["status"])

    def _cyc(self, rec: dict) -> int:
        return (rec["t_end"] - rec["t_upd"]) // self.smu_ps

    # ---- steps -------------------------------------------------------------------------

    async def _baseline(self) -> dict:
        self.term = "BASELINE"
        rv = await self._access(J2A_OP_READ, RV0, size=SMC_DBG_AXSIZE_8B, label="s2_rv0")
        self.log.info("OBS-J2A-ENTRY: view=local addr=0x%08x", RV0)
        iso_w = await self._access(J2A_OP_WRITE, ISOLATE_REQ_REG, ISO_PAT, label="s2_iso_wr")
        iso_r = await self._access(J2A_OP_READ, ISOLATE_REQ_REG, label="s2_iso_rd")
        cfg_w = await self._access(J2A_OP_WRITE, SS_CONFIG, SS_CONFIG_PAT, label="s2_sscfg_wr")
        cfg_r = await self._access(J2A_OP_READ, SS_CONFIG, label="s2_sscfg_rd")
        await self._mark("BASELINE", "RESET_VECTOR[0] read; ISOLATE_REQ_REG and SS_CONFIG rw")
        got = (
            STATUS_NAME[rv["status"]],
            rv["value"],
            STATUS_NAME[iso_w["status"]],
            STATUS_NAME[iso_r["status"]],
            iso_r["value"],
            STATUS_NAME[cfg_w["status"]],
            STATUS_NAME[cfg_r["status"]],
            cfg_r["value"],
        )
        want = ("OKAY", RV_RESET, "OKAY", "OKAY", ISO_PAT, "OKAY", "OKAY", SS_CONFIG_PAT)
        self.log.info(
            "S2 observed RV0=0x%x ISOLATE_REQ_REG=0x%08x SS_CONFIG=0x%08x statuses=%s",
            rv["value"],
            iso_r["value"],
            cfg_r["value"],
            got[0:1] + got[2:4] + got[5:7],
        )
        self.sb.expect_eq(
            "CHK-J2A-RV-BASELINE: RV0=0xC0040000 OKAY; patterns read back",
            got,
            want,
            evidence="CHK-J2A-RV-BASELINE",
        )
        return {"iso": iso_r["value"]}

    async def _scheduled_release(self, cycles: int) -> None:
        await ClockCycles(self.dut.clk_ref_i, cycles)
        self.dut.tb_cool_reset_pin.value = 0
        self.pin_release_ps = _now_ps()

    def _release_now(self) -> None:
        self.dut.tb_cool_reset_pin.value = 0
        self.pin_release_ps = _now_ps()

    def _log_cool(self, src: str, dirn: str, rec: dict) -> None:
        self.log.info(
            "OBS-J2A-DURING-COOL: src=%s dir=%s status=%s rdata=0x%x before_release=%d cyc=%d",
            src,
            dirn,
            self._obs_status(rec),
            rec["value"],
            int(rec["p_end"] == 0),
            self._cyc(rec),
        )

    async def _cool_pin(self) -> dict:
        dut = self.dut
        await RisingEdge(dut.clk_ref_i)
        dut.tb_cool_reset_pin.value = 1
        t_hold = _now_ps()
        release = cocotb.start_soon(self._scheduled_release(COOL_HOLD_REF))
        await self._wait_obs(0, ASSERT_BOUND_REF, "s3 pin assert")
        # The clk_smu samples place the fall; the clk_ref wait above sees it one edge late.
        t_fall = self._first_level(0, t_hold)
        deadline = t_hold + COOL_HOLD_REF * self.ref_ps
        rd = await self._access(
            J2A_OP_READ,
            RV0,
            size=SMC_DBG_AXSIZE_8B,
            label="s3_pin_rd",
            graded=False,
            deadline_ps=deadline,
        )
        self._log_cool("pin", "r", rd)
        wr = await self._access(
            J2A_OP_WRITE, SCRATCH0, SCRATCH_DURING["pin"], label="s3_pin_wr", graded=False
        )
        self._log_cool("pin", "w", wr)
        await release
        t_rel = self.pin_release_ps
        await self._wait_obs(1, RELEASE_BOUND_REF, "s3 pin release")
        t_rise = self._first_rise(t_fall)
        self.log.info(
            "OBSERVATION S3 pin hold@%d fall@%d release@%d rise@%d ps (release %d clk_ref "
            "after the hold)",
            t_hold,
            t_fall,
            t_rel,
            t_rise,
            (t_rel - t_hold) // self.ref_ps,
        )
        await self._ensure_tap("s3_pin", rd["complete"] and wr["complete"])
        low = self._window(t_fall, t_rel)
        return {
            "upd_p": (rd["p_upd"], wr["p_upd"]),
            "upd_in": all(t_fall <= r["t_upd"] < t_rel for r in (rd, wr)),
            "samples_high": sum(1 for i in low if self.p[i] != 0),
            "samples": len(low),
            "rise_after_schedule": t_rise >= t_rel,
        }

    async def _cool_flr(self) -> dict:
        dut = self.dut
        dut.tb_cfg_flr_pf_active.value = 0
        await self._wr_ok(FLR_COUNTER, FLR_COUNTER_VALUE, "s3_flr_counter")
        await self._wr_ok(FLR_RESET_COUNTER, FLR_HOLD_REF, "s3_flr_reset_counter")
        dut.tb_cfg_flr_pf_active.value = 1
        t_edge = _now_ps()
        await self._wait_obs(0, ASSERT_BOUND_REF, "s3 flr assert")
        t_fall = self._first_level(0, t_edge)
        deadline = t_fall + FLR_HOLD_REF * self.ref_ps
        rd = await self._access(
            J2A_OP_READ,
            RV0,
            size=SMC_DBG_AXSIZE_8B,
            label="s3_flr_rd",
            graded=False,
            deadline_ps=deadline,
        )
        self._log_cool("flr", "r", rd)
        wr = await self._access(
            J2A_OP_WRITE, SCRATCH0, SCRATCH_DURING["flr"], label="s3_flr_wr", graded=False
        )
        self._log_cool("flr", "w", wr)
        await self._wait_obs(1, FLR_HOLD_REF + RELEASE_BOUND_REF, "s3 flr release")
        dut.tb_cfg_flr_pf_active.value = 0
        t_rise = self._first_rise(t_fall)
        self.log.info(
            "OBSERVATION S3 flr fall@%d rise@%d ps (%d clk_ref low, hold count %d)",
            t_fall,
            t_rise,
            (t_rise - t_fall) // self.ref_ps,
            FLR_HOLD_REF,
        )
        await self._ensure_tap("s3_flr", rd["complete"] and wr["complete"])
        sched = t_fall + FLR_HOLD_REF * self.ref_ps
        low = self._window(t_fall, sched)
        return {
            "upd_p": (rd["p_upd"], wr["p_upd"]),
            "upd_in": all(t_fall <= r["t_upd"] < t_rise for r in (rd, wr)),
            "samples_high": sum(1 for i in low if self.p[i] != 0),
            "samples": len(low),
            "rise_after_schedule": t_rise >= sched,
        }

    async def _during_cool(self) -> None:
        self.term = "DURING_COOL"
        pin = await self._cool_pin()
        flr = await self._cool_flr()
        await self._mark("DURING_COOL", "pin and FLR cool resets with a read and a write inside")
        got = {
            src: (
                r["upd_p"],
                r["upd_in"],
                r["samples_high"],
                r["samples"] > 0,
                r["rise_after_schedule"],
            )
            for src, r in (("pin", pin), ("flr", flr))
        }
        want = {src: ((0, 0), True, 0, True, True) for src in ("pin", "flr")}
        self.log.info(
            "S3 (primary at the two Update-DRs, both inside the window, samples not 0 until the "
            "scheduled release, samples present, release not before the schedule)=%s",
            got,
        )
        self.sb.expect_eq(
            "CHK-J2A-DURING-COOL: pin rd/wr inside reset; flr rd/wr inside reset",
            got,
            want,
            evidence="CHK-J2A-DURING-COOL",
        )

    async def _mid_release(self) -> None:
        self.term = "MID_RELEASE"
        results = {}
        for offset in MID_OFFSETS_TCK:
            self.dut.tb_cool_reset_pin.value = 1
            await self._wait_obs(0, ASSERT_BOUND_REF, f"s4 off{offset} assert")
            rec = await self._launch(J2A_OP_READ, RV0, 0, 0, SMC_DBG_AXSIZE_8B)
            await self._idle(max(offset, 1 + IDLE_TCK), at=offset, action=self._release_now)
            t_rel = self.pin_release_ps
            rec = await self._poll(rec, f"s4_off{offset}", graded=False)
            rec["value"] = rec["rdata"] & RV_BM
            self.log.info(
                "OBS-J2A-MID-RELEASE: offset=%d status=%s rdata=0x%x",
                offset,
                self._obs_status(rec),
                rec["value"],
            )
            await self._wait_obs(1, RELEASE_BOUND_REF, f"s4 off{offset} release")
            t_rise = self._first_rise(rec["t_upd"])
            self.log.info(
                "OBSERVATION S4 offset=%d update@%d pin release@%d (%d TCK) rise@%d poll end@%d ps",
                offset,
                rec["t_upd"],
                t_rel,
                round((t_rel - rec["t_upd"]) / self.tck_ps),
                t_rise,
                rec["t_end"],
            )
            results[offset] = (
                rec["p_upd"],
                round((t_rel - rec["t_upd"]) / self.tck_ps),
                rec["t_upd"] < t_rise <= rec["t_end"],
            )
            await self._ensure_tap(f"s4_off{offset}", rec["complete"])
        await self._mark("MID_RELEASE", "pin released 0, 8 and 32 TCK after the launching update")
        inside = sum(1 for o in MID_OFFSETS_TCK if results[o][0] == 0 and results[o][2])
        self.log.info(
            "S4 (primary at Update-DR, release offset in TCK, rise inside the access) per offset=%s",
            results,
        )
        self.sb.expect_eq(
            f"CHK-J2A-MID-RELEASE: {inside}/3 offsets release inside the access",
            {o: results[o] for o in MID_OFFSETS_TCK},
            {o: (0, o, True) for o in MID_OFFSETS_TCK},
            evidence="CHK-J2A-MID-RELEASE",
        )

    async def _post(self) -> None:
        self.term = "POST"
        cfg = await self._access(J2A_OP_READ, SS_CONFIG, label="s5_sscfg")
        iso = await self._access(J2A_OP_READ, ISOLATE_REQ_REG, label="s5_iso")
        await self._mark("POST", "SS_CONFIG and ISOLATE_REQ_REG read after the resets")
        got = (STATUS_NAME[cfg["status"]], cfg["value"], STATUS_NAME[iso["status"]], iso["value"])
        want = ("OKAY", SS_CONFIG_RESET, "OKAY", ISO_PAT)
        self.log.info("S5 observed (status, SS_CONFIG, status, ISOLATE_REQ_REG)=%s", got)
        self.sb.expect_eq(
            "CHK-J2A-POST-RESET-VALUES: SS_CONFIG=0x0 ISOLATE_REQ_REG=pat",
            got,
            want,
            evidence="CHK-J2A-POST-RESET-VALUES",
        )

    async def _fresh(self) -> None:
        self.term = "FRESH"
        wr = await self._access(J2A_OP_WRITE, SCRATCH0, SCRATCH_FRESH, label="s6_scratch_wr")
        rd = await self._access(J2A_OP_READ, SCRATCH0, label="s6_scratch_rd")
        rv = await self._access(J2A_OP_READ, RV0, size=SMC_DBG_AXSIZE_8B, label="s6_rv0")
        await self._mark("FRESH", "SCRATCH[0] write and read, RESET_VECTOR[0] read")
        got = (
            STATUS_NAME[wr["status"]],
            STATUS_NAME[rd["status"]],
            rd["value"],
            STATUS_NAME[rv["status"]],
            rv["value"],
        )
        want = ("OKAY", "OKAY", SCRATCH_FRESH, "OKAY", RV_RESET)
        self.log.info("S6 observed (wr, rd, SCRATCH[0], rv, RV0)=%s", got)
        self.sb.expect_eq(
            "CHK-J2A-FRESH-ACCESS: scratch rw OKAY; RV0=0xC0040000",
            got,
            want,
            evidence="CHK-J2A-FRESH-ACCESS",
        )

    async def _during_warm(self) -> None:
        self.term = "DURING_WARM"
        await self._wr_ok(SS_CONFIG, SS_CONFIG_WARM_PAT, "s7_sscfg")
        t_arm = _now_ps()
        self.watch_warm = True
        await self._wr_ok(WDT_KEY, WDT_KEY_MAGIC, "s7_wdt_key_cmp")
        await self._wr_ok(WDT_CMP, WDT_CMP_ARMED, "s7_wdt_cmp")
        await self._wr_ok(WDT_KEY, WDT_KEY_MAGIC, "s7_wdt_key_ctrl")
        await self._wr_ok(WDT_CTRL, WDT_ARM_BITS, "s7_wdt_ctrl")
        bound = -(-(WARM_EVENT_BOUND_NS * 1000) // self.tck_ps)
        rec = await self._launch(
            J2A_OP_READ,
            SS_CONFIG,
            0,
            0,
            SMC_DBG_AXSIZE_4B,
            park=(lambda: _level(self.warm) == 0, bound, "s7 warm fall (Pause-DR)"),
        )
        await self._idle(1 + IDLE_TCK)
        rec = await self._poll(rec, "s7_warm_rd", graded=False)
        rec["value"] = axi64_unpack32(SS_CONFIG, rec["rdata"])
        self.log.info(
            "OBS-J2A-DURING-WARM: status=%s rdata=0x%x", self._obs_status(rec), rec["value"]
        )
        await self._wait_warm(1, WARM_RISE_BOUND_SMU, "s7 warm rise")
        t_end = _now_ps()
        await self._ensure_tap("s7_warm", rec["complete"])
        await self._mark("DURING_WARM", "SS_CONFIG read launched while the warm probe read 0")
        win = self._window(t_arm, t_end)
        primary_low = sum(1 for i in win if self.p[i] != 1)
        okay = rec["status"] == J2A_STATUS_SUCCESS
        capture = "OKAY==pat" if okay else "logged"
        got = (
            rec["w_upd"],
            rec["p_upd"],
            primary_low,
            len(win) > 0,
            (not okay) or (rec["value"] == SS_CONFIG_WARM_PAT),
        )
        want = (0, 1, 0, True, True)
        self.log.info(
            "S7 (warm at Update-DR, primary at Update-DR, samples with primary not 1 from arming "
            "to warm release, samples present, an OKAY capture carries the pattern)=%s",
            got,
        )
        self.sb.expect_eq(
            f"CHK-J2A-DURING-WARM: launched in warm; capture={capture}",
            got,
            want,
            evidence="CHK-J2A-DURING-WARM",
        )

    def _integrity(self) -> None:
        for rec in self.sites:
            self.log.info(
                "TIMEOUT-PATH %s %s: bound=%d used=%d %s last=%s",
                rec["kind"],
                rec["label"],
                rec["bound"],
                rec["used"],
                "ok" if rec["met"] else ("obs-none" if rec["kind"] == "obs_capture" else "EXPIRED"),
                rec["last"],
            )
        kinds = dict(Counter(rec["kind"] for rec in self.sites))
        expired = sum(1 for r in self.sites if not r["met"] and r["kind"] != "obs_capture")
        unresolved = sum(1 for p, w in zip(self.p, self.w) if p < 0 or w < 0)
        self.sb.expect_eq(
            f"CHK-TIMEOUT-PATHS: {len(self.sites)} waits in {len(kinds)} kinds, none expired "
            "(bound, used, last state per site)",
            (kinds, expired, unresolved),
            (EXPECTED_SITE_KINDS, 0, 0),
            evidence="CHK-TIMEOUT-PATHS",
        )
        terms = (*TERMS, "PASS")
        stamps = [self.stamps.get(t, -1) for t in terms]
        counts = [self.counts[t] for t in TERMS] + [sum(self.counts.values())]
        fence = ", ".join(f"{t}@{s / 1000:.1f}ns n={n}" for t, s, n in zip(terms, stamps, counts))
        ordered = all(s >= 0 for s in stamps) and all(b > a for a, b in zip(stamps, stamps[1:]))
        self.sb.expect_eq(
            "CHK-NONVAC: SETUP < BASELINE < DURING_COOL < MID_RELEASE < POST < FRESH < "
            f"DURING_WARM < PASS ({fence})",
            (ordered, all(n >= 1 for n in counts)),
            (True, True),
            evidence="CHK-NONVAC",
        )

    async def run(self) -> None:
        await self.cfg.reset_done.wait()
        self.dut.tb_cool_reset_pin.value = 0
        self.dut.tb_cfg_flr_pf_active.value = 0
        await self._open_tap()
        monitor = cocotb.start_soon(self._monitor())
        await self._mark("SETUP", "TAP reset, IDCODE, JTAG2AXI gate open, CAPS; sampling on")
        await self._baseline()
        await self._during_cool()
        await self._mid_release()
        await self._post()
        await self._fresh()
        await self._during_warm()
        await ClockCycles(self.clk, STEP_CLOCK_GAP)
        self.stamps["PASS"] = _now_ps()
        self.log.info("STEP PASS @%.3fns", self.stamps["PASS"] / 1000)
        monitor.cancel()
        self._integrity()
        self.done = True
