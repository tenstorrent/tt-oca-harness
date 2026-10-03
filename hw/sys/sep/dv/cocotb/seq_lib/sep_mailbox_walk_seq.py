# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Mailbox datapath walk: config, golden FIFO and the two port drivers.

``hw/sys/sep/doc/mailbox.adoc``: mailbox *m* occupies the 4 kB at
``0x10A0_0000 + m * 0x1000``, outbound port at ``+0x000`` and inbound port at
``+0x800``. Each mailbox holds two FIFOs of eight 64-bit entries, and
``WRITE_DATA`` in one port pushes the FIFO that ``READ_DATA`` in the other
port pops. A write of ``WRITE_DATA`` pushes one entry, "with bytes outside
the write strobe pushed as zero".

The outbound (host) port is driven by the CPU-LSU master. The inbound (peer)
port is reached only by the SMN-inbound external master, through the inbound
filter. The two port apertures interleave, so a window from inbound mailbox 0
to inbound mailbox 7 also holds the outbound ports of mailboxes 1 to 7. The
walk therefore opens a window over exactly one inbound port at a time.

Every base address comes from the generated register export, by mailbox
index, so a map change moves it here too.
"""

from __future__ import annotations

from env.sep_axi_agent import SepAxiOp
from env.sep_mbox_golden import (
    MAILBOX_DEPTH,
    READ_DATA,
    ST_EMPTY,
    ST_FULL,
    STATUS,
    WRITE_DATA,
)
from env.sep_seeded_rng import SepSeededRng
from sep_reg_meta import indexed_block_count, sym

from seq_lib.sep_axi_access_seq import SepAxiAccessSeq
from seq_lib.sep_inbound_attr_seq import SepInboundAttrs, SepInboundAttrTally

MAILBOX_COUNT = indexed_block_count("AXIL_MAILBOX_OUTBOUND_MAILBOX")
WORD_BITS = 64
WORD_BYTES = WORD_BITS // 8
MASK64 = (1 << WORD_BITS) - 1
RESP_OKAY = 0
# AXI4 AxSIZE for an 8-byte beat.
SIZE_8B = 3


def outbound_base(m: int) -> int:
    return sym(f"AXIL_MAILBOX_OUTBOUND_MAILBOX_{m}_REG_MAP_BASE_ADDR")


def inbound_base(m: int) -> int:
    return sym(f"AXIL_MAILBOX_INBOUND_MAILBOX_{m}_REG_MAP_BASE_ADDR")


def inbound_last(m: int) -> int:
    """Last byte of the inbound port's register map."""
    return inbound_base(m) + sym(f"AXIL_MAILBOX_INBOUND_MAILBOX_{m}_REG_MAP_SIZE") - 1


def walking_one(bit: int) -> int:
    return 1 << bit


def walking_zero(bit: int) -> int:
    return MASK64 ^ (1 << bit)


def strobe_image(data: int, offset: int, nbytes: int) -> int:
    """The entry a push of ``nbytes`` at byte ``offset`` enqueues: the strobed
    bytes of ``data`` in their lanes, every other byte zero (mailbox.adoc)."""
    mask = ((1 << (8 * nbytes)) - 1) << (8 * offset)
    return (data << (8 * offset)) & mask


class SepMboxWalkCfg:
    """Single source of truth for the walk: mailbox order, pattern rotation and
    the strobe cases. Every mailbox, every bit position and both directions
    are walked on every seed; the seed picks only the order, the rotation,
    the strobe runs, the strobe data and the inbound request attributes."""

    def __init__(self, seed: int, *, depth: int = MAILBOX_DEPTH) -> None:
        self.seed = seed
        self.depth = depth
        rng = SepSeededRng(seed)
        self.rng = rng
        order = list(range(MAILBOX_COUNT))
        for i in range(len(order) - 1, 0, -1):
            j = rng.randrange(0, i + 1)
            order[i], order[j] = order[j], order[i]
        self.order = order
        # One rotation per (mailbox, direction): the walk starts at a seeded
        # bit and still visits all 64.
        self.rot = {(m, d): rng.randrange(WORD_BITS) for m in order for d in ("h2p", "p2h")}
        # Strobe cases: one FIFO-depth batch per (mailbox, direction). Entry j
        # strobes a contiguous run that contains byte lane j, so every lane is
        # strobed in every batch and lanes outside a run read back zero.
        self.strobes: dict[tuple[int, str], list[tuple[int, int, int]]] = {}
        for m in order:
            for d in ("h2p", "p2h"):
                cases = []
                for j in range(depth):
                    lane = j % WORD_BYTES
                    lo = rng.randrange(0, lane + 1)
                    hi = rng.randrange(lane, WORD_BYTES)
                    n = hi - lo + 1
                    data = rng.getrandbits(8 * n) | (1 << (8 * (lane - lo)))
                    cases.append((lo, n, data))
                self.strobes[(m, d)] = cases

    def patterns(self, m: int, d: str) -> list[int]:
        """Walking one then walking zero over all 64 bits, from the seeded bit."""
        r = self.rot[(m, d)]
        bits = [(r + i) % WORD_BITS for i in range(WORD_BITS)]
        return [walking_one(b) for b in bits] + [walking_zero(b) for b in bits]

    def summary(self) -> str:
        return (
            f"seed={self.seed} mailboxes={MAILBOX_COUNT} depth={self.depth} "
            f"order={self.order} words/dir={2 * WORD_BITS} "
            f"strobe_cases/dir={self.depth}"
        )


class SepMboxWalkPort:
    """Both ports of one mailbox. Host = outbound port on the CPU-LSU master;
    peer = inbound port on the external master with seeded attributes. Every
    access returns its response, and every peer access also its response ID,
    so the caller grades both."""

    def __init__(self, test, m: int, rng: SepSeededRng, tally: SepInboundAttrTally) -> None:
        self.test = test
        self.m = m
        self.host = outbound_base(m)
        self.peer = inbound_base(m)
        self.rng = rng
        self.tally = tally

    def _attrs(self, *, write: bool) -> SepInboundAttrs:
        a = SepInboundAttrs(self.rng, write=write, lock_ok=True)
        self.tally.add(a)
        return a

    async def host_push(self, value: int, *, offset: int = 0, nbytes: int = WORD_BYTES) -> int:
        seq = SepAxiAccessSeq(
            "mbx_walk_host_push",
            op=SepAxiOp.WRITE,
            addr=self.host + WRITE_DATA + offset,
            wdata=value,
            length=nbytes,
            size=SIZE_8B,
            allow_unverified_write_resp=True,
        )
        await self.test.start_seq(seq)
        return seq.resp_code

    async def host_pop(self) -> tuple[int, int]:
        seq = SepAxiAccessSeq(
            "mbx_walk_host_pop",
            op=SepAxiOp.READ,
            addr=self.host + READ_DATA,
            length=WORD_BYTES,
            size=SIZE_8B,
        )
        await self.test.start_seq(seq)
        return seq.resp_code, seq.rdata & MASK64

    async def host_status(self) -> int:
        seq = SepAxiAccessSeq(
            "mbx_walk_host_status",
            op=SepAxiOp.READ,
            addr=self.host + STATUS,
            length=WORD_BYTES,
            size=SIZE_8B,
        )
        await self.test.start_seq(seq)
        assert seq.resp_code == RESP_OKAY, (
            f"mailbox {self.m} host STATUS read @0x{self.host + STATUS:08x} "
            f"answered resp={seq.resp_code}, expected OKAY"
        )
        return seq.rdata

    async def peer_push(
        self, value: int, *, offset: int = 0, nbytes: int = WORD_BYTES
    ) -> tuple[int, int | None, SepInboundAttrs]:
        a = self._attrs(write=True)
        seq = SepAxiAccessSeq(
            "mbx_walk_peer_push",
            op=SepAxiOp.WRITE,
            addr=self.peer + WRITE_DATA + offset,
            wdata=value,
            length=nbytes,
            size=SIZE_8B,
            allow_unverified_write_resp=True,
            **a.kwargs(),
        )
        await self.test.start_ext_seq(seq)
        return seq.resp_code, seq.resp_id, a

    async def peer_pop(self) -> tuple[int, int, int | None, SepInboundAttrs]:
        a = self._attrs(write=False)
        seq = SepAxiAccessSeq(
            "mbx_walk_peer_pop",
            op=SepAxiOp.READ,
            addr=self.peer + READ_DATA,
            length=WORD_BYTES,
            size=SIZE_8B,
            allow_ungraded_read_resp=True,
            **a.kwargs(),
        )
        await self.test.start_ext_seq(seq)
        return seq.resp_code, seq.rdata & MASK64, seq.resp_id, a

    async def peer_status(self) -> int:
        a = self._attrs(write=False)
        seq = SepAxiAccessSeq(
            "mbx_walk_peer_status",
            op=SepAxiOp.READ,
            addr=self.peer + STATUS,
            length=WORD_BYTES,
            size=SIZE_8B,
            allow_ungraded_read_resp=True,
            **a.kwargs(),
        )
        await self.test.start_ext_seq(seq)
        assert seq.resp_code in a.ok_resps(), (
            f"mailbox {self.m} peer STATUS read @0x{self.peer + STATUS:08x} "
            f"({a}) answered resp={seq.resp_code}; the window or the peer path "
            "is not open, and a refused read must not be read as a status"
        )
        assert seq.resp_id == a.axi_id, (
            f"CHK-MBX-RESP-ID FAIL: mailbox {self.m} peer STATUS read issued ID "
            f"0x{a.axi_id:02x} and the response carried ID {seq.resp_id}"
        )
        self.tally.graded_resp(a, seq.resp_code)
        return seq.rdata


__all__ = [
    "MAILBOX_COUNT",
    "RESP_OKAY",
    "ST_EMPTY",
    "ST_FULL",
    "SepMboxWalkCfg",
    "SepMboxWalkPort",
    "inbound_base",
    "inbound_last",
    "outbound_base",
    "strobe_image",
]
