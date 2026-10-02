# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Every bit of every mailbox FIFO entry, in both directions, through both ports.

``hw/sys/sep/doc/mailbox.adoc``: each of the eight mailboxes holds two FIFOs of
eight 64-bit entries, and ``WRITE_DATA`` in one port pushes the FIFO that
``READ_DATA`` in the other port pops. A write of ``WRITE_DATA`` pushes one
entry, with the bytes outside the write strobe pushed as zero.

The other mailbox leaves grade one mailbox and a few values. This leaf grades
the data path itself: for each mailbox and each direction it pushes a walking
one and a walking zero over all 64 bits, in FIFO-depth batches, and pops them
on the other port. A stuck, swapped or crossed data bit on either port of any
mailbox, a reordered FIFO, a lost or duplicated entry, or a push that lands in
another mailbox, fails a compare.

The host port is driven by the CPU-LSU master. The peer port is driven by the
SMN-inbound external master, and every peer access carries seeded AxID,
AxPROT, AxCACHE, AxQOS, AxREGION, AxUSER, WUSER and (on reads) ARLOCK. The
inbound filter decides only on the address, ``prot[1]``, ``user[3:0]`` and
``AxLEN`` (``hw/ip/axi_filter/doc/index.adoc``). Each inbound port gets two
entries over exactly its own register map, one per ``allow_ns`` value, with
``src_id = 0`` (wildcard) and ``allow_burst = 0``, so every drawn access is
admitted and none of the other fields may change the data. A window spanning
several inbound ports would also cover the outbound ports interleaved between
them, so there is one window per port.

CHK-MBX-EMPTY: before any push, both FIFOs of every mailbox are empty in
STATUS on both ports. It is the control for the compares and for the leak
check at the end.

CHK-MBX-H2P-WALK / CHK-MBX-P2H-WALK: 128 words per mailbox per direction pop
in push order and bit-exact.

CHK-MBX-DEPTH: on the writing port STATUS.full is clear before the eighth
push and set after it; on the reading port STATUS.empty is clear with entries
queued and set after exactly as many pops as pushes.

CHK-MBX-STROBE: a partial-strobe push (a contiguous byte run that contains
lane j, for entry j, at an unaligned address inside WRITE_DATA) pushes one
entry, and that entry pops with each strobed byte in its own lane, in both
directions. The VIP drives the unstrobed WDATA lanes to zero, so the
specified zero fill of unstrobed bytes is not distinguishable from WDATA
pass-through here and is not claimed.

CHK-MBX-RESP-ID: every peer access returns its BID / RID equal to the AWID /
ARID it issued, and every peer access answers OKAY (or EXOKAY on an exclusive
read).

CHK-MBX-NO-LEAK: after the walk every FIFO of every mailbox is empty again,
so no push reached a mailbox other than its own.

RUN-MODE: no_cpu (CPU-LSU master) + external SMN master. FUSE-MODE:
+skip_fuse_sense (the mailbox has no OTP/LC dependency; the filter windows are
programmed explicitly). RAND: mailbox order, the walk's start bit, the strobe
runs and data, and every inbound request attribute come from SepSeededRng.
"""

from __future__ import annotations

import pyuvm
from sep_base_test import sep_base_test
from seq_lib.sep_inbound_attr_seq import SepInboundAttrTally
from seq_lib.sep_inbound_filter_rule_seq import (
    INFILT_N_ENTRIES,
    SepInboundFilter,
    SepInboundFilterCfg,
)
from seq_lib.sep_mailbox_iface_seq import SepMbox
from seq_lib.sep_mailbox_walk_seq import (
    MAILBOX_COUNT,
    RESP_OKAY,
    ST_EMPTY,
    ST_FULL,
    SepMboxWalkCfg,
    SepMboxWalkPort,
    inbound_base,
    inbound_last,
    strobe_image,
)


def _chunks(seq: list[int], n: int) -> list[list[int]]:
    return [seq[i : i + n] for i in range(0, len(seq), n)]


@pyuvm.test()
class sep_mailbox_datapath_walk_test(sep_base_test):
    """Walking-one / walking-zero and strobe pushes through all 8 mailboxes, both ways."""

    required_evidence = (
        "CHK-MBX-EMPTY",
        "CHK-MBX-H2P-WALK",
        "CHK-MBX-P2H-WALK",
        "CHK-MBX-DEPTH",
        "CHK-MBX-STROBE",
        "CHK-MBX-RESP-ID",
        "CHK-MBX-NO-LEAK",
    )

    async def run_scenario(self) -> None:
        cfg = SepMboxWalkCfg(self.random_seed())
        self.cfg_walk = cfg
        self.logger.info("mailbox walk config: %s", cfg.summary())
        assert 2 * MAILBOX_COUNT <= INFILT_N_ENTRIES, (
            f"{MAILBOX_COUNT} mailboxes need {2 * MAILBOX_COUNT} inbound filter "
            f"entries (one per NS polarity) but the bank has {INFILT_N_ENTRIES}"
        )

        await self.bring_up_no_cpu()
        await SepMbox(self).ungate_clock()

        filt = SepInboundFilter(self)
        await filt.disable_all()
        for m in range(MAILBOX_COUNT):
            for entry, ns in ((m, True), (MAILBOX_COUNT + m, False)):
                rule = SepInboundFilterCfg(entry=entry, allow_addr=inbound_base(m))
                await filt.program_rule(
                    rule,
                    read_allowed=True,
                    write_allowed=True,
                    end_addr=inbound_last(m),
                    allow_ns=ns,
                )
            self.logger.info(
                "inbound filter entries %d (ns) and %d (secure) allow inbound port of "
                "mailbox %d 0x%08x..0x%08x r+w",
                m,
                MAILBOX_COUNT + m,
                m,
                inbound_base(m),
                inbound_last(m),
            )

        self.tally = SepInboundAttrTally()
        self.ports = {
            m: SepMboxWalkPort(self, m, cfg.rng, self.tally) for m in range(MAILBOX_COUNT)
        }
        self.n_depth = 0

        await self._all_empty("CHK-MBX-EMPTY", "before any push")
        self.logger.info(
            "CHK-MBX-EMPTY PASS: all %d mailboxes report both FIFOs empty on both "
            "ports before any push",
            MAILBOX_COUNT,
        )

        words = {"h2p": 0, "p2h": 0}
        strobes = 0
        for m in cfg.order:
            port = self.ports[m]
            for d in ("h2p", "p2h"):
                pats = cfg.patterns(m, d)
                for batch in _chunks(pats, cfg.depth):
                    await self._batch(port, d, [(v, 0, 8, v) for v in batch], "WALK")
                words[d] += len(pats)
                cases = [
                    (data, lo, n, strobe_image(data, lo, n)) for lo, n, data in cfg.strobes[(m, d)]
                ]
                await self._batch(port, d, cases, "STROBE")
                strobes += len(cases)
            self.logger.info(
                "mailbox %d: %d words each way and %d strobe pushes each way popped "
                "exact and in order",
                m,
                len(cfg.patterns(m, "h2p")),
                cfg.depth,
            )

        self.logger.info(
            "CHK-MBX-H2P-WALK PASS: %d host-pushed words (walking one + walking zero "
            "over 64 bits, %d mailboxes) popped at the peer port bit-exact and in "
            "push order",
            words["h2p"],
            MAILBOX_COUNT,
        )
        self.logger.info(
            "CHK-MBX-P2H-WALK PASS: %d peer-pushed words (walking one + walking zero "
            "over 64 bits, %d mailboxes) popped at the host port bit-exact and in "
            "push order",
            words["p2h"],
            MAILBOX_COUNT,
        )
        self.logger.info(
            "CHK-MBX-STROBE PASS: %d partial-strobe pushes at unaligned WRITE_DATA "
            "addresses (every byte lane strobed in every batch) each pushed one entry "
            "that popped with the strobed bytes in their own lanes",
            strobes,
        )
        self.logger.info(
            "CHK-MBX-DEPTH PASS: %d batches of %d: full clear before the last push and "
            "set after it on the writing port; empty clear while queued and set "
            "after the last pop on the reading port",
            self.n_depth,
            cfg.depth,
        )

        await self._all_empty("CHK-MBX-NO-LEAK", "after the walk")
        self.logger.info(
            "CHK-MBX-NO-LEAK PASS: after %d pushes every FIFO of all %d mailboxes "
            "is empty again; no push reached another mailbox",
            words["h2p"] + words["p2h"] + strobes,
            MAILBOX_COUNT,
        )
        self.logger.info(
            "CHK-MBX-RESP-ID PASS: %d peer accesses answered OKAY (EXOKAY allowed "
            "on exclusive reads) with BID/RID equal to the issued ID; attributes "
            "drawn: %s",
            self.tally.graded,
            self.tally.summary(),
        )

        for entry in range(2 * MAILBOX_COUNT):
            await filt.disable_entry(entry)

    async def _all_empty(self, chk: str, when: str) -> None:
        """Both FIFOs of every mailbox empty, read on both ports."""
        for m in range(MAILBOX_COUNT):
            p = self.ports[m]
            hs = await p.host_status()
            ps = await p.peer_status()
            assert hs & ST_EMPTY and ps & ST_EMPTY, (
                f"{chk} FAIL: mailbox {m} {when}: host STATUS=0x{hs:08x} "
                f"peer STATUS=0x{ps:08x}; STATUS.empty must be set on both ports"
            )
            assert not (hs & ST_FULL) and not (ps & ST_FULL), (
                f"{chk} FAIL: mailbox {m} {when}: STATUS.full set (host=0x{hs:08x} peer=0x{ps:08x})"
            )

    def _grade_peer(self, what: str, rc: int, rid: int | None, a) -> None:
        self.tally.graded_resp(a, rc)
        assert rc in a.ok_resps(), (
            f"CHK-MBX-RESP-ID FAIL: peer {what} ({a}) answered resp={rc}, expected "
            f"one of {a.ok_resps()}; the window admits every drawn attribute"
        )
        assert rid == a.axi_id, (
            f"CHK-MBX-RESP-ID FAIL: peer {what} issued ID 0x{a.axi_id:02x} and the "
            f"response carried ID {rid if rid is None else hex(rid)}"
        )

    async def _push(self, port: SepMboxWalkPort, d: str, data: int, lo: int, n: int) -> None:
        if d == "h2p":
            rc = await port.host_push(data, offset=lo, nbytes=n)
            assert rc == RESP_OKAY, (
                f"mailbox {port.m} host push of 0x{data:x} (+{lo}, {n} B) answered "
                f"resp={rc}, expected OKAY"
            )
        else:
            rc, bid, a = await port.peer_push(data, offset=lo, nbytes=n)
            self._grade_peer(f"push of 0x{data:x} (+{lo}, {n} B)", rc, bid, a)

    async def _pop(self, port: SepMboxWalkPort, d: str) -> int:
        if d == "h2p":
            rc, got, rid, a = await port.peer_pop()
            self._grade_peer("pop", rc, rid, a)
            return got
        rc, got = await port.host_pop()
        assert rc == RESP_OKAY, (
            f"mailbox {port.m} host pop answered resp={rc}, expected OKAY with entries queued"
        )
        return got

    async def _write_status(self, port: SepMboxWalkPort, d: str) -> int:
        return await (port.host_status() if d == "h2p" else port.peer_status())

    async def _read_status(self, port: SepMboxWalkPort, d: str) -> int:
        return await (port.peer_status() if d == "h2p" else port.host_status())

    async def _batch(
        self, port: SepMboxWalkPort, d: str, cases: list[tuple[int, int, int, int]], kind: str
    ) -> None:
        """Push ``cases`` (data, byte offset, byte count, expected entry) on the
        writing port of direction ``d``, then pop them on the other port."""
        chk = f"CHK-MBX-{'STROBE' if kind == 'STROBE' else d.upper() + '-WALK'}"
        full_batch = len(cases) == self.cfg_walk.depth
        for i, (data, lo, n, _exp) in enumerate(cases):
            if full_batch and i == len(cases) - 1:
                st = await self._write_status(port, d)
                assert not st & ST_FULL, (
                    f"CHK-MBX-DEPTH FAIL: mailbox {port.m} {d}: STATUS.full set with "
                    f"{i} of {self.cfg_walk.depth} entries queued (STATUS=0x{st:08x})"
                )
            await self._push(port, d, data, lo, n)
        st_w = await self._write_status(port, d)
        st_r = await self._read_status(port, d)
        if full_batch:
            assert st_w & ST_FULL, (
                f"CHK-MBX-DEPTH FAIL: mailbox {port.m} {d}: STATUS.full clear after "
                f"{self.cfg_walk.depth} pushes (STATUS=0x{st_w:08x})"
            )
        assert not st_r & ST_EMPTY, (
            f"CHK-MBX-DEPTH FAIL: mailbox {port.m} {d}: reading port STATUS.empty "
            f"set with {len(cases)} entries pushed (STATUS=0x{st_r:08x})"
        )
        for i, (data, lo, n, exp) in enumerate(cases):
            got = await self._pop(port, d)
            assert got == exp, (
                f"{chk} FAIL: mailbox {port.m} {d} entry {i}: popped 0x{got:016x}, "
                f"expected 0x{exp:016x} (pushed 0x{data:x} at byte {lo}, {n} B); "
                f"xor=0x{got ^ exp:016x}"
            )
        st_r = await self._read_status(port, d)
        assert st_r & ST_EMPTY, (
            f"CHK-MBX-DEPTH FAIL: mailbox {port.m} {d}: reading port STATUS.empty "
            f"clear after {len(cases)} pops of {len(cases)} pushes (STATUS=0x{st_r:08x})"
        )
        if full_batch:
            self.n_depth += 1
