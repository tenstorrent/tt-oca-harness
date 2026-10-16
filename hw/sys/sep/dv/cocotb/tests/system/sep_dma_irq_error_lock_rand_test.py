# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Secure DMA interrupt enable gate, size errors, the range lock and a non-zero ADDR_HI.

Run mode: no_cpu (``lsu_stub_all_live``), real fuse sense with a PROD image
and zero disable vectors, because the leaf pulses ``rst_ni``. Every trial
starts from a cold reset. All four legs run on every simulator.

Leg L1, enable gate (``secure_dma.adoc``, INTR_STATE, INTR_ENABLE;
``interrupts.adoc``, SEP CPU Interrupt Vector Map). Six trials: a single-chunk
copy, a multi-chunk copy and a TOTAL_DATA_SIZE of zero, each with a drawn
INTR_ENABLE value that clears the bit of the event and one that sets it (the
twin). ``sep_internal_interrupts_probe_o`` indices 8, 9 and 10 (PIC sources 9,
10 and 11) are sampled on every clock from the GO write to a bounded wait after
DONE (or ERROR). Model: the line of source n is the matching event AND the
matching INTR_ENABLE bit; a single-chunk copy raises no chunk event, so its
source 10 is 0 with either value of INTR_ENABLE.DMA_CHUNK_DONE. For the
zero-size event sources 9 and 10 are logged when enabled and graded 0 when
disabled. Single-chunk contract: STATUS.CHUNK_DONE is "Only raised for
multi-chunk memory-to-memory transfers" (``secure_dma.rdl:327-328``); "Chunk
completion applies to multi-chunk transfers without hardware handshake; it is
not a per-trigger interrupt in handshake mode" (``dma.adoc:129-131``); "Since interrupts are implemented as status bits, they are cleared
by writing a '1' to the corresponding bit in the STATUS register" (OpenTitan
DMA ``vendor/lowRISC/opentitan/upstream/hw/ip/dma/doc/programmers_guide.md:39``). So every STATUS read of the single-chunk copy
gives CHUNK_DONE = 0, INTR_STATE.DMA_CHUNK_DONE reads 0 at the end of the trial
and source 10 stays low.

Leg L2, SIZE_ERROR (``secure_dma.adoc``, ERROR_CODE, STATUS, INTR_STATE;
``dma.hjson``, ERROR_CODE). TOTAL_DATA_SIZE 0, CHUNK_DATA_SIZE 0, both 0, and
SHA-256 at TRANSFER_WIDTH encodings 0 and 1 each set STATUS.ERROR,
ERROR_CODE.SIZE_ERROR and INTR_STATE.DMA_ERROR and assert PIC source 11. After
a write of 1 to STATUS.ERROR, with no reset, ERROR and ERROR_CODE read 0 and a
legal copy completes with the destination equal to the source. Control:
SHA-256 at encoding 2 completes with ERROR clear. The same write of 1 to
STATUS.ERROR releases the interrupt: "Since interrupts are implemented as
status bits, they are cleared by writing a '1' to the corresponding bit in the
STATUS register" (OpenTitan DMA
``vendor/lowRISC/opentitan/upstream/hw/ip/dma/doc/programmers_guide.md:39``); "Status
completion and error bits are write-one-to-clear" (``dma.adoc:131-132``).
INTR_STATE is read once after that write: DMA_ERROR reads 0 and
source 11 is low. Its control is INTR_STATE.DMA_ERROR = 1 before the write.

Leg L3, range lock (``sep-programming.adoc``, zero fill procedure: write MuBi4
False 0x9 to RANGE_REGWEN to fix the enabled memory range until reset;
``dma.adoc``, Zero Fill; ``dma.hjson``, RANGE_VALID). A lock from idle and a
lock after a size error, each from a cold reset: write BASE, LIMIT and
RANGE_VALID=1, read them back with RANGE_REGWEN (control: the writes landed and
RANGE_REGWEN reads True 0x6), write 0x9 to RANGE_REGWEN, then the unlock
attempts 0x6, 0xF, 0x9 and 0x0 in a drawn order. After the lock write and after
each attempt the leaf writes new BASE and LIMIT values and RANGE_VALID=0 and
reads all four registers back. An outside-range copy runs first and is logged
only (``OBS-DMA-RANGE-OUT``): the range does not bound a copy between internal
addresses (``dma.adoc``, Zero Fill).

Leg L4, non-zero ADDR_HI (``dma.adoc``, SEP secure DMA integration: the DMA
master interface has 32-bit addresses and ASID 0x7 is its only route). A copy
from the SRAM source to the SRAM destination with the SEP ASID, legal LO
addresses and a drawn non-zero SRC_ADDR_HI, then the same copy with a drawn
non-zero DST_ADDR_HI, must end with DONE or ERROR in a bounded number of
STATUS reads. The destination footprint at DST_ADDR_LO (the destination words
and its guards, read when the copy ends and again after the recovery writes),
STATUS.ERROR and ERROR_CODE are logged (``OBS-DMA-HI-ADDR``) and not graded,
because no document defines the ADDR_HI rule for the SEP DMA route. Control: the same copy
with both ADDR_HI at 0 completes and the destination equals the source. After
each non-zero trial, with no reset, a write of 1 to STATUS.ERROR and a clean
state precede a legal copy that must complete with the destination equal to the
source.

Randomization (``SepSeededRng`` from the run seed): the INTR_ENABLE values and
the trial order of L1, the copy sizes and the multi-chunk shape, the L2 sizes,
the buffer placement and the guards, the sentinel byte and the source words,
and for L3 the outside case, the region sizes and order, the outside distance,
the range values and the unlock-attempt orders, and for L4 the copy size and
the two ADDR_HI values. Every value is drawn before the first stimulus, on
every simulator.

Checkers:
  CHK-DMA-IRQ       per L1 trial: the three lines against the gate model, with
                    the twin of the same event in the same seed.
  CHK-DMA-IRQ-SINGLE per single-chunk L1 trial: no STATUS read shows
                    CHUNK_DONE, INTR_STATE.DMA_CHUNK_DONE reads 0 and source 10
                    stays low. Control: the multi-chunk trial with
                    DMA_CHUNK_DONE enabled shows source 10 high.
  CHK-DMA-SIZE-ERR  per L2 kind: the error response, its clear and the
                    recovery copy; the encoding-2 hash control completes.
  CHK-DMA-INTR-RELEASE per L2 kind: after the write of 1 to STATUS.ERROR,
                    INTR_STATE.DMA_ERROR reads 0 and source 11 is low. Control:
                    INTR_STATE.DMA_ERROR read 1 before the write.
  CHK-DMA-LOCK      per L3 lock write and unlock attempt, in both contexts:
                    RANGE_REGWEN reads 0x9, BASE and LIMIT read the values
                    written before the lock and RANGE_VALID reads 1. Source
                    of 0x9: "Once this register is set to
                    kMultiBitBool4False, it can only be set to
                    kMultiBitBool4True through a reset event."
                    (``vendor/lowRISC/opentitan/upstream/hw/ip/dma/data/dma.hjson:338-339``),
                    with the MultiBitBool4 encoding "True = 6; False = 9;"
                    (``vendor/lowRISC/opentitan/overlay/regs/secure_dma/regs/secure_dma.rdl:158-159``).
                    Every
                    new value differs from the locked one, so a write that
                    lands changes the read-back.
  CHK-DMA-HI-ADDR   per L4 side (SRC_ADDR_HI, DST_ADDR_HI): the copy ends and
                    the recovery copy completes; the ADDR_HI=0 control
                    completes with the source data. The footprint at
                    DST_ADDR_LO is OBS-DMA-HI-ADDR only.
"""

from __future__ import annotations

import cocotb
import pyuvm
from cocotb.triggers import ClockCycles
from env.sep_axi_agent import SepAxiOp
from env.sep_bit_watch import SepBitWatch
from env.sep_dma_model import draw_source_words
from env.sep_fcov_gate import close_graded_window, open_graded_window
from env.sep_field_compare import field_compare
from env.sep_lcc_golden import LC_PROD
from env.sep_seeded_rng import SepSeededRng
from sep_base_test import sep_base_test
from sep_reg_meta import sym
from seq_lib.sep_dma_ops import (
    _D,
    CHUNK_DATA_SIZE,
    CONTROL,
    ERROR_CODE,
    ERROR_CODE_MASK,
    INTR_CHUNK_DONE,
    INTR_ENABLE,
    INTR_ERROR,
    INTR_STATE,
    OP_COPY,
    OP_SHA256,
    RANGE_BASE,
    RANGE_LIMIT,
    RANGE_REGWEN,
    RANGE_VALID,
    ST_ERROR,
    STATUS,
    TOTAL_DATA_SIZE,
    TRANSFER_WIDTH,
    DmaTimeout,
    SepDmaOps,
    SepMemWords,
    asid_word,
    control_word,
    transfer_width_word,
)

TEST = "sep_dma_irq_error_lock_rand_test"

# SEP SRAM (generated memory map): the DMA enabled range and the home of every buffer.
SRAM_BASE = sym("SEP_SRAM_MEM_BASE_ADDR")
SRAM_SIZE = sym("SEP_SRAM_MEM_SIZE")
SRAM_LIMIT = SRAM_BASE + SRAM_SIZE - 1
ASID_SEP = asid_word(7, 7)

EVENTS = ("done", "chunk", "error")
EVENT_BIT = {
    "done": _D.field_lsb("INTR_ENABLE", "dma_done"),
    "chunk": _D.field_lsb("INTR_ENABLE", "dma_chunk_done"),
    "error": _D.field_lsb("INTR_ENABLE", "dma_error"),
}
INTR_EN_ALL = _D.mask32("INTR_ENABLE")
L2_KINDS = ("total", "chunk", "both", "hash_w0", "hash_w1")
OUTSIDE_CASES = (("src", "below"), ("src", "above"), ("dst", "below"), ("dst", "above"))

MAX_BYTES = 1024  # largest L1/L2 transfer
POST_WAIT = 200  # clocks of line sampling after DONE or ERROR
ERR_POLL_BOUND = 200  # STATUS reads in a wait for ERROR
BUSY_RISE_BOUND = 2_000
POLL_PER_KIB = 1_500

SIZE_ERR_MASK = _D.field_mask("ERROR_CODE", "size_error")
SRC_ERR_MASK = _D.field_mask("ERROR_CODE", "src_addr_error")
DST_ERR_MASK = _D.field_mask("ERROR_CODE", "dst_addr_error")
REGWEN_MASK = _D.field_mask("RANGE_REGWEN", "regwen")
_REGWEN_LSB = _D.field_lsb("RANGE_REGWEN", "regwen")
_REGWEN_ALL = REGWEN_MASK >> _REGWEN_LSB
# RANGE_REGWEN is MuBi4 with reset True; False is its bitwise complement.
REGWEN_TRUE = (_D.reset32("RANGE_REGWEN") & REGWEN_MASK) >> _REGWEN_LSB
REGWEN_FALSE = ~REGWEN_TRUE & _REGWEN_ALL
UNLOCK_VALUES = (REGWEN_TRUE, _REGWEN_ALL, REGWEN_FALSE, 0)
ADDR_HI_ALL = _D.mask32("SRC_ADDR_HI")
HI_SIDES = ("src", "dst")
VALID_MASK = _D.field_mask("RANGE_VALID", "range_valid")
_VALID_LSB = _D.field_lsb("RANGE_VALID", "range_valid")


def _word(b: int) -> int:
    return b * 0x0101_0101


def _bits(v: int | None) -> str:
    return "-" if v is None else str(v)


def irq_model(event: str, en: int) -> tuple[int | None, int | None, int | None]:
    """Expected (src9, src10, src11); None is a logged, ungraded line."""
    d, c, e = ((en >> EVENT_BIT[k]) & 1 for k in EVENTS)
    if event == "done":
        return d, 0, 0
    if event == "chunk":
        return d, c, 0
    return (None if d else 0), (None if c else 0), e


class _Cfg:
    """Seed-drawn plan of the leaf; drawn in full on every simulator."""

    def __init__(self, seed: int) -> None:
        rng = SepSeededRng(seed)
        self.seed = seed
        # L1 enable values and trial order.
        self.trials: list[tuple[str, int]] = []
        for ev in EVENTS:
            b = 1 << EVENT_BIT[ev]
            self.trials.append((ev, rng.choice([v for v in range(INTR_EN_ALL + 1) if not v & b])))
            self.trials.append((ev, rng.choice([v for v in range(INTR_EN_ALL + 1) if v & b])))
        rng.shuffle(self.trials)
        self.single = 4 * rng.randrange(4, MAX_BYTES // 4 + 1)
        self.mc_chunk = 4 * rng.randrange(4, 65)
        self.mc_n = rng.randrange(2, MAX_BYTES // self.mc_chunk + 1)
        self.zero_chunk = 4 * rng.randrange(1, 65)
        # L2 sizes: legal size of each kind, and the size of its recovery copy.
        self.l2_size = {k: 4 * rng.randrange(4, MAX_BYTES // 4 + 1) for k in L2_KINDS}
        self.l2_rec = {k: 4 * rng.randrange(4, MAX_BYTES // 4 + 1) for k in L2_KINDS}
        # Buffers for L1 and L2: two slots of MAX_BYTES with guards, drawn order and gap.
        self.guard = 4 * rng.randrange(1, 17)
        self.src, self.dst = self._place(rng, MAX_BYTES)
        self.sentinel = rng.randrange(256)
        self.words = draw_source_words(rng, MAX_BYTES // 4, self.sentinel)
        # L3.
        self.out_side, self.out_dir = rng.choice(OUTSIDE_CASES)
        self.l3_size = 4 * rng.randrange(4, 257)
        self.l3_src_first = bool(rng.getrandbits(1))
        self.out_dist = 4 * rng.randrange(1, 1025)
        self.out_off = 4 * rng.randrange(0, 0x4000)
        self.lock_vals = [self._range_pair(rng)]
        while len(self.lock_vals) < 12:
            nb, nl = self._range_pair(rng)
            if nb != self.lock_vals[0][0] and nl != self.lock_vals[0][1]:
                self.lock_vals.append((nb, nl))
        self.orders = {}
        for ctx in ("idle", "after_error"):
            o = list(UNLOCK_VALUES)
            rng.shuffle(o)
            self.orders[ctx] = o
        # L4.
        self.hi_size = 4 * rng.randrange(4, MAX_BYTES // 4 + 1)
        self.addr_hi = {s: rng.randrange(1, ADDR_HI_ALL + 1) for s in HI_SIDES}

    def _place(self, rng, size: int) -> tuple[int, int]:
        span = size + 2 * self.guard
        gap = 4 * rng.randrange(0, 1025)
        start = 4 * rng.randrange(0, (SRAM_SIZE - 2 * span - gap) // 4 + 1)
        lo = SRAM_BASE + start + self.guard
        hi = lo + span + gap
        return (lo, hi) if rng.getrandbits(1) else (hi, lo)

    @staticmethod
    def _range_pair(rng) -> tuple[int, int]:
        """A non-reset (BASE, LIMIT) pair inside the SEP SRAM, BASE below LIMIT."""
        base = SRAM_BASE + 4 * rng.randrange(1, SRAM_SIZE // 8)
        limit = base + 4 * rng.randrange(1, SRAM_SIZE // 8) - 1
        return base, limit

    def draw_line(self) -> str:
        return (
            f"seed={self.seed} trials="
            + ",".join(f"{e}:0x{v:x}" for e, v in self.trials)
            + f" single={self.single} mc_chunk={self.mc_chunk} mc_n={self.mc_n} "
            f"zero_chunk={self.zero_chunk} src=0x{self.src:08x} dst=0x{self.dst:08x} "
            f"guard={self.guard} sentinel=0x{self.sentinel:02x} "
            + " ".join(f"l2_{k}={self.l2_size[k]}/{self.l2_rec[k]}" for k in L2_KINDS)
            + f" l3_case={self.out_side}_{self.out_dir} l3_size={self.l3_size} "
            f"l3_src_first={int(self.l3_src_first)} out_dist={self.out_dist} "
            f"orders="
            + ";".join(f"{c}:" + ",".join(f"0x{v:x}" for v in o) for c, o in self.orders.items())
            + f" l4_size={self.hi_size} "
            + " ".join(f"l4_{s}_hi=0x{self.addr_hi[s]:08x}" for s in HI_SIDES)
        )


@pyuvm.test()
class sep_dma_irq_error_lock_rand_test(sep_base_test):
    """DMA interrupt enable gate, size errors with recovery, range lock."""

    required_evidence = (
        "CHK-DMA-IRQ",
        "CHK-DMA-IRQ-SINGLE",
        "CHK-DMA-SIZE-ERR",
        "CHK-DMA-INTR-RELEASE",
        "CHK-DMA-LOCK",
        "CHK-DMA-HI-ADDR",
    )

    # ---- helpers -----------------------------------------------------------
    def _pass(self, chk: str, line: str) -> None:
        self.logger.info("%s PASS seed=%d %s", chk, self.cfg_t.seed, line)
        self.n_checks += 1

    def _fail(self, chk: str, line: str) -> None:
        msg = f"{chk} FAIL seed={self.cfg_t.seed} {line}"
        self.logger.error(msg)
        raise AssertionError(msg)

    def _ctrl_missing(self, line: str) -> None:
        msg = f"CTRL-MISSING seed={self.cfg_t.seed} {line}"
        self.logger.error(msg)
        raise AssertionError(msg)

    async def _cold_reset(self) -> None:
        close_graded_window(self.logger)
        await self.pulse_rst_ni()

    async def _base_config(self, n_src_words: int) -> None:
        """Range over the SEP SRAM, ASID, source words and a sentinel destination."""
        c = self.cfg_t
        await self.ops.program_range(SRAM_BASE, SRAM_LIMIT, valid=True)
        await self.ops.wr(_D.addr("ADDR_SPACE_ID"), ASID_SEP)
        await self.mem.fill(c.src, c.words[:n_src_words])
        await self._sentinel_dst()

    async def _sentinel_dst(self) -> None:
        c = self.cfg_t
        await self.mem.fill(c.dst - c.guard, [_word(c.sentinel)] * ((MAX_BYTES + 2 * c.guard) // 4))

    async def _wait_error(self, bound: int):
        """Read STATUS until ERROR=1; returns the last status and whether ERROR was seen."""
        st = None
        for _ in range(bound):
            st = await self.ops.read_status()
            if st.error:
                return st, True
        return st, False

    # ---- L1 ------------------------------------------------------------------
    async def _l1_trial(self, event: str, en: int) -> tuple[tuple[int, int, int], int, int]:
        """One L1 trial; returns (lines, INTR_STATE, STATUS reads with CHUNK_DONE)."""
        c = self.cfg_t
        ops = self.ops
        await self._cold_reset()
        if event == "done":
            total, chunk = c.single, c.single
        elif event == "chunk":
            total, chunk = c.mc_chunk * c.mc_n, c.mc_chunk
        else:
            total, chunk = 0, c.zero_chunk
        await self._base_config(max(total, 4) // 4)
        open_graded_window(TEST, self.logger)
        await ops.wr(INTR_ENABLE, en)
        await ops.program_transfer(src=c.src, dst=c.dst, total=total, chunk=chunk)
        m = self.irq.mark()
        await ops.go(opcode=OP_COPY, initial=1)
        if event == "error":
            st, seen = await self._wait_error(ERR_POLL_BOUND)
            if not seen:
                msg = (
                    f"FAIL-DMA-TIMEOUT: zero-size trial intr_en=0x{en:x} no ERROR in "
                    f"{ERR_POLL_BOUND} STATUS reads (last {st.fmt()})"
                )
                self.logger.error(msg)
                raise DmaTimeout(msg)
            go_writes = 1
            chunk_reads = int(st.chunk_done)
        else:
            res = await ops.run_to_done(
                total,
                busy=self.busy,
                w1c_chunk_done=True,
                busy_bound=BUSY_RISE_BOUND,
                tag=f" L1 {event}",
            )
            st, go_writes = res.status, res.go_writes
            chunk_reads = sum(s.chunk_done for s in res.statuses)
            if not st.done:
                self._fail(
                    "CHK-DMA-IRQ",
                    f"intr_en=0x{en:x} event={event} copy ended without DONE: {st.fmt()}",
                )
        await ClockCycles(cocotb.top.clk_i, POST_WAIT)
        lines = tuple(int(self.irq.any_high_since(m, b)) for b in ("src9", "src10", "src11"))
        istate = await ops.rd(INTR_STATE)
        ecode = await ops.rd(ERROR_CODE)
        close_graded_window(self.logger)
        self.logger.info(
            "L1-TRIAL LOG seed=%d event=%s intr_en=0x%x total=%d chunk=%d go_writes=%d "
            "src9=%d src10=%d src11=%d intr_state=0x%x error_code=0x%x %s",
            c.seed,
            event,
            en,
            total,
            chunk,
            go_writes,
            *lines,
            istate,
            ecode,
            st.fmt(),
        )
        return lines, istate, chunk_reads

    async def _leg_l1(self) -> None:
        c = self.cfg_t
        got: dict[tuple[str, int], tuple[int, int, int]] = {}
        single: dict[int, tuple[int, int]] = {}
        for event, en in c.trials:
            got[(event, en)], istate, chunk_reads = await self._l1_trial(event, en)
            if event == "done":
                single[en] = (istate, chunk_reads)
        for event, en in c.trials:
            twin_en = next(v for e, v in c.trials if e == event and v != en)
            a, b, z = got[(event, en)]
            twin = got[(event, twin_en)]
            exp = irq_model(event, en)
            line = (
                f"intr_en=0x{en:x} event={event} src9={a} src10={b} src11={z} "
                f"expect={'/'.join(_bits(x) for x in exp)} twin={'/'.join(map(str, twin))}"
            )
            bad = [g for g, x in zip((a, b, z), exp) if x is not None and g != x]
            if bad:
                self._fail("CHK-DMA-IRQ", line)
            self._pass("CHK-DMA-IRQ", line)
        self._grade_single(got, single)

    def _grade_single(
        self,
        got: dict[tuple[str, int], tuple[int, int, int]],
        single: dict[int, tuple[int, int]],
    ) -> None:
        """Single-chunk copy: no CHUNK_DONE in STATUS or INTR_STATE, source 10 low."""
        c = self.cfg_t
        bit = 1 << EVENT_BIT["chunk"]
        mc_en = next(v for e, v in c.trials if e == "chunk" and v & bit)
        mc_src10 = got[("chunk", mc_en)][1]
        if mc_src10 != 1:
            self._ctrl_missing(
                f"CHK-DMA-IRQ-SINGLE control: multi-chunk trial intr_en=0x{mc_en:x} "
                f"src10={mc_src10}, expected 1"
            )
        for en, (istate, chunk_reads) in single.items():
            src10 = got[("done", en)][1]
            intr_chunk = int(bool(istate & INTR_CHUNK_DONE))
            line = (
                f"intr_en=0x{en:x} chunk_en={int(bool(en & bit))} status_chunk_done_reads="
                f"{chunk_reads} intr_chunk_done={intr_chunk} src10={src10} "
                f"intr_state=0x{istate:x} control_mc_src10={mc_src10}"
            )
            if (chunk_reads, intr_chunk, src10) != (0, 0, 0):
                self._fail("CHK-DMA-IRQ-SINGLE", line)
            self._pass("CHK-DMA-IRQ-SINGLE", line)

    # ---- L2 ------------------------------------------------------------------
    async def _l2_kind(self, kind: str) -> tuple[str, bool, tuple[int, int, int]]:
        c = self.cfg_t
        ops = self.ops
        size = c.l2_size[kind]
        rsize = c.l2_rec[kind]
        await self._cold_reset()
        await self._base_config(MAX_BYTES // 4)
        await ops.wr(INTR_ENABLE, INTR_EN_ALL)
        await ops.program_transfer(src=c.src, dst=c.dst, total=size, chunk=size)
        open_graded_window(TEST, self.logger)
        m = self.irq.mark()
        if kind in ("total", "both"):
            await ops.wr(TOTAL_DATA_SIZE, 0)
        if kind in ("chunk", "both"):
            await ops.wr(CHUNK_DATA_SIZE, 0)
        if kind.startswith("hash"):
            await ops.wr(TRANSFER_WIDTH, transfer_width_word(int(kind[-1])))
            await ops.go(opcode=OP_SHA256, initial=1)
        else:
            await ops.go(opcode=OP_COPY, initial=1)
        st, seen = await self._wait_error(ERR_POLL_BOUND)
        if not seen:
            self._fail(
                "CHK-DMA-SIZE-ERR",
                f"kind={kind} no ERROR within {ERR_POLL_BOUND} STATUS reads (last {st.fmt()})",
            )
        ecode = await ops.rd(ERROR_CODE)
        istate = await ops.rd(INTR_STATE)
        await ClockCycles(cocotb.top.clk_i, 8)
        src11 = int(self.irq.any_high_since(m, "src11"))
        # Recovery with no reset: write 1 to STATUS.ERROR alone.
        await ops.wr(STATUS, ST_ERROR)
        st_c = await ops.read_status()
        ecode_c = await ops.rd(ERROR_CODE)
        istate_c = await ops.rd(INTR_STATE)
        src11_c = self.irq.level("src11")
        await ops.clean_state()
        await ops.wr(CONTROL, control_word())
        await self._sentinel_dst()
        await ops.program_transfer(src=c.src, dst=c.dst, total=rsize, chunk=rsize)
        await ops.go(opcode=OP_COPY, initial=1)
        res = await ops.run_to_done(rsize, busy=self.busy, tag=f" L2 {kind} recovery")
        img = await self.mem.read(c.dst, rsize // 4)
        close_graded_window(self.logger)
        mism = sum(1 for g, w in zip(img, c.words) if g != w)

        fc_err = field_compare(st.raw, ST_ERROR, ST_ERROR)
        fc_code = field_compare(ecode, SIZE_ERR_MASK, SIZE_ERR_MASK)
        fc_int = field_compare(istate, INTR_ERROR, INTR_ERROR)
        fc_errc = field_compare(st_c.raw, 0, ST_ERROR)
        fc_codec = field_compare(ecode_c, 0, ERROR_CODE_MASK)
        rec_ok = res.status.done and not res.status.error and mism == 0
        return (
            f"kind={kind} error={st.error} size_error={int(bool(ecode & SIZE_ERR_MASK))} "
            f"intr_dma_error={int(bool(istate & INTR_ERROR))} src11={src11} "
            f"error_cleared={int(fc_errc.ok)} code_cleared={int(fc_codec.ok)} "
            f"recovery_done={int(rec_ok)} @@CTRL@@ size={size} recovery_size={rsize} "
            f"recovery_mismatch={mism} error_code=0x{ecode:x} code_mask=0x{SIZE_ERR_MASK:x} "
            f"intr_state=0x{istate:x} intr_mask=0x{INTR_ERROR:x} "
            f"code_after_clear[{fc_codec.fields()}]",
            all(f.ok for f in (fc_err, fc_code, fc_int, fc_errc, fc_codec))
            and src11 == 1
            and rec_ok,
            (istate, istate_c, src11_c),
        )

    async def _l2_control(self, kind: str) -> int:
        """SHA-256 at the size of `kind` and TRANSFER_WIDTH encoding 2 completes with ERROR clear."""
        c = self.cfg_t
        ops = self.ops
        size = c.l2_size[kind]
        await self._cold_reset()
        await self._base_config(MAX_BYTES // 4)
        await ops.wr(INTR_ENABLE, INTR_EN_ALL)
        await ops.program_transfer(src=c.src, dst=c.dst, total=size, chunk=size, width_enc=2)
        await ops.go(opcode=OP_SHA256, initial=1)
        res = await ops.run_to_done(size, busy=self.busy, tag=" L2 control")
        ecode = await ops.rd(ERROR_CODE)
        ok = int(res.status.done and not res.status.error and (ecode & ERROR_CODE_MASK) == 0)
        self.logger.info(
            "CTL-DMA-SIZE-ERR LOG seed=%d kind=%s hash_width_enc=2 size=%d control_width_ok=%d "
            "error_code=0x%x %s",
            c.seed,
            kind,
            size,
            ok,
            ecode,
            res.status.fmt(),
        )
        return ok

    async def _leg_l2(self) -> None:
        results = [await self._l2_kind(k) for k in L2_KINDS]
        # One control per hash kind, at that kind's size: the SIZE_ERROR of each
        # width case then comes from the width alone.
        hash_kinds = [k for k in L2_KINDS if k.startswith("hash")]
        ctl = {k: await self._l2_control(k) for k in hash_kinds}
        for k in hash_kinds:
            if not ctl[k]:
                self._ctrl_missing(
                    f"CHK-DMA-SIZE-ERR control: SHA-256 at width encoding 2 and size "
                    f"{self.cfg_t.l2_size[k]} (kind={k}) failed"
                )
        for (line, ok, _), k in zip(results, L2_KINDS):
            k_ctl = ctl[k] if k in ctl else int(all(ctl.values()))
            line = line.replace("@@CTRL@@", f"control_width_ok={k_ctl}")
            if not ok:
                self._fail("CHK-DMA-SIZE-ERR", line)
            self._pass("CHK-DMA-SIZE-ERR", line)
        for (_, _, (pre, post, src11_c)), k in zip(results, L2_KINDS):
            pre_bit = int(bool(pre & INTR_ERROR))
            post_bit = int(bool(post & INTR_ERROR))
            line = (
                f"kind={k} intr_dma_error_after_w1c={post_bit} src11_after_w1c={src11_c} "
                f"control_intr_dma_error_before_w1c={pre_bit} intr_state_before=0x{pre:x} "
                f"intr_state_after=0x{post:x}"
            )
            if pre_bit != 1:
                self._ctrl_missing(f"CHK-DMA-INTR-RELEASE control: {line}")
            if (post_bit, src11_c) != (0, 0):
                self._fail("CHK-DMA-INTR-RELEASE", line)
            self._pass("CHK-DMA-INTR-RELEASE", line)

    # ---- L4 ------------------------------------------------------------------
    async def _hi_copy(self, src_hi: int, dst_hi: int):
        """One L4 copy; returns (last STATUS, ended, ERROR_CODE, destination footprint).

        The footprint is the destination of the copy and its two guards, read
        back from the SRAM after the copy ends or the STATUS bound expires.
        """
        c = self.cfg_t
        ops = self.ops
        size = c.hi_size
        await ops.program_transfer(
            src=c.src, dst=c.dst, total=size, chunk=size, src_hi=src_hi, dst_hi=dst_hi
        )
        await ops.go(opcode=OP_COPY, initial=1)
        st, ended = None, False
        for _ in range(ops.done_bound(size)):
            st = await ops.read_status()
            if st.done or st.error:
                ended = True
                break
        ecode = await ops.rd(ERROR_CODE)
        foot = await self.mem.read(c.dst - c.guard, (size + 2 * c.guard) // 4)
        return st, ended, ecode, foot

    def _hi_image_ok(self, foot: list[int]) -> tuple[int, int]:
        """(source mismatches, sentinel mismatches) of a footprint after a legal copy."""
        c = self.cfg_t
        g = c.guard // 4
        n = c.hi_size // 4
        sent = _word(c.sentinel)
        mism = sum(1 for got, w in zip(foot[g : g + n], c.words) if got != w)
        guard_bad = sum(1 for w in foot[:g] + foot[g + n :] if w != sent)
        return mism, guard_bad

    async def _l4_control(self) -> int:
        """The L4 copy with both ADDR_HI at 0 completes with the source data."""
        c = self.cfg_t
        await self._cold_reset()
        await self._base_config(c.hi_size // 4)
        st, ended, ecode, foot = await self._hi_copy(0, 0)
        mism, guard_bad = self._hi_image_ok(foot)
        ok = int(ended and st.done and not st.error and mism == 0 and guard_bad == 0)
        self.logger.info(
            "CTL-DMA-HI-ADDR LOG seed=%d size=%d src=0x%08x dst=0x%08x control_ok=%d "
            "mismatch=%d guard_bad=%d error_code=0x%x %s",
            c.seed,
            c.hi_size,
            c.src,
            c.dst,
            ok,
            mism,
            guard_bad,
            ecode,
            st.fmt(),
        )
        return ok

    async def _l4_side(self, side: str) -> tuple[str, bool]:
        c = self.cfg_t
        ops = self.ops
        hi = c.addr_hi[side]
        await self._cold_reset()
        await self._base_config(c.hi_size // 4)
        # Graded: the non-zero ADDR_HI copy (sep_dma_config_fault_cg.cp_addr_hi_nonzero).
        open_graded_window(TEST, self.logger)
        st, ended, ecode, foot = await self._hi_copy(
            hi if side == "src" else 0, hi if side == "dst" else 0
        )
        close_graded_window(self.logger)
        sent = _word(c.sentinel)
        moved = sum(1 for w in foot if w != sent)
        self.logger.info(
            "OBS-DMA-HI-ADDR seed=%d side=%s addr_hi=0x%08x error=%d done=%d src_err=%d "
            "dst_err=%d error_code=0x%x %s",
            c.seed,
            side,
            hi,
            st.error,
            st.done,
            int(bool(ecode & SRC_ERR_MASK)),
            int(bool(ecode & DST_ERR_MASK)),
            ecode,
            st.fmt(),
        )
        # Recovery with no reset: write 1 to STATUS.ERROR, then a clean state.
        await ops.wr(STATUS, ST_ERROR)
        await ops.clean_state()
        await ops.wr(CONTROL, control_word())
        # Second footprint read, after the recovery writes and before the
        # sentinel refill: a write beat that lands after the first read is seen.
        late = await self.mem.read(c.dst - c.guard, len(foot))
        moved_late = sum(1 for w in late if w != sent)
        # No document states where a non-zero ADDR_HI copy writes, so the
        # footprint at DST_ADDR_LO is logged and not graded.
        self.logger.info(
            "OBS-DMA-HI-ADDR seed=%d side=%s addr_hi=0x%08x footprint_words=%d "
            "footprint_changed=%d footprint_changed_late=%d sentinel=0x%08x "
            "changed=%s changed_late=%s",
            c.seed,
            side,
            hi,
            len(foot),
            moved,
            moved_late,
            sent,
            ",".join(f"{i}:0x{w:08x}" for i, w in enumerate(foot) if w != sent) or "-",
            ",".join(f"{i}:0x{w:08x}" for i, w in enumerate(late) if w != sent) or "-",
        )
        await self._sentinel_dst()
        rst, rended, _, rec = await self._hi_copy(0, 0)
        mism, guard_bad = self._hi_image_ok(rec)
        rec_ok = rended and rst.done and not rst.error and mism == 0 and guard_bad == 0
        line = (
            f"side={side} addr_hi=0x{hi:08x} lo_dst=0x{c.dst:08x} size={c.hi_size} "
            f"ended={int(ended)} done={st.done} "
            f"recovery_done={int(rec_ok)} @@CTRL@@ "
            f"recovery_mismatch={mism} recovery_guard_bad={guard_bad}"
        )
        return line, ended and rec_ok

    async def _leg_l4(self) -> None:
        results = [await self._l4_side(s) for s in HI_SIDES]
        ctl = await self._l4_control()
        if not ctl:
            self._ctrl_missing("CHK-DMA-HI-ADDR control: the ADDR_HI=0 copy failed")
        for line, ok in results:
            line = line.replace("@@CTRL@@", f"control_ok={ctl}")
            if not ok:
                self._fail("CHK-DMA-HI-ADDR", line)
            self._pass("CHK-DMA-HI-ADDR", line)

    # ---- L3 ------------------------------------------------------------------
    async def _wr_log(self, addr: int, value: int) -> int:
        seq = await self.ops.access(SepAxiOp.WRITE, addr, value, ungraded=True)
        return int(seq.resp_code)

    async def _l3_outside(self) -> None:
        c = self.cfg_t
        ops = self.ops
        size, g, dist = c.l3_size, c.guard, c.out_dist
        await self._cold_reset()
        out_lo = c.out_dir == "below"
        a = SRAM_BASE + g + c.out_off
        if out_lo:
            out_start = a
            base = out_start + size + dist
            in_start = base + g
            limit = in_start + size + g - 1
        else:
            in_start = a
            base = in_start - g
            limit = in_start + size + g - 1
            out_start = limit + 1 + dist
        src, dst = (out_start, in_start) if c.out_side == "src" else (in_start, out_start)
        await ops.program_range(base, limit, valid=True)
        await ops.wr(_D.addr("ADDR_SPACE_ID"), ASID_SEP)
        await self.mem.fill(src, c.words[: size // 4])
        await ops.program_transfer(src=src, dst=dst, total=size, chunk=size)
        await ops.go(opcode=OP_COPY, initial=1)
        st = None
        timeout = 1
        for _ in range(ops.done_bound(size)):
            st = await ops.read_status()
            if st.done or st.error:
                timeout = 0
                break
        ecode = await ops.rd(ERROR_CODE)
        self.logger.info(
            "OBS-DMA-RANGE-OUT seed=%d side=%s dir=%s dist=%d error=%d src_err=%d dst_err=%d "
            "timeout=%d base=0x%08x limit=0x%08x src=0x%08x dst=0x%08x size=%d "
            "error_code=0x%x %s",
            c.seed,
            c.out_side,
            c.out_dir,
            dist,
            st.error,
            int(bool(ecode & SRC_ERR_MASK)),
            int(bool(ecode & DST_ERR_MASK)),
            timeout,
            base,
            limit,
            src,
            dst,
            size,
            ecode,
            st.fmt(),
        )

    async def _lock_attempts(self, ctx: str, pre: tuple[int, int]) -> None:
        c = self.cfg_t
        ops = self.ops
        vals = iter(c.lock_vals[1:] if ctx == "idle" else c.lock_vals[6:])

        async def attempt(name: str, regwen_val: int) -> None:
            resp_rw = await self._wr_log(RANGE_REGWEN, regwen_val << _REGWEN_LSB)
            nb, nl = next(vals)
            if nb == pre[0] or nl == pre[1]:
                self._ctrl_missing(
                    f"CHK-DMA-LOCK ctx={ctx} attempt={name}: new value equals the locked "
                    f"value (0x{nb:08x}/0x{nl:08x})"
                )
            resps = [
                await self._wr_log(RANGE_BASE, nb),
                await self._wr_log(RANGE_LIMIT, nl),
                await self._wr_log(RANGE_VALID, 0),
            ]
            regwen = (await ops.rd(RANGE_REGWEN) & REGWEN_MASK) >> _REGWEN_LSB
            base = await ops.rd(RANGE_BASE)
            limit = await ops.rd(RANGE_LIMIT)
            valid = (await ops.rd(RANGE_VALID) & VALID_MASK) >> _VALID_LSB
            line = (
                f"ctx={ctx} attempt={name} regwen=0x{regwen:x}/0x{REGWEN_FALSE:x} "
                f"base=0x{base:08x}/0x{pre[0]:08x} limit=0x{limit:08x}/0x{pre[1]:08x} "
                f"valid={valid}/1 new=0x{nb:08x}/0x{nl:08x}/0 "
                f"write_resp={resp_rw}/{'/'.join(map(str, resps))} control_pre_lock_landed=1"
            )
            # Locked RANGE_REGWEN is kMultiBitBool4False until a reset
            # (dma.hjson:338-339); False encodes as 9 (secure_dma.rdl:158-159).
            if regwen != REGWEN_FALSE or base != pre[0] or limit != pre[1] or valid != 1:
                self._fail("CHK-DMA-LOCK", line)
            self._pass("CHK-DMA-LOCK", line)

        await attempt("lock", REGWEN_FALSE)
        for v in c.orders[ctx]:
            await attempt(f"0x{v:x}", v)

    async def _l3_lock(self, ctx: str) -> None:
        c = self.cfg_t
        ops = self.ops
        await self._cold_reset()
        open_graded_window(TEST, self.logger)
        if ctx == "idle":
            pre = c.lock_vals[0]
        else:
            pre = (SRAM_BASE, SRAM_LIMIT)
            await ops.wr(_D.addr("ADDR_SPACE_ID"), ASID_SEP)
        await ops.wr(RANGE_BASE, pre[0])
        await ops.wr(RANGE_LIMIT, pre[1])
        await ops.wr(RANGE_VALID, 1 << _VALID_LSB)
        base = await ops.rd(RANGE_BASE)
        limit = await ops.rd(RANGE_LIMIT)
        valid = (await ops.rd(RANGE_VALID) & VALID_MASK) >> _VALID_LSB
        regwen = (await ops.rd(RANGE_REGWEN) & REGWEN_MASK) >> _REGWEN_LSB
        err_seen = 1
        if ctx == "after_error":
            src, dst = (c.src, c.dst) if c.l3_src_first else (c.dst, c.src)
            await ops.program_transfer(src=src, dst=dst, total=0, chunk=c.zero_chunk)
            await ops.go(opcode=OP_COPY, initial=1)
            _, seen = await self._wait_error(ERR_POLL_BOUND)
            err_seen = int(seen)
        ctl = (
            f"ctx={ctx} base=0x{base:08x}/0x{pre[0]:08x} limit=0x{limit:08x}/0x{pre[1]:08x} "
            f"regwen=0x{regwen:x}/0x{REGWEN_TRUE:x} valid={valid}/1 error_seen={err_seen}"
        )
        self.logger.info("CTL-DMA-LOCK seed=%d %s", c.seed, ctl)
        if (base, limit, regwen, valid, err_seen) != (pre[0], pre[1], REGWEN_TRUE, 1, 1):
            self._ctrl_missing(f"CHK-DMA-LOCK control before the lock: {ctl}")
        await self._lock_attempts(ctx, pre)
        close_graded_window(self.logger)

    async def _leg_l3(self) -> None:
        await self._l3_outside()
        await self._l3_lock("idle")
        await self._l3_lock("after_error")

    # ---- scenario ----------------------------------------------------------
    async def run_scenario(self) -> None:
        seed = self.random_seed()
        self.cfg_t = c = _Cfg(seed)
        self.n_checks = 0
        self.logger.info(
            "PLAN seed=%d L1 6 trials, L2 5 kinds + width-2 control, L3 outside copy + "
            "lock from idle and after an error with 4 unlock attempts each, L4 2 ADDR_HI "
            "sides + ADDR_HI=0 control; every trial from a cold reset",
            seed,
        )
        self.logger.info("DRAW %s", c.draw_line())

        image = self.select_efuse_image(lc_raw=LC_PROD, fixed={"SIP_DIS": 0, "SYS_DIS": 0})
        self.write_efuse_image(image)
        await self.bring_up_no_cpu()
        self.suppress_host_axi_transaction_info()
        self.ops = SepDmaOps(self)
        # One STATUS read takes fewer clocks than the DMA needs per KiB at width 4,
        # so the wait for DONE allows more reads per KiB than the helper default.
        self.ops.POLL_PER_KIB = POLL_PER_KIB
        self.mem = SepMemWords(self)
        self.irq = SepBitWatch(
            cocotb.top.sep_internal_interrupts_probe_o, {"src9": 8, "src10": 9, "src11": 10}
        ).start()
        self.busy = SepBitWatch(cocotb.top.dma_busy_probe_o, {"busy": 0}).start()
        await ClockCycles(cocotb.top.clk_i, 2)

        await self._leg_l1()
        await self._leg_l2()
        await self._leg_l3()
        await self._leg_l4()
        close_graded_window(self.logger)
        await self.irq.stop()
        await self.busy.stop()
        self.result_pass(TEST, seed, self.n_checks)
