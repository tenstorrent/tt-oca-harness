# SPDX-License-Identifier: Apache-2.0
"""axil_mailbox interface breadth (randomized-rep, TX path).

no_cpu host-AXI test of the SEP axil_mailbox MECHANICS over the CPU-LSU master,
on the outbound_mailbox_0 aperture (0x10A0_0000) -- the SEP/CPU side of the
two-port cross-FIFO, reachable with NO inbound filter. This is the TX-path test,
matching OCAH's "CPU not running -> RX FIFO always empty; verify the TX path"
intent. Distinct from the outbound->PIC->CPU delivery path
(sep_mailbox_plic_test).

A SepMboxCfg config object (seeded WIRQT + payloads) is the single source of truth
for DUT programming and the golden depth model (env/sep_mbox_golden.py), which
predicts the visible STATUS bits + the write-threshold IRQ from the TX occupancy
(STATUS has no exact-depth field). Thresholds compare with strict > (RTL). Seed is
logged; regression mode can sweep this via TOML ``reseed = N``.

OCAH refs: fabric sep_mailbox_64bit_data_test, sep_mailbox_misc_regs_test,
sep_fabric_mailbox_fifo_closure_test
@ 9ec8f9f4b. Mapping: MERGED_INTO (one rep subsumes the TX FIFO/IRQ/error/flush family).
RUN-MODE: no_cpu (CPU-LSU master). FUSE-MODE: +skip_fuse_sense (the local mailbox has
no OTP/LC dependency).

ACCEPTED DELTAS: (1) data round-trip readback and (2) read-threshold (RIRQT) need the
RX FIFO filled from the peer side. A clean VCS repro proved the external smn_inbound
frontdoor can fill inbound_mailbox_0 at 0x10A0_0800 and the CPU-LSU side can pop that
value from outbound_mailbox_0. This rep intentionally stays TX-focused because the
OCAH mailbox data test it ports is TX-focused; the external-inbound closure belongs
in a separate fabric/mailbox peer-path testcase if we keep it permanently.
"""

from __future__ import annotations

import pyuvm

from sep_base_test import sep_base_test
from seq_lib.sep_mailbox_iface_seq import SepMbox
from env.sep_mbox_golden import (
    SepMboxCfg, SepMboxGolden,
    STATUS, ERROR_FLAGS, WIRQT, IRQS, IRQEN, IRQP, CTRL,
    ST_EMPTY, ST_FULL, ST_WLVL_ABOVE, ST_RLVL_ABOVE,
    IRQ_WTIRQ, IRQ_EIRQ, ERR_READ, ERR_WRITE,
    READ_EMPTY_SENTINEL, RESP_OKAY, RESP_SLVERR,
)


@pyuvm.test()
class sep_axil_mailbox_iface_rand_test(sep_base_test):
    """TX FIFO push/STATUS/threshold + read-empty/write-full error + flush."""

    async def _check_status(self, where: str) -> None:
        st = await self.mb.rd_csr(STATUS)
        g = self.gold.status()
        got = {"full": bool(st & ST_FULL), "wlvl_above": bool(st & ST_WLVL_ABOVE),
               "empty": bool(st & ST_EMPTY), "rlvl_above": bool(st & ST_RLVL_ABOVE)}
        assert got == g, (
            f"[{where}] STATUS {got} != golden {g} "
            f"(tx={self.gold.tx} wirqt={self.gold.wirqt} STATUS=0x{st:08x})"
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

        await self._chk_read_empty_error()
        await self._chk_64b_status_threshold()
        await self._chk_write_full_error()
        await self._chk_flush()
        self.logger.info("CHK-ALL PASS: axil_mailbox TX 64b + STATUS + WIRQT + error + flush")

    async def _chk_read_empty_error(self) -> None:
        """CHK-ERR-RD: READ_DATA on the empty RX FIFO -> 0xFEEDDEAD + SLVERR +
        ERROR_FLAGS.read_error (read-clear) + IRQS.eirq (W1C)."""
        resp, data = await self.mb.pop64(expect_error=True)
        assert resp == RESP_SLVERR, f"read-from-empty resp={resp}, expected SLVERR"
        assert (data & 0xFFFF_FFFF) == READ_EMPTY_SENTINEL, (
            f"read-from-empty data=0x{data:016x}, expected sentinel 0x{READ_EMPTY_SENTINEL:08x}"
        )
        err = await self.mb.rd_csr(ERROR_FLAGS)              # read-clear
        assert err & ERR_READ, f"ERROR_FLAGS.read_error not set after read-empty (0x{err:08x})"
        err2 = await self.mb.rd_csr(ERROR_FLAGS)             # read again -> cleared
        assert (err2 & ERR_READ) == 0, f"ERROR_FLAGS.read_error not read-cleared (0x{err2:08x})"
        self.logger.info(
            "CHK-ERR-RD PASS: read-empty -> SLVERR + 0xFEEDDEAD + ERROR_FLAGS.read_error (read-clear)"
        )
        irqs = await self.mb.rd_csr(IRQS)
        assert irqs & IRQ_EIRQ, f"IRQS.eirq not set after read-empty (0x{irqs:08x})"
        await self.mb.wr_csr(IRQS, IRQ_EIRQ)                 # W1C
        irqs2 = await self.mb.rd_csr(IRQS)
        assert (irqs2 & IRQ_EIRQ) == 0, f"IRQS.eirq not W1C-cleared (0x{irqs2:08x})"
        self.logger.info("CHK-ERR-IRQ PASS: read-empty -> IRQS.eirq set + W1C -> 0")

    async def _chk_64b_status_threshold(self) -> None:
        """CHK-64B + CHK-STATUS + CHK-WIRQT: push 64-bit entries, STATUS tracks the
        golden TX depth, write-threshold IRQ fires when tx>WIRQT (IRQP gated).

        Each WRITE_DATA access is a single native 64-bit beat (the CPU-LSU path is
        64-bit; a 32-bit sub-word write to WRITE_DATA+0x04 SLVERRs -- the 2x32->1x64
        combine exists only on the external 32-bit-downsized smn_inbound path, not
        here). The exact 64-bit value is carried per push and the FIFO fills 1 entry
        per beat, proving the 64-bit WRITE_DATA data path."""
        await self.mb.wr_csr(IRQEN, IRQ_WTIRQ)
        # Phase 1 -- push a RANDOM first batch (seeded message length) that crosses WIRQT,
        # with RANDOM 64-bit payloads. STATUS tracks the golden TX depth after each push.
        for i in range(self.cfg_mb.first_batch):
            assert await self.mb.push64(self.cfg_mb.payloads[i]) == RESP_OKAY
            assert self.gold.push()
            await self._check_status("push64")
        # CHK-WIRQT: tx = first_batch > WIRQT -> wtirq set; IRQP gated by IRQEN; level-held.
        irqs = await self.mb.rd_csr(IRQS)
        assert (irqs & IRQ_WTIRQ) and self.gold.wtirq(), (
            f"IRQS.wtirq not set at tx={self.gold.tx}>wirqt={self.gold.wirqt} (0x{irqs:08x})"
        )
        irqp = await self.mb.rd_csr(IRQP)
        assert irqp & IRQ_WTIRQ, f"IRQP.wtirq not gated-set by IRQEN+IRQS (0x{irqp:08x})"
        await self.mb.wr_csr(IRQS, IRQ_WTIRQ)                # W1C while still above
        reassert = await self.mb.rd_csr(IRQS)
        assert reassert & IRQ_WTIRQ, "wtirq should re-assert after W1C while still above threshold"
        self.logger.info(
            "CHK-WIRQT PASS: write-threshold IRQ set (tx=%d>%d), IRQP gated, level-held re-assert",
            self.gold.tx, self.gold.wirqt,
        )
        # Phase 2 -- top up to full.
        for i in range(self.cfg_mb.first_batch, self.cfg_mb.depth):
            assert await self.mb.push64(self.cfg_mb.payloads[i]) == RESP_OKAY
            assert self.gold.push()
            await self._check_status("push64-fill")
        st = await self.mb.rd_csr(STATUS)
        assert st & ST_FULL, f"TX FIFO not full after {self.cfg_mb.depth} pushes (STATUS=0x{st:08x})"
        self.logger.info(
            "CHK-64B PASS: %d native 64-bit WRITE_DATA pushes (random data, first batch=%d) "
            "-> exactly full (1 entry/beat)", self.cfg_mb.depth, self.cfg_mb.first_batch,
        )
        self.logger.info("CHK-STATUS PASS: full/write_level_above tracked golden TX depth")

    async def _chk_write_full_error(self) -> None:
        """CHK-ERR-WR: a push to the full TX FIFO -> SLVERR +
        ERROR_FLAGS.write_error + IRQS.eirq W1C."""
        assert self.gold.tx == self.cfg_mb.depth, "test bug: TX not full before write-full check"
        resp = await self.mb.push64(self.cfg_mb.payloads[self.cfg_mb.depth], expect_error=True)
        assert resp == RESP_SLVERR, f"write-to-full resp={resp}, expected SLVERR"
        assert not self.gold.push()                          # golden: push on full fails
        err = await self.mb.rd_csr(ERROR_FLAGS)
        assert err & ERR_WRITE, f"ERROR_FLAGS.write_error not set after write-full (0x{err:08x})"
        self.logger.info("CHK-ERR-WR PASS: write-to-full -> SLVERR + ERROR_FLAGS.write_error")
        irqs = await self.mb.rd_csr(IRQS)
        assert irqs & IRQ_EIRQ, f"IRQS.eirq not set after write-full (0x{irqs:08x})"
        await self.mb.wr_csr(IRQS, IRQ_EIRQ)                 # W1C
        irqs2 = await self.mb.rd_csr(IRQS)
        assert (irqs2 & IRQ_EIRQ) == 0, f"write-full IRQS.eirq not W1C-cleared (0x{irqs2:08x})"
        self.logger.info("CHK-ERR-WR-IRQ PASS: write-full -> IRQS.eirq set + W1C -> 0")

    async def _chk_flush(self) -> None:
        """CHK-FLUSH: CTRL.wflush drains the TX FIFO -> STATUS not-full; then the
        level-held wtirq W1C-clears to 0 (tx now below threshold)."""
        await self.mb.flush_write()
        self.gold.flush()
        await self._check_status("after-flush")
        await self.mb.wr_csr(IRQS, IRQ_WTIRQ)                # W1C, now tx=0<=wirqt
        irqs = await self.mb.rd_csr(IRQS)
        assert (irqs & IRQ_WTIRQ) == 0, f"wtirq not cleared by W1C after flush (0x{irqs:08x})"
        self.logger.info("CHK-FLUSH PASS: CTRL.wflush drained TX -> not-full + wtirq W1C -> 0")
