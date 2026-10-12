# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Secure DMA zero fill (OPCODE 4): the image, the beats, the erase window, errors and abort.

RANDOMIZED (SepSeededRng from the run seed). The leaf programs the secure DMA
over the CPU-LSU splice (no CPU) and keeps every buffer in SEP SRAM
(``memory_map.adoc``). A zero fill writes zeros to the destination without
reading the source, writes only inside the enabled memory range (checked on
every beat), and is rejected in hardware handshake mode (``dma.hjson``,
CONTROL.OPCODE; ``hw/sys/sep/doc/dma.adoc``, Zero Fill). The expected image and
beats come from ``env/sep_dma_model.DmaZeroFill``.

* Leg Z: one fill per destination mode {INCREMENT, INCREMENT and WRAP, fixed}
  and TRANSFER_WIDTH encoding {0, 1, 2}: a drawn chunk size and chunk count
  (one chunk for the fixed destination), a drawn start offset inside the
  64-bit beat, and a drawn total whose last beat can be narrower than the
  width. A copy of non-zero words runs just before each fill, so the data
  register holds a non-zero word when the fill starts.
* Leg W: the enabled memory range around a drawn block, with DMA_DONE and
  DMA_ERROR enabled in INTR_ENABLE: a fill of the whole range; fills that start
  below BASE (by words at width 4, by one byte at width 1), that run past LIMIT
  in one chunk, and that cross LIMIT in a later chunk; a fill whose narrow last
  beat ends on an unaligned LIMIT; a copy outside the range.
* Leg E: OPCODE 5, then a fill in hardware handshake mode with the SPI trigger
  held high by SPI CONTROL.TX_WATERMARK 1 and an empty TX FIFO
  (``hw/sys/sep/doc/spi.adoc``, DMA Trigger).
* Leg A: a fill aborted at a drawn fraction of the clean time of the same fill,
  then a recovery fill.
* Leg L, last because the lock holds until reset: RANGE_REGWEN written False,
  a write that would widen LIMIT, then a fill that runs past the locked LIMIT.

Probes: register and SRAM frontdoor over ``s_axi``; ``dma_axi_req_probe_o`` and
``dma_status_probe_o`` through ``env/sep_dma_tap.py``; ``dma_busy_probe_o``;
bits 8 and 10 of ``sep_internal_interrupts_probe_o`` (PIC sources 9 and 11);
``spi_lsio_trigger_probe_o``. No inject.

Checkers (log shape ``CHK-<ID> PASS|FAIL seed=<n> ...``):
  CHK-DMA-ZERO-IMAGE     per Leg Z cell: every word of the destination span
                         equals the model (cleared bytes 0, every other byte
                         unchanged); DONE=1, ERROR=0, ERROR_CODE=0.
  CHK-DMA-ZERO-BEAT      per Leg Z cell: no AR handshake; one AW per model
                         beat with AxLEN 0, AxADDR[31:2] and the WSTRB lanes
                         of that beat; one OKAY B per AW.
  CHK-DMA-ZERO-RESIDUE   per Leg Z cell: the cleared bytes read 0 although the
                         last word of the copy before the fill is non-zero.
  CHK-DMA-ZERO-WIN-OK    the fill of the whole range completes, clears the
                         range and leaves the guards.
  CHK-DMA-ZERO-WIN-ERR   per out-of-range fill: ERROR=1 with ERROR_CODE equal
                         to DST_ADDR_ERROR alone, AW beats for the in-range
                         beats only, the in-range beats cleared and every other
                         byte unchanged.
  CHK-DMA-ZERO-WIN-EXACT the fill whose narrow last beat ends on an unaligned
                         LIMIT completes and leaves the bytes after LIMIT.
  CHK-DMA-ZERO-COPY-CTRL a copy whose destination is outside the range
                         completes with the data copied (control: the range
                         bounds a fill, not a copy).
  CHK-DMA-ZERO-IRQ       PIC source 9 rises for the completed fill of the whole
                         range and PIC source 11 does not; PIC source 11 rises
                         for the fill past LIMIT and PIC source 9 does not.
  CHK-DMA-ZERO-OPC       OPCODE 5 sets ERROR with ERROR_CODE equal to
                         OPCODE_ERROR alone and moves no beat; after the W1C of
                         ERROR a fill completes.
  CHK-DMA-ZERO-HS        a fill in handshake mode sets ERROR with ERROR_CODE
                         equal to OPCODE_ERROR alone, moves no beat and leaves
                         the destination. Control: the trigger probe reads 1
                         when GO is written.
  CHK-DMA-ZERO-ABORT     ABORTED reads 1; the destination is whole zero words
                         followed by the sentinel words, at least one of each,
                         and reads the same again after a quarter of the clean
                         time; ABORTED clears by W1C; the recovery fill clears
                         the whole destination.
  CHK-DMA-ZERO-WIN-LOCK  RANGE_REGWEN reads other than True after it is written
                         False and LIMIT keeps its value through a later write;
                         a fill past LIMIT then stops at the first beat beyond
                         it.

Logged only: ``OBS-DMA-ZERO-ABORT``, the AR and AW handshakes after the ABORTED
rise (``sep_dma_abort_recovery_rand_test`` grades that contract).

Run mode: no_cpu, target ``lsu_stub_all_live``, ``+skip_fuse_sense``; Verilator
and VCS. Graded-window owner code from ``tb/sep_fcov_owner_codes.svh``.
"""

from __future__ import annotations

from dataclasses import dataclass

import cocotb
import pyuvm
from cocotb.triggers import ClockCycles
from env.sep_bit_watch import SepBitWatch
from env.sep_dma_model import DmaZeroFill, ZeroBeat, bytes_to_words, words_to_bytes
from env.sep_dma_tap import DmaTapEvents, SepDmaTap
from env.sep_fcov_gate import close_graded_window, open_graded_window
from env.sep_field_compare import field_compare
from env.sep_seeded_rng import SepSeededRng
from sep_base_test import sep_base_test
from sep_reg_meta import SPI_CONTROLLER, sym
from seq_lib.sep_dma_ops import (
    _D,
    DST_ADDR_HI,
    ERROR_CODE,
    ERROR_CODE_MASK,
    HANDSHAKE_INTR_ENABLE,
    INTR_ENABLE,
    OP_COPY,
    OP_ZERO,
    RANGE_LIMIT,
    RANGE_REGWEN,
    SRC_ADDR_HI,
    ST_ABORTED,
    ST_DONE,
    STATUS,
    DmaStatus,
    SepDmaOps,
    SepMemWords,
    asid_word,
)
from seq_lib.sep_spi_host_csr_seq import CONTROL as SPI_CONTROL

TEST = "sep_dma_zero_fill_rand_test"

SRAM_BASE = sym("SEP_SRAM_MEM_BASE_ADDR")
SRAM_SIZE = sym("SEP_SRAM_MEM_SIZE")
SRAM_LIMIT = SRAM_BASE + SRAM_SIZE - 1
ASID = 0x7
# The first OPCODE above ZERO.
OP_INVALID = 0x5

WIDTH = {0: 1, 1: 2, 2: 4}
# Destination mode -> (DST_CONFIG.INCREMENT, DST_CONFIG.WRAP).
MODES = {"inc": (True, False), "wrap": (True, True), "fixed": (False, False)}

DST_ERR = _D.field_mask("ERROR_CODE", "dst_addr_error")
OPC_ERR = _D.field_mask("ERROR_CODE", "opcode_error")
INTR_EN_DONE = _D.field_mask("INTR_ENABLE", "dma_done")
INTR_EN_ERROR = _D.field_mask("INTR_ENABLE", "dma_error")
HS_RESET = _D.reset32("HANDSHAKE_INTR_ENABLE")
HS_TRIGGER0 = 1 << _D.field_lsb("HANDSHAKE_INTR_ENABLE", "mask")
SPI_TX_WM = SPI_CONTROLLER.field_mask("CONTROL", "tx_watermark")
SPI_TX_WM_LSB = SPI_CONTROLLER.field_lsb("CONTROL", "tx_watermark")
REGWEN_MASK = _D.field_mask("RANGE_REGWEN", "regwen")
REGWEN_LSB = _D.field_lsb("RANGE_REGWEN", "regwen")
# RANGE_REGWEN is MuBi4 with reset True; False is its bitwise complement.
REGWEN_TRUE = (_D.reset32("RANGE_REGWEN") & REGWEN_MASK) >> REGWEN_LSB
REGWEN_FALSE = ~REGWEN_TRUE & (REGWEN_MASK >> REGWEN_LSB)

# PIC source n is bit n-1 of sep_internal_interrupts_probe_o.
PIC_DONE_BIT = 8
PIC_ERROR_BIT = 10

GUARD = 8  # bytes kept on each side of a destination
ERR_POLL_BOUND = 400  # STATUS reads in a wait for ERROR or ABORTED
TRIGGER_BOUND = 200  # clocks in a wait for the SPI trigger
IRQ_SETTLE = 50  # clocks of line sampling after DONE or ERROR
BUSY_RISE_BOUND = 2_000
ABORT_REDRAWS = 3


def nonzero_word(rng: SepSeededRng) -> int:
    """A drawn 32-bit word with no zero byte."""
    return rng.getrandbits(32) | 0x0101_0101


def span(addr: int, nbytes: int) -> tuple[int, int]:
    """First address and word count of the aligned words that cover ``nbytes`` from ``addr``."""
    lo = addr & ~3
    hi = (addr + nbytes + 3) & ~3
    return lo, (hi - lo) // 4


class Alloc:
    """Disjoint 8-aligned SRAM blocks at drawn gaps, handed out in order."""

    def __init__(self, rng: SepSeededRng) -> None:
        self.rng = rng
        self.next = SRAM_BASE + 8 * rng.randrange(0, 64)

    def take(self, nbytes: int) -> int:
        addr = self.next
        self.next = (addr + nbytes + 7) & ~7
        self.next += 8 * self.rng.randrange(0, 16)
        if self.next > SRAM_LIMIT + 1:
            raise ValueError("the drawn blocks do not fit the SRAM")
        return addr


@dataclass
class Region:
    """A word span with its drawn initial words."""

    addr: int
    words: list[int]

    @property
    def nbytes(self) -> int:
        return 4 * len(self.words)

    def image(self) -> dict[int, int]:
        return words_to_bytes(self.addr, self.words)


@dataclass
class ZCell:
    mode: str
    enc: int
    fill: DmaZeroFill
    region: Region
    copy_src: Region
    copy_dst: int


@dataclass
class WDraw:
    """The Leg W block: range [base, limit] with guards outside it."""

    region: Region
    base: int
    limit: int
    below_words: int
    below_total: int
    above_words: int
    above_extra: int
    cross_chunk: int
    cross_extra: int
    exact_trim: int
    ctrl_src: Region
    ctrl_dst: Region


def draw_region(rng: SepSeededRng, alloc: Alloc, nbytes: int) -> Region:
    addr = alloc.take(nbytes)
    return Region(addr, [nonzero_word(rng) for _ in range(-(-nbytes // 4))])


class Plan:
    """Every value of the leaf, drawn from the seed before the first DUT access."""

    def __init__(self, seed: int) -> None:
        rng = SepSeededRng(seed)
        self.seed = seed
        self.lines: list[str] = []
        alloc = Alloc(rng)
        self._leg_z(rng, alloc)
        self._leg_w(rng, alloc)
        self._leg_e(rng, alloc)
        self._leg_a(rng, alloc)
        self._leg_l(rng, alloc)

    def _leg_z(self, rng: SepSeededRng, alloc: Alloc) -> None:
        cells = [(m, e) for m in MODES for e in WIDTH]
        rng.shuffle(cells)
        self.cells: list[ZCell] = []
        for mode, enc in cells:
            w = WIDTH[enc]
            inc, wrap = MODES[mode]
            if mode == "fixed":
                chunk = w * rng.randrange(1, 9)
                total = rng.randrange(1, chunk + 1)
            else:
                n = rng.randrange(2, 5) if mode == "wrap" else rng.randrange(1, 5)
                chunk = w * rng.randrange(4, 33)
                total = (n - 1) * chunk + rng.randrange(1, chunk + 1)
            off = w * rng.randrange(0, 8 // w)
            probe = DmaZeroFill(off, total, chunk, enc, inc, wrap)
            reach = max(b.addr + b.nbytes for b in probe.beats())
            region = draw_region(rng, alloc, GUARD + reach + GUARD)
            fill = DmaZeroFill(region.addr + GUARD + off, total, chunk, enc, inc, wrap)
            copy_src = draw_region(rng, alloc, 32)
            copy_dst = alloc.take(32)
            self.cells.append(ZCell(mode, enc, fill, region, copy_src, copy_dst))
            self.lines.append(
                f"DRAW leg=Z mode={mode} enc={enc} total={total} chunk={chunk} "
                f"n={fill.n_chunks} dst=0x{fill.dst_base:08x} region=0x{region.addr:08x}+"
                f"{region.nbytes} copy_last=0x{copy_src.words[-1]:08x}"
            )

    def _leg_w(self, rng: SepSeededRng, alloc: Alloc) -> None:
        size = 4 * rng.randrange(16, 65)
        guard = 4 * rng.randrange(2, 9)
        region = draw_region(rng, alloc, guard + size + guard)
        base = region.addr + guard
        self.w = WDraw(
            region=region,
            base=base,
            limit=base + size - 1,
            below_words=rng.randrange(1, guard // 4 + 1),
            below_total=4 * rng.randrange(1, 9),
            above_words=rng.randrange(1, min(8, size // 4) + 1),
            above_extra=4 * rng.randrange(1, 5),
            cross_chunk=4 * rng.randrange(2, 9),
            cross_extra=4 * rng.randrange(1, 5),
            exact_trim=rng.randrange(1, 4),
            ctrl_src=draw_region(rng, alloc, 16),
            ctrl_dst=draw_region(rng, alloc, 16),
        )
        d = self.w
        self.lines.append(
            f"DRAW leg=W base=0x{d.base:08x} limit=0x{d.limit:08x} guard={guard} "
            f"below_words={d.below_words} below_total={d.below_total} "
            f"above_words={d.above_words} above_extra={d.above_extra} "
            f"cross_chunk={d.cross_chunk} cross_extra={d.cross_extra} exact_trim={d.exact_trim}"
        )

    def _leg_e(self, rng: SepSeededRng, alloc: Alloc) -> None:
        self.e_region = draw_region(rng, alloc, 64)
        self.e_total = 4 * rng.randrange(2, 9)
        self.lines.append(
            f"DRAW leg=E region=0x{self.e_region.addr:08x} total={self.e_total} "
            f"opcode=0x{OP_INVALID:x}"
        )

    def _leg_a(self, rng: SepSeededRng, alloc: Alloc) -> None:
        total = 4 * rng.randrange(1024, 2049)
        self.a_region = draw_region(rng, alloc, total)
        self.a_fracs = [rng.randrange(20, 81) for _ in range(ABORT_REDRAWS + 1)]
        self.lines.append(
            f"DRAW leg=A dst=0x{self.a_region.addr:08x} total={total} "
            f"fracs={','.join(map(str, self.a_fracs))}"
        )

    def _leg_l(self, rng: SepSeededRng, alloc: Alloc) -> None:
        size = 4 * rng.randrange(8, 33)
        guard = 4 * rng.randrange(2, 5)
        self.l_region = draw_region(rng, alloc, guard + size + guard)
        self.l_base = self.l_region.addr + guard
        self.l_limit = self.l_base + size - 1
        self.l_words = rng.randrange(1, min(8, size // 4) + 1)
        self.l_extra = 4 * rng.randrange(1, 5)
        self.lines.append(
            f"DRAW leg=L base=0x{self.l_base:08x} limit=0x{self.l_limit:08x} "
            f"words={self.l_words} extra={self.l_extra}"
        )


@dataclass
class FillRun:
    """What one fill or copy showed: the last STATUS, ERROR_CODE and its tap window."""

    status: DmaStatus
    error_code: int
    ev: DmaTapEvents
    go_writes: int


@pyuvm.test()
class sep_dma_zero_fill_rand_test(sep_base_test):
    """Secure DMA zero fill: image and beats per mode and width, erase window, errors, abort."""

    required_evidence = (
        "CHK-DMA-ZERO-IMAGE",
        "CHK-DMA-ZERO-BEAT",
        "CHK-DMA-ZERO-RESIDUE",
        "CHK-DMA-ZERO-WIN-OK",
        "CHK-DMA-ZERO-WIN-ERR",
        "CHK-DMA-ZERO-WIN-EXACT",
        "CHK-DMA-ZERO-COPY-CTRL",
        "CHK-DMA-ZERO-IRQ",
        "CHK-DMA-ZERO-OPC",
        "CHK-DMA-ZERO-HS",
        "CHK-DMA-ZERO-ABORT",
        "CHK-DMA-ZERO-WIN-LOCK",
    )

    # ---- log helpers ------------------------------------------------------
    def _pass(self, chk: str, ok: bool, values: str) -> None:
        line = f"{chk} {'PASS' if ok else 'FAIL'} seed={self.seed} {values}"
        if not ok:
            self.logger.error(line)
            raise AssertionError(line)
        self.logger.info(line)
        self.k += 1

    def _ctrl_missing(self, chk: str, why: str) -> None:
        line = f"CTRL-MISSING {chk} seed={self.seed} {why}"
        self.logger.error(line)
        raise AssertionError(line)

    # ---- scenario ---------------------------------------------------------
    async def run_scenario(self) -> None:
        self.seed = self.random_seed()
        self.k = 0
        plan = Plan(self.seed)
        self.logger.info("PLAN %s seed=%d legZ_cells=%d", TEST, self.seed, len(plan.cells))
        for line in plan.lines:
            self.logger.info(line)

        await self.bring_up_no_cpu()
        self.suppress_host_axi_transaction_info()
        dut = cocotb.top
        self.tap = SepDmaTap(dut).start()
        self.busy = SepBitWatch(dut.dma_busy_probe_o, name="dma_busy_probe_o").start()
        self.irq = SepBitWatch(
            dut.sep_internal_interrupts_probe_o,
            {"done": PIC_DONE_BIT, "error": PIC_ERROR_BIT},
            name="pic_src9_11",
        ).start()
        self.trigger = SepBitWatch(dut.spi_lsio_trigger_probe_o, name="spi_lsio_trigger").start()
        self.ops = SepDmaOps(self)
        self.mem = SepMemWords(self)
        try:
            open_graded_window(TEST, self.logger)
            await self._setup()
            await self._leg_z(plan)
            await self._leg_w(plan)
            await self._leg_e(plan)
            await self._leg_a(plan)
            await self._leg_l(plan)
        finally:
            close_graded_window(self.logger)
            for watch in (self.tap, self.busy, self.irq, self.trigger):
                await watch.stop()
        self.logger.info("RESULT %s seed=%d PASS checks=%d", TEST, self.seed, self.k)

    async def _setup(self) -> None:
        ops = self.ops
        await ops.program_range(SRAM_BASE, SRAM_LIMIT, valid=True)
        await ops.set_asid(ASID, ASID)
        await ops.wr(SRC_ADDR_HI, 0)
        await ops.wr(DST_ADDR_HI, 0)
        await ops.clean_state()
        await ops.wr(INTR_ENABLE, 0)
        self.logger.info(
            "SETUP range=0x%08x..0x%08x valid=1 addr_space_id=0x%02x intr_enable=0",
            SRAM_BASE,
            SRAM_LIMIT,
            asid_word(ASID, ASID),
        )

    # ---- shared pieces ----------------------------------------------------
    async def _idle(self) -> None:
        """W1C ERROR, ABORTED, DONE and CHUNK_DONE, then wait for BUSY=0."""
        await self.ops.clean_state()
        await self.ops.poll_status(lambda s: not s.busy, ERR_POLL_BOUND, "BUSY=0")

    async def _run(
        self,
        *,
        opcode: int,
        dst: int,
        total: int,
        chunk: int,
        width_enc: int = 2,
        src: int = 0,
        dst_inc: bool = True,
        dst_wrap: bool = False,
        hs: int = 0,
        stop_on_error: bool = True,
    ) -> FillRun:
        """Program one transfer, GO, and wait for DONE or ERROR (re-GO between chunks)."""
        ops = self.ops
        await ops.program_transfer(
            src=src,
            dst=dst,
            total=total,
            chunk=chunk,
            width_enc=width_enc,
            dst_inc=dst_inc,
            dst_wrap=dst_wrap,
        )
        mark = self.tap.mark()
        await ops.go(opcode=opcode, hs=hs)
        stop = (lambda s: bool(s.error or s.aborted)) if stop_on_error else (lambda s: False)
        res = await ops.run_to_done(2 * total, busy=self.busy, stop_on=stop)
        ec = await ops.rd(ERROR_CODE)
        return FillRun(res.status, ec, self.tap.since(mark), res.go_writes)

    async def _wait_status(self, mask: int, what: str) -> DmaStatus:
        return await self.ops.poll_status(lambda s: bool(s.raw & mask), ERR_POLL_BOUND, what)

    async def _read_region(self, region: Region) -> list[int]:
        return await self.mem.read(region.addr, len(region.words))

    def _expect_words(self, region: Region, fill: DmaZeroFill, beats: list[ZeroBeat]) -> list[int]:
        img = fill.dst_image(region.image(), beats)
        return bytes_to_words(img, region.addr, len(region.words))

    @staticmethod
    def _diff(got: list[int], exp: list[int], base: int) -> str:
        bad = [(i, g, e) for i, (g, e) in enumerate(zip(got, exp)) if g != e]
        if not bad:
            return "mismatches=0"
        i, g, e = bad[0]
        return f"mismatches={len(bad)} first=0x{base + 4 * i:08x} got=0x{g:08x} expect=0x{e:08x}"

    def _beat_problems(self, ev: DmaTapEvents, beats: list[ZeroBeat]) -> list[str]:
        """Differences between the tap window and the model beats of a fill."""
        out = []
        if ev.ar:
            out.append(f"ar={len(ev.ar)}")
        if len(ev.aw) != len(beats) or len(ev.w) != len(beats):
            out.append(f"aw={len(ev.aw)} w={len(ev.w)} expect={len(beats)}")
        for i, (aw, wb, beat) in enumerate(zip(ev.aw, ev.w, beats)):
            if aw.len != 0 or (aw.addr or 0) >> 2 != beat.addr >> 2 or wb.strb != beat.wstrb:
                out.append(
                    f"beat{i}: aw=0x{aw.addr or 0:08x} len={aw.len} strb=0x{wb.strb or 0:02x} "
                    f"expect aw=0x{beat.addr & ~3:08x} strb=0x{beat.wstrb:02x}"
                )
                break
        if len(ev.b) != len(ev.aw) or any(b.resp != 0 for b in ev.b):
            out.append(f"b={len(ev.b)} resp={[b.resp for b in ev.b]}")
        return out

    # ---- Leg Z: image and beats per mode and width -------------------------
    async def _leg_z(self, plan: Plan) -> None:
        for c in plan.cells:
            f = c.fill
            tag = (
                f"mode={c.mode} enc={c.enc} total={f.total} chunk={f.chunk} dst=0x{f.dst_base:08x}"
            )
            await self.mem.fill(c.region.addr, c.region.words)
            await self.mem.fill(c.copy_src.addr, c.copy_src.words)
            cp = await self._run(
                opcode=OP_COPY, src=c.copy_src.addr, dst=c.copy_dst, total=32, chunk=32
            )
            if not cp.status.done or cp.status.error:
                self._ctrl_missing("CHK-DMA-ZERO-RESIDUE", f"{tag} copy {cp.status.fmt()}")
            inc, wrap = MODES[c.mode]
            run = await self._run(
                opcode=OP_ZERO,
                dst=f.dst_base,
                total=f.total,
                chunk=f.chunk,
                width_enc=c.enc,
                dst_inc=inc,
                dst_wrap=wrap,
            )
            beats = f.beats()
            got = await self._read_region(c.region)
            exp = self._expect_words(c.region, f, beats)
            st = run.status
            ok = got == exp and st.done and not st.error and run.error_code & ERROR_CODE_MASK == 0
            self._pass(
                "CHK-DMA-ZERO-IMAGE",
                ok,
                f"{tag} {st.fmt()} error_code=0x{run.error_code:x} go_writes={run.go_writes} "
                f"{self._diff(got, exp, c.region.addr)}",
            )
            probs = self._beat_problems(run.ev, beats)
            self._pass(
                "CHK-DMA-ZERO-BEAT",
                not probs,
                f"{tag} ar={len(run.ev.ar)} aw={len(run.ev.aw)} beats={len(beats)} "
                f"{' '.join(probs) or 'shape=model'}",
            )
            cleared = sorted({beat.addr + b for beat in beats for b in range(beat.nbytes)})
            img = words_to_bytes(c.region.addr, got)
            self._pass(
                "CHK-DMA-ZERO-RESIDUE",
                all(img[a] == 0 for a in cleared),
                f"{tag} copy_last=0x{c.copy_src.words[-1]:08x} cleared_bytes={len(cleared)}",
            )
            await self._idle()

    # ---- Leg W: the erase window ------------------------------------------
    async def _window_err(
        self, d: WDraw, case: str, fill: DmaZeroFill, base: int, limit: int, irq: bool = False
    ) -> None:
        await self.ops.program_range(base, limit, valid=True)
        await self.mem.fill(d.region.addr, d.region.words)
        m_irq = self.irq.mark()
        run = await self._run(
            opcode=OP_ZERO,
            dst=fill.dst_base,
            total=fill.total,
            chunk=fill.chunk,
            width_enc=fill.width_enc,
        )
        await ClockCycles(cocotb.top.clk_i, IRQ_SETTLE)
        beats = fill.beats_in_range(base, limit)
        got = await self._read_region(d.region)
        exp = self._expect_words(d.region, fill, beats)
        st = run.status
        ec = run.error_code & ERROR_CODE_MASK
        aw = len(run.ev.aw)
        ok = st.error and not st.done and ec == DST_ERR and got == exp and aw == len(beats)
        self._pass(
            "CHK-DMA-ZERO-WIN-ERR",
            ok and not run.ev.ar,
            f"case={case} base=0x{base:08x} limit=0x{limit:08x} dst=0x{fill.dst_base:08x} "
            f"total={fill.total} chunk={fill.chunk} {st.fmt()} error_code=0x{ec:x} "
            f"aw={aw} in_range_beats={len(beats)} {self._diff(got, exp, d.region.addr)}",
        )
        if irq:
            done_r = self.irq.rises_since(m_irq, "done")
            err_r = self.irq.rises_since(m_irq, "error")
            self._pass(
                "CHK-DMA-ZERO-IRQ",
                err_r >= 1 and done_r == 0,
                f"case={case} pic_src11_rises={err_r} pic_src9_rises={done_r}",
            )
        await self._idle()

    async def _leg_w(self, plan: Plan) -> None:
        d = plan.w
        ops = self.ops
        await ops.wr(INTR_ENABLE, INTR_EN_DONE | INTR_EN_ERROR)
        size = d.limit - d.base + 1

        # The whole range.
        await ops.program_range(d.base, d.limit, valid=True)
        await self.mem.fill(d.region.addr, d.region.words)
        fill = DmaZeroFill(d.base, size, size)
        m_irq = self.irq.mark()
        run = await self._run(opcode=OP_ZERO, dst=d.base, total=size, chunk=size)
        await ClockCycles(cocotb.top.clk_i, IRQ_SETTLE)
        got = await self._read_region(d.region)
        exp = self._expect_words(d.region, fill, fill.beats())
        st = run.status
        self._pass(
            "CHK-DMA-ZERO-WIN-OK",
            st.done and not st.error and got == exp,
            f"base=0x{d.base:08x} limit=0x{d.limit:08x} {st.fmt()} "
            f"{self._diff(got, exp, d.region.addr)}",
        )
        done_r = self.irq.rises_since(m_irq, "done")
        err_r = self.irq.rises_since(m_irq, "error")
        self._pass(
            "CHK-DMA-ZERO-IRQ",
            done_r >= 1 and err_r == 0,
            f"case=in_range pic_src9_rises={done_r} pic_src11_rises={err_r}",
        )
        await self._idle()

        # Starts below BASE.
        below = d.base - 4 * d.below_words
        await self._window_err(
            d, "below", DmaZeroFill(below, d.below_total, d.below_total), d.base, d.limit
        )
        # One byte below an unaligned BASE, at width 1.
        await self._window_err(d, "below_byte", DmaZeroFill(d.base, 4, 4, 0), d.base + 1, d.limit)
        # Runs past LIMIT in one chunk.
        start = d.limit + 1 - 4 * d.above_words
        total = 4 * d.above_words + d.above_extra
        await self._window_err(
            d, "above", DmaZeroFill(start, total, total), d.base, d.limit, irq=True
        )
        # Crosses LIMIT in a later chunk.
        total = size + d.cross_extra
        await self._window_err(
            d, "cross_chunk", DmaZeroFill(d.base, total, d.cross_chunk), d.base, d.limit
        )

        # A narrow last beat that ends on an unaligned LIMIT.
        limit = d.limit - d.exact_trim
        await ops.program_range(d.base, limit, valid=True)
        await self.mem.fill(d.region.addr, d.region.words)
        total = size - d.exact_trim
        fill = DmaZeroFill(d.base, total, total)
        run = await self._run(opcode=OP_ZERO, dst=d.base, total=total, chunk=total)
        got = await self._read_region(d.region)
        exp = self._expect_words(d.region, fill, fill.beats())
        st = run.status
        self._pass(
            "CHK-DMA-ZERO-WIN-EXACT",
            st.done and not st.error and got == exp,
            f"limit=0x{limit:08x} total={total} last_beat={fill.beats()[-1].nbytes} {st.fmt()} "
            f"{self._diff(got, exp, d.region.addr)}",
        )
        await self._idle()

        # Control: a copy whose destination is outside the range completes.
        await ops.program_range(d.base, d.limit, valid=True)
        await self.mem.fill(d.ctrl_src.addr, d.ctrl_src.words)
        await self.mem.fill(d.ctrl_dst.addr, [0] * len(d.ctrl_dst.words))
        run = await self._run(
            opcode=OP_COPY, src=d.ctrl_src.addr, dst=d.ctrl_dst.addr, total=16, chunk=16
        )
        got = await self._read_region(d.ctrl_dst)
        st = run.status
        self._pass(
            "CHK-DMA-ZERO-COPY-CTRL",
            st.done and not st.error and got == d.ctrl_src.words,
            f"dst=0x{d.ctrl_dst.addr:08x} base=0x{d.base:08x} limit=0x{d.limit:08x} {st.fmt()} "
            f"{self._diff(got, d.ctrl_src.words, d.ctrl_dst.addr)}",
        )
        await self._idle()
        await ops.wr(INTR_ENABLE, 0)
        await ops.program_range(SRAM_BASE, SRAM_LIMIT, valid=True)

    # ---- Leg E: invalid opcode and handshake mode --------------------------
    def _opcode_error(self, chk: str, run: FillRun, ok: bool, extra: str) -> None:
        """OPCODE_ERROR alone, no beat, and the caller's own condition ``ok``."""
        st = run.status
        ec = run.error_code & ERROR_CODE_MASK
        self._pass(
            chk,
            ok and st.error and ec == OPC_ERR and not run.ev.ar and not run.ev.aw,
            f"{extra} {st.fmt()} error_code=0x{ec:x} ar={len(run.ev.ar)} aw={len(run.ev.aw)}",
        )

    async def _leg_e(self, plan: Plan) -> None:
        ops = self.ops
        r = plan.e_region
        total = plan.e_total
        fill = DmaZeroFill(r.addr, total, total)

        # OPCODE 5, then a fill after the W1C of ERROR.
        await self.mem.fill(r.addr, r.words)
        run = await self._run(opcode=OP_INVALID, dst=r.addr, total=total, chunk=total)
        got = await self._read_region(r)
        self._opcode_error(
            "CHK-DMA-ZERO-OPC",
            run,
            got == r.words,
            f"opcode=0x{OP_INVALID:x} {self._diff(got, r.words, r.addr)}",
        )
        await self._idle()
        run = await self._run(opcode=OP_ZERO, dst=r.addr, total=total, chunk=total)
        got = await self._read_region(r)
        exp = self._expect_words(r, fill, fill.beats())
        self._pass(
            "CHK-DMA-ZERO-OPC",
            run.status.done and not run.status.error and got == exp,
            f"recovery {run.status.fmt()} {self._diff(got, exp, r.addr)}",
        )
        await self._idle()

        # Handshake mode with the SPI trigger held high.
        await self.mem.fill(r.addr, r.words)
        spi_ctrl = await ops.rd(SPI_CONTROL)
        await ops.wr(SPI_CONTROL, (spi_ctrl & ~SPI_TX_WM) | (1 << SPI_TX_WM_LSB))
        await ops.wr(HANDSHAKE_INTR_ENABLE, HS_TRIGGER0)
        try:
            await self.trigger.wait_level(1, TRIGGER_BOUND)
        except AssertionError:
            self._ctrl_missing("CHK-DMA-ZERO-HS", "the SPI trigger did not rise")
        trig_at_go = self.trigger.level()
        run = await self._run(opcode=OP_ZERO, dst=r.addr, total=total, chunk=total, hs=1)
        got = await self._read_region(r)
        if trig_at_go != 1:
            self._ctrl_missing("CHK-DMA-ZERO-HS", f"trigger_at_go={trig_at_go}")
        self._opcode_error(
            "CHK-DMA-ZERO-HS",
            run,
            got == r.words,
            f"trigger_at_go={trig_at_go} {self._diff(got, r.words, r.addr)}",
        )
        await self._idle()
        await ops.wr(HANDSHAKE_INTR_ENABLE, HS_RESET)
        await ops.wr(SPI_CONTROL, spi_ctrl)

    # ---- Leg A: abort --------------------------------------------------------
    async def _leg_a(self, plan: Plan) -> None:
        ops = self.ops
        r = plan.a_region
        total = r.nbytes
        sentinel = r.words

        # Reference fill: its clean time sets the abort delay only.
        await self.mem.fill(r.addr, sentinel)
        mark = self.tap.mark()
        run = await self._run(opcode=OP_ZERO, dst=r.addr, total=total, chunk=total)
        t_clean = self.tap.clk - mark.clk
        if not run.status.done:
            self._ctrl_missing("CHK-DMA-ZERO-ABORT", f"reference fill {run.status.fmt()}")
        await self._idle()

        for attempt, frac in enumerate(plan.a_fracs):
            await self.mem.fill(r.addr, sentinel)
            await ops.program_transfer(src=0, dst=r.addr, total=total, chunk=total)
            m_busy = self.busy.mark()
            await ops.go(opcode=OP_ZERO)
            await self.busy.wait_rise(m_busy, BUSY_RISE_BOUND)
            await ClockCycles(cocotb.top.clk_i, t_clean * frac // 100)
            busy_at_abort = self.busy.level()
            await ops.abort()
            st = await self._wait_status(ST_ABORTED | ST_DONE, "ABORTED or DONE")
            if busy_at_abort and st.aborted:
                break
            self.logger.info(
                "OBS-DMA-ZERO-ABORT-REDRAW attempt=%d frac=%d busy_at_abort=%s %s",
                attempt,
                frac,
                busy_at_abort,
                st.fmt(),
            )
            await self._idle()
        else:
            self._ctrl_missing("CHK-DMA-ZERO-ABORT", "no abort landed while the fill was busy")

        m_after = self.tap.mark()
        img1 = await self._read_region(r)
        await ClockCycles(cocotb.top.clk_i, max(1, t_clean // 4))
        img2 = await self._read_region(r)
        after = self.tap.since(m_after)
        z = next((i for i, w in enumerate(img1) if w != 0), len(img1))
        prefix_ok = all(w == 0 for w in img1[:z]) and img1[z:] == sentinel[z:]
        self.logger.info(
            "OBS-DMA-ZERO-ABORT ar_after=%d aw_after=%d zero_words=%d",
            len(after.ar),
            len(after.aw),
            z,
        )
        await ops.wr(STATUS, ST_ABORTED)
        st_clr = await ops.read_status()
        await self._idle()
        rec = await self._run(opcode=OP_ZERO, dst=r.addr, total=total, chunk=total)
        img3 = await self._read_region(r)
        ok = (
            st.aborted
            and prefix_ok
            and 0 < z < len(img1)
            and img1 == img2
            and not st_clr.aborted
            and rec.status.done
            and not rec.status.error
            and all(w == 0 for w in img3)
        )
        self._pass(
            "CHK-DMA-ZERO-ABORT",
            ok,
            f"frac={frac} t_clean={t_clean} {st.fmt()} zero_words={z}/{len(img1)} "
            f"prefix_ok={int(prefix_ok)} quiet={int(img1 == img2)} "
            f"aborted_after_w1c={st_clr.aborted} recovery={rec.status.fmt()} "
            f"recovery_zero={int(all(w == 0 for w in img3))}",
        )
        await self._idle()

    # ---- Leg L: the locked range -------------------------------------------
    async def _leg_l(self, plan: Plan) -> None:
        ops = self.ops
        r = plan.l_region
        await ops.program_range(plan.l_base, plan.l_limit, valid=True)
        await ops.wr(RANGE_REGWEN, REGWEN_FALSE << REGWEN_LSB)
        regwen = (await ops.rd(RANGE_REGWEN) & REGWEN_MASK) >> REGWEN_LSB
        await ops.wr(RANGE_LIMIT, plan.l_limit + 64)
        limit_rb = await ops.rd(RANGE_LIMIT)
        if regwen == REGWEN_TRUE or limit_rb != plan.l_limit:
            self._pass(
                "CHK-DMA-ZERO-WIN-LOCK",
                False,
                f"regwen=0x{regwen:x} limit_readback=0x{limit_rb:08x} "
                f"expect_limit=0x{plan.l_limit:08x}",
            )
        start = plan.l_limit + 1 - 4 * plan.l_words
        total = 4 * plan.l_words + plan.l_extra
        fill = DmaZeroFill(start, total, total)
        await self.mem.fill(r.addr, r.words)
        run = await self._run(opcode=OP_ZERO, dst=start, total=total, chunk=total)
        beats = fill.beats_in_range(plan.l_base, plan.l_limit)
        got = await self._read_region(r)
        exp = self._expect_words(r, fill, beats)
        st = run.status
        ec = run.error_code & ERROR_CODE_MASK
        cmp = field_compare(limit_rb, plan.l_limit, _D.mask32("ENABLED_MEMORY_RANGE_LIMIT"))
        self._pass(
            "CHK-DMA-ZERO-WIN-LOCK",
            cmp.ok
            and st.error
            and ec == DST_ERR
            and got == exp
            and len(run.ev.aw) == len(beats) == plan.l_words,
            f"regwen=0x{regwen:x} limit_readback=0x{limit_rb:08x} {st.fmt()} "
            f"error_code=0x{ec:x} aw={len(run.ev.aw)} in_range_beats={len(beats)} "
            f"{self._diff(got, exp, r.addr)}",
        )
        await self._idle()
