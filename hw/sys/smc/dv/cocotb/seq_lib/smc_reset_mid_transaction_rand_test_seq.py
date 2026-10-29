# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Seeded resets asserted inside an in-flight operation, and the register retention by domain.

Specs: hw/sys/smc/doc/clk_rst.adoc (Reset Architecture; Power-Good and Cold Reset; Primary and
Warm Reset), hw/sys/smc/regs/blocks/reset_unit/reset_unit.rdl, cpu_ctrl/cpu_ctrl.rdl,
misc_wrap/misc_wrap.rdl and scratch/scratch.rdl.

Six passes. The first four passes take the four reset kinds (cool pin, FLR, cold, SEP watchdog)
in a drawn order and the last two draw a kind each, so every kind runs on every seed. Each pass
programs drawn non-zero patterns, starts a drawn in-flight operation (an SPM burst write or read
over SEP_IN, a DMA copy or a zeroer job through the SYS_OUT responder), drives the reset source
at a drawn cycle of it for a drawn hold, waits for the release and compares every register
with the golden of the reset kind. The watchdog kind never draws an SPM operation: a watchdog warm
reset with an SPM access in flight leaves the cluster boundary unanswering until a primary reset.
When no SPM burst of the six was inside its reset (issued past the L2-frontend isolate into the
cluster, response not returned), SPM passes of a drawn cool-pin or cold kind are added, each
counting its drawn cycle from the burst's issue into the cluster, until one is; at least one such
pass per seed is required. `rst_primary_smc_clk_no`, `tb_rst_warm_smc_clk_n` and
`rst_cold_stable_ref_clk_no` are sampled on every `clk_ref_i` edge of the run.
"""

from __future__ import annotations

import random

import cocotb
from cocotb.triggers import ClockCycles, ReadOnly, RisingEdge, with_timeout
from cocotb.utils import get_sim_time
from env.smc_reset_item import SmcResetItem, SmcResetOp
from env.smc_sys_axi_agent import SmcSysAxiItem, SmcSysAxiOp

from ._one_shot import _OneShot
from .smc_addr_map import (
    SPM_MEMORY_BASE,
    ZEROER_CTRL_DEST_ADDR,
    ZEROER_CTRL_SIZE,
    ZEROER_CTRL_STATUS,
    cpu_ctrl_u32,
    reset_unit_u32,
    smc_addr,
    smc_indexed_addr,
)
from .smc_csr_seq_utils import SmcCsrSeq
from .smc_dma_sanity_test_seq import (
    DMA_CONFIG_ENABLED_ND,
    DMA_CTRL_CONFIG,
    DMA_CTRL_DONE_0,
    DMA_CTRL_DST_ADDRESS_HI,
    DMA_CTRL_DST_ADDRESS_LO,
    DMA_CTRL_DST_STRIDE_HI,
    DMA_CTRL_DST_STRIDE_LO,
    DMA_CTRL_LENGTH_HI,
    DMA_CTRL_LENGTH_LO,
    DMA_CTRL_NEXT_ID_0,
    DMA_CTRL_NUM_REPETITIONS_HI,
    DMA_CTRL_NUM_REPETITIONS_LO,
    DMA_CTRL_SRC_ADDRESS_HI,
    DMA_CTRL_SRC_ADDRESS_LO,
    DMA_CTRL_SRC_STRIDE_HI,
    DMA_CTRL_SRC_STRIDE_LO,
    DMA_CTRL_STATUS_0,
    INBOUND0_END,
    INBOUND0_FILTER_CONFIG,
    INBOUND0_START,
    OUTBOUND0_END,
    OUTBOUND0_FILTER_CONFIG,
    OUTBOUND0_START,
    PASS_ALL_CONFIG,
)
from .smc_filter_reset_word_test_seq import RESET_CFG, RESET_END, RESET_START
from .smc_isolate_pin_utils import drive_isolate_pin
from .smc_reset_seq_base import SmcResetSeqBase

SS_CONFIG = smc_addr("SMC_TOP_SMC_RESET_UNIT_SS_CONFIG_BASE_ADDR")
SS_COLD_RESET_N = smc_addr("SMC_TOP_SMC_RESET_UNIT_SS_COLD_RESET_N_BASE_ADDR")
SMCEN = smc_addr("SMC_TOP_SMC_RESET_UNIT_ISOLATE_REQ_SMCEN_REG_BASE_ADDR")
SMC_REG = smc_addr("SMC_TOP_SMC_RESET_UNIT_ISOLATE_REQ_SMC_REG_BASE_ADDR")
FLR_DELAY = smc_addr("SMC_TOP_SMC_RESET_UNIT_ISOLATE_REQ_FLR_COUNTER_VALUE_BASE_ADDR")
FLR_HOLD = smc_addr("SMC_TOP_SMC_RESET_UNIT_ISOLATE_REQ_FLR_RESET_COUNTER_VALUE_BASE_ADDR")
RESET_VECTOR_0 = smc_indexed_addr("SMC_TOP_SMC_CPU_CTRL_RESET_VECTOR_BASE_ADDR", 0)
SCRATCH_0 = smc_indexed_addr("SMC_TOP_SMC_CPU_CTRL_SCRATCH_BASE_ADDR", 0)
SCRATCH_CW_0 = smc_indexed_addr("SMC_TOP_SMC_MISC_WRAP_SCRATCH_COLD_WARM_SCRATCH_BASE_ADDR", 0)
SPM_ROM_BASE = smc_addr("SMC_TOP_SPM_ROM_MEMORY_BASE_ADDR")
SPM_ROM_SIZE = smc_addr("SMC_TOP_SPM_ROM_MEMORY_SIZE")

SMC_BIT = reset_unit_u32("RESET_UNIT__ISOLATE_REQ_SMC_REG__ISOLATE_REQ_SMC_REG_bm")
VECTOR_BM = cpu_ctrl_u32("CPU_CTRL__RESET_VECTOR__VECTOR_bm")
SCRATCH_BM = cpu_ctrl_u32("CPU_CTRL__SCRATCH__DATA_bm")

KINDS = ("COOL", "FLR", "COLD", "WDT")
OPS = ("SPM_WRITE", "SPM_READ", "DMA", "ZEROER")
PASSES = 6

# name -> (address, access bytes, field mask, RDL reset value, reset domain)
# Domains per clk_rst.adoc Reset Architecture: "primary" is reset by the cool pin, the FLR cool
# reset and the stable cold reset; "cold" only by the stable cold reset; neither by a warm reset.
REGS = {
    "SS_COLD_RESET_N": (
        SS_COLD_RESET_N,
        4,
        reset_unit_u32("RESET_UNIT__SS_COLD_RESET_N__RESET_N_N0_SCAN_bm"),
        reset_unit_u32("RESET_UNIT__SS_COLD_RESET_N__RESET_N_N0_SCAN_reset"),
        "primary",
    ),
    "RESET_VECTOR0": (
        RESET_VECTOR_0,
        8,
        VECTOR_BM,
        cpu_ctrl_u32("CPU_CTRL__RESET_VECTOR__VECTOR_reset"),
        "primary",
    ),
    "SCRATCH0": (
        SCRATCH_0,
        8,
        SCRATCH_BM,
        cpu_ctrl_u32("CPU_CTRL__SCRATCH__DATA_reset"),
        "primary",
    ),
    "SMCEN": (
        SMCEN,
        4,
        reset_unit_u32("RESET_UNIT__ISOLATE_REQ_SMCEN_REG__ISOLATE_REQ_SMCEN_REG_bm"),
        reset_unit_u32("RESET_UNIT__ISOLATE_REQ_SMCEN_REG__ISOLATE_REQ_SMCEN_REG_reset"),
        "cold",
    ),
    "FLR_DELAY": (
        FLR_DELAY,
        4,
        reset_unit_u32(
            "RESET_UNIT__ISOLATE_REQ_FLR_COUNTER_VALUE__ISOLATE_REQ_FLR_COUNTER_VALUE_bm"
        ),
        reset_unit_u32(
            "RESET_UNIT__ISOLATE_REQ_FLR_COUNTER_VALUE__ISOLATE_REQ_FLR_COUNTER_VALUE_reset"
        ),
        "cold",
    ),
    "FLR_HOLD": (
        FLR_HOLD,
        4,
        reset_unit_u32(
            "RESET_UNIT__ISOLATE_REQ_FLR_RESET_COUNTER_VALUE__"
            "ISOLATE_REQ_FLR_RESET_COUNTER_VALUE_bm"
        ),
        reset_unit_u32(
            "RESET_UNIT__ISOLATE_REQ_FLR_RESET_COUNTER_VALUE__"
            "ISOLATE_REQ_FLR_RESET_COUNTER_VALUE_reset"
        ),
        "cold",
    ),
}
LOGGED = {
    "SS_CONFIG": (SS_CONFIG, 4),
    "SCRATCH_COLD_WARM0": (SCRATCH_CW_0, 4),
}
PRIMARY_KINDS = ("COOL", "FLR", "COLD")
COLD_KINDS = ("COLD",)

# Drawn ranges, in clk_ref_i cycles for the holds and the FLR counters.
HOLD_MIN, HOLD_MAX = 40, 96
FLR_DELAY_MIN, FLR_DELAY_MAX = 0x10, 0x80
FLR_HOLD_MIN, FLR_HOLD_MAX = 40, 0xC0
DEGLITCH_SAMPLES = 32
# Assertion cycle, in clk_smc_i rises after the operation is launched.
SPM_DELAY_MAX = 8
# Passes added when none of the six had its SPM burst inside the reset, and the kinds they draw.
SPM_EXTRA_MAX = 3
EXTRA_KINDS = ("COOL", "COLD")
SPM_OPS = ("SPM_WRITE", "SPM_READ")
# The watchdog kind never draws an SPM operation: a watchdog warm reset with an SPM access in
# flight leaves the cluster boundary unanswering until a primary reset.
EXCLUDED_KIND, EXCLUDED_OPS = "WDT", SPM_OPS
OP_REDRAW_BOUND = 64
SPM_HS_BOUND = 256
ENGINE_DELAY_MIN, ENGINE_DELAY_MAX = 1, 256
VECTOR_STEP = 8

SPM_BEATS = 16
SPM_WINDOW = SPM_MEMORY_BASE + 0x8000
WINDOW = 0x0200_0000
PASS_SPAN = 0x8000
DMA_LENGTH = 0x1000
ZEROER_SIZE = 0x2000
ZEROER_START = 0x1

CDC_REF = 64
FUSE_SENSE_BOUND = 200_000
FLR_FALL_SLACK = 128
FLR_RISE_SLACK = 128
WDT_ASSERT_BOUND = 64
RELEASE_BOUND_REF = 4_000
ENGINE_IDLE_BOUND = 200_000
OP_JOIN_NS = 200_000

STEPS = ("S2", "S3", "S4", "S5", "S6")
CHK_ORDER = (
    ("CHK-RMT-PRIMARY-RESET-VALUES", "S5"),
    ("CHK-RMT-COLD-ONLY-RETAIN", "S5"),
    ("CHK-RMT-WARM-RETAIN", "S5"),
    ("CHK-RMT-WARM-EQUATION", "S4"),
    ("CHK-RMT-ALLZERO-X-FREE", "S5"),
    ("CHK-RMT-RECOVERY", "S6"),
    ("CHK-RMT-SCRATCH-LOGGED", "S5"),
)


FOUR_STATE_SIMULATORS = ("vcs", "xcelium", "xmsim", "ncsim", "questa", "modelsim", "riviera")


def four_state_simulator() -> bool:
    name = str(getattr(cocotb, "SIM_NAME", "") or "").lower()
    return any(sim in name for sim in FOUR_STATE_SIMULATORS)


def x_note() -> str:
    if four_state_simulator():
        return (
            "four-state simulator: every bit resolved (the AXI master converts the read data "
            "to an integer, which fails on an unknown bit)"
        )
    return (
        "X resolution printed, not graded: it is graded on a four-state simulator only, and "
        "none is in the scheduled runs; the values compared"
    )


def _pattern(addr: int) -> int:
    return ((addr * 29) ^ (addr >> 5) ^ 0x6B) & 0xFF


class _RefSampler:
    """Primary, warm and stable cold reset at every `clk_ref_i` edge."""

    PROBES = ("rst_primary_smc_clk_no", "tb_rst_warm_smc_clk_n", "rst_cold_stable_ref_clk_no")

    def __init__(self) -> None:
        self.samples: list[tuple[int, int, int]] = []

    async def run(self) -> None:
        dut = cocotb.top
        while True:
            await RisingEdge(dut.clk_ref_i)
            await ReadOnly()
            row = []
            for name in self.PROBES:
                value = getattr(dut, name).value
                assert value.is_resolvable, f"{name} is X/Z ({value}) at tick {len(self.samples)}"
                row.append(int(value) & 1)
            self.samples.append(tuple(row))


class _SepInWatch:
    """SEP_IN address handshakes and completed responses (B, last R beat), and the L2-frontend
    isolate's pending count of the burst's direction, at `clk_smc_i` rises."""

    def __init__(self, write: bool) -> None:
        self.addr = 0
        self.resp = 0
        self.l2_probe = "tb_cpu_l2_pending_aw" if write else "tb_cpu_l2_pending_ar"
        self.l2_launch: int | None = None
        self.l2_issued = False

    @staticmethod
    def _hs(dut, valid: str, ready: str, last: str | None = None) -> bool:
        sigs = [getattr(dut, n).value for n in (valid, ready) + ((last,) if last else ())]
        return all(v.is_resolvable and int(v) for v in sigs)

    async def run(self) -> None:
        dut = cocotb.top
        while True:
            await RisingEdge(dut.clk_smc_i)
            await ReadOnly()
            self.addr += self._hs(dut, "s_axi_awvalid", "s_axi_awready")
            self.addr += self._hs(dut, "s_axi_arvalid", "s_axi_arready")
            self.resp += self._hs(dut, "s_axi_bvalid", "s_axi_bready")
            self.resp += self._hs(dut, "s_axi_rvalid", "s_axi_rready", "s_axi_rlast")
            value = getattr(dut, self.l2_probe).value
            pending = int(value) if value.is_resolvable else -1
            if self.l2_launch is None:
                self.l2_launch = pending
            elif self.l2_launch == 0 and pending > 0:
                self.l2_issued = True


class _Pass:
    def __init__(self, index: int, kind: str) -> None:
        self.index = index
        self.kind = kind
        self.op = ""
        self.delay = 0
        self.hold = 0
        self.patterns: dict[str, int] = {}
        self.logged: dict[str, int] = {}
        self.fate = ""
        self.window = (0, 0)
        self.assert_tick = 0
        self.release_tick = 0
        self.after: dict[str, int] = {}
        self.logged_after: dict[str, int] = {}
        self.recovery = 0
        self.fate_item: SmcSysAxiItem | None = None
        self.dma_id = -1
        self.busy_at_assert: int | None = None
        self.added = False
        self.op_redraws = 0
        self.burst_at_assert: tuple[int, int, int | None, bool] | None = None
        self.watch: _SepInWatch | None = None
        self.watch_task = None

    def inside(self) -> bool:
        """The SPM burst issued past the L2-frontend isolate into the cluster (its pending count
        rose from 0 after the launch) with its SEP_IN address handshake done and its response not
        returned."""
        if self.burst_at_assert is None:
            return False
        addr, resp, l2_launch, l2_issued = self.burst_at_assert
        return (addr, resp) == (1, 0) and l2_launch == 0 and l2_issued

    def cell(self) -> str:
        return (
            f"P{self.index} {self.kind}/{self.op} delay {self.delay} hold {self.hold} "
            f"FLR 0x{self.patterns['FLR_DELAY']:x}/0x{self.patterns['FLR_HOLD']:x}"
        )


class smc_reset_mid_transaction_rand_test_seq(SmcResetSeqBase, SmcCsrSeq):
    """Drawn reset kind, in-flight operation, assertion cycle, hold and patterns per pass."""

    def __init__(self, name: str = "smc_reset_mid_transaction_rand_test_seq", *, seed: int) -> None:
        super().__init__(name)
        self.dispatch_reset = None
        self.seed = seed
        self.rng = random.Random(self.seed)
        self.passes: list[_Pass] = []
        self.sampler: _RefSampler | None = None
        self.stamps: list[tuple[str, int, int]] = []
        self.chk_lines: list[str] = []
        self.waits: list[str] = []
        self.texts: dict[str, list[str]] = {c: [] for c, _ in CHK_ORDER}
        self.done = False

    async def _dispatch_reset_item(self, item: SmcResetItem) -> None:
        await self.dispatch_reset(item)

    # -- plumbing ---------------------------------------------------------

    def _mark(self, step: str, index: int) -> None:
        self.stamps.append((step, index, int(get_sim_time("ps"))))

    def _tick(self) -> int:
        return len(self.sampler.samples)

    async def _access(
        self, name: str, addr: int, op: SmcSysAxiOp, data: int = 0, length: int = 4
    ) -> int:
        item = SmcSysAxiItem(f"{'rd' if op is SmcSysAxiOp.READ else 'wr'}_{name}")
        item.op, item.addr, item.length, item.wdata = op, addr, length, data
        await self.start_item(item)
        await self.finish_item(item)
        self.accesses += 1
        assert item.resp_code == 0, f"{name}@0x{addr:x}: response {item.resp_code}, want OKAY"
        return int(item.rdata) if op is SmcSysAxiOp.READ else 0

    async def _rd(self, name: str, addr: int, length: int = 4) -> int:
        return await self._access(name, addr, SmcSysAxiOp.READ, length=length)

    async def _wr(self, name: str, addr: int, data: int, length: int = 4) -> None:
        await self._access(name, addr, SmcSysAxiOp.WRITE, data, length)

    async def _ref_ticks(self, count: int) -> None:
        await ClockCycles(cocotb.top.clk_ref_i, count)

    async def _ref_until(self, label: str, probe, level: int, bound: int, on_edge=None) -> int:
        dut = cocotb.top
        for n in range(bound + 1):
            value = probe.value
            if value.is_resolvable and int(value) == level:
                self.waits.append(f"{label}={n}/{bound} clk_ref_i")
                return self._tick()
            if on_edge is not None:
                on_edge()
            await RisingEdge(dut.clk_ref_i)
        raise AssertionError(f"{label}: probe not {level} within {bound} clk_ref_i edges")

    # -- draw -------------------------------------------------------------

    def _draw(self) -> None:
        kinds = self.rng.sample(KINDS, len(KINDS))
        kinds += [self.rng.choice(KINDS) for _ in range(PASSES - len(KINDS))]
        for n, kind in enumerate(kinds):
            self.passes.append(self._draw_pass(n, kind, OPS))
        assert set(kinds[: len(KINDS)]) == set(KINDS)
        cocotb.log.info(
            "RAND-SEED: %d; RAND-DRAW: %s",
            self.seed,
            "; ".join(self._draw_text(p) for p in self.passes),
        )

    @staticmethod
    def _draw_text(p: _Pass) -> str:
        return (
            f"{p.cell()} patterns "
            + " ".join(f"{k}=0x{v:x}" for k, v in {**p.patterns, **p.logged}.items())
            + f" recovery=0x{p.recovery:x} op_redraws={p.op_redraws}"
        )

    def _draw_pass(self, n: int, kind: str, ops: tuple[str, ...]) -> _Pass:
        used: set[int] = set()

        def fresh(lo: int, hi: int, reset: int) -> int:
            while True:
                value = self.rng.randint(lo, hi)
                if value != reset and value not in used:
                    used.add(value)
                    return value

        p = _Pass(n, kind)
        p.op = self.rng.choice(ops)
        while kind == EXCLUDED_KIND and p.op in EXCLUDED_OPS:
            assert p.op_redraws < OP_REDRAW_BOUND, f"P{n} {kind}: no op outside {EXCLUDED_OPS}"
            p.op_redraws += 1
            p.op = self.rng.choice(ops)
        assert not (kind == EXCLUDED_KIND and p.op in EXCLUDED_OPS), (
            f"P{n} {kind}/{p.op}: the watchdog kind is never drawn with an SPM operation"
        )
        if p.op.startswith("SPM"):
            p.delay = self.rng.randint(0, SPM_DELAY_MAX)
        else:
            p.delay = self.rng.randint(ENGINE_DELAY_MIN, ENGINE_DELAY_MAX)
        pats = p.patterns
        pats["SS_COLD_RESET_N"] = fresh(1, 0xFFFF_FFFF, REGS["SS_COLD_RESET_N"][3])
        vector = SPM_ROM_BASE + VECTOR_STEP * self.rng.randint(1, SPM_ROM_SIZE // VECTOR_STEP - 1)
        while vector in used or vector == REGS["RESET_VECTOR0"][3]:
            vector = SPM_ROM_BASE + VECTOR_STEP * self.rng.randint(
                1, SPM_ROM_SIZE // VECTOR_STEP - 1
            )
        used.add(vector)
        pats["RESET_VECTOR0"] = vector
        pats["SCRATCH0"] = fresh(1, 0xFFFF_FFFF, REGS["SCRATCH0"][3])
        pats["SMCEN"] = fresh(1, 0xFFFF_FFFF, REGS["SMCEN"][3])
        pats["FLR_DELAY"] = fresh(FLR_DELAY_MIN, FLR_DELAY_MAX, REGS["FLR_DELAY"][3])
        pats["FLR_HOLD"] = fresh(FLR_HOLD_MIN, FLR_HOLD_MAX, REGS["FLR_HOLD"][3])
        p.logged["SS_CONFIG"] = fresh(1, 0xFFFF_FFFF, 0)
        p.logged["SCRATCH_COLD_WARM0"] = fresh(1, 0xFFFF_FFFF, 0)
        p.recovery = SPM_ROM_BASE + VECTOR_STEP * self.rng.randint(
            1, SPM_ROM_SIZE // VECTOR_STEP - 1
        )
        p.hold = pats["FLR_HOLD"] if kind == "FLR" else self.rng.randint(HOLD_MIN, HOLD_MAX)
        assert p.hold >= HOLD_MIN > DEGLITCH_SAMPLES, f"{p.cell()}: hold under {HOLD_MIN}"
        assert FLR_DELAY_MIN <= pats["FLR_DELAY"] <= FLR_DELAY_MAX
        assert FLR_HOLD_MIN <= pats["FLR_HOLD"] <= FLR_HOLD_MAX
        all_pats = list(pats.values()) + list(p.logged.values())
        assert 0 not in all_pats and len(set(all_pats)) == len(all_pats)
        return p

    def _add_spm_pass(self) -> _Pass:
        """A pass added because no SPM burst so far was inside its reset: SPM write or read, a
        cool-pin or cold kind (the watchdog x SPM filter of `_draw_pass` applies), the drawn cycle
        counted from the burst's issue into the cluster."""
        kind = self.rng.choice(EXTRA_KINDS)
        p = self._draw_pass(len(self.passes), kind, SPM_OPS)
        p.added = True
        self.passes.append(p)
        cocotb.log.info("RAND-DRAW added pass: %s", self._draw_text(p))
        return p

    # -- per-pass actions -------------------------------------------------

    async def _pass_all(self, p: _Pass, on: bool) -> None:
        cfg = PASS_ALL_CONFIG if on else RESET_CFG
        start = 0 if on else RESET_START
        end = 0x00FF_FFFF_FFFF_FFFF if on else RESET_END
        for bank, (a_start, a_end, a_cfg) in (
            ("IN", (INBOUND0_START, INBOUND0_END, INBOUND0_FILTER_CONFIG)),
            ("OUT", (OUTBOUND0_START, OUTBOUND0_END, OUTBOUND0_FILTER_CONFIG)),
        ):
            tag = f"P{p.index}_{bank}_{'PASS' if on else 'RESTORE'}"
            await self._wr(f"{tag}_START", a_start, start, 8)
            await self._wr(f"{tag}_END", a_end, end, 8)
            await self._wr(f"{tag}_CFG", a_cfg, cfg, 8)

    async def _program(self, p: _Pass) -> None:
        for name, (addr, length, _, _, _) in REGS.items():
            await self._wr(f"P{p.index}_{name}", addr, p.patterns[name], length)
        for name, (addr, length) in LOGGED.items():
            await self._wr(f"P{p.index}_{name}", addr, p.logged[name], length)
        await self._ref_ticks(CDC_REF)
        self.waits.append(f"P{p.index}_cdc_allowance={CDC_REF} clk_ref_i")
        for name, (addr, length, mask, _, _) in REGS.items():
            got = await self._rd(f"P{p.index}_{name}_RB", addr, length) & mask
            assert got == p.patterns[name], (
                f"{p.cell()}: {name} reads 0x{got:x} before the reset, wrote 0x{p.patterns[name]:x}"
            )
        got = await self._rd(f"P{p.index}_SCRATCH_COLD_WARM0_RB", SCRATCH_CW_0)
        assert got == p.logged["SCRATCH_COLD_WARM0"], f"{p.cell()}: SCRATCH_COLD_WARM0 0x{got:x}"
        p.logged["SS_CONFIG_RB"] = await self._rd(f"P{p.index}_SS_CONFIG_RB", SS_CONFIG)

    def _base(self, p: _Pass) -> int:
        return WINDOW + p.index * PASS_SPAN

    async def _launch(self, p: _Pass):
        """Start the drawn operation; return the task of an SEP_IN access, if any."""
        responder = self.cfg.sys_out_mem
        base = self._base(p)
        if p.op.startswith("SPM"):
            item = SmcSysAxiItem(f"P{p.index}_{p.op}")
            item.op = SmcSysAxiOp.WRITE if p.op == "SPM_WRITE" else SmcSysAxiOp.READ
            item.addr = SPM_WINDOW + p.index * 0x100
            item.length = 8
            item.beats = SPM_BEATS
            item.wdata = int.from_bytes(
                bytes(_pattern(item.addr + i) for i in range(8 * SPM_BEATS)), "little"
            )
            item.allow_reset_abort = True
            item.allow_timeout = True
            item.allow_error = True
            p.fate_item = item
            p.watch = _SepInWatch(item.op is SmcSysAxiOp.WRITE)
            p.watch_task = cocotb.start_soon(p.watch.run())
            return cocotb.start_soon(
                _OneShot(item, f"P{p.index}_op_os").start(self.env.sys_axi_agent.sequencer)
            )
        assert responder is not None, "SYS_OUT responder not bound"
        await self._pass_all(p, True)
        if p.op == "DMA":
            src, dst = base, base + 0x2000
            responder.write(src, bytes(_pattern(src + i) for i in range(DMA_LENGTH)))
            responder.write(dst, bytes([0xEE]) * DMA_LENGTH)
            for reg, value in (
                (DMA_CTRL_CONFIG, DMA_CONFIG_ENABLED_ND),
                (DMA_CTRL_DST_ADDRESS_LO, dst & 0xFFFF_FFFF),
                (DMA_CTRL_DST_ADDRESS_HI, dst >> 32),
                (DMA_CTRL_SRC_ADDRESS_LO, src & 0xFFFF_FFFF),
                (DMA_CTRL_SRC_ADDRESS_HI, src >> 32),
                (DMA_CTRL_LENGTH_LO, DMA_LENGTH),
                (DMA_CTRL_LENGTH_HI, 0),
                (DMA_CTRL_DST_STRIDE_LO, 0),
                (DMA_CTRL_DST_STRIDE_HI, 0),
                (DMA_CTRL_SRC_STRIDE_LO, 0),
                (DMA_CTRL_SRC_STRIDE_HI, 0),
                (DMA_CTRL_NUM_REPETITIONS_LO, 1),
                (DMA_CTRL_NUM_REPETITIONS_HI, 0),
            ):
                await self._wr(f"P{p.index}_DMA_0x{reg & 0xFFF:03x}", reg, value)
            p.dma_id = await self._rd(f"P{p.index}_DMA_NEXT_ID", DMA_CTRL_NEXT_ID_0)
        else:
            dst = base + 0x4000
            responder.write(dst, bytes([0xA5]) * ZEROER_SIZE)
            await self._wr(f"P{p.index}_ZEROER_DEST", ZEROER_CTRL_DEST_ADDR, dst, 8)
            await self._wr(f"P{p.index}_ZEROER_SIZE", ZEROER_CTRL_SIZE, ZEROER_SIZE, 8)
            await self._wr(f"P{p.index}_ZEROER_START", ZEROER_CTRL_STATUS, ZEROER_START, 8)
        return None

    def _busy(self, p: _Pass) -> int | None:
        if p.op == "DMA":
            return int(cocotb.top.tb_dma_busy.value)
        if p.op == "ZEROER":
            return int(cocotb.top.tb_zeroer_busy.value)
        return None

    def _burst_state(self, p: _Pass) -> None:
        """At the reset's assertion, the SPM burst's address handshakes and responses so far, the
        L2-frontend pending count at the launch and whether the burst was issued into the
        cluster."""
        if p.watch is not None:
            w = p.watch
            p.burst_at_assert = (w.addr, w.resp, w.l2_launch, w.l2_issued)
            p.watch_task.kill()

    async def _inject(self, p: _Pass) -> None:
        dut = cocotb.top
        if p.added:
            for n in range(SPM_HS_BOUND + 1):
                if p.watch.addr and p.watch.l2_issued:
                    self.waits.append(f"P{p.index}_spm_cluster_issue={n}/{SPM_HS_BOUND} clk_smc_i")
                    break
                await RisingEdge(dut.clk_smc_i)
            else:
                raise AssertionError(
                    f"{p.cell()}: SPM burst not issued into the cluster within {SPM_HS_BOUND} "
                    f"clk_smc_i rises ({p.watch.l2_probe} at launch {p.watch.l2_launch})"
                )
        await ClockCycles(dut.clk_smc_i, p.delay)
        busy_at_assert = self._busy(p)
        p.window = (self._tick(), 0)
        if p.kind == "COOL":
            await RisingEdge(dut.clk_ref_i)
            dut.rst_cool_ni.value = 0
            p.assert_tick = self._tick()
            self._burst_state(p)
            await self._ref_ticks(p.hold)
            dut.rst_cool_ni.value = 1
            p.release_tick = self._tick()
        elif p.kind == "WDT":
            await RisingEdge(dut.clk_ref_i)
            dut.tb_sep_wdt_reset_n.value = 0
            p.assert_tick = self._tick()
            self._burst_state(p)
            await self._ref_ticks(p.hold)
            dut.tb_sep_wdt_reset_n.value = 1
            p.release_tick = self._tick()
        elif p.kind == "COLD":
            await self._send(SmcResetOp.COLD_RST_LO, item_name=f"p{p.index}_cold_lo")
            p.assert_tick = self._tick()
            self._burst_state(p)
            await self._ref_ticks(p.hold)
            await self._send(SmcResetOp.COLD_RST_HI, item_name=f"p{p.index}_cold_hi")
            p.release_tick = self._tick()
        else:
            await RisingEdge(dut.clk_ref_i)
            dut.tb_cfg_flr_pf_active.value = 1
            p.assert_tick = self._tick()
            # The FLR cool reset falls a counted delay after the request: the engine's busy is
            # taken at the last clk_ref_i edge before the fall, not before the request.
            last = [busy_at_assert]

            def sample() -> None:
                last[0] = self._busy(p)

            await self._ref_until(
                f"P{p.index}_flr_cool_fall",
                dut.tb_rst_cool_from_flr,
                0,
                p.patterns["FLR_DELAY"] + FLR_FALL_SLACK,
                sample,
            )
            busy_at_assert = last[0]
            self._burst_state(p)
            dut.tb_cfg_flr_pf_active.value = 0
            await self._ref_until(
                f"P{p.index}_flr_cool_rise",
                dut.tb_rst_cool_from_flr,
                1,
                p.patterns["FLR_HOLD"] + FLR_RISE_SLACK,
            )
            p.release_tick = self._tick()
        p.busy_at_assert = busy_at_assert

    async def _release(self, p: _Pass) -> None:
        await self._wait_released(f"P{p.index}_released", bound=RELEASE_BOUND_REF)
        await self.wait_fuse_sense_done(FUSE_SENSE_BOUND)
        self.waits.append(f"P{p.index}_fuse_sense_done<={FUSE_SENSE_BOUND} clk_smc_i")
        await self._ref_ticks(4)
        p.window = (p.window[0], self._tick())

    def _equation(self, p: _Pass) -> str:
        s = self.sampler.samples
        start, stop = p.window
        rows = s[start:stop]
        bad = [start + i for i, r in enumerate(rows) if r[0] == 0 and r[1] != 0]
        assert not bad, f"{p.cell()}: warm released at ticks {bad[:8]} while primary was low"
        primary_low = sum(1 for r in rows if r[0] == 0)
        if p.kind == "WDT":
            high = [start + i for i, r in enumerate(rows) if r[0] != 1]
            assert not high, f"{p.cell()}: primary low at ticks {high[:8]} on a watchdog reset"
            fall = next((t for t in range(p.assert_tick, p.release_tick) if s[t][1] == 0), None)
            assert fall is not None and fall - p.assert_tick <= WDT_ASSERT_BOUND, (
                f"{p.cell()}: warm did not fall within {WDT_ASSERT_BOUND} clk_ref_i edges of the "
                f"watchdog pin (first low {fall})"
            )
            up = [t for t in range(fall, p.release_tick) if s[t][1] != 0]
            assert not up, f"{p.cell()}: warm released at ticks {up[:8]} during the pulse"
            return (
                f"{p.cell()}: primary high at all {len(rows)} ticks, warm low at every tick from "
                f"{fall} ({fall - p.assert_tick} after the pin fell, printed) to the pin release "
                f"{p.release_tick}"
            )
        assert primary_low > 0, f"{p.cell()}: primary never asserted in ticks {start}..{stop}"
        cold_low = sum(1 for r in rows if r[2] == 0)
        if p.kind == "COLD":
            assert cold_low > 0, f"{p.cell()}: stable cold reset never asserted"
        return (
            f"{p.cell()}: warm low at all {primary_low} ticks with primary low in ticks "
            f"{start}..{stop} (stable cold low at {cold_low}, printed)"
        )

    async def _fate(self, p: _Pass, task) -> str:
        dut = cocotb.top
        if task is not None:
            await with_timeout(task, OP_JOIN_NS, "ns")
            self.waits.append(f"P{p.index}_op_join<={OP_JOIN_NS} ns")
            item = p.fate_item
            hs, resp, l2_launch, l2_issued = p.burst_at_assert
            return (
                f"{p.op} at the reset assertion: {hs} SEP_IN address handshake(s), {resp} "
                f"response(s), {p.watch.l2_probe} {l2_launch} at launch, issued into the cluster: "
                f"{l2_issued}, burst inside the reset: {p.inside()}; resp={item.resp_code} "
                f"reset_aborted={item.reset_aborted} timed_out={item.timed_out}"
            )
        sig = dut.tb_dma_busy if p.op == "DMA" else dut.tb_zeroer_busy
        await self._wait_low(f"P{p.index}_{p.op}_idle", sig)
        responder = self.cfg.sys_out_mem
        base = self._base(p)
        if p.op == "DMA":
            got = bytes(responder.read(base + 0x2000, DMA_LENGTH))
            copied = sum(1 for i, b in enumerate(got) if b == _pattern(base + i))
            done = await self._rd(f"P{p.index}_DMA_DONE", DMA_CTRL_DONE_0)
            status = await self._rd(f"P{p.index}_DMA_STATUS", DMA_CTRL_STATUS_0)
            return (
                f"DMA id {p.dma_id} busy at {self._busy_when(p)} {p.busy_at_assert}; after "
                f"release DONE_0 "
                f"{done} STATUS_0 0x{status:x}, {copied} of {DMA_LENGTH} bytes copied"
            )
        got = bytes(responder.read(base + 0x4000, ZEROER_SIZE))
        zeroed = sum(1 for b in got if b == 0)
        status = await self._rd(f"P{p.index}_ZEROER_STATUS", ZEROER_CTRL_STATUS, 8)
        return (
            f"zeroer busy at {self._busy_when(p)} {p.busy_at_assert}; after release CTRL_STATUS "
            f"0x{status:x}, {zeroed} of {ZEROER_SIZE} bytes zero"
        )

    @staticmethod
    def _busy_when(p: _Pass) -> str:
        if p.kind == "FLR":
            return "the last clk_ref_i edge before the FLR cool reset fell"
        return "assertion"

    async def _wait_low(self, label: str, sig) -> None:
        clk = cocotb.top.clk_smc_i
        for n in range(ENGINE_IDLE_BOUND + 1):
            if int(sig.value) == 0:
                self.waits.append(f"{label}={n}/{ENGINE_IDLE_BOUND} clk_smc_i")
                return
            await RisingEdge(clk)
        raise AssertionError(f"{label}: busy after {ENGINE_IDLE_BOUND} clk_smc_i rises")

    async def _compare(self, p: _Pass) -> None:
        primary = p.kind in PRIMARY_KINDS
        cold = p.kind in COLD_KINDS
        zero_parts = []
        for name, (addr, length, mask, reset, domain) in REGS.items():
            raw = await self._rd(f"P{p.index}_{name}_POST", addr, length)
            got = raw & mask
            p.after[name] = got
            reset_here = primary if domain == "primary" else cold
            want = reset if reset_here else p.patterns[name]
            assert got == want, (
                f"{p.cell()}: {name} reads 0x{got:x} (raw 0x{raw:x}) after the reset, want "
                f"0x{want:x} ({'RDL reset value' if reset_here else 'programmed pattern'}, "
                f"{domain} domain)"
            )
            if reset_here and reset == 0:
                zero_parts.append(f"{name}=0x{raw:x}")
        for name, (addr, length) in LOGGED.items():
            p.logged_after[name] = await self._rd(f"P{p.index}_{name}_POST", addr, length)
        drawn = f"drawn={p.cell()}"
        if p.kind in PRIMARY_KINDS:
            vals = " ".join(
                f"{n}=0x{p.after[n]:x}" for n in ("SS_COLD_RESET_N", "RESET_VECTOR0", "SCRATCH0")
            )
            self.texts["CHK-RMT-PRIMARY-RESET-VALUES"].append(f"{drawn}: {vals}")
            vals = " ".join(f"{n}=0x{p.after[n]:x}" for n in ("SMCEN", "FLR_DELAY", "FLR_HOLD"))
            fate = "reset" if cold else "kept"
            self.texts["CHK-RMT-COLD-ONLY-RETAIN"].append(f"{drawn}: {fate} {vals}")
        else:
            vals = " ".join(f"{n}=0x{v:x}" for n, v in p.after.items())
            self.texts["CHK-RMT-WARM-RETAIN"].append(f"{drawn}: kept {vals}")
        if zero_parts:
            self.texts["CHK-RMT-ALLZERO-X-FREE"].append(f"{drawn}: {' '.join(zero_parts)}")
        self.texts["CHK-RMT-SCRATCH-LOGGED"].append(
            f"{drawn}: SCRATCH_COLD_WARM0 0x{p.logged['SCRATCH_COLD_WARM0']:x} -> "
            f"0x{p.logged_after['SCRATCH_COLD_WARM0']:x}, SS_CONFIG wrote "
            f"0x{p.logged['SS_CONFIG']:x} read 0x{p.logged['SS_CONFIG_RB']:x} -> "
            f"0x{p.logged_after['SS_CONFIG']:x}"
        )

    async def _recover(self, p: _Pass) -> None:
        word = p.recovery
        await self._wr(f"P{p.index}_RECOVERY_WR", RESET_VECTOR_0, word, 8)
        got = await self._rd(f"P{p.index}_RECOVERY_RD", RESET_VECTOR_0, 8) & VECTOR_BM
        assert got == word, f"{p.cell()}: recovery read 0x{got:x}, wrote 0x{word:x}"
        self.texts["CHK-RMT-RECOVERY"].append(f"P{p.index} wrote and read 0x{word:x} OKAY")
        for name, (addr, length, mask, reset, _) in REGS.items():
            await self._wr(f"P{p.index}_{name}_RESTORE", addr, reset, length)
            got = await self._rd(f"P{p.index}_{name}_RESTORE_RB", addr, length) & mask
            assert got == reset, f"{p.cell()}: {name} restore reads 0x{got:x}"
        for name, (addr, length) in LOGGED.items():
            await self._wr(f"P{p.index}_{name}_RESTORE", addr, 0, length)
        latch = await self._rd(f"P{p.index}_SMC_REG", SMC_REG)
        if latch & SMC_BIT:
            await self._wr(f"P{p.index}_SMC_REG_CLR", SMC_REG, SMC_BIT)
            latch = await self._rd(f"P{p.index}_SMC_REG_CLR_RB", SMC_REG)
            assert latch & SMC_BIT == 0, f"{p.cell()}: ISOLATE_REQ_SMC_REG 0x{latch:x}"
        if not p.op.startswith("SPM"):
            await self._pass_all(p, False)

    # -- body -------------------------------------------------------------

    async def body(self) -> None:
        dut = cocotb.top
        await self.wait_fuse_sense_done(FUSE_SENSE_BOUND)
        self.waits.append(f"fuse_sense_done<={FUSE_SENSE_BOUND} clk_smc_i")
        for name in _RefSampler.PROBES + (
            "rst_cool_ni",
            "tb_cfg_flr_pf_active",
            "tb_sep_wdt_reset_n",
            "tb_rst_cool_from_flr",
            "tb_dma_busy",
            "tb_zeroer_busy",
            "tb_cpu_l2_pending_aw",
            "tb_cpu_l2_pending_ar",
        ):
            assert hasattr(dut, name), f"tb_top has no {name}"
        dut.tb_cfg_flr_pf_active.value = 0
        dut.tb_sep_wdt_reset_n.value = 1
        dut.rst_cool_ni.value = 1
        drive_isolate_pin(dut, 0)
        self.sampler = _RefSampler()
        cocotb.start_soon(self.sampler.run())
        self._draw()
        await self._ref_ticks(2)
        self._mark("S1", -1)
        for p in list(self.passes):
            await self._run_pass(p)
        while (
            not any(q.inside() for q in self.passes) and len(self.passes) < PASSES + SPM_EXTRA_MAX
        ):
            await self._run_pass(self._add_spm_pass())
        drive_isolate_pin(dut, None)
        self._print_checkers()
        kinds = [p.kind for p in self.passes]
        assert PASSES <= len(self.passes) <= PASSES + SPM_EXTRA_MAX, f"{len(self.passes)} passes"
        assert set(kinds[: len(KINDS)]) == set(KINDS), f"kinds {kinds}"
        bound = self.cfg.axi_timeout_ns
        self.waits.append(f"axi_access<={bound} ns per access ({self.accesses} accesses)")
        cocotb.log.info(
            "CHK-TIMEOUT-PATHS: %d bounded waits: %s; reset release bound %d clk_ref_i edges, "
            "FLR cool fall/rise bounds counter + %d/%d, watchdog warm assert %d, engine idle %d "
            "clk_smc_i rises, in-flight access join %d ns; expiry raises AssertionError",
            len(self.waits) + len(self._timeout_paths),
            "; ".join(self.waits + self._timeout_paths),
            RELEASE_BOUND_REF,
            FLR_FALL_SLACK,
            FLR_RISE_SLACK,
            WDT_ASSERT_BOUND,
            ENGINE_IDLE_BOUND,
            OP_JOIN_NS,
        )
        self._nonvac()
        self.done = True

    async def _run_pass(self, p: _Pass) -> None:
        await self._program(p)
        task = await self._launch(p)
        self._mark("S2", p.index)
        await self._inject(p)
        self._mark("S3", p.index)
        await self._release(p)
        self.texts["CHK-RMT-WARM-EQUATION"].append(self._equation(p))
        p.fate = await self._fate(p, task)
        cocotb.log.info("P%d in-flight operation, measured: %s", p.index, p.fate)
        self._mark("S4", p.index)
        await self._compare(p)
        self._mark("S5", p.index)
        await self._recover(p)
        self._mark("S6", p.index)

    def _print_checkers(self) -> None:
        xnote = x_note()
        for chk, _ in CHK_ORDER:
            parts = self.texts[chk]
            assert parts, f"{chk}: no pass graded it"
            text = "; ".join(parts)
            if chk == "CHK-RMT-ALLZERO-X-FREE":
                text = f"{text}; {xnote}"
            if chk == "CHK-RMT-SCRATCH-LOGGED":
                text = f"{text}; logged, not compared"
            self.chk_lines.append(chk)
            cocotb.log.info("%s: %s", chk, text)

    def _nonvac(self) -> None:
        order = [(s, i) for s, i, _ in self.stamps]
        want = [("S1", -1)]
        for p in self.passes:
            want += [(s, p.index) for s in STEPS]
        assert order == want, f"step order {order}"
        stamps = [ps for _, _, ps in self.stamps]
        assert all(b > a for a, b in zip(stamps, stamps[1:])), f"stamps not increasing {stamps}"
        assert self.chk_lines == [c for c, _ in CHK_ORDER], f"checker lines {self.chk_lines}"
        kinds = {k: sum(1 for p in self.passes if p.kind == k) for k in KINDS}
        paired = [p.cell() for p in self.passes if p.kind == EXCLUDED_KIND and p.op in EXCLUDED_OPS]
        assert not paired, f"watchdog x SPM pass ran: {paired}"
        spm = [
            f"P{p.index} {p.kind}/{p.op}{' added' if p.added else ''} inside={p.inside()}"
            for p in self.passes
            if p.op.startswith("SPM")
        ]
        inside = [p for p in self.passes if p.inside()]
        assert inside, f"no SPM burst inside its reset: {spm}"
        added = len(self.passes) - PASSES
        cocotb.log.info(
            "CHK-NONVAC: ordered fence S1 < (S2 < S3 < S4 < S5 < S6) x %d (%d drawn, %d added); "
            "stamps %s; checker lines %s printed after the last pass; passes per kind %s; no "
            "watchdog x SPM pass; SPM bursts inside their reset (issued into the cluster past the "
            "L2-frontend isolate, response not returned) %d, at least one required: %s",
            len(self.passes),
            PASSES,
            added,
            ",".join(str(ps) for ps in stamps),
            ",".join(self.chk_lines),
            kinds,
            len(inside),
            spm,
        )
