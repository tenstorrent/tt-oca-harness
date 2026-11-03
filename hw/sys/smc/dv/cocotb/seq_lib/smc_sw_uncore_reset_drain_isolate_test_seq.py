# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
# DV-TESTCASE-CONTRACT: SMC_SEP_SCN_003 ANCHOR: smc_sw_uncore_reset_drain_isolate_test
# DV-TESTCASE-CONTRACT-REVISION: 4 RECORD-SHA256: 5f510c164e672349855dda85b6c985e428a2efcce774768756405e2d1f93d81a
# DV-TESTCASE-CONTRACT-SOURCE: hw/sys/smc/dv/ai/dv_vplan_gen/SMC_SEP_SCN_VPLAN_DETAIL.md @ artifact_revision 2 ENV: cocotb
"""Software core reset, core reset pulse and software uncore reset with the L2 frontend isolate.

``CPU_CTRL.RESET_CTRL`` is driven over SEP_IN in four ways. Core 3 is held and then pulsed
without any drain while SEP_IN and SYS_IN keep reaching the scratchpad and the core-3 watchdog
compare register keeps its value. The uncore bit is cleared with four L2 frontend reads parked
by ``tb_sep_axi_r_hold`` in timer-off mode (the reset is withheld for 1024 edges), in give-up
mode (``reset_timeout`` is reported and the reset is still withheld until the drain completes)
and with nothing pending, where a scratchpad read presented on SEP_IN, SYS_IN and JTAG_IN while
the boundary is isolated is blocked, not terminated, and completes after the reconnect. The
force-mode episode is not driven: its flush presents a stale R beat with ID 0 on SYS_IN, the
behaviour ruling #2449 accepts, every inbound protocol checker stays on, and the pinned wedge
leaves cover the episode. The CPU MMIO episodes are not driven. A cold reset replayed through the reset agent ends the leaf and records the isolation release.

Graded: the compares named by the ``CHK-*`` lines the sequence prints. ``OBS-*`` content is
printed inside the matching ``CHK-OBS-*`` line and on its own ``EVIDENCE:`` line, never
compared, and names its spec finding or ruling. The drain claims count the parked reads the
isolate counted as pending (the first ``tb_cpu_l2_pending_ar`` peak reads in front-port AR
order) and time their RLAST at the front port, the isolate boundary; a read the front port
accepted that the isolate never counted is an observation that must complete after the
reconnect. A status read is graded only when no request of any manager is stalled at the front
port and no bench hold is active; any other status read is an observation whose bounded
wait is counted apart, and the fact it would have carried comes from the probes.

Probes: ``tb_cpu_core_resets_n`` (core 3 is bit 3), ``tb_cpu_uncore_reset_n``,
``tb_cpu_isolate_req``, ``tb_cpu_drained``, ``tb_cpu_reset_timeout``, ``tb_cpu_reset_applied``,
``tb_cpu_l2_isolated``, ``tb_cpu_mmio_isolated``, ``tb_cpu_l2_pending_ar``,
``tb_cpu_front_valid`` / ``_ready`` and ``tb_cpu_mmio_valid`` / ``_ready`` with
``[4:0] = {r, ar, b, w, aw}``, ``tb_cpu_front_arid``, ``tb_cpu_front_rid`` and
``tb_cpu_front_rlast`` (the front-port AR ID, R ID and RLAST), the bench holds
``tb_sep_axi_r_hold`` / ``tb_sys_axi_r_hold``, and ``rst_primary_smc_clk_no`` for the primary
reset.
"""

from __future__ import annotations

from types import SimpleNamespace

import cocotb
from cocotb.triggers import FallingEdge, RisingEdge, SimTimeoutError, with_timeout
from cocotb.utils import get_sim_time
from env.smc_reset_item import SmcResetOp
from env.smc_sys_axi_agent import SmcSysAxiDriver, SmcSysAxiItem, SmcSysAxiOp

from ._one_shot import _OneShot
from .smc_addr_map import cpu_ctrl_u32, smc_addr, smc_indexed_addr, wdt_u32
from .smc_base_test_seq import wait_fuse_sense_done
from .smc_output_fabric_vip_utils import output_fabric_pass_all_cfg_seq
from .smc_reset_seq_base import SmcResetSeqBase

SPM_BASE = smc_addr("SMC_TOP_SPM_MEMORY_BASE_ADDR")
RESET_CTRL = smc_addr("SMC_TOP_SMC_CPU_CTRL_RESET_CTRL_BASE_ADDR")
CPU_CTRL_BASE = smc_addr("SMC_TOP_SMC_CPU_CTRL_BASE_ADDR")
CPU_CTRL_SIZE = smc_addr("SMC_TOP_SMC_CPU_CTRL_SIZE")
RESET_TIMEOUT = smc_addr("SMC_TOP_SMC_CPU_CTRL_RESET_TIMEOUT_BASE_ADDR")
PULSE_COUNT = smc_addr("SMC_TOP_SMC_CPU_CTRL_CORE_RESET_PULSE_COUNT_BASE_ADDR")
WDT3_COUNT = smc_addr("SMC_TOP_SMC_CLUSTER_CORE3_WDT_COUNT_BASE_ADDR")
WDT3_KEY = smc_addr("SMC_TOP_SMC_CLUSTER_CORE3_WDT_KEY_BASE_ADDR")
WDT3_CMP = smc_addr("SMC_TOP_SMC_CLUSTER_CORE3_WDT_CMP_BASE_ADDR")
BEU3_ENABLE = smc_addr("SMC_TOP_SMC_CLUSTER_CORE3_BEU_ENABLE_BASE_ADDR")


def _wb_pc_core0(i: int) -> int:
    return smc_indexed_addr("SMC_TOP_SMC_CPU_CTRL_WB_PC_CORE0_BASE_ADDR", i)


CORE3_RESET_N = cpu_ctrl_u32("CPU_CTRL__RESET_CTRL__CORE3_RESET_N_N0_SCAN_bm")
CORE3_PULSE_START = cpu_ctrl_u32("CPU_CTRL__RESET_CTRL__CORE3_RESET_PULSE_START_N0_SCAN_bm")
UNCORE_RESET_N = cpu_ctrl_u32("CPU_CTRL__RESET_CTRL__UNCORE_RESET_N_N0_SCAN_bm")
CORE_RESET_N_ALL = sum(
    cpu_ctrl_u32(f"CPU_CTRL__RESET_CTRL__CORE{i}_RESET_N_N0_SCAN_bm") for i in range(4)
)
START_BITS = sum(
    cpu_ctrl_u32(f"CPU_CTRL__RESET_CTRL__CORE{i}_RESET_PULSE_START_N0_SCAN_bm") for i in range(4)
)
TIMEOUT_VALUE_BM = cpu_ctrl_u32("CPU_CTRL__RESET_TIMEOUT__TIMEOUT_VALUE_bm")
TIMEOUT_MODE_BM = cpu_ctrl_u32("CPU_CTRL__RESET_TIMEOUT__TIMEOUT_MODE_bm")
RESET_APPLIED_BM = cpu_ctrl_u32("CPU_CTRL__RESET_TIMEOUT__RESET_APPLIED_bm")
RESET_TIMEOUT_BM = cpu_ctrl_u32("CPU_CTRL__RESET_TIMEOUT__RESET_TIMEOUT_bm")
PRE_COUNT_BM = cpu_ctrl_u32("CPU_CTRL__CORE_RESET_PULSE_COUNT__PRE_RESET_COUNT_bm")
POST_COUNT_BM = cpu_ctrl_u32("CPU_CTRL__CORE_RESET_PULSE_COUNT__POST_RESET_COUNT_bm")
POST_COUNT_BP = cpu_ctrl_u32("CPU_CTRL__CORE_RESET_PULSE_COUNT__POST_RESET_COUNT_bp")
RESETS_DONE_BM = cpu_ctrl_u32("CPU_CTRL__CORE_RESET_PULSE_COUNT__CORE_RESETS_DONE_bm")
PRE_COUNT_RESET = cpu_ctrl_u32("CPU_CTRL__CORE_RESET_PULSE_COUNT__PRE_RESET_COUNT_reset")
POST_COUNT_RESET = cpu_ctrl_u32("CPU_CTRL__CORE_RESET_PULSE_COUNT__POST_RESET_COUNT_reset")
RESETS_DONE_RESET = cpu_ctrl_u32("CPU_CTRL__CORE_RESET_PULSE_COUNT__CORE_RESETS_DONE_reset")
RESETS_DONE_BP = cpu_ctrl_u32("CPU_CTRL__CORE_RESET_PULSE_COUNT__CORE_RESETS_DONE_bp")
RESETS_DONE_CORE3 = 1 << (RESETS_DONE_BP + 3)

# wdt.adoc: the KEY write that unlocks the next write.
WDT_MAGIC_KEY = 0x51F15E
WDT_CMP_REF = 0x0234
WDT_CMP_RESET = wdt_u32("WDT__CMP__WDOGCMP0_reset")

SCRATCH_REF_BASE = SPM_BASE + 0x20_000
PAIR_SEP_ADDR = SPM_BASE + 0x20_100
PAIR_SYS_ADDR = SPM_BASE + 0x20_108
BLOCK_BASE = SPM_BASE + 0x20_200
FRESH_ADDR = SPM_BASE + 0x20_300
EXT_ROUTE = 0xB000_0010
EXT_ROUTE_WORD = 0x1A72_00B0_0000_0010
REF_TAG = 0x0C0F_FEE0_0000_0000
PAIR_DATA = (0x5EC0_0001_0000_0100, 0x5EC0_0002_0000_0108)

TIMEOUT_CYCLES = 64
PULSE_POST_LONG = 0x00FF
PULSE_WIDTH_RESET = POST_COUNT_RESET + 1
HOLD_EDGES = 512
HOLD_EDGES_MID = 256
HOLD_EDGES_END = 480
RMW_EDGES = 128
PULSE_TAIL_EDGES = 64
PULSE_HOLD_EDGES = 400
TIMER_OFF_EDGES = 1024
GIVE_UP_KEEP_EDGES = 256
BLOCK_EDGES = 256
COLD_TAIL_EDGES = 16
COLD_ISOLATE_EDGES = 4

ISOLATE_BOUND = 300
DRAIN_BOUND = 20_000
TIMEOUT_BOUND = 2_000
RECONNECT_BOUND = 4_000
PULSE_BOUND = 2_000
PENDING_BOUND = 2_000
ASSERT_BOUND = 300
COLD_BOUND = 60_000
FUSE_SENSE_BOUND = 200_000
AXI_BOUND_NS = 50_000
OBS_AXI_BOUND_NS = 2_000

PEND_ID = 0x30
FIFTH_ID = 0x34
STALL_ID_BASE = 0x01
TOKEN_STATUS = "CHK-STATUS-READABLE-FROM-SEP"
BLOCK_ID = (0x3A, 0x3B, 1)
WB_ID = 0x08

REQUIRED_TOKENS = (
    "CHK-CORE-HOLD-NO-DRAIN",
    "CHK-CORE-PULSE",
    "CHK-CORE3-WDT-CONFIG",
    "CHK-CORE-RESET-N-TERM",
    "CHK-TIMER-OFF-WAITS",
    "CHK-L2F-FOUR-OUTSTANDING",
    "CHK-DRAIN-HANDSHAKE-ORDER",
    "CHK-GIVEUP-REPORT-AND-WAIT",
    "CHK-DRAIN-PENDING-READS-COMPLETE",
    "CHK-BLOCKED-NOT-TERMINATED-THEN-RECONNECT",
    "CHK-STATUS-READABLE-FROM-SEP",
    "CHK-OBS-VALID-UNCORE-SW",
    "CHK-COLD-ISOLATION-RELEASE",
    "CHK-OBS-TIMEOUT-EXPIRY",
    "CHK-OBS-ISOLATION-DELAY",
    "CHK-OBS-DRAIN-FLUSH-RESPONSES",
    "CHK-OBS-CORE-RESET-ACCESS",
    "CHK-OBS-MMIO-RESET",
    "CHK-OBS-PULSE-AND-STATUS",
    "CHK-NONVAC",
    "CHK-TIMEOUT-PATHS",
)
FENCE = (
    "SETUP",
    "CORE_HOLD",
    "PULSE",
    "TIMER_OFF",
    "GIVE_UP",
    "BLOCKED",
    "FORCE",
    "MMIO",
    "COLD_ENTRY",
)
SEP_ID_BITS = 6
SEP_ID_MASK = (1 << SEP_ID_BITS) - 1

_EXTRA_NAMES = (
    "rst_primary_smc_clk_no",
    "tb_cpu_cluster_isolate",
    "tb_sep_axi_r_hold",
    "tb_sys_axi_r_hold",
    "tb_output_axi_resp_hold",
)

# key -> tb_top net, sampled on every clk_smc_i falling edge (half a clock before the capturing
# edge), so a handshake is a VALID and a READY that both read 1 in the same sample.
SAMPLED = (
    ("core", "tb_cpu_core_resets_n"),
    ("unc", "tb_cpu_uncore_reset_n"),
    ("isoreq", "tb_cpu_isolate_req"),
    ("drn", "tb_cpu_drained"),
    ("rto", "tb_cpu_reset_timeout"),
    ("rap", "tb_cpu_reset_applied"),
    ("l2iso", "tb_cpu_l2_isolated"),
    ("mmioiso", "tb_cpu_mmio_isolated"),
    ("l2fl", "tb_cpu_l2_flush_active"),
    ("mmiofl", "tb_cpu_mmio_flush_active"),
    ("l2par", "tb_cpu_l2_pending_ar"),
    ("mpar", "tb_cpu_mmio_pending_ar"),
    ("mpaw", "tb_cpu_mmio_pending_aw"),
    ("mpw", "tb_cpu_mmio_pending_w"),
    ("fv", "tb_cpu_front_valid"),
    ("fr", "tb_cpu_front_ready"),
    ("farid", "tb_cpu_front_arid"),
    ("frid", "tb_cpu_front_rid"),
    ("frl", "tb_cpu_front_rlast"),
    ("sh", "tb_sep_axi_r_hold"),
    ("yh", "tb_sys_axi_r_hold"),
    ("mv", "tb_cpu_mmio_valid"),
    ("mr", "tb_cpu_mmio_ready"),
    ("sarv", "s_axi_arvalid"),
    ("sarr", "s_axi_arready"),
    ("sara", "s_axi_araddr"),
    ("yarv", "sys_axi_arvalid"),
    ("yarr", "sys_axi_arready"),
    ("yara", "sys_axi_araddr"),
    ("jarv", "jtag_axi_arvalid"),
    ("jarr", "jtag_axi_arready"),
    ("jara", "jtag_axi_araddr"),
    ("srv", "s_axi_rvalid"),
    ("srr", "s_axi_rready"),
    ("srl", "s_axi_rlast"),
    ("srid", "s_axi_rid"),
    ("sbv", "s_axi_bvalid"),
    ("srraw", "tb_sep_axi_r_raw_valid"),
    ("yrv", "sys_axi_rvalid"),
    ("yraw", "tb_sys_axi_r_raw_valid"),
    ("yrid", "sys_axi_rid"),
    ("jrid", "jtag_axi_rid"),
    ("ybv", "sys_axi_bvalid"),
    ("jrv", "jtag_axi_rvalid"),
    ("jbv", "jtag_axi_bvalid"),
    ("init", "smc_init_mem_done_o"),
    ("prim", "rst_primary_smc_clk_no"),
    ("oarv", "tb_output_axi_arvalid"),
    ("oarr", "tb_output_axi_arready"),
    ("oara", "tb_output_axi_araddr"),
    ("orv", "tb_output_axi_rvalid"),
    ("orr", "tb_output_axi_rready"),
)
IDX = {key: n for n, (key, _name) in enumerate(SAMPLED)}
AR_NETS = {"SEP": ("sarv", "sara"), "SYS": ("yarv", "yara"), "JTAG": ("jarv", "jara")}
FRONT_BIT = {"aw": 0, "w": 1, "b": 2, "ar": 3, "r": 4}
NO_RESPONSE = None
BURST_BEATS = 8
REF_WORDS = 16


class smc_sw_uncore_reset_drain_isolate_test_seq(SmcResetSeqBase, output_fabric_pass_all_cfg_seq):
    """RESET_CTRL software reset family seen from SEP_IN with the L2 frontend isolate."""

    def __init__(self, name: str = "smc_sw_uncore_reset_drain_isolate_test_seq") -> None:
        super().__init__(name)
        self.rows: list[tuple[int, ...]] = []
        self._sampler_stop = False
        self._sampler_task = None
        self.fence: list[tuple[str, int, int]] = []
        self.fails: list[str] = []
        self.lines: list[tuple[str, str]] = []
        self._raw_seq = 0
        self.ctx = SimpleNamespace()
        self.obs: dict[str, list[str]] = {
            "pulse": [],
            "expiry": [],
            "iso": [],
            "flush": [],
            "core": [],
            "status": [],
        }
        self.notes: dict[str, object] = {}
        self.aborted: list[str] = []
        self.term: list[tuple[str, int, int]] = []
        self.valid_windows: list[tuple[str, int, int]] = []
        self.rt_reads: list = []
        self.rc_base = CORE_RESET_N_ALL | UNCORE_RESET_N
        self.cmp_kept = None
        self.cmp_after = None
        self.drained_b: list = []
        self.ctrl_log: list[list] = []
        self.printed: set[str] = set()
        self.agg_done = False
        self.obs_waits: list[str] = []
        self.front_prefix: int | None = None
        self.front_ids: list[int] = []
        self.obs_lines: list[str] = []
        self.graded_status: list[tuple] = []
        self.stall_reads: list[tuple] = []

    # --- plumbing ------------------------------------------------------------------------
    @staticmethod
    def _g(name: str) -> int:
        """Live value of a tb_top net, -1 when it is not resolvable."""
        value = getattr(cocotb.top, name).value
        return int(value) if value.is_resolvable else -1

    def _stamp(self, name: str, count: int) -> None:
        self.fence.append((name, int(get_sim_time("ps")), count))

    def _bound(self, label: str, bound: str, state: str) -> None:
        self._timeout_paths.append(f"{label}: bound={bound} last={state}")
        if "EXPIRED" in state:
            cocotb.log.info(
                "WAIT-EXPIRED %s: bound=%s last=%s (sample %d)", label, bound, state, self.n
            )

    def _fail(self, token: str, text: str) -> None:
        self.fails.append(f"{token}: {text}")

    def _ok(self, token: str, text: str) -> None:
        self.lines.append((token, text))

    def _c(self, key: str, i: int) -> int:
        return self.rows[i][IDX[key]]

    @property
    def n(self) -> int:
        return len(self.rows)

    async def _sampler(self) -> None:
        clk = cocotb.top.clk_smc_i
        handles = [getattr(cocotb.top, name) for _key, name in SAMPLED]
        while not self._sampler_stop:
            await FallingEdge(clk)
            row = []
            for handle in handles:
                value = handle.value
                row.append(int(value) if value.is_resolvable else -1)
            self.rows.append(tuple(row))

    async def _edges(self, count: int) -> None:
        """A counted observation window: `count` falling edges, then one more rising edge so
        the sampler has stored the last of them."""
        clk = cocotb.top.clk_smc_i
        for _ in range(count):
            await FallingEdge(clk)
        await RisingEdge(clk)

    async def _until_rows(self, target: int) -> None:
        clk = cocotb.top.clk_smc_i
        while self.n < target:
            await FallingEdge(clk)
        await RisingEdge(clk)

    async def _poll(
        self, label: str, token: str, bound: int, cond, state, *, obs: bool = False
    ) -> int | None:
        """Bounded wait on a live condition; an expiry is a checker FAIL, not an exception.
        An observation wait (``obs``) records its expiry apart and fails nothing."""
        clk = cocotb.top.clk_smc_i
        for k in range(bound + 1):
            await FallingEdge(clk)
            if cond():
                text = f"reached after {k} edges, {state()}"
                if obs:
                    self.obs_waits.append(f"{label}: bound={bound}clk_smc_i last={text}")
                else:
                    self._bound(label, f"{bound}clk_smc_i", text)
                await RisingEdge(clk)
                return k
        if obs:
            self.obs_waits.append(f"{label}: bound={bound}clk_smc_i last=expired {state()}")
            return None
        self._bound(label, f"{bound}clk_smc_i", f"EXPIRED {state()}")
        self._fail(token, f"{label}: not reached within {bound} clk_smc_i edges; {state()}")
        return None

    def _state(self) -> str:
        g = self._g
        return (
            f"core={g('tb_cpu_core_resets_n')} uncore={g('tb_cpu_uncore_reset_n')} "
            f"isolate_req={g('tb_cpu_isolate_req')} drained={g('tb_cpu_drained')} "
            f"reset_timeout={g('tb_cpu_reset_timeout')} applied={g('tb_cpu_reset_applied')} "
            f"l2_isolated={g('tb_cpu_l2_isolated')} mmio_isolated={g('tb_cpu_mmio_isolated')} "
            f"l2_pending_ar={g('tb_cpu_l2_pending_ar')}"
        )

    # --- sample queries ----------------------------------------------------------------------
    def _v(self, key: str, i: int, bit: int | None) -> int:
        v = self._c(key, i)
        return v if bit is None or v < 0 else (v >> bit) & 1

    def _first(
        self, key: str, val: int, a: int, b: int | None = None, bit: int | None = None
    ) -> int | None:
        for i in range(a, self.n if b is None else min(b, self.n)):
            if self._v(key, i, bit) == val:
                return i
        return None

    def _all(
        self, key: str, val: int, a: int, b: int, bit: int | None = None
    ) -> tuple[int, int, int | None]:
        """(samples equal to val, samples examined, first sample that differs)."""
        good, bad = 0, None
        total = max(0, min(b, self.n) - a)
        for i in range(a, a + total):
            if self._v(key, i, bit) == val:
                good += 1
            elif bad is None:
                bad = i
        return good, total, bad

    def _hs(self, ch: str, a: int, b: int, vkey: str = "fv", rkey: str = "fr") -> list[int]:
        """Samples in [a, b) at which a channel of a 5-bit link vector handshakes."""
        bit = FRONT_BIT[ch]
        out = []
        for i in range(a, min(b, self.n)):
            v, r = self._c(vkey, i), self._c(rkey, i)
            if v >= 0 and r >= 0 and (v >> bit) & 1 and (r >> bit) & 1:
                out.append(i)
        return out

    def _front_ar(self, a: int, b: int) -> list[tuple[int, int]]:
        """(sample, front-port ARID) of every front-port AR handshake in [a, b)."""
        return [(i, self._c("farid", i)) for i in self._hs("ar", a, b)]

    def _calibrate_front_ids(self, since: int, until: int) -> None:
        """Bind the front-port ARID of a SEP_IN read from the first parked set: the four
        parked reads are the only front-port reads in [since, until), so their front IDs must
        carry the SEP_IN IDs PEND_ID + k in the low SEP_ID_BITS under one common upper field;
        otherwise no front-port ID is attributed."""
        seen = self._front_ar(since, until)
        self.front_ids = [x for _i, x in seen]
        want = {PEND_ID + k for k in range(4)}
        lows = {x & SEP_ID_MASK for x in self.front_ids if x >= 0}
        highs = {x >> SEP_ID_BITS for x in self.front_ids if x >= 0}
        if len(seen) == 4 and lows == want and len(highs) == 1:
            self.front_prefix = highs.pop()

    def _front_id(self, sep_id: int) -> int | None:
        return None if self.front_prefix is None else (self.front_prefix << SEP_ID_BITS) | sep_id

    def _front_rlast(self, a: int, b: int) -> list[tuple[int, int]]:
        """(sample, front-port RID) of every front-port R handshake carrying RLAST in [a, b)."""
        return [(i, self._c("frid", i)) for i in self._hs("r", a, b) if self._c("frl", i) == 1]

    def _front_open(self, since: int) -> dict[int, int]:
        """Front-port reads accepted since `since` and not yet answered with RLAST, per ID."""
        open_ids: dict[int, int] = {}
        for _i, x in self._front_ar(since, self.n):
            open_ids[x] = open_ids.get(x, 0) + 1
        for _i, x in self._front_rlast(since, self.n):
            if open_ids.get(x, 0) > 0:
                open_ids[x] -= 1
        return {x: c for x, c in open_ids.items() if c > 0}

    def _read_name(self, front_id: int) -> str:
        for k in range(4):
            if front_id == self._front_id(PEND_ID + k):
                return f"read{k}"
        if front_id == self._front_id(FIFTH_ID):
            return "fifth"
        return f"front_id_0x{front_id:x}"

    def _stalled(self, since: int) -> tuple[list[str], list[str]]:
        """(requests stalled at the front port since `since`, active bench holds).
        A graded status read is issued only when both are empty."""
        reads = [self._read_name(x) for x in sorted(self._front_open(since))]
        last = self.n - 1
        if last >= 0:
            v, r = self._c("fv", last), self._c("fr", last)
            if v < 0 or r < 0 or ((v >> FRONT_BIT["ar"]) & 1 and not (r >> FRONT_BIT["ar"]) & 1):
                reads.append("front_ar_waiting")
        holds = [
            tag
            for name, tag in (
                ("tb_sep_axi_r_hold", "sep_hold"),
                ("tb_sys_axi_r_hold", "sys_hold"),
            )
            if self._g(name) != 0
        ]
        return reads, holds

    def _armed(self, since: int, count: int) -> bool:
        ar = self._front_ar(since, self.n)
        if self.front_prefix is not None:
            ids = {x for _i, x in ar}
            if any(self._front_id(PEND_ID + k) not in ids for k in range(count)):
                return False
        elif len(ar) < count:
            return False
        return self._g("tb_cpu_l2_pending_ar") > 0 and self._g("tb_sep_axi_r_raw_valid") == 1

    def _held(self, a: int, b: int) -> list[int]:
        """Samples in [a, b] at which either bench R hold reads 1."""
        return [
            i
            for i in range(a, min(b + 1, self.n))
            if self._c("sh", i) == 1 or self._c("yh", i) == 1
        ]

    def _in_ctrl(self, i: int) -> bool:
        return any(a0 <= i <= (a1 if a1 is not None else self.n) for a0, a1 in self.ctrl_log)

    def _sep_r_done(self, a: int, b: int, ids) -> list[int]:
        """Samples in [a, b) at which a SEP_IN R beat with RLAST and an RID in ids handshakes."""
        return [
            i
            for i in range(a, min(b, self.n))
            if self._c("srv", i) == 1
            and self._c("srr", i) == 1
            and self._c("srl", i) == 1
            and self._c("srid", i) in ids
        ]

    def _runs(self, key: str, bit: int | None, val: int, a: int, b: int) -> list[int]:
        """Lengths of the maximal runs of samples in [a, b) at which a net (or bit) reads val."""
        runs, cur = [], 0
        for i in range(a, min(b, self.n)):
            if self._v(key, i, bit) == val:
                cur += 1
            elif cur:
                runs.append(cur)
                cur = 0
        if cur:
            runs.append(cur)
        return runs

    # --- bench access helpers ----------------------------------------------------------------
    def _agent(self, port: str):
        return {
            "SEP": self.env.sys_axi_agent,
            "SYS": self.env.sys_in_axi_agent,
            "JTAG": self.env.jtag_axi_agent,
        }[port]

    @staticmethod
    def _item(op, label, addr, data=0, length=8, axi_id=None, beats=1) -> SmcSysAxiItem:
        item = SmcSysAxiItem(label)
        item.op = op
        item.addr = addr
        item.length = length
        item.beats = beats
        item.wdata = data
        item.axi_id = axi_id
        return item

    @staticmethod
    def _result(raw) -> tuple[int | None, int | None]:
        if not raw.event.is_set():
            return None, None
        data = raw.event.data
        if data is None:
            return None, None
        code = SmcSysAxiDriver._resp_code(data)
        value = None
        if raw.op is SmcSysAxiOp.READ:
            value = int.from_bytes(data.data, "little") & ((1 << (8 * raw.length * raw.beats)) - 1)
        return code, value

    def _raw(self, port, op, label, addr, data=0, length=8, axi_id=None, beats=1):
        """Present an access and return at once; the response is joined later."""
        item = self._item(op, label, addr, data, length, axi_id, beats)
        event = self._agent(port).driver._start_transfer(item)
        span = [self.n, None]
        if CPU_CTRL_BASE <= addr < CPU_CTRL_BASE + CPU_CTRL_SIZE:
            self.ctrl_log.append(span)
            cocotb.start_soon(self._span_end(span, event))
            event_span = span
        else:
            event_span = None
        raw = SimpleNamespace(
            span=event_span,
            label=label,
            port=port,
            event=event,
            op=op,
            addr=addr,
            length=length,
            beats=beats,
            axi_id=axi_id,
            issued=self.n,
            done_at=None,
        )
        cocotb.start_soon(self._mark_done(raw))
        return raw

    def _ar_presented(self, raw, a: int, b: int, gate: str) -> int | None:
        """First sample in [a, b) with the port's ARVALID at 1 on ``raw.addr`` and ``gate`` at 1."""
        valid, addr = AR_NETS[raw.port]
        for i in range(max(a, raw.issued), min(b, self.n)):
            if self._c(valid, i) == 1 and self._c(addr, i) == raw.addr and self._c(gate, i) == 1:
                return i
        return None

    async def _mark_done(self, raw) -> None:
        """Record the sample at which a presented access is answered."""
        await raw.event.wait()
        raw.done_at = self.n

    async def _span_end(self, span: list, event) -> None:
        """Close the CPU_CTRL access interval at the sample where its response arrives."""
        await event.wait()
        span[1] = self.n + 2

    async def _join(
        self,
        raw,
        token: str,
        *,
        obs: bool = False,
        bound_ns: int = AXI_BOUND_NS,
        obs_wait: bool = False,
    ):
        """Bounded wait for a presented access; (resp code, read data), (None, None) on expiry.
        An observation wait (``obs_wait``) records its expiry apart and fails nothing."""
        if not raw.event.is_set():
            try:
                await with_timeout(raw.event.wait(), bound_ns, "ns")
            except SimTimeoutError:
                if obs_wait:
                    self.obs_waits.append(
                        f"{raw.label}.axi: bound={bound_ns}ns last=expired {raw.port} "
                        f"@0x{raw.addr:x} (sample {self.n})"
                    )
                    return NO_RESPONSE, NO_RESPONSE
                self._bound(
                    f"{raw.label}.axi", f"{bound_ns}ns", f"EXPIRED {raw.port} @0x{raw.addr:x}"
                )
                self._fail(
                    token,
                    f"{raw.port} {raw.label} @0x{raw.addr:x}: no response within {bound_ns} ns "
                    f"({self._state()})",
                )
                return NO_RESPONSE, NO_RESPONSE
        code, value = self._result(raw)
        self.accesses += 1
        if raw.span is not None and raw.span[1] is None:
            raw.span[1] = self.n + 2
        if obs_wait:
            self.obs_waits.append(f"{raw.label}.axi: bound={bound_ns}ns last=answered resp={code}")
        else:
            self._bound(f"{raw.label}.axi", f"{bound_ns}ns", f"answered resp={code}")
        cocotb.log.info(
            "ACCESS %s %s @0x%x resp=%s data=%s done at sample %d",
            raw.port,
            raw.label,
            raw.addr,
            code,
            None if value is None else hex(value & ((1 << 64) - 1)),
            self.n,
        )
        if code != 0 and not obs:
            self._fail(token, f"{raw.port} {raw.label} @0x{raw.addr:x}: resp={code}")
        return code, value

    async def _acc(self, port, op, label, addr, data=0, length=8, *, token, obs=False, axi_id=None):
        self._raw_seq += 1
        if axi_id is None and port != "JTAG":
            axi_id = 0x10 + (self._raw_seq % 0x20)
        raw = self._raw(port, op, label, addr, data, length, axi_id)
        return await self._join(raw, token, obs=obs)

    async def _rd(self, label, addr, token, *, port="SEP", length=8, obs=False):
        _, value = await self._acc(
            port, SmcSysAxiOp.READ, f"rd_{label}", addr, length=length, token=token, obs=obs
        )
        return value

    async def _wr(self, label, addr, data, token, *, port="SEP", length=8, obs=False):
        code, _ = await self._acc(
            port, SmcSysAxiOp.WRITE, f"wr_{label}", addr, data, length, token=token, obs=obs
        )
        return code

    @staticmethod
    def _rt_fields(value: int | None) -> dict:
        if value is None:
            return {}
        return {
            "value": (value & TIMEOUT_VALUE_BM),
            "mode": int(bool(value & TIMEOUT_MODE_BM)),
            "applied": int(bool(value & RESET_APPLIED_BM)),
            "flag": int(bool(value & RESET_TIMEOUT_BM)),
        }

    async def _rt(self, label: str, token: str, port: str = "SEP") -> dict:
        value = await self._rd(f"RESET_TIMEOUT_{label}", RESET_TIMEOUT, token, port=port)
        fields = self._rt_fields(value)
        self.rt_reads.append(
            (label, fields, {"SEP": "SEP_IN", "SYS": "SYS_IN", "JTAG": "JTAG_IN"}[port])
        )
        return fields

    async def _wdt_write(self, label: str, addr: int, value: int, token: str) -> None:
        await self._wr(f"{label}_KEY", WDT3_KEY, WDT_MAGIC_KEY, token, length=4)
        await self._wr(label, addr, value, token, length=4)

    async def _status_point(self, label: str, since: int, want: dict, port: str = "SEP"):
        """RESET_TIMEOUT and CORE_RESET_PULSE_COUNT read at one point of an episode: graded
        when no request of any manager is stalled at the front port since `since` and no bench
        hold is active, else one RESET_TIMEOUT read recorded as
        OBS-STATUS-READ-UNDER-STALL with a bounded observation wait. Returns the graded
        RESET_TIMEOUT fields, or None for an observation."""
        stalled, holds = self._stalled(since)
        if stalled or holds:
            axi_id = None if port == "JTAG" else STALL_ID_BASE + len(self.stall_reads)
            raw = self._raw(
                port, SmcSysAxiOp.READ, f"{label}_status_under_stall", RESET_TIMEOUT, axi_id=axi_id
            )
            self.stall_reads.append((raw, stalled, holds))
            await self._join(raw, TOKEN_STATUS, obs=True, bound_ns=OBS_AXI_BOUND_NS, obs_wait=True)
            return None
        fields = await self._rt(label, TOKEN_STATUS, port=port)
        pc = await self._rd(f"PULSE_COUNT_{label}", PULSE_COUNT, TOKEN_STATUS, port=port)
        self.graded_status.append((label, port, fields, pc, want))
        return fields

    async def _drain_stall_reads(self) -> None:
        """Bounded observation join of every status read still open from a stalled point."""
        for raw, _stalled, _holds in self.stall_reads:
            if not raw.event.is_set():
                await self._join(
                    raw, TOKEN_STATUS, obs=True, bound_ns=OBS_AXI_BOUND_NS, obs_wait=True
                )

    @staticmethod
    def _fields_text(fields: dict) -> str:
        return ",".join(f"{k}:{v}" for k, v in fields.items()) or "none"

    def _stall_lines(self) -> list[str]:
        names = {"SEP": "SEP_IN", "SYS": "SYS_IN", "JTAG": "JTAG_IN"}
        out = []
        for raw, stalled, holds in self.stall_reads:
            done = "never" if raw.done_at is None else str(raw.done_at)
            code, value = self._result(raw)
            out.append(
                f"OBS-STATUS-READ-UNDER-STALL: port={names[raw.port]} completed={done} "
                f"stalled_request={'+'.join(stalled) or 'none'} hold={'+'.join(holds) or 'none'} "
                f"label={raw.label} issued={raw.issued} resp={self._code_text(code)} "
                f"fields={self._fields_text(self._rt_fields(value))} sf=SF-026"
            )
        return out

    # --- shared episode steps ------------------------------------------------------------------
    async def _write_rc(self, label: str, value: int, token: str) -> tuple[int, int]:
        """RESET_CTRL write over SEP_IN; (sample index at the issue, at the response)."""
        issue = self.n
        await self._wr(label, RESET_CTRL, value, token)
        return issue, self.n

    async def _release_holds(self) -> None:
        """Drop the bench holds at a falling edge, so the DUT and the SVA see the same
        rising edge as the first one without the hold."""
        dut = cocotb.top
        await FallingEdge(dut.clk_smc_i)
        for name in ("tb_sep_axi_r_hold", "tb_sys_axi_r_hold", "tb_output_axi_resp_hold"):
            getattr(dut, name).value = 0

    def _front_reads(self, count: int, tag: str) -> list:
        rd = SmcSysAxiOp.READ
        return [
            self._raw(
                "SEP",
                rd,
                f"{tag}_rd{k}",
                SCRATCH_REF_BASE + 8 * k,
                length=8,
                beats=BURST_BEATS,
                axi_id=PEND_ID + k,
            )
            for k in range(count)
        ]

    async def _wait_pending(self, tag: str, token: str, since: int, count: int) -> int | None:
        return await self._poll(
            f"{tag}.pending",
            token,
            PENDING_BOUND,
            lambda: self._armed(since, count),
            lambda: (
                f"front AR handshakes {self._front_ar(since, self.n)} for {count} reads; "
                f"raw R valid {self._g('tb_sep_axi_r_raw_valid')}; {self._state()}"
            ),
        )

    async def _wait_reset_applied(self, tag: str, token: str) -> dict:
        drained = await self._poll(
            f"{tag}.drained",
            token,
            DRAIN_BOUND,
            lambda: self._g("tb_cpu_drained") == 1,
            self._state,
        )
        applied = await self._poll(
            f"{tag}.applied",
            token,
            DRAIN_BOUND,
            lambda: self._g("tb_cpu_reset_applied") == 1,
            self._state,
        )
        uncore = await self._poll(
            f"{tag}.uncore_low",
            token,
            DRAIN_BOUND,
            lambda: self._g("tb_cpu_uncore_reset_n") == 0,
            self._state,
        )
        return {"drained": drained, "applied": applied, "uncore": uncore}

    async def _reconnect(self, tag: str, token: str) -> int | None:
        return await self._poll(
            f"{tag}.reconnect",
            token,
            RECONNECT_BOUND,
            lambda: self._g("tb_cpu_l2_isolated") == 0 and self._g("tb_cpu_uncore_reset_n") == 1,
            self._state,
        )

    # --- steps -----------------------------------------------------------------------------------
    async def _step(self, name: str, coro) -> None:
        cocotb.log.info("STEP %s start at sample %d", name, self.n)
        try:
            await coro
            cocotb.log.info("STEP %s end at sample %d", name, self.n)
        except AssertionError as exc:
            self.aborted.append(name)
            self._fail("CHK-NONVAC", f"step {name} aborted: {exc}")
            await self._recover()

    async def _recover(self) -> None:
        await self._release_holds()
        for _ in range(2):
            await self._wr(
                "RECOVER_RC", RESET_CTRL, self.rc_base, "CHK-NONVAC", port="SEP", obs=True
            )
            if (
                await self._poll(
                    "recover.uncore",
                    "CHK-NONVAC",
                    ISOLATE_BOUND,
                    lambda: (
                        self._g("tb_cpu_uncore_reset_n") == 1
                        and self._g("tb_cpu_core_resets_n") == 15
                    ),
                    self._state,
                )
                is not None
            ):
                return

    async def body(self) -> None:
        dut = cocotb.top
        for name in [n for _k, n in SAMPLED] + list(_EXTRA_NAMES):
            assert hasattr(dut, name), f"{name} is not a signal of the testbench top"
        self._sampler_task = cocotb.start_soon(self._sampler())
        try:
            await self._step("S1", self._s1_setup())
            await self._step("S2", self._s2_core_hold())
            await self._step("S3", self._s3_pulses())
            await self._step("S4", self._s4_timer_off())
            await self._step("S5", self._s5_give_up())
            await self._step("S6", self._s6_blocked())
            await self._s7_not_driven()
            await self._s8_not_driven()
            await self._step("S9", self._s9_cold())
        finally:
            await self._release_holds()
            self._sampler_stop = True
            await RisingEdge(dut.clk_smc_i)
        self._report()

    # S1 -------------------------------------------------------------------------------------------
    async def _s1_setup(self) -> None:
        T = "CHK-NONVAC"
        dut = cocotb.top
        await wait_fuse_sense_done(FUSE_SENSE_BOUND)
        self._bound("S1.fuse_sense", f"{FUSE_SENSE_BOUND}clk_smc_i", "sense done")
        for name in ("tb_sep_axi_r_hold", "tb_sys_axi_r_hold", "tb_output_axi_resp_hold"):
            assert self._g(name) == 0, f"S1: {name} is set outside a pending phase"
        assert self._g("rst_primary_smc_clk_no") == 1, "S1: the primary reset is asserted"
        await self.program_inbound_pass_all()
        await self.program_outbound_pass_all()
        await self._poll(
            "S1.cluster_boundary",
            T,
            COLD_BOUND,
            lambda: (
                self._g("tb_cpu_cluster_isolate") == 0
                and self._g("tb_cpu_l2_isolated") == 0
                and self._g("tb_cpu_mmio_isolated") == 0
            ),
            self._state,
        )
        sys_out_mem = self.cfg.sys_out_mem
        assert sys_out_mem is not None, "SYS_OUT responder not bound"
        sys_out_mem.write_int(EXT_ROUTE, EXT_ROUTE_WORD, 8)
        for k in range(REF_WORDS):
            addr = SCRATCH_REF_BASE + 8 * k
            await self._ref_word(f"REF{k}", addr)
        for k in range(3):
            await self._ref_word(f"BLOCK{k}", BLOCK_BASE + 8 * k)
        await self._ref_word("FRESH", FRESH_ADDR)
        await self._wdt_write("CMP_SET", WDT3_CMP, WDT_CMP_REF, T)
        got = await self._rd("CMP_SET_RB", WDT3_CMP, T, length=4)
        if got != WDT_CMP_REF:
            self._fail(T, f"S1: core-3 watchdog CMP reads {got}, wrote 0x{WDT_CMP_REF:x}")
        rc = await self._rd("RESET_CTRL_RESET", RESET_CTRL, T)
        rt = await self._rd("RESET_TIMEOUT_RESET", RESET_TIMEOUT, T)
        pc = await self._rd("PULSE_COUNT_RESET", PULSE_COUNT, T)
        want_rc = CORE_RESET_N_ALL | UNCORE_RESET_N
        if rc is None or rc & (want_rc | START_BITS) != want_rc:
            self._fail(
                T, f"S1: RESET_CTRL reads {rc}, expected core and uncore reset bits 1, starts 0"
            )
        if rt is None or rt & (
            TIMEOUT_VALUE_BM | TIMEOUT_MODE_BM | RESET_APPLIED_BM | RESET_TIMEOUT_BM
        ):
            self._fail(T, f"S1: RESET_TIMEOUT reads {rt}, expected every field 0")
        want_pc = (
            PRE_COUNT_RESET
            | (POST_COUNT_RESET << POST_COUNT_BP)
            | (RESETS_DONE_RESET << RESETS_DONE_BP)
        )
        if pc is None or pc & (PRE_COUNT_BM | POST_COUNT_BM | RESETS_DONE_BM) != want_pc:
            self._fail(T, f"S1: CORE_RESET_PULSE_COUNT reads {pc}, expected 0x{want_pc:x}")
        self.rc_base = rc if rc is not None else want_rc
        self.rc_base &= ~START_BITS
        self._stamp("SETUP", self.accesses)
        dut._log.info("S1: RESET_CTRL=0x%x RESET_TIMEOUT=%s PULSE_COUNT=%s", self.rc_base, rt, pc)

    async def _ref_word(self, label: str, addr: int) -> None:
        T = "CHK-NONVAC"
        data = REF_TAG | addr
        await self._wr(f"{label}_SET", addr, data, T)
        got = await self._rd(f"{label}_RB", addr, T)
        if got != data:
            self._fail(T, f"S1: {label} @0x{addr:x} reads {got}, wrote 0x{data:x}")

    def _core3(self) -> int:
        value = self._g("tb_cpu_core_resets_n")
        return -1 if value < 0 else (value >> 3) & 1

    @staticmethod
    def _burst_ref(addr: int, beats: int) -> int:
        return sum(((REF_TAG | (addr + 8 * b)) & ((1 << 64) - 1)) << (64 * b) for b in range(beats))

    def _grade(self, token: str, bad: list[str], text: str) -> None:
        if bad:
            self._fail(token, "; ".join(bad))
        else:
            self._ok(token, text)
        self._print(token, text)

    def _print(self, token: str, text: str) -> None:
        mine = [f.split(": ", 1)[1] for f in self.fails if f.split(":", 1)[0] == token]
        if mine:
            cocotb.log.info("%s: FAIL %s", token, "; ".join(mine))
        else:
            cocotb.log.info("%s: %s", token, text)
        self.printed.add(token)

    # S2 -------------------------------------------------------------------------------------------
    async def _s2_core_hold(self) -> None:
        T = "CHK-CORE-HOLD-NO-DRAIN"
        TW = "CHK-CORE3-WDT-CONFIG"
        TO = "CHK-OBS-CORE-RESET-ACCESS"
        bad: list[str] = []
        self.env.axi_monitor.expected_decerr_addrs.add(BEU3_ENABLE)
        rc = await self._rd("RESET_CTRL_S2", RESET_CTRL, T)
        assert rc is not None, "S2: the RESET_CTRL read had no response"
        held = rc & ~CORE3_RESET_N
        _issue, resp = await self._write_rc("CORE3_HELD", held, T)
        await self._poll("S2.core3_low", T, ASSERT_BOUND, lambda: self._core3() == 0, self._state)
        first = self._first("core", 0, resp, bit=3)
        assert first is not None, f"S2: the core 3 probe never read 0 ({self._state()})"
        rt_reads = [await self._rt("s2_start", T)]
        for port, addr, data in (
            ("SEP", PAIR_SEP_ADDR, PAIR_DATA[0]),
            ("SYS", PAIR_SYS_ADDR, PAIR_DATA[1]),
        ):
            await self._wr(f"S2_{port}_PAIR", addr, data, T, port=port)
            got = await self._rd(f"S2_{port}_PAIR", addr, T, port=port)
            if got != data:
                bad.append(f"{port} scratchpad read-back {got} after writing 0x{data:x}")
        held_rd_code, held_rd = await self._acc(
            "SEP", SmcSysAxiOp.READ, "rd_S2_BEU3_HELD", BEU3_ENABLE, token=TO, obs=True
        )
        held_wr = await self._wr("S2_BEU3_HELD", BEU3_ENABLE, 0xE6, TO, obs=True)
        cmp_held = await self._rd("S2_CMP_HELD", WDT3_CMP, TW, length=4)
        await self._until_rows(first + HOLD_EDGES_MID)
        rt_reads.append(await self._rt("s2_mid", T))
        await self._until_rows(first + HOLD_EDGES_END)
        rt_reads.append(await self._rt("s2_end", T))
        await self._until_rows(first + HOLD_EDGES + 2)
        end = first + HOLD_EDGES
        counts = {}
        for key, name in (
            ("isoreq", "isolate_req"),
            ("l2iso", "l2_isolated"),
            ("mmioiso", "mmio_isolated"),
            ("rto", "reset_timeout"),
            ("rap", "reset_applied"),
        ):
            good, total, first_bad = self._all(key, 0, first, end)
            counts[name] = (good, total)
            if good != total or total != HOLD_EDGES:
                bad.append(f"{name} reads 0 at {good}/{total} edges (first bad sample {first_bad})")
        good3, total3, bad3 = self._all("core", 0, first, end, bit=3)
        if good3 != total3 or total3 != HOLD_EDGES:
            bad.append(f"core 3 probe held {good3}/{total3} edges (first bad sample {bad3})")
        self.term.append(("hold", good3, total3))
        for rt in rt_reads:
            if rt.get("applied") != 0 or rt.get("flag") != 0:
                bad.append(f"RESET_TIMEOUT over SEP_IN reads {rt}")
        if cmp_held != WDT_CMP_REF:
            self._fail(
                TW, f"CMP reads {cmp_held} during the core 3 hold, expected 0x{WDT_CMP_REF:x}"
            )
        _i, resp_rel = await self._write_rc("CORE3_RELEASE", rc, T)
        up = await self._poll(
            "S2.core3_high", T, ASSERT_BOUND, lambda: self._core3() == 1, self._state
        )
        if up is None:
            bad.append("core 3 not released by RESET_CTRL.core3_reset_n")
        await self._edges(PULSE_TAIL_EDGES)
        rel = self._first("core", 1, resp_rel, bit=3)
        if rel is not None:
            goodr, totalr, _b = self._all("core", 1, rel, rel + PULSE_TAIL_EDGES, bit=3)
            self.term.append(("released", goodr, totalr))
            if goodr != totalr or totalr == 0:
                bad.append(f"core 3 probe reads 1 at {goodr}/{totalr} edges after the release")
        cmp_kept = await self._rd("S2_CMP_RELEASED", WDT3_CMP, TW, length=4)
        self.cmp_kept = cmp_kept
        rel_rd_code, rel_rd = await self._acc(
            "SEP", SmcSysAxiOp.READ, "rd_S2_BEU3_RELEASED", BEU3_ENABLE, token=TO, obs=True
        )
        rel_wr = await self._wr("S2_BEU3_RELEASED", BEU3_ENABLE, 0xE6, TO, obs=True)
        self.obs["core"].append(
            f"OBS-CORE-RESET-ACCESS: held rd={self._code_data(held_rd_code, held_rd)} "
            f"wr={self._code_text(held_wr)}; released rd={self._code_data(rel_rd_code, rel_rd)} "
            f"wr={self._code_text(rel_wr)} sf=SF-022,SF-038"
        )
        self._grade(
            T,
            bad,
            f"core3 held {good3}/{total3} edges; isolate_req/l2_isolated/mmio_isolated 0 at "
            f"{counts['isolate_req'][0]}/{counts['isolate_req'][1]}, "
            f"{counts['l2_isolated'][0]}/{counts['l2_isolated'][1]}, "
            f"{counts['mmio_isolated'][0]}/{counts['mmio_isolated'][1]}; reset_applied 0, "
            f"reset_timeout 0; SEP_IN and SYS_IN pairs OKAY",
        )
        self._stamp("CORE_HOLD", total3)

    @staticmethod
    def _code_text(code) -> str:
        return "none" if code is None else str(code)

    @staticmethod
    def _code_data(code, data) -> str:
        return f"{'none' if code is None else code},{'none' if data is None else hex(data)}"

    # S3 -------------------------------------------------------------------------------------------
    async def _s3_pulses(self) -> None:
        T = "CHK-CORE-PULSE"
        bad: list[str] = []
        rc = await self._rd("RESET_CTRL_S3", RESET_CTRL, T)
        assert rc is not None, "S3: the RESET_CTRL read had no response"
        base = rc & ~START_BITS
        # pulse a: reset pulse counts
        _i, resp = await self._write_rc("PULSE_A_START", base | CORE3_PULSE_START, T)
        up = await self._poll(
            "pulse_a.assert", T, PULSE_BOUND, lambda: self._core3() == 0, self._state
        )
        if up is not None:
            await self._poll(
                "pulse_a.release", T, PULSE_BOUND, lambda: self._core3() == 1, self._state
            )
        await self._edges(PULSE_TAIL_EDGES)
        runs_a = self._runs("core", 3, 0, resp, self.n)
        if runs_a != [PULSE_WIDTH_RESET]:
            bad.append(f"core 3 probe zero runs {runs_a} after the start write, expected [17]")
        after = await self._rd("RESET_CTRL_AFTER_PULSE", RESET_CTRL, T)
        if after is None or after & START_BITS:
            bad.append(f"RESET_CTRL start bits read {after} after a start write")
        rmw = await self._rd("RESET_CTRL_RMW", RESET_CTRL, T)
        rmw_start = None if rmw is None else rmw & START_BITS
        _i, resp2 = await self._write_rc("PULSE_RMW", base if rmw is None else rmw, T)
        await self._edges(RMW_EDGES)
        rmw_zero = sum(self._runs("core", 3, 0, resp2, self.n))
        if rmw_zero or rmw_start:
            bad.append(
                f"read-modify-write: start bits read {rmw_start}, {rmw_zero} samples of the core "
                f"3 probe at 0 in the following {RMW_EDGES} edges"
            )
        # pulse b: long post-reset count, polled over SEP_IN
        long_count = PRE_COUNT_RESET | (PULSE_POST_LONG << POST_COUNT_BP)
        await self._wr("PULSE_COUNT_LONG", PULSE_COUNT, long_count, T)
        _i, resp = await self._write_rc("PULSE_B_START", base | CORE3_PULSE_START, T)
        up = await self._poll(
            "pulse_b.assert", T, PULSE_BOUND, lambda: self._core3() == 0, self._state
        )
        during = []
        while up is not None and self._core3() == 0 and len(during) < 64:
            p0 = self._core3()
            value = await self._rd("PULSE_COUNT_RUN", PULSE_COUNT, T)
            during.append((p0, self._core3(), value))
        if up is not None:
            await self._poll(
                "pulse_b.release", T, PULSE_BOUND, lambda: self._core3() == 1, self._state
            )
        value_after = await self._rd("PULSE_COUNT_AFTER", PULSE_COUNT, T)
        await self._edges(PULSE_TAIL_EDGES)
        runs_b = self._runs("core", 3, 0, resp, self.n)
        if runs_b != [PULSE_POST_LONG + 1]:
            bad.append(
                f"core 3 probe zero runs {runs_b} with post_reset_count 0xFF, expected [256]"
            )
        inside = [v for p0, p1, v in during if p0 == 0 and p1 == 0 and v is not None]
        if not inside:
            bad.append("no CORE_RESET_PULSE_COUNT read completed inside the long pulse")
        if any(v & RESETS_DONE_CORE3 for v in inside):
            bad.append(f"core_resets_done[3] reads 1 inside the pulse: {[hex(v) for v in inside]}")
        if value_after is None or not value_after & RESETS_DONE_CORE3:
            bad.append(f"core_resets_done[3] reads 0 after the pulse: {value_after}")
        # pulse c: core 3 held through the pulse
        _i, resp = await self._write_rc(
            "PULSE_C_START", (base & ~CORE3_RESET_N) | CORE3_PULSE_START, T
        )
        await self._poll("pulse_c.low", T, PULSE_BOUND, lambda: self._core3() == 0, self._state)
        first_c = self._first("core", 0, resp, bit=3)
        await self._edges(PULSE_HOLD_EDGES)
        if first_c is None:
            bad.append("core 3 probe never read 0 with core3_reset_n 0 and the start bit written")
        else:
            good, total, bad_i = self._all("core", 0, first_c, first_c + PULSE_HOLD_EDGES, bit=3)
            self.term.append(("pulse_hold", good, total))
            if good != total or total != PULSE_HOLD_EDGES:
                bad.append(
                    f"core 3 probe held {good}/{total} edges through the pulse with core3_reset_n "
                    f"0 (first bad sample {bad_i})"
                )
        await self._write_rc("PULSE_C_RELEASE", base, T)
        up = await self._poll(
            "pulse_c.high", T, PULSE_BOUND, lambda: self._core3() == 1, self._state
        )
        if up is None:
            bad.append("core 3 not released by core3_reset_n after the pulse")
        restore = PRE_COUNT_RESET | (POST_COUNT_RESET << POST_COUNT_BP)
        await self._wr("PULSE_COUNT_RESTORE", PULSE_COUNT, restore, T)
        # pulse d: a start bit written twice back to back (restart observation)
        _i, r1 = await self._write_rc("PULSE_D_FIRST", base | CORE3_PULSE_START, T)
        _i, r2 = await self._write_rc("PULSE_D_RESTART", base | CORE3_PULSE_START, T)
        up = await self._poll(
            "pulse_d.assert", T, PULSE_BOUND, lambda: self._core3() == 0, self._state
        )
        if up is not None:
            await self._poll(
                "pulse_d.release", T, PULSE_BOUND, lambda: self._core3() == 1, self._state
            )
        await self._edges(PULSE_TAIL_EDGES)
        a_d = self._first("core", 0, r1, bit=3)
        self.notes["restart"] = (
            None if a_d is None else a_d - r2,
            self._runs("core", 3, 0, r1, self.n),
            r2 - r1,
        )
        self._grade(
            T,
            bad,
            f"held width {runs_a[0] if runs_a else None} and "
            f"{runs_b[0] if runs_b else None} samples; core_resets_done[3]=0 during "
            f"({len(inside)} reads), 1 after; start bits read 0; RMW no new pulse "
            f"({RMW_EDGES} edges); core3_reset_n=0 holds through the pulse",
        )
        self._stamp("PULSE", sum(runs_a) + sum(runs_b))

    # S4 -------------------------------------------------------------------------------------------
    async def _arm_four(self, tag: str, token: str):
        """Hold R on SEP_IN and park four single-beat reads in the L2 frontend."""
        await FallingEdge(cocotb.top.clk_smc_i)
        cocotb.top.tb_sep_axi_r_hold.value = 1
        since = self.n
        reads = self._front_reads(4, tag)
        await self._wait_pending(tag, token, since, 4)
        return since, reads

    def _window(self, tag: str, a: int, b: int) -> None:
        self.valid_windows.append((tag, a, b))

    async def _s4_timer_off(self) -> None:
        T1 = "CHK-TIMER-OFF-WAITS"
        T2 = "CHK-L2F-FOUR-OUTSTANDING"
        TP = "CHK-OBS-PULSE-AND-STATUS"
        await self._wr("RESET_TIMEOUT_OFF", RESET_TIMEOUT, 0, T1)
        bad1: list[str] = []
        bad2: list[str] = []
        since, reads = await self._arm_four("S4a", T1)
        pending0 = self._g("tb_cpu_l2_pending_ar")
        trace = []
        for i in range(since, self.n):
            v = (self._c("l2par", i), self._c("fv", i) >> 3 & 1, self._c("fr", i) >> 3 & 1)
            if not trace or trace[-1][1:] != (v,) and trace[-1][1] != v:
                trace.append((i, v))
        cocotb.log.info(
            "S4a: (l2par, front arvalid, front arready) changes from the reads: %s", trace[:20]
        )
        if pending0 <= 0:
            bad1.append(f"tb_cpu_l2_pending_ar reads {pending0} before the uncore bit is cleared")
        iss, resp = await self._write_rc("S4a_UNCORE_CLEAR", self.rc_base & ~UNCORE_RESET_N, T1)
        self._calibrate_front_ids(since, iss)
        iso = await self._poll(
            "S4a.isolate_req",
            T1,
            ISOLATE_BOUND,
            lambda: self._g("tb_cpu_isolate_req") == 1,
            self._state,
        )
        fifth = self._raw(
            "SEP",
            SmcSysAxiOp.READ,
            "S4a_fifth_rd",
            SCRATCH_REF_BASE + 32,
            length=8,
            beats=BURST_BEATS,
            axi_id=FIFTH_ID,
        )
        await self._until_rows(resp + TIMER_OFF_EDGES + 2)
        end = resp + TIMER_OFF_EDGES
        for key, val, name in (
            ("unc", 1, "uncore_reset_n"),
            ("rap", 0, "reset_applied"),
            ("drn", 0, "drained"),
            ("rto", 0, "reset_timeout"),
        ):
            good, total, first_bad = self._all(key, val, resp, end)
            if good != total or total != TIMER_OFF_EDGES:
                bad1.append(
                    f"{name} reads {val} at {good}/{total} edges of the window (first bad sample "
                    f"{first_bad}); reset not withheld"
                )
        a_idx = self._first("isoreq", 1, iss)
        if iso is None or a_idx is None:
            bad1.append("tb_cpu_isolate_req never rose")
        else:
            good, total, first_bad = self._all("isoreq", 1, a_idx, end)
            if good != total:
                bad1.append(f"isolate_req falls inside the window at sample {first_bad}")
        await self._release_holds()
        await self._wait_reset_applied("S4a", T1)
        res_idx = self._first("unc", 0, iss)
        if res_idx is None:
            bad1.append("the uncore reset never applied after the reads completed")
        early = [r.event.is_set() for r in reads]
        self.drained_a = [self._result(r) for r in reads]
        if not any(early):
            bad1.append("no parked read completed before the reset applied")
        if self._g("tb_cpu_l2_pending_ar") != 0 and res_idx is not None:
            bad1.append("a read is still pending in the isolate after the reset applied")
        i_set, r_set = await self._write_rc("S4a_UNCORE_SET", self.rc_base, T1)
        await self._reconnect("S4a", T1)
        recon = self._first("l2iso", 0, r_set)
        for r, done in zip(reads, early):
            if not done:
                await self._join(r, T1, obs=True)
        cocotb.log.info(
            "S4a: parked reads completed before the reset applied %s, isolate pending peak %s",
            early,
            max((self._c("l2par", i) for i in range(since, self.n)), default=-1),
        )
        fifth_code, fifth_data = await self._join(fifth, T2)
        pend_vals = [self._c("l2par", i) for i in range(since, self.n)]
        pend_max = max(pend_vals, default=-1)
        if any(v < 0 for v in pend_vals):
            bad2.append("tb_cpu_l2_pending_ar reads X/Z in the episode")
        if pend_max > 4:
            bad2.append(f"tb_cpu_l2_pending_ar peaks at {pend_max}, above 4")
        want5 = self._burst_ref(SCRATCH_REF_BASE + 32, BURST_BEATS)
        if fifth_code != 0 or fifth_data != want5:
            bad2.append(
                f"fifth read completes resp={fifth_code} "
                f"data={None if fifth_data is None else hex(fifth_data)}, want 0x{want5:x}"
            )
        if recon is None or fifth.done_at is None or fifth.done_at < recon:
            bad2.append(
                f"fifth read answered at sample {fifth.done_at}, not after the reconnect@{recon}"
            )
        a0 = a_idx if a_idx is not None else iss
        fifth_ar = self._ar_presented(fifth, a0, recon or self.n, "isoreq")
        if fifth_ar is None:
            bad2.append(
                f"fifth read ARVALID not sampled high on 0x{fifth.addr:x} with isolate_req 1 "
                f"between isolate_req@{a_idx} and the reconnect@{recon}"
            )
        front_after = self._front_ar(a0, self.n)
        fifth_front = self._front_id(FIFTH_ID)
        if fifth_front is None:
            ar5 = "unattributed:" + (",".join(f"{i}/0x{x:02x}" for i, x in front_after) or "none")
        else:
            hits = [i for i, x in self._front_ar(since, self.n) if x == fifth_front]
            ar5 = ",".join(str(i) for i in hits) or "none"
        cocotb.log.info(
            "S4a: front-port AR (sample:ARID) from isolate_req@%s: %s; parked front IDs %s; "
            "applied@%s reconnect@%s; fifth answered at sample %s",
            a_idx,
            " ".join(f"{i}:0x{x:02x}" for i, x in front_after) or "none",
            [hex(x) for x in self.front_ids],
            res_idx,
            recon,
            fifth.done_at,
        )
        obs5 = (
            f"OBS-L2F-FIFTH-READ: front_ar_sample={ar5} isolate_req={a_idx} applied={res_idx} "
            f"reconnect={recon} sf=SF-005"
        )
        self.obs_lines.append(obs5)
        text2 = (
            f"max pending AR {pend_max} <= 4; fifth read (FIFTH_ID) presented while isolated "
            f"(SEP_IN ARVALID on its address at sample {fifth_ar}, isolate_req 1, reconnect@"
            f"{recon}) and completed after reconnect (answered at sample {fifth.done_at}) with "
            f"its reference data | {obs5}"
        )
        released = self._first("unc", 0, iss)
        self._window("S4a", iss, (recon or self.n) + 1)
        self._grade(
            T1,
            bad1,
            f"{TIMER_OFF_EDGES} edges withheld, reset_timeout 0, applied 0; reset applied after "
            f"release",
        )
        self._grade(T2, bad2, text2)
        self._stamp("TIMER_OFF", len(self._hs("ar", since, since + 400)))
        self.ep_s4 = SimpleNamespace(since=since, iss=iss, res=released, reads=reads)

        # second timer-off episode with a core 3 pulse started just before the uncore bit clears
        since2, reads2 = await self._arm_four("S4b", T1)
        _i, r1 = await self._write_rc("S4b_PULSE_START", self.rc_base | CORE3_PULSE_START, TP)
        iss2, _r2 = await self._write_rc("S4b_UNCORE_CLEAR", self.rc_base & ~UNCORE_RESET_N, TP)
        await self._edges(PULSE_HOLD_EDGES // 4)
        await self._release_holds()
        await self._wait_reset_applied("S4b", TP)
        early2 = [r.event.is_set() for r in reads2]
        _i, r_set2 = await self._write_rc("S4b_UNCORE_SET", self.rc_base, TP)
        await self._reconnect("S4b", TP)
        recon2 = self._first("l2iso", 0, r_set2)
        for r, done in zip(reads2, early2):
            if not done:
                await self._join(r, TP, obs=True)
        events = {
            "core3_low": self._first("core", 0, r1, bit=3),
            "isolate_req": self._first("isoreq", 1, iss2),
            "drained": self._first("drn", 1, iss2),
            "uncore_low": self._first("unc", 0, iss2),
            "applied": self._first("rap", 1, iss2),
        }
        order = " < ".join(
            f"{k}@{v}" for k, v in sorted(events.items(), key=lambda kv: (kv[1] is None, kv[1]))
        )
        self.notes["pulse_vs_uncore"] = order
        self._window("S4b", iss2, (recon2 or self.n) + 1)

    # S5 -------------------------------------------------------------------------------------------
    async def _s5_give_up(self) -> None:
        T = "CHK-GIVEUP-REPORT-AND-WAIT"
        TH = "CHK-DRAIN-HANDSHAKE-ORDER"
        TP = "CHK-DRAIN-PENDING-READS-COMPLETE"
        TE = "CHK-OBS-TIMEOUT-EXPIRY"
        bg: list[str] = []
        bh: list[str] = []
        bp: list[str] = []
        await self._wr("RESET_TIMEOUT_GIVEUP", RESET_TIMEOUT, TIMEOUT_CYCLES, T)
        since, reads = await self._arm_four("S5", T)
        iss, resp = await self._write_rc("S5_UNCORE_CLEAR", self.rc_base & ~UNCORE_RESET_N, T)
        await self._poll(
            "S5.isolate_req",
            TH,
            ISOLATE_BOUND,
            lambda: self._g("tb_cpu_isolate_req") == 1,
            self._state,
        )
        await self._poll(
            "S5.reset_timeout",
            T,
            TIMEOUT_BOUND,
            lambda: self._g("tb_cpu_reset_timeout") == 1,
            self._state,
        )
        rise = self._first("rto", 1, iss)
        # The withheld point comes from the probes; a status read issued now is under the hold.
        want_s5 = {"value": TIMEOUT_CYCLES, "mode": 0}
        await self._status_point("s5_expired", since, want_s5, port="SYS")
        probe_end = self.n
        if rise is None:
            bg.append("tb_cpu_reset_timeout never rose with timeout_value 64")
        else:
            for key, val, name in (
                ("rto", 1, "reset_timeout"),
                ("rap", 0, "reset_applied"),
                ("unc", 1, "uncore_reset_n"),
                ("drn", 0, "drained"),
            ):
                good, total, first_bad = self._all(key, val, rise, probe_end)
                if good != total or total == 0:
                    bg.append(
                        f"{name} probe reads {val} at {good}/{total} samples after the expiry "
                        f"(first bad sample {first_bad}); reset not withheld"
                    )
        hrel = self.n
        await self._release_holds()
        await self._wait_reset_applied("S5", T)
        a = self._first("isoreq", 1, iss)
        b = self._first("drn", 1, a if a is not None else iss)
        res = self._first("unc", 0, iss)
        app = self._first("rap", 1, iss)
        cc = self._first("core", 0, iss)
        # per parked read: front-port AR and RLAST by ID, SEP_IN RLAST
        front_ar = self._front_ar(since, a if a is not None else iss)
        front_rl = self._front_rlast(since, self.n)
        per = []
        for k in range(4):
            fid = self._front_id(PEND_ID + k)
            per.append(
                SimpleNamespace(
                    k=k,
                    far=None if fid is None else next((i for i, x in front_ar if x == fid), None),
                    frl=None if fid is None else next((i for i, x in front_rl if x == fid), None),
                    srl=next(iter(self._sep_r_done(since, self.n, {PEND_ID + k})), None),
                )
            )
        upto = res if res is not None else self.n
        pend_vals = [self._c("l2par", x) for x in range(since, upto)]
        pend_peak = max(pend_vals, default=-1)
        accepted = sorted((p for p in per if p.far is not None), key=lambda p: p.far)
        n_counted = max(0, min(pend_peak, len(accepted)))
        counted = accepted[:n_counted]
        not_pending = accepted[n_counted:]
        if self.front_prefix is None:
            bp.append("the front-port IDs of the parked reads are not bound; no read attributed")
        elif len(accepted) != 4:
            bp.append(
                f"{len(accepted)} front-port AR handshakes of the four parked reads before "
                f"isolate_req@{a}"
            )
        if any(v < 0 for v in pend_vals) or pend_peak < 1:
            bp.append(f"tb_cpu_l2_pending_ar peaks at {pend_peak} (X/Z or no pending read)")
        # handshake order
        if None in (a, b, res, cc):
            bh.append(f"events missing: isolate_req@{a} drained@{b} uncore@{res} core@{cc}")
        else:
            if self._c("unc", a) != 1:
                bh.append(f"uncore reset already asserted at isolate_req@{a}")
            if not a < b <= res:
                bh.append(f"order isolate_req@{a} drained@{b} uncore@{res}")
            if cc != res:
                bh.append(f"core reset@{cc} not in the sample of the uncore reset@{res}")
        # drain claims count only the isolate-pending reads the bench had released
        rel0 = self._first("sh", 0, hrel)
        bench_held = []
        late_d, late_a = [], []
        for edge, late in ((b, late_d), (res, late_a)):
            if edge is None or rel0 is None:
                continue
            held = self._held(rel0, edge)
            for p in counted:
                if p.frl is not None and p.frl < edge:
                    continue
                if held:
                    bench_held.append(
                        f"OBS-DRAIN-BENCH-HELD: read={p.k} rlast={self._opt(p.frl)} "
                        f"hold_release={hrel} drained={b} held_samples={held[:3]}"
                    )
                else:
                    late.append((p.k, p.frl))
        if rel0 is None:
            bp.append(f"tb_sep_axi_r_hold never read 0 after the release at sample {hrel}")
        self.obs_lines.extend(dict.fromkeys(bench_held))
        if late_d:
            bh.append(
                f"drained@{b} before the front-port RLAST of isolate-pending released reads "
                f"{late_d} (read, RLAST sample); holds 0 from sample {rel0}"
            )
        if late_a:
            bp.append(
                f"uncore reset applied@{res} before the front-port RLAST of isolate-pending "
                f"released reads {late_a} (read, RLAST sample); holds 0 from sample {rel0}"
            )
        r_n = sum(1 for p in counted if p.frl is not None and res is not None and p.frl < res)
        cocotb.log.info(
            "S5: parked reads (read, front AR, front RLAST, SEP_IN RLAST) %s; isolate-pending "
            "%s, front-port-accepted-not-pending %s; isolate_req@%s drained@%s applied@%s "
            "uncore@%s; hold release@%s (holds 0 from %s); pending peak %s",
            [(p.k, p.far, p.frl, p.srl) for p in per],
            [p.k for p in counted],
            [p.k for p in not_pending],
            a,
            b,
            app,
            res,
            hrel,
            rel0,
            pend_peak,
        )
        # status after the drain: graded only with no stalled request, else an observation
        link = "SEP" if all(r.event.is_set() for r in reads) else "JTAG"
        await self._status_point("s5_applied", since, dict(want_s5, applied=1, flag=1), link)
        await self._edges(GIVE_UP_KEEP_EDGES)
        i_set, r_set = await self._write_rc("S5_UNCORE_SET", self.rc_base, T)
        await self._reconnect("S5", TH)
        recon = self._first("l2iso", 0, r_set)
        # probe facts of the applied state, held until the bit is set
        if app is None:
            bg.append("tb_cpu_reset_applied never rose after the drain")
        else:
            for key, name, start in (("rap", "reset_applied", app), ("rto", "reset_timeout", app)):
                good, total, first_bad = self._all(key, 1, start, i_set)
                if good != total or total == 0:
                    bg.append(
                        f"{name} probe reads 1 at {good}/{total} samples from the apply to the "
                        f"bit set (first bad sample {first_bad})"
                    )
            good, total, first_bad = self._all("rap", 1, app, i_set)
            if good != total or total == 0:
                bh.append(f"reset_applied probe falls at sample {first_bad} while applied")
        if rise is not None:
            good, total, first_bad = self._all("rto", 1, rise, i_set)
            if good != total:
                bg.append(f"reset_timeout falls at sample {first_bad} while the request stays")
        if a is not None:
            good, total, first_bad = self._all("isoreq", 1, a, i_set)
            if good != total:
                bh.append(f"isolate_req falls at sample {first_bad} before the bit is set")
        if recon is None:
            bh.append("no reconnect after the uncore bit was set")
        # the reads the isolate never counted complete only after the reconnect
        for p in not_pending:
            code, value = await self._join(reads[p.k], TP)
            want = self._burst_ref(SCRATCH_REF_BASE + 8 * p.k, BURST_BEATS)
            done = reads[p.k].done_at
            after = recon is not None and done is not None and done >= recon
            ok = code == 0 and value == want and after
            if not ok:
                bp.append(
                    f"front-port-accepted-not-pending read {p.k} answered at sample {done} "
                    f"(reconnect@{recon}) resp={code} "
                    f"data={None if value is None else hex(value)}, want 0x{want:x}"
                )
            self.obs_lines.append(
                f"OBS-DRAIN-FRONTPORT-ACCEPTED-NOT-PENDING: read={p.k} front_ar_sample={p.far} "
                f"isolate_req={a} pending_peak={pend_peak} rlast={self._opt(p.frl)} "
                f"completed_after_reconnect={'yes' if ok else 'no'} sf=SF-005,SF-006"
            )
        for r in reads:
            if not r.event.is_set():
                await self._join(r, TP, obs=True)
        self.drained_b = [self._result(r) for r in reads]
        await self._drain_stall_reads()
        await self._status_point("s5_reconnected", since, dict(want_s5, applied=0), port="SEP")
        self._grade(
            T,
            bg,
            f"expired: timeout=1 applied=0 withheld (probes, {probe_end - (rise or 0)} samples "
            f"from the expiry); after drain: applied=1 timeout=1 (probes, "
            f"{i_set - (app or i_set)} samples) until bit set",
        )
        self._grade(
            TH,
            bh,
            f"isolate_req@{a} < drained@{b} <= uncore_reset@{res} == core_reset@{cc}; isolate_req "
            f"held until bit set; reset_applied 1 (probe from {app}); reconnect@{recon}; "
            f"isolate-pending reads {[p.k for p in counted]} front-port RLAST "
            f"{[p.frl for p in counted]} before drained",
        )
        self._grade(
            TP,
            bp,
            f"isolate-pending reads AR {len(counted)} R {r_n} before reset applied (front-port "
            f"RLAST {[p.frl for p in counted]}, SEP_IN RLAST {[p.srl for p in counted]}, uncore "
            f"reset@{res}, holds 0 from sample {rel0}, pending peak {pend_peak}); "
            f"front-port-accepted-not-pending {len(not_pending)} completed after reconnect",
        )
        if rise is not None:
            self.obs["expiry"].append(
                f"OBS-RESET-TIMEOUT-EXPIRY: value={TIMEOUT_CYCLES} from_write={rise - resp} "
                f"from_isolate_req={rise - (a if a is not None else iss)} sf=SF-028"
            )
        else:
            self._fail(TE, "no expiry edge observed")
        self.notes["pend_peak"] = pend_peak
        self._window("S5", iss, (recon or self.n) + 1)
        self._stamp("GIVE_UP", len(front_ar))

    @staticmethod
    def _opt(value) -> str:
        return "none" if value is None else str(value)

    # S6 -------------------------------------------------------------------------------------------
    async def _s6_blocked(self) -> None:
        T = "CHK-BLOCKED-NOT-TERMINATED-THEN-RECONNECT"
        TW = "CHK-CORE3-WDT-CONFIG"
        TO = "CHK-OBS-PULSE-AND-STATUS"
        bad: list[str] = []
        await self._wr("RESET_TIMEOUT_NOTIMER", RESET_TIMEOUT, 0, T)
        await self._wdt_write("CMP_PRE_UNCORE", WDT3_CMP, WDT_CMP_REF, TW)
        cmp_pre = await self._rd("CMP_PRE_UNCORE_RB", WDT3_CMP, TW, length=4)
        if cmp_pre != WDT_CMP_REF:
            self._fail(TW, f"CMP reads {cmp_pre} before the software uncore reset")
        iss, resp = await self._write_rc("S6_UNCORE_CLEAR", self.rc_base & ~UNCORE_RESET_N, T)
        await self._poll(
            "S6.isolated_applied",
            T,
            DRAIN_BOUND,
            lambda: (
                self._g("tb_cpu_l2_isolated") == 1
                and self._g("tb_cpu_uncore_reset_n") == 0
                and self._g("tb_cpu_reset_applied") == 1
            ),
            self._state,
        )
        iso_first = self._first("l2iso", 1, iss)
        want_s6 = {"value": 0, "mode": 0}
        await self._status_point("s6_applied", iss, dict(want_s6, applied=1))
        rd = SmcSysAxiOp.READ
        wb = []
        wb_reads = [
            self._raw("SEP", rd, f"S6_wb_pc{i}", _wb_pc_core0(i), axi_id=WB_ID + i)
            for i in range(8)
        ]
        for raw in wb_reads:
            _code, value = await self._join(raw, TO)
            wb.append(value)
        self.notes["wb_pc"] = wb
        w0 = self.n
        blocked = [
            self._raw("SEP", rd, "S6_sep_rd", BLOCK_BASE, axi_id=BLOCK_ID[0]),
            self._raw("SYS", rd, "S6_sys_rd", BLOCK_BASE + 8, axi_id=BLOCK_ID[1]),
            self._raw("JTAG", rd, "S6_jtag_rd", BLOCK_BASE + 16, axi_id=BLOCK_ID[2]),
        ]
        await self._until_rows(w0 + BLOCK_EDGES + 2)
        end = w0 + BLOCK_EDGES
        resp_samples = {"SEP R": 0, "SEP B": 0, "SYS R": 0, "SYS B": 0, "JTAG R": 0, "JTAG B": 0}
        for i in range(w0, end):
            if self._c("srv", i) == 1 and self._c("srid", i) == BLOCK_ID[0]:
                resp_samples["SEP R"] += 1
            resp_samples["SEP B"] += int(self._c("sbv", i) == 1)
            resp_samples["SYS R"] += int(self._c("yrv", i) == 1)
            resp_samples["SYS B"] += int(self._c("ybv", i) == 1)
            resp_samples["JTAG R"] += int(self._c("jrv", i) == 1)
            resp_samples["JTAG B"] += int(self._c("jbv", i) == 1)
        if any(resp_samples.values()):
            bad.append(f"response samples inside the {BLOCK_EDGES}-edge window: {resp_samples}")
        if any(raw.event.is_set() for raw in blocked):
            bad.append("a blocked read completed while the boundary was isolated")
        good, total, first_bad = self._all("l2iso", 1, w0, end)
        if good != total:
            bad.append(f"l2_isolated drops inside the window at sample {first_bad}")
        presented = {raw.port: self._ar_presented(raw, w0, end, "l2iso") for raw in blocked}
        for raw in blocked:
            if presented[raw.port] is None:
                bad.append(
                    f"{raw.port} blocked read ARVALID not sampled high on 0x{raw.addr:x} with "
                    f"l2_isolated 1 in samples {w0}..{end}"
                )
        good, total, first_bad = self._all("l2par", 0, w0, end)
        if good != total:
            bad.append(f"tb_cpu_l2_pending_ar leaves 0 at sample {first_bad}: a read was accepted")
        i_set, r_set = await self._write_rc("S6_UNCORE_SET", self.rc_base, T)
        await self._reconnect("S6", T)
        u0 = self._first("unc", 0, iss)
        ru = None if u0 is None else self._first("unc", 1, u0)
        if iso_first is not None:
            good, total, first_bad = self._all("l2iso", 1, iso_first, i_set)
            if good != total:
                bad.append(f"isolation drops at sample {first_bad} while the uncore bit is 0")
        l2_fall = None if ru is None else self._first("l2iso", 0, ru)
        mm_fall = None if ru is None else self._first("mmioiso", 0, ru)
        self.notes["sw_iso"] = (
            None if l2_fall is None else l2_fall - ru,
            None if mm_fall is None else mm_fall - ru,
        )
        for k, raw in enumerate(blocked):
            code, value = await self._join(raw, T)
            want = REF_TAG | (BLOCK_BASE + 8 * k)
            if code != 0 or value != want:
                bad.append(
                    f"{raw.port} blocked read completes resp={code} data={value}, want 0x{want:x}"
                )
        fresh = await self._rd("S6_fresh", FRESH_ADDR, T)
        if fresh != REF_TAG | FRESH_ADDR:
            bad.append(f"fresh SEP_IN read returns {fresh}")
        await self._drain_stall_reads()
        await self._status_point("s6_reconnected", iss, dict(want_s6, applied=0))
        cmp_after = await self._rd("S6_CMP_AFTER", WDT3_CMP, TW, length=4)
        count_after = await self._rd("S6_WDT_COUNT", WDT3_COUNT, TW, length=4)
        self.notes["wdt_count"] = count_after
        self.cmp_after = cmp_after
        self._window("S6", iss, (l2_fall or self.n) + 1)
        self._grade(
            T,
            bad,
            f"3 managers presented while isolated (ARVALID on the read address with l2_isolated "
            f"1 at sample SEP {presented['SEP']} SYS {presented['SYS']} JTAG "
            f"{presented['JTAG']}, window {w0}..{end}), blocked {BLOCK_EDGES} edges, 0 "
            f"responses; after reconnect 3/3 completed with reference data; fresh read OK",
        )
        self._stamp("BLOCKED", len(blocked))

    # S7 -------------------------------------------------------------------------------------------
    async def _s7_not_driven(self) -> None:
        await RisingEdge(cocotb.top.clk_smc_i)
        codes = [self._code_text(c) for c, _v in self.drained_b]
        data = [("none" if v is None else f"0x{v & ((1 << 64) - 1):x}") for _c, v in self.drained_b]
        self.obs["flush"] += [
            "OBS-DRAIN-FLUSH-RESPONSES: episode=not-driven ruling=#2449",
            f"OBS-DRAIN-FLUSH-RESPONSES: episode=give_up drained rresp={','.join(codes)} "
            f"rdata={','.join(data)} sf=SF-006",
        ]
        cocotb.log.info(
            "INFO-CELL-NOT-DRIVABLE: force episode S7 (ruling #2449, covered by the pinned wedge "
            "leaves)"
        )
        self._stamp("FORCE", 1)

    # S8 -------------------------------------------------------------------------------------------
    async def _s8_not_driven(self) -> None:
        await RisingEdge(cocotb.top.clk_smc_i)
        self.obs["mmio"] = [
            "OBS-MMIO-RESET: episode=none items=0 not-driven sf=SF-004,SF-022,SF-035"
        ]
        cocotb.log.info("INFO-CELL-NOT-DRIVABLE: MMIO episodes (c-fw image not staged)")
        self._stamp("MMIO", 1)

    # S9 -------------------------------------------------------------------------------------------
    async def _dispatch_reset_item(self, item) -> None:
        await _OneShot(item, "reset_os").start(self.env.reset_agent.sequencer)

    async def _s9_cold(self) -> None:
        T = "CHK-COLD-ISOLATION-RELEASE"
        bad: list[str] = []
        await self._release_holds()
        start = self.n
        await self._send(SmcResetOp.COLD_RST_LO)
        await self._wait_state(
            "S9 cold assert",
            expect_powergood_stable=1,
            expect_rst_cold_stable_ref_clk_n=0,
            expect_rst_primary_ref_clk_n=0,
            expect_rst_primary_smc_clk_n=0,
            expect_left_stable=True,
        )
        await self._poll(
            "S9.uncore_low",
            T,
            COLD_BOUND,
            lambda: self._g("tb_cpu_uncore_reset_n") == 0,
            self._state,
        )
        await self._send(SmcResetOp.COLD_RST_HI)
        await self._wait_released("S9 cold release")
        await self._poll(
            "S9.uncore_high",
            T,
            COLD_BOUND,
            lambda: self._g("tb_cpu_uncore_reset_n") == 1,
            self._state,
        )
        await self._poll(
            "S9.l2_isolated_falls",
            T,
            COLD_BOUND,
            lambda: self._g("tb_cpu_uncore_reset_n") == 1 and self._g("tb_cpu_l2_isolated") == 0,
            self._state,
        )
        await self._edges(COLD_TAIL_EDGES)
        low = self._first("unc", 0, start)
        later = e_unc = e_init = iso_hi = fall = mm_fall = None
        if low is None:
            bad.append("tb_cpu_uncore_reset_n never read 0 in the cold reset")
        else:
            e_unc = self._first("unc", 1, low)
            init_low = self._first("init", 0, low)
            e_init = low if init_low is None else self._first("init", 1, init_low)
            if e_unc is None or e_init is None:
                bad.append(
                    f"events missing: uncore release@{e_unc} init_mem_done@{e_init} ({self._state()})"
                )
            else:
                later = max(e_unc, e_init)
                iso_hi = self._first("l2iso", 1, low)
                fall = self._first("l2iso", 0, later)
                mm_fall = self._first("mmioiso", 0, later)
                if iso_hi is None:
                    bad.append("tb_cpu_l2_isolated never read 1 in the cold reset")
                elif iso_hi < later:
                    good, total, first_bad = self._all("l2iso", 1, iso_hi, later)
                    if good != total:
                        bad.append(
                            f"tb_cpu_l2_isolated drops at sample {first_bad} before the release"
                        )
                if fall is None:
                    bad.append("tb_cpu_l2_isolated never fell after the release")
                elif fall < later:
                    bad.append(f"tb_cpu_l2_isolated fell at {fall} before the later event {later}")
        await wait_fuse_sense_done(FUSE_SENSE_BOUND)
        self._bound("S9.fuse_sense", f"{FUSE_SENSE_BOUND}clk_smc_i", "sense done")
        await self.program_inbound_pass_all()
        await self.program_outbound_pass_all()
        code, value = await self._acc("SEP", SmcSysAxiOp.READ, "rd_S9_fresh", FRESH_ADDR, token=T)
        if code != 0:
            bad.append(f"SEP_IN scratchpad read after the release: resp={code} data={value}")
        sw_l2, sw_mm = self.notes.get("sw_iso", (None, None))
        cold_l2 = None if fall is None or later is None else fall - later
        cold_mm = None if mm_fall is None or later is None else mm_fall - later
        self.obs["iso"] = [
            f"OBS-ISOLATION-DELAY: source=sw l2={sw_l2} mmio={sw_mm} sf=SF-026",
            f"OBS-ISOLATION-DELAY: source=cold_bypass l2={cold_l2} mmio={cold_mm} "
            f"init_mem_done@{e_init} uncore_release@{e_unc} sf=SF-026",
        ]
        later_event = (
            "none"
            if later is None
            else ("uncore_release" if e_unc is not None and e_unc >= e_init else "init_mem_done")
        )
        self.obs_lines.append(
            f"OBS-COLD-ISOLATION-RELEASE: later={later_event} edges={cold_l2} "
            f"stated={COLD_ISOLATE_EDGES} ruling=#3425-item-6"
        )
        self._grade(
            T,
            bad,
            "isolated until later event; released (edges in OBS); SEP_IN read completed",
        )
        self._stamp("COLD_ENTRY", 0 if fall is None or low is None else fall - low)

    # report ---------------------------------------------------------------------------------------
    def _valid_obs(self) -> None:
        """OBS-VALID-UNCORE-SW: the cluster-side VALIDs at every sampled edge of the drained
        software uncore resets; recorded, never compared (SF-003, SF-019)."""
        edges, xz, high = 0, 0, []
        for tag, a, b in self.valid_windows:
            for i in range(a, min(b, self.n)):
                if self._c("unc", i) != 0:
                    continue
                edges += 1
                fv, mv = self._c("fv", i), self._c("mv", i)
                if fv < 0 or mv < 0:
                    xz += 1
                    continue
                if fv & ((1 << FRONT_BIT["b"]) | (1 << FRONT_BIT["r"])) or mv & (
                    (1 << FRONT_BIT["aw"]) | (1 << FRONT_BIT["w"]) | (1 << FRONT_BIT["ar"])
                ):
                    high.append(f"{tag}@{i}:f{fv:05b}m{mv:05b}")
        if edges == 0:
            self._fail("CHK-OBS-VALID-UNCORE-SW", "no sampled edge of the software uncore reset")
        more = f",+{len(high) - 8}" if len(high) > 8 else ""
        self.obs["valid"] = [
            f"OBS-VALID-UNCORE-SW: edges={edges} high={','.join(high[:8]) + more or 'none'} "
            f"xz={xz} sf=SF-019"
        ]

    def _reset_term(self) -> None:
        T = "CHK-CORE-RESET-N-TERM"
        good = sum(g for _n, g, _t in self.term)
        total = sum(t for _n, _g, t in self.term)
        bad = []
        if total == 0 or good != total:
            bad.append(f"probe agrees with core3_reset_n at {good}/{total} samples: {self.term}")
        self._grade(T, bad, f"core3 probe == !core3_reset_n over {total} samples (hold and pulse)")

    def _wdt_config(self) -> None:
        T = "CHK-CORE3-WDT-CONFIG"
        bad = []
        if self.cmp_kept != WDT_CMP_REF:
            bad.append(
                f"CMP reads {self.cmp_kept} after the core 3 reset, expected 0x{WDT_CMP_REF:x}"
            )
        if self.cmp_after != WDT_CMP_RESET:
            bad.append(
                f"CMP reads {self.cmp_after} after the uncore reset, expected 0x{WDT_CMP_RESET:x}"
            )
        self._grade(T, bad, "CMP 0x0234 kept across core-3 reset; 0x1000 after uncore reset")

    def _status_reads(self) -> None:
        T = TOKEN_STATUS
        names = {"SEP": "SEP_IN", "SYS": "SYS_IN", "JTAG": "JTAG_IN"}
        want_pc = PRE_COUNT_RESET | (POST_COUNT_RESET << POST_COUNT_BP)
        bad = []
        labels = []
        for label, port, fields, pc, want in self.graded_status:
            labels.append(f"{label}/{names[port]}")
            if not fields:
                bad.append(f"{label} over {names[port]}: RESET_TIMEOUT without an OKAY response")
                continue
            for key, val in want.items():
                if fields.get(key) != val:
                    bad.append(
                        f"{label} over {names[port]}: {key} reads {fields.get(key)}, want {val}"
                    )
            if pc is None or pc & (PRE_COUNT_BM | POST_COUNT_BM) != want_pc:
                bad.append(
                    f"{label} over {names[port]}: CORE_RESET_PULSE_COUNT reads {pc}, want counts "
                    f"0x{want_pc:x}"
                )
        if "s6_applied" not in [g[0] for g in self.graded_status]:
            bad.append(
                "the S6 status point (applied and isolated, nothing presented) is not graded"
            )
        self._grade(
            T,
            bad,
            f"{len(self.graded_status)} inbound-manager reads of RESET_TIMEOUT with no stalled "
            f"front-port request, all OKAY; reset_applied=1 while applied ({' '.join(labels)}; "
            f"CORE_RESET_PULSE_COUNT with each) | OBS-STATUS-READ-UNDER-STALL: "
            f"{len(self.stall_reads)} reads recorded apart, sf=SF-026",
        )

    def _fence_check(self) -> str:
        names = [f[0] for f in self.fence]
        times = [f[1] for f in self.fence]
        if names != list(FENCE) or any(b <= a for a, b in zip(times, times[1:])):
            self._fail("CHK-NONVAC", f"terms {self.fence}")
        floors = {
            "CORE_HOLD": HOLD_EDGES,
            "PULSE": PULSE_WIDTH_RESET + PULSE_POST_LONG + 1,
            "BLOCKED": 3,
        }
        for term, _t, count in self.fence:
            want = floors.get(term, 4 if term in ("TIMER_OFF", "GIVE_UP") else 1)
            if count < want:
                self._fail("CHK-NONVAC", f"term {term} count {count} below {want}")
        if self.aborted:
            self._fail("CHK-NONVAC", f"steps aborted {self.aborted}")
        return (
            " < ".join(names)
            + " (counts and times per term): "
            + "; ".join(f"{n} t={t}ps count={c}" for n, t, c in self.fence)
        )

    def _report(self, final: bool = True) -> None:
        if self.agg_done:
            if final:
                self._finish()
            return
        self.agg_done = True
        self._valid_obs()
        self._reset_term()
        self._wdt_config()
        self._status_reads()
        for token, key in (
            ("CHK-OBS-TIMEOUT-EXPIRY", "expiry"),
            ("CHK-OBS-ISOLATION-DELAY", "iso"),
            ("CHK-OBS-DRAIN-FLUSH-RESPONSES", "flush"),
            ("CHK-OBS-CORE-RESET-ACCESS", "core"),
            ("CHK-OBS-MMIO-RESET", "mmio"),
            ("CHK-OBS-VALID-UNCORE-SW", "valid"),
        ):
            texts = self.obs.get(key, [])
            if texts:
                self._ok(token, " | ".join(texts))
        restart, runs, gap = self.notes.get("restart", (None, [], None))
        order = self.notes.get("pulse_vs_uncore", "not observed")
        wb = self.notes.get("wb_pc", [])
        wb_text = " ".join("none" if v is None else f"0x{v:x}" for v in wb) or "none"
        pulse_text = (
            f"OBS-PULSE-AND-STATUS: pulse_vs_uncore={order} wb_pc_core0={wb_text} "
            f"restart_start_to_assert={restart} (runs {runs}, second write {gap} samples after the "
            f"first; wdt_count={self.notes.get('wdt_count')}) sf=SF-027"
        )
        self._ok("CHK-OBS-PULSE-AND-STATUS", pulse_text)
        self._ok("CHK-NONVAC", self._fence_check())
        expired = [t for t in self._timeout_paths if "EXPIRED" in t]
        obs_expired = [t for t in self.obs_waits if "last=expired" in t]
        if expired:
            self._fail("CHK-TIMEOUT-PATHS", f"{len(expired)} bounded waits expired: {expired[:6]}")
        self._ok(
            "CHK-TIMEOUT-PATHS",
            f"{len(self._timeout_paths)} bounded waits, bound/last-state per wait, "
            f"{len(expired)} expired; observation waits {len(self.obs_waits)} counted apart, "
            f"{len(obs_expired)} expired (recorded, not graded; {len(self.stall_reads)} status "
            f"reads under stall)",
        )
        for token, text in self.lines:
            if token not in self.printed:
                self._print(token, text)
        for key in ("expiry", "iso", "flush", "core", "mmio", "valid"):
            for text in self.obs.get(key, []):
                cocotb.log.info("EVIDENCE: %s", text)
        cocotb.log.info("EVIDENCE: %s", pulse_text)
        for text in self.obs_lines + self._stall_lines():
            cocotb.log.info("EVIDENCE: %s", text)
        for token in REQUIRED_TOKENS:
            if token not in self.printed:
                mine = [f.split(": ", 1)[1] for f in self.fails if f.split(":", 1)[0] == token]
                cocotb.log.info(
                    "%s: FAIL %s",
                    token,
                    "; ".join(mine) if mine else "step not reached, see CHK-NONVAC",
                )
        for line in self._timeout_paths:
            cocotb.log.info("CHK-TIMEOUT-PATHS: wait %s", line)
        for line in self.obs_waits:
            cocotb.log.info("CHK-TIMEOUT-PATHS: observation wait %s", line)
        if final:
            self._finish()

    def _finish(self) -> None:
        assert not self.fails, "contract checkers failed:\n" + "\n".join(
            f"FAIL {f}" for f in self.fails
        )
