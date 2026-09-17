# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Entropy-pool aperture: status, pop, write-SLVERR, unmapped, PIC [36]/[37].

no_cpu host-AXI. The pool fills from the native EDN endpoint after the
shared entropy bring-up. Empty-pop SLVERR is taken only after at least one
accepted pop. Bit [36] is observed high, then low, then high; bit [37] is
the first fill-stall after ESRC disable plus EDN_ENABLE=False for
StallThresh cycles with the pool not full. Drain-under-fill and stall-duration
stress are not claimed.

RANDCFG: extra accepted pops and one unique-dead offset come from the
run seed. Every seed walks the high-bit mirrors of the live registers
(the offsets that catch a truncated decode). no_cpu / +skip_fuse_sense /
+esrc_noise_force.
"""

from __future__ import annotations

import cocotb
from ocah_axi_vip import AxiTimingProfile
import pyuvm
from cocotb.triggers import ClockCycles, ReadOnly, RisingEdge
from sep_base_test import sep_base_test
from seq_lib.sep_entropy_pool_seq import (
    FIFO_DEPTH,
    IRQ_FILL_STALL,
    IRQ_POOL_LOW,
    POOL_POP,
    POOL_STATUS,
    RESP_OKAY,
    RESP_SLVERR,
    STALL_THRESH,
    SepEntropyPool,
    SepEntropyPoolCfg,
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
            last = (await pool.status()) & 0x3F
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
            nxt = (await pool.status()) & 0x3F
            if (not ack) and nxt == last and nxt < FIFO_DEPTH:
                return nxt
        raise AssertionError("EDN acks did not stop with pool not full after EDN_ENABLE=0")

    async def _wait_pool_low(self, pool: SepEntropyPool, expect: int, *, iters: int = 40000) -> int:
        """Wait on the live pool_low flag, not on an occupancy threshold."""
        for _ in range(iters):
            st = await pool.status()
            level = st & 0x3F
            err = (st >> 8) & 1
            assert err == 0, f"pool_err set in status 0x{st:x}"
            if ((st >> 6) & 1) == expect:
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
        level = st & 0x3F
        low = (st >> 6) & 1
        assert await self._irq(IRQ_POOL_LOW) == low, (
            f"CHK-POOL-LOW-EDGE FAIL: aggregate [36] disagrees with status "
            f"pool_low={low} at level={level}"
        )
        self._edge_levels.append(level)
        return level

    async def run_scenario(self) -> None:
        self._edge_levels: list[int] = []
        cfg = SepEntropyPoolCfg(self.random_seed())
        self.logger.info("entropy-pool aperture: %s", cfg.summary())

        await self.bring_up_no_cpu()
        pool = SepEntropyPool(self)

        # [36] high while empty, before any fill. A stuck-low source fails here.
        st0 = await pool.status()
        level0 = st0 & 0x3F
        assert level0 == 0, f"pool not empty at reset: status=0x{st0:x}"
        assert await self._irq(IRQ_POOL_LOW) == 1, "pool_low aggregate [36] not high on empty pool"
        self.logger.info("CHK-POOL-LOW-HIGH PASS: [36]=1 at empty (status=0x%x level=0)", st0)
        cause0 = await pool.irq_cause()
        assert cause0 == 0x1, (
            f"irq-cause 0x{cause0:x} at empty, expected 0x1 (pool_low); "
            f"must not copy status 0x{st0:x} or hardwire 0"
        )
        self.logger.info("CHK-IRQ-CAUSE-LOW PASS: 0x08=0x1 at empty, not status 0x%x", st0)

        # Observe-mode CHK5_pool: this test owns the 0x1095 aperture, not
        # bit-exact EDN routing (that is sep_esrc_e2e_smoke_test). report()
        # still gates the >=1-beat floor; a started scoreboard that is never
        # asked cannot fail.
        await self.bring_up_entropy(strict=False, score_km=False, score_sinks={"pool": "observe"})
        assert await self.wait_genbits(), "CSRNG CTR_DRBG never produced genbits"
        self.start_fifo_drain()

        st_fill = await self._wait_pool_low(pool, 0)
        level_fill = st_fill & 0x3F
        assert level_fill > 0, f"pool_low cleared with empty pool (status=0x{st_fill:x})"
        assert await self._irq(IRQ_POOL_LOW) == 0, f"[36] still high after fill level={level_fill}"
        self.logger.info(
            "CHK-POOL-FILL PASS: fifo_level=%d pool_low=0 pool_err=0",
            level_fill,
        )
        self.logger.info("CHK-POOL-LOW-LOW PASS: [36]=0 at level=%d", level_fill)
        await self._check_low_edge(st_fill)

        cause = await pool.irq_cause()
        expect_cause = ((st_fill >> 7) & 1) << 1 | ((st_fill >> 6) & 1)
        # Traversal of 0x08, not a 0==0 snapshot: empty was 0x1, fill must be 0x0.
        # Hardwired-0 fails CHK-IRQ-CAUSE-LOW; sticky-1 fails here.
        assert cause == 0x0 and cause == expect_cause, (
            f"irq-cause empty=0x{cause0:x} fill=0x{cause:x}, expected 0x1 -> 0x0 "
            f"(status 0x{st_fill:x} must not be copied)"
        )
        self.logger.info(
            "CHK-IRQ-CAUSE-IDLE PASS: 0x08 0x1 -> 0x0 after fill, not status 0x%x", st_fill
        )

        await pool.disable_esrc()
        for off in (*cfg.alias_offs, *cfg.unmapped_offs):
            unmapped = POOL_STATUS + off
            um = await pool.access(unmapped, expect_error=True)
            assert um.resp_code == RESP_SLVERR and um.rdata == 0 and not um.timed_out, (
                f"unmapped 0x{unmapped:08x} resp={um.resp_code} rdata=0x{um.rdata:x}, "
                f"expected SLVERR + RDATA=0"
            )
        self.logger.info(
            "CHK-UNMAPPED PASS: %d alias + %d unique-dead offsets -> SLVERR rdata=0",
            len(cfg.alias_offs),
            len(cfg.unmapped_offs),
        )

        # ESRC MODULE_ENABLE=0 does not drop AUTO-mode EDN acks. EDN_ENABLE=False
        # is what leaves the pool request outstanding without ack. Pop after
        # that so req_pending stays high (a full pool holds it low and clears
        # the stall counter). Status write is here, with room in the FIFO: a
        # full pool cannot show a refused fill.
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
        wr = await pool.access(POOL_STATUS, write=True, wdata=0xFFFF, expect_error=True)
        assert wr.resp_code == RESP_SLVERR and not wr.timed_out, (
            f"status write resp={wr.resp_code} timed_out={wr.timed_out}, expected SLVERR"
        )
        st_after_wr = await pool.status()
        assert (st_after_wr & 0x3F) == level_room, (
            f"write changed fifo_level {level_room} -> {st_after_wr & 0x3F}"
        )
        self.logger.info(
            "CHK-WRITE-SLVERR PASS: write BRESP=SLVERR, level unchanged (%d < depth %d)",
            level_room,
            FIFO_DEPTH,
        )

        # AW and W carry no ordering requirement between them (AMBA IHI 0022
        # A3.3), and sep_entropy_fifo.sv:390 states it accepts either order and
        # answers one SLVERR. The backend presents both in the same cycle, so
        # the aw_recv_q-first and w_recv_q-first arms of that handshake are
        # unreachable without arming the master.
        drv = self.env.axi_agent.driver.axi.driver
        for order, profile in (
            ("aw-first", AxiTimingProfile(w_delay=4)),
            ("w-first", AxiTimingProfile(aw_delay=4)),
        ):
            drv.set_timing(profile)
            try:
                wr = await pool.access(
                    POOL_STATUS, write=True, wdata=0xFFFF, expect_error=True
                )
            finally:
                drv.set_timing(AxiTimingProfile())
            assert wr.resp_code == RESP_SLVERR and not wr.timed_out, (
                f"{order} write resp={wr.resp_code} timed_out={wr.timed_out}, "
                f"expected one SLVERR; a slave that assumes same-cycle arrival "
                f"either wedges or answers twice"
            )
            st = await pool.status()
            assert (st & 0x3F) == level_room, (
                f"{order} write changed fifo_level {level_room} -> {st & 0x3F}"
            )
            self.logger.info(
                "CHK-WRITE-ORDER PASS: %s write BRESP=SLVERR, level unchanged (%d)",
                order,
                level_room,
            )

        await ClockCycles(cocotb.top.clk_i, STALL_THRESH + 64)
        st_stall = await pool.status()
        fill_stall = (st_stall >> 7) & 1
        assert fill_stall == 1 and await self._irq(IRQ_FILL_STALL) == 1, (
            f"[37] not high after StallThresh (status=0x{st_stall:x} "
            f"level={st_stall & 0x3F} fill_stall={fill_stall} "
            f"edn_req={int(self.rd(cocotb.top.pool_edn_req_o))} "
            f"edn_ack={int(self.rd(cocotb.top.pool_edn_ack_o))})"
        )
        self.logger.info(
            "CHK-STALL-ASSERT PASS: [37]=1 after StallThresh=%d with pool not full (level=%d)",
            STALL_THRESH,
            level_room,
        )
        cause_stall = await pool.irq_cause()
        # Fill left pool_low clear and this setup does not drain, so cause
        # is fill_stall alone. Must not copy the raw status word.
        assert cause_stall == 0x2, (
            f"irq-cause 0x{cause_stall:x} at stall, expected 0x2 "
            f"(fill_stall, pool_low still clear); must not copy status "
            f"0x{st_stall:x}"
        )
        self.logger.info(
            "CHK-IRQ-CAUSE-STALL PASS: 0x08=0x2 (fill_stall, pool_low clear), not status 0x%x",
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
        assert cause_held == 0x2, (
            f"irq-cause 0x{cause_held:x} after the extended stall, expected 0x2"
        )
        self.logger.info(
            "CHK-STALL-DURATION PASS: [37] still 1 and cause still 0x2 after "
            "%d cycles, well past StallThresh=%d",
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
        st_pre = await pool.status()
        level = st_pre & 0x3F
        assert level >= 1, "pool empty before accepted-pop leg"
        pops = min(cfg.extra_pops, max(level - 1, 1))
        popped: list[int] = []
        for i in range(pops):
            before = (await pool.status()) & 0x3F
            pop = await pool.access(POOL_POP)
            assert pop.resp_code == RESP_OKAY, (
                f"accepted pop[{i}] resp={pop.resp_code}, expected OKAY"
            )
            after = (await pool.status()) & 0x3F
            assert after == before - 1, (
                f"pop[{i}] level {before} -> {after}, expected decrement by 1"
            )
            popped.append(pop.rdata)
        assert any(w != 0 for w in popped), f"every accepted pop was 0: {popped}"
        if len(popped) >= 2:
            assert popped[0] != popped[1], f"two popped words identical 0x{popped[0]:x}"
        else:
            nxt_level = (await pool.status()) & 0x3F
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

        await self.stop_fifo_drain()
        await self.check_entropy_alerts_zero()
        assert self.drbg_sb.report(), (
            "sep_drbg_scoreboard report failed (CHK5_pool beat floor or CHK1..CHK4)"
        )
        self.logger.info("CHK5_pool PASS: observe-mode pool adapter beats reached the floor")
        self.logger.info("entropy-pool aperture ALL CHECKS PASS")
