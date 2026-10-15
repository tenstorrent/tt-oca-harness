# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Every mailbox accepts an inbound write while SEP_DBG bypasses the inbound filter.

The mailbox has no qualification of its own. In PROD with ``SEP_DBG`` clear,
the inbound filter blocks a write that matches no entry
(``hw/sys/sep/doc/fabric.adoc``, "Filtering and Protection";
``hw/ip/axi_filter/doc/index.adoc``, "Blocked Transactions"). ``DEMOTE_1``
in PROD sets ``SEP_DBG`` when bit 0 of ``SIP_DIS`` and of ``SYS_DIS`` is clear
(``hw/sys/sep/doc/lifecycle_controller.adoc``, "In-Field Debug Demotion",
"Debug and Functional Feature Control"). While ``SEP_DBG`` is set every
inbound write passes, so every mailbox takes the word into its FIFO and raises
its inbound line, which is bit ``m`` of ``sep_internal_interrupts_probe_o``
(``hw/sys/sep/doc/mailbox.adoc``, "Mailboxes";
``hw/sys/sep/doc/interrupts.adoc``, "SEP PIC source assignments").

Procedure: real PROD fuse sense of an image with distinct non-zero
``SIP_DIS`` and ``SYS_DIS`` whose bit 0 is clear; one filter entry over the
inbound aperture of mailbox 3 (``src_id`` 5, ``allow_ns`` 0); no entry over
any other mailbox; ``IRQEN`` 0x1 and ``WIRQT`` 0 on the inbound port of all
eight mailboxes. The wrong-source write to mailbox 3 and the write to
mailbox 6 are blocked before ``DEMOTE_1`` and accepted after it, then the six
other mailboxes take one write each with directed source IDs and
``AxPROT[1]`` values. Every word is popped and compared at the outbound port.

Checks:

* CTL-PROD-BLOCK (control): before the demote the two writes answer DECERR,
  leave the FIFO empty and leave the inbound line low.
* CHK-DBG-ACCEPT: after the demote FEAT_CTRL reads its DEMOTE_1 golden with
  ``SEP_DBG`` set, and every mailbox answers OKAY, holds one entry, raises
  its inbound line, and the popped word equals the pushed word; on mailbox 3
  the outbound occupancy goes from 0 to 1 across the demote.
* CTL-NONVAC (control): the same mailbox 3 write answers DECERR before the
  demote and OKAY after it.

Run mode: no_cpu (``lsu_stub_all_live``), real PROD fuse sense, one seed. The
life-cycle path has one legal sequence; the payload words come from the seed.
"""

from __future__ import annotations

from typing import Any

import cocotb
import pyuvm
from cocotb.triggers import ClockCycles, ReadOnly, RisingEdge
from env.sep_axi_agent import SepAxiOp
from env.sep_fcov_gate import close_graded_window, open_graded_window
from env.sep_filter_model import FilterEntry
from env.sep_lcc_golden import LC_PROD, LCC_FEAT_CTRL, feat_ctrl_expected
from env.sep_mbox_golden import IRQ_EIRQ, IRQ_RTIRQ, IRQ_WTIRQ, ST_EMPTY
from env.sep_seeded_rng import SepSeededRng
from sep_base_test import sep_base_test
from seq_lib.sep_axi_access_seq import SepAxiAccessSeq
from seq_lib.sep_fabric_filter_bank_seq import SepFilterBank
from seq_lib.sep_lcc_inbound_filter_gating_seq import SepLccDemoteSeq
from seq_lib.sep_mailbox_iface_seq import SepMbox
from seq_lib.sep_mailbox_walk_seq import inbound_base, outbound_base
from seq_lib.sep_mbox_port_ops import RESP_DECERR, RESP_OKAY, ports, resp_name

TEST = "sep_mailbox_debug_bypass_test"

# Image: PROD, distinct non-zero disable vectors with bit 0 (SEP_DBG) clear.
SIP_DIS = 0x0F0F_0F0F_0F0F_0F0E
SYS_DIS = 0x00FF_00FF_00FF_00FE
MAX_SENSE_CYCLES = 20_000

ISS_MBOX = 3
ISS_SRC = 5
NOENTRY_MBOX = 6
WRONG_SRC = 9
# Directed source ID and AxPROT[1] of the six other mailboxes.
DIRECTED = ((0, 1, 0), (1, 2, 1), (2, 3, 0), (4, 4, 1), (5, 5, 0), (7, 6, 1))

QUIET_CLKS = 32
# IRQEN fields (eirq, rtirq, wtirq) and the address span of one inbound port
# (the inbound port base to the next outbound port base), from the RDL.
IRQEN_FIELDS = IRQ_WTIRQ | IRQ_RTIRQ | IRQ_EIRQ
IN_PORT_SPAN = inbound_base(0) - outbound_base(0)
DEMOTE_TRIES = 16
MASK64 = (1 << 64) - 1


@pyuvm.test()
class sep_mailbox_debug_bypass_test(sep_base_test):
    """In PROD, DEMOTE_1 opens every mailbox to any inbound write."""

    required_evidence = ("CHK-DBG-ACCEPT",)

    @staticmethod
    def _top() -> Any:
        return cocotb.top

    def _fail(self, chk: str, line: str) -> None:
        msg = f"{chk} FAIL seed={self.seed} {line}"
        self.logger.error(msg)
        raise AssertionError(msg)

    def _pass(self, chk: str, line: str) -> None:
        self.logger.info("%s PASS seed=%d %s", chk, self.seed, line)
        self.n_checks += 1

    async def _lsu(self, op: SepAxiOp, addr: int, wdata: int = 0) -> tuple[int, int]:
        seq = SepAxiAccessSeq(
            "dbg_lsu",
            op=op,
            addr=addr,
            wdata=wdata,
            length=4,
            size=2,
            allow_unverified_write_resp=op is SepAxiOp.WRITE,
            allow_ungraded_read_resp=op is SepAxiOp.READ,
        )
        await self.start_seq(seq)
        return int(seq.resp_code), int(seq.rdata) & 0xFFFF_FFFF

    async def _probe(self) -> int:
        """Probe bits [7:0] after one quiet window with no mailbox access."""
        await ClockCycles(self._top().clk_i, QUIET_CLKS)
        await RisingEdge(self._top().clk_i)
        await ReadOnly()
        v = self.rd(self._top().sep_internal_interrupts_probe_o, 0xFF) & 0xFF
        await RisingEdge(self._top().clk_i)
        return v

    async def _out_status(self, m: int) -> int:
        return int(await self.ops[m].rd_ok("out", "STATUS"))

    async def _push(self, m: int, src: int, prot1: int, word: int) -> int:
        return int(await self.ops[m].push("in", word, prot1=prot1, user=src))

    async def _feat_ctrl(self) -> int:
        """Frontdoor read of the 64-bit FEAT_CTRL; bit 0 is SEP_DBG."""
        lo = (await self._lsu(SepAxiOp.READ, LCC_FEAT_CTRL))[1]
        hi = (await self._lsu(SepAxiOp.READ, LCC_FEAT_CTRL + 4))[1]
        return lo | (hi << 32)

    async def _bring_up(self) -> None:
        image = self.select_efuse_image(
            lc_raw=LC_PROD, fixed={"SIP_DIS": SIP_DIS, "SYS_DIS": SYS_DIS}
        )
        self.write_efuse_image(image)
        await self.bring_up_and_wait_fuse_sense(max_cycles=MAX_SENSE_CYCLES)
        golden = feat_ctrl_expected(LC_PROD, SIP_DIS, SYS_DIS, demote_1=0, sec_dis=0)
        feat = await self._feat_ctrl()
        if feat != golden or feat & 1:
            self._fail(
                "CTL-PROD-BLOCK", f"precondition feat_ctrl=0x{feat:016x} golden=0x{golden:016x}"
            )
        self.logger.info(
            "CTL-PROD-BLOCK LOG precondition feat_ctrl=0x%016x golden=0x%016x sep_dbg=%d",
            feat,
            golden,
            feat & 1,
        )

    async def run_scenario(self) -> None:
        self.seed = self.random_seed()
        self.n_checks = 0
        rng = SepSeededRng(self.seed)
        self.logger.info("SEED seed=%d", self.seed)
        words: dict[int, int] = {}
        for m in range(8):
            while True:
                w = rng.getrandbits(64)
                if w and w not in words.values():
                    break
            words[m] = w
        blocked3 = rng.getrandbits(64) | 1
        blocked6 = rng.getrandbits(64) | 1
        for m in range(8):
            self.logger.info("DRAW word_mbox%d=0x%016x", m, words[m])
        self.logger.info(
            "DRAW blocked_word_mbox3=0x%016x blocked_word_mbox6=0x%016x", blocked3, blocked6
        )
        close_graded_window(self.logger)

        # Step 1: PROD sense, SEP_DBG clear; mailbox clock.
        await self._bring_up()
        await SepMbox(self).ungate_clock()
        self.ops = ports(self)

        # Step 2: one ISS entry over mailbox 3; IRQEN.wtirq and WIRQT 0 on all eight inbound ports.
        bank = SepFilterBank(self, "in")
        base3 = inbound_base(ISS_MBOX)
        await bank.program(
            0,
            FilterEntry(
                start=base3,
                end=base3 + IN_PORT_SPAN - 1,
                enabled=True,
                read_allowed=True,
                write_allowed=True,
                allow_ns=False,
                src_id=ISS_SRC,
            ),
        )
        for m in range(8):
            o = self.ops[m]
            for reg, val in (("WIRQT", 0), ("IRQEN", IRQ_WTIRQ)):
                resp, _ = await self._lsu(SepAxiOp.WRITE, o.addr("in", reg), val)
                if resp != RESP_OKAY:
                    self._fail("CTL-PROD-BLOCK", f"set-up mbox={m} in {reg} resp={resp_name(resp)}")
            resp, irqen = await self._lsu(SepAxiOp.READ, o.addr("in", "IRQEN"))
            if resp != RESP_OKAY or irqen & IRQEN_FIELDS != IRQ_WTIRQ:
                self._fail(
                    "CTL-PROD-BLOCK",
                    f"set-up mbox={m} in IRQEN read resp={resp_name(resp)} irqen=0x{irqen & IRQEN_FIELDS:x} exp=0x{IRQ_WTIRQ:x}",
                )
            self.logger.info(
                "SETUP LOG mbox=%d in IRQEN=0x%x WIRQT=0 (written by CPU-LSU)",
                m,
                irqen & IRQEN_FIELDS,
            )

        # Step 3: PROD block of a wrong source ID and of a mailbox with no entry.
        prod: dict[int, tuple[int, int, int]] = {}
        for m, src, prot1, w in (
            (ISS_MBOX, WRONG_SRC, 0, blocked3),
            (NOENTRY_MBOX, WRONG_SRC, 1, blocked6),
        ):
            resp = await self._push(m, src, prot1, w)
            probe = await self._probe()
            st = await self._out_status(m)
            occ = 0 if st & ST_EMPTY else 1
            line = (probe >> m) & 1
            prod[m] = (resp, occ, line)
            txt = f"mbox={m} src={src} prot1={prot1} resp={resp_name(resp)} occ={occ} line={line} probe=0x{probe:02x}"
            if resp != RESP_DECERR or occ != 0 or line != 0 or probe != 0:
                self._fail("CTL-PROD-BLOCK", txt)
            self.logger.info("CTL-PROD-BLOCK PASS seed=%d %s", self.seed, txt)

        # Step 4: DEMOTE_1 (graded stimulus starts here).
        open_graded_window(TEST, self.logger)
        demote = SepLccDemoteSeq(1)
        await self.start_seq(demote)
        self.logger.info("DEMOTE_1 LOG demote=%s lock=%s", demote.demote, demote.lock)

        # Step 5: the mailbox 3 write until OKAY, with a bounded number of tries.
        written = 0
        resp = -1
        for t in range(1, DEMOTE_TRIES + 1):
            resp = await self._push(ISS_MBOX, WRONG_SRC, 0, words[ISS_MBOX])
            if resp == RESP_OKAY:
                self.logger.info("DEMOTE-RETRY LOG mbox=3 tries=%d", t)
                break
            st = await self._out_status(ISS_MBOX)
            if resp != RESP_DECERR or not st & ST_EMPTY:
                self._fail(
                    "CHK-DBG-ACCEPT",
                    f"mbox=3 try={t} resp={resp_name(resp)} status=0x{st & 0xF:x} (a refused try must leave the FIFO empty)",
                )
        if resp != RESP_OKAY:
            self._fail(
                "CHK-DBG-ACCEPT", f"mbox=3 no OKAY within {DEMOTE_TRIES} tries after DEMOTE_1"
            )
        # SEP_DBG is the cause of the bypass: FEAT_CTRL reads the DEMOTE_1 golden
        # with bit 0 set before any accepted write is graded.
        golden = feat_ctrl_expected(LC_PROD, SIP_DIS, SYS_DIS, demote_1=1, sec_dis=0)
        feat = await self._feat_ctrl()
        dbg = f"post-demote feat_ctrl=0x{feat:016x} golden=0x{golden:016x} sep_dbg={feat & 1}"
        if feat != golden or not feat & 1:
            self._fail("CHK-DBG-ACCEPT", dbg)
        self._pass("CHK-DBG-ACCEPT", dbg)
        written |= 1 << ISS_MBOX
        probe = await self._probe()
        if probe != written:
            self._fail("CHK-DBG-ACCEPT", f"mbox=3 probe=0x{probe:02x} exp=0x{written:02x}")
        st = await self._out_status(ISS_MBOX)
        occ_after = 0 if st & ST_EMPTY else 1
        if prod[ISS_MBOX][1] != 0 or occ_after != 1:
            self._fail(
                "CHK-DBG-ACCEPT",
                f"mbox=3 occ_before_demote={prod[ISS_MBOX][1]} occ_after_demote={occ_after}",
            )
        self._pass(
            "CHK-DBG-ACCEPT",
            f"mbox=3 occ_before_demote={prod[ISS_MBOX][1]} occ_after_demote={occ_after}",
        )
        nonvac = f"mbox=3 resp_before_demote={resp_name(prod[ISS_MBOX][0])} resp_after_demote={resp_name(resp)}"
        if prod[ISS_MBOX][0] != RESP_DECERR or resp != RESP_OKAY:
            self._fail("CTL-NONVAC", nonvac)
        self.logger.info("CTL-NONVAC PASS seed=%d %s", self.seed, nonvac)

        # Steps 6 and 7: mailbox 6 (no entry) and the six directed writes.
        accepted: dict[int, tuple[int, int, int, int]] = {ISS_MBOX: (WRONG_SRC, 0, resp, probe)}
        plan = [(NOENTRY_MBOX, WRONG_SRC, 1)] + list(DIRECTED)
        for m, src, prot1 in plan:
            resp = await self._push(m, src, prot1, words[m])
            if resp != RESP_OKAY:
                self._fail(
                    "CHK-DBG-ACCEPT",
                    f"mbox={m} src={src} prot1={prot1} resp={resp_name(resp)} exp=OKAY",
                )
            written |= 1 << m
            probe = await self._probe()
            if probe != written:
                self._fail(
                    "CHK-DBG-ACCEPT",
                    f"mbox={m} src={src} prot1={prot1} probe=0x{probe:02x} exp=0x{written:02x}",
                )
            accepted[m] = (src, prot1, resp, probe)
            self.logger.info(
                "DBG-PROBE LOG mbox=%d src=%d prot1=%d resp=%s probe=0x%02x exp=0x%02x",
                m,
                src,
                prot1,
                resp_name(resp),
                probe,
                written,
            )

        # Step 8: every mailbox holds one entry; the pop returns the pushed word.
        for m in range(8):
            src, prot1, resp, probe = accepted[m]
            st0 = await self._out_status(m)
            presp, data = await self.ops[m].pop("out")
            st1 = await self._out_status(m)
            occ = 1 if (not st0 & ST_EMPTY and st1 & ST_EMPTY and presp == RESP_OKAY) else 0
            entry = "iss_src5" if m == ISS_MBOX else "none"
            txt = (
                f"mbox={m} entry={entry} src={src} prot1={prot1} resp={resp_name(resp)} occ={occ} "
                f"line={(probe >> m) & 1} data=0x{data & MASK64:016x} exp=0x{words[m]:016x} "
                f"pop_resp={resp_name(presp)} status_before=0x{st0 & 0xF:x} status_after=0x{st1 & 0xF:x}"
            )
            if occ != 1 or (data & MASK64) != words[m] or not (probe >> m) & 1:
                self._fail("CHK-DBG-ACCEPT", txt)
            self._pass("CHK-DBG-ACCEPT", txt)

        close_graded_window(self.logger)
        self.result_pass(TEST, self.seed, self.n_checks)
