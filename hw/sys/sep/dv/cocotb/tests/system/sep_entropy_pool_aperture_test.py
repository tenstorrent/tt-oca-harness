# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Entropy-pool aperture: status, pop, write-SLVERR, unmapped, PIC [36]/[37].

no_cpu host-AXI. The pool fills from the native EDN endpoint after the
shared entropy bring-up. Empty-pop SLVERR is taken only after at least one
accepted pop. Bit [36] is observed high, then low, then high; bit [37] is
the first fill-stall after ESRC disable plus EDN_ENABLE=False for
StallThresh cycles with the pool not full. CHK-STALL-DURATION holds the same
stall three times past StallThresh and requires [37] and the fill-stall cause
to stay set. Drain-under-fill is not claimed.

RANDCFG: extra accepted pops come from the run seed. Every seed walks the
high-bit mirrors of the live registers (the offsets that catch a truncated
decode) and all three unique-dead offsets. no_cpu / +skip_fuse_sense /
+esrc_noise_force.
"""

from __future__ import annotations

import cocotb
import pyuvm
from cocotb.triggers import ClockCycles, ReadOnly, RisingEdge
from ocah_axi_vip import AxiTimingProfile
from sep_base_test import sep_base_test
from seq_lib.sep_entropy_pool_seq import (
    CAUSE_FILL_STALL,
    CAUSE_POOL_LOW,
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
        the signed-off ``pool_edn_*`` observation ports and drives nothing.
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

    async def _wait_pool_low(self, pool: SepEntropyPool, expect: int, *, iters: int = 40000) -> int:
        """Wait on the live pool_low flag, not on an occupancy threshold."""
        for _ in range(iters):
            st = await pool.status()
            level = pool_level(st)
            err = pool_flag(st, ST_POOL_ERROR)
            assert err == 0, f"pool_err set in status 0x{st:x}"
            if pool_flag(st, ST_POOL_LOW) == expect:
                return st
            await ClockCycles(cocotb.top.clk_i, 20)
        raise AssertionError(
            f"status pool_low never became {expect} in {iters} status polls (last level={level})"
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
        return level

    async def run_scenario(self) -> None:
        self._edge_levels: list[int] = []
        self._pool_beats: list[int] = []
        cfg = SepEntropyPoolCfg(self.random_seed())
        self.logger.info("entropy-pool aperture: %s", cfg.summary())

        await self.bring_up_no_cpu()
        pool = SepEntropyPool(self)

        # [36] high while empty, before any fill. A stuck-low source fails here.
        st0 = await pool.status()
        level0 = pool_level(st0)
        assert level0 == 0, f"pool not empty at reset: status=0x{st0:x}"
        assert await self._irq(IRQ_POOL_LOW) == 1, "pool_low aggregate [36] not high on empty pool"
        self.logger.info("CHK-POOL-LOW-HIGH PASS: [36]=1 at empty (status=0x%x level=0)", st0)
        cause0 = await pool.irq_cause()
        assert cause0 == CAUSE_POOL_LOW, (
            f"irq-cause 0x{cause0:x} at empty, expected 0x{CAUSE_POOL_LOW:x} (pool_low); "
            f"must not copy status 0x{st0:x} or hardwire 0"
        )
        self.logger.info(
            "CHK-IRQ-CAUSE-LOW PASS: 0x08=0x%x (pool_low) at empty, not status 0x%x",
            cause0,
            st0,
        )

        # Observe-mode CHK5_pool: this test owns the 0x1095 aperture, not
        # bit-exact EDN routing (that is sep_esrc_e2e_smoke_test). report()
        # still gates the >=1-beat floor; a started scoreboard that is never
        # asked cannot fail.
        capture = cocotb.start_soon(self._capture_pool_beats())
        await self.bring_up_entropy(strict=False, score_km=False, score_sinks={"pool": "observe"})
        assert await self.wait_genbits(), "CSRNG CTR_DRBG never produced genbits"
        self.start_fifo_drain()

        st_fill = await self._wait_pool_low(pool, 0)
        level_fill = pool_level(st_fill)
        assert level_fill > 0, f"pool_low cleared with empty pool (status=0x{st_fill:x})"
        assert await self._irq(IRQ_POOL_LOW) == 0, f"[36] still high after fill level={level_fill}"
        self.logger.info(
            "CHK-POOL-FILL PASS: fifo_level=%d pool_low=0 pool_err=0",
            level_fill,
        )
        self.logger.info("CHK-POOL-LOW-LOW PASS: [36]=0 at level=%d", level_fill)
        await self._check_low_edge(st_fill)

        cause = await pool.irq_cause()
        expect_cause = (CAUSE_FILL_STALL if pool_flag(st_fill, ST_FILL_STALL) else 0) | (
            CAUSE_POOL_LOW if pool_flag(st_fill, ST_POOL_LOW) else 0
        )
        # Traversal of 0x08, not a 0==0 snapshot: empty was pool_low, fill must be 0.
        # Hardwired-0 fails CHK-IRQ-CAUSE-LOW; sticky-1 fails here.
        assert cause == 0x0 and cause == expect_cause, (
            f"irq-cause empty=0x{cause0:x} fill=0x{cause:x}, expected "
            f"0x{CAUSE_POOL_LOW:x} -> 0x0 "
            f"(status 0x{st_fill:x} must not be copied)"
        )
        self.logger.info(
            "CHK-IRQ-CAUSE-IDLE PASS: 0x08 0x%x -> 0x0 after fill, not status 0x%x",
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
                    f"unmapped 0x{unmapped:08x} resp={um.resp_code} rdata=0x{um.rdata:x}, "
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
                f"{label} write @0x{addr:08x} resp={wr.resp_code} "
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

        await ClockCycles(cocotb.top.clk_i, STALL_THRESH + 64)
        st_stall = await pool.status()
        fill_stall = pool_flag(st_stall, ST_FILL_STALL)
        assert fill_stall == 1 and await self._irq(IRQ_FILL_STALL) == 1, (
            f"[37] not high after StallThresh (status=0x{st_stall:x} "
            f"level={pool_level(st_stall)} fill_stall={fill_stall} "
            f"edn_req={self.rd(cocotb.top.pool_edn_req_o, allow_unknown=True)} "
            f"edn_ack={self.rd(cocotb.top.pool_edn_ack_o, allow_unknown=True)})"
        )
        self.logger.info(
            "CHK-STALL-ASSERT PASS: [37]=1 after StallThresh=%d with pool not full (level=%d)",
            STALL_THRESH,
            level_room,
        )
        cause_stall = await pool.irq_cause()
        # Fill left pool_low clear and this setup does not drain, so cause
        # is fill_stall alone. Must not copy the raw status word.
        assert cause_stall == CAUSE_FILL_STALL, (
            f"irq-cause 0x{cause_stall:x} at stall, expected 0x{CAUSE_FILL_STALL:x} "
            f"(fill_stall, pool_low still clear); must not copy status "
            f"0x{st_stall:x}"
        )
        self.logger.info(
            "CHK-IRQ-CAUSE-STALL PASS: 0x08=0x%x (fill_stall, pool_low clear), not status 0x%x",
            cause_stall,
            st_stall,
        )

        # The stall counter saturates at StallThresh and the flag clears only on
        # forward progress, so holding the same
        # stall far past the threshold must leave [37] asserted. A counter that
        # wrapped, or a flag that self-cleared on saturation, would drop the
        # fault here and let a real EDN outage go unreported.
        await ClockCycles(cocotb.top.clk_i, STALL_THRESH * 3)
        assert await self._irq(IRQ_FILL_STALL) == 1, (
            f"[37] dropped after {STALL_THRESH * 3} further cycles of the same "
            f"stall; the flag tracks the live stall state, so a saturated counter "
            f"cannot clear it without an edn_ack"
        )
        cause_held = await pool.irq_cause()
        assert cause_held == CAUSE_FILL_STALL, (
            f"irq-cause 0x{cause_held:x} after the extended stall, expected 0x{CAUSE_FILL_STALL:x}"
        )
        self.logger.info(
            "CHK-STALL-DURATION PASS: [37] still 1 and cause still 0x%x after "
            "%d cycles, well past StallThresh=%d",
            cause_held,
            STALL_THRESH * 3,
            STALL_THRESH,
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
                f"accepted pop[{i}] resp={pop.resp_code}, expected OKAY"
            )
            after = pool_level(await pool.status())
            assert after == before - 1, (
                f"pop[{i}] level {before} -> {after}, expected decrement by 1"
            )
            popped.append(pop.rdata)
        assert any(w != 0 for w in popped), f"every accepted pop was 0: {popped}"
        if len(popped) >= 2:
            assert popped[0] != popped[1], f"two popped words identical 0x{popped[0]:x}"
        else:
            nxt_level = pool_level(await pool.status())
            if nxt_level:
                pop2 = await pool.access(POOL_POP)
                assert pop2.resp_code == RESP_OKAY
                popped.append(pop2.rdata)
            assert len(popped) >= 2 and popped[0] != popped[1], (
                f"need two distinct popped words, got {popped}"
            )
        self.logger.info(
            "CHK-POP-DATA PASS: %d accepted pop(s) OKAY, level-1 each, nonzero/distinct words",
            len(popped),
        )

        # Drain to empty so the empty-pop SLVERR is a real empty, not a race.
        drain_iters = 0
        while True:
            st_drain = await pool.status()
            level = await self._check_low_edge(st_drain)
            if level == 0:
                break
            pop = await pool.access(POOL_POP)
            assert pop.resp_code == RESP_OKAY, f"drain pop resp={pop.resp_code} while level>0"
            drain_iters += 1
            assert drain_iters <= FIFO_DEPTH + 2, "drain did not empty"
        self.logger.info(
            "CHK-POOL-LOW-EDGE PASS: aggregate [36] tracked status pool_low "
            "on %d status reads down to empty",
            len(self._edge_levels),
        )
        assert await self._irq(IRQ_POOL_LOW) == 1, "[36] not high again after drain"
        self.logger.info("CHK-POOL-LOW-REHIGH PASS: [36]=1 after drain (high-low-high)")

        empty = await pool.access(POOL_POP, expect_error=True)
        assert empty.resp_code == RESP_SLVERR and not empty.timed_out, (
            f"empty pop resp={empty.resp_code} timed_out={empty.timed_out}, expected SLVERR"
        )
        self.logger.info("CHK-EMPTY-SLVERR PASS: pop @0x10 -> SLVERR on empty pool")

        capture.cancel()
        await self.stop_fifo_drain()
        await self.check_entropy_alerts_zero()
        assert self.drbg_sb.report(), (
            "sep_drbg_scoreboard report failed (CHK5_pool beat floor or CHK1..CHK4)"
        )
        self.logger.info("CHK5_pool PASS: observe-mode pool adapter beats reached the floor")
        self.logger.info("entropy-pool aperture ALL CHECKS PASS")
