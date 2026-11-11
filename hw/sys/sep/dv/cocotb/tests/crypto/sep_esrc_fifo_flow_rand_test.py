# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""ESRC main FIFO: fill, pops, restart, word order, churn and integrity errors.

Contract (``hw/ip/entropy_source/regs/gen/adoc/entropy_source.adoc``, ``INTR_STATUS``,
``FIFO_CTRL``, ``FIFO_STATUS``, ``FIFO_RDATA``; ``hw/ip/entropy_source/doc/architecture.adoc``,
Output FIFO):
  * The main FIFO has 64 entries (architecture.adoc:146). ``LEVEL`` counts the valid
    words and ``RPTR``/``WPTR`` move modulo 64 (entropy_source.adoc:231-235). A write
    while full is discarded and sets ``FIFO_OVERFLOW`` (entropy_source.adoc:144).
  * With ``FIFO_CTRL.ENABLE`` = 0 writes stop and reads continue
    (entropy_source.adoc:221); a ``FIFO_RDATA`` read returns and removes the next
    word (entropy_source.adoc:244).
  * ``ENTROPY_CHURN_ENABLE`` XORs each incoming word with the entry 32 positions
    ahead of the write pointer (entropy_source.adoc:219).
  * The stream port carries each word as it is written into the FIFO
    (architecture.adoc:148).
  * A parity error on a read word, or a pointer-copy mismatch, sets
    ``INTR_STATUS.FIFO_ERROR``, which clears by write-one (architecture.adoc:146;
    entropy_source.adoc:146).
  * A source whose ``INTR_ENABLE`` bit is 0 raises no interrupt
    (``hw/ip/entropy_source/regs/entropy_source.rdl``:168-210): with every enable bit 0,
    PIC source 16 (bit 15 of ``sep_internal_interrupts``, ``hw/sys/sep/doc/interrupts.adoc``
    :22-24, :109-111) stays 0 while a FIFO overflow or underflow is live.

Run mode: no_cpu (``lsu_stub_all_live``), ``+skip_fuse_sense``,
``+esrc_noise_force``. ``SW_RESET_N`` baseline 0x20. The exact-pattern noise
driver (``env/sep_esrc_pattern_noise.py``) drives ``balanced`` from before the
first TRNG reset release. The ESRC FIFO integrity inject
(``esrc_fifo_parity_*``, ``esrc_fifo_ptr_*``, docs/SEP_TB_ARCH.adoc) forces one
stored parity bit of the entry at the read pointer, or holds one bit of one
pointer copy.

Randomization (``SepSeededRng`` from the run seed, drawn before the first
stimulus): the pop count k, the churn mask M, the idle reads between fill
samples, the held word count H, the parity bit, and the pointer, copy and bit
of the pointer trial.

Checkers:
  CHK-FIFO-FILL          LEVEL rises to 64 and stays, FIFO_OVERFLOW = 1,
                         (WPTR - RPTR) mod 64 == LEVEL mod 64 at every sample.
  CHK-FIFO-POP           each pop with the producer stopped: LEVEL - 1, RPTR + 1, WPTR kept;
                         LEVEL and WPTR still kept after the stream port offers a word;
                         control: CTRL-FIFO-POP offered >= 1 stream word in the window.
  CHK-FIFO-RESUME        LEVEL rises from 0 after ENABLE = 1.
  CHK-FIFO-POP-LIVE      pops with ENABLE = 1 and the producer running. A window is a
                         FIFO_STATUS read A, one FIFO_RDATA pop and a FIFO_STATUS read B;
                         t counts the stream words between the return of read A and the
                         start of read B. A window is graded when no stream word falls
                         inside read A or read B, 1 <= L(A) <= 62 and L(A) + t <= 64 (no
                         word can be discarded): L(B) == L(A) - 1 + t
                         (entropy_source.rdl FIFO_STATUS.LEVEL, FIFO_RDATA, FIFO_CTRL.ENABLE;
                         architecture.adoc:148). Controls: CTRL-FIFO-POP-LIVE, graded
                         windows per L(A) class {1, mid, 62} and per kind {pop_only
                         (t = 0), push_pop (t >= 1)}, each above 0.
  CHK-FIFO-ORDER         64 popped words == 64 consecutive stream words at one d in 0..8.
  CHK-FIFO-CHURN         w_k XOR w_(k-32) == C for k = 32..63; control: churn off, every word == C.
  CHK-FIFO-NOERR         FIFO_ERROR reads 0 after each leg; control: INTR_TEST sets it.
  CHK-FIFO-INTEG-PARITY  0 after the intact pop, 1 after the pop of the corrupted entry.
  CHK-FIFO-INTEG-PTR     1 within 16 x the clean pop time after a pointer-copy error.
  CHK-FIFO-INTEG-W1C     the parity trial bit reads 1, then 0 after the write-one clear.
  CHK-FIFO-FLAGS-CLEAR   FIFO_OVERFLOW and FIFO_UNDERFLOW read 0 after their write-one
                         clear (entropy_source.rdl FIFO_OVERFLOW, FIFO_UNDERFLOW);
                         control: CTRL-FIFO-FLAGS sees both at 1 before the clear.
  CHK-ESRC-LIVE-MASKED   with INTR_ENABLE = 0, PIC source 16 reads 0 after a stream word
                         is offered while LEVEL reads 64 before and after it (overflow), and
                         after a FIFO_RDATA read while LEVEL reads 0 before and after it
                         (underflow). Controls: CTRL-ESRC-LIVE-LINE, after each grade an
                         INTR_TEST pulse of PERSISTENT_FAILURE with only its enable set
                         raises source 16 (entropy_source.rdl:193); CTRL-ESRC-LIVE-CAUSE,
                         the same cause with only its enable set, after a write-one clear,
                         sets its INTR_STATUS bit (entropy_source.rdl:129, :136).
  CHK-FIFO-STREAM-FULL   with LEVEL held at 64, the stream port (``esrc_compress_vld_o``)
                         carries at least one word in a window of 2 x the longest gap
                         between stream words of the fill, and LEVEL reads 64 after it
                         (``hw/ip/entropy_source/regs/entropy_source.rdl``:269 "Words
                         offered to the FIFO are also the DRBG seed stream";
                         ``hw/ip/entropy_source/doc/architecture.adoc``:177-178 "The same
                         words leave on ``entropy_stream_data_o`` whatever the FIFO does.");
                         control: CTRL-FIFO-STREAM-FULL, the fill offered at least two words.
Logged only: ``OBS-FIFO-PTR-W1C``, ``OBS-ESRC-LIVE-PIC16`` (source 16 with only the live
cause enabled: the register text does not state which enabled status bits drive source 16),
``OBS-FIFO-CHURN-FIRST32`` (the first 32 churned words XOR C: the churn rule
names no partner for them), ``OBS-FIFO-ERR-ALERT`` (after the parity and the pointer
trial, with FIFO_ERROR as read: the ESRC interrupt line, and LEVEL and WPTR before and
after the stream offers a word with ENABLE = 1; no text states an alert or a write stop
for a FIFO error, and the entropy source has no alert output at the SEP boundary, so the
line records ``alert=none-at-sep-boundary``).

FCOV pass label ``u_sep_fcov.esrc_fifo_pass`` (``ESRC_FIFO_PASS_*``): the leaf pulses
the bit of CHK-FIFO-FILL, CHK-FIFO-POP, each CHK-FIFO-POP-LIVE window and CHK-FIFO-CHURN
after that check passes.
"""

from __future__ import annotations

from dataclasses import dataclass

import cocotb
import pyuvm
from cocotb.triggers import ClockCycles, ReadOnly, RisingEdge
from env.sep_chk_log import SepChkLog
from env.sep_esrc_pattern_noise import (
    NUM_LANES,
    Balanced,
    SepEsrcPatternNoise,
    Stuck,
    balanced_lanes,
    describe,
)
from env.sep_fcov_gate import close_graded_window, fcov_present, open_graded_window
from env.sep_seeded_rng import SepSeededRng
from sep_base_test import sep_base_test
from sep_reg_meta import ENTROPY_SOURCE
from seq_lib.sep_axi_reg_driver import SepAxiRegDriver
from seq_lib.sep_esrc_alert_seq import IRQ_AGG_IDX
from seq_lib.sep_esrc_bringup_seq import (
    ESRC_ALERT_THRESHOLD,
    ESRC_CTRL,
    ESRC_DECORRELATOR_CTRL,
    ESRC_DECORRELATOR_MASK,
    ESRC_FIFO_CTRL,
    ESRC_FIFO_RDATA,
    ESRC_FIFO_STATUS,
    ESRC_INTR_ENABLE,
    ESRC_INTR_STATUS,
    ESRC_INTR_TEST,
    ESRC_MAIN_SM_STATUS,
)
from seq_lib.sep_esrc_clean_start_seq import (
    BYPASS_ALL,
    LATENCY_FACTOR,
    SepEsrcCleanStart,
    SepEsrcLeafSetup,
)

TEST = "sep_esrc_fifo_flow_rand_test"

PARK = ("otbn", "aes", "hmac", "kmac", "abr")
WINDOW = 2048
DEPTH = 64  # architecture.adoc:146
PTR_MOD = 64
STREAM_WINDOW_GAPS = 2  # the full-FIFO stream window spans this many fill word gaps
ORDER_MAX_OFFSET = 8
CHURN_DISTANCE = 32  # entropy_source.adoc:219
CHURN_SETTLE_WORDS = 6
POINTERS = ("wptr", "rptr")

LAT_FACTOR = LATENCY_FACTOR
# Cap of the first fill (no clean fill time yet): 2W + 64 strobes; a healthy fill
# needs far fewer (64 digest words from about 128 whitener input words).
FILL_STROBE_CAP = 2 * WINDOW + 64

INTR_ENABLE_ALL = ENTROPY_SOURCE.mask("INTR_ENABLE")

# Live pop leg. A window from L(A) = 63 or 64 can lose a push to a full FIFO
# (entropy_source.rdl:129), so the highest graded L(A) is 62.
LIVE_TOP = DEPTH - 2
LIVE_MID = DEPTH // 2
LIVE_CLASSES = ("1", "mid", "62")
LIVE_KINDS = ("pop_only", "push_pop")
# Windows per (L(A) target, kind) attempt before the leg moves on (test parameter).
LIVE_TRIES = 8
# A push_pop window holds read B until the stream is quiet for this many clocks, so a
# burst of digest words does not overlap read B (reach only; read B is graded only
# when no word falls inside it).
LIVE_QUIET_CLK = 16
LIVE_PLAN = (
    (LIVE_TOP, "pop_only"),
    (LIVE_MID, "pop_only"),
    (LIVE_MID, "push_pop"),
    (1, "push_pop"),
    (1, "pop_only"),
)

# Bits of u_sep_fcov.esrc_fifo_pass, one per check of this leaf.
ESRC_FIFO_PASS_FILL = 1 << 0  # CHK-FIFO-FILL
ESRC_FIFO_PASS_POP = 1 << 1  # CHK-FIFO-POP
ESRC_FIFO_PASS_POP_LIVE = 1 << 2  # CHK-FIFO-POP-LIVE
ESRC_FIFO_PASS_CHURN = 1 << 3  # CHK-FIFO-CHURN
# Clocks the leaf holds a pass bit before it writes 0.
FIFO_PASS_HOLD_CLKS = 2


def _get(value: int, reg: str, field: str) -> int:
    meta = ENTROPY_SOURCE.fields(reg)[field]
    return (value & meta["bm"]) >> meta["bp"]


def _val(reg: str, **fields: int) -> int:
    return ENTROPY_SOURCE.value(reg, **fields)


def _live_class(level: int) -> str:
    return "1" if level == 1 else "62" if level == LIVE_TOP else "mid"


def _status(value: int) -> tuple[int, int, int]:
    return (
        _get(value, "FIFO_STATUS", "LEVEL"),
        _get(value, "FIFO_STATUS", "WPTR"),
        _get(value, "FIFO_STATUS", "RPTR"),
    )


INTR_FIFO_ERROR = ENTROPY_SOURCE.fields("INTR_STATUS")["FIFO_ERROR"]["bm"]
INTR_FIFO_OVERFLOW = ENTROPY_SOURCE.fields("INTR_STATUS")["FIFO_OVERFLOW"]["bm"]
INTR_FIFO_UNDERFLOW = ENTROPY_SOURCE.fields("INTR_STATUS")["FIFO_UNDERFLOW"]["bm"]
INTR_PF = ENTROPY_SOURCE.fields("INTR_STATUS")["PERSISTENT_FAILURE"]["bm"]


@dataclass(frozen=True)
class Plan:
    seed: int
    k: int
    churn_mask: int
    idle_reads: int
    held: int
    parity_bit: int
    pointer: str
    copy: int
    ptr_bit: int
    balanced: tuple[Balanced, ...]

    @property
    def c_word(self) -> int:
        """The constant incoming word: M in each of its four byte lanes."""
        return self.churn_mask * 0x0101_0101

    def describe(self) -> str:
        return (
            f"k={self.k} m=0x{self.churn_mask:02x} c=0x{self.c_word:08x} "
            f"idle_reads={self.idle_reads} h={self.held} parity_bit={self.parity_bit} "
            f"pointer={self.pointer} copy={self.copy} ptr_bit={self.ptr_bit} "
            f"{describe(self.balanced)}"
        )


def draw_plan(seed: int) -> Plan:
    """Every draw of the leaf, in a fixed order, with no simulator access."""
    rng = SepSeededRng(seed)
    k = rng.randrange(1, DEPTH + 1)
    churn_mask = rng.randrange(1, 256)
    idle_reads = rng.randrange(0, 4)
    held = rng.randrange(2, 41)
    parity_bit = rng.randrange(4)
    pointer = rng.choice(POINTERS)
    copy = rng.randrange(2)
    ptr_bit = rng.randrange(7)
    balanced = tuple(balanced_lanes(rng))
    return Plan(seed, k, churn_mask, idle_reads, held, parity_bit, pointer, copy, ptr_bit, balanced)


class _EsrcRegs(SepAxiRegDriver):
    _DRIVER_TAG = "ESRC"


class _StreamTap:
    """Every-clock reader of esrc_compress_vld_o and esrc_compress_data_o."""

    def __init__(self, test) -> None:
        self.test = test
        self.dut = cocotb.top
        self.words = 0
        self.max_gap = 0
        self._prev_clk: int | None = None
        self.recording = False
        self.record: list[int] = []
        self._on = False
        self._task = None

    def start(self) -> "_StreamTap":
        self._on = True
        self._task = cocotb.start_soon(self._run())
        return self

    async def stop(self) -> None:
        self._on = False
        if self._task is not None:
            await self._task
            self._task = None

    def mark_gaps(self) -> None:
        """Restart the longest-gap measure; the next word starts it."""
        self.max_gap = 0
        self._prev_clk = None

    def last(self, n: int) -> list[int]:
        return self.record[-n:]

    async def _run(self) -> None:
        rd = self.test.rd
        while self._on:
            await RisingEdge(self.dut.clk_i)
            await ReadOnly()
            if rd(self.dut.esrc_compress_vld_o):
                self.words += 1
                now = self.test._now()
                if self._prev_clk is not None:
                    self.max_gap = max(self.max_gap, now - self._prev_clk)
                self._prev_clk = now
                if self.recording:
                    self.record.append(rd(self.dut.esrc_compress_data_o))


@pyuvm.test()
class sep_esrc_fifo_flow_rand_test(sep_base_test):
    """Fill, pop, restart, order, churn and integrity of the ESRC main FIFO."""

    required_evidence = (
        "CHK-FIFO-FILL",
        "CHK-FIFO-POP",
        "CHK-FIFO-RESUME",
        "CHK-FIFO-POP-LIVE",
        "CHK-FIFO-ORDER",
        "CHK-FIFO-CHURN",
        "CHK-FIFO-NOERR",
        "CHK-FIFO-INTEG-PARITY",
        "CHK-FIFO-INTEG-PTR",
        "CHK-FIFO-INTEG-W1C",
        "CHK-FIFO-FLAGS-CLEAR",
        "CHK-FIFO-STREAM-FULL",
        "CHK-ESRC-LIVE-MASKED",
    )

    async def run_scenario(self) -> None:
        await self.bring_up_no_cpu(park=PARK)
        seed = self.random_seed()
        plan = draw_plan(seed)
        self.logger.info("INFO-PLAN seed=%d %s", seed, plan.describe())
        self.plan = plan
        self.chk = SepChkLog(self, TEST, seed)
        self.esrc = _EsrcRegs(self)
        self.p: int | None = None
        self.fill_clk: int | None = None
        self.noerr_legs = 0
        self.logger.info("INFO-BASELINE sw_reset_n=0x%02x", self.swrst.value)
        self._release_injects()
        self.noise = SepEsrcPatternNoise(logger=self.logger)
        self.noise.start(plan.balanced)
        self.setup = SepEsrcLeafSetup(self, self.swrst, self.noise)
        self.tap = _StreamTap(self).start()

        await self._setup()
        open_graded_window(TEST, self.logger)
        if await self._fill_leg():
            await self._pop_leg()
            await self._resume_leg()
            await self._pop_live_leg()
            await self._order_leg()
            await self._churn_leg()
        await self._intr_test_ctrl()
        close_graded_window(self.logger)
        await self._live_cause_leg()
        await self._parity_trial()
        await self._pointer_trial()
        close_graded_window(self.logger)
        self._release_injects()
        await self.tap.stop()
        await self.noise.stop()
        self.chk.finish()

    # --- bus, clocks and bounds -----------------------------------------------
    async def _wr(self, addr: int, data: int) -> None:
        await self.esrc._wr(addr, data)

    async def _rd(self, addr: int) -> int:
        return await self.esrc._rd(addr)

    def _now(self) -> int:
        return self.noise.clk

    def _period(self) -> int:
        return self.setup.period()

    def _fill_bound(self) -> int:
        """16 x the clean fill time, or the strobe cap before the first fill."""
        if self.fill_clk is not None:
            return LAT_FACTOR * self.fill_clk
        return FILL_STROBE_CAP * self._period()

    def _word_bound(self) -> int:
        """16 x the fill time per word (the resume latency bound)."""
        if self.fill_clk is not None:
            return LAT_FACTOR * max(1, self.fill_clk // DEPTH)
        return FILL_STROBE_CAP * self._period()

    def _release_injects(self) -> None:
        dut = cocotb.top
        dut.esrc_fifo_parity_inject_i.value = 0
        dut.esrc_fifo_ptr_inject_i.value = 0

    async def _poll(self, addr: int, getter, pred, bound: int):
        """Reads until pred(getter(value)) holds or bound clocks pass: (ok, value, clocks)."""
        t0 = self._now()
        value = 0
        for _ in range(bound + 1):
            value = await self._rd(addr)
            if pred(getter(value)):
                return True, value, self._now() - t0
            if self._now() - t0 > bound:
                break
        return False, value, self._now() - t0

    async def _level(self) -> int:
        return _get(await self._rd(ESRC_FIFO_STATUS), "FIFO_STATUS", "LEVEL")

    async def _pop_to_empty(self) -> int:
        pops = 0
        for _ in range(DEPTH + 2):
            level = await self._level()
            if level == 0:
                return pops
            for _ in range(level):
                await self._rd(ESRC_FIFO_RDATA)
                pops += 1
        raise AssertionError(f"FIFO_STATUS.LEVEL did not reach 0 after {pops} pops")

    async def _fifo_error(self) -> int:
        return _get(await self._rd(ESRC_INTR_STATUS), "INTR_STATUS", "FIFO_ERROR")

    async def _fifo_pass(self, bits: int) -> None:
        """Pulse the esrc_fifo_pass bits of a check that passed (FIFO_PASS_HOLD_CLKS)."""
        if not fcov_present():
            return
        fcov = cocotb.top.u_sep_fcov
        if not hasattr(fcov, "esrc_fifo_pass"):
            raise AttributeError("u_sep_fcov has no esrc_fifo_pass variable (cov/sv/sep_fcov.sv)")
        fcov.esrc_fifo_pass.value = bits
        self.logger.info("FCOV-ESRC-FIFO-PASS %d", bits)
        await ClockCycles(cocotb.top.clk_i, FIFO_PASS_HOLD_CLKS)
        fcov.esrc_fifo_pass.value = 0
        await RisingEdge(cocotb.top.clk_i)

    async def _next_word(self) -> bool:
        """Wait for the next stream word, at most the per-word bound; True when one came."""
        w0 = self.tap.words
        bound = self._word_bound()
        t0 = self._now()
        while self.tap.words == w0 and self._now() - t0 <= bound:
            await RisingEdge(cocotb.top.clk_i)
        return self.tap.words > w0

    async def _noerr(self, leg: str) -> None:
        err = await self._fifo_error()
        self.noerr_legs += 1
        self.chk.ok("FIFO-NOERR", err == 0, leg=leg, fifo_error=err)

    # --- set-up -----------------------------------------------------------------
    async def _trng_reset(self) -> int:
        return await self.setup.trng_reset(
            balanced=self.plan.balanced, before_release=self._release_injects
        )

    async def _setup(self) -> None:
        close_graded_window(self.logger)
        mark = await self._trng_reset()
        await self._wr(ESRC_INTR_ENABLE, INTR_ENABLE_ALL)
        await self._wr(ESRC_ALERT_THRESHOLD, _val("ALERT_THRESHOLD", THRESHOLD=0))
        await SepEsrcCleanStart(self, self.noise, self.plan.balanced, window=WINDOW).run(
            release_mark=mark
        )
        self.p = await self.setup.measure_period(self.chk)
        await self.setup.wait_boot_done(self.esrc, WINDOW)

    # --- fill leg (steps 2-7) -------------------------------------------------------
    async def _fill_leg(self) -> bool:
        plan = self.plan
        bound = self._fill_bound()
        fill_w0 = self.tap.words
        self.tap.mark_gaps()
        t0 = self._now()
        samples: list[tuple[int, int, int]] = []
        ptr_bad = 0
        full = False
        while self._now() - t0 <= bound:
            lvl, wp, rp = _status(await self._rd(ESRC_FIFO_STATUS))
            samples.append((lvl, wp, rp))
            ptr_bad += ((wp - rp) % PTR_MOD) != (lvl % PTR_MOD)
            if lvl == DEPTH:
                full = True
                break
            for _ in range(plan.idle_reads):
                await self._rd(ESRC_MAIN_SM_STATUS)
        fill = self._now() - t0
        fill_words, fill_gap = self.tap.words - fill_w0, self.tap.max_gap
        if not full:
            self.chk.ok(
                "FIFO-FILL",
                False,
                level_max=max(s[0] for s in samples),
                reason=f"timeout:level64 bound={bound}",
            )
            return False
        self.fill_clk = max(1, fill)
        self.chk.info("FIFO-FILL-REF", clean=self.fill_clk, bound=LAT_FACTOR * self.fill_clk)
        ok, intr, _ = await self._poll(
            ESRC_INTR_STATUS, lambda v: v & INTR_FIFO_OVERFLOW, bool, self._fill_bound()
        )
        overflow = _get(intr, "INTR_STATUS", "FIFO_OVERFLOW")
        plateau_bad = 0
        t1 = self._now()
        while self._now() - t1 <= self.fill_clk:
            lvl, wp, rp = _status(await self._rd(ESRC_FIFO_STATUS))
            samples.append((lvl, wp, rp))
            plateau_bad += lvl != DEPTH
            ptr_bad += ((wp - rp) % PTR_MOD) != (lvl % PTR_MOD)
        # Stream words in a window of STREAM_WINDOW_GAPS x the longest gap between stream
        # words of the fill, with LEVEL held at 64. Control: the fill offered at least two
        # words, so every window of that length inside the fill held at least one word.
        window_clk = STREAM_WINDOW_GAPS * fill_gap
        self.chk.ctrl(
            "FIFO-STREAM-FULL", fill_words >= 2, fill_words=fill_words, fill_max_gap_clk=fill_gap
        )
        w0 = self.tap.words
        await ClockCycles(cocotb.top.clk_i, max(1, window_clk))
        full_window = self.tap.words - w0
        level_after = _status(await self._rd(ESRC_FIFO_STATUS))[0]
        self.chk.ok(
            "FIFO-STREAM-FULL",
            full_window >= 1 and level_after == DEPTH,
            full_window_words=full_window,
            window_clk=window_clk,
            fill_max_gap_clk=fill_gap,
            level_after=level_after,
        )
        first = samples[0][0]
        self.chk.ctrl("FIFO-FILL", first < DEPTH, level_first=first)
        lvl, wp, rp = samples[-1]
        if self.chk.ok(
            "FIFO-FILL",
            ok and overflow == 1 and ptr_bad == 0 and plateau_bad == 0,
            level_max=max(s[0] for s in samples),
            overflow=overflow,
            wptr=wp,
            rptr=rp,
            ptr_diff_ok=ptr_bad == 0,
            plateau_bad=plateau_bad,
            samples=len(samples),
            fill_clk=fill,
        ):
            await self._fifo_pass(ESRC_FIFO_PASS_FILL)
        await self._noerr("fill")
        return True

    # --- pop leg (steps 8-11) ---------------------------------------------------------
    async def _pop_leg(self) -> None:
        plan = self.plan
        await self._wr(ESRC_FIFO_CTRL, _val("FIFO_CTRL", ENABLE=0))
        l0, w0, r0 = _status(await self._rd(ESRC_FIFO_STATUS))
        tap0 = self.tap.words
        prev = (l0, w0, r0)
        bad = 0
        for _ in range(plan.k):
            await self._rd(ESRC_FIFO_RDATA)
            cur = _status(await self._rd(ESRC_FIFO_STATUS))
            bad += cur != (prev[0] - 1, prev[1], (prev[2] + 1) % PTR_MOD)
            prev = cur
        # The stream port offers words whatever FIFO_CTRL.ENABLE is (architecture.adoc:150):
        # the window stays open until one word is offered, and then LEVEL and WPTR must hold.
        bound = self._word_bound()
        t0 = self._now()
        while self.tap.words == tap0 and self._now() - t0 <= bound:
            await self._rd(ESRC_FIFO_STATUS)
        offered = self.tap.words - tap0
        cur = _status(await self._rd(ESRC_FIFO_STATUS))
        bad += cur != prev
        prev = cur
        self.chk.ctrl("FIFO-POP", offered >= 1, offered=offered, wait_bound=bound)
        l1, w1, r1 = prev
        if self.chk.ok(
            "FIFO-POP",
            bad == 0,
            pops=plan.k,
            level_start=l0,
            level_end=l1,
            rptr_delta=(r1 - r0) % PTR_MOD,
            wptr_delta=(w1 - w0) % PTR_MOD,
            bad_pops=bad,
        ):
            await self._fifo_pass(ESRC_FIFO_PASS_POP)
        await self._pop_to_empty()
        await self._rd(ESRC_FIFO_RDATA)  # one read while empty (data undefined, not graded)
        intr = await self._rd(ESRC_INTR_STATUS)
        ovf = _get(intr, "INTR_STATUS", "FIFO_OVERFLOW")
        udf = _get(intr, "INTR_STATUS", "FIFO_UNDERFLOW")
        self.chk.ctrl("FIFO-FLAGS", ovf == 1 and udf == 1, overflow=ovf, underflow=udf)
        await self._noerr("pop")
        await self._wr(ESRC_INTR_STATUS, INTR_FIFO_OVERFLOW | INTR_FIFO_UNDERFLOW)
        after = await self._rd(ESRC_INTR_STATUS)
        ovf_after = _get(after, "INTR_STATUS", "FIFO_OVERFLOW")
        udf_after = _get(after, "INTR_STATUS", "FIFO_UNDERFLOW")
        self.chk.ok(
            "FIFO-FLAGS-CLEAR",
            ovf_after == 0 and udf_after == 0,
            overflow=ovf_after,
            underflow=udf_after,
        )

    # --- resume leg (step 12) ---------------------------------------------------------
    async def _resume_leg(self) -> None:
        l0 = await self._level()
        self.chk.ctrl("FIFO-RESUME", l0 == 0, level_before=l0)
        await self._wr(ESRC_FIFO_CTRL, _val("FIFO_CTRL", ENABLE=1))
        bound = self._word_bound()
        ok, v, clocks = await self._poll(
            ESRC_FIFO_STATUS, lambda x: _get(x, "FIFO_STATUS", "LEVEL"), lambda x: x > 0, bound
        )
        fields = {"enable": 1, "level_rises": ok, "level": _status(v)[0], "clk": clocks}
        if not ok:
            fields["reason"] = f"timeout:level bound={bound}"
        self.chk.ok("FIFO-RESUME", ok and l0 == 0, **fields)
        await self._noerr("resume")

    # --- live pop leg -------------------------------------------------------------------
    async def _steer(self, target: int) -> int:
        """With ENABLE = 1, pop or wait for stream words until LEVEL reads ``target``.

        Pops only the words above ``target`` that a LEVEL read showed, so it never
        reads an empty FIFO. Returns the last LEVEL read.
        """
        level = await self._level()
        for _ in range(4 * DEPTH):
            if level == target:
                break
            if level > target:
                for _ in range(level - target):
                    await self._rd(ESRC_FIFO_RDATA)
            elif not await self._next_word():
                break
            level = await self._level()
        return level

    async def _live_window(self, hold: bool) -> dict | None:
        """Read A, one pop, (``hold``: the next word and a quiet stream), read B.

        Returns None without a pop when read A shows LEVEL 0.
        """
        a0 = self.tap.words
        la = _status(await self._rd(ESRC_FIFO_STATUS))[0]
        a1 = self.tap.words
        if la == 0:
            return None
        await self._rd(ESRC_FIFO_RDATA)
        if hold and await self._next_word():
            last = self.tap.words
            quiet = 0
            for _ in range(DEPTH * LIVE_QUIET_CLK):
                await RisingEdge(cocotb.top.clk_i)
                if self.tap.words != last:
                    last, quiet = self.tap.words, 0
                    continue
                quiet += 1
                if quiet >= LIVE_QUIET_CLK:
                    break
        b0 = self.tap.words
        lb = _status(await self._rd(ESRC_FIFO_STATUS))[0]
        b1 = self.tap.words
        t = b0 - a1
        return {
            "l_a": la,
            "l_b": lb,
            "t": t,
            "inside_a": a1 - a0,
            "inside_b": b1 - b0,
            "graded": a1 == a0 and b1 == b0 and 1 <= la <= LIVE_TOP and la + t <= DEPTH,
        }

    async def _pop_live_leg(self) -> None:
        """CHK-FIFO-POP-LIVE: pops with ENABLE = 1 while the stream writes the FIFO."""
        await self._wr(ESRC_FIFO_CTRL, _val("FIFO_CTRL", ENABLE=1))
        enable = _get(await self._rd(ESRC_FIFO_CTRL), "FIFO_CTRL", "ENABLE")
        by_class = dict.fromkeys(LIVE_CLASSES, 0)
        by_kind = dict.fromkeys(LIVE_KINDS, 0)
        cells: set[tuple[str, str]] = set()
        skipped = 0
        for target, want in LIVE_PLAN:
            cell = (_live_class(target), want)
            for _ in range(LIVE_TRIES):
                if cell in cells:
                    break
                await self._steer(target)
                w = await self._live_window(want == "push_pop")
                if w is None or not w["graded"]:
                    skipped += 1
                    continue
                kind = "pop_only" if w["t"] == 0 else "push_pop"
                cls = _live_class(w["l_a"])
                by_class[cls] += 1
                by_kind[kind] += 1
                cells.add((cls, kind))
                if self.chk.ok(
                    "FIFO-POP-LIVE",
                    enable == 1 and w["l_b"] == w["l_a"] - 1 + w["t"],
                    enable=enable,
                    l_a=w["l_a"],
                    l_b=w["l_b"],
                    t=w["t"],
                    kind=kind,
                    level_class=cls,
                ):
                    await self._fifo_pass(ESRC_FIFO_PASS_POP_LIVE)
        self.chk.info("FIFO-POP-LIVE-SKIP", windows=skipped)
        for cls in LIVE_CLASSES:
            self.chk.ctrl("FIFO-POP-LIVE", by_class[cls] > 0, level_class=cls, graded=by_class[cls])
        for kind in LIVE_KINDS:
            self.chk.ctrl("FIFO-POP-LIVE", by_kind[kind] > 0, kind=kind, graded=by_kind[kind])

    # --- order leg (steps 13-15) --------------------------------------------------------
    async def _order_leg(self) -> None:
        await self._wr(ESRC_FIFO_CTRL, _val("FIFO_CTRL", ENABLE=0))
        await self._pop_to_empty()
        self.tap.record = []
        self.tap.recording = True
        await self._wr(ESRC_FIFO_CTRL, _val("FIFO_CTRL", ENABLE=1))
        bound = self._fill_bound()
        ok, _, _ = await self._poll(
            ESRC_FIFO_STATUS,
            lambda x: _get(x, "FIFO_STATUS", "LEVEL"),
            lambda x: x == DEPTH,
            bound,
        )
        await self._wr(ESRC_FIFO_CTRL, _val("FIFO_CTRL", ENABLE=0))
        self.tap.recording = False
        rec = list(self.tap.record)
        if not ok:
            self.chk.ok("FIFO-ORDER", False, words=0, reason=f"timeout:level64 bound={bound}")
            return
        popped = [await self._rd(ESRC_FIFO_RDATA) for _ in range(DEPTH)]
        offset = None
        for d in range(ORDER_MAX_OFFSET + 1):
            if d + DEPTH <= len(rec) and all(w == rec[i + d] for i, w in enumerate(popped)):
                offset = d
                break
        self.chk.ok(
            "FIFO-ORDER",
            offset is not None,
            words=DEPTH,
            offset="none" if offset is None else offset,
            equal_order=offset is not None,
            recorded=len(rec),
        )
        await self._noerr("order")

    # --- churn leg (steps 16-20) --------------------------------------------------------
    async def _churn_leg(self) -> None:
        plan = self.plan
        c = plan.c_word
        await self._wr(ESRC_FIFO_CTRL, _val("FIFO_CTRL", ENABLE=0))
        await self._pop_to_empty()
        await self._wr(ESRC_DECORRELATOR_CTRL, _val("DECORRELATOR_CTRL", BYPASS=BYPASS_ALL))
        await self._wr(
            ESRC_DECORRELATOR_MASK, _val("DECORRELATOR_MASK", ENTROPY_BYTE_MASK=plan.churn_mask)
        )
        await self._wr(ESRC_CTRL, _val("CTRL", BYPASS_ENTROPY_COMPRESSOR=1))
        self.noise.set_lanes([Stuck(1)] * NUM_LANES)
        self.tap.record = []
        self.tap.recording = True
        bound = self._fill_bound()
        t0 = self._now()
        settled = False
        while self._now() - t0 <= bound:
            last = self.tap.last(CHURN_SETTLE_WORDS)
            if len(last) == CHURN_SETTLE_WORDS and all(w == c for w in last):
                settled = True
                break
            await RisingEdge(cocotb.top.clk_i)
        self.tap.recording = False
        self.chk.ctrl("FIFO-CHURN-C", settled, c=f"0x{c:08x}", settle_bound=bound)
        if not settled:
            self.chk.ok("FIFO-CHURN", False, reason=f"timeout:constant_word bound={bound}")
            await self._noerr("churn")
            return
        on = await self._fill_and_pop(churn=1)
        off = None
        if on is not None:
            await self._pop_to_empty()
            off = await self._fill_and_pop(churn=0)
        pairs = 0
        bad = 0
        if on is not None:
            for k in range(CHURN_DISTANCE, DEPTH):
                pairs += 1
                bad += (on[k] ^ on[k - CHURN_DISTANCE]) != c
            self.chk.obs(
                "FIFO-CHURN-FIRST32",
                c=f"0x{c:08x}",
                words_xor_c=",".join(f"0x{on[k] ^ c:08x}" for k in range(CHURN_DISTANCE)),
            )
        ctrl_ok = off is not None and all(w == c for w in off)
        self.chk.ctrl("FIFO-CHURN", ctrl_ok, ctrl_churn_off_words_equal_c=ctrl_ok)
        fields = {
            "churn": 1,
            "pairs": pairs,
            "c": f"0x{c:08x}",
            "mismatches": bad,
            "ctrl_churn_off_words_equal_c": ctrl_ok,
        }
        if on is None:
            fields["reason"] = f"timeout:level64 bound={self._fill_bound()}"
        if self.chk.ok("FIFO-CHURN", on is not None and pairs > 0 and bad == 0, **fields):
            await self._fifo_pass(ESRC_FIFO_PASS_CHURN)
        await self._noerr("churn")

    async def _fill_and_pop(self, *, churn: int) -> list[int] | None:
        """ENABLE = 1 with the churn bit, poll LEVEL 64, ENABLE = 0, pop 64 words."""
        await self._wr(ESRC_FIFO_CTRL, _val("FIFO_CTRL", ENABLE=1, ENTROPY_CHURN_ENABLE=churn))
        bound = self._fill_bound()
        ok, _, _ = await self._poll(
            ESRC_FIFO_STATUS,
            lambda x: _get(x, "FIFO_STATUS", "LEVEL"),
            lambda x: x == DEPTH,
            bound,
        )
        await self._wr(ESRC_FIFO_CTRL, _val("FIFO_CTRL", ENABLE=0, ENTROPY_CHURN_ENABLE=churn))
        if not ok:
            return None
        return [await self._rd(ESRC_FIFO_RDATA) for _ in range(DEPTH)]

    async def _intr_test_ctrl(self) -> None:
        """Control of CHK-FIFO-NOERR: INTR_TEST.FIFO_ERROR sets the bit, W1C clears it."""
        await self._wr(ESRC_INTR_TEST, INTR_FIFO_ERROR)
        set_v = await self._fifo_error()
        await self._wr(ESRC_INTR_STATUS, INTR_FIFO_ERROR)
        clr_v = await self._fifo_error()
        self.chk.ctrl(
            "FIFO-NOERR",
            set_v == 1 and clr_v == 0 and self.noerr_legs > 0,
            intr_test_sets=set_v,
            w1c=clr_v,
            legs=self.noerr_legs,
        )

    # --- live causes with the interrupt masked ------------------------------------------
    def _pic16(self) -> int:
        vec = self.rd_known(cocotb.top.sep_internal_interrupts_probe_o, mask=1 << IRQ_AGG_IDX)
        return (vec >> IRQ_AGG_IDX) & 1

    async def _set_enable(self, value: int) -> int:
        await self._wr(ESRC_INTR_ENABLE, value)
        return await self._rd(ESRC_INTR_ENABLE) & INTR_ENABLE_ALL

    async def _overflow(self) -> tuple[bool, dict]:
        """One stream word offered while LEVEL reads 64 before and after it."""
        l0 = await self._level()
        w0 = self.tap.words
        bound = self._word_bound()
        t0 = self._now()
        while self.tap.words == w0 and self._now() - t0 <= bound:
            await RisingEdge(cocotb.top.clk_i)
        offered = self.tap.words - w0
        l1 = await self._level()
        live = l0 == DEPTH and offered >= 1 and l1 == DEPTH
        return live, {"level_before": l0, "words_offered": offered, "level_after": l1}

    async def _underflow(self) -> tuple[bool, dict]:
        """One FIFO_RDATA read while LEVEL reads 0 before and after it."""
        l0 = await self._level()
        await self._rd(ESRC_FIFO_RDATA)
        l1 = await self._level()
        return l0 == 0 and l1 == 0, {"level_before": l0, "level_after": l1}

    async def _live_line(self, cause: str) -> None:
        """CTRL-ESRC-LIVE-LINE: INTR_TEST.PERSISTENT_FAILURE with its enable raises source 16."""
        en = await self._set_enable(INTR_PF)
        await self._wr(ESRC_INTR_TEST, INTR_PF)
        st = await self._rd(ESRC_INTR_STATUS)
        pic = self._pic16()
        await self._wr(ESRC_INTR_STATUS, INTR_PF)
        self.chk.ctrl(
            "ESRC-LIVE-LINE",
            en == INTR_PF and st & INTR_PF and pic == 1,
            after=cause,
            intr_enable=f"0x{en:08x}",
            intr_status=f"0x{st:08x}",
            vector_bit15=pic,
        )

    async def _cause_legs(self, cause: str, bm: int, drive) -> None:
        en = await self._set_enable(0)
        live, fields = await drive()
        pic = self._pic16()
        self.chk.ok(
            "ESRC-LIVE-MASKED",
            live and en == 0 and pic == 0,
            cause=cause,
            intr_enable=f"0x{en:08x}",
            vector_bit15=pic,
            **fields,
        )
        await self._live_line(cause)
        en = await self._set_enable(bm)
        await self._wr(ESRC_INTR_STATUS, bm)
        live, fields = await drive()
        st = await self._rd(ESRC_INTR_STATUS)
        pic = self._pic16()
        self.chk.ctrl(
            "ESRC-LIVE-CAUSE",
            live and en == bm and st & bm,
            cause=cause,
            intr_enable=f"0x{en:08x}",
            intr_status=f"0x{st:08x}",
            **fields,
        )
        self.chk.obs("ESRC-LIVE-PIC16", cause=cause, intr_enable=f"0x{en:08x}", vector_bit15=pic)

    async def _live_cause_leg(self) -> None:
        """Overflow with the producer running into a full FIFO, then underflow once empty."""
        await self._setup()
        await self._poll(
            ESRC_FIFO_STATUS,
            lambda x: _get(x, "FIFO_STATUS", "LEVEL"),
            lambda x: x == DEPTH,
            self._fill_bound(),
        )
        await self._cause_legs("FIFO_OVERFLOW", INTR_FIFO_OVERFLOW, self._overflow)
        await self._wr(ESRC_FIFO_CTRL, _val("FIFO_CTRL", ENABLE=0))
        await self._pop_to_empty()
        await self._cause_legs("FIFO_UNDERFLOW", INTR_FIFO_UNDERFLOW, self._underflow)

    # --- integrity trials (steps 21-28) -------------------------------------------------
    async def _err_alert_obs(self, trial: str) -> None:
        """OBS-FIFO-ERR-ALERT: after a FIFO error, does the FIFO still take a stream word."""
        close_graded_window(self.logger)
        err = await self._fifo_error()
        irq = self._pic16()
        l0, w0, _ = _status(await self._rd(ESRC_FIFO_STATUS))
        tap0 = self.tap.words
        await self._wr(ESRC_FIFO_CTRL, _val("FIFO_CTRL", ENABLE=1))
        await self._next_word()
        await self._wr(ESRC_FIFO_CTRL, _val("FIFO_CTRL", ENABLE=0))
        offered = self.tap.words - tap0
        l1, w1, _ = _status(await self._rd(ESRC_FIFO_STATUS))
        self.chk.obs(
            "FIFO-ERR-ALERT",
            trial=trial,
            fifo_error=err,
            esrc_irq=irq,
            level_before=l0,
            wptr_before=w0,
            words_offered=offered,
            level_after=l1,
            wptr_after=w1,
            fifo_error_after=await self._fifo_error(),
            alert="none-at-sep-boundary",
        )
        open_graded_window(TEST, self.logger)

    async def _hold(self) -> tuple[bool, int]:
        """Set-up, LEVEL >= H, ENABLE = 0; returns (ok, held count)."""
        plan = self.plan
        await self._setup()
        bound = self._fill_bound()
        ok, _, _ = await self._poll(
            ESRC_FIFO_STATUS,
            lambda x: _get(x, "FIFO_STATUS", "LEVEL"),
            lambda x: x >= plan.held,
            bound,
        )
        await self._wr(ESRC_FIFO_CTRL, _val("FIFO_CTRL", ENABLE=0))
        return ok, await self._level()

    async def _parity_trial(self) -> None:
        plan = self.plan
        dut = cocotb.top
        ok, held = await self._hold()
        e0 = await self._fifo_error()
        await self._rd(ESRC_FIFO_RDATA)
        e1 = await self._fifo_error()
        open_graded_window(TEST, self.logger)
        dut.esrc_fifo_parity_bit_i.value = plan.parity_bit
        dut.esrc_fifo_parity_inject_i.value = 1
        await ClockCycles(dut.clk_i, 2)
        await self._rd(ESRC_FIFO_RDATA)
        e2 = await self._fifo_error()
        dut.esrc_fifo_parity_inject_i.value = 0
        await ClockCycles(dut.clk_i, 2)
        fields = {
            "held": held,
            "parity_bit": plan.parity_bit,
            "pre_error": e0,
            "intact_pop_error": e1,
            "parity_pop_error": e2,
        }
        if not ok:
            fields["reason"] = f"timeout:held bound={self._fill_bound()}"
        self.chk.ctrl("FIFO-INTEG-PARITY", e2 == 1, parity_pop_error=e2)
        self.chk.ok("FIFO-INTEG-PARITY", ok and e0 == 0 and e1 == 0 and e2 == 1, **fields)
        await self._err_alert_obs("parity")
        before = await self._fifo_error()
        await self._wr(ESRC_INTR_STATUS, INTR_FIFO_ERROR)
        after = await self._fifo_error()
        self.chk.ctrl("FIFO-INTEG-W1C", before == 1, before=before)
        self.chk.ok("FIFO-INTEG-W1C", before == 1 and after == 0, before=before, after=after)
        close_graded_window(self.logger)

    async def _pointer_trial(self) -> None:
        plan = self.plan
        dut = cocotb.top
        ok, held = await self._hold()
        e0 = await self._fifo_error()
        t0 = self._now()
        await self._rd(ESRC_FIFO_RDATA)
        clean_pop = max(1, self._now() - t0)
        e1 = await self._fifo_error()
        open_graded_window(TEST, self.logger)
        dut.esrc_fifo_ptr_sel_i.value = (POINTERS.index(plan.pointer) << 1) | plan.copy
        dut.esrc_fifo_ptr_bit_i.value = plan.ptr_bit
        dut.esrc_fifo_ptr_inject_i.value = 1
        await ClockCycles(dut.clk_i, 2)
        w0 = self.tap.words
        await self._wr(ESRC_FIFO_CTRL, _val("FIFO_CTRL", ENABLE=1))
        wbound = self._word_bound()
        t1 = self._now()
        while self.tap.words == w0 and self._now() - t1 <= wbound:
            await RisingEdge(dut.clk_i)
        word_passed = self.tap.words > w0
        await self._wr(ESRC_FIFO_CTRL, _val("FIFO_CTRL", ENABLE=0))
        await self._rd(ESRC_FIFO_RDATA)
        bound = LAT_FACTOR * clean_pop
        detect, _, clocks = await self._poll(
            ESRC_INTR_STATUS, lambda v: _get(v, "INTR_STATUS", "FIFO_ERROR"), bool, bound
        )
        dut.esrc_fifo_ptr_inject_i.value = 0
        await ClockCycles(dut.clk_i, 2)
        self.chk.ctrl("FIFO-INTEG-PTR", e0 == 0 and e1 == 0, ctrl_pre_error=e0 | e1)
        fields = {
            "pointer": plan.pointer,
            "copy": plan.copy,
            "bit": plan.ptr_bit,
            "held": held,
            "detect_clk": clocks if detect else "none",
            "clean_pop_clk": clean_pop,
            "bound": bound,
            "fifo_error": int(detect),
            "ctrl_pre_error": e0 | e1,
            "word_passed": word_passed,
        }
        if not detect:
            fields["reason"] = "timeout"
        self.chk.ok("FIFO-INTEG-PTR", ok and detect and e0 == 0 and e1 == 0, **fields)
        await self._err_alert_obs("pointer")
        await self._wr(ESRC_INTR_STATUS, INTR_FIFO_ERROR)
        self.chk.obs("FIFO-PTR-W1C", fifo_error=await self._fifo_error())
        close_graded_window(self.logger)
