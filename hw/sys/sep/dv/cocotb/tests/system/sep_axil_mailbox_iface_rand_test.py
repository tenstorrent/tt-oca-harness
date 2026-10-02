# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""axil_mailbox interface breadth (randomized-rep, TX path).

no_cpu host-AXI test of the SEP axil_mailbox MECHANICS over the CPU-LSU master,
on the outbound_mailbox_0 aperture (0x10A0_0000) -- the SEP/CPU side of the
two-port cross-FIFO, reachable with NO inbound filter. This is the TX-path test:
with no CPU running the RX FIFO is always empty. Distinct from the
outbound->PIC->CPU delivery path
(sep_mailbox_plic_test).

A SepMboxCfg config object (seeded WIRQT + payloads) is the single source of truth
for DUT programming and the golden depth model (env/sep_mbox_golden.py), which
predicts the visible STATUS bits + the write-threshold IRQ from the TX occupancy
(STATUS has no exact-depth field). Thresholds compare with strict greater-than
(``architecture.adoc``: fill level exceeds the configured threshold). Seed is
logged; regression mode can sweep this via TOML ``reseed = N``.

reference refs: fabric sep_mailbox_64bit_data_test, sep_mailbox_misc_regs_test,
sep_fabric_mailbox_fifo_closure_test (one rep subsumes the TX FIFO/IRQ/error/flush family).
RUN-MODE: no_cpu (CPU-LSU master). FUSE-MODE: +skip_fuse_sense (the local mailbox has
no OTP/LC dependency).

Not covered here: (1) data round-trip readback and (2) read-threshold (RIRQT) need the
RX FIFO filled from the peer side, which this aperture cannot do, so the read half of
the threshold pair has no vehicle on this master. The rep is TX-only, like the
reference test it ports; the peer path is reachable only from the external
smn_inbound master.
"""

from __future__ import annotations

import pyuvm
from env.sep_mbox_golden import (
    ERR_READ,
    ERR_WRITE,
    ERROR_FLAGS,
    IRQ_EIRQ,
    IRQ_WTIRQ,
    IRQEN,
    IRQP,
    IRQS,
    READ_EMPTY_SENTINEL,
    RESP_OKAY,
    RESP_SLVERR,
    ST_EMPTY,
    ST_FULL,
    ST_RLVL_ABOVE,
    ST_WLVL_ABOVE,
    STATUS,
    WIRQT,
    WRITE_DATA_RD_SENTINEL,
    SepMboxCfg,
    SepMboxGolden,
)
from sep_base_test import sep_base_test
from seq_lib.sep_mailbox_iface_seq import SepMbox


@pyuvm.test()
class sep_axil_mailbox_iface_rand_test(sep_base_test):
    """TX FIFO push/STATUS/threshold + read-empty/write-full error + flush."""

    async def _check_status(self, where: str) -> None:
        st = await self.mb.rd_csr(STATUS)
        g = self.gold.status()
        got = {
            "full": bool(st & ST_FULL),
            "wlvl_above": bool(st & ST_WLVL_ABOVE),
            "empty": bool(st & ST_EMPTY),
            "rlvl_above": bool(st & ST_RLVL_ABOVE),
        }
        assert got == g, (
            f"[{where}] STATUS {got} != golden {g} "
            f"(tx={self.gold.tx} wirqt={self.gold.wirqt} STATUS=0x{st:08x})"
        )

    async def _check_wtirq(self, where: str) -> None:
        irqs = await self.mb.rd_csr(IRQS)
        assert bool(irqs & IRQ_WTIRQ) == self.gold.wtirq(), (
            f"[{where}] IRQS.wtirq={bool(irqs & IRQ_WTIRQ)} but golden expects "
            f"{self.gold.wtirq()} at tx={self.gold.tx} wirqt={self.gold.wirqt} "
            f"(IRQS=0x{irqs:08x})"
        )

    async def run_scenario(self) -> None:
        self.cfg_mb = SepMboxCfg(self.random_seed())
        self.gold = SepMboxGolden(self.cfg_mb)
        self.logger.info("mailbox config: %s", self.cfg_mb.summary())

        await self.bring_up_no_cpu()
        self.mb = SepMbox(self)
        await self.mb.ungate_clock()
        # Program WIRQT up front so the golden's predicted write_level_above matches
        # the DUT throughout (reset WIRQT=0 would make any non-empty level "above").
        await self.mb.wr_csr(WIRQT, self.cfg_mb.wirqt)

        # CHK-NONVAC: empty TX + empty RX at reset.
        await self._check_status("reset")
        self.logger.info("CHK-NONVAC PASS: empty FIFOs reflected in STATUS (not stuck)")

        await self._chk_write_data_readback()
        await self._chk_read_empty_error()
        await self._chk_64b_status_threshold()
        await self._chk_write_full_error()
        await self._chk_flush()
        # No CHK-ALL summary: it asserted nothing, and every facet above already
        # logs its own PASS line. A plan row keyed on a bare summary string would
        # record coverage with no checker behind it.

    async def _chk_write_data_readback(self) -> None:
        """CHK-WDATA-RD: WRITE_DATA is push-only. A read of it returns the
        0xFEEDC0DE constant with OKAY -- not a FIFO entry, not SLVERR -- and does
        not disturb the TX occupancy."""
        resp, data = await self.mb.rd_write_data()
        assert resp == RESP_OKAY, f"WRITE_DATA read resp={resp}, expected OKAY"
        assert (data & 0xFFFF_FFFF) == WRITE_DATA_RD_SENTINEL, (
            f"WRITE_DATA read data=0x{data:016x}, expected constant 0x{WRITE_DATA_RD_SENTINEL:08x}"
        )
        await self._check_status("after-wdata-read")
        self.logger.info(
            "CHK-WDATA-RD PASS: WRITE_DATA reads 0x%08x + OKAY, TX occupancy unchanged",
            WRITE_DATA_RD_SENTINEL,
        )

    async def _chk_read_empty_error(self) -> None:
        """CHK-ERR-RD: READ_DATA on the empty RX FIFO -> 0xFEEDDEAD + SLVERR +
        ERROR_FLAGS.read_error (read-clear) + IRQS.eirq (W1C)."""
        resp, data = await self.mb.pop64(expect_error=True)
        assert resp == RESP_SLVERR, f"read-from-empty resp={resp}, expected SLVERR"
        assert (data & 0xFFFF_FFFF) == READ_EMPTY_SENTINEL, (
            f"read-from-empty data=0x{data:016x}, expected sentinel 0x{READ_EMPTY_SENTINEL:08x}"
        )
        err = await self.mb.rd_csr(ERROR_FLAGS)  # read-clear
        assert err & ERR_READ, f"ERROR_FLAGS.read_error not set after read-empty (0x{err:08x})"
        err2 = await self.mb.rd_csr(ERROR_FLAGS)  # read again -> cleared
        assert (err2 & ERR_READ) == 0, f"ERROR_FLAGS.read_error not read-cleared (0x{err2:08x})"
        assert (err2 & ERR_WRITE) == 0, (
            f"ERROR_FLAGS.write_error set with no write to a full FIFO (0x{err2:08x})"
        )
        self.logger.info(
            "CHK-ERR-RD PASS: read-empty -> SLVERR + 0xFEEDDEAD + ERROR_FLAGS.read_error (read-clear)"
        )
        irqs = await self.mb.rd_csr(IRQS)
        assert irqs & IRQ_EIRQ, f"IRQS.eirq not set after read-empty (0x{irqs:08x})"
        await self.mb.wr_csr(IRQS, IRQ_EIRQ)  # W1C
        irqs2 = await self.mb.rd_csr(IRQS)
        assert (irqs2 & IRQ_EIRQ) == 0, f"IRQS.eirq not W1C-cleared (0x{irqs2:08x})"
        self.logger.info("CHK-ERR-IRQ PASS: read-empty -> IRQS.eirq set + W1C -> 0")

    async def _chk_64b_status_threshold(self) -> None:
        """CHK-64B + CHK-STATUS + CHK-WIRQT: push 64-bit entries, STATUS tracks the
        golden TX depth, write-threshold IRQ fires when tx>WIRQT (IRQP gated).

        Each WRITE_DATA access is a single native 64-bit beat (the CPU-LSU path is
        64-bit). The exact 64-bit value is carried per push and the FIFO fills 1
        entry per beat, proving the 64-bit WRITE_DATA data path."""
        await self.mb.wr_csr(IRQEN, IRQ_WTIRQ)
        # tx=0 here, so the golden expects wtirq clear. The per-push compare
        # below then grades the clear side at every tx <= WIRQT and the set
        # side from the first push above it.
        await self._check_wtirq("pre-push")
        # Phase 1 -- push a RANDOM first batch (seeded message length) that crosses WIRQT,
        # with RANDOM 64-bit payloads. STATUS tracks the golden TX depth after each push.
        for i in range(self.cfg_mb.first_batch):
            assert await self.mb.push64(self.cfg_mb.payloads[i]) == RESP_OKAY
            # Advance the model. Not asserted: gold.push() only returns False when the
            # model is already full, which a range(first_batch < depth) loop cannot
            # reach, so asserting it tests the model's arithmetic rather than the DUT.
            # _check_status below is what compares the model against the DUT.
            self.gold.push()
            await self._check_status("push64")
            await self._check_wtirq("push64")
        # CHK-WIRQT: tx = first_batch > WIRQT -> wtirq set; IRQP gated by IRQEN; level-held.
        irqs = await self.mb.rd_csr(IRQS)
        # SepMboxCfg draws first_batch from [wirqt+1, depth], so tx > wirqt holds for
        # every seed at this point and this leg grades the SET direction against the
        # model. The CLEAR direction is graded in _chk_flush, where the flush drops tx
        # to 0 and wtirq must W1C to zero.
        assert bool(irqs & IRQ_WTIRQ) == self.gold.wtirq(), (
            f"IRQS.wtirq={bool(irqs & IRQ_WTIRQ)} but golden expects "
            f"{self.gold.wtirq()} at tx={self.gold.tx} wirqt={self.gold.wirqt} "
            f"(IRQS=0x{irqs:08x})"
        )
        irqp = await self.mb.rd_csr(IRQP)
        assert irqp & IRQ_WTIRQ, f"IRQP.wtirq not gated-set by IRQEN+IRQS (0x{irqp:08x})"
        await self.mb.wr_csr(IRQEN, 0)
        irqp_masked = await self.mb.rd_csr(IRQP)
        irqs_held = await self.mb.rd_csr(IRQS)
        assert (irqp_masked & IRQ_WTIRQ) == 0, (
            f"IRQP.wtirq stayed set with IRQEN=0 (IRQP=0x{irqp_masked:08x}) -- pending "
            f"mirrors status rather than being gated by enable"
        )
        assert irqs_held & IRQ_WTIRQ, (
            f"IRQS.wtirq dropped when IRQEN was cleared (0x{irqs_held:08x})"
        )
        await self.mb.wr_csr(IRQEN, IRQ_WTIRQ)
        await self.mb.wr_csr(IRQS, IRQ_WTIRQ)  # W1C while still above
        reassert = await self.mb.rd_csr(IRQS)
        assert reassert & IRQ_WTIRQ, "wtirq should re-assert after W1C while still above threshold"
        self.logger.info(
            "CHK-WIRQT PASS: write-threshold IRQ set (tx=%d>%d), IRQP gated by IRQEN "
            "(drops when enable is cleared, IRQS stays), level-held re-assert",
            self.gold.tx,
            self.gold.wirqt,
        )
        # Phase 2 -- top up to full.
        for i in range(self.cfg_mb.first_batch, self.cfg_mb.depth):
            assert await self.mb.push64(self.cfg_mb.payloads[i]) == RESP_OKAY
            self.gold.push()
            await self._check_status("push64-fill")
        st = await self.mb.rd_csr(STATUS)
        assert st & ST_FULL, (
            f"TX FIFO not full after {self.cfg_mb.depth} pushes (STATUS=0x{st:08x})"
        )
        self.logger.info(
            "CHK-64B PASS: %d native 64-bit WRITE_DATA pushes (random data, first batch=%d) "
            "-> exactly full (1 entry/beat)",
            self.cfg_mb.depth,
            self.cfg_mb.first_batch,
        )
        # No separate CHK-STATUS line: the STATUS comparison is _check_status, called
        # after every push above, and a bare summary log with no assert behind it reads
        # as a checker in a plan while enforcing nothing.

    async def _chk_write_full_error(self) -> None:
        """CHK-ERR-WR: a push to the full TX FIFO -> SLVERR +
        ERROR_FLAGS.write_error + IRQS.eirq W1C.

        write_error and eirq are both read 0 before the overflow push, so the
        set seen after it is caused by that push."""
        pre_err = await self.mb.rd_csr(ERROR_FLAGS)
        assert (pre_err & ERR_WRITE) == 0, (
            f"ERROR_FLAGS.write_error already set before the write-to-full (0x{pre_err:08x})"
        )
        pre_irqs = await self.mb.rd_csr(IRQS)
        assert (pre_irqs & IRQ_EIRQ) == 0, (
            f"IRQS.eirq already set before the write-to-full (0x{pre_irqs:08x})"
        )
        resp = await self.mb.push64(self.cfg_mb.payloads[self.cfg_mb.depth], expect_error=True)
        assert resp == RESP_SLVERR, f"write-to-full resp={resp}, expected SLVERR"
        err = await self.mb.rd_csr(ERROR_FLAGS)
        assert err & ERR_WRITE, f"ERROR_FLAGS.write_error not set after write-full (0x{err:08x})"
        self.logger.info("CHK-ERR-WR PASS: write-to-full -> SLVERR + ERROR_FLAGS.write_error")
        irqs = await self.mb.rd_csr(IRQS)
        assert irqs & IRQ_EIRQ, f"IRQS.eirq not set after write-full (0x{irqs:08x})"
        await self.mb.wr_csr(IRQS, IRQ_EIRQ)  # W1C
        irqs2 = await self.mb.rd_csr(IRQS)
        assert (irqs2 & IRQ_EIRQ) == 0, f"write-full IRQS.eirq not W1C-cleared (0x{irqs2:08x})"
        self.logger.info("CHK-ERR-WR-IRQ PASS: write-full -> IRQS.eirq set + W1C -> 0")

    async def _chk_flush(self) -> None:
        """CHK-FLUSH: CTRL.wflush drains the TX FIFO -> STATUS not-full; then the
        level-held wtirq W1C-clears to 0 (tx now below threshold)."""
        await self.mb.flush_write()
        self.gold.flush()
        await self._check_status("after-flush")
        await self.mb.wr_csr(IRQS, IRQ_WTIRQ)  # W1C, now tx=0<=wirqt
        irqs = await self.mb.rd_csr(IRQS)
        assert (irqs & IRQ_WTIRQ) == 0, f"wtirq not cleared by W1C after flush (0x{irqs:08x})"
        self.logger.info("CHK-FLUSH PASS: CTRL.wflush drained TX -> not-full + wtirq W1C -> 0")
