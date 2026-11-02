# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Entropy-pool aperture: status, pop, write-SLVERR, unmapped, aggregator bits [36]/[37].

no_cpu host-AXI. The pool fills from the native EDN endpoint after the
shared entropy bring-up. Empty-pop SLVERR is taken only after at least one
accepted pop. Bit [36] must equal STATUS pool_low at every graded read; the
low watermark is not stated, so the pool_low value at empty is logged only
(OBS-POOL-LOW-EMPTY, OBS-POOL-LOW-REHIGH). CHK-POOL-FILL claims that pool_low
clears only when pool_low and [36] read 1 together at empty; otherwise it claims
only that both read 0 at a level above 0. Bit [37] is the first fill-stall
after ESRC disable plus EDN_ENABLE=False with the pool not full: the stall
threshold is not stated, so STATUS is polled up to STALL_POLL_CAP clocks and
the time to the flag is logged (OBS-POOL-STALL-TIME). CHK-STALL-DURATION holds
the same stall STALL_THRESH * 3 clocks after the flag rose and requires [37]
and the fill-stall cause to stay set. Drain-under-fill is not claimed.

CHK-POP-DATA: each accepted pop after CHK-HALF-READ, the drain pops included,
returns the next packed word of the captured pool EDN beats, in the packing
order that CHK-HALF-READ found.

CHK-HALF-READ: a 32-bit read at a register's upper word is refused with RDATA 0
and does not pop. CHK-WRITE-ORDER: aw-first and w-first writes each get one
SLVERR and leave the pool level unchanged.

CHK-POOL-LEVEL-STEP (hw/sys/sep/doc/entropy_pool.adoc:31-43): every pool
access followed by a 64-bit STATUS read, with no captured pool EDN beat from
the issue of the STATUS read before the access to the end of the STATUS read
after it, moves fifo_level by exactly the OKAY DATA pops between: one lower for
a pop, unchanged for a STATUS read, an IRQ_CAUSE read, a refused write and a
refused upper-word DATA read. Each of those five classes needs at least one
graded pair. In the stall phase two IRQ_CAUSE reads are followed by a STATUS
read that must show the armed level.

IRQ_CAUSE values: the RDL names the fields and gives no description, and no
document states whether the register is live or latched or what bits 63:3
read. Each value is logged only (OBS-POOL-CAUSE-EMPTY, OBS-POOL-CAUSE-IDLE,
OBS-POOL-CAUSE-STALL, OBS-POOL-CAUSE-HELD) and no check depends on it. The
graded part of an IRQ_CAUSE read is its OKAY response and that it does not
move fifo_level (CHK-POOL-LEVEL-STEP).

FCOV: the graded window (owner sep_entropy_pool_aperture_test) opens after
CHK-POOL-LOW-HIGH, before the pool EDN capture and the entropy bring-up, so
the [36] fall at the first fill is inside it, and closes after
CHK-EMPTY-SLVERR and the CHK-POOL-LEVEL-STEP class floor. A raise closes it.

RANDCFG: extra accepted pops come from the run seed. Every seed walks the
high-bit mirrors of the live registers (the offsets that catch a truncated
decode) and all three unique-dead offsets. Run mode: no_cpu with
+skip_fuse_sense and +esrc_noise_force.
"""

from __future__ import annotations

import cocotb
import pyuvm
from cocotb.triggers import ClockCycles, NextTimeStep, ReadOnly, RisingEdge
from cocotb.utils import get_sim_time
from env.sep_fcov_gate import close_graded_window, open_graded_window
from ocah_axi_vip import AxiTimingProfile
from sep_base_test import sep_base_test
from seq_lib.sep_axi_access_seq import SepAxiAccessSeq
from seq_lib.sep_entropy_pool_seq import (
    FIFO_DEPTH,
    HALF_UPPER,
    IRQ_FILL_STALL,
    IRQ_POOL_LOW,
    POOL_IRQ_CAUSE,
    POOL_POP,
    POOL_STATUS,
    RESP_OKAY,
    RESP_SLVERR,
    ST_FILL_STALL,
    ST_POOL_ERROR,
    ST_POOL_LOW,
    STALL_THRESH,
    SepEntropyPool,
    SepEntropyPoolCfg,
    pool_flag,
    pool_level,
)

TEST = "sep_entropy_pool_aperture_test"

# CHK-POOL-LEVEL-STEP access classes (hw/sys/sep/doc/entropy_pool.adoc:31 a DATA
# read pops one word; :34 STATUS and IRQ_CAUSE are non-destructive; :38-39 a
# write changes no state; :42-43 a refused upper-word DATA read does not pop).
STEP_CLASSES = ("pop", "status", "cause", "write", "upper_data")
# DV-owned ceiling of the fill-stall poll, in clocks. The threshold is not stated
# (sep_entropy_pool.rdl STATUS.fill_stall: "the configured stall threshold"), so
# no check depends on it; a DUT threshold above this ceiling fails the poll.
STALL_POLL_CAP = 16 * STALL_THRESH
STALL_POLL_STEP = 64
# DV-owned ceiling of the CHK-POOL-FILL wait, in STATUS polls 20 clocks apart. The
# fill time is not stated, so no check depends on it. The wait starts after CSRNG
# produced genbits and the EDN stream to the pool runs, so a pool that fills ends
# the wait in a few polls. A pool that does not fill fails CHK-POOL-FILL at this
# ceiling, well inside the testlist timeout.
FILL_POLL_CAP = 4096


class _LevelStep:
    """CHK-POOL-LEVEL-STEP: the fifo_level step between two 64-bit STATUS reads.

    ``beats`` is the live list of pool EDN beats the leaf captures. A pair is
    graded only when that list does not grow from the issue of the first
    STATUS read to the end of the second, so no fill can enter either level.
    The golden is the first level minus the OKAY 64-bit DATA reads between.
    The class of a pair is the last pop, IRQ_CAUSE read, write or upper-word
    DATA read between the two STATUS reads, else ``status``.
    """

    def __init__(self, beats: list[int]) -> None:
        self.beats = beats
        self.on = False
        self._base: tuple[int, int] | None = None  # (level, beats at issue)
        self._cls = "status"
        self._pops = 0
        self.counts = dict.fromkeys(STEP_CLASSES, 0)
        self.steps: dict[str, set[tuple[int, int]]] = {c: set() for c in STEP_CLASSES}
        self.graded = 0
        self.skipped = 0
        self.last: tuple[str, int, int] | None = None  # (class, before, after)

    def note(self, addr: int, write: bool, nbytes: int, seq, issue_beats: int) -> None:
        if not self.on:
            return
        okay = seq.resp_code == RESP_OKAY
        if not write and nbytes == 8 and addr == POOL_STATUS and okay:
            self._status(pool_level(seq.rdata), issue_beats)
            return
        if self._base is None:
            return
        if write:
            self._cls = "write"
        elif nbytes == 8 and addr == POOL_POP and okay:
            self._pops += 1
            self._cls = "pop"
        elif nbytes == 8 and addr == POOL_IRQ_CAUSE and okay:
            self._cls = "cause"
        elif nbytes == 4 and addr == POOL_POP + 4:
            self._cls = "upper_data"

    def _status(self, level: int, issue_beats: int) -> None:
        if self._base is not None:
            before, base_beats = self._base
            if len(self.beats) == base_beats:
                want = before - self._pops
                if level != want:
                    raise AssertionError(
                        f"CHK-POOL-LEVEL-STEP FAIL: {self._cls} pair fifo_level "
                        f"{before} -> {level}, expected {want} ({self._pops} OKAY "
                        f"DATA pop(s) between, no pool EDN beat between)"
                    )
                self.counts[self._cls] += 1
                self.steps[self._cls].add((before, level))
                self.graded += 1
                self.last = (self._cls, before, level)
            else:
                self.skipped += 1
        self._base = (level, issue_beats)
        self._cls = "status"
        self._pops = 0

    def stop(self) -> None:
        self.on = False
        self._base = None

    def summary(self) -> str:
        return ", ".join(f"{c}={self.counts[c]} {sorted(self.steps[c])}" for c in STEP_CLASSES)


class _LevelStepPool(SepEntropyPool):
    """``SepEntropyPool`` whose every aperture access feeds ``_LevelStep``."""

    step: _LevelStep | None = None

    async def access(self, addr: int, **kw) -> SepAxiAccessSeq:
        step = self.step
        issue_beats = len(step.beats) if step is not None else 0
        seq = await super().access(addr, **kw)
        if step is not None:
            step.note(addr, kw.get("write", False), kw.get("nbytes", 8), seq, issue_beats)
        return seq


@pyuvm.test()
class sep_entropy_pool_aperture_test(sep_base_test):
    """64-bit entropy-pool aperture: pop, refuse, and aggregator bits [36]/[37]."""

    async def _irq(self, idx: int) -> int:
        # Sample in ReadOnly so NBA has settled. Do not await a second
        # posedge here: that makes ``_wait_irq`` count two clocks per poll.
        # Do not await ReadWrite either: cocotb forbids ReadOnly -> ReadWrite.
        # Callers that drive AXI wait their own posedge (the master driver
        # already does).
        await RisingEdge(cocotb.top.clk_i)
        await ReadOnly()
        raw = cocotb.top.sep_internal_interrupts_probe_o.value
        if not raw.is_resolvable:
            raise AssertionError(f"sep_internal_interrupts X/Z while sampling bit [{idx}]")
        return (int(raw) >> idx) & 1

    async def _wait_irq(self, idx: int, expect: int, *, cycles: int) -> None:
        for _ in range(cycles):
            if await self._irq(idx) == expect:
                return
        raise AssertionError(
            f"sep_internal_interrupts[{idx}] did not become {expect} in {cycles} cycles"
        )

    async def _arm_not_full_no_ack(self, pool: SepEntropyPool) -> int:
        """Pop leftover until the pool has room and EDN acks have stopped.

        A full pool holds ``req_pending`` low and clears the stall counter.
        One pop is not enough: an in-flight EDN word can refill to full
        during the next status read. Cap the pops at leftover EDN-adapter
        beats, not the CSRNG generate length (``glen``).
        """
        for _ in range(FIFO_DEPTH * 8):
            last = pool_level(await pool.status())
            if last >= FIFO_DEPTH:
                pop = await pool.access(POOL_POP)
                assert pop.resp_code == RESP_OKAY, "room-making pop not OKAY on a full pool"
                continue
            ack = 0
            for _c in range(32):
                await RisingEdge(cocotb.top.clk_i)
                await ReadOnly()
                raw = cocotb.top.pool_edn_ack_o.value
                if not raw.is_resolvable:
                    raise AssertionError("pool_edn_ack_o X/Z during leftover wait")
                ack |= int(raw)
            await RisingEdge(cocotb.top.clk_i)
            nxt = pool_level(await pool.status())
            if (not ack) and nxt == last and nxt < FIFO_DEPTH:
                return nxt
        raise AssertionError("EDN acks did not stop with pool not full after EDN_ENABLE=0")

    async def _capture_pool_beats(self) -> None:
        """Record every 32-bit EDN beat the pool accepts, in order.

        The pool packs two native EDN beats into each 64-bit word. This record
        is the reference CHK-HALF-READ grades a popped word against. It reads
        the accepted ``pool_edn_*`` observation ports and drives nothing.
        """
        top = cocotb.top
        while True:
            await RisingEdge(top.clk_i)
            await ReadOnly()
            req, ack = top.pool_edn_req_o.value, top.pool_edn_ack_o.value
            if not (req.is_resolvable and ack.is_resolvable):
                continue
            if int(req) and int(ack):
                bus = top.pool_edn_bus_o.value
                if not bus.is_resolvable:
                    raise AssertionError("pool_edn_bus_o X/Z on an accepted pool EDN beat")
                self._pool_beats.append(int(bus) & 0xFFFF_FFFF)

    def _pair_index(self, word: int) -> list[tuple[int, bool]]:
        """Each (i, hi_first) where ``word`` packs captured beats i and i+1."""
        beats = self._pool_beats
        hits = []
        for i in range(len(beats) - 1):
            lo_first = (beats[i + 1] << 32) | beats[i]
            hi_first = (beats[i] << 32) | beats[i + 1]
            if word == lo_first:
                hits.append((i, False))
            if word == hi_first:
                hits.append((i, True))
        return hits

    def _check_pop_word(self, label: str, word: int) -> None:
        """CHK-POP-DATA: ``word`` is the next packed word of the captured beats.

        The pool packs two EDN beats per 64-bit word in arrival order; the packing
        order (which beat is high) is the one CHK-HALF-READ found. The cursor then
        moves two beats.
        """
        i = self._pop_next
        nxt = self._pool_beats[i : i + 2]
        assert len(nxt) == 2, (
            f"CHK-POP-DATA FAIL: {label} 0x{word:016x} has no captured beats at index {i} "
            f"({len(self._pool_beats)} captured)"
        )
        want = (nxt[0] << 32) | nxt[1] if self._pop_hi_first else (nxt[1] << 32) | nxt[0]
        assert word == want, (
            f"CHK-POP-DATA FAIL: {label} returned 0x{word:016x}, expected the next packed "
            f"word 0x{want:016x} (beats {i}, {i + 1})"
        )
        self._pop_next = i + 2

    async def _check_half_reads(self, pool: SepEntropyPool) -> None:
        """CHK-HALF-READ: a 32-bit beat at a register's upper word is refused.

        ``sep_entropy_pool.rdl`` gives every register ``accesswidth = 64``. The
        refused read must return RDATA=0, must not pop, and must not disturb the
        FIFO: the 64-bit pop after it returns the word that follows the pop
        before it in the captured EDN beat stream.
        """
        level0 = pool_level(await pool.status())
        assert level0 >= 3, f"CHK-HALF-READ FAIL: precondition needs >=3 pool words, level={level0}"
        before = await pool.access(POOL_POP)
        assert before.resp_code == RESP_OKAY, f"pre-half pop resp={before.resp_code}"
        level1 = pool_level(await pool.status())
        assert level1 == level0 - 1, f"pre-half pop level {level0} -> {level1}"
        hits = self._pair_index(before.rdata)
        assert len(hits) == 1, (
            f"CHK-HALF-READ FAIL: popped word 0x{before.rdata:016x} matches {len(hits)} "
            f"adjacent pairs of the {len(self._pool_beats)} captured pool EDN beats, "
            f"expected exactly one"
        )
        idx, hi_first = hits[0]
        mon = self.env.axi_monitor
        mon.open_error_rdata_window()
        try:
            for label, addr in HALF_UPPER:
                half = await pool.access(addr, expect_error=True, nbytes=4)
                assert half.resp_code == RESP_SLVERR and half.rdata == 0 and not half.timed_out, (
                    f"CHK-HALF-READ FAIL: 32-bit read of the {label} upper word "
                    f"0x{addr:08x} resp={half.resp_code} rdata=0x{half.rdata:x} "
                    f"timed_out={half.timed_out}, expected SLVERR + RDATA=0"
                )
                level = pool_level(await pool.status())
                assert level == level1, (
                    f"CHK-HALF-READ FAIL: 32-bit read of the {label} upper word "
                    f"changed fifo_level {level1} -> {level}; a refused read popped"
                )
        finally:
            mon.close_error_rdata_window()
        after = await pool.access(POOL_POP)
        assert after.resp_code == RESP_OKAY, f"post-half pop resp={after.resp_code}"
        nxt = self._pool_beats[idx + 2 : idx + 4]
        assert len(nxt) == 2, "CHK-HALF-READ FAIL: no captured beats after the pre-half word"
        want = (nxt[0] << 32) | nxt[1] if hi_first else (nxt[1] << 32) | nxt[0]
        assert after.rdata == want, (
            f"CHK-HALF-READ FAIL: 64-bit pop after the refused half reads returned "
            f"0x{after.rdata:016x}, expected the next packed word 0x{want:016x}"
        )
        level2 = pool_level(await pool.status())
        assert level2 == level1 - 1, f"post-half pop level {level1} -> {level2}"
        # CHK-POP-DATA continues from here: the next pop packs beats idx + 4, idx + 5.
        self._pop_next = idx + 4
        self._pop_hi_first = hi_first
        self.logger.info(
            "CHK-HALF-READ PASS: %d 32-bit upper-word reads (%s) -> SLVERR RDATA=0, "
            "fifo_level held at %d; the next 64-bit pop returned 0x%016x, the word "
            "after 0x%016x in the captured EDN stream (beat %d, %s)",
            len(HALF_UPPER),
            ",".join(f"0x{a:08x}" for _l, a in HALF_UPPER),
            level1,
            after.rdata,
            before.rdata,
            idx,
            "first beat high" if hi_first else "first beat low",
        )

    async def _wait_pool_low(
        self, pool: SepEntropyPool, expect: int, *, iters: int = FILL_POLL_CAP
    ) -> int:
        """Wait on the live pool_low flag, not on an occupancy threshold."""
        for _ in range(iters):
            st = await pool.status()
            level = pool_level(st)
            err = pool_flag(st, ST_POOL_ERROR)
            assert err == 0, f"pool_err set in status 0x{st:x}"
            if pool_flag(st, ST_POOL_LOW) == expect:
                return st
            self._fill_prev_level = level
            await ClockCycles(cocotb.top.clk_i, 20)
        raise AssertionError(
            f"CHK-POOL-FILL FAIL: status pool_low never became {expect} in {iters} "
            f"status polls (last level={level})"
        )

    async def _check_low_edge(self, st: int) -> int:
        """Aggregate [36] must follow the live status pool_low flag.

        Occupancy is not compared against a FIFO watermark. The flag-to-IRQ
        connection is what this check can fail.
        """
        level = pool_level(st)
        low = pool_flag(st, ST_POOL_LOW)
        assert await self._irq(IRQ_POOL_LOW) == low, (
            f"CHK-POOL-LOW-EDGE FAIL: aggregate [36] disagrees with status "
            f"pool_low={low} at level={level}"
        )
        self._edge_levels.append(level)
        self._edge_trace.append((level, low))
        return level

    async def run_scenario(self) -> None:
        self._edge_levels: list[int] = []
        # (level, pool_low) of every _check_low_edge read, and the last fill
        # poll level that still read pool_low 1.
        self._edge_trace: list[tuple[int, int]] = []
        self._fill_prev_level: int | None = None
        self._pool_beats: list[int] = []
        self._pop_next = 0
        self._pop_hi_first = False
        cfg = SepEntropyPoolCfg(self.random_seed())
        self.logger.info("entropy-pool aperture: %s", cfg.summary())

        await self.bring_up_no_cpu()
        pool = _LevelStepPool(self)

        # [36] high while empty, before any fill. A stuck-low source fails here.
        # The low watermark is not stated, so pool_low at empty is logged only. The
        # graded part is that [36] carries the STATUS pool_low flag. No text states
        # the IRQ_CAUSE value, so it is logged only.
        st0 = await pool.status()
        level0 = pool_level(st0)
        assert level0 == 0, f"pool not empty at reset: status=0x{st0:x}"
        low0 = pool_flag(st0, ST_POOL_LOW)
        irq0 = await self._irq(IRQ_POOL_LOW)
        cause0 = await pool.irq_cause()
        self.logger.info(
            "OBS-POOL-LOW-EMPTY level=0 status=0x%x pool_low=%d irq36=%d cause=0x%x",
            st0,
            low0,
            irq0,
            cause0,
        )
        assert irq0 == low0, (
            f"CHK-POOL-LOW-HIGH FAIL: [36]={irq0} at empty, STATUS pool_low={low0} "
            f"(status=0x{st0:x})"
        )
        self.logger.info(
            "CHK-POOL-LOW-HIGH PASS: [36]=%d equals STATUS pool_low at empty (status=0x%x)",
            irq0,
            st0,
        )
        self.logger.info("OBS-POOL-CAUSE-EMPTY cause=0x%x status=0x%x", cause0, st0)
        self._step = _LevelStep(self._pool_beats)
        pool.step = self._step
        open_graded_window(TEST, self.logger)
        try:
            capture = await self._graded(pool, cfg, cause0, low0 == 1 and irq0 == 1)
        except BaseException:
            # A failure may resume from ReadOnly, where no value can be written.
            await NextTimeStep()
            close_graded_window(self.logger)
            raise
        close_graded_window(self.logger)

        capture.cancel()
        await self.stop_fifo_drain()
        await self.check_entropy_alerts_zero()
        assert self.drbg_sb.report(), (
            "sep_drbg_scoreboard report failed (CHK5_pool beat floor or CHK1..CHK4)"
        )
        self.logger.info("CHK5_pool PASS: observe-mode pool adapter beats reached the floor")
        self.logger.info("entropy-pool aperture ALL CHECKS PASS")

    async def _graded(
        self, pool: _LevelStepPool, cfg: SepEntropyPoolCfg, cause0: int, high_at_empty: bool
    ):
        """The graded window body: fill, refusals, stall, pops and drain to empty.

        ``high_at_empty`` is True when STATUS pool_low and [36] both read 1 at
        the empty read. Only then does CHK-POOL-FILL claim that pool_low clears.
        """
        # Observe-mode CHK5_pool: this test owns the entropy-pool aperture
        # (0x1095_0000), not bit-exact EDN routing (that is
        # sep_esrc_e2e_smoke_test). report() still gates the >=1-beat floor; a
        # started scoreboard that is never asked cannot fail.
        capture = cocotb.start_soon(self._capture_pool_beats())
        self._step.on = True
        await self.bring_up_entropy(strict=False, score_km=False, score_sinks={"pool": "observe"})
        assert await self.wait_genbits(), "CSRNG CTR_DRBG never produced genbits"
        self.start_fifo_drain()

        st_fill = await self._wait_pool_low(pool, 0)
        level_fill = pool_level(st_fill)
        self._fill_level = level_fill
        low_fill = pool_flag(st_fill, ST_POOL_LOW)
        irq_fill = await self._irq(IRQ_POOL_LOW)
        # A clear is claimed only after pool_low and [36] read 1 together at
        # empty. The low watermark is not stated, so a flag that reads 0 at
        # empty is not a fault here, and the line then claims no clear.
        claim = (
            "pool_low and [36] read 1 at level 0, then 0"
            if high_at_empty
            else "no clear claimed: pool_low read 0 at level 0 (OBS-POOL-LOW-EMPTY)"
        )
        assert level_fill > 0 and low_fill == 0 and irq_fill == 0, (
            f"CHK-POOL-FILL FAIL: fifo_level={level_fill} pool_low={low_fill} [36]={irq_fill} "
            f"(status=0x{st_fill:x}), expected fifo_level > 0 with pool_low 0 and [36] 0"
        )
        self.logger.info(
            "CHK-POOL-FILL PASS: %s; fifo_level=%d pool_low=0 [36]=0 pool_err=0 high_at_empty=%d",
            claim,
            level_fill,
            int(high_at_empty),
        )
        self.logger.info("CHK-POOL-LOW-LOW PASS: [36]=0 at level=%d", level_fill)
        await self._check_low_edge(st_fill)

        cause = await pool.irq_cause()
        self.logger.info(
            "OBS-POOL-CAUSE-IDLE cause=0x%x empty_cause=0x%x status=0x%x",
            cause,
            cause0,
            st_fill,
        )

        await pool.disable_esrc()
        # The driver packs X/Z read bits as 0, and the s_axi monitor lane-checks
        # error beats only inside an error-RDATA window. Open it so an X/Z on a
        # refused beat fails instead of passing the RDATA=0 compare below.
        mon = self.env.axi_monitor
        mon.open_error_rdata_window()
        try:
            for off in (*cfg.alias_offs, *cfg.unmapped_offs):
                unmapped = POOL_STATUS + off
                um = await pool.access(unmapped, expect_error=True)
                assert um.resp_code == RESP_SLVERR and um.rdata == 0 and not um.timed_out, (
                    f"CHK-UNMAPPED FAIL: unmapped 0x{unmapped:08x} resp={um.resp_code} "
                    f"rdata=0x{um.rdata:x}, "
                    f"expected SLVERR + RDATA=0"
                )
        finally:
            mon.close_error_rdata_window()
        self.logger.info(
            "CHK-UNMAPPED PASS: %d alias + %d unique-dead offsets -> SLVERR rdata=0",
            len(cfg.alias_offs),
            len(cfg.unmapped_offs),
        )

        # ESRC MODULE_ENABLE=0 does not drop AUTO-mode EDN acks. EDN_ENABLE=False
        # is what leaves the pool request outstanding without ack. Pop after
        # that so req_pending stays high (a full pool holds it low and clears
        # the stall counter). The live/unmapped write walk is here, with room
        # in the FIFO: a full pool cannot show a refused fill.
        await pool.disable_edn()
        level_room = await self._arm_not_full_no_ack(pool)
        # DUT-side precondition for the refused-fill check: the pool has an
        # outstanding entropy request, which is what keeps req_pending asserted.
        req = cocotb.top.pool_edn_req_o.value
        assert req.is_resolvable, f"pool_edn_req_o is unresolvable ({req})"
        assert int(req) == 1, (
            f"write-SLVERR arming left no outstanding pool request "
            f"(level={level_room}, pool_edn_req_o=0)"
        )
        write_cells = (
            ("status", POOL_STATUS),
            ("irq-cause", POOL_IRQ_CAUSE),
            ("data", POOL_POP),
            ("unmapped", POOL_STATUS + cfg.unmapped_offs[0]),
        )
        # These writes are the same-cycle arm of the AW/W arrival orders graded
        # below, so the order is taken from the s_axi monitor, as for the other
        # two arms, not assumed from the backend default.
        for label, addr in write_cells:
            mon.arm_write_order()
            wr = await pool.access(addr, write=True, wdata=0xFFFF, expect_error=True)
            seen = mon.last_write_stim
            aw_cyc, w_cyc = mon.write_order_cycles[0], mon.write_order_cycles[1]
            assert seen == "same-cycle", (
                f"CHK-WRITE-SLVERR FAIL: {label} write was meant to present AW and W "
                f"in the same cycle, but the s_axi monitor saw {seen} (AWVALID cycle "
                f"{aw_cyc}, WVALID cycle {w_cyc})"
            )
            assert wr.resp_code == RESP_SLVERR and not wr.timed_out, (
                f"CHK-WRITE-SLVERR FAIL: {label} write @0x{addr:08x} resp={wr.resp_code} "
                f"timed_out={wr.timed_out}, expected SLVERR"
            )
            st_after_wr = await pool.status()
            assert pool_level(st_after_wr) == level_room, (
                f"{label} write changed fifo_level {level_room} -> {pool_level(st_after_wr)}"
            )
        self.logger.info(
            "CHK-WRITE-SLVERR PASS: %d live/unmapped write cells, AW and W observed "
            "in the same cycle, returned SLVERR, level unchanged (%d < depth %d)",
            len(write_cells),
            level_room,
            FIFO_DEPTH,
        )

        # AW and W carry no ordering requirement between them (AMBA IHI 0022
        # A3.3); one write transaction answers one BRESP. The backend presents
        # both in the same cycle, so the aw-first and w-first arms of that
        # handshake are unreachable without arming the master. The profile is
        # only a request: the order the DUT saw is taken from the s_axi monitor,
        # which records the first AWVALID and WVALID cycle after it is armed.
        # The background ESRC FIFO drain shares this master, so it is paused
        # while the profile is armed; ESRC is already disabled, so the FIFO
        # cannot overflow meanwhile.
        drv = self.env.axi_agent.driver.axi.driver
        await self.stop_fifo_drain()
        for order, profile in (
            ("aw-first", AxiTimingProfile(w_delay=4)),
            ("w-first", AxiTimingProfile(aw_delay=4)),
        ):
            mon.arm_write_order()
            drv.set_timing(profile)
            try:
                wr = await pool.access(POOL_STATUS, write=True, wdata=0xFFFF, expect_error=True)
                # Sample before the status read below issues more traffic.
                seen = mon.last_write_stim
                aw_cyc, w_cyc = mon.write_order_cycles[0], mon.write_order_cycles[1]
            finally:
                drv.set_timing(AxiTimingProfile())
            assert seen == order, (
                f"CHK-WRITE-ORDER FAIL: requested {order} but the s_axi monitor saw "
                f"{seen} (AWVALID cycle {aw_cyc}, WVALID cycle {w_cyc}); the arm "
                "cannot be credited from the timing profile alone"
            )
            assert wr.resp_code == RESP_SLVERR and not wr.timed_out, (
                f"{order} write resp={wr.resp_code} timed_out={wr.timed_out}, "
                f"expected one SLVERR; a slave that assumes same-cycle arrival "
                f"either wedges or answers twice"
            )
            st = await pool.status()
            assert pool_level(st) == level_room, (
                f"{order} write changed fifo_level {level_room} -> {pool_level(st)}"
            )
            self.logger.info(
                "CHK-WRITE-ORDER PASS: %s write observed on s_axi (AWVALID cycle %s, "
                "WVALID cycle %s), BRESP=SLVERR, level unchanged (%d)",
                order,
                aw_cyc,
                w_cyc,
                level_room,
            )
        self.start_fifo_drain()

        # The stall threshold is not stated: poll STATUS until fill_stall reads 1, up
        # to the DV ceiling, and log the time to the flag.
        t_stall0 = get_sim_time("ns")
        waited = 0
        st_stall = await pool.status()
        while not pool_flag(st_stall, ST_FILL_STALL) and waited < STALL_POLL_CAP:
            await ClockCycles(cocotb.top.clk_i, STALL_POLL_STEP)
            waited += STALL_POLL_STEP
            st_stall = await pool.status()
        fill_stall = pool_flag(st_stall, ST_FILL_STALL)
        self.logger.info(
            "OBS-POOL-STALL-TIME ns=%d polled_clocks=%d fill_stall=%d level=%d",
            get_sim_time("ns") - t_stall0,
            waited,
            fill_stall,
            pool_level(st_stall),
        )
        assert fill_stall == 1 and await self._irq(IRQ_FILL_STALL) == 1, (
            f"CHK-STALL-ASSERT FAIL: fill_stall or [37] not high within the poll ceiling "
            f"of {STALL_POLL_CAP} clocks (status=0x{st_stall:x} "
            f"level={pool_level(st_stall)} fill_stall={fill_stall} "
            f"edn_req={self.rd(cocotb.top.pool_edn_req_o, allow_unknown=True)} "
            f"edn_ack={self.rd(cocotb.top.pool_edn_ack_o, allow_unknown=True)})"
        )
        self.logger.info(
            "CHK-STALL-ASSERT PASS: STATUS fill_stall=1 and [37]=1 with the pool not full "
            "(level=%d) and the fill request outstanding",
            pool_level(st_stall),
        )
        cause_stall = await pool.irq_cause()
        self.logger.info("OBS-POOL-CAUSE-STALL cause=0x%x status=0x%x", cause_stall, st_stall)

        # The flag reports a fill request that is still outstanding, so holding the
        # same stall for STALL_THRESH * 3 more clocks (a DV-chosen hold) must leave
        # [37] asserted. A counter that wrapped, or a flag that self-cleared, would
        # drop the fault here and let a real EDN outage go unreported.
        await ClockCycles(cocotb.top.clk_i, STALL_THRESH * 3)
        assert await self._irq(IRQ_FILL_STALL) == 1, (
            f"CHK-STALL-DURATION FAIL: [37] dropped after {STALL_THRESH * 3} further cycles of the same "
            f"stall; the flag tracks the live stall state, so a saturated counter "
            f"cannot clear it without an edn_ack"
        )
        self.logger.info(
            "CHK-STALL-DURATION PASS: [37] still 1 %d cycles after the flag rose",
            STALL_THRESH * 3,
        )
        cause_held = await pool.irq_cause()
        self.logger.info("OBS-POOL-CAUSE-HELD cause=0x%x", cause_held)

        # Stall phase: EDN is disabled and the pool is not full, so no fill can
        # enter. The two IRQ_CAUSE reads above must leave fifo_level at the armed
        # level (hw/sys/sep/doc/entropy_pool.adoc:34, non-destructive reads).
        graded0 = self._step.graded
        st_kept = await pool.status()
        kept = pool_level(st_kept)
        last = self._step.last
        if self._step.graded != graded0 + 1 or last is None or last[0] != "cause":
            raise AssertionError(
                f"CHK-POOL-LEVEL-STEP FAIL: stall-phase IRQ_CAUSE reads not followed by "
                f"a graded STATUS pair (last pair={last}, "
                f"cause_pairs={self._step.counts['cause']}, level_room={level_room})"
            )
        if kept != level_room:
            raise AssertionError(
                f"CHK-POOL-LEVEL-STEP FAIL: stall-phase STATUS level {kept} after two "
                f"IRQ_CAUSE reads, expected the armed level {level_room}"
            )
        self.logger.info(
            "CHK-POOL-LEVEL-STEP PASS: stall phase, IRQ_CAUSE 0x%x read twice, next "
            "STATUS level %d == armed level %d, no pool EDN beat between",
            cause_held,
            kept,
            level_room,
        )

        await pool.enable_edn()
        await pool.enable_esrc()
        await self._wait_irq(IRQ_FILL_STALL, 0, cycles=20000)
        self.logger.info("CHK-STALL-CLEAR PASS: [37]=0 after EDN/ESRC re-enable")

        await pool.disable_edn()
        await pool.disable_esrc()
        await self._arm_not_full_no_ack(pool)
        await self._check_half_reads(pool)
        st_pre = await pool.status()
        level = pool_level(st_pre)
        assert level >= 1, "pool empty before accepted-pop leg"
        pops = min(cfg.extra_pops, max(level - 1, 1))
        popped: list[int] = []
        for i in range(pops):
            before = pool_level(await pool.status())
            pop = await pool.access(POOL_POP)
            assert pop.resp_code == RESP_OKAY, (
                f"CHK-POP-DATA FAIL: accepted pop[{i}] resp={pop.resp_code}, expected OKAY"
            )
            after = pool_level(await pool.status())
            assert after == before - 1, (
                f"CHK-POP-DATA FAIL: pop[{i}] level {before} -> {after}, expected decrement by 1"
            )
            self._check_pop_word(f"pop[{i}]", pop.rdata)
            popped.append(pop.rdata)
        self.logger.info(
            "CHK-POP-DATA PASS: %d accepted pop(s) OKAY, level-1 each, each word the next "
            "packed word of the captured pool EDN beats: %s",
            len(popped),
            ",".join(f"0x{w:016x}" for w in popped),
        )

        # Drain to empty so the empty-pop SLVERR is a real empty, not a race.
        drain_iters = 0
        drain_mark = len(self._edge_trace)
        while True:
            st_drain = await pool.status()
            level = await self._check_low_edge(st_drain)
            if level == 0:
                break
            pop = await pool.access(POOL_POP)
            assert pop.resp_code == RESP_OKAY, f"drain pop resp={pop.resp_code} while level>0"
            self._check_pop_word(f"drain[{drain_iters}]", pop.rdata)
            drain_iters += 1
            assert drain_iters <= FIFO_DEPTH + 2, "drain did not empty"
        self.logger.info(
            "CHK-POOL-LOW-EDGE PASS: aggregate [36] tracked status pool_low "
            "on %d status reads down to empty",
            len(self._edge_levels),
        )
        self.logger.info(
            "CHK-POP-DATA PASS: %d drain pops, each the next packed word of the captured "
            "pool EDN beats (next beat index %d of %d)",
            drain_iters,
            self._pop_next,
            len(self._pool_beats),
        )
        # No line states the low watermark: the levels where pool_low changes are logged.
        drain = self._edge_trace[drain_mark:]
        first_low = next((lv for lv, lo in drain if lo == 1), None)
        self.logger.info(
            "OBS-POOL-LOW-LEVEL drain_first_low_level=%s fill_clear_level=%d "
            "fill_last_low_level=%s drain_trace=%s",
            first_low,
            self._fill_level,
            self._fill_prev_level,
            ",".join(f"{lv}:{lo}" for lv, lo in drain),
        )
        # The drain loop graded [36] against STATUS pool_low down to level 0
        # (CHK-POOL-LOW-EDGE); the pool_low value at empty is not stated.
        st_empty = await pool.status()
        self.logger.info(
            "OBS-POOL-LOW-REHIGH level=%d pool_low=%d irq36=%d",
            pool_level(st_empty),
            pool_flag(st_empty, ST_POOL_LOW),
            await self._irq(IRQ_POOL_LOW),
        )

        empty = await pool.access(POOL_POP, expect_error=True)
        assert empty.resp_code == RESP_SLVERR and not empty.timed_out, (
            f"CHK-EMPTY-SLVERR FAIL: empty pop resp={empty.resp_code} "
            f"timed_out={empty.timed_out}, expected SLVERR"
        )
        self.logger.info("CHK-EMPTY-SLVERR PASS: pop @0x10 -> SLVERR on empty pool")
        self._step.stop()
        missing = [c for c in STEP_CLASSES if self._step.counts[c] == 0]
        if missing:
            raise AssertionError(
                f"CHK-POOL-LEVEL-STEP FAIL: no graded pair for {','.join(missing)} "
                f"(graded={self._step.graded} skipped={self._step.skipped}: "
                f"{self._step.summary()})"
            )
        self.logger.info(
            "CHK-POOL-LEVEL-STEP PASS: %d STATUS pairs graded with no pool EDN beat "
            "between (%d skipped on a fill), level steps per class (before, after): %s",
            self._step.graded,
            self._step.skipped,
            self._step.summary(),
        )
        return capture
