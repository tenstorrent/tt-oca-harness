# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""axil_mailbox peer-RX path: data round trip, pop-per-read, and the read threshold.

``sep_axil_mailbox_iface_rand_test`` drives the SEP-host aperture
(outbound_mailbox_0 @ 0x10A0_0000) and proves the TX half. It cannot fill the
receive FIFO. This test grades the three contracts that need a filled FIFO: a
data round-trip readback, the read threshold (``RIRQT`` /
``STATUS.read_level_above``), and the 32-bit-read-of-a-64-bit-entry behaviour
that ``hw/sys/sep/doc/mailbox.adoc`` specifies.

The receive side is fed from the peer aperture (inbound_mailbox_0 @ 0x10A0_0800),
which only the external SMN-inbound master reaches. The inbound filter blocks by
default, so an allow window over the peer aperture is programmed from the CPU-LSU
side first, exactly as the m_axi order sweep does.

``mailbox.adoc`` is the contract for the read half: registers sit on an 8-byte
stride and a register's low and high halves alias to the same register, so "a
read of READ_DATA at either half pops one FIFO entry. The mailbox drives the
whole entry; the CPU keeps the half selected by address bit 2 and discards the
other. Reading both halves consumes two entries." That last sentence is what
this test grades, and it is the opposite of the intuitive reading -- two 32-bit
reads do not reassemble one 64-bit entry, they consume two entries and lose the
high half of the first.

Run mode: no_cpu (CPU-LSU master) with the external SMN master and
+skip_fuse_sense (the mailbox has no OTP/LC dependency; the filter window is
programmed explicitly rather than inherited from a debug state).
"""

from __future__ import annotations

import pyuvm
from env.sep_axi_agent import SepAxiOp
from env.sep_mbox_golden import (
    ERR_READ,
    ERROR_FLAGS,
    IRQ_RTIRQ,
    IRQEN,
    IRQP,
    IRQS,
    OUTBOUND_BASE,
    READ_DATA,
    READ_EMPTY_SENTINEL,
    RESP_OKAY,
    RESP_SLVERR,
    RIRQT,
    ST_EMPTY,
    ST_RLVL_ABOVE,
    STATUS,
    WRITE_DATA,
)
from sep_base_test import sep_base_test
from sep_reg_meta import sym
from seq_lib.sep_axi_access_seq import SepAxiAccessSeq
from seq_lib.sep_inbound_filter_rule_seq import (
    RESP_DECERR,
    SepInboundFilter,
    SepInboundFilterCfg,
)
from seq_lib.sep_mailbox_iface_seq import SepMbox

INBOUND_BASE = sym("AXIL_MAILBOX_INBOUND_MAILBOX_0_REG_MAP_BASE_ADDR")
# The filter window spans the peer aperture up to the next block.
_MAILBOX_STRIDE = INBOUND_BASE - OUTBOUND_BASE

# Two distinct entries whose halves are all different, so a check can tell which
# half of which entry it got back. No half equals another half.
_E0 = 0xAAAA0001_BBBB0002
_E1 = 0xCCCC0003_DDDD0004


def _lo(v: int) -> int:
    return v & 0xFFFF_FFFF


def _hi(v: int) -> int:
    return (v >> 32) & 0xFFFF_FFFF


# Read threshold for the RIRQT leg, and a fill that clears it with room to spare.
_RIRQT = 2
_RIRQT_FILL = 4


@pyuvm.test()
class sep_mailbox_peer_rx_rirqt_test(sep_base_test):
    """Peer fills RX; host grades round trip, pop-per-read, high-half loss, RIRQT."""

    async def _peer_push64(self, value: int) -> int:
        """One 64-bit WRITE_DATA push on the peer aperture, external master."""
        seq = SepAxiAccessSeq(
            "mbox_peer_push64",
            op=SepAxiOp.WRITE,
            addr=INBOUND_BASE + WRITE_DATA,
            wdata=value,
            length=8,
            size=3,
            allow_unverified_write_resp=True,
        )
        await self.start_ext_seq(seq)
        return seq.resp_code

    async def _host_read_half(
        self, half_offset: int, *, expect_error: bool = False
    ) -> tuple[int, int]:
        """Issue one 4-byte READ_DATA beat on the host aperture.

        half_offset is 0 for the low half and 4 for the high half (address bit 2).
        expect_error declares the read-empty SLVERR to the bus scoreboard; the
        caller still asserts the code.
        """
        seq = SepAxiAccessSeq(
            "mbox_host_read_half",
            op=SepAxiOp.READ,
            addr=OUTBOUND_BASE + READ_DATA + half_offset,
            length=4,
            size=2,
            expect_error=expect_error,
        )
        await self.start_seq(seq)
        return seq.resp_code, (seq.rdata & 0xFFFF_FFFF)

    async def run_scenario(self) -> None:
        await self.bring_up_no_cpu()

        self.mb = SepMbox(self)
        await self.mb.ungate_clock()

        # The filter blocks by default, so the peer aperture needs an explicit
        # read+write window before the external master can reach WRITE_DATA.
        filt = SepInboundFilter(self)
        self._filt_rule = SepInboundFilterCfg(entry=0, allow_addr=INBOUND_BASE)
        rule = self._filt_rule
        await filt.program_rule(
            rule, read_allowed=True, write_allowed=True, end_addr=INBOUND_BASE + _MAILBOX_STRIDE - 1
        )
        self.logger.info(
            "inbound filter entry 0 allows peer mailbox 0x%08x..0x%08x r+w",
            INBOUND_BASE,
            INBOUND_BASE + _MAILBOX_STRIDE - 1,
        )

        # --- CHK-RX-EMPTY: the control ---------------------------------------
        # Every check below reads RX. If RX answered the same way whether or not
        # the peer wrote, none of them could fail. Establish that an unfilled RX
        # is visibly empty and errors on a read first.
        st = await self.mb.rd_csr(STATUS)
        assert st & ST_EMPTY, (
            f"CHK-RX-EMPTY FAIL: STATUS.empty clear before any peer write (STATUS=0x{st:08x})"
        )
        resp, data = await self._host_read_half(0, expect_error=True)
        assert resp == RESP_SLVERR and data == READ_EMPTY_SENTINEL, (
            "CHK-RX-EMPTY FAIL: read of an empty RX returned "
            f"resp={resp} data=0x{data:08x}, expected SLVERR and the empty "
            f"sentinel 0x{READ_EMPTY_SENTINEL:08x}"
        )
        # ERROR_FLAGS.read_error is read-clear: reading it both confirms the
        # empty read was flagged as an error and clears it for the legs below.
        err = await self.mb.rd_csr(ERROR_FLAGS)
        assert err & ERR_READ, (
            f"CHK-RX-EMPTY FAIL: ERROR_FLAGS.read_error not set after a read of an "
            f"empty RX (ERROR_FLAGS=0x{err:08x})"
        )
        err2 = await self.mb.rd_csr(ERROR_FLAGS)
        assert (err2 & ERR_READ) == 0, (
            f"CHK-RX-EMPTY FAIL: ERROR_FLAGS.read_error did not read-clear "
            f"(ERROR_FLAGS=0x{err2:08x})"
        )
        self.logger.info(
            "CHK-RX-EMPTY PASS: RX empty before the peer wrote; read returned SLVERR "
            "and sentinel 0x%08x, and set ERROR_FLAGS.read_error",
            READ_EMPTY_SENTINEL,
        )

        # --- Peer fills two entries -------------------------------------------
        for name, val in (("E0", _E0), ("E1", _E1)):
            rc = await self._peer_push64(val)
            assert rc == RESP_OKAY, (
                f"peer push of {name}=0x{val:016x} to the inbound aperture returned "
                f"resp={rc}, expected OKAY -- the allow window or the peer path is "
                "not working, and every check below would be vacuous"
            )
        st = await self.mb.rd_csr(STATUS)
        assert not (st & ST_EMPTY), (
            f"CHK-PEER-RX FAIL: STATUS.empty still set after two peer pushes "
            f"(STATUS=0x{st:08x}) -- nothing crossed into the receive FIFO"
        )
        self.logger.info("peer pushed E0=0x%016x and E1=0x%016x; RX non-empty", _E0, _E1)

        # --- CHK-PEER-RX: the data round trip ---------------------------------
        # First host read, low half. mailbox.adoc: the half is selected by address
        # bit 2, so this returns E0's low word.
        resp, got = await self._host_read_half(0)
        assert resp == RESP_OKAY, (
            f"CHK-PEER-RX FAIL: read of a non-empty RX returned resp={resp}, expected OKAY"
        )
        assert got == _lo(_E0), (
            f"CHK-PEER-RX FAIL: low-half read returned 0x{got:08x}, expected E0's low "
            f"word 0x{_lo(_E0):08x} (E0=0x{_E0:016x}). The peer wrote it, so a "
            "mismatch is a real round-trip failure, not an empty FIFO."
        )
        self.logger.info(
            "CHK-PEER-RX PASS: value written by the peer came back to the host "
            "(0x%08x == E0 low word)",
            got,
        )

        # --- CHK-HIGH-HALF-LOSS + CHK-POP-PER-READ ----------------------------
        # The single read above must have popped the WHOLE entry, so the next
        # read -- even at the high half -- sees E1, not E0's high word. A design
        # that packed two 32-bit reads into one entry would return E0's high word
        # here, and a design that did not pop would return E0's low word again.
        resp, got = await self._host_read_half(4)
        assert resp == RESP_OKAY, (
            f"CHK-HIGH-HALF-LOSS FAIL: second read returned resp={resp}, expected OKAY"
        )
        assert got != _hi(_E0), (
            f"CHK-HIGH-HALF-LOSS FAIL: high-half read returned E0's high word "
            f"0x{got:08x}. mailbox.adoc says reading both halves consumes two "
            "entries and the discarded half is lost; this DUT reassembled one "
            "64-bit entry from two 32-bit reads instead."
        )
        assert got == _hi(_E1), (
            f"CHK-POP-PER-READ FAIL: high-half read returned 0x{got:08x}, expected "
            f"E1's high word 0x{_hi(_E1):08x} (E1=0x{_E1:016x}). The first read "
            "should have popped E0 entirely, leaving E1 at the head."
        )
        self.logger.info(
            "CHK-HIGH-HALF-LOSS PASS: the second read returned E1's high word "
            "0x%08x, not E0's high word 0x%08x -- E0's high half was discarded "
            "with its entry",
            got,
            _hi(_E0),
        )
        st = await self.mb.rd_csr(STATUS)
        assert st & ST_EMPTY, (
            f"CHK-POP-PER-READ FAIL: RX not empty after two reads of two entries "
            f"(STATUS=0x{st:08x})"
        )
        self.logger.info(
            "CHK-POP-PER-READ PASS: one 4-byte READ_DATA beat popped one whole "
            "entry at each half, so two reads consumed both entries and the FIFO "
            "is empty (STATUS=0x%08x)",
            st,
        )

        # --- CHK-RIRQT: the read half of the threshold pair -------------------
        # Thresholds compare strictly greater-than, matching the write half that
        # sep_axil_mailbox_iface_rand_test grades.
        await self.mb.wr_csr(RIRQT, _RIRQT)
        rb = await self.mb.rd_csr(RIRQT)
        assert rb == _RIRQT, f"CHK-RIRQT FAIL: RIRQT read back 0x{rb:x}, wrote 0x{_RIRQT:x}"
        # IRQEN gates the pending output; IRQP is the gated result and is read, not
        # written.
        await self.mb.wr_csr(IRQEN, IRQ_RTIRQ)

        st = await self.mb.rd_csr(STATUS)
        assert not (st & ST_RLVL_ABOVE), (
            "CHK-RIRQT FAIL: read_level_above already set on an empty RX "
            f"(STATUS=0x{st:08x}) -- the threshold cannot be shown to arm"
        )

        # IRQS.rtirq is sticky (stickybit, woclr), and the E0/E1 pushes above went
        # over the reset RIRQT, so it can already be latched. Clear it and show it
        # reads 0 in IRQS and IRQP; otherwise a later read of 1 would prove nothing
        # about this fill.
        await self.mb.wr_csr(IRQS, IRQ_RTIRQ)
        irqs = await self.mb.rd_csr(IRQS)
        irqp = await self.mb.rd_csr(IRQP)
        assert not (irqs & IRQ_RTIRQ) and not (irqp & IRQ_RTIRQ), (
            f"CHK-RIRQT FAIL: rtirq still set after write-1-clear on an empty RX "
            f"(IRQS=0x{irqs:08x} IRQP=0x{irqp:08x}) -- a later raise cannot be "
            "attributed to the fill"
        )
        self.logger.info(
            "CHK-RIRQT-CLEAR PASS: rtirq cleared before the fill (IRQS=0x%08x IRQP=0x%08x)",
            irqs,
            irqp,
        )

        # Fill to exactly RIRQT: strict greater-than, so neither the level flag
        # nor rtirq may rise yet. This pins the raise to the entry that crosses.
        for i in range(_RIRQT):
            rc = await self._peer_push64(_E0 + i)
            assert rc == RESP_OKAY, f"peer push {i} for the RIRQT fill returned resp={rc}"
        st = await self.mb.rd_csr(STATUS)
        irqs = await self.mb.rd_csr(IRQS)
        assert not (st & ST_RLVL_ABOVE) and not (irqs & IRQ_RTIRQ), (
            f"CHK-RIRQT FAIL: at exactly RIRQT={_RIRQT} entries read_level_above or "
            f"rtirq is already set (STATUS=0x{st:08x} IRQS=0x{irqs:08x}); the "
            "threshold is strict greater-than"
        )
        self.logger.info(
            "CHK-RIRQT-AT PASS: %d entries == RIRQT left read_level_above and rtirq "
            "clear (STATUS=0x%08x IRQS=0x%08x)",
            _RIRQT,
            st,
            irqs,
        )

        for i in range(_RIRQT, _RIRQT_FILL):
            rc = await self._peer_push64(_E0 + i)
            assert rc == RESP_OKAY, f"peer push {i} for the RIRQT fill returned resp={rc}"

        st = await self.mb.rd_csr(STATUS)
        assert st & ST_RLVL_ABOVE, (
            f"CHK-RIRQT FAIL: read_level_above clear with {_RIRQT_FILL} entries in RX "
            f"and RIRQT={_RIRQT} (STATUS=0x{st:08x})"
        )
        irqs = await self.mb.rd_csr(IRQS)
        assert irqs & IRQ_RTIRQ, (
            f"CHK-RIRQT FAIL: rtirq not raised in IRQS=0x{irqs:08x} with "
            f"read_level_above set and rtirq enabled"
        )
        irqp = await self.mb.rd_csr(IRQP)
        assert irqp & IRQ_RTIRQ, (
            f"CHK-RIRQT FAIL: rtirq set in IRQS but not pending in IRQP=0x{irqp:08x} "
            "with IRQEN.rtirq set -- the enable gate did not pass it through"
        )
        self.logger.info(
            "CHK-RIRQT PASS: %d entries over RIRQT=%d set read_level_above, raised "
            "rtirq and drove it through the enable gate (STATUS=0x%08x IRQS=0x%08x "
            "IRQP=0x%08x)",
            _RIRQT_FILL,
            _RIRQT,
            st,
            irqs,
            irqp,
        )

        # Drain to at-or-below the threshold; strict > means the flag must drop.
        for _ in range(_RIRQT_FILL - _RIRQT):
            resp, _ = await self._host_read_half(0)
            assert resp == RESP_OKAY, f"RIRQT drain read returned resp={resp}"
        st = await self.mb.rd_csr(STATUS)
        assert not (st & ST_RLVL_ABOVE), (
            f"CHK-RIRQT FAIL: read_level_above still set at {_RIRQT} entries with "
            f"RIRQT={_RIRQT} (strict greater-than, STATUS=0x{st:08x})"
        )
        self.logger.info(
            "CHK-RIRQT PASS: draining to exactly RIRQT=%d cleared read_level_above "
            "(strict greater-than)",
            _RIRQT,
        )

        # --- CHK-FILTER-DENY: the filter gates the live peer path -------------
        # Every push above went through an open allow window. Closing the window
        # must stop the peer reaching WRITE_DATA at all. The measurement is taken
        # here, where a healthy design demonstrably succeeds a line earlier, so
        # the refusal is scored in a window that is otherwise live rather than
        # against a dead bus.
        st_before = await self.mb.rd_csr(STATUS)
        await filt.disable_entry(self._filt_rule.entry)
        rc = await self._peer_push64(_E1)
        assert rc == RESP_DECERR, (
            f"CHK-FILTER-DENY FAIL: with the allow window closed, the peer write to "
            f"0x{INBOUND_BASE:08x} returned resp={rc}, expected DECERR "
            f"({RESP_DECERR}) from the filter error slave. The identical write "
            "succeeded with the window open, so the path is live."
        )
        st_after = await self.mb.rd_csr(STATUS)
        assert st_after == st_before, (
            f"CHK-FILTER-DENY FAIL: the refused write still changed the receive "
            f"FIFO (STATUS 0x{st_before:08x} -> 0x{st_after:08x}). A DECERR that "
            "still enqueues is worse than no filter at all."
        )
        self.logger.info(
            "CHK-FILTER-DENY PASS: with the window closed the peer write took "
            "DECERR and the receive FIFO did not move (STATUS=0x%08x)",
            st_after,
        )

        # --- CHK-FILTER-REOPEN: the positive control --------------------------
        # Without this the deny above could be a permanently broken peer path
        # rather than the filter doing its job.
        await filt.program_rule(
            self._filt_rule,
            read_allowed=True,
            write_allowed=True,
            end_addr=INBOUND_BASE + _MAILBOX_STRIDE - 1,
        )
        rc = await self._peer_push64(_E1)
        assert rc == RESP_OKAY, (
            f"CHK-FILTER-REOPEN FAIL: reopening the window did not restore the peer "
            f"path (resp={rc}). Without this the deny above proves nothing."
        )
        st_reopen = await self.mb.rd_csr(STATUS)
        assert st_reopen != st_after, (
            f"CHK-FILTER-REOPEN FAIL: the accepted write did not change the receive "
            f"FIFO (STATUS stayed 0x{st_after:08x})"
        )
        self.logger.info(
            "CHK-FILTER-REOPEN PASS: reopening the window restored the peer write "
            "and the receive FIFO moved again (STATUS=0x%08x)",
            st_reopen,
        )
