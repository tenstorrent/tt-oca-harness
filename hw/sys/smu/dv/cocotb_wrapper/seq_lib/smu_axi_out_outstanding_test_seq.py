# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Several outbound transactions in flight at once on smu_axi_out.

The bench responder on ``u_axi_out_if`` is built with
``max_outstanding = DEPTH``: it accepts up to DEPTH writes and DEPTH reads
before it answers any, and it delays each B and R response by a seeded number
of cycles, holding back only later responses of the same ID. The SMC iDMA is
the bench-drivable master that issues back-to-back transactions: with CONFIG
``src_reduce_len`` and ``dst_reduce_len`` set and ``max_llen`` 0 its copy
crosses the boundary as one address phase per beat (``smu_axi_out_addr_len_size_test``
S3), and its master port is sized for ``smc_pkg::FabricMaxTrans`` transactions
in flight.

S1: the iDMA copies a 2 KiB block between two addresses outside the SMC and
    SEP apertures while every response is delayed. The destination holds the
    source and DONE reports the launch id; the reads and the writes in flight
    at once, counted at the wires from the address handshake to the RLAST or B
    handshake, each rise above 3 and never exceed DEPTH, and the responder's
    own peak occupancy is in the same range.
S2: over the same copy, every R beat carries the bytes the responder holds at
    the address of the oldest outstanding read of its RID, every B answers an
    outstanding write of its BID, and none is left outstanding afterwards: the
    responses lose, duplicate and reorder nothing within an ID.
"""

from __future__ import annotations

import random
from collections import defaultdict, deque

import cocotb
from cocotb.triggers import RisingEdge

from seq_lib.smu_axi_out_addr_len_size_test_seq import (
    DMA_CONFIG_SINGLE_BEAT,
    _OutboundTap,
    smu_axi_out_addr_len_size_test_seq,
)
from seq_lib.smu_filter_helpers import program_outbound0_pass_all

DEPTH = 8
# A transaction holds its slot for at least MIN_DELAY cycles, longer than the
# iDMA takes to issue DEPTH address phases back to back.
MIN_DELAY = 16
MAX_DELAY = 48
# More than this many in flight at once is the depth the responder adds.
FIXED_DEPTH = 3
COPY_SRC = 0x0800_0000
COPY_DST = 0x0900_0000
COPY_SEED = 41
BEAT_BYTES = 8


class _InFlight:
    """Outstanding transactions on u_axi_out_if, counted and paired per ID at the wires."""

    def __init__(self, dut, mem) -> None:
        self._if = dut.u_axi_out_if
        self._clk = dut.clk_smu_i
        self._mem = mem
        self.writes: dict[int, deque[None]] = defaultdict(deque)
        self.reads: dict[int, deque[list[int]]] = defaultdict(deque)
        self.peak = {"write": 0, "read": 0}
        self.counts = {"aw": 0, "ar": 0, "b": 0, "rlast": 0}
        self.mismatches: list[str] = []
        self._task = cocotb.start_soon(self._watch())

    def _int(self, name: str) -> int:
        val = getattr(self._if, name).value
        if not val.is_resolvable:
            raise AssertionError(f"X/Z on u_axi_out_if.{name}: {val}")
        return int(val)

    def _fire(self, channel: str) -> bool:
        return bool(self._int(f"{channel}valid")) and bool(self._int(f"{channel}ready"))

    def _beat_addresses(self) -> list[int]:
        addr, length, size = (self._int(f"ar{f}") for f in ("addr", "len", "size"))
        step = 1 << size
        base = addr & ~(step - 1)
        return [(base + beat * step) & ~(BEAT_BYTES - 1) for beat in range(length + 1)]

    def outstanding(self, kind: str) -> int:
        table = self.writes if kind == "write" else self.reads
        return sum(len(pending) for pending in table.values())

    async def _watch(self) -> None:
        while True:
            await RisingEdge(self._clk)
            if self._fire("aw"):
                self.counts["aw"] += 1
                self.writes[self._int("awid")].append(None)
            if self._fire("ar"):
                self.counts["ar"] += 1
                self.reads[self._int("arid")].append(self._beat_addresses())
            for kind in ("write", "read"):
                self.peak[kind] = max(self.peak[kind], self.outstanding(kind))
            if self._fire("b"):
                self.counts["b"] += 1
                bid = self._int("bid")
                if self.writes[bid]:
                    self.writes[bid].popleft()
                else:
                    self.mismatches.append(f"B id 0x{bid:x} with no write outstanding")
            if self._fire("r"):
                self._retire_read_beat()

    def _retire_read_beat(self) -> None:
        rid = self._int("rid")
        pending = self.reads[rid]
        if not pending:
            self.mismatches.append(f"R id 0x{rid:x} with no read outstanding")
            return
        beats = pending[0]
        addr = beats.pop(0)
        want = self._mem.read_int(addr, BEAT_BYTES)
        got = self._int("rdata")
        if got != want:
            self.mismatches.append(
                f"R id 0x{rid:x} @0x{addr:x} data 0x{got:016x} want 0x{want:016x}"
            )
        last = bool(self._int("rlast"))
        if last != (not beats):
            self.mismatches.append(f"R id 0x{rid:x} @0x{addr:x} RLAST={int(last)} out of place")
        if last:
            self.counts["rlast"] += 1
            pending.popleft()

    def stop(self) -> None:
        if not self._task.done():
            self._task.cancel()


class smu_axi_out_outstanding_test_seq(smu_axi_out_addr_len_size_test_seq):
    """An iDMA copy holds more than three reads and writes in flight on smu_axi_out."""

    def __init__(self, test) -> None:
        super().__init__(test)
        self.s1_ok = False
        self.s2_ok = False

    async def run(self) -> None:
        dut = self.dut
        sb = self.test.env.scoreboard
        mem = self.cfg.axi_out_mem
        await self.cfg.reset_done.wait()
        sb.expect_eq("smu_axi_out responder depth", mem.max_outstanding, DEPTH)
        jtag = await self._bring_up_tap()
        await program_outbound0_pass_all(jtag, scoreboard=sb)
        rng = random.Random(self.test.random_seed() ^ 0x0DE7_A11D)
        delays = iter(lambda: rng.randint(MIN_DELAY, MAX_DELAY), None)
        mem.set_response_delay(delays)
        tap = _InFlight(dut, mem)
        boundary = _OutboundTap(dut)
        try:
            done, start_id, payload, aw, ar = await self._dma_copy(
                jtag, sb, boundary, COPY_SRC, COPY_DST, COPY_SEED, DMA_CONFIG_SINGLE_BEAT
            )
        finally:
            mem.clear_response_delay()
            boundary.stop()
        # The last responses retire after DONE is read; let them drain.
        for _ in range(4 * MAX_DELAY):
            if not (tap.outstanding("write") or tap.outstanding("read")):
                break
            await RisingEdge(dut.clk_smu_i)
        tap.stop()
        dst = mem.read(COPY_DST, len(payload))
        reported = mem.outstanding_peak()
        self._log(
            f"OBSERVATION CHK-AXIOUT-OUTSTANDING wire peak={tap.peak} responder peak={reported} "
            f"handshakes={tap.counts} address phases aw={len(aw)} ar={len(ar)} "
            f"ids aw={sorted({p[4] for p in aw})} ar={sorted({p[4] for p in ar})}"
        )
        in_range = range(FIXED_DEPTH + 1, DEPTH + 1)
        sb.expect_eq(
            "CHK-AXIOUT-OUTSTANDING",
            (
                (done, dst.hex()),
                tap.peak["write"] in in_range,
                tap.peak["read"] in in_range,
                reported["write"] in in_range,
                reported["read"] in in_range,
            ),
            ((start_id, payload.hex()), True, True, True, True),
            evidence="CHK-AXIOUT-OUTSTANDING",
        )
        self.s1_ok = True
        sb.expect_eq(
            "CHK-AXIOUT-OUTSTANDING-ORDER",
            (
                tap.mismatches,
                tap.outstanding("write"),
                tap.outstanding("read"),
                tap.counts["aw"] == tap.counts["b"],
                tap.counts["ar"] == tap.counts["rlast"],
            ),
            ([], 0, 0, True, True),
            evidence="CHK-AXIOUT-OUTSTANDING-ORDER",
        )
        self.s2_ok = True
