# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Every bit of every mailbox FIFO entry, in both directions, through both ports.

``hw/sys/sep/doc/mailbox.adoc``: each of the eight mailboxes holds two FIFOs of
eight 64-bit entries, and ``WRITE_DATA`` in one port pushes the FIFO that
``READ_DATA`` in the other port pops. A write of ``WRITE_DATA`` pushes one
entry, with the bytes outside the write strobe pushed as zero.

This leaf grades the data path itself: for each mailbox and each direction it pushes a walking
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

CHK-MBX-DEPTH: STATUS is read on both ports after every push and every pop,
so both flags are graded at every depth from 0 to 8. On the writing port
STATUS.full is set only with eight entries queued; on the reading port
STATUS.empty is set only with none queued. The PASS line logs the flag values
seen at each depth.

CHK-MBX-STROBE: a partial-strobe push (a contiguous byte run that contains
lane j, for entry j, at an unaligned address inside WRITE_DATA) pushes one
entry, and that entry pops with each strobed byte in its own lane, in both
directions. The VIP drives the unstrobed WDATA lanes to zero in this batch;
CHK-MBX-ZERO-FILL grades the zero fill.

``hw/ip/axi_lite_mailbox_unit/regs/axil_mailbox.rdl`` (WRITE_DATA): any write
pushes one entry, irrespective of WSTRB, including a write with no byte lanes
enabled; byte lanes whose strobe is 0 are pushed as 0. One more FIFO-depth
batch per mailbox and direction grades this. A wrapper on the VIP W-channel
send puts seeded non-zero data on every unstrobed lane of each beat, and sets
WSTRB to 0 on the beat at one seeded position. A pin monitor on the writing
port records every W handshake, and each push must show exactly one beat with
the planned WSTRB, the written bytes on the strobed lanes and the non-zero
fill on every unstrobed lane, so neither check can pass on a bus that carried
zeros.

CHK-MBX-ZERO-STROBE: the WSTRB=0 write pushes exactly one entry. STATUS on
both ports is graded after every push and every pop of the batch (writing-port
full only at depth 8, reading-port empty only at depth 0), so a write that
pushed no entry or two entries moves the full flag to the wrong push or leaves
an entry after the last pop. The entry pops at its position in the batch with
the value 0, although WDATA on the pins was non-zero.

CHK-MBX-ZERO-FILL: each partial-strobe write of the batch (1 to 7 bytes at a
seeded offset) pops with the strobed bytes in their lanes and 0 on every
unstrobed lane, although the pins carried non-zero data there.

CHK-MBX-RESP-ID: every peer access returns its BID / RID equal to the AWID /
ARID it issued, and every peer access answers OKAY (or EXOKAY on an exclusive
read).

CHK-MBX-NO-LEAK: after the walk every FIFO of every mailbox is empty again,
so no push reached a mailbox other than its own.

Run mode: no_cpu (CPU-LSU master) with the external SMN master and
+skip_fuse_sense (the mailbox has no OTP/LC dependency; the filter windows are
programmed explicitly). The mailbox order, the walk's start bit, the strobe runs
and data, the zero-strobe position, the fill data, and every inbound request
attribute come from SepSeededRng.
"""

from __future__ import annotations

from typing import Any

import cocotb
import pyuvm
from cocotb.triggers import ReadOnly, RisingEdge
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
    WORD_BYTES,
    SepMboxWalkCfg,
    SepMboxWalkPort,
    inbound_base,
    inbound_last,
    strobe_image,
)


def _chunks(seq: list[int], n: int) -> list[list[int]]:
    return [seq[i : i + n] for i in range(0, len(seq), n)]


def _lanes(strb: int) -> int:
    """Bit mask of the byte lanes that ``strb`` enables."""
    mask = 0
    for lane in range(WORD_BYTES):
        if strb >> lane & 1:
            mask |= 0xFF << (8 * lane)
    return mask


ALL_LANES = (1 << (8 * WORD_BYTES)) - 1


class _WLaneFill:
    """Unstrobed-lane fill and WSTRB override on one VIP master, and a pin
    monitor of its W handshakes.

    The backend builds each W beat with 0 on the unstrobed lanes. The wrapper
    on the W-channel ``send`` edits the beat object just before it is queued:
    it sets WSTRB to ``strb`` when one is armed, and puts ``fill`` on every lane
    whose strobe is 0. ``beats`` holds (WSTRB, WDATA) of every W handshake seen
    on the pins of ``prefix``, sampled once per clock in the ReadOnly phase
    after the rising edge, so each handshake gives exactly one entry.
    """

    def __init__(self, agent, prefix: str) -> None:
        self.prefix = prefix
        self._w_channel = agent.driver.axi.driver.channels["w_delay"]
        self._fill: int | None = None
        self._strb: int | None = None
        self.beats: list[tuple[int, int]] = []
        self._watch = None
        original = self._w_channel.send

        async def send(beat, _orig=original):
            if self._fill is not None:
                if self._strb is not None:
                    beat.wstrb = self._strb
                active = _lanes(int(beat.wstrb))
                beat.wdata = (int(beat.wdata) & active) | (self._fill & ~active & ALL_LANES)
            await _orig(beat)

        self._w_channel.send = send
        self._watch = cocotb.start_soon(self._watch_pins())

    def arm(self, fill: int, strb: int | None = None) -> None:
        self._fill = fill
        self._strb = strb

    def disarm(self) -> None:
        self._fill = None
        self._strb = None

    def restore(self) -> None:
        self.disarm()
        if "send" in vars(self._w_channel):
            del self._w_channel.send
        if self._watch is not None:
            self._watch.kill()
            self._watch = None

    async def _watch_pins(self) -> None:
        dut: Any = cocotb.top
        valid = getattr(dut, f"{self.prefix}_wvalid")
        ready = getattr(dut, f"{self.prefix}_wready")
        strb = getattr(dut, f"{self.prefix}_wstrb")
        data = getattr(dut, f"{self.prefix}_wdata")
        while True:
            await RisingEdge(dut.clk_i)
            await ReadOnly()
            if valid.value != 1 or ready.value != 1:
                continue
            self.beats.append((int(strb.value), int(data.value)))


@pyuvm.test()
class sep_mailbox_datapath_walk_test(sep_base_test):
    """Every pushed entry pops in order and bit-exact on the other port, in all 8 mailboxes."""

    required_evidence = (
        "CHK-MBX-EMPTY",
        "CHK-MBX-H2P-WALK",
        "CHK-MBX-P2H-WALK",
        "CHK-MBX-DEPTH",
        "CHK-MBX-STROBE",
        "CHK-MBX-ZERO-STROBE",
        "CHK-MBX-ZERO-FILL",
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

        zero_plan = self._draw_zero_plan(cfg)
        self.tally = SepInboundAttrTally()
        self.ports = {
            m: SepMboxWalkPort(self, m, cfg.rng, self.tally) for m in range(MAILBOX_COUNT)
        }
        self.n_depth = 0
        # depth -> {(reading-port empty, writing-port full): samples}
        self.depth_seen: dict[int, dict[tuple[bool, bool], int]] = {}

        await self._all_empty("CHK-MBX-EMPTY", "before any push")
        self.logger.info(
            "CHK-MBX-EMPTY PASS: all %d mailboxes report both FIFOs empty on both "
            "ports before any push",
            MAILBOX_COUNT,
        )

        words = {"h2p": 0, "p2h": 0}
        strobes = 0
        filled = 0
        self.fills = {
            "h2p": _WLaneFill(self.env.axi_agent, "s_axi"),
            "p2h": _WLaneFill(self.env.ext_axi_agent, "m_axi"),
        }
        self.zero_seen: list[str] = []
        self.fill_n = 0
        self.fill_pin_or = 0
        self.fill_pop_or = 0
        try:
            for m in cfg.order:
                port = self.ports[m]
                for d in ("h2p", "p2h"):
                    pats = cfg.patterns(m, d)
                    for batch in _chunks(pats, cfg.depth):
                        await self._batch(port, d, [(v, 0, 8, v) for v in batch], "WALK")
                    words[d] += len(pats)
                    cases = [
                        (data, lo, n, strobe_image(data, lo, n))
                        for lo, n, data in cfg.strobes[(m, d)]
                    ]
                    await self._batch(port, d, cases, "STROBE")
                    strobes += len(cases)
                    await self._zero_batch(port, d, zero_plan[(m, d)])
                    filled += len(zero_plan[(m, d)])
                self.logger.info(
                    "mailbox %d: %d words each way, %d strobe pushes each way and %d "
                    "filled pushes each way popped exact and in order",
                    m,
                    len(cfg.patterns(m, "h2p")),
                    cfg.depth,
                    cfg.depth,
                )
        finally:
            for f in self.fills.values():
                f.restore()

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
        assert len(self.zero_seen) == 2 * MAILBOX_COUNT, (
            f"CHK-MBX-ZERO-STROBE FAIL: {len(self.zero_seen)} zero-strobe writes "
            f"graded, expected {2 * MAILBOX_COUNT} (one per mailbox and direction)"
        )
        self.logger.info(
            "CHK-MBX-ZERO-STROBE PASS: %d writes with WSTRB=0 on the pins each pushed "
            "exactly one entry (STATUS graded after every push and pop of its batch) "
            "that popped as 0x0 at its position; per write (mailbox.dir@pos "
            "pin_wstrb pin_wdata exp popped): %s",
            len(self.zero_seen),
            "; ".join(self.zero_seen),
        )
        assert self.fill_n > 0 and self.fill_pin_or != 0, (
            f"CHK-MBX-ZERO-FILL FAIL: {self.fill_n} filled partial-strobe pushes, "
            f"OR of unstrobed pin data 0x{self.fill_pin_or:016x}; the stimulus did "
            "not put non-zero data on an unstrobed lane"
        )
        self.logger.info(
            "CHK-MBX-ZERO-FILL PASS: %d partial-strobe pushes carried non-zero data on "
            "every unstrobed lane on the pins (OR of unstrobed pin data "
            "0x%016x) and popped with the strobed bytes in their lanes and the "
            "unstrobed lanes 0 (expected OR 0x0, observed OR of unstrobed popped "
            "data 0x%016x)",
            self.fill_n,
            self.fill_pin_or,
            self.fill_pop_or,
        )
        per_depth = "; ".join(
            f"{q}: "
            + ",".join(
                f"empty={int(e)} full={int(f)} x{n}"
                for (e, f), n in sorted(self.depth_seen[q].items())
            )
            for q in sorted(self.depth_seen)
        )
        assert sorted(self.depth_seen) == list(range(cfg.depth + 1)), (
            f"CHK-MBX-DEPTH FAIL: STATUS graded at depths {sorted(self.depth_seen)}, "
            f"expected every depth 0..{cfg.depth}"
        )
        self.logger.info(
            "CHK-MBX-DEPTH PASS: %d batches of %d; STATUS on both ports after every "
            "push and pop, writing-port full set only at depth %d and reading-port "
            "empty set only at depth 0; observed per depth (reading-port empty, "
            "writing-port full, samples): %s",
            self.n_depth,
            cfg.depth,
            cfg.depth,
            per_depth,
        )

        await self._all_empty("CHK-MBX-NO-LEAK", "after the walk")
        self.logger.info(
            "CHK-MBX-NO-LEAK PASS: after %d pushes every FIFO of all %d mailboxes "
            "is empty again; no push reached another mailbox",
            words["h2p"] + words["p2h"] + strobes + filled,
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
            await self._push(port, d, data, lo, n)
            await self._grade_depth(port, d, i + 1, f"after push {i + 1}")
        for i, (data, lo, n, exp) in enumerate(cases):
            got = await self._pop(port, d)
            assert got == exp, (
                f"{chk} FAIL: mailbox {port.m} {d} entry {i}: popped 0x{got:016x}, "
                f"expected 0x{exp:016x} (pushed 0x{data:x} at byte {lo}, {n} B); "
                f"xor=0x{got ^ exp:016x}"
            )
            await self._grade_depth(port, d, len(cases) - i - 1, f"after pop {i + 1}")
        if full_batch:
            self.n_depth += 1

    def _draw_zero_plan(self, cfg: SepMboxWalkCfg) -> dict:
        """Per (mailbox, direction): a FIFO-depth batch of (kind, offset, bytes,
        data, fill). One seeded position is the WSTRB=0 write; the others write
        1 to 7 bytes at a seeded offset. Every fill byte is non-zero."""
        rng = cfg.rng
        plan = {}
        for m in cfg.order:
            for d in ("h2p", "p2h"):
                z = rng.randrange(cfg.depth)
                cases = []
                for j in range(cfg.depth):
                    fill = 0
                    for lane in range(WORD_BYTES):
                        fill |= rng.randrange(1, 256) << (8 * lane)
                    if j == z:
                        cases.append(("zero", 0, WORD_BYTES, rng.getrandbits(64), fill))
                        continue
                    lo = rng.randrange(0, WORD_BYTES)
                    n = rng.randrange(1, min(WORD_BYTES - lo, WORD_BYTES - 1) + 1)
                    cases.append(("fill", lo, n, rng.getrandbits(8 * n), fill))
                plan[(m, d)] = cases
        return plan

    def _pin_beat(
        self,
        chk: str,
        port: SepMboxWalkPort,
        d: str,
        i: int,
        n0: int,
        strb: int,
        data_exp: int,
        fill: int,
    ) -> int:
        """The one W beat of push ``i`` on the pins: WSTRB ``strb``, the strobed
        lanes equal to ``data_exp``, every unstrobed lane equal to the non-zero
        ``fill``. Returns the WDATA seen."""
        beats = self.fills[d].beats[n0:]
        assert len(beats) == 1, (
            f"{chk} FAIL: mailbox {port.m} {d} push {i}: {len(beats)} W handshakes on "
            f"{self.fills[d].prefix} pins, expected 1: {beats}"
        )
        p_strb, p_data = beats[0]
        active = _lanes(p_strb)
        assert (
            p_strb == strb
            and p_data & active == data_exp
            and p_data & ~active & ALL_LANES == fill & ~active & ALL_LANES
            and p_data & ~active & ALL_LANES != 0
        ), (
            f"{chk} FAIL: mailbox {port.m} {d} push {i}: pins WSTRB=0x{p_strb:02x} "
            f"WDATA=0x{p_data:016x}, planned WSTRB=0x{strb:02x} strobed data "
            f"0x{data_exp:016x} unstrobed fill 0x{fill & ~active & ALL_LANES:016x}"
        )
        return p_data

    async def _zero_batch(self, port: SepMboxWalkPort, d: str, cases: list) -> None:
        """Push the filled batch with the WSTRB=0 write at its seeded position,
        grade STATUS after every push and pop, then pop and compare each entry."""
        mon = self.fills[d]
        pins = []
        exps = []
        for i, (kind, lo, n, data, fill) in enumerate(cases):
            chk = "CHK-MBX-ZERO-STROBE" if kind == "zero" else "CHK-MBX-ZERO-FILL"
            n0 = len(mon.beats)
            mon.arm(fill, 0 if kind == "zero" else None)
            try:
                await self._push(port, d, data, lo, n)
            finally:
                mon.disarm()
            if kind == "zero":
                strb, exp = 0, 0
            else:
                strb, exp = ((1 << n) - 1) << lo, strobe_image(data, lo, n)
            pins.append(self._pin_beat(chk, port, d, i, n0, strb, exp, fill))
            exps.append((strb, exp))
            await self._grade_depth(
                port, d, i + 1, f"after filled push {i + 1}", chk="CHK-MBX-ZERO-STROBE"
            )
        for i, (kind, lo, n, data, fill) in enumerate(cases):
            strb, exp = exps[i]
            got = await self._pop(port, d)
            inactive = ~_lanes(strb) & ALL_LANES
            if kind == "zero":
                self.zero_seen.append(
                    f"{port.m}.{d}@{i} 0x{strb:02x} 0x{pins[i]:016x} 0x{exp:016x} 0x{got:016x}"
                )
            else:
                self.fill_n += 1
                self.fill_pin_or |= pins[i] & inactive
                self.fill_pop_or |= got & inactive
            chk = "CHK-MBX-ZERO-STROBE" if kind == "zero" else "CHK-MBX-ZERO-FILL"
            self.logger.info(
                "%s compare: mailbox %d %s entry %d pin WSTRB=0x%02x WDATA=0x%016x "
                "expected 0x%016x popped 0x%016x",
                chk,
                port.m,
                d,
                i,
                strb,
                pins[i],
                exp,
                got,
            )
            assert got == exp, (
                f"{chk} FAIL: mailbox {port.m} {d} entry {i}: popped 0x{got:016x}, "
                f"expected 0x{exp:016x} (pins WSTRB=0x{strb:02x} WDATA=0x{pins[i]:016x}); "
                f"xor=0x{got ^ exp:016x}"
            )
            await self._grade_depth(
                port,
                d,
                len(cases) - i - 1,
                f"after filled pop {i + 1}",
                chk="CHK-MBX-ZERO-STROBE",
            )
        self.n_depth += 1

    async def _grade_depth(
        self, port: SepMboxWalkPort, d: str, q: int, when: str, chk: str = "CHK-MBX-DEPTH"
    ) -> None:
        """CHK-MBX-DEPTH at depth ``q``: the writing port's STATUS.full is set
        only at the FIFO depth, the reading port's STATUS.empty only at 0."""
        depth = self.cfg_walk.depth
        st_w = await self._write_status(port, d)
        st_r = await self._read_status(port, d)
        full = bool(st_w & ST_FULL)
        empty = bool(st_r & ST_EMPTY)
        assert full == (q == depth) and empty == (q == 0), (
            f"{chk} FAIL: mailbox {port.m} {d} {when}, {q} of {depth} entries "
            f"queued: writing port STATUS=0x{st_w:08x} full={int(full)} (expected "
            f"{int(q == depth)}), reading port STATUS=0x{st_r:08x} empty={int(empty)} "
            f"(expected {int(q == 0)})"
        )
        seen = self.depth_seen.setdefault(q, {})
        seen[(empty, full)] = seen.get((empty, full), 0) + 1
