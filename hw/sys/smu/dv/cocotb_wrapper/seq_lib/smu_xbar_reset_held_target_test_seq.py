# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Sequence for smu_xbar_reset_held_target_test (SMU_AXI_FAB_019).

DV-TESTCASE-CONTRACT: SMU_AXI_FAB_019 ANCHOR: smu_xbar_reset_held_target_test
DV-TESTCASE-CONTRACT-REVISION: 4 RECORD-SHA256: b553961199b073e5d38d9dee104657566726fffaaf6e4df6bb3d9769f73357cb
DV-TESTCASE-CONTRACT-SOURCE: hw/sys/smu/dv/ai/dv_vplan_gen/SMU_AXI_FAB_VPLAN_DETAIL.md @ artifact_revision 4 ENV: cocotb

The JTAG IC_RESET SEP slice drives the SEP's sep_reset_n low while the SMU
crossbar keeps running. ``sep_reset_no`` resets the SEP system peripherals
(``hw/sys/sep/doc/reset_controller.adoc``), while ``rst_ni`` keeps the SEP
local crossbar, and the override runs no isolation sequence
(``hw/sys/sep/doc/clk_rst.adoc``). The SMU-side ID-width converter in front of
sep_in is on the crossbar reset net; only the SEP-side ID truncation is behind
``sep_reset_no``. Each measurement gets its own hold, and a cold reset
separates the holds.

S1:  over the SEP debug system bus SEP_GLOBAL_BASE_ADDR 0x0 and SEP_REGION_SIZE
     0x1100_0000, which covers the reset window [0, 16 MiB) and SEP SRAM at
     0x1000_0000; SMC inbound filter entry 0 opened over the whole space over
     JTAG2AXI. Baseline: the orphan's SRAM block is written, then an ext_in read
     of SEP SRAM and of SMC VERSION_LO answer OKAY; every counter is sampled.
Hold A
S2:  ARID 0x11 reads 256 INCR beats of SEP SRAM with RREADY dropped after 4
     beats; AWID 0x12 writes 256 INCR beats with WVALID stopped after 4 beats.
S3:  the IC_RESET SEP slice is scanned as smu_dtp_sep_ic_reset_effect_test
     scans it (reset_control, then reset_enable) until sep_reset_n falls; the
     reset nets, the SEP aperture ports and a per-cycle sep_in AR/R trace from
     8 cycles before to 8 after the fall are recorded.
S4:  RREADY rises and the 252 remaining W beats resume; 20000-cycle window.
S5:  ARIDs 0x21..0x24 single reads of VERSION_LO one after another, with no
     ARID 0x11 and no sep_in-bound request issued since the orphan; each must
     complete within 2000 cycles, OKAY with the RDL reset value, and smc_in
     counts four ARs.
S6:  ARID 0x31 read and AWID 0x32 write at SEP global 0x0000_1000; 20000 cycles.
S7:  the slice is scanned back, the aperture re-programmed if the hold reset
     it, a 20000-cycle window, then a fresh SEP SRAM write and read.
S8:  rst_cold_ni as in smu_xbar_zero_aperture_test, the S1 programming again,
     then a fresh SEP SRAM write, its read-back and a VERSION_LO read.
Hold B
S9:  the S2 read orphan only, then the S3 hold.
S10: ARID 0x11 single read of SMC VERSION_LO; 20000-cycle window.
S11: one JTAG2AXI read at 0x8000_0000, outside both apertures, while the S10
     read is held.
S12: release as in S7, then clear as in S8.
Hold C
S13: the S9 orphan and hold.
S14: sixteen ARID 0x41 reads at SEP global 0x0000_1000 + 8k; the AR
     handshakes accepted before ARREADY stays low for 4096 cycles.
S15: release as in S7, then clear as in S8.
Hold D
S16: the S9 orphan and hold.
S17: twenty-four reads under ARIDs 0x50..0x67 at SEP global 0x0000_1000 + 8k.
S18: release as in S7, then clear as in S8.
S19: every wait is bounded and every window logs its length and outcome.

The orphan's fate, the same-ID hold, the acceptance counts, the responses
during and after a hold and whether the release alone restores OKAY are OBS
lines without a verdict (SF-011, SF-012, SF-013, SF-018, SF-023). The R beat
the SEP side of sep_in withdraws at the fall is OBS-SEPIN-WITHDRAWN, recorded
and never graded; the bench's expectation window
(+axi_sva_expect_sep_in_override) covers the checker rules it trips, and the
leaf grades that window under CHK-HELD-REACH. Every handshake is sampled on
the ext_in pins each clk_smu_i cycle; the crossbar subordinate counters, the
sep_in AR tap, the reset nets and the window signals are read from the bench
top. No force or deposit.
"""

from __future__ import annotations

from collections import deque
from pathlib import Path

import cocotb
from cocotb.triggers import ClockCycles, FallingEdge, RisingEdge
from ocah_axi_vip import PROT_NONSECURE, RESP_OKAY, clear_profile
from ocah_jtag_vip import OcahJtagState

from seq_lib.smu_addr_map import (
    INBOUND0_END,
    INBOUND0_FILTER_CONFIG,
    INBOUND0_START,
    SMC_CHIP_CONFIG_VERSION_LO,
    SMC_CHIP_CONFIG_VERSION_LO_RESET,
    c_header_u32,
)
from seq_lib.smu_axi_helpers import make_smu_axi_master
from seq_lib.smu_dtp_sep_dm_sba_test_seq import (
    COLD_RESET_BOUND,
    COLD_RESET_HOLD,
    SBADDRESS0_ADDR,
    SBCS_ADDR,
    SBCS_SBACCESS_64,
    SBCS_SBERROR_W1C,
    SBDATA0_ADDR,
    SBDATA1_ADDR,
    SEP_GLOBAL_BASE_ADDR,
    SEP_GLOBAL_BASE_RESET,
    SEP_REGION_SIZE_ADDR,
    SEP_REGION_SIZE_RESET,
)
from seq_lib.smu_dtp_sep_ic_reset_effect_test_seq import (
    ALL_ONES,
    CAPTURE_POLL_CLK,
    DMI_OP_WRITE,
    SEP_HELD,
    SEP_STAGED,
    smu_dtp_sep_ic_reset_effect_test_seq,
)
from seq_lib.smu_filter_helpers import (
    EXT_FABRIC_PROBE_ADDR,
    PASS_ALL_END,
    PASS_RW_CONFIG,
    SMC_APERTURE_LOCAL_BASE,
)
from seq_lib.smu_jtag_helpers import (
    DTP_DEFAULT_IDCODE,
    DTP_IR_SMC_AXI_SINGLE_OP,
    J2A_OP_READ,
    J2A_OP_WRITE,
    J2A_STATUS_BUSY,
    J2A_STATUS_SUCCESS,
    SMC_DBG_AXSIZE_8B,
    SMC_DBG_SINGLE_OP_LEN,
    make_smu_jtag_tap,
    pack_single_op,
    require_jtag_tdo_resolved,
    unpack_single_op,
)
from seq_lib.smu_lifecycle_table import LC_STATE_PRESENSE
from seq_lib.smu_tb_pins import smc_primary_reset
from seq_lib.smu_xbar_decerr_burst_response_test_seq import (
    _ExtInMonitor,
    _hx,
    _kv,
    _ranges,
    _rn,
    _val,
)

_SEP_ADDR_H = Path(__file__).resolve().parents[6] / "hw/sys/sep/regs/gen/c/sep_addr.h"
SRAM_LOCAL = c_header_u32(_SEP_ADDR_H, "SEP_TOP_SEP_SRAM_BASE_ADDR")

# Aperture placement and probe addresses stated by the contract.
SEP_WIN_BASE = 0x0
SEP_WIN_SIZE = 0x1100_0000
SRAM_GLOBAL = SEP_WIN_BASE + SRAM_LOCAL
DURING_ADDR = 0x0000_1000
OTHER_INIT_ADDR = EXT_FABRIC_PROBE_ADDR
# Four 4 KiB pages of SEP SRAM, one per use, so no burst crosses a 4 KiB boundary
# and no two uses share a word.
ORPHAN_RD_ADDR = SRAM_GLOBAL
ORPHAN_WR_ADDR = SRAM_GLOBAL + 0x1000
AFTER_ADDR = SRAM_GLOBAL + 0x2000
COLD_ADDR = SRAM_GLOBAL + 0x3000

AXI_BURST_INCR = 1
SIZE_8B = 3
SIZE_4B = 2
BEAT_BYTES = 8
ORPHAN_BEATS = 256
ORPHAN_HELD_AFTER = 4

FILL_AWID = 0x01
BASE_SEP_ARID = 0x02
BASE_SMC_ARID = 0x03
ORPHAN_ARID = 0x11
ORPHAN_AWID = 0x12
DIFF_ARIDS = (0x21, 0x22, 0x23, 0x24)
DURING_ARID = 0x31
DURING_AWID = 0x32
SAME_ARID = 0x41
SAME_COUNT = 16
DISTINCT_ARIDS = tuple(range(0x50, 0x68))
AFTER_AWID = 0x71
AFTER_ARID = 0x72
COLD_AWID = 0x73
COLD_ARID = 0x74
COLD_SMC_ARID = 0x75

FILL_PATTERN = bytes((0xA0 + i) & 0xFF for i in range(ORPHAN_BEATS * BEAT_BYTES))
ORPHAN_WR_PATTERN = bytes((0x30 + i) & 0xFF for i in range(ORPHAN_BEATS * BEAT_BYTES))
DURING_WORD = 0x5E1D_0032_5E1D_0032
AFTER_WORD = 0xAF7E_0071_AF7E_0071
COLD_WORD = 0xC01D_0073_C01D_0073


def cold_word(hold: str) -> int:
    """The word each clear writes, distinct per hold, so no clear reads back an earlier one."""
    return COLD_WORD ^ HOLDS.index(hold)


# Observation windows and bounds, in clk_smu_i cycles unless stated.
OBS_WINDOW = 20_000
DIFF_BOUND = 2_000
ACCEPT_STALL = 4_096
XFER_BOUND = 20_000
BEAT_BOUND = 4_000
LEVEL_BOUND = 8_000
PORT_BOUND = 200
SENSE_BOUND = 100_000
J2A_OBS_CAPTURES = 32

COUNTS = (
    "sep_xbar_in_aw_count_o",
    "sep_xbar_in_ar_count_o",
    "smc_xbar_in_ar_count_o",
    "smc_xbar_in_aw_count_o",
    "smu_axi_out_write_count_o",
    "smu_axi_out_read_count_o",
)
PORTS = {
    "sep_xbar_global_base_o": "sep_base",
    "sep_xbar_region_size_o": "sep_size",
    "smc_global_base_o": "smc_base",
    "smc_region_size_o": "smc_size",
}
RESET_NETS = (
    "sep_reset_n_o",
    "obs_sep_rst_n_o",
    "obs_xbar_rst_n_o",
    "rst_primary_smc_clk_n_o",
)
# Ports of the sep_in AXI checker instance, read passively around the fall of sep_reset_n.
TRACE_PORTS = (
    "arvalid",
    "arready",
    "arid",
    "araddr",
    "rvalid",
    "rready",
    "rid",
    "rlast",
    "rresp",
    "rdata",
    "aresetn",
)
TRACE_SPAN = 8
# The bench closes its expectation window WINDOW_CLOSE_MARGIN clk_smu_i cycles
# after the rise of sep_reset_n, give or take the one edge on which the leaf and
# the bench may sample it apart; the leaf waits at most WINDOW_CLOSE_BOUND for it.
WINDOW_CLOSE_MARGIN = 8
WINDOW_CLOSE_BOUND = 64
HOLDS = ("A", "B", "C", "D")
MARKERS = (
    "BASELINE_OK",
    "ORPHAN_A",
    "HOLD_A",
    "ORPHAN_OBSERVED",
    "DIFFID_DONE",
    "FRESH_DURING",
    "RELEASED_A",
    "COLD_A",
    "HOLD_B",
    "SAMEID_OBSERVED",
    "OTHER_INIT",
    "COLD_B",
    "HOLD_C",
    "LIMITS_SAMEID",
    "COLD_C",
    "HOLD_D",
    "LIMITS_DISTINCT",
    "COLD_D",
)
STEPS = tuple(f"S{i}" for i in range(1, 20))


def _word(rdata: int | None, addr: int) -> int | None:
    """The 32-bit word at ``addr`` from its 64-bit beat."""
    if rdata is None:
        return None
    return (rdata >> (8 * (addr % BEAT_BYTES))) & 0xFFFF_FFFF


def _codes(beats: list[dict], key: str) -> str:
    counts: dict[str, int] = {}
    for beat in beats:
        name = _rn(beat[key])
        counts[name] = counts.get(name, 0) + 1
    return ",".join(f"{k}:{v}" for k, v in sorted(counts.items())) or "-"


def _bit(value: int | None) -> str:
    return "X" if value is None else str(value)


class smu_xbar_reset_held_target_test_seq(smu_dtp_sep_ic_reset_effect_test_seq):
    """ext_in traffic orphaned behind the crossbar while the SEP is held in reset."""

    def __init__(self, test) -> None:
        super().__init__(test)
        self.log = test.logger
        self.seed = test.random_seed()
        self.mon: _ExtInMonitor | None = None
        self.master = None
        self.markers: list[tuple[str, int]] = []
        self.steps: dict[str, bool] = {}
        self.windows: list[dict] = []
        self.failures: list[str] = []
        self.lv = {
            "on": False,
            "cold": False,
            "armed": None,
            "held": None,
            "rising": None,
            "in_hold": None,
            "after": TRACE_SPAN,
            "pre": deque(maxlen=TRACE_SPAN),
            "rst_ni_bad": [],
            "samples": 0,
            "win": 0,
            "opens": [],
            "closes": [],
        }
        self.holds: dict[str, dict] = {}
        self.o: dict[str, object] = {}

    # ------------------------------------------------------------------ helpers

    def _info(self, msg: str) -> None:
        self.log.info("INFO-%s", msg)

    def _step(self, step: str, text: str) -> None:
        self._info(f"STEP {step}: cycle={self.mon.cyc if self.mon else 0} {text}")

    def _ctrl(self, name: str) -> None:
        self.markers.append((name, self.mon.cyc))
        self.log.info("CTRL-%s: cycle=%d", name, self.mon.cyc)

    def _grade(self, chk: str, observed: dict, expected: dict, desc: str) -> None:
        """One compare per checker; a failure is recorded and the run goes on to S11."""
        self._info(f"{chk} {desc}")
        try:
            self.sb.expect_eq(chk, _kv(observed), _kv(expected), evidence=chk)
        except AssertionError as exc:
            self.failures.append(str(exc))

    def _counts(self) -> dict[str, int | None]:
        return {name: _val(getattr(self.dut, name)) for name in COUNTS}

    @staticmethod
    def _delta(before: dict, after: dict, name: str) -> int | str:
        if before[name] is None or after[name] is None:
            return "X"
        return after[name] - before[name]

    def _ports(self) -> dict[str, int | None]:
        return {short: _val(getattr(self.dut, name)) for name, short in PORTS.items()}

    def _nets(self) -> dict[str, int | None]:
        return {name: _val(getattr(self.dut, name)) for name in RESET_NETS}

    def _state(self) -> str:
        return f"{self.mon.state()} nets={self._nets()}"

    def _record(self, kind: str, label: str, bound: int, unit: str, used, last: str, expired):
        self.sites.append(
            {
                "kind": kind,
                "label": label,
                "bound": bound,
                "unit": unit,
                "used": used,
                "last": last,
                "expired": int(bool(expired)),
            }
        )

    async def _until(self, label: str, cond, bound: int, *, fatal: bool = True) -> int | None:
        """Wait, one clk_smu_i edge at a time, for ``cond``; ``bound`` edges at most."""
        used = 0
        while not cond():
            if used >= bound:
                last = self._state()
                self._record("cycle_wait", label, bound, "cycles", used, last, True)
                self._info(f"TIMEOUT-STATE site={label} bound={bound} cycles {last}")
                if fatal:
                    raise AssertionError(f"TIMEOUT {label}: bound={bound} cycles; {last}")
                return None
            await RisingEdge(self.dut.clk_smu_i)
            used += 1
        self._record("cycle_wait", label, bound, "cycles", used, f"cycle={self.mon.cyc}", False)
        return used

    async def _window(self, label: str, cycles: int, probes: dict) -> dict[str, int | None]:
        """An observation window of exactly ``cycles`` edges; the first edge each probe held."""
        first: dict[str, int | None] = {name: None for name in probes}
        start = self.mon.cyc
        for edge in range(1, cycles + 1):
            await RisingEdge(self.dut.clk_smu_i)
            for name, probe in probes.items():
                if first[name] is None and probe():
                    first[name] = edge
        outcome = " ".join(
            f"{name}={'none' if cyc is None else f'@{cyc}'}" for name, cyc in first.items()
        )
        self.windows.append(
            {"label": label, "length": cycles, "start": start, "outcome": outcome or "-"}
        )
        self._info(
            f"WINDOW site={label} length={cycles} clk_smu_i cycles from cycle {start} to "
            f"{self.mon.cyc}; outcome {outcome or '-'}; an observation, never a verdict"
        )
        return first

    def _since(self, mark: dict, ch: str, ids=None, key: str = "") -> list[dict]:
        events = self.mon.since(mark, ch)
        if ids is None:
            return events
        return [e for e in events if e[key] in ids]

    def _issue_read(self, addr: int, length: int, size: int, arid: int):
        return self.master.init_read(
            addr, length, size=size, prot=PROT_NONSECURE, burst=AXI_BURST_INCR, arid=arid
        )

    def _issue_write(self, addr: int, payload: bytes, size: int, awid: int):
        return self.master.init_write(
            addr, payload, size=size, prot=PROT_NONSECURE, burst=AXI_BURST_INCR, awid=awid
        )

    def _smc_view(self, local: int) -> int:
        return self.ports["smc_base"] + (local - SMC_APERTURE_LOCAL_BASE)

    def _pre(self, name: str, observed: dict, expected: dict) -> None:
        """A precondition compare; a failure is recorded and the run goes on."""
        try:
            self.sb.expect_eq(name, _kv(observed), _kv(expected))
        except AssertionError as exc:
            self.failures.append(str(exc))

    def _sep_in_row(self, sep: int | None) -> dict:
        sva = self.dut.u_xbar_sep_in_axi_sva
        row: dict[str, int | None] = {"cyc": self.mon.cyc, "sep_reset_n": sep}
        row.update({name: _val(getattr(sva, name)) for name in TRACE_PORTS})
        return row

    async def _level_watch(self) -> None:
        """sep_reset_n, the SEP rst_ni and the bench expectation window on every clk_smu_i edge.

        The SEP rst_ni is graded outside the cold resets. While a hold is armed
        the sep_in AR/R levels of the last TRACE_SPAN edges are kept; the edge
        that first samples sep_reset_n low is the fall, and TRACE_SPAN more
        edges complete the trace.
        """
        lv = self.lv
        dut = self.dut
        while lv["on"]:
            await RisingEdge(dut.clk_smu_i)
            cyc = self.mon.cyc
            sep = _val(dut.sep_reset_n_o)
            rst = _val(dut.obs_sep_rst_n_o)
            win = _val(dut.obs_sep_in_expect_window_open)
            if not lv["cold"]:
                lv["samples"] += 1
                if rst != 1:
                    lv["rst_ni_bad"].append((cyc, rst))
            armed = lv["armed"]
            if armed is not None:
                row = self._sep_in_row(sep)
                if sep == 0:
                    rec = self.holds[armed]
                    rec["fall"] = cyc
                    rec["trace"] = [*lv["pre"], row]
                    lv["pre"].clear()
                    lv["armed"] = None
                    lv["held"] = armed
                    lv["in_hold"] = armed
                    lv["after"] = 0
                else:
                    lv["pre"].append(row)
            elif lv["held"] is not None:
                rec = self.holds[lv["held"]]
                if lv["after"] < TRACE_SPAN:
                    rec["trace"].append(self._sep_in_row(sep))
                    lv["after"] += 1
                rec["hold_samples"] += 1
                if sep != 0:
                    rec["early"].append((cyc, sep))
            rising = lv["rising"]
            if rising is not None and sep == 1:
                self.holds[rising]["rise"] = cyc
                lv["rising"] = None
            if win != lv["win"]:
                (lv["opens"] if win == 1 else lv["closes"]).append((cyc, lv["in_hold"], win))
                lv["win"] = win

    # ------------------------------------------------------------------ JTAG

    async def _sba_write64(self, addr: int, data: int, label: str) -> None:
        await self._dmi_op(
            SBCS_ADDR, SBCS_SBACCESS_64 | SBCS_SBERROR_W1C, DMI_OP_WRITE, f"{label}_sbcs"
        )
        await self._dmi_op(SBADDRESS0_ADDR, addr, DMI_OP_WRITE, f"{label}_addr")
        await self._dmi_op(SBDATA1_ADDR, (data >> 32) & 0xFFFF_FFFF, DMI_OP_WRITE, f"{label}_d1")
        await self._dmi_op(SBDATA0_ADDR, data & 0xFFFF_FFFF, DMI_OP_WRITE, f"{label}_d0")
        await self._sba_wait(label)

    async def _program_inbound0(self, tag: str) -> list[int]:
        """SMC inbound filter entry 0 over the whole space, over JTAG2AXI."""
        statuses = []
        for addr, data, name in (
            (INBOUND0_START, 0, "start"),
            (INBOUND0_END, PASS_ALL_END, "end"),
            (INBOUND0_FILTER_CONFIG, PASS_RW_CONFIG, "config"),
        ):
            status, _ = await self._fabric(J2A_OP_WRITE, addr, data, f"{tag}_inbound0_{name}")
            statuses.append(status)
        return statuses

    async def _program_sep_aperture(self, tag: str) -> dict[str, int | None]:
        """SEP_GLOBAL_BASE_ADDR then SEP_REGION_SIZE (the window grows), then the ports."""
        await self._sba_write64(SEP_GLOBAL_BASE_ADDR, SEP_WIN_BASE, f"{tag}_sep_base")
        await self._sba_write64(SEP_REGION_SIZE_ADDR, SEP_WIN_SIZE, f"{tag}_sep_size")
        dut = self.dut
        await self._until(
            f"{tag}_sep_base_port",
            lambda: _val(dut.sep_xbar_global_base_o) == SEP_WIN_BASE,
            PORT_BOUND,
        )
        await self._until(
            f"{tag}_sep_size_port",
            lambda: _val(dut.sep_xbar_region_size_o) == SEP_WIN_SIZE,
            PORT_BOUND,
        )
        return self._ports()

    async def _posture(self, tag: str) -> tuple[int, int]:
        """Sensing done: lc_state left its pre-sense value and every debug path is open."""
        last = "no sample"
        lc = dbg = None
        for used in range(SENSE_BOUND + 1):
            lc = _val(self.dut.lc_state_o)
            dbg = _val(self.dut.lcc_dbg_disable_o)
            last = f"lc_state={_hx(lc)} dbg_disable={_hx(dbg)}"
            if lc is not None and lc != LC_STATE_PRESENSE and dbg == 0:
                self._record("sensing", tag, SENSE_BOUND, "cycles", used, last, False)
                return lc, dbg
            await RisingEdge(self.dut.clk_smu_i)
        self._record("sensing", tag, SENSE_BOUND, "cycles", SENSE_BOUND, last, True)
        raise AssertionError(f"TIMEOUT {tag} sensing: bound={SENSE_BOUND} cycles; {last}")

    async def _jtag_bringup(self, tag: str) -> int:
        self.jtag = jtag = make_smu_jtag_tap(self.dut, self.cfg.jtag_period_ns)
        self.selected = False
        self.ir_key = None
        await jtag.reset_tap()
        await jtag.goto_state(OcahJtagState.RUN_TEST_IDLE)
        idcode = await jtag.read_idcode()
        require_jtag_tdo_resolved(f"{tag} IDCODE")
        return idcode

    async def _setup_access(self, tag: str) -> dict:
        """Sensing, SMC inbound filter, debug module and the SEP aperture: S1 and S11."""
        idcode = await self._jtag_bringup(tag)
        lc, dbg = await self._posture(tag)
        security = _val(self.dut.tb_smc_jtag2axi_security_disable)
        statuses = await self._program_inbound0(tag)
        dmactive = await self._activate_debug_module(tag)
        ports = await self._program_sep_aperture(tag)
        return {
            "idcode": _hx(idcode),
            "lc_presense_left": lc != LC_STATE_PRESENSE,
            "dbg_disable": dbg,
            "j2a_security_disable": security,
            "inbound0_status": statuses,
            "dmactive": dmactive,
            "sep_base": _hx(ports["sep_base"]),
            "sep_size": _hx(ports["sep_size"]),
        }

    @staticmethod
    def _setup_expected() -> dict:
        return {
            "idcode": _hx(DTP_DEFAULT_IDCODE),
            "lc_presense_left": True,
            "dbg_disable": 0,
            "j2a_security_disable": 0,
            "inbound0_status": [J2A_STATUS_SUCCESS] * 3,
            "dmactive": 1,
            "sep_base": _hx(SEP_WIN_BASE),
            "sep_size": _hx(SEP_WIN_SIZE),
        }

    # ------------------------------------------------------------------ AXI

    async def _xfer(self, label: str, event, *, fatal: bool = True) -> int | None:
        return await self._until(label, event.is_set, XFER_BOUND, fatal=fatal)

    async def _sram_write_read(self, tag: str, addr: int, word: int, awid: int, arid: int):
        """A single-beat ext_in write and read-back of SEP SRAM, both bounded."""
        mon = self.mon
        mk = mon.mark()
        ok_w = await self._xfer(
            f"{tag}_write",
            self._issue_write(addr, word.to_bytes(8, "little"), SIZE_8B, awid),
            fatal=False,
        )
        b = self._since(mk, "b", {awid}, "bid")
        mk = mon.mark()
        ok_r = await self._xfer(
            f"{tag}_read", self._issue_read(addr, BEAT_BYTES, SIZE_8B, arid), fatal=False
        )
        r = self._since(mk, "r", {arid}, "rid")
        return {
            "w_done": ok_w is not None,
            "bresp": [_rn(x["bresp"]) for x in b],
            "r_done": ok_r is not None,
            "rresp": [_rn(x["rresp"]) for x in r],
            "rdata": [_hx(x["rdata"]) for x in r],
        }

    async def _version_lo(self, tag: str, arid: int, *, fatal: bool) -> dict:
        mk = self.mon.mark()
        addr = self._smc_view(SMC_CHIP_CONFIG_VERSION_LO)
        ok = await self._xfer(
            f"{tag}_version_lo", self._issue_read(addr, 4, SIZE_4B, arid), fatal=fatal
        )
        r = self._since(mk, "r", {arid}, "rid")
        return {
            "done": ok is not None,
            "rresp": [_rn(x["rresp"]) for x in r],
            "word": [_hx(_word(x["rdata"], addr)) for x in r],
        }

    async def _stop_after(
        self, chan, count, valid, ready, beats: int, label: str, *, extra=None, sink=False
    ):
        """Pause ``chan`` so the handshake that completes ``beats`` is its last.

        Decided at the falling edge before the rising edge that takes beat
        ``beats``. The W source reads ``pause`` at that edge, after the
        handshake, so WVALID drops behind beat ``beats``. The R sink drives
        RREADY from a ``pause`` it read one edge earlier, so for a ``sink`` the
        occupancy limit drops to one as well: the sink tests it at that edge
        with beat ``beats`` already queued and lowers RREADY at once, and
        ``pause`` keeps it low from the next edge on.
        """
        dut = self.dut
        for used in range(1, BEAT_BOUND + 1):
            await FallingEdge(dut.clk_smu_i)
            done = count()
            live = _val(valid) == 1 and _val(ready) == 1 and (extra is None or extra())
            if done >= beats or (done == beats - 1 and live):
                if sink:
                    chan.queue_occupancy_limit = 1
                chan.pause = True
                self._record("cycle_wait", label, BEAT_BOUND, "cycles", used, f"done={done}", False)
                return
        last = self._state()
        self._record("cycle_wait", label, BEAT_BOUND, "cycles", BEAT_BOUND, last, True)
        raise AssertionError(f"TIMEOUT {label}: bound={BEAT_BOUND} cycles; {last}")

    async def _cold_reset(self, tag: str = "S11") -> None:
        """rst_cold_ni as smu_xbar_zero_aperture_test drives it, each wait bounded."""
        dut = self.dut
        dut.rst_cold_ni.value = 0
        dut.jtag_trst.value = 0
        await self._until(
            f"{tag}_cold_reset_reaches_sep",
            lambda: _val(dut.obs_sep_rst_n_o) == 0,
            COLD_RESET_BOUND,
        )
        await ClockCycles(dut.clk_ref_i, COLD_RESET_HOLD)
        dut.rst_cold_ni.value = 1
        dut.jtag_trst.value = 1
        await self.test.jtag_tap_reset(16)
        self.selected = False
        self.ir_key = None
        await self._until(
            f"{tag}_sep_rst_ni_release", lambda: _val(dut.obs_sep_rst_n_o) == 1, COLD_RESET_BOUND
        )
        smc_reset = smc_primary_reset(dut)
        await self._until(
            f"{tag}_smc_primary_release", lambda: _val(smc_reset) == 1, COLD_RESET_BOUND
        )

    # ------------------------------------------------------------------ hold building blocks

    async def _fill(self, tag: str) -> list[str]:
        """The orphan's SEP SRAM block written, so no read of it returns X."""
        mk = self.mon.mark()
        await self._xfer(
            f"{tag}_fill_orphan_block",
            self._issue_write(ORPHAN_RD_ADDR, FILL_PATTERN, SIZE_8B, FILL_AWID),
        )
        return [_rn(x["bresp"]) for x in self._since(mk, "b", {FILL_AWID}, "bid")]

    def _r_channel(self):
        return self.master.driver.channels["r_ready_delay"]

    def _rready_restore(self) -> None:
        r_chan = self._r_channel()
        r_chan.queue_occupancy_limit = self.o["r_limit"]
        r_chan.pause = False

    async def _orphan(self, hold: str, step: str, *, write: bool) -> None:
        """ARID 0x11 256-beat read (and with ``write`` AWID 0x12 256-beat write), 4 beats each."""
        dut = self.dut
        mon = self.mon
        rec = self.holds[hold] = {
            "fall": None,
            "rise": None,
            "early": [],
            "hold_samples": 0,
            "trace": [],
            "write": write,
        }
        drv = self.master.driver
        clear_profile(drv)
        r_chan = drv.channels["r_ready_delay"]
        w_chan = drv.channels["w_delay"]
        self.o["r_limit"] = r_chan.queue_occupancy_limit
        c0 = self._counts()
        mk = mon.mark()
        rec["mk"] = mk
        rec["c0"] = c0
        self._issue_read(ORPHAN_RD_ADDR, ORPHAN_BEATS * BEAT_BYTES, SIZE_8B, ORPHAN_ARID)
        if write:
            self._issue_write(ORPHAN_WR_ADDR, ORPHAN_WR_PATTERN, SIZE_8B, ORPHAN_AWID)
        stops = [
            cocotb.start_soon(
                self._stop_after(
                    r_chan,
                    lambda: len(self._since(mk, "r", {ORPHAN_ARID}, "rid")),
                    dut.ext_in_rvalid,
                    dut.ext_in_rready,
                    ORPHAN_HELD_AFTER,
                    f"{step}_rready_drop",
                    extra=lambda: _val(dut.ext_in_rid) == ORPHAN_ARID,
                    sink=True,
                )
            )
        ]
        if write:
            stops.append(
                cocotb.start_soon(
                    self._stop_after(
                        w_chan,
                        lambda: len(self._since(mk, "w")),
                        dut.ext_in_wvalid,
                        dut.ext_in_wready,
                        ORPHAN_HELD_AFTER,
                        f"{step}_wvalid_stop",
                    )
                )
            )
        for stop in stops:
            await stop
        await self._until(
            f"{step}_four_beats",
            lambda: (
                len(self._since(mk, "r", {ORPHAN_ARID}, "rid")) >= ORPHAN_HELD_AFTER
                and (not write or len(self._since(mk, "w")) >= ORPHAN_HELD_AFTER)
            ),
            BEAT_BOUND,
        )
        await self._until(
            f"{step}_sep_in_ar_tap",
            lambda: (_val(dut.sep_xbar_in_ar_count_o) or 0) > (c0["sep_xbar_in_ar_count_o"] or 0),
            XFER_BOUND,
        )
        if write:
            await self._until(
                f"{step}_sep_in_aw_count",
                lambda: (
                    (_val(dut.sep_xbar_in_aw_count_o) or 0) > (c0["sep_xbar_in_aw_count_o"] or 0)
                ),
                XFER_BOUND,
            )
        c1 = self._counts()
        rec["c1"] = c1
        r = self._since(mk, "r", {ORPHAN_ARID}, "rid")
        w = self._since(mk, "w")
        self._info(
            f"{step} hold={hold} orphan sep_in ar_tap_delta="
            f"{self._delta(c0, c1, 'sep_xbar_in_ar_count_o')} "
            f"aw_delta={self._delta(c0, c1, 'sep_xbar_in_aw_count_o')} "
            f"ar_tap_addr={_hx(_val(dut.sep_xbar_in_ar_addr_o))} "
            f"r_hs_cycles={_ranges([x['cyc'] for x in r])} "
            f"w_hs_cycles={_ranges([x['cyc'] for x in w])} rready={_val(dut.ext_in_rready)} "
            f"wvalid={_val(dut.ext_in_wvalid)}"
        )

    def _before_fall(self, hold: str) -> dict:
        """The orphan's handshakes up to the fall of sep_reset_n."""
        rec = self.holds[hold]
        mk, fall = rec["mk"], rec["fall"]
        r = [x for x in self._since(mk, "r", {ORPHAN_ARID}, "rid") if x["cyc"] <= fall]
        w = [x for x in self._since(mk, "w") if x["cyc"] <= fall]
        b = [x for x in self._since(mk, "b", {ORPHAN_AWID}, "bid") if x["cyc"] <= fall]
        return {
            "sep_in_ar_tap_delta": self._delta(rec["c0"], rec["c1"], "sep_xbar_in_ar_count_o"),
            "r_beats_before_fall": len(r),
            "rlast_before_fall": sum(1 for x in r if x["rlast"] == 1),
            "w_beats_before_fall": len(w),
            "b_before_fall": len(b),
        }

    async def _hold(self, hold: str, step: str) -> None:
        """The IC_RESET SEP slice drives sep_reset_n low; reset nets, aperture and sep_in trace."""
        rec = self.holds[hold]
        lv = self.lv
        lv["pre"].clear()
        lv["armed"] = hold
        await self._ic_reset(SEP_STAGED, f"{step}_sep_staged")
        await self._ic_reset(SEP_HELD, f"{step}_sep_held")
        await self._until(f"{step}_sep_reset_fall", lambda: rec["fall"] is not None, LEVEL_BOUND)
        nets = self._nets()
        ports = self._ports()
        rec["nets"] = nets
        rec["ports"] = ports
        self.log.info(
            "OBS-HELD-XBAR-RESET: hold=%s cycle=%d sep_reset_n_o=%s obs_sep_rst_n_o=%s "
            "obs_xbar_rst_n_o=%s rst_primary_smc_clk_n_o=%s converter_rst_n=%s (the SMU-side "
            "10-to-6-bit ID-width converter on the sep_in path is on the crossbar reset net; "
            "only the SEP-side ID truncation is behind sep_reset_no)",
            hold,
            self.mon.cyc,
            _hx(nets["sep_reset_n_o"]),
            _hx(nets["obs_sep_rst_n_o"]),
            _hx(nets["obs_xbar_rst_n_o"]),
            _hx(nets["rst_primary_smc_clk_n_o"]),
            _hx(nets["obs_xbar_rst_n_o"]),
        )
        self.log.info(
            "OBS-HELD-APERTURE: hold=%s cycle=%d sep_xbar_global_base_o=%s "
            "sep_xbar_region_size_o=%s programmed=(%s,%s) rdl_reset=(%s,%s)",
            hold,
            self.mon.cyc,
            _hx(ports["sep_base"]),
            _hx(ports["sep_size"]),
            _hx(SEP_WIN_BASE),
            _hx(SEP_WIN_SIZE),
            _hx(SEP_GLOBAL_BASE_RESET),
            _hx(SEP_REGION_SIZE_RESET),
        )
        await self._until(f"{step}_sep_in_trace", lambda: lv["after"] >= TRACE_SPAN, TRACE_SPAN + 2)
        self._sep_in_report(hold)
        rec["obs"] = True
        self._ctrl(f"HOLD_{hold}")

    def _sep_in_report(self, hold: str) -> None:
        """The sep_in AR/R levels around the fall, and the R beat withdrawn at it.

        A VALID that drops with its READY low and no handshake is withdrawn
        (IHI0022 A3.2.1). Here the source is the SEP side of sep_in under the
        debug override, which performs no isolation; it is recorded, not graded.
        """
        rec = self.holds[hold]
        fall = rec["fall"]
        trace = rec["trace"]
        for row in trace:
            fields = " ".join(
                f"{k}={_hx(v)}" for k, v in row.items() if k not in ("cyc", "sep_reset_n")
            )
            self._info(
                f"SEPIN-TRACE hold={hold} rel={row['cyc'] - fall:+d} cycle={row['cyc']} "
                f"sep_reset_n={_bit(row['sep_reset_n'])} {fields}"
            )
        before = next((r for r in reversed(trace) if r["cyc"] < fall), None)
        at = next((r for r in trace if r["cyc"] == fall), None)
        empty: dict = {}
        before = before or empty
        at = at or empty
        payload = ("rid", "rdata", "rresp", "rlast")
        withdrawn = (
            before.get("rvalid") == 1 and before.get("rready") == 0 and at.get("rvalid") != 1
        )
        changed = before.get("rvalid") == 1 and any(before.get(k) != at.get(k) for k in payload)
        rec["withdrawn"] = withdrawn
        self.log.info(
            "OBS-SEPIN-WITHDRAWN: hold=%s cycle_fall=%d rvalid_before=%s rvalid_after=%s "
            "rready=%s rid=%s withdrawn=%s payload_changed=%s aresetn=%s ruling=#2891",
            hold,
            fall,
            _bit(before.get("rvalid")),
            _bit(at.get("rvalid")),
            _bit(before.get("rready")),
            _hx(before.get("rid")),
            withdrawn,
            changed,
            _bit(at.get("aresetn")),
        )

    def _queued_ahead(self, hold: str) -> dict:
        """ext_in requests issued since the orphan of ``hold`` other than the orphan itself."""
        rec = self.holds[hold]
        ar = self._since(rec["mk"], "ar")
        aw = self._since(rec["mk"], "aw")
        other_ar = [(_hx(e["arid"]), _hx(e["araddr"])) for e in ar]
        if ar and ar[0]["arid"] == ORPHAN_ARID:
            other_ar = other_ar[1:]
        other_aw = [(_hx(e["awid"]), _hx(e["awaddr"])) for e in aw if e["awid"] != ORPHAN_AWID]
        levels = self.mon.levels.get("ar", (None, None))
        return {"ar": other_ar, "aw": other_aw, "arvalid_pending": levels[0] == 1}

    def _completions(self, hold: str, since_cyc: int) -> dict:
        """Per request group of ``hold``: RLAST / B ends since its orphan and after ``since_cyc``."""
        mk = self.holds[hold]["mk"]
        r = self._since(mk, "r")
        b = self._since(mk, "b")
        groups = {
            "orphan_rd_0x11": ("r", {ORPHAN_ARID}),
            "orphan_wr_0x12": ("b", {ORPHAN_AWID}),
            "diff_0x21_0x24": ("r", set(DIFF_ARIDS)),
            "during_rd_0x31": ("r", {DURING_ARID}),
            "during_wr_0x32": ("b", {DURING_AWID}),
            "same_id_0x41": ("r", {SAME_ARID}),
            "distinct_0x50_0x67": ("r", set(DISTINCT_ARIDS)),
        }
        out = {}
        for name, (ch, ids) in groups.items():
            if ch == "r":
                ends = [x for x in r if x["rid"] in ids and x["rlast"] == 1]
            else:
                ends = [x for x in b if x["bid"] in ids]
            if ends:
                out[name] = (len(ends), sum(1 for x in ends if x["cyc"] > since_cyc))
        return out

    async def _release(self, hold: str, step: str) -> None:
        """The slice scanned back, a 20000-cycle window, then a fresh SEP SRAM write and read."""
        dut = self.dut
        mon = self.mon
        lv = self.lv
        rec = self.holds[hold]
        self._step(step, f"hold {hold} release: reset_enable 1 first, then reset_control 1")
        lv["held"] = None
        lv["rising"] = hold
        await self._ic_reset(SEP_STAGED, f"{step}_release_enable")
        await self._until(f"{step}_sep_reset_rise", lambda: rec["rise"] is not None, LEVEL_BOUND)
        await self._until(
            f"{step}_expect_window_close", lambda: lv["win"] == 0, WINDOW_CLOSE_BOUND, fatal=False
        )
        lv["in_hold"] = None
        await self._ic_reset(ALL_ONES, f"{step}_release_control")
        release = mon.cyc
        r_at_release = len(mon.events["r"])
        if hold == "A":
            self._ctrl("RELEASED_A")
        reset_seen = (rec["ports"]["sep_base"], rec["ports"]["sep_size"]) != (
            SEP_WIN_BASE,
            SEP_WIN_SIZE,
        )
        self._info(
            f"{step} hold={hold} sep_reset_n rose at cycle {rec['rise']}; aperture at the fall "
            f"{rec['ports']} reset_seen={reset_seen}; Test-Logic-Reset and the STAP re-select "
            "reach the debug module again"
        )
        await self._tlr()
        dmactive = await self._activate_debug_module(step.lower())
        self._pre(
            f"{step} debug module active after the release", {"dmactive": dmactive}, {"dmactive": 1}
        )
        if reset_seen:
            ports = await self._program_sep_aperture(step.lower())
            self._info(f"{step} SEP aperture re-programmed ports={ports}")
        await self._window(
            f"{step}_held_completions",
            OBS_WINDOW,
            {
                "orphan_rlast": lambda: any(
                    x["rid"] == ORPHAN_ARID and x["rlast"] == 1
                    for x in mon.events["r"][r_at_release:]
                )
            },
        )
        done = self._completions(hold, release)
        self._info(
            f"{step} hold={hold} held requests (ends since the orphan, of which after the "
            f"release at cycle {release}): {done or 'none'}"
        )
        pre_after = _val(dut.sep_reset_n_o)
        mk = mon.mark()
        self._issue_write(AFTER_ADDR, AFTER_WORD.to_bytes(8, "little"), SIZE_8B, AFTER_AWID)
        await self._window(
            f"{step}_fresh_write",
            OBS_WINDOW,
            {"b_0x71": lambda: bool(self._since(mk, "b", {AFTER_AWID}, "bid"))},
        )
        b = self._since(mk, "b", {AFTER_AWID}, "bid")
        mk2 = mon.mark()
        self._issue_read(AFTER_ADDR, BEAT_BYTES, SIZE_8B, AFTER_ARID)
        await self._window(
            f"{step}_fresh_read",
            OBS_WINDOW,
            {"r_0x72": lambda: bool(self._since(mk2, "r", {AFTER_ARID}, "rid"))},
        )
        r = self._since(mk2, "r", {AFTER_ARID}, "rid")
        self.log.info(
            "OBS-FRESH-AFTER: hold=%s sep_reset_n_o=%s addr=0x%x awid=0x%x b=%s arid=0x%x r=%s "
            "written=0x%016x window=%d each",
            hold,
            _hx(pre_after),
            AFTER_ADDR,
            AFTER_AWID,
            [(_rn(x["bresp"]), x["cyc"]) for x in b] or "none",
            AFTER_ARID,
            [(_rn(x["rresp"]), _hx(x["rdata"]), x["cyc"]) for x in r] or "none",
            AFTER_WORD,
            OBS_WINDOW,
        )
        rec["restored"] = [_rn(x["bresp"]) for x in b] == [_rn(RESP_OKAY)] and [
            (_rn(x["rresp"]), x["rdata"]) for x in r
        ] == [(_rn(RESP_OKAY), AFTER_WORD)]
        rec["after"] = {
            "pre": pre_after,
            "x": sum(1 for x in r if x["rresp"] is None) + sum(1 for x in b if x["bresp"] is None),
        }

    async def _clear(self, hold: str, step: str) -> None:
        """rst_cold_ni, the S1 programming again, then the post-cold-reset accesses CHK-CLEAR grades."""
        rec = self.holds[hold]
        lv = self.lv
        self._step(
            step, f"hold {hold} clear: rst_cold_ni, the S1 programming, fresh SEP SRAM, VERSION_LO"
        )
        lv["cold"] = True
        await self._cold_reset(step)
        lv["cold"] = False
        setup = await self._setup_access(step.lower())
        self.ports = self._ports()
        self._info(f"{step} setup {_kv(setup)} ports={self.ports}")
        self._pre(f"{step} setup access path open", setup, self._setup_expected())
        sram = await self._sram_write_read(
            f"{step}_sram", COLD_ADDR, cold_word(hold), COLD_AWID, COLD_ARID
        )
        smc = await self._version_lo(step, COLD_SMC_ARID, fatal=False)
        self.log.info(
            "OBS-CLEARED-BY: hold=%s release_alone_restored_okay=%s (fresh write and read-back "
            "after the release); after rst_cold_ni sram=%s version_lo=%s",
            hold,
            rec["restored"],
            sram,
            smc,
        )
        rec["clear"] = {"sram": sram, "smc": smc}
        if sram["w_done"] and sram["r_done"] and smc["done"]:
            self._ctrl(f"COLD_{hold}")

    # ------------------------------------------------------------------ steps

    async def _s1_setup(self) -> None:
        dut = self.dut
        sb = self.sb
        await self.cfg.reset_done.wait()
        self.mon = _ExtInMonitor(dut)
        await RisingEdge(dut.clk_smu_i)
        self._step("S1", "SEP aperture, SMC inbound filter, baseline, counters")
        self._info(f"SEED: RANDOM_SEED={self.seed} (every draw of this leaf is directed)")
        sb.expect_eq("S1 SEP=1 build with the crossbar elaborated", _val(dut.sep_enabled_o), 1)
        self.lv["on"] = True
        cocotb.start_soon(self._level_watch())
        setup = await self._setup_access("s1")
        self._info(f"S1 setup {_kv(setup)}")
        sb.expect_eq("S1 setup access path open", _kv(setup), _kv(self._setup_expected()))
        self.ports = self._ports()
        self.master = await make_smu_axi_master(dut, dut.clk_smu_i, smc_primary_reset(dut))
        clear_profile(self.master.driver)

        mon = self.mon
        fill_b = await self._fill("S1")
        mk = mon.mark()
        await self._xfer(
            "S1_baseline_sep_read",
            self._issue_read(ORPHAN_RD_ADDR, BEAT_BYTES, SIZE_8B, BASE_SEP_ARID),
        )
        sep_r = self._since(mk, "r", {BASE_SEP_ARID}, "rid")
        smc = await self._version_lo("S1_baseline", BASE_SMC_ARID, fatal=True)
        self.o["c_s1"] = self._counts()
        self._info(
            f"S1 baseline fill_b={fill_b} "
            f"sep_r={[(_rn(x['rresp']), _hx(x['rdata'])) for x in sep_r]} smc={smc} "
            f"counters={self.o['c_s1']} ports={self.ports}"
        )
        sb.expect_eq(
            "S1 baseline the SEP SRAM block and VERSION_LO answer OKAY on ext_in",
            (fill_b, [_rn(x["rresp"]) for x in sep_r], smc["rresp"]),
            ([_rn(RESP_OKAY)], [_rn(RESP_OKAY)], [_rn(RESP_OKAY)]),
        )
        self._ctrl("BASELINE_OK")
        self.steps["S1"] = True

    async def _s2_orphan(self) -> None:
        self._step("S2", "hold A orphan: read ARID 0x11 and write AWID 0x12, 4 beats each")
        await self._orphan("A", "S2", write=True)
        self._ctrl("ORPHAN_A")
        self.steps["S2"] = True

    async def _s3_hold(self) -> None:
        self._step("S3", "hold A: IC_RESET SEP slice reset_control 0, then reset_enable 0")
        await self._hold("A", "S3")
        self.steps["S3"] = True

    async def _s4_orphan_fate(self) -> None:
        mon = self.mon
        rec = self.holds["A"]
        self._step("S4", "RREADY rises, the 252 remaining W beats resume, 20000 cycles")
        before = self._before_fall("A")
        mk4 = mon.mark()
        self._rready_restore()
        self.master.driver.channels["w_delay"].pause = False
        await self._window(
            "S4_orphan",
            OBS_WINDOW,
            {
                "orphan_rlast": lambda: any(
                    x["rlast"] == 1 for x in self._since(mk4, "r", {ORPHAN_ARID}, "rid")
                ),
                "orphan_b": lambda: bool(self._since(mk4, "b", {ORPHAN_AWID}, "bid")),
            },
        )
        r_after = self._since(mk4, "r", {ORPHAN_ARID}, "rid")
        w_after = self._since(mk4, "w")
        b_after = self._since(mk4, "b", {ORPHAN_AWID}, "bid")
        rlast = [x["cyc"] for x in r_after if x["rlast"] == 1]
        if r_after:
            self.log.info(
                "OBS-ORPHAN-RD: arid=0x%x remaining_beats=%d of %d rlast_cycles=%s rresp=%s "
                "r_hs_cycles=%s window=%d",
                ORPHAN_ARID,
                len(r_after),
                ORPHAN_BEATS - ORPHAN_HELD_AFTER,
                rlast or "none",
                _codes(r_after, "rresp"),
                _ranges([x["cyc"] for x in r_after]),
                OBS_WINDOW,
            )
        else:
            self.log.info(
                "OBS-ORPHAN-RD: arid=0x%x none within %d cycles (remaining beats, RLAST)",
                ORPHAN_ARID,
                OBS_WINDOW,
            )
        if w_after or b_after:
            self.log.info(
                "OBS-ORPHAN-WR: awid=0x%x w_beats_accepted=%d of %d wlast_at=%s b=%s window=%d",
                ORPHAN_AWID,
                len(w_after),
                ORPHAN_BEATS - ORPHAN_HELD_AFTER,
                [i for i, x in enumerate(w_after) if x["wlast"] == 1] or "none",
                [(_rn(x["bresp"]), _hx(x["bid"]), x["cyc"]) for x in b_after] or "none",
                OBS_WINDOW,
            )
        else:
            self.log.info(
                "OBS-ORPHAN-WR: awid=0x%x none within %d cycles (W beats, B)",
                ORPHAN_AWID,
                OBS_WINDOW,
            )
        self._info(f"S4 aperture at the window end {self._ports()}")
        observed_x = sum(1 for x in r_after if None in (x["rresp"], x["rid"], x["rlast"])) + sum(
            1 for x in b_after if None in (x["bresp"], x["bid"])
        )
        self._grade(
            "CHK-ORPHAN-OBS",
            {
                **before,
                "sep_in_aw_delta": self._delta(rec["c0"], rec["c1"], "sep_xbar_in_aw_count_o"),
                "x_on_observed": observed_x,
            },
            {
                "sep_in_ar_tap_delta": 1,
                "r_beats_before_fall": ORPHAN_HELD_AFTER,
                "rlast_before_fall": 0,
                "w_beats_before_fall": ORPHAN_HELD_AFTER,
                "b_before_fall": 0,
                "sep_in_aw_delta": 1,
                "x_on_observed": 0,
            },
            f"the hold A orphan reached sep_in and held at 4 R and 4 W beats when sep_reset_n "
            f"fell at cycle {rec['fall']}; its fate is OBS-ORPHAN-RD / OBS-ORPHAN-WR",
        )
        self._ctrl("ORPHAN_OBSERVED")
        self.steps["S4"] = True

    async def _s5_diff_id(self) -> None:
        dut = self.dut
        mon = self.mon
        self._step("S5", "ARIDs 0x21..0x24 single reads of SMC VERSION_LO one after another")
        addr = self._smc_view(SMC_CHIP_CONFIG_VERSION_LO)
        ahead = self._queued_ahead("A")
        self._info(
            f"S5 precondition since the orphan AR: other ext_in AR={ahead['ar'] or 'none'} "
            f"other AW={ahead['aw'] or 'none'} arvalid_pending={ahead['arvalid_pending']}"
        )
        c0 = self._counts()
        per_id: dict[str, list] = {}
        used_per_id: dict[str, int | None] = {}
        for arid in DIFF_ARIDS:
            mk = mon.mark()
            self._issue_read(addr, 4, SIZE_4B, arid)
            used = await self._until(
                f"S5_diff_id_0x{arid:x}",
                lambda arid=arid, mk=mk: any(
                    x["rlast"] == 1 for x in self._since(mk, "r", {arid}, "rid")
                ),
                DIFF_BOUND,
                fatal=False,
            )
            r = self._since(mk, "r", {arid}, "rid")
            used_per_id[_hx(arid)] = used
            per_id[_hx(arid)] = [
                (_rn(x["rresp"]), _hx(x["rid"]), _hx(_word(x["rdata"], addr))) for x in r
            ]
        c1 = self._counts()
        self._info(f"S5 completed_in={used_per_id} sep_reset_n_o={_hx(_val(dut.sep_reset_n_o))}")
        done = all(u is not None for u in used_per_id.values())
        self._grade(
            "CHK-DIFFID-LIVE",
            {
                "no_same_id_or_sep_in_request_ahead": ahead
                == {"ar": [], "aw": [], "arvalid_pending": False},
                "completed_within_bound": done,
                "per_id": per_id,
                "smc_in_ar_delta": self._delta(c0, c1, "smc_xbar_in_ar_count_o"),
            },
            {
                "no_same_id_or_sep_in_request_ahead": True,
                "completed_within_bound": True,
                "per_id": {
                    _hx(arid): [(_rn(RESP_OKAY), _hx(arid), _hx(SMC_CHIP_CONFIG_VERSION_LO_RESET))]
                    for arid in DIFF_ARIDS
                },
                "smc_in_ar_delta": len(DIFF_ARIDS),
            },
            f"with no ARID 0x11 and no sep_in-bound request issued since the orphan, each of "
            f"ARID 0x21..0x24 completes within {DIFF_BOUND} cycles OKAY with RID=ARID and the "
            "VERSION_LO RDL reset value; smc_in counts four ARs",
        )
        if done:
            self._ctrl("DIFFID_DONE")
        self.steps["S5"] = True

    async def _s6_fresh_during(self) -> None:
        dut = self.dut
        mon = self.mon
        self._step("S6", "ARID 0x31 read and AWID 0x32 write at SEP global 0x1000 during the hold")
        pre = _val(dut.sep_reset_n_o)
        mk = mon.mark()
        self._issue_read(DURING_ADDR, BEAT_BYTES, SIZE_8B, DURING_ARID)
        self._issue_write(DURING_ADDR, DURING_WORD.to_bytes(8, "little"), SIZE_8B, DURING_AWID)
        await self._window(
            "S6_fresh_during",
            OBS_WINDOW,
            {
                "ar_0x31": lambda: bool(self._since(mk, "ar", {DURING_ARID}, "arid")),
                "r_0x31": lambda: bool(self._since(mk, "r", {DURING_ARID}, "rid")),
                "aw_0x32": lambda: bool(self._since(mk, "aw", {DURING_AWID}, "awid")),
                "b_0x32": lambda: bool(self._since(mk, "b", {DURING_AWID}, "bid")),
            },
        )
        ar = self._since(mk, "ar", {DURING_ARID}, "arid")
        r = self._since(mk, "r", {DURING_ARID}, "rid")
        aw = self._since(mk, "aw", {DURING_AWID}, "awid")
        b = self._since(mk, "b", {DURING_AWID}, "bid")
        self.log.info(
            "OBS-FRESH-DURING: sep_reset_n_o=%s addr=0x%x arid=0x%x ar_hs=%s r=%s awid=0x%x "
            "aw_hs=%s w_hs_since_issue=%d b=%s window=%d",
            _hx(pre),
            DURING_ADDR,
            DURING_ARID,
            [x["cyc"] for x in ar] or "none",
            [(_rn(x["rresp"]), _hx(x["rdata"]), x["cyc"]) for x in r] or "none",
            DURING_AWID,
            [x["cyc"] for x in aw] or "none",
            len(self._since(mk, "w")),
            [(_rn(x["bresp"]), x["cyc"]) for x in b] or "none",
            OBS_WINDOW,
        )
        self.o["during"] = {
            "pre": pre,
            "x": sum(1 for x in r if x["rresp"] is None) + sum(1 for x in b if x["bresp"] is None),
        }
        self._ctrl("FRESH_DURING")
        self.steps["S6"] = True

    async def _s7_release(self) -> None:
        await self._release("A", "S7")
        during = self.o["during"]
        after = self.holds["A"]["after"]
        self._grade(
            "CHK-FRESH-OBS",
            {
                "sep_reset_n_during": during["pre"],
                "sep_reset_n_after": after["pre"],
                "x_on_observed": during["x"] + after["x"],
            },
            {
                "sep_reset_n_during": 0,
                "sep_reset_n_after": 1,
                "x_on_observed": 0,
            },
            "OBS-FRESH-DURING with sep_reset_n 0 at issue and OBS-FRESH-AFTER with sep_reset_n 1 "
            "at issue are logged for hold A",
        )
        self.steps["S7"] = True

    async def _s8_clear(self) -> None:
        await self._clear("A", "S8")
        self.steps["S8"] = True

    async def _orphan_and_hold(self, hold: str, step: str) -> None:
        """The S2 read orphan only, then the S3 hold, then RREADY back up."""
        self._step(step, f"hold {hold}: read orphan ARID 0x11 (4 beats), then the IC_RESET hold")
        fill_b = await self._fill(step)
        self._pre(f"{step} orphan block written", {"bresp": fill_b}, {"bresp": [_rn(RESP_OKAY)]})
        await self._orphan(hold, step, write=False)
        await self._hold(hold, step)
        before = self._before_fall(hold)
        self._rready_restore()
        self._info(f"{step} hold={hold} orphan before the fall {_kv(before)}; RREADY raised")
        self._pre(
            f"{step} hold {hold} orphan accepted at sep_in, 4 beats, no RLAST before the fall",
            {k: before[k] for k in ("sep_in_ar_tap_delta", "r_beats_before_fall")}
            | {"rlast_before_fall": before["rlast_before_fall"]},
            {
                "sep_in_ar_tap_delta": 1,
                "r_beats_before_fall": ORPHAN_HELD_AFTER,
                "rlast_before_fall": 0,
            },
        )
        self.steps[step] = True

    async def _s10_same_id(self) -> None:
        dut = self.dut
        mon = self.mon
        self._step("S10", "ARID 0x11 single read of SMC VERSION_LO with the hold B orphan open")
        c0 = self._counts()
        mk = mon.mark()
        self.o["mk_sameid"] = mk
        issue = mon.cyc
        self._issue_read(self._smc_view(SMC_CHIP_CONFIG_VERSION_LO), 4, SIZE_4B, ORPHAN_ARID)
        base_ar = c0["smc_xbar_in_ar_count_o"]
        first = await self._window(
            "S10_same_id",
            OBS_WINDOW,
            {
                "ext_in_ar": lambda: bool(self._since(mk, "ar", {ORPHAN_ARID}, "arid")),
                "smc_in_ar": lambda: (_val(dut.smc_xbar_in_ar_count_o) or 0) > (base_ar or 0),
                "r_0x11": lambda: bool(self._since(mk, "r", {ORPHAN_ARID}, "rid")),
            },
        )
        c1 = self._counts()
        r = self._since(mk, "r", {ORPHAN_ARID}, "rid")
        ar = self._since(mk, "ar", {ORPHAN_ARID}, "arid")
        ar_cyc = ar[0]["cyc"] if ar else None
        orphan_rlast = [
            x["cyc"]
            for x in self._since(self.holds["B"]["mk"], "r", {ORPHAN_ARID}, "rid")
            if x["rlast"] == 1 and ar_cyc is not None and x["cyc"] <= ar_cyc
        ]
        self.o["sameid_ar"] = {
            "s10_ar_handshakes_on_ext_in": len(ar),
            "orphan_rlast_by_s10_ar": orphan_rlast if ar_cyc is not None else "no S10 AR",
        }
        self._info(
            f"S10 sample: ext_in AR handshakes of ARID 0x11 since the S10 issue={len(ar)} "
            f"first at cycle {ar_cyc}; ARID 0x11 RLAST beats since the hold B orphan up to that "
            f"cycle={self.o['sameid_ar']['orphan_rlast_by_s10_ar']}"
        )
        self.log.info(
            "OBS-SAMEID-HELD: arid=0x%x issued_cycle=%d ext_in_ar_accepted=%s smc_in_ar=%s "
            "smc_in_ar_delta=%s r_beats=%d rlast_beats=%d r=%s window=%d (beats without RLAST "
            "are the orphan's, RREADY having risen after the hold)",
            ORPHAN_ARID,
            issue,
            "none" if first["ext_in_ar"] is None else f"+{first['ext_in_ar']}",
            f"none within {OBS_WINDOW} cycles"
            if first["smc_in_ar"] is None
            else f"+{first['smc_in_ar']}",
            self._delta(c0, c1, "smc_xbar_in_ar_count_o"),
            len(r),
            sum(1 for x in r if x["rlast"] == 1),
            [(_rn(x["rresp"]), _hx(x["rlast"]), x["cyc"]) for x in r] or "none",
            OBS_WINDOW,
        )
        self.o["obs_sameid"] = True
        self._ctrl("SAMEID_OBSERVED")
        self.steps["S10"] = True

    async def _s11_other_initiator(self) -> None:
        dut = self.dut
        self._step("S11", "JTAG2AXI read at 0x8000_0000 (smc_out) while the S10 read is held")
        ports = self._ports()
        outside = None not in ports.values() and not any(
            base <= OTHER_INIT_ADDR < base + size
            for base, size in (
                (ports["sep_base"], ports["sep_size"]),
                (ports["smc_base"], ports["smc_size"]),
            )
        )
        s10_held = not any(
            x["rlast"] == 1 for x in self._since(self.o["mk_sameid"], "r", {ORPHAN_ARID}, "rid")
        )
        arvalid, arready = _val(dut.ext_in_arvalid), _val(dut.ext_in_arready)
        c0 = self._counts()
        raw = pack_single_op(J2A_OP_READ, OTHER_INIT_ADDR, 0, wstrb=0, size=SMC_DBG_AXSIZE_8B)
        await self._dr(DTP_IR_SMC_AXI_SINGLE_OP, raw, SMC_DBG_SINGLE_OP_LEN, "s11_j2a_issue")
        status, rdata, used = J2A_STATUS_BUSY, 0, 0
        for used in range(1, J2A_OBS_CAPTURES + 1):
            captured, _ = await self._dr(
                DTP_IR_SMC_AXI_SINGLE_OP,
                0,
                SMC_DBG_SINGLE_OP_LEN,
                f"s11_j2a_c{used}",
                counted=used == 1,
            )
            status, rdata = unpack_single_op(captured)
            if status != J2A_STATUS_BUSY:
                break
            await ClockCycles(dut.clk_smu_i, CAPTURE_POLL_CLK)
        c1 = self._counts()
        self.windows.append(
            {
                "label": "S11_j2a_status",
                "length": J2A_OBS_CAPTURES,
                "start": self.mon.cyc,
                "outcome": f"status={status} captures={used}",
            }
        )
        self._info(
            f"WINDOW site=S11_j2a_status length={J2A_OBS_CAPTURES} captures used={used} "
            f"status={status}; an observation, never a verdict"
        )
        self.log.info(
            "OBS-OTHER-INITIATOR: addr=0x%x j2a_status=%d (%s) rdata=0x%x captures=%d "
            "smu_axi_out_read_count_delta=%s ext_in_arvalid=%s ext_in_arready=%s at issue "
            "s10_read_held=%s",
            OTHER_INIT_ADDR,
            status,
            "busy" if status == J2A_STATUS_BUSY else "complete",
            rdata,
            used,
            self._delta(c0, c1, "smu_axi_out_read_count_o"),
            _hx(arvalid),
            _hx(arready),
            s10_held,
        )
        self._grade(
            "CHK-OTHER-INIT-OBS",
            {
                "s10_read_held_at_issue": s10_held,
                "addr_outside_both_apertures": outside,
            },
            {
                "s10_read_held_at_issue": True,
                "addr_outside_both_apertures": True,
            },
            "the JTAG2AXI smc_out read was issued while the S10 same-ID read was held (no RLAST "
            "beat returned for it); its status, the smu_axi_out read delta and the ext_in "
            "ARVALID / ARREADY levels at issue are OBS-OTHER-INITIATOR",
        )
        self._ctrl("OTHER_INIT")
        self.steps["S11"] = True

    async def _s12_release_clear(self) -> None:
        await self._release("B", "S12")
        sameid = self.o["mk_sameid"]
        ones = self._since(self.holds["B"]["mk"], "r", {ORPHAN_ARID}, "rid")
        early_last = [i for i, x in enumerate(ones) if x["rlast"] == 1 and i < ORPHAN_BEATS - 1]
        orphan_last = ones[ORPHAN_BEATS - 1]["cyc"] if len(ones) >= ORPHAN_BEATS else None
        later = self._since(sameid, "r", {ORPHAN_ARID}, "rid")
        self._info(
            f"S12 ARID 0x11 beats since the hold B orphan={len(ones)} "
            f"orphan_rlast_cycle={orphan_last} beats_since_S10={len(later)} "
            f"rlast_before_beat_256={early_last}"
        )
        self._grade(
            "CHK-SAMEID-NO-OVERTAKE",
            {
                **self.o.get("sameid_ar", {"s10_ar_handshakes_on_ext_in": "not run"}),
                "single_beat_rlast_before_orphan_rlast": early_last,
                "x_on_rid_rresp": sum(1 for x in later if None in (x["rid"], x["rresp"])),
                "obs_line": self.o.get("obs_sameid", False),
            },
            {
                "s10_ar_handshakes_on_ext_in": 1,
                "orphan_rlast_by_s10_ar": [],
                "single_beat_rlast_before_orphan_rlast": [],
                "x_on_rid_rresp": 0,
                "obs_line": True,
            },
            "the S10 ARID 0x11 AR is handshaken once on ext_in while the hold B orphan has no "
            "RLAST, and no ARID 0x11 beat with RLAST is handshaken before the orphan's 256th beat "
            "from S10 through the S12 release; OBS-SAMEID-HELD logged",
        )
        await self._clear("B", "S12")
        self.steps["S12"] = True

    async def _accept_phase(self, tag: str, mk: dict, ids: set, n: int) -> dict:
        """AR handshakes of ``ids`` until all ``n`` are taken or ARREADY holds 4096 cycles."""
        dut = self.dut
        stall = 0
        bound = (n + 1) * ACCEPT_STALL
        outcome = "unresolved"
        used = 0
        for used in range(1, bound + 1):
            await RisingEdge(dut.clk_smu_i)
            if len(self._since(mk, "ar", ids, "arid")) >= n:
                outcome = "all"
                break
            if _val(dut.ext_in_arvalid) == 1 and _val(dut.ext_in_arready) == 0:
                stall += 1
            else:
                stall = 0
            if stall >= ACCEPT_STALL:
                outcome = "held"
                break
        await RisingEdge(dut.clk_smu_i)
        accepted = len(self._since(mk, "ar", ids, "arid"))
        self.windows.append(
            {
                "label": tag,
                "length": ACCEPT_STALL,
                "start": self.mon.cyc - used,
                "outcome": f"{outcome} accepted={accepted}",
            }
        )
        self._info(
            f"WINDOW site={tag} stall_length={ACCEPT_STALL} cycles bound={bound} used={used} "
            f"outcome={outcome} accepted={accepted} of {n}; an observation, never a verdict"
        )
        return {"accepted": accepted, "outcome": outcome, "used": used}

    async def _limits(self, hold: str, step: str, arids: tuple[int, ...]) -> dict:
        """Reads at SEP global 0x1000 + 8k under ``arids`` during the hold; the accepted counts."""
        dut = self.dut
        mon = self.mon
        ahead = self._queued_ahead(hold)
        pre = _val(dut.sep_reset_n_o)
        c0 = self._counts()
        mk = mon.mark()
        for k, arid in enumerate(arids):
            self._issue_read(DURING_ADDR + BEAT_BYTES * k, BEAT_BYTES, SIZE_8B, arid)
        res = await self._accept_phase(f"{step}_accept", mk, set(arids), len(arids))
        c1 = self._counts()
        res.update(
            pre=pre,
            ahead=ahead,
            tap=self._delta(c0, c1, "sep_xbar_in_ar_count_o"),
            tap_sampled=None not in (c0["sep_xbar_in_ar_count_o"], c1["sep_xbar_in_ar_count_o"]),
            label=f">{len(arids)}" if res["outcome"] == "all" else str(res["accepted"]),
        )
        self._info(
            f"{step} hold={hold} precondition since the orphan AR: other ext_in AR="
            f"{ahead['ar'] or 'none'} other AW={ahead['aw'] or 'none'} "
            f"arvalid_pending={ahead['arvalid_pending']}"
        )
        return res

    @staticmethod
    def _accept_grade_fields(res: dict) -> dict:
        return {
            "window_applied": res["outcome"] in ("all", "held"),
            "issued_during_hold": res["pre"] == 0,
            "no_request_queued_ahead": res["ahead"]
            == {"ar": [], "aw": [], "arvalid_pending": False},
        }

    async def _s14_same_id_limit(self) -> None:
        self._step("S14", "sixteen reads under ARID 0x41 at SEP global 0x1000 + 8k during hold C")
        res = await self._limits("C", "S14", (SAME_ARID,) * SAME_COUNT)
        self.o["same"] = res
        self.log.info(
            "OBS-ACCEPT-SAME-ID: arid=0x%x accepted=%s of %d outcome=%s stall_window=%d "
            "sep_reset_n_o_at_issue=%s",
            SAME_ARID,
            res["label"],
            SAME_COUNT,
            res["outcome"],
            ACCEPT_STALL,
            _hx(res["pre"]),
        )
        self.log.info(
            "OBS-IDW-SEP-PER-ID: sep_in_ar_tap_delta=%s beside ext_in_accepted=%s (ARID 0x%x)",
            res["tap"],
            res["accepted"],
            SAME_ARID,
        )
        self._grade(
            "CHK-ACCEPT-PER-ID-OBS",
            self._accept_grade_fields(res),
            {
                "window_applied": True,
                "issued_during_hold": True,
                "no_request_queued_ahead": True,
            },
            f"OBS-ACCEPT-SAME-ID accepted={res['label']} under ARID 0x41 with the "
            f"{ACCEPT_STALL}-cycle ARREADY window during hold C",
        )
        self._ctrl("LIMITS_SAMEID")
        self.steps["S14"] = True

    async def _s17_distinct_limit(self) -> None:
        self._step("S17", "twenty-four reads under ARIDs 0x50..0x67 at SEP 0x1000 + 8k, hold D")
        res = await self._limits("D", "S17", DISTINCT_ARIDS)
        same = self.o["same"]
        self.log.info(
            "OBS-ACCEPT-SEP-SUB: arids=0x50..0x67 accepted=%s of %d outcome=%s stall_window=%d "
            "sep_reset_n_o_at_issue=%s",
            res["label"],
            len(DISTINCT_ARIDS),
            res["outcome"],
            ACCEPT_STALL,
            _hx(res["pre"]),
        )
        self.log.info(
            "OBS-IDW-SEP-UNIQUE: sep_in_ar_tap_delta=%s beside ext_in_accepted=%s (distinct IDs)",
            res["tap"],
            res["accepted"],
        )
        self._grade(
            "CHK-ACCEPT-SEP-OBS",
            self._accept_grade_fields(res),
            {
                "window_applied": True,
                "issued_during_hold": True,
                "no_request_queued_ahead": True,
            },
            f"OBS-ACCEPT-SEP-SUB accepted={res['label']} under ARIDs 0x50..0x67 with the "
            f"{ACCEPT_STALL}-cycle ARREADY window during hold D",
        )
        self._grade(
            "CHK-IDW-SEP-LIMIT-OBS",
            {
                "unique_recorded": res["tap"] != "X",
                "per_id_recorded": same["tap"] != "X",
                "tap_sampled": res["tap_sampled"] and same["tap_sampled"],
            },
            {"unique_recorded": True, "per_id_recorded": True, "tap_sampled": True},
            f"OBS-IDW-SEP-UNIQUE tap={res['tap']} (hold D) and OBS-IDW-SEP-PER-ID "
            f"tap={same['tap']} (hold C) logged beside the ext_in counts",
        )
        self._ctrl("LIMITS_DISTINCT")
        self.steps["S17"] = True

    async def _release_clear(self, hold: str, step: str) -> None:
        await self._release(hold, step)
        await self._clear(hold, step)
        self.steps[step] = True

    # ------------------------------------------------------------------ verdicts across holds

    def _clear_grade(self) -> None:
        observed, expected = {}, {}
        for hold in HOLDS:
            clear = self.holds.get(hold, {}).get("clear")
            if clear is None:
                observed[hold] = "not run"
            else:
                sram, smc = clear["sram"], clear["smc"]
                observed[hold] = (
                    (sram["w_done"], sram["bresp"]),
                    (sram["r_done"], sram["rresp"], sram["rdata"]),
                    (smc["done"], smc["rresp"], smc["word"]),
                )
            expected[hold] = (
                (True, [_rn(RESP_OKAY)]),
                (True, [_rn(RESP_OKAY)], [_hx(cold_word(hold))]),
                (True, [_rn(RESP_OKAY)], [_hx(SMC_CHIP_CONFIG_VERSION_LO_RESET)]),
            )
        self._grade(
            "CHK-CLEAR",
            observed,
            expected,
            "after every rst_cold_ni and the S1 programming (S8, S12, S15, S18) the SEP SRAM "
            "write is OKAY, its read returns that hold's word OKAY and VERSION_LO returns OKAY with its "
            "RDL reset value; OBS-CLEARED-BY logged for every hold",
        )

    def _held_grade(self) -> None:
        lv = self.lv
        per_hold, want = {}, {}
        for hold in HOLDS:
            rec = self.holds.get(hold, {})
            fall, rise = rec.get("fall"), rec.get("rise")
            opens = [c for c, label, _ in lv["opens"] if label == hold]
            closes = [c for c, label, _ in lv["closes"] if label == hold]
            per_hold[hold] = {
                "sep_reset_n_fell": fall is not None,
                "sep_reset_n_at_fall": rec.get("nets", {}).get("sep_reset_n_o"),
                "sep_reset_n_not_low_in_hold": len(rec.get("early", [None])),
                "window_opened_at_fall": len(opens) == 1
                and fall is not None
                and 0 <= opens[0] - fall <= 1,
                "window_closed_at_release": len(closes) == 1
                and rise is not None
                and abs(closes[0] - rise - WINDOW_CLOSE_MARGIN) <= 1,
                "obs_lines": rec.get("obs", False),
            }
            want[hold] = {
                "sep_reset_n_fell": True,
                "sep_reset_n_at_fall": 0,
                "sep_reset_n_not_low_in_hold": 0,
                "window_opened_at_fall": True,
                "window_closed_at_release": True,
                "obs_lines": True,
            }
            self._info(
                f"CHK-HELD-REACH hold={hold} fall={fall} rise={rise} hold_samples="
                f"{rec.get('hold_samples')} window_open={opens} window_close={closes}"
            )
        outside = [(c, w) for c, label, w in lv["opens"] + lv["closes"] if label is None]
        observed = {
            "holds": per_hold,
            "sep_rst_ni_not_high": len(lv["rst_ni_bad"]),
            "window_edges_outside_hold": outside,
            "window_count": _val(self.dut.obs_sep_in_expect_window_count),
            "window_open_at_end": _val(self.dut.obs_sep_in_expect_window_open),
        }
        expected = {
            "holds": want,
            "sep_rst_ni_not_high": 0,
            "window_edges_outside_hold": [],
            "window_count": len(HOLDS),
            "window_open_at_end": 0,
        }
        self._grade(
            "CHK-HELD-REACH",
            observed,
            expected,
            f"in each of holds {'/'.join(HOLDS)} sep_reset_n_o read 0 from the IC_RESET update "
            f"to the release while obs_sep_rst_n_o read 1 on all {lv['samples']} samples outside "
            "the cold resets; the bench expectation window opened at every fall and closed "
            f"{WINDOW_CLOSE_MARGIN} (+/-1) clk_smu_i cycles after every rise, never outside a hold "
            "and not at the end; OBS-HELD-XBAR-RESET, "
            "OBS-HELD-APERTURE and OBS-SEPIN-WITHDRAWN logged per hold",
        )

    def _fences(self) -> None:
        names = [n for n, _ in self.markers]
        cycles = [c for _, c in self.markers]
        increasing = all(a < b for a, b in zip(cycles, cycles[1:]))
        self._info(f"NONVAC markers={self.markers}")
        self._grade(
            "CHK-NONVAC",
            {"order": names, "strictly_increasing": increasing, "steps": sorted(self.steps)},
            {"order": list(MARKERS), "strictly_increasing": True, "steps": sorted(STEPS)},
            "ordered markers " + " < ".join(f"{n}@{c}" for n, c in self.markers),
        )
        for rec in self.sites:
            self._info(
                f"TIMEOUT-PATH {rec['kind']} {rec['label']}: bound={rec['bound']} {rec['unit']} "
                f"used={rec['used']} {'EXPIRED' if rec['expired'] else 'ok'} on_expiry=fail "
                f"last={rec['last']}"
            )
        for win in self.windows:
            self._info(
                f"WINDOW-RECORD {win['label']}: length={win['length']} outcome={win['outcome']} "
                "graded=no"
            )
        expired = [s["label"] for s in self.sites if s["expired"]]
        unbounded = [s["label"] for s in self.sites if not s["bound"]]
        no_last = [s["label"] for s in self.sites if not s["last"]]
        no_outcome = [w["label"] for w in self.windows if not w["length"] or not w["outcome"]]
        self._grade(
            "CHK-TIMEOUT-PATHS",
            {
                "expired": expired,
                "unbounded": unbounded,
                "without_last_state": no_last,
                "windows_without_length_or_outcome": no_outcome,
                "expect_window_open_at_end": _val(self.dut.obs_sep_in_expect_window_open),
            },
            {
                "expired": [],
                "unbounded": [],
                "without_last_state": [],
                "windows_without_length_or_outcome": [],
                "expect_window_open_at_end": 0,
            },
            f"every wait ({len(self.sites)}) has a finite bound, a fail-on-expiry path and a last "
            f"state, none expired; every observation window ({len(self.windows)}) logged its "
            "length and outcome and none is graded; the bench expectation window is closed at "
            "the end",
        )

    async def run(self) -> None:
        await self._s1_setup()
        await self._s2_orphan()
        await self._s3_hold()
        await self._s4_orphan_fate()
        await self._s5_diff_id()
        await self._s6_fresh_during()
        await self._s7_release()
        await self._s8_clear()
        await self._orphan_and_hold("B", "S9")
        await self._s10_same_id()
        await self._s11_other_initiator()
        await self._s12_release_clear()
        await self._orphan_and_hold("C", "S13")
        await self._s14_same_id_limit()
        await self._release_clear("C", "S15")
        await self._orphan_and_hold("D", "S16")
        await self._s17_distinct_limit()
        await self._release_clear("D", "S18")
        self._clear_grade()
        self._held_grade()
        self.lv["on"] = False
        self._step("S19", "bounded waits, logged windows and the bench window closed at the end")
        self.steps["S19"] = True
        self._fences()
        if self.failures:
            raise AssertionError(f"{len(self.failures)} checker compare(s) failed: {self.failures}")
