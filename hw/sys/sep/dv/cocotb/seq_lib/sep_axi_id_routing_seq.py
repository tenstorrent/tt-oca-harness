# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Concurrent reads on distinct AXI IDs, and where each response lands.

Every access defaults to ``AxID = 0`` (``SepAxiItem.axi_id``), so the
transaction-ID dimension of the SEP crossbars is exercised only where a test
sets it. That dimension matters: the crossbar prepends the master index
to the incoming ID and the demux keeps one outstanding counter per ID, so the
whole ID field is address-like state on the response path.

What that state can get wrong, and what this sequence is built to catch:

* A response returned under the wrong ID. The master matches responses by ID,
  so a mangled or truncated ID delivers a read's data to a different
  outstanding request.
* An ID field carried only in its low bits. Any access on the top ID still
  completes, but it aliases onto a lower slot, so two "different" IDs share
  one counter.

Both need SEVERAL reads outstanding at once, each on its own ID and each from
a location holding a DIFFERENT value: with one access in flight there is only
one response to deliver and any routing would look correct. The per-ID value
is what turns a routing defect into a data mismatch.

The concurrency comes from calling the VIP master sequence directly, the way
``sep_axi_concurrent_rw_seq`` does. The SEP AXI sequencer awaits each item to
completion, so nothing overlaps through it.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import RisingEdge
from sep_reg_meta import sym

from seq_lib.sep_axi_reg_driver import SepAxiRegDriver

# SCRATCH_COLD is eight independent R/W registers in one block, which is one
# location per ID on a 3-bit port with no aliasing between them. Each address
# comes from its own generated symbol: the registers are 64-bit and sit on an
# 8-byte stride, so a base-plus-4*index walk addresses the upper half of every
# other one and reads zero there.
SCRATCH_ADDRS = tuple(sym(f"SEP_SCRATCH_COLD_SCRATCH_{i}__REG_ADDR") for i in range(8))
SCRATCH_WORDS = len(SCRATCH_ADDRS)

RESP_OKAY = 0


def _bit(sig) -> bool:
    """One signal bit, with X/Z read as 0 (no handshake).

    Used only for the outstanding-depth measurement.
    """
    try:
        return bool(int(sig.value))
    except ValueError:
        return False


def _hs(valid, ready) -> bool:
    """A handshake completed on this edge."""
    return _bit(valid) and _bit(ready)


# The TB drives the SEP slave port, whose AXI ID is 3 bits wide
# (tb_top.sv ocah_axi_sva ID_WIDTH for s_axi), so 0..7 is the whole field and
# 7 is the top of it.
ID_WIDTH = 3
ID_MAX = (1 << ID_WIDTH) - 1

_READ_TIMEOUT_NS = 20_000


def _selftest() -> None:
    # Pinned against the generated header so a register-layout change fails at
    # import rather than as reads of an unwritable upper half mid-simulation.
    assert SCRATCH_WORDS == 8
    assert SCRATCH_ADDRS[0] == 0x1080_2000
    strides = {b - a for a, b in zip(SCRATCH_ADDRS, SCRATCH_ADDRS[1:])}
    assert strides == {8}, f"SCRATCH_COLD stride is not 8 bytes: {strides}"


_selftest()


class SepAxiIdRouting(SepAxiRegDriver):
    """Primes one scratch word per ID, then reads them all at once."""

    _DRIVER_TAG = "AXI-ID"

    # Deepest AR-accepted-minus-R-returned depth concurrent_reads() observed.
    # Zero until it has run, so a caller grading it cannot read a stale pass.
    max_outstanding = 0

    @staticmethod
    def addr_for(idx: int) -> int:
        return SCRATCH_ADDRS[idx]

    @staticmethod
    def value_for(idx: int) -> int:
        """A value that names its own word, so a response that arrives under
        the wrong ID carries a value that identifies where it came from."""
        return 0xA5_00_0000 | ((idx + 1) << 8) | (idx + 1)

    def _master(self):
        """The VIP master sequence, bypassing the one-item-at-a-time sequencer.

        Raises rather than returning None: without it nothing overlaps, and a
        walk of sequential single accesses would report ID routing it never
        put under stress.
        """
        seq = getattr(getattr(self.test.env.axi_agent, "driver", None), "axi", None)
        if seq is None or not hasattr(seq, "read_bytes_result"):
            raise RuntimeError(
                "no VIP master sequence behind env.axi_agent.driver.axi; the "
                "ID walk cannot hold several reads outstanding and would "
                "report routing it never exercised"
            )
        return seq

    async def prime(self) -> list[str]:
        """Write the per-word values and read each back. Returns mismatches.

        The readback is not redundant with the concurrent leg: it establishes
        that the eight words are independent storage holding eight distinct
        values. Without it a block that aliased every word onto one register
        would make the routing compare pass for the one ID whose value
        happened to be last written.
        """
        bad: list[str] = []
        for idx in range(SCRATCH_WORDS):
            await self._wr(self.addr_for(idx), self.value_for(idx))
        for idx in range(SCRATCH_WORDS):
            got = await self._rd(self.addr_for(idx))
            if got != self.value_for(idx):
                bad.append(
                    f"word{idx} @0x{self.addr_for(idx):08x} read 0x{got:08x}, "
                    f"wrote 0x{self.value_for(idx):08x}"
                )
        return bad

    async def concurrent_reads(self, ids: list[int]) -> list[tuple[int, int, int, int]]:
        """Hold one read per ID outstanding at once.

        ``ids[k]`` reads word ``k``, so the ID and the expected value are
        independent of each other and a response delivered under the wrong ID
        carries a value that names the word it really came from. Returns
        (axi_id, word index, resp, data); resp is -1 when nothing returned.
        """
        master = self._master()
        # The overlap is the contract, not a side effect: an ID field carried
        # in too few bits still answers every access, and only a response that
        # is in flight beside its aliasing partner can expose the truncation.
        # The LSU demux bounds outstanding transactions, so the depth this bus
        # actually reaches is measured rather than assumed.
        watch = cocotb.start_soon(self._watch_outstanding())
        tasks = [
            cocotb.start_soon(
                master.read_bytes_result(
                    self.addr_for(idx),
                    4,
                    size=2,
                    id=axi_id,
                    check_response=False,
                    timeout_ns=_READ_TIMEOUT_NS,
                    allow_timeout=True,
                )
            )
            for idx, axi_id in enumerate(ids)
        ]
        out: list[tuple[int, int, int, int]] = []
        for idx, (axi_id, task) in enumerate(zip(ids, tasks)):
            res = await task
            if res.timed_out:
                out.append((axi_id, idx, -1, 0))
                continue
            data = int.from_bytes(res.data_bytes, "little") if res.data_bytes else res.data
            out.append((axi_id, idx, res.resp, data))
        watch.kill()
        return out

    async def _watch_outstanding(self) -> None:
        """Track the deepest AR-accepted-minus-R-returned the bus reaches."""
        dut = cocotb.top
        self.max_outstanding = 0
        live = 0
        while True:
            await RisingEdge(dut.clk_i)
            if _hs(dut.s_axi_arvalid, dut.s_axi_arready):
                live += 1
                self.max_outstanding = max(self.max_outstanding, live)
            if _hs(dut.s_axi_rvalid, dut.s_axi_rready) and _bit(dut.s_axi_rlast):
                live -= 1
