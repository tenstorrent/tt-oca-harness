# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Register and data access to both ports of any SEP AXI-Lite mailbox.

``hw/sys/sep/doc/mailbox.adoc``: mailbox ``m`` occupies the 4 KiB at
``0x10A0_0000 + m * 0x1000``; the outbound port is at ``+0x000`` and the
inbound port at ``+0x800``. The CPU-LSU master (``s_axi``) drives the
outbound port. The SMN-inbound external master (``m_axi``) drives the inbound
port through an inbound filter window (``SEP_DBG`` off), with the AxPROT[1]
and the source ID (AxUSER[3:0]) that the caller states, because the filter
decides on them (``hw/ip/axi_filter/doc/index.adoc``, "Match, Then Permit").

Every access returns its AXI response code and read data and never asserts on
them: the leaf grades the response. The scoreboard is told that a non-OKAY
response may come (``allow_ungraded_read_resp`` / ``allow_unverified_write_resp``),
so the leaf's own check is the only judge. A caller that grades a response
compares :data:`RESP_OKAY`, :data:`RESP_SLVERR` or :data:`RESP_DECERR`.

``WRITE_DATA`` and ``READ_DATA`` take a 64-bit beat (AxSIZE 3, full strobe)
or a 32-bit beat at one half (AxSIZE 2, address bit 2 selects the half). Every
other register is one 32-bit beat at its offset. Offsets and field masks come
from ``env/sep_mbox_golden.py`` (generated register export); base addresses
from ``seq_lib/sep_mailbox_walk_seq.py``.

Pair this driver with ``env/sep_mbox_pair_model.MboxSystem``: issue the access
here, apply the same access to the model, and compare the DUT result with the
model.

Usage::

    ops = SepMboxPortOps(test, m=3, in_prot1=0, in_user=0)
    resp = await ops.push("in", 0x1122_3344_5566_7788)
    resp, data = await ops.pop("out")
    resp, st = await ops.rd("out", "STATUS")
"""

from __future__ import annotations

from env.sep_axi_agent import SepAxiOp
from env.sep_mbox_golden import (
    CTRL,
    ERROR_FLAGS,
    IRQEN,
    IRQP,
    IRQS,
    READ_DATA,
    RIRQT,
    STATUS,
    WIRQT,
    WRITE_DATA,
)

from seq_lib.sep_axi_access_seq import SepAxiAccessSeq
from seq_lib.sep_mailbox_walk_seq import MAILBOX_COUNT, inbound_base, outbound_base

RESP_OKAY = 0
RESP_SLVERR = 2
RESP_DECERR = 3
RESP_NAME = {0: "OKAY", 1: "EXOKAY", 2: "SLVERR", 3: "DECERR"}
SIZE_4B = 2
SIZE_8B = 3
PROT_NS_BIT = 1
MASK64 = (1 << 64) - 1

REG_OFFSETS = {
    "WRITE_DATA": WRITE_DATA,
    "READ_DATA": READ_DATA,
    "STATUS": STATUS,
    "ERROR_FLAGS": ERROR_FLAGS,
    "WIRQT": WIRQT,
    "RIRQT": RIRQT,
    "IRQS": IRQS,
    "IRQEN": IRQEN,
    "IRQP": IRQP,
    "CTRL": CTRL,
}


def port_base(m: int, port: str) -> int:
    """Base address of the ``port`` ("out" or "in") aperture of mailbox ``m``."""
    if not 0 <= m < MAILBOX_COUNT:
        raise IndexError(f"mailbox {m} out of range 0..{MAILBOX_COUNT - 1}")
    if port == "out":
        return outbound_base(m)
    if port == "in":
        return inbound_base(m)
    raise ValueError(f"port must be 'out' or 'in', got {port!r}")


def resp_name(code: int) -> str:
    return RESP_NAME.get(code, f"resp{code}")


class SepMboxPortOps:
    """Both ports of mailbox ``m``. The outbound port goes on the CPU-LSU
    master; the inbound port on the external master with ``in_prot1`` and
    ``in_user`` unless an access passes its own."""

    def __init__(self, test, m: int, *, in_prot1: int = 0, in_user: int = 0) -> None:
        self.test = test
        self.m = m
        self.in_prot1 = in_prot1
        self.in_user = in_user
        self.log = test.logger

    def addr(self, port: str, reg: str, *, half: int = 0) -> int:
        """Address of ``reg`` on ``port``; ``half`` 1 adds 4 (upper 32 bits)."""
        return port_base(self.m, port) + REG_OFFSETS[reg] + 4 * half

    async def raw(
        self,
        port: str,
        op: SepAxiOp,
        addr: int,
        *,
        wdata: int = 0,
        size: int = SIZE_4B,
        prot1: int | None = None,
        user: int | None = None,
        axi_id: int = 0,
    ) -> tuple[int, int]:
        """One single-beat access at ``addr`` through the master of ``port``.

        Returns (response code, read data). The read data of a 32-bit access is
        the 32 bits at ``addr``; of a 64-bit access, the 64-bit word.
        """
        nbytes = 1 << size
        kw: dict = {
            "op": op,
            "addr": addr,
            "length": nbytes,
            "size": size,
            "axi_id": axi_id,
        }
        if op is SepAxiOp.READ:
            kw["allow_ungraded_read_resp"] = True
        else:
            kw["wdata"] = wdata & ((1 << (8 * nbytes)) - 1)
            kw["allow_unverified_write_resp"] = True
        if port == "in":
            p1 = self.in_prot1 if prot1 is None else prot1
            kw["prot"] = (p1 & 1) << PROT_NS_BIT
            kw["user"] = self.in_user if user is None else user
            seq = SepAxiAccessSeq(f"mbx{self.m}_in", **kw)
            await self.test.start_ext_seq(seq)
        else:
            seq = SepAxiAccessSeq(f"mbx{self.m}_out", **kw)
            await self.test.start_seq(seq)
        mask = (1 << (8 * nbytes)) - 1
        return seq.resp_code, seq.rdata & mask

    async def push(self, port: str, data: int, *, half: int | None = None, **kw) -> int:
        """``WRITE_DATA`` write: 64-bit full strobe, or 32 bits at ``half``."""
        if half is None:
            resp, _ = await self.raw(
                port, SepAxiOp.WRITE, self.addr(port, "WRITE_DATA"), wdata=data, size=SIZE_8B, **kw
            )
        else:
            resp, _ = await self.raw(
                port,
                SepAxiOp.WRITE,
                self.addr(port, "WRITE_DATA", half=half),
                wdata=data,
                size=SIZE_4B,
                **kw,
            )
        return resp

    async def pop(self, port: str, *, half: int | None = None, **kw) -> tuple[int, int]:
        """``READ_DATA`` read: 64-bit, or 32 bits at ``half``. (resp, data)."""
        if half is None:
            return await self.raw(
                port, SepAxiOp.READ, self.addr(port, "READ_DATA"), size=SIZE_8B, **kw
            )
        return await self.raw(
            port, SepAxiOp.READ, self.addr(port, "READ_DATA", half=half), size=SIZE_4B, **kw
        )

    async def rd(self, port: str, reg: str, **kw) -> tuple[int, int]:
        """32-bit read of ``reg``. (resp, data)."""
        return await self.raw(port, SepAxiOp.READ, self.addr(port, reg), size=SIZE_4B, **kw)

    async def wr(self, port: str, reg: str, value: int, **kw) -> int:
        """32-bit write of ``reg``. Returns the response."""
        resp, _ = await self.raw(
            port, SepAxiOp.WRITE, self.addr(port, reg), wdata=value, size=SIZE_4B, **kw
        )
        return resp

    async def rd_ok(self, port: str, reg: str, what: str = "", **kw) -> int:
        """32-bit read that must answer OKAY (a set-up read, not a graded one)."""
        resp, data = await self.rd(port, reg, **kw)
        if resp != RESP_OKAY:
            raise AssertionError(
                f"MBX-SETUP FAIL: mailbox {self.m} {port} {reg} read answered "
                f"{resp_name(resp)} {what}".rstrip()
            )
        return data

    async def wr_ok(self, port: str, reg: str, value: int, what: str = "", **kw) -> None:
        """32-bit write that must answer OKAY (a set-up write, not a graded one)."""
        resp = await self.wr(port, reg, value, **kw)
        if resp != RESP_OKAY:
            raise AssertionError(
                f"MBX-SETUP FAIL: mailbox {self.m} {port} {reg}=0x{value:x} answered "
                f"{resp_name(resp)} {what}".rstrip()
            )


def ports(test, *, in_prot1: int = 0, in_user: int = 0) -> list[SepMboxPortOps]:
    """One :class:`SepMboxPortOps` per mailbox."""
    return [
        SepMboxPortOps(test, m, in_prot1=in_prot1, in_user=in_user) for m in range(MAILBOX_COUNT)
    ]


__all__ = [
    "MAILBOX_COUNT",
    "REG_OFFSETS",
    "RESP_DECERR",
    "RESP_OKAY",
    "RESP_SLVERR",
    "SepMboxPortOps",
    "port_base",
    "ports",
    "resp_name",
]
