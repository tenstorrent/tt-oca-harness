# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Secure DMA interrupt enable gate, size errors with recovery, and the range lock (logged).

Run mode: no_cpu (``lsu_stub_all_live``), real fuse sense with a PROD image
and zero disable vectors, because the leaf pulses ``rst_ni``. Every trial
starts from a cold reset, because the register description states no write
that releases INTR_STATE. Leg L3 reads state after reset, so it runs on a
four-state simulator only (VCS); on Verilator the leaf logs ``L3-SKIP`` and
runs L1 and L2.

Leg L1, enable gate (``secure_dma.adoc``, INTR_STATE, INTR_ENABLE;
``interrupts.adoc``, SEP CPU Interrupt Vector Map). Six trials: a single-chunk
copy, a multi-chunk copy and a TOTAL_DATA_SIZE of zero, each with a drawn
INTR_ENABLE value that clears the bit of the event and one that sets it (the
twin). ``sep_internal_interrupts_probe_o`` indices 8, 9 and 10 (PIC sources 9,
10 and 11) are sampled on every clock from the GO write to a bounded wait after
DONE (or ERROR). Model: the line of source n is the matching event AND the
matching INTR_ENABLE bit. The cited text does not say whether a single-chunk
copy raises DMA_CHUNK_DONE, so that line is logged (``OBS-DMA-IRQ-SINGLE``) and
graded only with the bit clear; for the zero-size event sources 9 and 10 are
logged when enabled and graded 0 when disabled.

Leg L2, SIZE_ERROR (``secure_dma.adoc``, ERROR_CODE, STATUS, INTR_STATE;
``dma.hjson``, ERROR_CODE). TOTAL_DATA_SIZE 0, CHUNK_DATA_SIZE 0, both 0, and
SHA-256 at TRANSFER_WIDTH encodings 0 and 1 each set STATUS.ERROR,
ERROR_CODE.SIZE_ERROR and INTR_STATE.DMA_ERROR and assert PIC source 11. After
a write of 1 to STATUS.ERROR, with no reset, ERROR and ERROR_CODE read 0 and a
legal copy completes with the destination equal to the source. Control:
SHA-256 at encoding 2 completes with ERROR clear.

Leg L3, range lock (VCS only, logged only). The register description does not
name the write that applies the lock (RANGE_REGWEN is RW0C with reset True), so
the lock check is blocked. The leg runs an outside-range trial
(``OBS-DMA-RANGE-OUT``), a lock from idle and a lock after a size error, with
unlock attempts 0x6, 0xF, 0x9 and 0x0 in a drawn order, and logs every
read-back as ``OBS-DMA-LOCK LOG``. It grades nothing.

Randomization (``SepSeededRng`` from the run seed): the INTR_ENABLE values and
the trial order of L1, the copy sizes and the multi-chunk shape, the L2 sizes,
the buffer placement and the guards, the sentinel byte and the source words,
and for L3 the outside case, the region sizes and order, the outside distance,
the range values and the unlock-attempt orders. Every value is drawn before the
first stimulus, on every simulator.

Checkers:
  CHK-DMA-IRQ       per L1 trial: the three lines against the gate model, with
                    the twin of the same event in the same seed.
  CHK-DMA-SIZE-ERR  per L2 kind: the error response, its clear and the
                    recovery copy; the encoding-2 hash control completes.
  CHK-DMA-LOCK      blocked: ``OBS-DMA-LOCK LOG`` lines only, not counted.
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
from seq_lib.sep_dma_ops import (
    _D,
    CHUNK_DATA_SIZE,
    CONTROL,
    ERROR_CODE,
    ERROR_CODE_MASK,
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
    TOTAL_DATA_SIZE,
    TRANSFER_WIDTH,
    DmaTimeout,
    SepDmaOps,
    SepMemWords,
    control_word,
)

TEST = "sep_dma_irq_error_lock_rand_test"

# SEP SRAM (memory_map.adoc): the DMA enabled range and the home of every buffer.
SRAM_BASE = 0x1000_0000
SRAM_LIMIT = 0x1003_FFFF
SRAM_SIZE = SRAM_LIMIT - SRAM_BASE + 1
ASID_SEP = 0x77

EVENTS = ("done", "chunk", "error")
EVENT_BIT = {
    "done": _D.field_lsb("INTR_ENABLE", "dma_done"),
    "chunk": _D.field_lsb("INTR_ENABLE", "dma_chunk_done"),
    "error": _D.field_lsb("INTR_ENABLE", "dma_error"),
}
INTR_EN_ALL = _D.mask32("INTR_ENABLE")
L2_KINDS = ("total", "chunk", "both", "hash_w0", "hash_w1")
UNLOCK_VALUES = (0x6, 0xF, 0x9, 0x0)
OUTSIDE_CASES = (("src", "below"), ("src", "above"), ("dst", "below"), ("dst", "above"))
REGWEN_TRUE = 0x6
REGWEN_FALSE = 0x9

MAX_BYTES = 1024  # largest L1/L2 transfer
POST_WAIT = 200  # clocks of line sampling after DONE or ERROR
ERR_POLL_BOUND = 200  # STATUS reads in a wait for ERROR
BUSY_RISE_BOUND = 2_000
POLL_PER_KIB = 1_500

SIZE_ERR_MASK = _D.field_mask("ERROR_CODE", "size_error")
SRC_ERR_MASK = _D.field_mask("ERROR_CODE", "src_addr_error")
DST_ERR_MASK = _D.field_mask("ERROR_CODE", "dst_addr_error")
REGWEN_MASK = _D.field_mask("RANGE_REGWEN", "regwen")
VALID_MASK = _D.field_mask("RANGE_VALID", "range_valid")


def _word(b: int) -> int:
    return b * 0x0101_0101


def _bits(v: int | None) -> str:
    return "-" if v is None else str(v)


def irq_model(event: str, en: int) -> tuple[int | None, int | None, int | None]:
    """Expected (src9, src10, src11); None is a logged, ungraded line."""
    d, c, e = ((en >> EVENT_BIT[k]) & 1 for k in EVENTS)
    if event == "done":
        return d, (None if c else 0), 0
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
        self.lock_vals = [self._range_pair(rng) for _ in range(12)]
        self.orders = {}
        for ctx in ("idle", "after_error"):
            o = list(UNLOCK_VALUES)
            rng.shuffle(o)
            self.orders[ctx] = o

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
        )


@pyuvm.test()
class sep_dma_irq_error_lock_rand_test(sep_base_test):
    """DMA interrupt enable gate, size errors with recovery, logged range lock."""

    required_evidence = ("CHK-DMA-IRQ", "CHK-DMA-SIZE-ERR")

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
    async def _l1_trial(self, event: str, en: int) -> tuple[int, int, int]:
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
        else:
            res = await ops.run_to_done(
                total,
                busy=self.busy,
                w1c_chunk_done=True,
                busy_bound=BUSY_RISE_BOUND,
                tag=f" L1 {event}",
            )
            st, go_writes = res.status, res.go_writes
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
        return lines

    async def _leg_l1(self) -> None:
        c = self.cfg_t
        got: dict[tuple[str, int], tuple[int, int, int]] = {}
        for event, en in c.trials:
            got[(event, en)] = await self._l1_trial(event, en)
        for event, en in c.trials:
            twin_en = next(v for e, v in c.trials if e == event and v != en)
            a, b, z = got[(event, en)]
            twin = got[(event, twin_en)]
            exp = irq_model(event, en)
            if event == "done":
                self.logger.info("OBS-DMA-IRQ-SINGLE seed=%d intr_en=0x%x src10=%d", c.seed, en, b)
            line = (
                f"intr_en=0x{en:x} event={event} src9={a} src10={b} src11={z} "
                f"expect={'/'.join(_bits(x) for x in exp)} twin={'/'.join(map(str, twin))}"
            )
            bad = [g for g, x in zip((a, b, z), exp) if x is not None and g != x]
            if bad:
                self._fail("CHK-DMA-IRQ", line)
            self._pass("CHK-DMA-IRQ", line)

    # ---- L2 ------------------------------------------------------------------
    async def _l2_kind(self, kind: str) -> tuple[str, bool]:
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
            await ops.wr(TRANSFER_WIDTH, int(kind[-1]))
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
        # Recovery with no reset.
        await ops.clean_state()
        st_c = await ops.read_status()
        ecode_c = await ops.rd(ERROR_CODE)
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
        )

    async def _l2_control(self) -> int:
        """SHA-256 at TRANSFER_WIDTH encoding 2 completes with ERROR clear (window closed)."""
        c = self.cfg_t
        ops = self.ops
        size = c.l2_size["hash_w0"]
        await self._cold_reset()
        await self._base_config(MAX_BYTES // 4)
        await ops.wr(INTR_ENABLE, INTR_EN_ALL)
        await ops.program_transfer(src=c.src, dst=c.dst, total=size, chunk=size, width_enc=2)
        await ops.go(opcode=OP_SHA256, initial=1)
        res = await ops.run_to_done(size, busy=self.busy, tag=" L2 control")
        ecode = await ops.rd(ERROR_CODE)
        ok = int(res.status.done and not res.status.error and (ecode & ERROR_CODE_MASK) == 0)
        self.logger.info(
            "CTL-DMA-SIZE-ERR LOG seed=%d hash_width_enc=2 size=%d control_width_ok=%d "
            "error_code=0x%x %s",
            c.seed,
            size,
            ok,
            ecode,
            res.status.fmt(),
        )
        return ok

    async def _leg_l2(self) -> None:
        results = [await self._l2_kind(k) for k in L2_KINDS]
        ctl = await self._l2_control()
        if not ctl:
            self._ctrl_missing("CHK-DMA-SIZE-ERR control: SHA-256 at width encoding 2 failed")
        for line, ok in results:
            line = line.replace("@@CTRL@@", f"control_width_ok={ctl}")
            if not ok:
                self._fail("CHK-DMA-SIZE-ERR", line)
            self._pass("CHK-DMA-SIZE-ERR", line)

    # ---- L3 (logged only) ----------------------------------------------------
    async def _wr_log(self, addr: int, value: int) -> int:
        seq = await self.ops.access(SepAxiOp.WRITE, addr, value, ungraded=True)
        return int(seq.resp_code)

    async def _rd_log(self, addr: int) -> tuple[int, int]:
        seq = await self.ops.access(SepAxiOp.READ, addr, ungraded=True)
        return int(seq.rdata) & 0xFFFF_FFFF, int(seq.resp_code)

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
        vals = iter(c.lock_vals[1:] if ctx == "idle" else c.lock_vals[6:])

        async def attempt(name: str, regwen_val: int) -> None:
            resp_rw = await self._wr_log(RANGE_REGWEN, regwen_val)
            nb, nl = next(vals)
            resps = [
                await self._wr_log(RANGE_BASE, nb),
                await self._wr_log(RANGE_LIMIT, nl),
                await self._wr_log(RANGE_VALID, 0),
            ]
            regwen, _ = await self._rd_log(RANGE_REGWEN)
            base, _ = await self._rd_log(RANGE_BASE)
            limit, _ = await self._rd_log(RANGE_LIMIT)
            valid, _ = await self._rd_log(RANGE_VALID)
            self.logger.info(
                "OBS-DMA-LOCK LOG seed=%d blocked=1 attempt=%s regwen=0x%x base=0x%08x "
                "limit=0x%08x valid=%d ctx=%s pre_lock=0x%08x/0x%08x new=0x%08x/0x%08x "
                "write_resp=%d/%s",
                c.seed,
                name,
                regwen & REGWEN_MASK,
                base,
                limit,
                valid & VALID_MASK,
                ctx,
                pre[0],
                pre[1],
                nb,
                nl,
                resp_rw,
                "/".join(map(str, resps)),
            )

        await attempt("lock", REGWEN_FALSE)
        for v in c.orders[ctx]:
            await attempt(f"0x{v:x}", v)

    async def _l3_lock(self, ctx: str) -> None:
        c = self.cfg_t
        ops = self.ops
        await self._cold_reset()
        if ctx == "idle":
            pre = c.lock_vals[0]
        else:
            pre = (SRAM_BASE, SRAM_LIMIT)
            await ops.wr(_D.addr("ADDR_SPACE_ID"), ASID_SEP)
        await self._wr_log(RANGE_BASE, pre[0])
        await self._wr_log(RANGE_LIMIT, pre[1])
        base, _ = await self._rd_log(RANGE_BASE)
        limit, _ = await self._rd_log(RANGE_LIMIT)
        regwen, _ = await self._rd_log(RANGE_REGWEN)
        await self._wr_log(RANGE_VALID, 1)
        valid, _ = await self._rd_log(RANGE_VALID)
        err_seen = "-"
        if ctx == "after_error":
            src, dst = (c.src, c.dst) if c.l3_src_first else (c.dst, c.src)
            await ops.program_transfer(src=src, dst=dst, total=0, chunk=c.zero_chunk)
            await ops.go(opcode=OP_COPY, initial=1)
            _, seen = await self._wait_error(ERR_POLL_BOUND)
            err_seen = str(int(seen))
        self.logger.info(
            "CTL-DMA-LOCK LOG seed=%d ctx=%s base=0x%08x/0x%08x limit=0x%08x/0x%08x "
            "regwen=0x%x expect_regwen=0x%x valid=%d error_seen=%s",
            c.seed,
            ctx,
            base,
            pre[0],
            limit,
            pre[1],
            regwen & REGWEN_MASK,
            REGWEN_TRUE,
            valid & VALID_MASK,
            err_seen,
        )
        await self._lock_attempts(ctx, pre)

    async def _leg_l3(self) -> None:
        await self._l3_outside()
        await self._l3_lock("idle")
        await self._l3_lock("after_error")

    # ---- scenario ----------------------------------------------------------
    async def run_scenario(self) -> None:
        seed = self.random_seed()
        self.cfg_t = c = _Cfg(seed)
        self.n_checks = 0
        sim = str(getattr(cocotb, "SIM_NAME", "") or "").lower()
        run_l3 = "verilator" not in sim
        self.logger.info(
            "PLAN seed=%d L1 6 trials, L2 5 kinds + width-2 control, L3 %s (sim=%s); "
            "every trial from a cold reset",
            seed,
            "logged only" if run_l3 else "skipped",
            sim,
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
        if run_l3:
            await self._leg_l3()
        else:
            self.logger.info(
                "L3-SKIP LOG seed=%d sim=%s: leg L3 reads state after reset and runs on a "
                "four-state simulator only",
                seed,
                sim,
            )
        close_graded_window(self.logger)
        await self.irq.stop()
        await self.busy.stop()
        self.logger.info("RESULT %s seed=%d PASS checks=%d", TEST, seed, self.n_checks)
