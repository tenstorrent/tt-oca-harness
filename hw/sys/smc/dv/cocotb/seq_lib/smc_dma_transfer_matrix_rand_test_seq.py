# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Seeded DMA copy geometry and burst shaping through the SYS_OUT responder.

Specs hw/sys/smc/doc/dma.adoc, vendor idma overlay dma_ctrl.rdl,
doc/programmer/src/smc-programming.adoc (DMA Engine).

Sources and destinations sit in the SYS_OUT responder memory and are preloaded and read back
through its backdoor. Every AR and AW handshake of the exported SYS_OUT probes is recorded per
clk_smc_i rise with the length and size from u_output_axi_if, and each burst is attributed to a
transfer by the address range of that transfer.
"""

from __future__ import annotations

import copy
import random

import cocotb
from cocotb.triggers import ClockCycles, ReadOnly, RisingEdge
from cocotb.utils import get_sim_time
from env.smc_sys_axi_agent import SmcSysAxiItem, SmcSysAxiOp

from .smc_addr_map import (
    _DMA_CTRL_H,
    DMA_CONFIG_DECOUPLE_AW,
    DMA_CONFIG_DECOUPLE_RW,
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
    _field_mask,
)
from .smc_csr_seq_utils import SmcCsrSeq
from .smc_output_fabric_vip_utils import PASS_ALL_CONFIG

N_TRANSFERS = 12
N_LAUNCHES = N_TRANSFERS + 2
WINDOW = 0x0200_0000
REGION = WINDOW + 0x10_0000
CASE_SPAN = 0x2_0000
DST_OFFSET = 0x1_0000
LENGTH_MIN, LENGTH_MAX = 1, 2048
REPS_MIN, REPS_MAX = 1, 16
STRIDE_EXTRA_MAX = 256
WORD = 8
LLEN_MAX = 7
GUARD = 16
SENTINEL = 0xEE
ADDR_LIMIT = 1 << 40
KIB2 = 2048
MAX_BEATS = 256
POLL_LIMIT = 3000
DRAW_TRIES = 64
POLL_CYCLES = 50
FUSE_SENSE_BOUND = 200_000
ID_MASK = 0xFFFF_FFFF

SRC_REDUCE = _field_mask(_DMA_CTRL_H, "DMA_CTRL__CONFIG__SRC_REDUCE_LEN_bm")
DST_REDUCE = _field_mask(_DMA_CTRL_H, "DMA_CTRL__CONFIG__DST_REDUCE_LEN_bm")
SRC_LLEN_BP = _field_mask(_DMA_CTRL_H, "DMA_CTRL__CONFIG__SRC_MAX_LLEN_bp")
DST_LLEN_BP = _field_mask(_DMA_CTRL_H, "DMA_CTRL__CONFIG__DST_MAX_LLEN_bp")
SRC_LLEN_BM = _field_mask(_DMA_CTRL_H, "DMA_CTRL__CONFIG__SRC_MAX_LLEN_bm")
DST_LLEN_BM = _field_mask(_DMA_CTRL_H, "DMA_CTRL__CONFIG__DST_MAX_LLEN_bm")

STEPS = ("S1", "S2", "S3", "S4", "S5", "S6")
CHECKS = (
    ("S3", "CHK-DXM-BYTE-EXACT"),
    ("S3", "CHK-DXM-DONE-ID"),
    ("S3", "CHK-DXM-BURST-BOUND"),
    ("S4", "CHK-DXM-ND-CLEAR"),
    ("S5", "CHK-DXM-ZERO-LENGTH"),
)

_TB_SIGNALS = (
    "tb_output_axi_arvalid",
    "tb_output_axi_arready",
    "tb_output_axi_araddr",
    "tb_output_axi_awvalid",
    "tb_output_axi_awready",
    "tb_output_axi_awaddr",
    "tb_output_axi_resp_hold",
    "tb_dma_busy",
)
_IF_SIGNALS = ("arlen", "arsize", "awlen", "awsize")

# (address, beats, bytes per beat)
Burst = tuple[int, int, int]


def _pattern(tag: int, addr: int) -> int:
    """A source byte; never the sentinel, so a copied byte always differs from an uncopied one."""
    value = ((addr * 13) ^ (addr >> 7) ^ (tag * 0x5B) ^ 0x3C) & 0xFF
    return value ^ 0x01 if value == SENTINEL else value


def _last_byte(addr: int, beats: int, bytes_per_beat: int) -> int:
    return (addr & ~(bytes_per_beat - 1)) + beats * bytes_per_beat - 1


def _next_id(done: int) -> int:
    nxt = (done + 1) & ID_MASK
    return nxt if nxt else 1


class _Sampler:
    """Records every SYS_OUT AR and AW handshake with its length and size."""

    def __init__(self, dut) -> None:
        self.dut = dut
        self.ar: list[Burst] = []
        self.aw: list[Burst] = []

    @staticmethod
    def _bit(sig, name: str) -> int:
        value = sig.value
        assert value.is_resolvable, f"{name} is X/Z ({value})"
        return int(value)

    async def run(self) -> None:
        dut = self.dut
        ifc = dut.u_output_axi_if
        while True:
            await RisingEdge(dut.clk_smc_i)
            await ReadOnly()
            for ch, store in (("ar", self.ar), ("aw", self.aw)):
                valid = self._bit(getattr(dut, f"tb_output_axi_{ch}valid"), f"{ch}valid")
                ready = self._bit(getattr(dut, f"tb_output_axi_{ch}ready"), f"{ch}ready")
                if valid and ready:
                    addr = self._bit(getattr(dut, f"tb_output_axi_{ch}addr"), f"{ch}addr")
                    beats = self._bit(getattr(ifc, f"{ch}len"), f"u_output_axi_if.{ch}len") + 1
                    size = self._bit(getattr(ifc, f"{ch}size"), f"u_output_axi_if.{ch}size")
                    store.append((addr, beats, 1 << size))


class _Xfer:
    """One drawn transfer: geometry, CONFIG and what the run recorded."""

    def __init__(self, idx: int, rng: random.Random) -> None:
        self.idx = idx
        self.name = f"T{idx}"
        self.length = rng.randint(LENGTH_MIN, LENGTH_MAX)
        self.reps = rng.randint(REPS_MIN, REPS_MAX)
        self.src_stride = self.length + rng.randint(0, STRIDE_EXTRA_MAX)
        self.dst_stride = self.length + rng.randint(0, STRIDE_EXTRA_MAX)
        self.src_off = rng.randint(0, WORD - 1)
        self.dst_off = rng.randint(0, WORD - 1)
        self.decouple_aw = rng.randint(0, 1)
        self.src_reduce = rng.randint(0, 1)
        self.src_llen = rng.randint(0, LLEN_MAX)
        self.dst_reduce = rng.randint(0, 1)
        self.dst_llen = rng.randint(0, LLEN_MAX)
        base = REGION + idx * CASE_SPAN
        self.src = base + self.src_off
        self.dst = base + DST_OFFSET + self.dst_off
        self.id = -1
        self.done_before = -1
        self.done_after = -1
        self.status = -1
        self.polls = 0
        self.done_reads: list[int] = []
        self.ar: list[Burst] = []
        self.aw: list[Burst] = []

    @property
    def config(self) -> int:
        value = DMA_CONFIG_ENABLED_ND
        value |= DMA_CONFIG_DECOUPLE_AW if self.decouple_aw else 0
        value |= SRC_REDUCE if self.src_reduce else 0
        value |= DST_REDUCE if self.dst_reduce else 0
        value |= (self.src_llen << SRC_LLEN_BP) & SRC_LLEN_BM
        value |= (self.dst_llen << DST_LLEN_BP) & DST_LLEN_BM
        return value

    def clone(self, name: str, base: int) -> _Xfer:
        """The same drawn geometry and CONFIG at another base."""
        other = copy.copy(self)
        other.name = name
        other.src = base + self.src_off
        other.dst = base + DST_OFFSET + self.dst_off
        other.ar, other.aw = [], []
        return other

    def span(self, stride: int) -> int:
        return (self.reps - 1) * stride + self.length

    def src_rows(self) -> list[int]:
        return [self.src + n * self.src_stride for n in range(self.reps)]

    def dst_rows(self) -> list[int]:
        return [self.dst + n * self.dst_stride for n in range(self.reps)]

    def binding(self, side: str) -> bool:
        """True when the reduce bit of `side` ("src" or "dst") is set and a row of that side
        crosses a 2^(MAX_LLEN+3)-byte block boundary that is not a 2 KiB boundary, so the
        reduced bound splits the row where the 2 KiB bound alone would not."""
        reduce, llen = (
            (self.src_reduce, self.src_llen) if side == "src" else (self.dst_reduce, self.dst_llen)
        )
        if not reduce:
            return False
        block = 1 << (llen + 3)
        for a in self.src_rows() if side == "src" else self.dst_rows():
            last = a + self.length - 1
            for b in range((a // block + 1) * block, last + 1, block):
                if b % KIB2:
                    return True
        return False

    def check_filters(self) -> None:
        assert self.config & DMA_CONFIG_ENABLED_ND, f"{self.name}: ENABLED_ND clear"
        assert not self.config & DMA_CONFIG_DECOUPLE_RW, f"{self.name}: DECOUPLE_RW set"
        assert self.src_stride >= self.length and self.dst_stride >= self.length, (
            f"{self.name}: stride below the row width {self.length}"
        )
        src_end = self.src + self.span(self.src_stride)
        dst_end = self.dst + self.span(self.dst_stride)
        assert src_end + GUARD <= self.dst - GUARD or dst_end + GUARD <= self.src - GUARD, (
            f"{self.name}: source and destination spans overlap"
        )
        assert max(src_end, dst_end) + GUARD < ADDR_LIMIT, f"{self.name}: address too high"

    def cells(self) -> str:
        return (
            f"{self.name}(len={self.length} reps={self.reps} sstride={self.src_stride} "
            f"dstride={self.dst_stride} soff={self.src_off} doff={self.dst_off} "
            f"aw={self.decouple_aw} sred={self.src_reduce} sllen={self.src_llen} "
            f"dred={self.dst_reduce} dllen={self.dst_llen})"
        )


class smc_dma_transfer_matrix_rand_test_seq(SmcCsrSeq):
    """Twelve seeded copies, an ENABLED_ND-clear launch and a zero-length launch."""

    def __init__(
        self,
        name: str = "smc_dma_transfer_matrix_rand_test_seq",
        *,
        seed: int,
        grade_zero_length_done: bool = False,
    ) -> None:
        super().__init__(name)
        self.grade_zero_length_done = grade_zero_length_done
        self.steps: list[tuple[str, int]] = []
        self.chk_steps: list[tuple[str, str]] = []
        self.chk_ids: list[str] = []
        self.sampler: _Sampler | None = None
        self.seed = seed
        self.rng = random.Random(self.seed)
        self.xfers: list[_Xfer] = []
        self.nd_src = -1
        self.zero_src = -1
        self.last_done = 0
        self.launches = 0
        self.timeout_paths: list[str] = []
        self.binding: dict[str, list[str]] = {"AR": [], "AW": []}

    # -- plumbing ---------------------------------------------------------

    def _mark(self, step: str) -> None:
        self.steps.append((step, int(get_sim_time("ps"))))

    def _chk(self, step: str, chk_id: str, text: str) -> None:
        assert self.steps and self.steps[-1][0] == step, f"{chk_id} printed before {step} ended"
        self.chk_steps.append((step, chk_id))
        self.chk_ids.append(chk_id)
        cocotb.log.info("%s: %s", chk_id, text)

    @property
    def _responder(self):
        responder = self.cfg.sys_out_mem
        assert responder is not None, "SYS_OUT responder not bound"
        return responder

    @property
    def _s(self) -> _Sampler:
        assert self.sampler is not None, "sampler not started"
        return self.sampler

    async def _pass_all(self) -> None:
        for name, addr, value in (
            ("IN_START", INBOUND0_START, 0),
            ("IN_END", INBOUND0_END, 0x00FF_FFFF_FFFF_FFFF),
            ("IN_CFG", INBOUND0_FILTER_CONFIG, PASS_ALL_CONFIG),
            ("OUT_START", OUTBOUND0_START, 0),
            ("OUT_END", OUTBOUND0_END, 0x00FF_FFFF_FFFF_FFFF),
            ("OUT_CFG", OUTBOUND0_FILTER_CONFIG, PASS_ALL_CONFIG),
        ):
            await self.csr_write(f"PASS_{name}", addr, value, length=8)

    def _draw(self) -> None:
        for attempt in range(1, DRAW_TRIES + 1):
            self.xfers = [_Xfer(i, self.rng) for i in range(N_TRANSFERS)]
            if all(any(x.binding(side) for x in self.xfers) for side in ("src", "dst")):
                break
        else:
            raise AssertionError(f"no draw held a binding reduce-set row per side in {DRAW_TRIES}")
        for x in self.xfers:
            x.check_filters()
        self.nd_src = self.rng.randrange(N_TRANSFERS)
        self.zero_src = self.rng.randrange(N_TRANSFERS)
        cocotb.log.info(
            "RAND-SEED: %d; RAND-DRAW (attempt %d): %s; ENABLED_ND-clear launch on the geometry "
            "and CONFIG of T%d; zero-length launch on the geometry and CONFIG of T%d",
            self.seed,
            attempt,
            " ".join(x.cells() for x in self.xfers),
            self.nd_src,
            self.zero_src,
        )

    def _seed_rows(self, x: _Xfer, tag: int) -> None:
        for addr in x.src_rows():
            self._responder.write(addr, bytes(_pattern(tag, addr + i) for i in range(x.length)))
        span = x.span(x.dst_stride)
        self._responder.write(x.dst - GUARD, bytes([SENTINEL]) * (span + 2 * GUARD))

    def _golden(self, x: _Xfer, tag: int, copied: bool) -> bytes:
        span = x.span(x.dst_stride)
        image = bytearray([SENTINEL]) * (span + 2 * GUARD)
        if copied:
            for n, src in enumerate(x.src_rows()):
                off = GUARD + n * x.dst_stride
                image[off : off + x.length] = bytes(_pattern(tag, src + i) for i in range(x.length))
        return bytes(image)

    def _compare(self, x: _Xfer, tag: int, copied: bool, label: str) -> None:
        span = x.span(x.dst_stride) + 2 * GUARD
        want = self._golden(x, tag, copied)
        got = bytes(self._responder.read(x.dst - GUARD, span))
        if got != want:
            idx = next(i for i, (a, b) in enumerate(zip(got, want)) if a != b)
            raise AssertionError(
                f"{label} {x.cells()}: destination byte 0x{x.dst - GUARD + idx:x} is "
                f"0x{got[idx]:02x}, want 0x{want[idx]:02x}"
            )
        for addr in x.src_rows():
            src = bytes(self._responder.read(addr, x.length))
            assert src == bytes(_pattern(tag, addr + i) for i in range(x.length)), (
                f"{label} {x.cells()}: source row at 0x{addr:x} changed"
            )

    async def _program(self, x: _Xfer, config: int, length: int) -> None:
        for reg, value in (
            (DMA_CTRL_CONFIG, config),
            (DMA_CTRL_DST_ADDRESS_LO, x.dst & 0xFFFF_FFFF),
            (DMA_CTRL_DST_ADDRESS_HI, x.dst >> 32),
            (DMA_CTRL_SRC_ADDRESS_LO, x.src & 0xFFFF_FFFF),
            (DMA_CTRL_SRC_ADDRESS_HI, x.src >> 32),
            (DMA_CTRL_LENGTH_LO, length),
            (DMA_CTRL_LENGTH_HI, 0),
            (DMA_CTRL_DST_STRIDE_LO, x.dst_stride),
            (DMA_CTRL_DST_STRIDE_HI, 0),
            (DMA_CTRL_SRC_STRIDE_LO, x.src_stride),
            (DMA_CTRL_SRC_STRIDE_HI, 0),
            (DMA_CTRL_NUM_REPETITIONS_LO, x.reps),
            (DMA_CTRL_NUM_REPETITIONS_HI, 0),
        ):
            await self.csr_write(f"{x.name}_0x{reg & 0xFFF:03x}", reg, value)

    async def _launch(self, x: _Xfer) -> int:
        """One NEXT_ID_0 read launches the programmed command; returns its response code."""
        x.done_before = self.last_done
        item = SmcSysAxiItem(f"rd_{x.name}_NEXT_ID")
        item.op = SmcSysAxiOp.READ
        item.addr = DMA_CTRL_NEXT_ID_0
        item.length = 4
        await self.start_item(item)
        await self.finish_item(item)
        self.accesses += 1
        self.launches += 1
        x.id = item.rdata
        return item.resp_code

    async def _await_done(self, x: _Xfer) -> None:
        done = -1
        for poll in range(1, POLL_LIMIT + 1):
            done = await self.csr_read(f"{x.name}_DONE", DMA_CTRL_DONE_0)
            if done == x.id:
                x.polls = poll
                x.done_after = done
                self.last_done = done
                x.status = await self.csr_read(f"{x.name}_STATUS", DMA_CTRL_STATUS_0)
                return
            await ClockCycles(cocotb.top.clk_smc_i, POLL_CYCLES)
        status = await self.csr_read(f"{x.name}_STATUS_TMO", DMA_CTRL_STATUS_0)
        raise AssertionError(
            f"{x.name}: DONE_0 reads {done}, not the returned id {x.id}, after {POLL_LIMIT} "
            f"polls of {POLL_CYCLES} clk_smc_i cycles (STATUS_0 0x{status:x}, "
            f"DONE_0 before the launch {x.done_before}); {x.cells()}"
        )

    async def _await_settle(self, x: _Xfer) -> None:
        """Polls DONE_0 until it has moved from its pre-launch value and two consecutive reads
        agree with tb_dma_busy low; fails when POLL_LIMIT reads pass first. The DONE_0 values
        are printed, not compared."""
        moved = False
        idle = False
        for poll in range(1, POLL_LIMIT + 1):
            done = await self.csr_read(f"{x.name}_DONE", DMA_CTRL_DONE_0)
            x.done_reads.append(done)
            x.polls = poll
            moved = moved or done != x.done_before
            busy = cocotb.top.tb_dma_busy.value
            idle = busy.is_resolvable and int(busy) == 0
            if moved and idle and len(x.done_reads) > 1 and x.done_reads[-2] == done:
                break
            await ClockCycles(cocotb.top.clk_smc_i, POLL_CYCLES)
        else:
            raise AssertionError(
                f"{x.name}: not settled after {POLL_LIMIT} DONE_0 reads {POLL_CYCLES} clk_smc_i "
                f"cycles apart: moved={moved} idle={idle}, DONE_0 before the launch "
                f"{x.done_before}, last reads {x.done_reads[-3:]}; {x.cells()}"
            )
        x.done_after = x.done_reads[-1]
        self.last_done = x.done_after
        x.status = await self.csr_read(f"{x.name}_STATUS", DMA_CTRL_STATUS_0)

    def _check_id(self, x: _Xfer, label: str, done_compared: bool = True) -> None:
        want = _next_id(x.done_before)
        assert x.id != 0, f"{label}: NEXT_ID_0 returned 0"
        assert x.id == want, (
            f"{label}: NEXT_ID_0 returned {x.id}, DONE_0 before the launch {x.done_before} "
            f"gives {want}"
        )
        if done_compared:
            assert x.done_after == x.id, f"{label}: DONE_0 {x.done_after}, returned id {x.id}"

    def _collect(self, x: _Xfer, ar0: int, aw0: int) -> None:
        s = self._s
        src_end = x.src + x.span(x.src_stride)
        dst_end = x.dst + x.span(x.dst_stride)
        x.ar = [b for b in s.ar[ar0:] if x.src - WORD <= b[0] < src_end]
        x.aw = [b for b in s.aw[aw0:] if x.dst - WORD <= b[0] < dst_end]

    @staticmethod
    def _bound(x: _Xfer, kind: str, bursts: list[Burst], reduce: int, llen: int) -> str:
        assert bursts, f"{x.name}: no {kind} burst observed for {x.cells()}"
        beats_max, block = (1 << llen, 1 << (llen + 3)) if reduce else (MAX_BEATS, KIB2)
        longest = 0
        for addr, beats, bpb in bursts:
            last = _last_byte(addr, beats, bpb)
            assert beats <= beats_max, (
                f"{x.name}: {kind} burst 0x{addr:x} has {beats} beats, limit {beats_max} "
                f"(reduce {reduce}, MAX_LLEN {llen}); {x.cells()}"
            )
            assert addr // block == last // block, (
                f"{x.name}: {kind} burst 0x{addr:x}..0x{last:x} crosses a {block}-byte boundary "
                f"(reduce {reduce}, MAX_LLEN {llen}); {x.cells()}"
            )
            longest = max(longest, beats)
        return f"{kind} {len(bursts)} longest {longest}/{beats_max} block {block}"

    # -- steps ------------------------------------------------------------

    async def _s1(self) -> None:
        dut = cocotb.top
        for name in _TB_SIGNALS:
            assert hasattr(dut, name), f"tb_top has no {name}"
        for name in _IF_SIGNALS:
            assert hasattr(dut.u_output_axi_if, name), f"u_output_axi_if has no {name}"
        await self.wait_fuse_sense_done(FUSE_SENSE_BOUND)
        dut.tb_output_axi_resp_hold.value = 0
        await self._pass_all()
        self.sampler = _Sampler(dut)
        cocotb.start_soon(self.sampler.run())
        self.last_done = await self.csr_read("DONE_BASE", DMA_CTRL_DONE_0)
        cocotb.log.info("DONE_0 baseline %d before the first launch", self.last_done)
        self._draw()
        await ClockCycles(dut.clk_smc_i, 2)
        self._mark("S1")

    async def _s2(self) -> None:
        s = self._s
        for x in self.xfers:
            self._seed_rows(x, x.idx)
            ar0, aw0 = len(s.ar), len(s.aw)
            await self._program(x, x.config, x.length)
            await self._launch(x)
            await self._await_done(x)
            await ClockCycles(cocotb.top.clk_smc_i, 1)
            busy = cocotb.top.tb_dma_busy.value
            assert busy.is_resolvable and int(busy) == 0, (
                f"{x.name}: tb_dma_busy {busy} after DONE_0 reached {x.id}"
            )
            self._collect(x, ar0, aw0)
            self._check_id(x, x.name)
            self._compare(x, x.idx, True, x.name)
            cocotb.log.info(
                "%s retired: id %d DONE_0 %d->%d in %d polls, STATUS_0 0x%x (printed), AR %d AW %d",
                x.cells(),
                x.id,
                x.done_before,
                x.done_after,
                x.polls,
                x.status,
                len(x.ar),
                len(x.aw),
            )
        self._mark("S2")

    async def _s3(self) -> list[tuple[str, str]]:
        for x in self.xfers:
            self._compare(x, x.idx, True, f"{x.name} after all twelve")
        bounds = []
        for x in self.xfers:
            ar = self._bound(x, "AR", x.ar, x.src_reduce, x.src_llen)
            aw = self._bound(x, "AW", x.aw, x.dst_reduce, x.dst_llen)
            bounds.append(f"{x.name}: {ar}; {aw}")
        self.binding = {
            "AR": [f"{x.name}({len(x.ar)} AR)" for x in self.xfers if x.binding("src") and x.ar],
            "AW": [f"{x.name}({len(x.aw)} AW)" for x in self.xfers if x.binding("dst") and x.aw],
        }
        await ClockCycles(cocotb.top.clk_smc_i, 2)
        self._mark("S3")
        drawn = " ".join(x.cells() for x in self.xfers)
        ids = ", ".join(f"{x.name} {x.done_before}->{x.id} ({x.polls} polls)" for x in self.xfers)
        sentinel = sum(x.span(x.dst_stride) + 2 * GUARD - x.reps * x.length for x in self.xfers)
        return [
            (
                "CHK-DXM-BYTE-EXACT",
                f"all {N_TRANSFERS} destination spans equal the golden image byte for byte "
                f"right after each retirement and again after the last, {sentinel} sentinel "
                f"bytes between and around the rows unchanged, every source row unchanged; "
                f"drawn={drawn}",
            ),
            (
                "CHK-DXM-DONE-ID",
                f"each of the {N_TRANSFERS} single NEXT_ID_0 reads returned DONE_0 + 1 (zero "
                f"skipped) and DONE_0 reached that id within {POLL_LIMIT} polls: {ids}; "
                f"drawn={drawn}",
            ),
            (
                "CHK-DXM-BURST-BOUND",
                f"every AR and AW burst of each transfer stays inside its bound (reduce set: "
                f"at most 2^MAX_LLEN beats inside a 2^(MAX_LLEN+3)-byte block; reduce clear: at "
                f"most {MAX_BEATS} beats inside a 2 KiB block): {'; '.join(bounds)}; binding "
                f"reduce-set transfers, a row crossing a 2^(MAX_LLEN+3)-byte block boundary "
                f"that is not a 2 KiB boundary: read side {self.binding['AR']}, write side "
                f"{self.binding['AW']}; drawn={drawn}",
            ),
        ]

    async def _no_data_leg(self, label: str, src: _Xfer, config: int, length: int) -> str:
        slot = N_TRANSFERS + (1 if label == "ND_CLEAR" else 2)
        x = src.clone(label, REGION + slot * CASE_SPAN)
        x.check_filters()
        tag = 0x40 + src.idx
        self._seed_rows(x, tag)
        await self._program(x, config, length)
        resp = await self._launch(x)
        if label == "ZERO_LENGTH":
            await self._await_settle(x)
            self._check_id(x, label, done_compared=False)
            self._compare(x, tag, False, label)
            grade = "compared" if self.grade_zero_length_done else "printed, not compared"
            cocotb.log.info(
                "ZERO_LENGTH DONE_0 (%s): returned id %d, DONE_0 before the "
                "launch %d, after %d (delta %d), reads %s, drawn reps %d",
                grade,
                x.id,
                x.done_before,
                x.done_after,
                x.done_after - x.done_before,
                x.done_reads,
                x.reps,
            )
            if self.grade_zero_length_done:
                assert x.done_after == x.id, (
                    f"CHK-DXM-ZERO-LENGTH-DONE FAIL: DONE_0 {x.done_after} after the LENGTH 0 "
                    f"launch, returned id {x.id} (DONE_0 before the launch {x.done_before}, "
                    f"delta {x.done_after - x.done_before}, drawn reps {x.reps}); {src.cells()}"
                )
            return (
                f"launch read returned the non-zero id {x.id} = DONE_0 before the launch "
                f"{x.done_before} plus one, all {x.span(x.dst_stride) + 2 * GUARD} destination "
                f"bytes kept the sentinel and the source rows are unchanged after {x.polls} "
                f"DONE_0 reads that ended moved and idle (tb_dma_busy low, two equal reads); "
                f"{grade}: DONE_0 before {x.done_before} after "
                f"{x.done_after} (delta {x.done_after - x.done_before}, drawn reps {x.reps}), "
                f"launch read response {resp}, STATUS_0 0x{x.status:x}; CONFIG 0x{config:x} "
                f"LENGTH {length}; drawn={src.cells()}"
            )
        await self._await_done(x)
        self._check_id(x, label)
        self._compare(x, tag, False, label)
        return (
            f"launch read returned id {x.id} (DONE_0 before {x.done_before}), DONE_0 reached it "
            f"in {x.polls} polls, all {x.span(x.dst_stride) + 2 * GUARD} destination bytes kept "
            f"the sentinel and the source rows are unchanged; printed: NEXT_ID_0 {x.id}, launch "
            f"read response {resp}, STATUS_0 0x{x.status:x}; CONFIG 0x{config:x} LENGTH "
            f"{length}; drawn={src.cells()}"
        )

    async def _s4(self) -> list[tuple[str, str]]:
        src = self.xfers[self.nd_src]
        text = await self._no_data_leg(
            "ND_CLEAR", src, src.config & ~DMA_CONFIG_ENABLED_ND, src.length
        )
        self._mark("S4")
        return [("CHK-DXM-ND-CLEAR", f"ENABLED_ND clear: {text}")]

    async def _s5(self) -> list[tuple[str, str]]:
        src = self.xfers[self.zero_src]
        text = await self._no_data_leg("ZERO_LENGTH", src, src.config, 0)
        self._mark("S5")
        return [("CHK-DXM-ZERO-LENGTH", f"LENGTH 0 with ENABLED_ND set: {text}")]

    async def body(self) -> None:
        await self._s1()
        await self._s2()
        for step, fn in (("S3", self._s3), ("S4", self._s4), ("S5", self._s5)):
            for chk, text in await fn():
                self._chk(step, chk, text)
        assert self.launches == N_LAUNCHES, f"{self.launches} launches, want {N_LAUNCHES}"
        await ClockCycles(cocotb.top.clk_smc_i, 2)
        self._mark("S6")
        period = self.cfg.smc_clk_period_ns
        self.timeout_paths = [
            f"fuse sense <= {FUSE_SENSE_BOUND} clk_smc_i rises",
            f"SEP_IN driver guard {self.cfg.axi_timeout_ns} ns per access ({self.accesses})",
            f"DONE_0 poll <= {POLL_LIMIT} reads {POLL_CYCLES} clk_smc_i cycles apart per launch "
            f"({N_LAUNCHES - 1} launches, clk_smc_i {period} ns), the zero-length launch's "
            f"DONE_0 settle poll <= {POLL_LIMIT} reads, failing unless DONE_0 moved and "
            f"tb_dma_busy is low",
        ]
        cocotb.log.info(
            "CHK-TIMEOUT-PATHS: %d bounded waits: %s; expiry raises AssertionError",
            len(self.timeout_paths),
            "; ".join(self.timeout_paths),
        )
        self._nonvac()

    def _nonvac(self) -> None:
        assert [s for s, _ in self.steps] == list(STEPS), f"step order {self.steps}"
        stamps = [ps for _, ps in self.steps]
        assert all(b > a for a, b in zip(stamps, stamps[1:])), f"stamps not increasing {stamps}"
        assert self.chk_steps == list(CHECKS), f"checker lines {self.chk_steps}"
        rows = [x.name for x in self.xfers if x.reps >= 2]
        assert rows, f"no copy of two or more rows: {[x.cells() for x in self.xfers]}"
        ar, aw = self.binding["AR"], self.binding["AW"]
        assert ar and aw, f"binding reduce-set bursts: AR {ar}, AW {aw}"
        cocotb.log.info(
            "CHK-NONVAC: ordered fence S1 < ... < S6, checker lines in step order each after "
            "its own step, %d launches, %d of %d drawn copies of two or more rows (%s), each "
            "row at its stride; binding reduce-set transfers with bursts observed: AR %d (%s), "
            "AW %d (%s); checker lines %s; stamps %s",
            self.launches,
            len(rows),
            N_TRANSFERS,
            ",".join(rows),
            len(ar),
            ",".join(ar),
            len(aw),
            ",".join(aw),
            ",".join(self.chk_ids),
            ",".join(f"{s}={ps}" for s, ps in self.steps),
        )
