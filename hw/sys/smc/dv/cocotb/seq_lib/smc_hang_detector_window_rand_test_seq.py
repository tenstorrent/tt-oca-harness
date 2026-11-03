# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Seeded hang-detector passes over the SEP, SYS and data-accelerator ports.

Specs: hw/sys/smc/regs/blocks/smc_base_config/smc_base_config.rdl (HANG_DET_CTRL,
HANG_DET_TIMEOUT_THRESHOLD) and hw/sys/smc/doc/interrupts.adoc (SMC CPU Interrupt Vector Map,
Exact Indexed Map, bit 286).

Every seed runs twelve pinned passes, one of each kind (below, fire, zero, clear) on each of the
three ports, and four drawn passes, in a drawn order. The pinned zero pass of each port holds
longer than the largest threshold plus the fire margin, so a zero threshold that acted as a large
threshold would raise the interrupt there. A pass programs the drawn threshold with
readback and `enable | irq_en` on its port (the two other detectors stay at CTRL 0), holds one
read on that port for the drawn number of `clk_smc_i` rises counted from the AR handshake the
bench sees (SEP_IN, SYS_IN, or SYS_OUT for the DMA read of the data-accelerator port), and samples
the three detector interrupts and raw bit 286 of `tb_cpu_interrupts` at every rise of the pass.
A clear pass writes `irq_en` alone to the port's CTRL at a drawn rise while the interrupt is
raised. The data-accelerator detector snoops an AR handshake inside `smc` that no bench probe
exposes and that precedes the SYS_OUT AR handshake by the fabric latency, which no document
states; the data port's fire window opens DATA_LEAD_ALLOWANCE rises before the threshold, a
DV-chosen bound on that latency.
"""

from __future__ import annotations

import random
import sys
from dataclasses import dataclass, field
from pathlib import Path

import cocotb
from cocotb.triggers import RisingEdge
from cocotb.utils import get_sim_time
from env.smc_sys_axi_agent import SmcSysAxiItem, SmcSysAxiOp

from ._one_shot import _OneShot
from .smc_addr_map import (
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
    HANG_DET_ARMED,
    HANG_DET_DATA_ACCEL_CTRL,
    HANG_DET_DATA_ACCEL_TIMEOUT,
    HANG_DET_IRQ_EN,
    HANG_DET_SEP_AXI_CTRL,
    HANG_DET_SEP_AXI_TIMEOUT,
    HANG_DET_SYS_AXI_CTRL,
    HANG_DET_SYS_AXI_TIMEOUT,
    HANG_DET_THR_VALUE,
    hang_det_ctrl_u32,
    smc_addr,
)
from .smc_csr_seq_utils import SmcCsrSeq
from .smc_output_fabric_vip_utils import (
    INBOUND0_END,
    INBOUND0_FILTER_CONFIG,
    INBOUND0_START,
    OUTBOUND0_END,
    OUTBOUND0_FILTER_CONFIG,
    OUTBOUND0_START,
    PASS_ALL_CONFIG,
)

_SMC_REG_PY = Path(__file__).resolve().parents[3] / "regs" / "gen" / "py"
if str(_SMC_REG_PY) not in sys.path:
    sys.path.insert(0, str(_SMC_REG_PY))

from smc_reg import (  # noqa: E402
    FILTER_CTRL_END_ADDR_REG_DEFAULT,
    FILTER_CTRL_FILTER_CONFIG_REG_DEFAULT,
    FILTER_CTRL_START_ADDR_REG_DEFAULT,
)

SCRATCH_COLD_WARM_0 = smc_addr("SMC_TOP_SMC_MISC_WRAP_SCRATCH_COLD_WARM_BASE_ADDR")
THRESHOLD_RESET = hang_det_ctrl_u32("SMC_BASE_CONFIG__HANG_DET_TIMEOUT_THRESHOLD__VALUE_reset")
RAW_BIT = 286
PORTS = ("SEP", "SYS", "DATA")
PORT_REGS = {
    "SEP": (HANG_DET_SEP_AXI_CTRL, HANG_DET_SEP_AXI_TIMEOUT),
    "SYS": (HANG_DET_SYS_AXI_CTRL, HANG_DET_SYS_AXI_TIMEOUT),
    "DATA": (HANG_DET_DATA_ACCEL_CTRL, HANG_DET_DATA_ACCEL_TIMEOUT),
}
KINDS = ("below", "fire", "zero", "clear")

# Threshold set; 0 disables detection (smc_base_config.rdl).
THRESHOLDS = (0, 0x40, 0x80, 0x100, 0x400, 0x1000)
NONZERO = THRESHOLDS[1:]
# Hold filters: shorter than a non-zero threshold by BELOW_MARGIN or more, longer by
# BEYOND_MARGIN or more; no hold equals its threshold.
BELOW_MARGIN = 16
BELOW_HOLD_MIN = 8
BEYOND_MARGIN = 64
BEYOND_EXTRA_MAX = 64
ZERO_HOLD_MIN, ZERO_HOLD_MAX = 0x40, 0x200
# Pinned zero passes hold past the largest threshold plus the fire margin.
ZERO_LONG_HOLD_MIN = max(NONZERO) + BEYOND_MARGIN + 1
ZERO_LONG_HOLD_MAX = 0x1100
# Bench bounds: the fire window from the threshold rise, the drop after a release or a
# CTRL write, the clear rise after the fire window, and the rises after the clear drop.
FIRE_WINDOW = 64
# DV-chosen bound on the latency from the data-accelerator detector's AR handshake to SYS_OUT.
DATA_LEAD_ALLOWANCE = 16
DROP_BOUND = 128
CLEAR_AFTER_MAX = 32
CLEAR_HELD_MIN, CLEAR_HELD_MAX = 16, 64
POST_RELEASE_RISES = DROP_BOUND + 32
DRAWN_PASSES = 4
AXI_ID_MIN, AXI_ID_MAX = 1, 63

FUSE_SENSE_BOUND = 200_000
AR_BOUND = 256
SYS_OUT_AR_BOUND = 4096
DONE_BOUND = 256
DONE_POLLS = 50

DMA_SRC_ADDR = 0x0200_0000
DMA_DST_ADDR = 0x0200_0008
DMA_LENGTH = 8
PASS_ALL_END = 0x00FF_FFFF_FFFF_FFFF
_FILTERS = (
    ("INBOUND0", INBOUND0_START, INBOUND0_END, INBOUND0_FILTER_CONFIG),
    ("OUTBOUND0", OUTBOUND0_START, OUTBOUND0_END, OUTBOUND0_FILTER_CONFIG),
)

# Checker lines print after S2.
STEPS = ("S1", "S2", "S3")
CHK_STEPS = (
    ("CHK-HDW-BELOW", "S2"),
    ("CHK-HDW-FIRES", "S2"),
    ("CHK-HDW-DISABLE", "S2"),
    ("CHK-HDW-DROP", "S2"),
    ("CHK-HDW-OR", "S2"),
)
_TAPS = (
    "tb_axi_hang_irq_sep",
    "tb_axi_hang_irq_sys",
    "tb_axi_hang_irq_data",
    "tb_cpu_interrupts",
    "tb_sep_axi_r_hold",
    "tb_sys_axi_r_hold",
    "tb_output_axi_resp_hold",
    "s_axi_arvalid",
    "s_axi_arready",
    "sys_axi_arvalid",
    "sys_axi_arready",
    "tb_output_axi_arvalid",
    "tb_output_axi_arready",
)


@dataclass
class HangPass:
    """One drawn or pinned pass and what it observed."""

    index: int
    origin: str
    port: str
    kind: str
    threshold: int
    hold: int
    clear_at: int = 0
    axi_id: int = 0
    samples: list[tuple[int, int, int, int]] = field(default_factory=list)
    fire: int = 0
    drop: int = 0
    clear_drop: int = 0

    def text(self) -> str:
        extra = f" clear_at={self.clear_at}" if self.kind == "clear" else ""
        ident = f" id={self.axi_id}" if self.port != "DATA" else ""
        return (
            f"#{self.index} {self.origin} {self.port} {self.kind} thr=0x{self.threshold:x} "
            f"hold={self.hold}{extra}{ident}"
        )


def fire_low(port: str, threshold: int) -> int:
    return threshold - (DATA_LEAD_ALLOWANCE if port == "DATA" else 0)


def draw_pass(rng: random.Random, index: int, origin: str, port: str, kind: str) -> HangPass:
    """Draw the threshold, hold and clear rise of a pass of a given port and kind."""
    threshold = 0 if kind == "zero" else rng.choice(NONZERO)
    clear_at = 0
    if kind == "zero" and origin == "pinned":
        hold = rng.randint(ZERO_LONG_HOLD_MIN, ZERO_LONG_HOLD_MAX)
    elif kind == "zero":
        hold = rng.randint(ZERO_HOLD_MIN, ZERO_HOLD_MAX)
    elif kind == "below":
        hold = rng.randint(BELOW_HOLD_MIN, threshold - BELOW_MARGIN)
    elif kind == "fire":
        hold = threshold + BEYOND_MARGIN + rng.randint(0, BEYOND_EXTRA_MAX)
    else:
        clear_at = threshold + FIRE_WINDOW + rng.randint(1, CLEAR_AFTER_MAX)
        hold = clear_at + DROP_BOUND + rng.randint(CLEAR_HELD_MIN, CLEAR_HELD_MAX)
    axi_id = rng.randint(AXI_ID_MIN, AXI_ID_MAX)
    p = HangPass(index, origin, port, kind, threshold, hold, clear_at, axi_id)
    check_pass(p)
    return p


def check_pass(p: HangPass) -> None:
    assert p.threshold in THRESHOLDS, p.text()
    assert p.hold != p.threshold, p.text()
    assert (p.kind == "zero") == (p.threshold == 0), p.text()
    if p.kind == "zero":
        assert ZERO_HOLD_MIN <= p.hold <= ZERO_LONG_HOLD_MAX, p.text()
    if p.kind == "below":
        assert BELOW_HOLD_MIN <= p.hold <= p.threshold - BELOW_MARGIN, p.text()
    if p.kind in ("fire", "clear"):
        assert p.hold >= p.threshold + BEYOND_MARGIN, p.text()
    if p.kind == "clear":
        assert p.threshold + FIRE_WINDOW < p.clear_at, p.text()
        assert p.clear_at + DROP_BOUND + CLEAR_HELD_MIN <= p.hold, p.text()
    assert AXI_ID_MIN <= p.axi_id <= AXI_ID_MAX, p.text()


def draw_passes(rng: random.Random) -> list[HangPass]:
    """Twelve pinned passes (every kind on every port) and four drawn ones, shuffled."""
    plan = [("pinned", port, kind) for port in PORTS for kind in KINDS]
    for _ in range(DRAWN_PASSES):
        port = rng.choice(PORTS)
        threshold_zero = rng.choice(THRESHOLDS) == 0
        kind = "zero" if threshold_zero else rng.choice(("below", "fire", "clear"))
        plan.append(("drawn", port, kind))
    rng.shuffle(plan)
    passes = [draw_pass(rng, i, origin, port, kind) for i, (origin, port, kind) in enumerate(plan)]
    for port in PORTS:
        for kind in KINDS:
            assert any(p.port == port and p.kind == kind for p in passes), (port, kind)
        assert any(
            p.port == port and p.kind == "zero" and p.hold >= ZERO_LONG_HOLD_MIN for p in passes
        ), f"{port}: no zero pass holding {ZERO_LONG_HOLD_MIN} rises or more"
    return passes


class _SysInReadSeq(SmcCsrSeq):
    """One SYS_IN read with an explicit ID."""

    def __init__(self, name: str, item: SmcSysAxiItem) -> None:
        super().__init__(name)
        self.item = item

    async def body(self) -> None:
        await self.start_item(self.item)
        await self.finish_item(self.item)


class smc_hang_detector_window_rand_test_seq(SmcCsrSeq):
    """Pinned and drawn holds on the three hang-detector ports, sampled at every rise."""

    def __init__(self, name: str = "smc_hang_detector_window_rand_test_seq", *, seed: int) -> None:
        super().__init__(name)
        self.seed = seed
        self.rng = random.Random(self.seed)
        self.passes: list[HangPass] = []
        self.steps: list[tuple[str, int]] = []
        self.chk_lines: list[tuple[str, str]] = []
        self.waits: dict[str, tuple[int, str, str]] = {}
        self.jtag_accesses = 0
        self.sys_in_reads = 0
        self.dma_jobs = 0
        self.done_id = 0
        self.done = False

    # -- plumbing ---------------------------------------------------------

    def _mark(self, step: str) -> None:
        self.steps.append((step, int(get_sim_time("ps"))))

    def _chk(self, step: str, chk_id: str, text: str) -> None:
        assert self.steps and self.steps[-1][0] == step, f"{chk_id} printed before {step} ended"
        self.chk_lines.append((chk_id, step))
        cocotb.log.info("%s: %s", chk_id, text)

    def _wait(self, name: str, used: int, bound: int, unit: str = "clk_smc_i rises") -> None:
        prev = self.waits.get(name, (0, "", unit))
        self.waits[name] = (max(prev[0], used), str(bound), unit)

    @staticmethod
    def _bit(name: str) -> int:
        value = getattr(cocotb.top, name).value
        assert value.is_resolvable, f"{name} is X/Z ({value})"
        return int(value)

    def _sample(self) -> tuple[int, int, int, int]:
        """(sep, sys, data, raw bit 286) at this rise."""
        return (
            self._bit("tb_axi_hang_irq_sep") & 1,
            self._bit("tb_axi_hang_irq_sys") & 1,
            self._bit("tb_axi_hang_irq_data") & 1,
            self._bit("tb_cpu_interrupts") >> RAW_BIT & 1,
        )

    async def _access(self, name: str, addr: int, op: SmcSysAxiOp, data: int = 0, length=4) -> int:
        item = SmcSysAxiItem(f"{'rd' if op is SmcSysAxiOp.READ else 'wr'}_{name}")
        item.op, item.addr, item.length, item.wdata = op, addr, length, data
        item.axi_id = 0
        await self.start_item(item)
        await self.finish_item(item)
        self.accesses += 1
        assert item.resp_code == 0, f"{name}@0x{addr:x}: response {item.resp_code}, want OKAY"
        return int(item.rdata) if op is SmcSysAxiOp.READ else 0

    async def _rd(self, name: str, addr: int, length: int = 4) -> int:
        return await self._access(name, addr, SmcSysAxiOp.READ, length=length)

    async def _wr(self, name: str, addr: int, data: int, length: int = 4) -> None:
        await self._access(name, addr, SmcSysAxiOp.WRITE, data, length)

    async def _jtag_wr(self, name: str, addr: int, data: int) -> None:
        item = SmcSysAxiItem(f"jtag_wr_{name}")
        item.op, item.addr, item.length, item.wdata = SmcSysAxiOp.WRITE, addr, 4, data
        item.axi_id = 0
        await _OneShot(item, f"{name}_os").start(self.env.jtag_axi_agent.sequencer)
        self.jtag_accesses += 1
        assert item.resp_code == 0, f"{name}: JTAG write of 0x{addr:x} answered {item.resp_code}"

    def _hold(self, port: str, value: int) -> None:
        name = {"SEP": "tb_sep_axi_r_hold", "SYS": "tb_sys_axi_r_hold"}.get(
            port, "tb_output_axi_resp_hold"
        )
        getattr(cocotb.top, name).value = value

    # -- one pass -----------------------------------------------------------

    def _start_held_read(self, p: HangPass):
        item = SmcSysAxiItem(f"rd_HELD_{p.index}")
        item.op, item.addr, item.length = SmcSysAxiOp.READ, SCRATCH_COLD_WARM_0, 4
        item.axi_id = p.axi_id
        if p.port == "SEP":
            return item, cocotb.start_soon(self._held_sep(item))
        child = _SysInReadSeq(f"held_sys_in_{p.index}", item)
        child.cfg = self.cfg
        child.env = self.env
        self.sys_in_reads += 1
        return item, cocotb.start_soon(child.start(self.env.sys_in_axi_agent.sequencer))

    async def _held_sep(self, item: SmcSysAxiItem) -> None:
        await self.start_item(item)
        await self.finish_item(item)
        self.accesses += 1

    async def _await_ar(self, p: HangPass) -> None:
        valid, ready, bound = {
            "SEP": ("s_axi_arvalid", "s_axi_arready", AR_BOUND),
            "SYS": ("sys_axi_arvalid", "sys_axi_arready", AR_BOUND),
            "DATA": ("tb_output_axi_arvalid", "tb_output_axi_arready", SYS_OUT_AR_BOUND),
        }[p.port]
        for n in range(1, bound + 1):
            await RisingEdge(cocotb.top.clk_smc_i)
            if self._bit(valid) & 1 and self._bit(ready) & 1:
                self._wait(f"{p.port} AR handshake", n, bound)
                return
        raise AssertionError(f"{p.text()}: no AR handshake on {valid} within {bound} rises")

    async def _window(self, p: HangPass) -> None:
        """Sample from the AR handshake to POST_RELEASE_RISES after the release."""
        await self._await_ar(p)
        ctrl, _ = PORT_REGS[p.port]
        clear_task = None
        for n in range(1, p.hold + POST_RELEASE_RISES + 1):
            await RisingEdge(cocotb.top.clk_smc_i)
            if n == p.hold:
                self._hold(p.port, 0)
            row = self._sample()
            p.samples.append(row)
            if p.kind == "clear" and n == p.clear_at:
                assert row[PORTS.index(p.port)] == 1, (
                    f"{p.text()}: port interrupt 0 at the drawn clear rise {n}"
                )
                write = (
                    self._jtag_wr(f"HANG_{p.port}_CLEAR_{p.index}", ctrl, HANG_DET_IRQ_EN)
                    if p.port == "SEP"
                    else self._wr(f"HANG_{p.port}_CLEAR_{p.index}", ctrl, HANG_DET_IRQ_EN)
                )
                clear_task = cocotb.start_soon(write)
        if clear_task is not None:
            await clear_task

    async def _program_dma(self, p: HangPass) -> None:
        regs = (
            ("CONFIG", DMA_CTRL_CONFIG, DMA_CONFIG_ENABLED_ND),
            ("DST_ADDRESS_LO", DMA_CTRL_DST_ADDRESS_LO, DMA_DST_ADDR & 0xFFFF_FFFF),
            ("DST_ADDRESS_HI", DMA_CTRL_DST_ADDRESS_HI, DMA_DST_ADDR >> 32),
            ("SRC_ADDRESS_LO", DMA_CTRL_SRC_ADDRESS_LO, DMA_SRC_ADDR & 0xFFFF_FFFF),
            ("SRC_ADDRESS_HI", DMA_CTRL_SRC_ADDRESS_HI, DMA_SRC_ADDR >> 32),
            ("LENGTH_LO", DMA_CTRL_LENGTH_LO, DMA_LENGTH),
            ("LENGTH_HI", DMA_CTRL_LENGTH_HI, 0),
            ("DST_STRIDE_LO", DMA_CTRL_DST_STRIDE_LO, 0),
            ("DST_STRIDE_HI", DMA_CTRL_DST_STRIDE_HI, 0),
            ("SRC_STRIDE_LO", DMA_CTRL_SRC_STRIDE_LO, 0),
            ("SRC_STRIDE_HI", DMA_CTRL_SRC_STRIDE_HI, 0),
            ("NUM_REPETITIONS_LO", DMA_CTRL_NUM_REPETITIONS_LO, 1),
            ("NUM_REPETITIONS_HI", DMA_CTRL_NUM_REPETITIONS_HI, 0),
        )
        for label, addr, value in regs:
            await self._wr(f"DMA_{label}_{p.index}", addr, value)
        job = await self._rd(f"DMA_NEXT_ID_0_{p.index}", DMA_CTRL_NEXT_ID_0)
        assert job != 0, f"{p.text()}: DMA NEXT_ID_0 read 0, the command was not accepted"
        self.dma_jobs += 1

    async def _await_dma_done(self, p: HangPass) -> None:
        done = self.done_id
        for n in range(1, DONE_POLLS + 1):
            done = await self._rd(f"DMA_DONE_0_POLL_{p.index}", DMA_CTRL_DONE_0)
            if done != self.done_id:
                self.done_id = done
                self._wait("DMA DONE_0 poll", n, DONE_POLLS, "polls")
                return
        raise AssertionError(f"{p.text()}: DONE_0 stayed {done} over {DONE_POLLS} polls")

    async def _await_read(self, p: HangPass, item: SmcSysAxiItem, task) -> None:
        for n in range(DONE_BOUND + 1):
            if task.done():
                self._wait("held read completion after the window", n, DONE_BOUND)
                assert item.resp_code == 0, f"{p.text()}: held read response {item.resp_code}"
                return
            await RisingEdge(cocotb.top.clk_smc_i)
        raise AssertionError(f"{p.text()}: held read pending {DONE_BOUND} rises after the window")

    async def _run_pass(self, p: HangPass) -> None:
        ctrl, timeout = PORT_REGS[p.port]
        await self._wr(f"HANG_{p.port}_THR_{p.index}", timeout, p.threshold)
        got = await self._rd(f"HANG_{p.port}_THR_RB_{p.index}", timeout)
        assert got & HANG_DET_THR_VALUE == p.threshold, (
            f"{p.text()}: threshold reads 0x{got:x}, wrote 0x{p.threshold:x}"
        )
        await self._wr(f"HANG_{p.port}_ARM_{p.index}", ctrl, HANG_DET_ARMED)
        await RisingEdge(cocotb.top.clk_smc_i)
        assert self._sample() == (0, 0, 0, 0), f"{p.text()}: interrupts not 0 before the hold"
        self._hold(p.port, 1)
        if p.port == "DATA":
            track = cocotb.start_soon(self._window(p))
            await self._program_dma(p)
            await track
            await self._await_dma_done(p)
        else:
            item, task = self._start_held_read(p)
            await self._window(p)
            await self._await_read(p, item, task)
        await self._wr(f"HANG_{p.port}_OFF_{p.index}", ctrl, 0)
        self._grade(p)

    def _grade(self, p: HangPass) -> None:
        col = PORTS.index(p.port)
        s = p.samples
        for i, row in enumerate(s):
            assert row[3] == (row[0] | row[1] | row[2]), (
                f"{p.text()}: raw bit 286 {row[3]} at rise {i + 1}, OR of (sep, sys, data) {row}"
            )
            peers = [row[c] for c in range(3) if c != col]
            assert not any(peers), f"{p.text()}: a peer interrupt at rise {i + 1}: {row}"
        ones = [i + 1 for i, row in enumerate(s) if row[col]]
        if p.kind in ("below", "zero"):
            assert not ones, (
                f"{p.text()}: port interrupt or raw bit 286 1 at rises {ones[:8]} of {len(s)}"
            )
            return
        assert ones, f"{p.text()}: port interrupt never rose in {len(s)} rises"
        p.fire = ones[0]
        low, high = fire_low(p.port, p.threshold), p.threshold + FIRE_WINDOW
        assert low <= p.fire <= high, (
            f"{p.text()}: port interrupt first 1 at rise {p.fire}, want {low} to {high} "
            "counted from the AR handshake"
        )
        if p.kind == "fire":
            gaps = [n for n in range(p.fire, p.hold) if not s[n - 1][col]]
            assert not gaps, f"{p.text()}: interrupt 0 at rises {gaps[:8]} before the release"
            after = [n for n in range(p.hold, len(s) + 1) if not s[n - 1][col]]
            assert after and after[0] - p.hold <= DROP_BOUND, (
                f"{p.text()}: interrupt not 0 within {DROP_BOUND} rises of the release at "
                f"{p.hold} (first 0 at {after[:1]})"
            )
            p.drop = after[0]
            back = [n for n in range(p.drop, len(s) + 1) if s[n - 1][col]]
            assert not back, f"{p.text()}: interrupt 1 again at rises {back[:8]} after the drop"
            return
        gaps = [n for n in range(p.fire, p.clear_at + 1) if not s[n - 1][col]]
        assert not gaps, f"{p.text()}: interrupt 0 at rises {gaps[:8]} before the clear"
        after = [n for n in range(p.clear_at + 1, len(s) + 1) if not s[n - 1][col]]
        assert after and after[0] - p.clear_at <= DROP_BOUND, (
            f"{p.text()}: interrupt not 0 within {DROP_BOUND} rises of the clear at {p.clear_at}"
        )
        p.clear_drop = after[0]
        back = [n for n in range(p.clear_drop, len(s) + 1) if s[n - 1][col]]
        assert not back, f"{p.text()}: interrupt 1 at rises {back[:8]} after the clear drop"
        assert p.clear_drop < p.hold, f"{p.text()}: clear drop {p.clear_drop} after the release"

    # -- steps ------------------------------------------------------------

    async def _s1(self) -> None:
        dut = cocotb.top
        await self.wait_fuse_sense_done(FUSE_SENSE_BOUND)
        self._wait("fuse_sense_done", 0, FUSE_SENSE_BOUND)
        for name in _TAPS:
            assert hasattr(dut, name), f"tb_top has no {name}"
        for port in PORTS:
            self._hold(port, 0)
        self.passes = draw_passes(self.rng)
        cocotb.log.info(
            "RAND-SEED: %d; RAND-DRAW: %d passes (%d pinned: below, fire, zero and clear on each "
            "of SEP, SYS, DATA; %d drawn), order and cells: %s",
            self.seed,
            len(self.passes),
            sum(p.origin == "pinned" for p in self.passes),
            DRAWN_PASSES,
            "; ".join(p.text() for p in self.passes),
        )
        for side, start, end, config in _FILTERS:
            await self._wr(f"{side}_START_PASS_ALL", start, 0, length=8)
            await self._wr(f"{side}_END_PASS_ALL", end, PASS_ALL_END, length=8)
            await self._wr(f"{side}_CONFIG_PASS_ALL", config, PASS_ALL_CONFIG, length=8)
            got = await self._rd(f"{side}_CONFIG_PASS_ALL_RB", config, length=8)
            assert got == PASS_ALL_CONFIG, f"{side} config reads 0x{got:x}"
        for port in PORTS:
            await self._wr(f"HANG_{port}_OFF_INIT", PORT_REGS[port][0], 0)
        self.done_id = await self._rd("DMA_DONE_0_BASELINE", DMA_CTRL_DONE_0)
        await RisingEdge(dut.clk_smc_i)
        assert self._sample() == (0, 0, 0, 0), f"interrupts after CTRL 0: {self._sample()}"
        self._mark("S1")

    async def _s2(self) -> None:
        for p in self.passes:
            await self._run_pass(p)
        self._mark("S2")
        by = {k: [p for p in self.passes if p.kind == k] for k in KINDS}
        self._chk(
            "S2",
            "CHK-HDW-BELOW",
            f"{len(by['below'])} holds shorter than a non-zero threshold by {BELOW_MARGIN} or "
            "more: the port interrupt and raw bit 286 read 0 at every rise from the AR "
            f"handshake to {POST_RELEASE_RISES} rises after the release; drawn="
            + "; ".join(f"{p.text()} rises={len(p.samples)}" for p in by["below"]),
        )
        fired = by["fire"] + by["clear"]
        self._chk(
            "S2",
            "CHK-HDW-FIRES",
            f"{len(fired)} holds longer than a non-zero threshold by {BEYOND_MARGIN} or more: "
            f"the port interrupt first read 1 at the threshold rise to that rise plus "
            f"{FIRE_WINDOW} (data port from {DATA_LEAD_ALLOWANCE} rises before, a DV-chosen "
            "bound, counted from the SYS_OUT AR handshake) and stayed 1 to the release or the "
            "clear; drawn="
            + "; ".join(
                f"{p.text()} first_rise={p.fire} (threshold {p.fire - p.threshold:+d})"
                for p in fired
            ),
        )
        self._chk(
            "S2",
            "CHK-HDW-DISABLE",
            f"{len(by['zero'])} threshold-0 holds never raised the port interrupt, the pinned one "
            f"of each port holding {ZERO_LONG_HOLD_MIN} rises or more (the largest threshold "
            f"0x{max(NONZERO):x} plus {BEYOND_MARGIN}); "
            f"{len(by['clear'])} writes of irq_en alone (enable 0) at the drawn rise of a raised "
            f"hold dropped it within {DROP_BOUND} rises and it read 0 to the release and "
            f"{POST_RELEASE_RISES} rises after; drawn="
            + "; ".join(f"{p.text()} rises={len(p.samples)}" for p in by["zero"])
            + "; "
            + "; ".join(f"{p.text()} drop_rise={p.clear_drop}" for p in by["clear"]),
        )
        self._chk(
            "S2",
            "CHK-HDW-DROP",
            f"{len(by['fire'])} released holds: the port interrupt read 0 within {DROP_BOUND} "
            "rises of the release with no CTRL write and stayed 0; drawn="
            + "; ".join(f"{p.text()} drop_rise={p.drop} (+{p.drop - p.hold})" for p in by["fire"]),
        )
        total = sum(len(p.samples) for p in self.passes)
        self._chk(
            "S2",
            "CHK-HDW-OR",
            f"raw bit 286 equalled the OR of the SEP, SYS and data-accelerator interrupts at all "
            f"{total} sampled rises of {len(self.passes)} passes, "
            f"{sum(sum(r[3] for r in p.samples) for p in self.passes)} of them at 1; "
            f"drawn={len(self.passes)} passes seed {self.seed}",
        )

    async def _s3(self) -> None:
        for port in PORTS:
            ctrl, timeout = PORT_REGS[port]
            await self._wr(f"HANG_{port}_OFF_RESTORE", ctrl, 0)
            await self._wr(f"HANG_{port}_THR_RESTORE", timeout, THRESHOLD_RESET)
            got = await self._rd(f"HANG_{port}_THR_RESTORE_RB", timeout)
            assert got & HANG_DET_THR_VALUE == THRESHOLD_RESET, f"{port} threshold 0x{got:x}"
        for side, start, end, config in _FILTERS:
            await self._wr(
                f"{side}_CONFIG_RESTORE", config, FILTER_CTRL_FILTER_CONFIG_REG_DEFAULT, length=8
            )
            await self._wr(
                f"{side}_START_RESTORE", start, FILTER_CTRL_START_ADDR_REG_DEFAULT, length=8
            )
            await self._wr(f"{side}_END_RESTORE", end, FILTER_CTRL_END_ADDR_REG_DEFAULT, length=8)
        self._mark("S3")
        waits = "; ".join(f"{k}<={b} {u} (max used {v})" for k, (v, b, u) in self.waits.items())
        cocotb.log.info(
            "CHK-TIMEOUT-PATHS: %d bounded waits: %s; held-read completion %d rises after each "
            "window; fire window %d, drop %d rises; driver guard %s ns per access (%d SEP_IN, "
            "%d JTAG, %d SYS_IN accesses); expiry raises AssertionError",
            len(self.waits) + 1,
            waits,
            DONE_BOUND,
            FIRE_WINDOW,
            DROP_BOUND,
            self.cfg.axi_timeout_ns,
            self.accesses,
            self.jtag_accesses,
            self.sys_in_reads,
        )
        self._nonvac()

    def _nonvac(self) -> None:
        assert [st for st, _ in self.steps] == list(STEPS), f"step order {self.steps}"
        stamps = [ps for _, ps in self.steps]
        assert all(b > a for a, b in zip(stamps, stamps[1:])), f"stamps not increasing {stamps}"
        assert self.chk_lines == list(CHK_STEPS), f"checker lines {self.chk_lines}"
        raised = [p for p in self.passes if p.fire]
        quiet = [p for p in self.passes if p.kind in ("below", "zero")]
        assert raised and quiet, f"raised {len(raised)}, held quiet {len(quiet)}"
        cells = {(p.port, p.kind) for p in self.passes}
        assert len(cells) == len(PORTS) * len(KINDS), f"cells run {sorted(cells)}"
        assert self.dma_jobs == sum(p.port == "DATA" for p in self.passes), self.dma_jobs
        cocotb.log.info(
            "CHK-NONVAC: ordered fence %s; stamps %s; checker lines %s; %d passes raised the "
            "interrupt, %d held without raising it; all %d port x kind cells run; %d DMA jobs; "
            "seed %d",
            " < ".join(STEPS),
            ",".join(str(ps) for ps in stamps),
            ",".join(c for c, _ in self.chk_lines),
            len(raised),
            len(quiet),
            len(cells),
            self.dma_jobs,
            self.seed,
        )

    async def body(self) -> None:
        await self._s1()
        await self._s2()
        await self._s3()
        self.done = True
