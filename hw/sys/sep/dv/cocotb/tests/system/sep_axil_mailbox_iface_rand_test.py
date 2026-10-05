# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""axil_mailbox TX: STATUS and WIRQT follow the depth golden; read-empty and write-full give SLVERR.

no_cpu host-AXI test of the SEP axil_mailbox mechanics over the CPU-LSU master,
on the outbound_mailbox_0 aperture (0x10A0_0000) -- the SEP/CPU side of the
two-port cross-FIFO, reachable with no inbound filter. This is the TX-path test:
with no CPU running the RX FIFO is always empty. Flush must drain the FIFO.
Distinct from the inbound-mailbox -> PIC -> CPU delivery path (sep_mailbox_plic_test).

A SepMboxCfg config object (seeded WIRQT + payloads) is the single source of truth
for DUT programming and the golden depth model (env/sep_mbox_golden.py), which
predicts the visible STATUS bits + the write-threshold IRQ from the TX occupancy
(STATUS has no exact-depth field). Thresholds compare with strict greater-than
(``hw/ip/axi_lite_mailbox_unit/doc/architecture.adoc``: occupancy strictly greater
than the threshold). Seed is logged; regression mode can sweep this via TOML
``reseed = N``.

Every run executes the whole rep twice, once with a WIRQT from the low half of
[1, depth-1] and once from the high half (``SepMboxCfg.per_half``). The seed
picks the two thresholds, their order, the fill lengths and the payloads, so
both halves of the threshold range are graded on every seed. Each rep starts
from the drained, error-free state the previous rep's flush leaves.

Every assert names the checker it grades. A STATUS compare names CHK-WIRQT
when ``write_level_above`` differs from the golden and the occupancy checker
of its step when ``full`` or ``empty`` differs, so a threshold fault in one
half of the range fails CHK-WIRQT by name. Each PASS line logs the register
values it read.

OCAH tests: sep_mailbox_64bit_data_test, sep_mailbox_misc_regs_test,
sep_fabric_mailbox_fifo_closure_test (one rep covers the TX FIFO/IRQ/error/flush family).
Run mode: no_cpu (CPU-LSU master) with +skip_fuse_sense (the local mailbox has
no OTP/LC dependency).

Not covered here: (1) data round-trip readback and (2) read-threshold (RIRQT) need the
RX FIFO filled from the peer side, which this aperture cannot do, so the read half of
the threshold pair has no vehicle on this master. The rep is TX-only, like the
OCAH tests it ports; the peer path is reachable only from the external
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
    """STATUS and WIRQT track the golden, error pushes and pops give SLVERR, and flush drains."""

    required_evidence = (
        "CHK-NONVAC",
        "CHK-WDATA-RD",
        "CHK-ERR-RD",
        "CHK-ERR-IRQ",
        "CHK-WIRQT",
        "CHK-64B",
        "CHK-ERR-WR",
        "CHK-ERR-WR-IRQ",
        "CHK-FLUSH",
    )

    def _ctx(self) -> str:
        return f"{self.cfg_mb.half} half, tx={self.gold.tx} wirqt={self.gold.wirqt}"

    async def _check_status(self, where: str, chk: str) -> int:
        """STATUS against the golden, field by field. ``chk`` owns the
        occupancy fields; ``write_level_above`` belongs to CHK-WIRQT."""
        st = await self.mb.rd_csr(STATUS)
        g = self.gold.status()
        got = {
            "full": bool(st & ST_FULL),
            "wlvl_above": bool(st & ST_WLVL_ABOVE),
            "empty": bool(st & ST_EMPTY),
            "rlvl_above": bool(st & ST_RLVL_ABOVE),
        }
        bad = {k: (got[k], g[k]) for k in g if got[k] != g[k]}
        owners = sorted({"CHK-WIRQT" if k == "wlvl_above" else chk for k in bad})
        assert not bad, (
            f"{' / '.join(owners)} FAIL: [{where}] STATUS=0x{st:08x} differs from the "
            f"golden (field: (DUT, golden)) {bad} ({self._ctx()})"
        )
        return st

    async def _check_wtirq(self, where: str) -> int:
        irqs = await self.mb.rd_csr(IRQS)
        assert bool(irqs & IRQ_WTIRQ) == self.gold.wtirq(), (
            f"CHK-WIRQT FAIL: [{where}] IRQS=0x{irqs:08x} wtirq={bool(irqs & IRQ_WTIRQ)}, "
            f"golden expects {self.gold.wtirq()} ({self._ctx()})"
        )
        return irqs

    async def run_scenario(self) -> None:
        cfgs = SepMboxCfg.per_half(self.random_seed())
        for i, cfg in enumerate(cfgs):
            self.logger.info("mailbox config rep %d/%d: %s", i + 1, len(cfgs), cfg.summary())

        await self.bring_up_no_cpu()
        self.mb = SepMbox(self)
        await self.mb.ungate_clock()

        for i, cfg in enumerate(cfgs):
            self.cfg_mb = cfg
            self.gold = SepMboxGolden(cfg)
            self.logger.info(
                "rep %d/%d: WIRQT=%d from the %s half", i + 1, len(cfgs), cfg.wirqt, cfg.half
            )
            await self._rep()

    async def _rep(self) -> None:
        # Program WIRQT up front so the golden's predicted write_level_above matches
        # the DUT throughout (reset WIRQT=0 would make any non-empty level "above").
        await self.mb.wr_csr(WIRQT, self.cfg_mb.wirqt)

        # CHK-NONVAC: empty TX + empty RX, at reset on the first rep and after
        # the previous rep's flush on the second.
        st = await self._check_status("rep-start", "CHK-NONVAC")
        self.logger.info(
            "CHK-NONVAC PASS: STATUS=0x%08x (empty=%d full=%d wlvl_above=%d "
            "rlvl_above=%d) equals the golden for empty FIFOs (%s)",
            st,
            bool(st & ST_EMPTY),
            bool(st & ST_FULL),
            bool(st & ST_WLVL_ABOVE),
            bool(st & ST_RLVL_ABOVE),
            self._ctx(),
        )

        await self._chk_write_data_readback()
        await self._chk_read_empty_error()
        await self._chk_64b_status_threshold()
        await self._chk_write_full_error()
        await self._chk_flush()

    async def _chk_write_data_readback(self) -> None:
        """CHK-WDATA-RD: WRITE_DATA is push-only. A read of it returns the
        0xFEEDC0DE constant with OKAY -- not a FIFO entry, not SLVERR -- and does
        not disturb the TX occupancy."""
        resp, data = await self.mb.rd_write_data()
        assert resp == RESP_OKAY, f"CHK-WDATA-RD FAIL: WRITE_DATA read resp={resp}, expected OKAY"
        assert (data & 0xFFFF_FFFF) == WRITE_DATA_RD_SENTINEL, (
            f"CHK-WDATA-RD FAIL: WRITE_DATA read data=0x{data:016x}, expected constant "
            f"0x{WRITE_DATA_RD_SENTINEL:08x}"
        )
        st = await self._check_status("after-wdata-read", "CHK-WDATA-RD")
        self.logger.info(
            "CHK-WDATA-RD PASS: WRITE_DATA read returned data=0x%016x resp=%d "
            "(expected 0x%08x, OKAY); STATUS=0x%08x after it equals the golden (%s)",
            data,
            resp,
            WRITE_DATA_RD_SENTINEL,
            st,
            self._ctx(),
        )

    async def _chk_read_empty_error(self) -> None:
        """CHK-ERR-RD: READ_DATA on the empty RX FIFO -> 0xFEEDDEAD + SLVERR +
        ERROR_FLAGS.read_error (read-clear) + IRQS.eirq (W1C).

        read_error and eirq are both read 0 after the WRITE_DATA read and
        before the read-empty access, so the set seen after it is caused by
        that access, not by reset or by the WRITE_DATA read."""
        pre_err = await self.mb.rd_csr(ERROR_FLAGS)  # read-clear
        assert (pre_err & ERR_READ) == 0, (
            f"CHK-ERR-RD FAIL: ERROR_FLAGS=0x{pre_err:08x}: read_error already set before "
            f"the read-empty access ({self._ctx()})"
        )
        pre_irqs = await self.mb.rd_csr(IRQS)
        assert (pre_irqs & IRQ_EIRQ) == 0, (
            f"CHK-ERR-IRQ FAIL: IRQS=0x{pre_irqs:08x}: eirq already set before the "
            f"read-empty access ({self._ctx()})"
        )
        resp, data = await self.mb.pop64(expect_error=True)
        assert resp == RESP_SLVERR, f"CHK-ERR-RD FAIL: read-from-empty resp={resp}, expected SLVERR"
        assert (data & 0xFFFF_FFFF) == READ_EMPTY_SENTINEL, (
            f"CHK-ERR-RD FAIL: read-from-empty data=0x{data:016x}, expected sentinel "
            f"0x{READ_EMPTY_SENTINEL:08x}"
        )
        err = await self.mb.rd_csr(ERROR_FLAGS)  # read-clear
        assert err & ERR_READ, (
            f"CHK-ERR-RD FAIL: ERROR_FLAGS.read_error not set after read-empty (0x{err:08x})"
        )
        err2 = await self.mb.rd_csr(ERROR_FLAGS)  # read again -> cleared
        assert (err2 & ERR_READ) == 0, (
            f"CHK-ERR-RD FAIL: ERROR_FLAGS.read_error not read-cleared (0x{err2:08x})"
        )
        assert (err2 & ERR_WRITE) == 0, (
            f"CHK-ERR-RD FAIL: ERROR_FLAGS.write_error set with no write to a full FIFO "
            f"(0x{err2:08x})"
        )
        self.logger.info(
            "CHK-ERR-RD PASS: ERROR_FLAGS=0x%08x before; read-empty answered resp=%d "
            "data=0x%016x (expected SLVERR, 0x%08x); ERROR_FLAGS=0x%08x after, "
            "0x%08x on the second read (read-clear)",
            pre_err,
            resp,
            data,
            READ_EMPTY_SENTINEL,
            err,
            err2,
        )
        irqs = await self.mb.rd_csr(IRQS)
        assert irqs & IRQ_EIRQ, (
            f"CHK-ERR-IRQ FAIL: IRQS.eirq not set after read-empty (0x{irqs:08x})"
        )
        await self.mb.wr_csr(IRQS, IRQ_EIRQ)  # W1C
        irqs2 = await self.mb.rd_csr(IRQS)
        assert (irqs2 & IRQ_EIRQ) == 0, (
            f"CHK-ERR-IRQ FAIL: IRQS.eirq not W1C-cleared (0x{irqs2:08x})"
        )
        self.logger.info(
            "CHK-ERR-IRQ PASS: IRQS=0x%08x before read-empty, 0x%08x after (eirq set), "
            "0x%08x after the eirq W1C",
            pre_irqs,
            irqs,
            irqs2,
        )

    async def _chk_64b_status_threshold(self) -> None:
        """CHK-64B + CHK-WIRQT: push 64-bit entries; STATUS matches the golden TX
        depth after every push (graded under CHK-64B); the write-threshold IRQ fires
        when tx>WIRQT (IRQP gated).

        Each WRITE_DATA access is a single native 64-bit beat (the CPU-LSU path is
        64-bit). The exact 64-bit value is carried per push and the FIFO fills 1
        entry per beat, proving the 64-bit WRITE_DATA data path."""
        await self.mb.wr_csr(IRQEN, IRQ_WTIRQ)
        # tx=0 here, so the golden expects wtirq clear. The per-push compare
        # below then grades the clear side at every tx <= WIRQT and the set
        # side from the first push above it.
        pre = await self._check_wtirq("pre-push")
        # Phase 1 -- push a RANDOM first batch (seeded message length) that crosses WIRQT,
        # with RANDOM 64-bit payloads. STATUS tracks the golden TX depth after each push.
        for i in range(self.cfg_mb.first_batch):
            rc = await self.mb.push64(self.cfg_mb.payloads[i])
            assert rc == RESP_OKAY, f"CHK-64B FAIL: push {i} answered resp={rc}, expected OKAY"
            # gold.push() returns False only when the model is already full, which
            # range(first_batch < depth) cannot reach; _check_status compares the model
            # against the DUT.
            self.gold.push()
            await self._check_status(f"push64 #{i + 1}", "CHK-64B")
            await self._check_wtirq(f"push64 #{i + 1}")
        # CHK-WIRQT: tx = first_batch > WIRQT -> wtirq set; IRQP gated by IRQEN; level-held.
        irqs = await self.mb.rd_csr(IRQS)
        # SepMboxCfg draws first_batch from [wirqt+1, depth], so tx > wirqt holds for
        # every seed at this point and this leg grades the SET direction against the
        # model. The CLEAR direction is graded in _chk_flush, where the flush drops tx
        # to 0 and wtirq must W1C to zero.
        assert bool(irqs & IRQ_WTIRQ) == self.gold.wtirq(), (
            f"CHK-WIRQT FAIL: IRQS=0x{irqs:08x} wtirq={bool(irqs & IRQ_WTIRQ)}, golden "
            f"expects {self.gold.wtirq()} ({self._ctx()})"
        )
        irqp = await self.mb.rd_csr(IRQP)
        assert irqp & IRQ_WTIRQ, (
            f"CHK-WIRQT FAIL: IRQP.wtirq not gated-set by IRQEN+IRQS (0x{irqp:08x})"
        )
        await self.mb.wr_csr(IRQEN, 0)
        irqp_masked = await self.mb.rd_csr(IRQP)
        irqs_held = await self.mb.rd_csr(IRQS)
        assert (irqp_masked & IRQ_WTIRQ) == 0, (
            f"CHK-WIRQT FAIL: IRQP.wtirq stayed set with IRQEN=0 (IRQP=0x{irqp_masked:08x}) -- pending "
            f"mirrors status rather than being gated by enable"
        )
        assert irqs_held & IRQ_WTIRQ, (
            f"CHK-WIRQT FAIL: IRQS.wtirq dropped when IRQEN is cleared (0x{irqs_held:08x})"
        )
        await self.mb.wr_csr(IRQEN, IRQ_WTIRQ)
        await self.mb.wr_csr(IRQS, IRQ_WTIRQ)  # W1C while still above
        reassert = await self.mb.rd_csr(IRQS)
        assert reassert & IRQ_WTIRQ, (
            f"CHK-WIRQT FAIL: IRQS=0x{reassert:08x}: wtirq did not re-assert after W1C "
            f"while still above threshold ({self._ctx()})"
        )
        self.logger.info(
            "CHK-WIRQT PASS: write-threshold IRQ set (tx=%d>%d, %s half); STATUS and "
            "IRQS.wtirq matched the golden at every first-batch push from IRQS=0x%08x "
            "at tx=0; "
            "IRQS=0x%08x IRQP=0x%08x with IRQEN set, IRQP=0x%08x IRQS=0x%08x with "
            "IRQEN clear, IRQS=0x%08x after W1C while above (level-held re-assert)",
            self.gold.tx,
            self.gold.wirqt,
            self.cfg_mb.half,
            pre,
            irqs,
            irqp,
            irqp_masked,
            irqs_held,
            reassert,
        )
        # Phase 2 -- top up to full. Every top-up push stays above WIRQT, so the
        # golden expects IRQS.wtirq set at each one: the W1C above must not leave
        # it clear, and the bit must not drop as the FIFO fills.
        fill_irqs = reassert
        for i in range(self.cfg_mb.first_batch, self.cfg_mb.depth):
            rc = await self.mb.push64(self.cfg_mb.payloads[i])
            assert rc == RESP_OKAY, f"CHK-64B FAIL: push {i} answered resp={rc}, expected OKAY"
            self.gold.push()
            await self._check_status(f"push64-fill #{i + 1}", "CHK-64B")
            fill_irqs = await self._check_wtirq(f"push64-fill #{i + 1}")
        self.logger.info(
            "CHK-WIRQT PASS: IRQS.wtirq matched the golden after each of the %d "
            "top-up pushes from tx=%d to full (depth=%d, wirqt=%d, %s half); "
            "IRQS=0x%08x at tx=%d",
            self.cfg_mb.depth - self.cfg_mb.first_batch,
            self.cfg_mb.first_batch,
            self.cfg_mb.depth,
            self.gold.wirqt,
            self.cfg_mb.half,
            fill_irqs,
            self.gold.tx,
        )
        st = await self.mb.rd_csr(STATUS)
        assert st & ST_FULL, (
            f"CHK-64B FAIL: TX FIFO not full after {self.cfg_mb.depth} pushes (STATUS=0x{st:08x})"
        )
        self.logger.info(
            "CHK-64B PASS: %d native 64-bit WRITE_DATA pushes (random data, first batch=%d) "
            "-> exactly full (1 entry/beat); STATUS=0x%08x after the last push, and "
            "STATUS equal to the golden after each push",
            self.cfg_mb.depth,
            self.cfg_mb.first_batch,
            st,
        )

    async def _chk_write_full_error(self) -> None:
        """CHK-ERR-WR: a push to the full TX FIFO -> SLVERR +
        ERROR_FLAGS.write_error + IRQS.eirq W1C.

        write_error and eirq are both read 0 before the overflow push, so the
        set seen after it is caused by that push."""
        pre_err = await self.mb.rd_csr(ERROR_FLAGS)
        assert (pre_err & ERR_WRITE) == 0, (
            f"CHK-ERR-WR FAIL: ERROR_FLAGS.write_error already set before the write-to-full (0x{pre_err:08x})"
        )
        pre_irqs = await self.mb.rd_csr(IRQS)
        assert (pre_irqs & IRQ_EIRQ) == 0, (
            f"CHK-ERR-WR-IRQ FAIL: IRQS.eirq already set before the write-to-full (0x{pre_irqs:08x})"
        )
        resp = await self.mb.push64(self.cfg_mb.payloads[self.cfg_mb.depth], expect_error=True)
        assert resp == RESP_SLVERR, f"CHK-ERR-WR FAIL: write-to-full resp={resp}, expected SLVERR"
        err = await self.mb.rd_csr(ERROR_FLAGS)
        assert err & ERR_WRITE, (
            f"CHK-ERR-WR FAIL: ERROR_FLAGS.write_error not set after write-full (0x{err:08x})"
        )
        self.logger.info(
            "CHK-ERR-WR PASS: ERROR_FLAGS=0x%08x before; write-to-full answered resp=%d "
            "(expected SLVERR); ERROR_FLAGS=0x%08x after (write_error set)",
            pre_err,
            resp,
            err,
        )
        irqs = await self.mb.rd_csr(IRQS)
        assert irqs & IRQ_EIRQ, (
            f"CHK-ERR-WR-IRQ FAIL: IRQS.eirq not set after write-full (0x{irqs:08x})"
        )
        await self.mb.wr_csr(IRQS, IRQ_EIRQ)  # W1C
        irqs2 = await self.mb.rd_csr(IRQS)
        assert (irqs2 & IRQ_EIRQ) == 0, (
            f"CHK-ERR-WR-IRQ FAIL: write-full IRQS.eirq not W1C-cleared (0x{irqs2:08x})"
        )
        self.logger.info(
            "CHK-ERR-WR-IRQ PASS: IRQS=0x%08x before write-to-full, 0x%08x after (eirq "
            "set), 0x%08x after the eirq W1C",
            pre_irqs,
            irqs,
            irqs2,
        )

    async def _chk_flush(self) -> None:
        """CHK-FLUSH: CTRL.wflush drains the TX FIFO -> STATUS not-full; then the
        level-held wtirq W1C-clears to 0 (tx now below threshold)."""
        await self.mb.flush_write()
        self.gold.flush()
        st = await self._check_status("after-flush", "CHK-FLUSH")
        await self.mb.wr_csr(IRQS, IRQ_WTIRQ)  # W1C, now tx=0<=wirqt
        irqs = await self.mb.rd_csr(IRQS)
        assert (irqs & IRQ_WTIRQ) == 0, (
            f"CHK-FLUSH FAIL: wtirq not cleared by W1C after flush (0x{irqs:08x})"
        )
        self.logger.info(
            "CHK-FLUSH PASS: after CTRL.wflush STATUS=0x%08x (full=%d empty=%d) equals "
            "the golden, IRQS=0x%08x after the wtirq W1C",
            st,
            bool(st & ST_FULL),
            bool(st & ST_EMPTY),
            irqs,
        )
