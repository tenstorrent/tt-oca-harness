# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Generic AXI access sequence on a SEP master bus.

A thin reusable wrapper so higher-level drivers (KM mailbox, OTBN exec) can issue
one register read/write through the SEP AXI agent without redeclaring a sequence
each time. The result (``rdata`` / ``resp_ok``) is published on the sequence
object after ``start_seq``.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import RisingEdge
from env.sep_axi_agent import SepAxiItem, SepAxiOp
from pyuvm import uvm_sequence


async def capture_addr_handshake(channel: str, prefix: str = "s_axi") -> dict[str, int]:
    """AxADDR / AxLEN / AxSIZE / AxBURST of the next address handshake on a TB port.

    ``channel`` is ``"aw"`` or ``"ar"``. Start it with ``cocotb.start_soon``
    before the access, then read ``task.result()`` after it. The values are
    sampled from the testbench master port, so they show what the master
    presented, not what the DUT did with it.
    """
    dut = cocotb.top
    sig = {
        f: getattr(dut, f"{prefix}_{channel}{f}")
        for f in ("valid", "ready", "addr", "len", "size", "burst")
    }
    while True:
        await RisingEdge(dut.clk_i)
        if sig["valid"].value == 1 and sig["ready"].value == 1:
            return {f: int(sig[f].value) for f in ("addr", "len", "size", "burst")}


def take_handshake(task) -> dict[str, int] | None:
    """Result of a ``capture_addr_handshake`` task, or None when none was seen."""
    if task.done():
        return task.result()
    if hasattr(task, "cancel"):
        task.cancel()
    else:
        task.kill()
    return None


class SepAxiAccessSeq(uvm_sequence):
    """One AXI read or write; exposes ``rdata`` and ``resp_ok`` after running."""

    def __init__(
        self,
        name: str = "sep_axi_access",
        *,
        op: SepAxiOp = SepAxiOp.READ,
        addr: int = 0,
        wdata: int = 0,
        length: int = 4,
        size: int | None = None,
        allow_unverified_write_resp: bool = False,
        allow_ungraded_read_resp: bool = False,
        allow_timeout: bool = False,
        expected: int | None = None,
        expect_error: bool = False,
        user: int = 0,
        burst: int | None = None,
        axi_id: int = 0,
    ) -> None:
        super().__init__(name)
        self._op = op
        self._addr = addr
        self._wdata = wdata
        self._length = length
        self._size = size  # AXI AxSIZE encoding (2 => 4-byte beat); None => bus width
        # Tolerate a non-OKAY write response (the caller verifies by readback). Used
        # e.g. for a write-once-set bit whose clear-attempt is actively rejected
        # (SLVERR) once locked -- the proof is the read-back value, not the resp.
        self._allow_unverified_write_resp = allow_unverified_write_resp
        # Tolerate a non-OKAY read response on a read the specification refuses
        # without naming the code (the caller grades the data). Read-only.
        if allow_ungraded_read_resp and op is not SepAxiOp.READ:
            raise ValueError("allow_ungraded_read_resp applies to a read only")
        self._allow_ungraded_read_resp = allow_ungraded_read_resp
        # A non-completing read is an outcome the caller grades. Pair it with
        # allow_ungraded_read_resp so the scoreboard does not also fail the wedge.
        if allow_timeout and op is not SepAxiOp.READ:
            raise ValueError("allow_timeout on this sequence applies to a read only")
        self._allow_timeout = allow_timeout
        self._expected = expected
        # Negative-path probe: a non-OKAY response is the EXPECTED outcome (the caller
        # asserts the exact resp_code). The scoreboard then tolerates it instead of
        # failing, and fails a probe that wrongly returns OKAY (e.g. a read from an
        # empty mailbox FIFO must SLVERR).
        self._expect_error = expect_error
        # Packed AWUSER/ARUSER (inbound FILTER_CONFIG.src_id matches user[3:0]).
        self._user = user
        # AXI AxBURST. None = VIP default (single beat).
        self._burst = burst
        # AXI AxID. Default 0 matches every pre-existing caller.
        self._axi_id = axi_id
        self.rdata: int = 0
        self.resp_ok: bool = False
        self.resp_code: int = -1
        self.resp_list: tuple[int, ...] = ()
        self.timed_out: bool = False

    async def body(self) -> None:
        item = SepAxiItem(self.get_name())
        item.op = self._op
        item.addr = self._addr
        item.length = self._length
        item.wdata = self._wdata
        item.size = self._size
        item.allow_unverified_write_resp = self._allow_unverified_write_resp
        item.allow_ungraded_read_resp = self._allow_ungraded_read_resp
        item.allow_timeout = self._allow_timeout
        item.expected = self._expected
        item.expect_error = self._expect_error
        item.user = self._user
        item.burst = self._burst
        item.axi_id = self._axi_id
        await self.start_item(item)
        await self.finish_item(item)
        self.rdata = item.rdata
        self.resp_ok = item.resp_ok
        self.resp_code = item.resp_code
        self.resp_list = item.resp_list
        self.timed_out = item.timed_out
