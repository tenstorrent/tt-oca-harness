# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
# DV-TESTCASE-CONTRACT: SMC_SEP_SCN_003 ANCHOR: smc_sw_uncore_reset_drain_isolate_test
# DV-TESTCASE-CONTRACT-REVISION: 1 RECORD-SHA256: 89c23b57e53913867731dea0e63164d785460cb5be5e0c3dd67a2bd39a962388
# DV-TESTCASE-CONTRACT-SOURCE: hw/sys/smc/dv/ai/dv_vplan_gen/SMC_SEP_SCN_VPLAN_DETAIL.md @ artifact_revision 1 ENV: cocotb
"""Software core reset, core reset pulse and software uncore reset with the L2 frontend isolate.

``CPU_CTRL.RESET_CTRL`` is driven over SEP_IN in four ways. Core 3 is held and then pulsed
without any drain while SEP_IN and SYS_IN keep reaching the scratchpad and the core-3 watchdog
compare register keeps its value. The uncore bit is cleared with four L2 frontend reads parked
by ``tb_sep_axi_r_hold`` in timer-off mode (the reset is withheld for 1024 edges), in give-up
mode (``reset_timeout`` is reported and the reset is still withheld until the drain completes)
and with nothing pending, where a scratchpad read presented on SEP_IN, SYS_IN and JTAG_IN while
the boundary is isolated is blocked, not terminated, and completes after the reconnect. One
force-mode episode checks the request status only. A cold reset replayed through the reset
agent ends the leaf and times the isolation release.

Graded: the compares named by the ``CHK-*`` lines the sequence prints. ``OBS-*`` content is
printed inside the matching ``CHK-OBS-*`` line and never compared; each names its spec finding.

Probes: ``tb_cpu_core_resets_n`` (core 3 is bit 3), ``tb_cpu_uncore_reset_n``,
``tb_cpu_isolate_req``, ``tb_cpu_drained``, ``tb_cpu_reset_timeout``, ``tb_cpu_reset_applied``,
``tb_cpu_l2_isolated``, ``tb_cpu_mmio_isolated``, ``tb_cpu_l2_pending_ar``,
``tb_cpu_front_valid`` / ``_ready`` and ``tb_cpu_mmio_valid`` / ``_ready`` with
``[4:0] = {r, ar, b, w, aw}``, and ``rst_primary_smc_clk_no`` for the primary reset.
"""

from __future__ import annotations

from types import SimpleNamespace

import cocotb
from cocotb.triggers import FallingEdge, RisingEdge, SimTimeoutError, with_timeout
from cocotb.utils import get_sim_time
from env.smc_reset_item import SmcResetOp
from env.smc_sys_axi_agent import SmcSysAxiDriver, SmcSysAxiItem, SmcSysAxiOp

from ._one_shot import _OneShot
from .smc_addr_map import cpu_ctrl_u32, smc_addr, smc_indexed_addr
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

# wdt.adoc: the KEY write that unlocks the next write, and the compare register reset.
WDT_MAGIC_KEY = 0x51F15E
WDT_CMP_REF = 0x0234
WDT_CMP_RESET = 0x1000

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

PEND_ID = 0x30
FIFTH_ID = 0x34
STATUS_ID = 0x38
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
    "CHK-VALID-LOW-UNCORE-SW",
    "CHK-FORCE-MODE-REQUEST-STATUS",
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
S7_TOKENS = ("CHK-FORCE-MODE-REQUEST-STATUS", "CHK-OBS-DRAIN-FLUSH-RESPONSES")
FENCE = (
    "SETUP",
    "CORE_HOLD",
    "PULSE",
    "TIMER_OFF",
    "GIVE_UP",
    "BLOCKED",
    "MMIO",
    "COLD_ENTRY",
    "FORCE",
)

_EXTRA_NAMES = (
    "rst_primary_smc_clk_no",
    "tb_cpu_cluster_isolate",
    "tb_sep_axi_r_hold",
    "tb_sys_axi_r_hold",
    "tb_sep_axi_r_drop",
    "tb_sys_axi_r_drop",
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
    ("mv", "tb_cpu_mmio_valid"),
    ("mr", "tb_cpu_mmio_ready"),
    ("sarv", "s_axi_arvalid"),
    ("sarr", "s_axi_arready"),
    ("sara", "s_axi_araddr"),
    ("yarv", "sys_axi_arvalid"),
    ("yarr", "sys_axi_arready"),
    ("yara", "sys_axi_araddr"),
    ("srv", "s_axi_rvalid"),
    ("srr", "s_axi_rready"),
    ("srl", "s_axi_rlast"),
    ("srid", "s_axi_rid"),
    ("sbv", "s_axi_bvalid"),
    ("srraw", "tb_sep_axi_r_raw_valid"),
    ("yrv", "sys_axi_rvalid"),
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

    async def _poll(self, label: str, token: str, bound: int, cond, state) -> int | None:
        """Bounded wait on a live condition; an expiry is a checker FAIL, not an exception."""
        clk = cocotb.top.clk_smc_i
        for k in range(bound + 1):
            await FallingEdge(clk)
            if cond():
                self._bound(label, f"{bound}clk_smc_i", f"reached after {k} edges, {state()}")
                await RisingEdge(clk)
                return k
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
        return SimpleNamespace(
            span=event_span,
            label=label,
            port=port,
            event=event,
            op=op,
            addr=addr,
            length=length,
            beats=beats,
            axi_id=axi_id,
        )

    async def _span_end(self, span: list, event) -> None:
        """Close the CPU_CTRL access interval at the sample where its response arrives."""
        await event.wait()
        span[1] = self.n + 2

    async def _join(self, raw, token: str, *, obs: bool = False, bound_ns: int = AXI_BOUND_NS):
        """Bounded wait for a presented access; (resp code, read data), (None, None) on expiry."""
        if not raw.event.is_set():
            try:
                await with_timeout(raw.event.wait(), bound_ns, "ns")
            except SimTimeoutError:
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
        self.rt_reads.append((label, fields, {"SEP": "SEP_IN", "SYS": "SYS_IN"}[port]))
        return fields

    async def _wdt_write(self, label: str, addr: int, value: int, token: str) -> None:
        await self._wr(f"{label}_KEY", WDT3_KEY, WDT_MAGIC_KEY, token, length=4)
        await self._wr(label, addr, value, token, length=4)

    # --- shared episode steps ------------------------------------------------------------------
    async def _write_rc(self, label: str, value: int, token: str) -> tuple[int, int]:
        """RESET_CTRL write over SEP_IN; (sample index at the issue, at the response)."""
        issue = self.n
        await self._wr(label, RESET_CTRL, value, token)
        return issue, self.n

    def _release_holds(self) -> None:
        dut = cocotb.top
        for name in ("tb_sep_axi_r_hold", "tb_sys_axi_r_hold", "tb_output_axi_resp_hold"):
            getattr(dut, name).value = 0
        dut.tb_sep_axi_r_drop.value = 0
        dut.tb_sys_axi_r_drop.value = 0

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
            lambda: (
                len(self._hs("ar", since, self.n)) >= count
                and self._g("tb_cpu_l2_pending_ar") > 0
                and self._g("tb_sep_axi_r_raw_valid") == 1
            ),
            lambda: (
                f"front AR handshakes {len(self._hs('ar', since, self.n))}/{count}; "
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
        self._release_holds()
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
            await self._s8_deferred()
            await self._step("S9", self._s9_cold())
            await self._step("S7", self._s7_force())
        finally:
            self._release_holds()
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
            f"wr={self._code_text(rel_wr)} (waits on SF-022 and SF-038)"
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
        fifth_early = fifth.event.is_set()
        self._release_holds()
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
        fifth_before = fifth.event.is_set()
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
        pend_max = max((self._c("l2par", i) for i in range(since, self.n)), default=-1)
        if pend_max > 4 or pend_max < 1:
            bad2.append(f"tb_cpu_l2_pending_ar peaks at {pend_max}")
        fifth_ar = self._hs("ar", a_idx if a_idx is not None else iss, self.n)
        stop = recon if recon is not None else self.n
        isolated_ar = [i for i in fifth_ar if a_idx is not None and a_idx <= i < stop]
        pend_rises = [
            i
            for i in range(a_idx if a_idx is not None else iss, stop)
            if i > 0 and self._c("l2par", i) > self._c("l2par", i - 1)
        ]
        if fifth_early or fifth_before:
            bad2.append("the fifth read answered while the boundary was isolated")
        if isolated_ar or pend_rises:
            bad2.append(
                f"the fifth read was accepted before the reconnect: front-port AR handshakes at "
                f"samples {isolated_ar[:3]} and tb_cpu_l2_pending_ar rises at samples "
                f"{pend_rises[:3]} between isolate_req@{a_idx} and reconnect@{recon}"
            )
        if recon is None or not fifth_ar:
            bad2.append("the fifth read never reached the L2 frontend after the reconnect")
        cocotb.log.info(
            "S4a: fifth read front-port AR handshakes at samples %s; isolate_req@%s "
            "applied@%s reconnect@%s; l2_isolated high %s samples",
            fifth_ar,
            a_idx,
            res_idx,
            recon,
            self._all("l2iso", 1, iss, (recon or self.n))[0],
        )
        want5 = self._burst_ref(SCRATCH_REF_BASE + 32, BURST_BEATS)
        if fifth_code != 0 or fifth_data != want5:
            bad2.append(f"fifth read completes resp={fifth_code} data={fifth_data}")
        released = self._first("unc", 0, iss)
        self._window("S4a", iss, (recon or self.n) + 1)
        self._grade(
            T1,
            bad1,
            f"{TIMER_OFF_EDGES} edges withheld, reset_timeout 0, applied 0; reset applied after "
            f"release",
        )
        self._grade(
            T2,
            bad2,
            f"max pending AR {pend_max}; fifth read accepted only after reconnect "
            f"(front-port AR handshakes after the isolate request at samples {fifth_ar}, "
            f"isolate_req@{a_idx}, reconnect@{recon})",
        )
        self._stamp("TIMER_OFF", len(self._hs("ar", since, since + 400)))
        self.ep_s4 = SimpleNamespace(since=since, iss=iss, res=released, reads=reads)

        # second timer-off episode with a core 3 pulse started just before the uncore bit clears
        since2, reads2 = await self._arm_four("S4b", T1)
        _i, r1 = await self._write_rc("S4b_PULSE_START", self.rc_base | CORE3_PULSE_START, TP)
        iss2, _r2 = await self._write_rc("S4b_UNCORE_CLEAR", self.rc_base & ~UNCORE_RESET_N, TP)
        await self._edges(PULSE_HOLD_EDGES // 4)
        self._release_holds()
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
        TS = "CHK-STATUS-READABLE-FROM-SEP"
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
        status_from = self.n
        status = self._raw(
            "SYS", SmcSysAxiOp.READ, "S5_status_expired", RESET_TIMEOUT, axi_id=STATUS_ID
        )
        await self._poll(
            "S5.status_ar",
            TS,
            ASSERT_BOUND,
            lambda: any(
                self._c("yarv", x) == 1
                and self._c("yarr", x) == 1
                and self._c("yara", x) == RESET_TIMEOUT
                for x in range(status_from, self.n)
            ),
            self._state,
        )
        ar_idx = self.n
        withheld_live = (
            self._g("tb_cpu_uncore_reset_n"),
            self._g("tb_cpu_reset_applied"),
            self._g("tb_cpu_drained"),
        )
        if rise is None:
            bg.append("tb_cpu_reset_timeout never rose with timeout_value 64")
        else:
            end_w = ar_idx + 1 if ar_idx is not None else self.n
            for key, val, name in (("unc", 1, "uncore_reset_n"), ("rap", 0, "reset_applied")):
                good, total, first_bad = self._all(key, val, rise, end_w)
                if good != total:
                    bg.append(f"{name} not {val} after the timer expired (sample {first_bad})")
        if withheld_live != (1, 0, 0):
            bg.append(f"uncore/applied/drained read {withheld_live} when the status read was taken")
        self._release_holds()
        await self._wait_reset_applied("S5", T)
        early = [r.event.is_set() for r in reads]
        self.drained_b = [self._result(r) for r in reads]
        status_code, status_value = await self._join(status, TS)
        expired = self._rt_fields(status_value)
        self.rt_reads.append(("s5_expired", expired, "SYS_IN"))
        if expired.get("flag") != 1 or expired.get("applied") != 0:
            bg.append(
                f"RESET_TIMEOUT read after the expiry (reset withheld) reads "
                f"{expired if expired else 'no response'}"
            )
        applied_rt = await self._rt("s5_applied", TS)
        if applied_rt.get("applied") != 1 or applied_rt.get("flag") != 1:
            bg.append(
                f"RESET_TIMEOUT after the drain reads "
                f"{applied_rt if applied_rt else 'no response'}, expected applied 1 timeout 1"
            )
        res = self._first("unc", 0, iss)
        keep_from = self.n
        await self._edges(GIVE_UP_KEEP_EDGES)
        i_set, r_set = await self._write_rc("S5_UNCORE_SET", self.rc_base, T)
        recon_rt = await self._rt("s5_reconnecting", TS)
        await self._reconnect("S5", TH)
        recon = self._first("l2iso", 0, r_set)
        for r, done in zip(reads, early):
            if not done:
                await self._join(r, TP, obs=True)
        cocotb.log.info(
            "S5: parked reads completed before the reset applied %s, isolate pending peak %s",
            early,
            max((self._c("l2par", i) for i in range(since, self.n)), default=-1),
        )
        if rise is not None:
            good, total, first_bad = self._all("rto", 1, rise, i_set)
            if good != total:
                bg.append(f"reset_timeout falls at sample {first_bad} while the request stays")
        # handshake order
        a = self._first("isoreq", 1, iss)
        b = self._first("drn", 1, a if a is not None else iss)
        cc = self._first("core", 0, iss)
        if None in (a, b, res, cc):
            bh.append(f"events missing: isolate_req@{a} drained@{b} uncore@{res} core@{cc}")
        else:
            if self._c("unc", a) != 1:
                bh.append(f"uncore reset already asserted at isolate_req@{a}")
            if not a < b <= res:
                bh.append(f"order isolate_req@{a} drained@{b} uncore@{res}")
            r_last = self._sep_r_done(since, b, {PEND_ID + k for k in range(4)})
            if len(r_last) < 4:
                bh.append(
                    f"drained@{b} with {len(r_last)} of the four parked R beats complete "
                    f"(RLAST samples {r_last})"
                )
            if cc != res:
                bh.append(f"core reset@{cc} not in the sample of the uncore reset@{res}")
            good, total, first_bad = self._all("isoreq", 1, a, i_set)
            if good != total:
                bh.append(f"isolate_req falls at sample {first_bad} before the bit is set")
        if applied_rt.get("applied") != 1:
            bh.append("reset_applied does not read 1 over SEP_IN once applied")
        if recon is None:
            bh.append("no reconnect after the uncore bit was set")
        # pending reads
        pend_addrs = {SCRATCH_REF_BASE + 8 * k for k in range(4)}
        ids = {PEND_ID + k for k in range(4)}
        ar_n = len(
            [
                x
                for x in range(since, status_from)
                if self._c("sarv", x) == 1
                and self._c("sarr", x) == 1
                and self._c("sara", x) in pend_addrs
            ]
        )
        r_n = len(self._sep_r_done(since, (res if res is not None else self.n) + 1, ids))
        pend_peak = max((self._c("l2par", x) for x in range(since, self.n)), default=-1)
        self.notes["pend_peak"] = pend_peak
        if ar_n != 4 or r_n != ar_n:
            bp.append(
                f"SEP_IN AR {ar_n} R {r_n} (RLAST) up to the reset applying, expected R equal to AR "
                f"(4)"
            )
        if not all(early):
            bp.append(f"reads completed before the reset applied: {early}")
        self._grade(
            T,
            bg,
            "expired: timeout=1 applied=0 withheld; after drain: applied=1 timeout=1 until bit set",
        )
        self._grade(
            TH,
            bh,
            f"isolate_req@{a} < drained@{b} <= uncore_reset@{res} == core_reset@{cc}; isolate_req "
            f"held until bit set; reset_applied 1; reconnect@{recon}",
        )
        self._grade(
            TP,
            bp,
            f"AR {ar_n} R {r_n} before reset applied at SEP_IN (OBS isolate pending_ar peak "
            f"{pend_peak})",
        )
        if rise is not None:
            self.obs["expiry"].append(
                f"OBS-RESET-TIMEOUT-EXPIRY: value={TIMEOUT_CYCLES} from_write={rise - resp} "
                f"from_isolate_req={rise - (a if a is not None else iss)} (waits on SF-028)"
            )
        else:
            self._fail(TE, "no expiry edge observed")
        self.status_reads_s5 = (status_code, applied_rt, recon_rt)
        self._window("S5", iss, (recon or self.n) + 1)
        self._stamp("GIVE_UP", ar_n)
        self.notes["keep_from"] = keep_from

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
        cmp_after = await self._rd("S6_CMP_AFTER", WDT3_CMP, TW, length=4)
        count_after = await self._rd("S6_WDT_COUNT", WDT3_COUNT, TW, length=4)
        self.notes["wdt_count"] = count_after
        self.cmp_after = cmp_after
        self._window("S6", iss, (l2_fall or self.n) + 1)
        self._grade(
            T,
            bad,
            f"3 managers blocked {BLOCK_EDGES} edges, 0 responses; after reconnect 3/3 completed "
            f"with reference data; fresh read OK",
        )
        self._stamp("BLOCKED", len(blocked))

    # S7 -------------------------------------------------------------------------------------------
    async def _s7_force(self) -> None:
        T = "CHK-FORCE-MODE-REQUEST-STATUS"
        TF = "CHK-OBS-DRAIN-FLUSH-RESPONSES"
        bad: list[str] = []
        dut = cocotb.top
        rd = SmcSysAxiOp.READ
        await self._wr("RESET_TIMEOUT_FORCE", RESET_TIMEOUT, TIMEOUT_MODE_BM | TIMEOUT_CYCLES, T)
        dut.tb_output_axi_resp_hold.value = 1
        out_from = self.n
        route = self._raw("JTAG", rd, "S7_route_rd", EXT_ROUTE, axi_id=BLOCK_ID[2])
        since, reads = await self._arm_four("S7", T)
        await self._poll(
            "S7.sys_out_ar",
            T,
            PENDING_BOUND,
            lambda: any(
                self._c("oarv", i) == 1
                and self._c("oarr", i) == 1
                and self._c("oara", i) == EXT_ROUTE
                for i in range(out_from, self.n)
            ),
            self._state,
        )
        self._stamp("FORCE", len(self._hs("ar", since, self.n)))
        self._report(final=False)
        iss, resp = await self._write_rc("S7_UNCORE_CLEAR", self.rc_base & ~UNCORE_RESET_N, T)
        await self._poll(
            "S7.isolate_req",
            T,
            ISOLATE_BOUND,
            lambda: self._g("tb_cpu_isolate_req") == 1,
            self._state,
        )
        await self._poll(
            "S7.reset_timeout",
            T,
            TIMEOUT_BOUND,
            lambda: self._g("tb_cpu_reset_timeout") == 1,
            self._state,
        )
        await self._poll(
            "S7.applied",
            T,
            DRAIN_BOUND,
            lambda: self._g("tb_cpu_reset_applied") == 1 and self._g("tb_cpu_uncore_reset_n") == 0,
            self._state,
        )
        rise = self._first("rto", 1, iss)
        _code, value = await self._acc("SYS", rd, "rd_S7_status_forced", RESET_TIMEOUT, token=T)
        forced = self._rt_fields(value)
        self.rt_reads.append(("s7_forced", forced, "SYS_IN"))
        dut.tb_sep_axi_r_hold.value = 0
        await self._poll(
            "S7.drained", T, DRAIN_BOUND, lambda: self._g("tb_cpu_drained") == 1, self._state
        )
        after_flush = await self._rt("s7_after_flush", T)
        for name, fields in (
            ("after the forced reset applied", forced),
            ("after the flush", after_flush),
        ):
            if fields.get("flag") != 1:
                bad.append(
                    f"reset_timeout reads {fields.get('flag')} {name} with the request present"
                )
        i_set, r_set = await self._write_rc("S7_UNCORE_SET", self.rc_base, T)
        if rise is None:
            bad.append("tb_cpu_reset_timeout never rose in force mode")
        else:
            good, total, first_bad = self._all("rto", 1, rise, i_set)
            if good != total:
                bad.append(f"reset_timeout falls at sample {first_bad} while the request stays")
        await self._reconnect("S7", T)
        await self._poll(
            "S7.request_removed",
            T,
            TIMEOUT_BOUND,
            lambda: self._g("tb_cpu_reset_timeout") == 0,
            self._state,
        )
        removed = await self._rt("s7_removed", T)
        if removed.get("flag") != 0:
            bad.append(f"reset_timeout reads {removed.get('flag')} after the request was removed")
        self._grade(
            T,
            bad,
            "force mode: reset_timeout 1 after flush until request removed; 0 afterwards",
        )
        # outside route
        release_at = self.n
        dut.tb_output_axi_resp_hold.value = 0
        route_code, route_value = await self._join(route, TF, obs=True)
        late = sum(
            1
            for i in range(release_at, self.n)
            if self._c("orv", i) == 1 and self._c("orr", i) == 1
        )
        fate = "hung" if route_code is None else f"completed code {route_code}"
        _c2, fresh_value = await self._acc(
            "JTAG", rd, "rd_S7_route_again", EXT_ROUTE, token=TF, obs=True
        )
        stale_fates = ",".join("done" if r.event.is_set() else "open" for r in reads)
        codes = [self._code_text(c) for c, _v in self.drained_b]
        data = [("none" if v is None else f"0x{v:x}") for _c, v in self.drained_b]
        self.obs["flush"].append(
            f"OBS-DRAIN-FLUSH-RESPONSES: drained rresp={','.join(codes)} rdata={' '.join(data)} "
            f"route_read={fate} late_beats={late} (route data {route_value}, again {fresh_value}; "
            f"force-mode reads {stale_fates}; waits on SF-006 and SF-029)"
        )
        self._print(TF, self.obs["flush"][-1])
        await self._wr("RESET_TIMEOUT_CLEAR", RESET_TIMEOUT, 0, T)

    # S8 -------------------------------------------------------------------------------------------
    async def _s8_deferred(self) -> None:
        await RisingEdge(cocotb.top.clk_smc_i)
        pend = {
            name: max((self._c(key, i) for i in range(self.n)), default=-1)
            for name, key in (("ar", "mpar"), ("aw", "mpaw"), ("w", "mpw"))
        }
        self.obs["mmio"] = [
            f"OBS-MMIO-RESET: episode=none items=0 (the mmio_wedge episodes are deferred and no "
            f"firmware image is staged) tb_cpu_mmio_valid samples={self.n} "
            f"mmio_pending max ar/aw/w={pend['ar']}/{pend['aw']}/{pend['w']} "
            f"(waits on SF-004, SF-022 and SF-035)"
        ]
        self._stamp("MMIO", self.n)

    # S9 -------------------------------------------------------------------------------------------
    async def _dispatch_reset_item(self, item) -> None:
        await _OneShot(item, "reset_os").start(self.env.reset_agent.sequencer)

    async def _s9_cold(self) -> None:
        T = "CHK-COLD-ISOLATION-RELEASE"
        bad: list[str] = []
        self._release_holds()
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
                elif fall - later != COLD_ISOLATE_EDGES:
                    bad.append(
                        f"tb_cpu_l2_isolated fell {fall - later} edges after the later event "
                        f"(uncore release@{e_unc}, init_mem_done@{e_init}), expected "
                        f"{COLD_ISOLATE_EDGES}"
                    )
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
            f"OBS-ISOLATION-DELAY: source=sw l2={sw_l2} mmio={sw_mm} (waits on SF-026)",
            f"OBS-ISOLATION-DELAY: source=cold_bypass l2={cold_l2} mmio={cold_mm} "
            f"init_mem_done@{e_init} uncore_release@{e_unc} (waits on SF-026)",
        ]
        self._grade(
            T,
            bad,
            f"isolated until later event; released {cold_l2} edges after; SEP_IN read completed",
        )
        self._stamp("COLD_ENTRY", 0 if fall is None or low is None else fall - low)

    # report ---------------------------------------------------------------------------------------
    def _valid_low(self) -> None:
        T = "CHK-VALID-LOW-UNCORE-SW"
        bad: list[str] = []
        edges = 0
        ctrl_excluded = 0
        for tag, a, b in self.valid_windows:
            j = 0
            for i in range(a, min(b, self.n)):
                unc = self._c("unc", i)
                if unc != 0:
                    continue
                j += 1
                fv, mv = self._c("fv", i), self._c("mv", i)
                if fv < 0 or mv < 0:
                    bad.append(f"{tag} sample {i}: X/Z on a link vector")
                    continue
                if fv & ((1 << 2) | (1 << 4)):
                    if self._in_ctrl(i):
                        ctrl_excluded += 1
                    else:
                        bad.append(f"{tag} sample {i}: front B/R VALID high (0b{fv:05b})")
                if j >= 2 and mv & ((1 << 0) | (1 << 1) | (1 << 3)):
                    bad.append(f"{tag} sample {i}: MMIO AW/W/AR VALID high (0b{mv:05b})")
                edges += 1
        if edges == 0:
            bad.append("no sampled edge of the software uncore reset")
        self._grade(
            T,
            bad[:6],
            f"cluster-side VALIDs low at {edges} edges of the uncore reset; 0 violations "
            f"({ctrl_excluded} B/R VALID samples answer an outstanding CPU_CTRL access)",
        )

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
        T = "CHK-STATUS-READABLE-FROM-SEP"
        reads = [(label, f, link) for label, f, link in self.rt_reads if label.startswith("s5")]
        bad = []
        if len(reads) < 3 or any(not f for _l, f, _k in reads):
            bad.append(f"{len(reads)} status reads, fields {reads}")
        applied = {label: f for label, f, _k in self.rt_reads}.get("s5_applied", {})
        links = sorted({k for _l, _f, k in reads})
        if applied.get("applied") != 1:
            bad.append("reset_applied does not read 1 while the reset is applied")
        self._grade(
            T,
            bad,
            f"{len(reads)} reads of RESET_TIMEOUT during the uncore reset (links {'/'.join(links)}; "
            f"SYS_IN while tb_sep_axi_r_hold is set), all OKAY; reset_applied=1 while applied",
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
            want = floors.get(term, 4 if term in ("TIMER_OFF", "GIVE_UP", "FORCE") else 1)
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
        self._valid_low()
        self._reset_term()
        self._wdt_config()
        self._status_reads()
        for token, key in (
            ("CHK-OBS-TIMEOUT-EXPIRY", "expiry"),
            ("CHK-OBS-ISOLATION-DELAY", "iso"),
            ("CHK-OBS-DRAIN-FLUSH-RESPONSES", "flush"),
            ("CHK-OBS-CORE-RESET-ACCESS", "core"),
            ("CHK-OBS-MMIO-RESET", "mmio"),
        ):
            texts = self.obs.get(key, [])
            if texts:
                self._ok(token, " | ".join(texts))
        restart, runs, gap = self.notes.get("restart", (None, [], None))
        order = self.notes.get("pulse_vs_uncore", "not observed")
        wb = self.notes.get("wb_pc", [])
        wb_text = " ".join("none" if v is None else f"0x{v:x}" for v in wb) or "none"
        self._ok(
            "CHK-OBS-PULSE-AND-STATUS",
            f"OBS-PULSE-AND-STATUS: pulse_vs_uncore={order} wb_pc_core0={wb_text} "
            f"restart_start_to_assert={restart} (runs {runs}, second write {gap} samples after the "
            f"first; wdt_count={self.notes.get('wdt_count')}; waits on SF-027)",
        )
        self._ok("CHK-NONVAC", self._fence_check())
        expired = [t for t in self._timeout_paths if "EXPIRED" in t]
        if expired:
            self._fail("CHK-TIMEOUT-PATHS", f"{len(expired)} bounded waits expired: {expired[:6]}")
        self._ok(
            "CHK-TIMEOUT-PATHS",
            f"{len(self._timeout_paths)} bounded waits, bound/last-state per wait, "
            f"{len(expired)} expired",
        )
        for token, text in self.lines:
            if token not in self.printed:
                self._print(token, text)
        for token in REQUIRED_TOKENS:
            if token not in self.printed and not final and token in S7_TOKENS:
                cocotb.log.info(
                    "%s: FAIL pending: the force-mode request is the next event; this line stands "
                    "when the run ends in the S7 assertion and a later %s line replaces it "
                    "otherwise",
                    token,
                    token,
                )
            elif token not in self.printed:
                mine = [f.split(": ", 1)[1] for f in self.fails if f.split(":", 1)[0] == token]
                cocotb.log.info(
                    "%s: FAIL %s",
                    token,
                    "; ".join(mine) if mine else "step not reached, see CHK-NONVAC",
                )
        for line in self._timeout_paths:
            cocotb.log.info("CHK-TIMEOUT-PATHS: wait %s", line)
        if final:
            self._finish()

    def _finish(self) -> None:
        assert not self.fails, "contract checkers failed:\n" + "\n".join(
            f"FAIL {f}" for f in self.fails
        )
