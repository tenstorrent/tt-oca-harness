# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SEP STAP deselected TMS parking, scan-path exclusion and 3DCR reset rules.

Spec: jtag_stap architecture.adoc (a STAP adds its SIB bit while deselected; a deselected STAP
ties its host TMS to the TMS-Hold bit; 3DCR bit 2 TMS-Hold, bit 1 Select, bit 0 Config-Hold, all
reset 0; the register resets on TRST, and on Test-Logic-Reset unless Config-Hold is set).

The 3DCR is written and captured through the SEP SIB of the secondary scan string. The SEP STAP
host TMS is observed on the bench tap tb_stap_sep_tms.
"""

from __future__ import annotations

from collections import Counter

import cocotb
from cocotb.triggers import ClockCycles, RisingEdge
from cocotb.utils import get_sim_time
from ocah_jtag_vip import OcahJtagMasterSequence, OcahJtagState

from seq_lib.smu_boundary_regs import (
    SMU_SEP_STAP_ORDER,
    ptap_prefixed,
    stap_3dcr_scan_word,
    stap_sib_pattern,
)
from seq_lib.smu_compose_helpers import hier, sample
from seq_lib.smu_dtp_sep_dm_dmi_test_seq import (
    IDCODE_DR_WIDTH,
    MIN_PTAP_TMS_EDGES,
    POSTURE_FOLLOW_CYCLES,
    SEP_STAP_TMS,
    SEP_TAP_IR_BYPASS,
    network_ir_scan,
    network_scan,
)
from seq_lib.smu_jtag_helpers import (
    DTP_IR_TAP_3DCR,
    DTP_IR_WIDTH,
    PTAP_3DCR_WIDTH,
    dtp_ir_opcode,
    make_smu_jtag_tap,
    ptap_3dcr_value,
    require_jtag_tdo_resolved,
)
from seq_lib.smu_lifecycle_table import (
    LC_STATE_PRESENSE,
    lc_raw_from_shadow_preload,
    lc_state_name,
    posture,
)

SIB_COUNT = len(SMU_SEP_STAP_ORDER)
SIB_BITS_FROM_SEP = SIB_COUNT - SMU_SEP_STAP_ORDER.index("sep")
STAP_3DCR_BITS = 3
TLR_TMS_HIGHS = 5
IDLE_TCKS = 2
IDLE_TCKS_AFTER_RELEASE = 8

# Bounds of the bounded waits.
POSTURE_POLL_LIMIT = 500
POSTURE_POLL_CYCLES = 10
RESET_DONE_POLL_LIMIT = 500
TMS_WINDOW_CYCLES = 2000
TRST_MAX_TCKS = 16
TRST_TCKS = 4

# 3DCR payloads, bit 2 TMS-Hold, bit 1 Select, bit 0 Config-Hold.
PAYLOAD_RESET = 0b000
PAYLOAD_ALL_SET = 0b111
PAYLOAD_HOLD_CH = 0b101
PAYLOAD_HOLD_NOCH = 0b100

# Flush marker: shifted behind the IDCODE register and the SIBs, it reappears on TDO after the
# chain length in TCKs.
MARKER = 0xB4E5A7
MARKER_BITS = 24
FLUSH_WIDTH = 64
EXPECTED_CHAIN_LEN = IDCODE_DR_WIDTH + SIB_COUNT

# Network scans each test step makes.
SCANS_S1 = 2
SCANS_S2 = 9
SCANS_S3 = 10
SCANS_S4 = 5
SCANS_S5 = 5
EXPECTED_SCANS = SCANS_S1 + SCANS_S2 + SCANS_S3 + SCANS_S4 + SCANS_S5

# Bounded waits: the posture wait, a TMS window per TMS-Hold value and one TRST
# hold; the reset_done poll is the bring-up wait.
EXPECTED_SITE_KINDS = {"posture": 1, "reset_done": 1, "tms_window": 2, "trst_hold": 1}

STEPS = ("S1", "S2", "S3", "S4", "S5", "S6")


def _bit(handle, name: str) -> int:
    return sample(handle, name) & 1


def _chain_length(captured: int, width: int) -> int:
    """TCKs until the flush marker reappears on TDO, or -1 when it is not found exactly once."""
    bits = [(captured >> i) & 1 for i in range(width)]
    pat = [(MARKER >> i) & 1 for i in range(MARKER_BITS)]
    hits = [i for i in range(width - MARKER_BITS + 1) if bits[i : i + MARKER_BITS] == pat]
    return hits[0] if len(hits) == 1 else -1


class smu_sep_stap_hold_reset_test_seq:
    """Deselected SEP STAP: TMS-Hold parking, scan-path length, TRST and Test-Logic-Reset."""

    def __init__(self, test) -> None:
        self.test = test
        self.dut = cocotb.top
        self.cfg = test.cfg
        self.sb = test.env.scoreboard
        self.jtag: OcahJtagMasterSequence | None = None
        self.scans = 0
        self.step_ns: dict[str, float] = {}
        self.step_scans: dict[str, int] = {}
        self.sites: list[dict] = []
        self.done = False
        self.reset_done_polls = 0
        self.posture_polls = 0

    def _log(self, msg: str) -> None:
        cocotb.log.info(msg)

    def _now(self) -> float:
        return float(get_sim_time(unit="ns"))

    def _mark(self, step: str, text: str) -> None:
        self.step_ns[step] = self._now()
        self.step_scans[step] = self.scans
        self._log(f"STEP {step} @{self.step_ns[step]:.3f}ns scans={self.scans}: {text}")

    def _cell(self, name: str, text: str) -> None:
        self._log(f"CELL {name} {text}")

    def _site(self, kind: str, label: str, bound: int, used: int, last: str, expired: bool) -> None:
        self.sites.append(
            {
                "kind": kind,
                "label": label,
                "bound": bound,
                "used": used,
                "last": last,
                "expired": int(expired),
            }
        )
        if expired:
            raise AssertionError(
                f"TIMEOUT {kind} {label}: bound={bound} used={used} last_state={last}"
            )

    def _tms_level(self) -> int:
        return _bit(hier(self.dut, SEP_STAP_TMS), SEP_STAP_TMS)

    async def _dr(self, value: int, width: int, label: str) -> int:
        self.scans += 1
        captured = await self.jtag.shift_dr(value, width, back_to_rti=True)
        require_jtag_tdo_resolved(f"DR {label}")
        self._log(f"SCAN {self.scans} DR {label} w={width} in=0x{value:x} out=0x{captured:x}")
        return captured

    async def _ir(self, value: int, width: int, label: str) -> int:
        self.scans += 1
        captured = await self.jtag.shift_ir(value, width=width, back_to_rti=True)
        require_jtag_tdo_resolved(f"IR {label}")
        self._log(f"SCAN {self.scans} IR {label} w={width} in=0x{value:x} out=0x{captured:x}")
        return captured

    async def _idle(self, tcks: int) -> None:
        for _ in range(tcks):
            await self.jtag.step_tms(0)

    async def _require_debug_open(self) -> None:
        """The SEP STAP is reachable only when the lifecycle posture leaves debug open."""
        preload = cocotb.plusargs.get("sep_shadow_reg_preload")
        assert preload is not None, (
            "+sep_shadow_reg_preload is required: it names the lifecycle state under test"
        )
        state = lc_state_name(lc_raw_from_shadow_preload(str(preload)))
        want = posture(state)
        assert want.all_open, (
            f"the entry's shadow image encodes {state}, whose posture keeps debug disabled; "
            f"the SEP STAP cannot be selected under it"
        )
        polls = 0
        lc_state = sample(self.dut.smc_lc_state_in_o, "smc_lc_state_in_o")
        while lc_state == LC_STATE_PRESENSE:
            if polls >= POSTURE_POLL_LIMIT:
                self._site(
                    "posture",
                    "lc_state_leaves_presense",
                    POSTURE_POLL_LIMIT,
                    polls,
                    f"smc_lc_state_in_o=0x{lc_state:02x}",
                    True,
                )
            await ClockCycles(self.dut.clk_smu_i, POSTURE_POLL_CYCLES)
            polls += 1
            lc_state = sample(self.dut.smc_lc_state_in_o, "smc_lc_state_in_o")
        await ClockCycles(self.dut.clk_smu_i, POSTURE_FOLLOW_CYCLES)
        lc_state = sample(self.dut.smc_lc_state_in_o, "smc_lc_state_in_o")
        dbg_disable = sample(self.dut.lcc_dbg_disable_o, "lcc_dbg_disable_o")
        self._site(
            "posture",
            "lc_state_leaves_presense",
            POSTURE_POLL_LIMIT,
            polls,
            f"smc_lc_state_in_o=0x{lc_state:02x} lcc_dbg_disable_o=0x{dbg_disable:04x}",
            False,
        )
        self.posture_polls = polls
        self.sb.expect_eq(f"lc_state exported for {state}", lc_state, want.lc_state)
        self.sb.expect_eq(
            f"dbg_disable posture for {state} (every debug path open)", dbg_disable, 0
        )
        self._log(
            f"OBS lifecycle posture {state}: lc_state=0x{lc_state:02x} "
            f"dbg_disable=0x{dbg_disable:04x}; the SEP STAP host interface is ungated"
        )

    async def _require_reset_done(self) -> None:
        polls = 0
        while not self.cfg.reset_done.is_set():
            if polls >= RESET_DONE_POLL_LIMIT:
                self._site(
                    "reset_done", "cfg.reset_done", RESET_DONE_POLL_LIMIT, polls, "clear", True
                )
            await ClockCycles(self.dut.clk_smu_i, POSTURE_POLL_CYCLES)
            polls += 1
        self._site("reset_done", "cfg.reset_done", RESET_DONE_POLL_LIMIT, polls, "set", False)
        self.reset_done_polls = polls

    # Scan words. The deselected layouts carry only the PTAP register and the four SIB bits, plus
    # the SEP 3DCR when its SIB is open.

    def _deselected_ir(self, opcode: int) -> tuple[int, int]:
        return opcode << SIB_COUNT, DTP_IR_WIDTH + SIB_COUNT

    def _deselected_3dcr(self, payload: int, sib_en: int) -> tuple[int, int]:
        stap_word, stap_width = stap_3dcr_scan_word(
            "sep",
            config_hold=payload & 1,
            stap_sel=(payload >> 1) & 1,
            tms_hold=(payload >> 2) & 1,
            sib_en=sib_en,
        )
        return ptap_prefixed(stap_word, stap_width)

    def _open_sib(self) -> tuple[int, int]:
        return ptap_prefixed(stap_sib_pattern("sep", 1), SIB_COUNT)

    def _selected_open_sib(self) -> tuple[int, int]:
        value, width = network_scan(ptap_3dcr_value(config_hold=1, select=1), PTAP_3DCR_WIDTH, 0, 1)
        return value | stap_sib_pattern("sep", 1), width

    def _selected_3dcr(self, payload: int) -> tuple[int, int]:
        """SEP register (bypass bit), then the open SEP 3DCR and SIB, TDI first."""
        stap_word, stap_width = stap_3dcr_scan_word(
            "sep",
            config_hold=payload & 1,
            stap_sel=(payload >> 1) & 1,
            tms_hold=(payload >> 2) & 1,
            sib_en=1,
        )
        tail_width = STAP_3DCR_BITS + SIB_BITS_FROM_SEP
        head = stap_word >> tail_width
        tail = stap_word & ((1 << tail_width) - 1)
        head_width = stap_width - tail_width
        sep_width = 1
        value = (
            (ptap_3dcr_value(config_hold=1, select=1) << (head_width + sep_width + tail_width))
            | (head << (sep_width + tail_width))
            | tail
        )
        return value, PTAP_3DCR_WIDTH + head_width + sep_width + tail_width

    @staticmethod
    def _payload(captured: int) -> int:
        return (captured >> SIB_BITS_FROM_SEP) & ((1 << STAP_3DCR_BITS) - 1)

    async def _write_3dcr(self, payload: int, sib_en: int, label: str) -> int:
        value, width = self._deselected_3dcr(payload, sib_en)
        return await self._dr(value, width, label)

    async def _capture_3dcr(self, payload: int, label: str) -> int:
        """A scan with the SIB open captures the 3DCR; it rewrites the same payload."""
        captured = await self._write_3dcr(payload, 1, label)
        return self._payload(captured)

    async def _tlr(self) -> None:
        for _ in range(TLR_TMS_HIGHS):
            await self.jtag.step_tms(1)
        await self.jtag.step_tms(0)

    async def _observe_tms(self, win: dict) -> dict:
        prev_ptap = int(self.dut.jtag_tms.value) & 1
        prev_sep = self._tms_level()
        out = {"ptap_edges": 0, "sep_edges": 0, "levels": set(), "done_cycle": None}
        for cycle in range(1, TMS_WINDOW_CYCLES + 1):
            await RisingEdge(self.dut.clk_ref_i)
            ptap = int(self.dut.jtag_tms.value) & 1
            sep = self._tms_level()
            out["levels"].add(sep)
            if ptap != prev_ptap:
                out["ptap_edges"] += 1
                prev_ptap = ptap
            if sep != prev_sep:
                out["sep_edges"] += 1
                prev_sep = sep
            if win["scan_done"] and out["done_cycle"] is None:
                out["done_cycle"] = cycle
        return out

    async def _tms_hold_leg(self, h: int, ir_is_tap_3dcr: bool) -> tuple[tuple, int]:
        label = f"tms_window_h{h}"
        if not ir_is_tap_3dcr:
            value, width = self._deselected_ir(DTP_IR_TAP_3DCR)
            await self._ir(value, width, f"h{h} IR TAP_3DCR")
        value, width = self._open_sib()
        await self._dr(value, width, f"h{h} open SEP SIB")
        await self._write_3dcr((h << 2) | 0b001, 0, f"h{h} write 3DCR select0 hold{h} ch1")

        win = {"scan_done": False}
        monitor = cocotb.start_soon(self._observe_tms(win))
        value, width = self._deselected_ir(dtp_ir_opcode("IDCODE"))
        await self._ir(value, width, f"h{h} IR IDCODE")
        captured = await self._dr(MARKER, FLUSH_WIDTH, f"h{h} IDCODE DR with flush marker")
        win["scan_done"] = True
        obs = await monitor
        idcode = (captured >> SIB_COUNT) & ((1 << IDCODE_DR_WIDTH) - 1)
        chain_len = _chain_length(captured, FLUSH_WIDTH)
        level_ok = int(obs["levels"] == {h})
        ptap_ok = int(obs["ptap_edges"] >= MIN_PTAP_TMS_EDGES)
        done = obs["done_cycle"]
        self._site(
            "tms_window",
            label,
            TMS_WINDOW_CYCLES,
            done if done is not None else TMS_WINDOW_CYCLES,
            f"levels={sorted(obs['levels'])} ptap_edges={obs['ptap_edges']} "
            f"sep_edges={obs['sep_edges']} scan_done_cycle={done}",
            done is None,
        )
        self._cell(
            f"tms_hold_{h}",
            f"level_ok={level_ok} sep_edges={obs['sep_edges']} ptap_edges={obs['ptap_edges']} "
            f"idcode=0x{idcode:08x}",
        )
        self._cell(
            "sep_tap_not_in_path",
            f"chain_len={chain_len} expected={EXPECTED_CHAIN_LEN} h={h}",
        )
        return (level_ok, obs["sep_edges"], ptap_ok), chain_len

    async def _trst_pulse(self) -> int:
        """Assert TRST for TRST_TCKS TCKs and release it; returns the TCKs it was held."""
        t0 = self._now()
        await self.jtag.assert_trst(tck_cycles=TRST_TCKS, tms=1)
        asserted = int(self.dut.jtag_trst.value)
        t1 = self._now()
        used = round((t1 - t0) / self.cfg.jtag_period_ns)
        await self.jtag.release_trst()
        await self.jtag.goto_state(OcahJtagState.RUN_TEST_IDLE)
        await self._idle(IDLE_TCKS_AFTER_RELEASE)
        released = int(self.dut.jtag_trst.value)
        self._site(
            "trst_hold",
            "jtag_trst",
            TRST_MAX_TCKS,
            used,
            f"jtag_trst asserted={asserted} released={released}",
            used > TRST_MAX_TCKS or asserted != 0 or released != 1,
        )
        return used

    async def run(self) -> None:
        sb = self.sb
        await self._require_reset_done()
        await self._require_debug_open()
        self._log(
            f"CELL bring_up reset_done_polls={self.reset_done_polls} "
            f"posture_polls={self.posture_polls}"
        )

        raw = make_smu_jtag_tap(self.dut, self.cfg.jtag_period_ns)
        jtag = OcahJtagMasterSequence(raw)
        self.jtag = jtag

        self._mark("S1", "TEST_DEV posture, TAP in Run-Test/Idle, PTAP 3DCR select and Config-Hold")
        jtag.sync_model(OcahJtagState.TEST_LOGIC_RESET)
        await jtag.goto_state(OcahJtagState.RUN_TEST_IDLE)
        await self._idle(IDLE_TCKS_AFTER_RELEASE)
        await self._ir(DTP_IR_TAP_3DCR, DTP_IR_WIDTH, "PTAP IR TAP_3DCR")
        await self._dr(
            ptap_3dcr_value(config_hold=1, select=1), PTAP_3DCR_WIDTH, "PTAP TAP_3DCR select"
        )
        await self._idle(IDLE_TCKS)

        self._mark("S2", "SEP STAP deselected: TMS-Hold parking and scan-path length")
        legs = []
        for h in (0, 1):
            legs.append(await self._tms_hold_leg(h, ir_is_tap_3dcr=(h == 0)))
        sb.expect_eq(
            "CHK-DBG-STAP-TMS-HOLD parked level, SEP TMS edges, PTAP edges and chain length",
            (legs[0][0], legs[1][0], (legs[0][1], legs[1][1])),
            ((1, 0, 1), (1, 0, 1), (EXPECTED_CHAIN_LEN, EXPECTED_CHAIN_LEN)),
            evidence="DBG_STAP_TMS_HOLD",
        )

        self._mark("S3", "TRST with Config-Hold set clears the 3DCR")
        value, width = self._deselected_ir(DTP_IR_TAP_3DCR)
        await self._ir(value, width, "IR TAP_3DCR")
        value, width = self._open_sib()
        await self._dr(value, width, "open SEP SIB")
        await self._write_3dcr(PAYLOAD_ALL_SET, 0, "write 3DCR 111 select")
        await self._idle(IDLE_TCKS)
        value, width = network_ir_scan(DTP_IR_TAP_3DCR, SEP_TAP_IR_BYPASS)
        await self._ir(value, width, "network IR TAP_3DCR, SEP IR BYPASS")
        value, width = self._selected_open_sib()
        await self._dr(value, width, "open SEP SIB, SEP selected")
        value, width = self._selected_3dcr(PAYLOAD_ALL_SET)
        before_trst = self._payload(await self._dr(value, width, "capture 3DCR, SEP selected"))
        tms_before = self._tms_level()
        await self._trst_pulse()
        tms_after = self._tms_level()
        await self._ir(DTP_IR_TAP_3DCR, DTP_IR_WIDTH, "PTAP IR TAP_3DCR after TRST")
        await self._dr(
            ptap_3dcr_value(config_hold=1, select=1), PTAP_3DCR_WIDTH, "PTAP TAP_3DCR re-select"
        )
        value, width = self._open_sib()
        await self._dr(value, width, "open SEP SIB after TRST")
        after_trst = await self._capture_3dcr(PAYLOAD_RESET, "capture 3DCR after TRST")
        self._cell("trst_clears_3dcr", f"before=0x{before_trst:x} after=0x{after_trst:x}")
        self._log(
            f"CELL tms_level_around_trst tb_stap_sep_tms before={tms_before} after={tms_after} "
            "(measured, not compared)"
        )

        results = {}
        for step, payload, label in (
            ("S4", PAYLOAD_HOLD_CH, "tlr_with_config_hold_1"),
            ("S5", PAYLOAD_HOLD_NOCH, "tlr_with_config_hold_0"),
        ):
            self._mark(step, f"{label}: write {payload:03b}, capture, Test-Logic-Reset, capture")
            await self._write_3dcr(payload, 1, f"write 3DCR {payload:03b}")
            before = await self._capture_3dcr(payload, f"capture 3DCR {payload:03b}")
            await self._tlr()
            value, width = self._deselected_ir(DTP_IR_TAP_3DCR)
            await self._ir(value, width, f"IR TAP_3DCR after TLR {payload:03b}")
            value, width = self._open_sib()
            await self._dr(value, width, f"PTAP re-select, open SEP SIB after TLR {payload:03b}")
            after = await self._capture_3dcr(payload, f"capture 3DCR after TLR {payload:03b}")
            results[label] = (before, after)
            self._cell(label, f"before=0x{before:x} after=0x{after:x}")
        sb.expect_eq(
            "CHK-DBG-STAP-3DCR-RESET TRST and Test-Logic-Reset legs, (before, after)",
            ((before_trst, after_trst), *results.values()),
            (
                (PAYLOAD_ALL_SET, PAYLOAD_RESET),
                (PAYLOAD_HOLD_CH, PAYLOAD_HOLD_CH),
                (PAYLOAD_HOLD_NOCH, PAYLOAD_RESET),
            ),
            evidence="DBG_STAP_3DCR_RESET",
        )

        self._mark("S6", "TIMEOUT: bounded waits and last state")
        for rec in self.sites:
            state = "EXPIRED" if rec["expired"] else "ok"
            self._log(
                f"TIMEOUT-PATH {rec['kind']} {rec['label']}: bound={rec['bound']} "
                f"used={rec['used']} {state} last={rec['last']}"
            )
        expired = sum(rec["expired"] for rec in self.sites)
        kinds = dict(Counter(rec["kind"] for rec in self.sites))
        self._log(f"CHK-TIMEOUT-PATHS: sites={len(self.sites)} kinds={kinds} expired={expired}")
        sb.expect_eq("expired TIMEOUT-PATH records", expired, 0, evidence="CHK_TIMEOUT_PATHS")
        sb.expect_eq("bounded wait kinds named by the test steps", kinds, EXPECTED_SITE_KINDS)

        await ClockCycles(self.dut.clk_ref_i, 2)
        self._log(f"OBS final {SEP_STAP_TMS}={self._tms_level()} after the Test-Logic-Reset legs")
        self.step_ns["PASS"] = self._now()
        order = [*STEPS, "PASS"]
        step_counts = tuple(
            b - a
            for a, b in zip(
                (self.step_scans[s] for s in STEPS[:-1]), (self.step_scans[s] for s in STEPS[1:])
            )
        )
        stamps = [self.step_ns[s] for s in order]
        deltas = [b - a for a, b in zip(stamps, stamps[1:])]
        fence = "<".join(f"{s}@{t:.1f}" for s, t in zip(order, stamps))
        self._log(f"CHK-NONVAC: ordered sim-time fence {fence} scans={self.scans}")
        sb.expect_eq(
            "CHK-NONVAC ordered sim-time fence",
            all(d > 0 for d in deltas),
            True,
            evidence="CHK-NONVAC",
        )
        sb.expect_eq(
            "CHK-NONVAC network scans counted at runtime",
            (step_counts, self.scans),
            ((SCANS_S1, SCANS_S2, SCANS_S3, SCANS_S4, SCANS_S5), EXPECTED_SCANS),
            evidence="CHK-NONVAC",
        )
        self.done = True
