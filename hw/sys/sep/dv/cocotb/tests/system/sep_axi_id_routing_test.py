# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""AXI transaction IDs: each response comes back to the request that owns it.

no_cpu / +skip_fuse_sense.

The SEP crossbars prepend the master index to the incoming ``AxID`` and the
demux keeps one outstanding counter per ID, so the ID field is address-like
state on the response path. A master matches responses by ID, so an ID that is
mangled, truncated, or dropped hands a read's data to a different outstanding
request -- and every access answers OKAY while it happens.

Eight scratch words are primed with eight distinct values, then read back with
eight reads outstanding at once, one per ID. Each read must return the value of
its OWN word. The per-word value names the word, so a misrouted response is
reported with where it actually came from rather than as a bare mismatch.

The top ID is included on purpose: an ID field carried only in its low bits
still completes every access, and only a compare on the top-ID read shows that
it did not alias onto a lower slot.

FCOV: the owner window of this leaf (``sep_axi_decode_cg.cp_id_return``)
opens after CHK-ID-PRIME passed and before the concurrent reads, and closes
after CHK-ID-TOP, or before the first FAIL raises. The prime writes and reads
are outside it. The sampler takes an R beat only when its data equals the last
value the LSU wrote to the address of the AR with that RID, the per-beat
compare of CHK-ID-ROUTE, and marks the beat when eight reads were outstanding,
the depth CHK-ID-OVERLAP grades.
"""

from __future__ import annotations

import cocotb
import pyuvm
from cocotb.triggers import ClockCycles, RisingEdge
from env.sep_fcov_gate import close_graded_window, open_graded_window
from sep_base_test import sep_base_test
from seq_lib.sep_axi_id_routing_seq import (
    ID_MAX,
    RESP_OKAY,
    SCRATCH_WORDS,
    SepAxiIdRouting,
    _bit,
    _hs,
)

TEST = "sep_axi_id_routing_test"

# clk_i edges between the last R beat and the close of the window, so the
# close never falls in the clock of a beat that the sampler counts.
WINDOW_HOLD_CYCLES = 2


@pyuvm.test()
class sep_axi_id_routing_test(sep_base_test):
    """Concurrent reads on distinct AXI IDs land on their own requests."""

    async def _watch_rid_order(self, order: list[int]) -> None:
        """Append the RID of each last R beat on the LSU port, in arrival order."""
        dut = cocotb.top
        while True:
            await RisingEdge(dut.clk_i)
            if _hs(dut.s_axi_rvalid, dut.s_axi_rready) and _bit(dut.s_axi_rlast):
                order.append(int(dut.s_axi_rid.value))

    def _grade(self, ok: bool, msg: str) -> None:
        """On a FAIL, close the owner window first, then raise."""
        if not ok:
            close_graded_window(self.logger)
            raise AssertionError(msg)

    async def run_scenario(self) -> None:
        try:
            await self._scenario()
        finally:
            close_graded_window(self.logger)

    async def _scenario(self) -> None:
        await self.bring_up_no_cpu()
        idr = SepAxiIdRouting(self)

        # --- CHK-ID-PRIME -----------------------------------------------------
        bad = await idr.prime()
        assert not bad, (
            f"CHK-ID-PRIME FAIL: {len(bad)} of {SCRATCH_WORDS} scratch words did "
            f"not hold their own value; first: {bad[0]}. The routing compare "
            "below needs eight distinct values in eight independent words"
        )
        self.logger.info(
            "CHK-ID-PRIME PASS: %d scratch words each hold their own distinct "
            "value, so a misrouted response can be told from a correct one",
            SCRATCH_WORDS,
        )

        # --- CHK-ID-ROUTE -----------------------------------------------------
        # ids[k] reads word k. The identity mapping is the simplest one that
        # keeps every ID in use; what makes the check meaningful is that the
        # eight reads are outstanding together, so there are eight responses
        # in flight for the fabric to place.
        ids = list(range(SCRATCH_WORDS))
        open_graded_window(TEST, self.logger)
        rid_order: list[int] = []
        order_watch = cocotb.start_soon(self._watch_rid_order(rid_order))
        results = await idr.concurrent_reads(ids)
        await ClockCycles(cocotb.top.clk_i, WINDOW_HOLD_CYCLES)
        order_watch.kill()
        # Not graded: no SEP document states whether responses on different
        # IDs may return in an order other than the AR order, so the arrival
        # order is logged only.
        self.logger.info(
            "OBS-ID-RETURN-ORDER: issued=%s returned=%s in_issue_order=%d",
            ids,
            rid_order,
            int(rid_order == ids),
        )
        self._grade(
            len(results) == SCRATCH_WORDS,
            f"CHK-ID-ROUTE FAIL: {len(results)} of {SCRATCH_WORDS} reads returned a result at all",
        )

        # The routing compare above is only meaningful while the responses are
        # in flight together: an ID truncated to N bits aliases k onto k+2**N,
        # and a bus that retires each read before accepting the next answers
        # every access correctly whatever it does to the ID. ids are issued in
        # order, so a depth of d proves ids 0..d-1 were live at once; the whole
        # set overlapping is what puts every aliasing pair under the compare.
        self._grade(
            idr.max_outstanding == SCRATCH_WORDS,
            f"CHK-ID-OVERLAP FAIL: the bus reached {idr.max_outstanding} outstanding "
            f"read(s), not {SCRATCH_WORDS}; with the reads serialized the ID compare "
            "below passes on a truncated ID field and proves nothing",
        )
        self.logger.info(
            "CHK-ID-OVERLAP PASS: %d reads outstanding at once, so every "
            "aliasing ID pair was in flight together",
            idr.max_outstanding,
        )

        problems: list[str] = []
        for axi_id, idx, resp, data in results:
            want = idr.value_for(idx)
            if resp == -1:
                problems.append(f"id={axi_id} word{idx} never returned")
                continue
            if resp != RESP_OKAY:
                problems.append(f"id={axi_id} word{idx} resp={resp}")
                continue
            if data != want:
                source = next(
                    (j for j in range(SCRATCH_WORDS) if idr.value_for(j) == data),
                    None,
                )
                came_from = f"word{source}" if source is not None else "no primed word"
                problems.append(
                    f"id={axi_id} asked for word{idx} (0x{want:08x}) and got "
                    f"0x{data:08x}, which is {came_from}"
                )
        self._grade(
            not problems,
            f"CHK-ID-ROUTE FAIL: {len(problems)} of {SCRATCH_WORDS} concurrent "
            f"reads did not get their own word: {problems[0] if problems else ''}",
        )
        self.logger.info(
            "CHK-ID-ROUTE PASS: %d reads outstanding together on IDs 0..%d each "
            "returned the value of its own word",
            SCRATCH_WORDS,
            ID_MAX,
        )

        # --- CHK-ID-TOP -------------------------------------------------------
        # A breadth guard on the stimulus, not a second routing claim: the
        # routing compare above already covers every ID it was given, so what
        # this grades is that the set GIVEN reached the top of the ID field.
        # An ID field carried in too few bits only shows up as a data mismatch
        # if a read was actually issued on the top ID, and a future edit that
        # shortened the ID list would leave CHK-ID-ROUTE passing over a subset
        # with nothing to say so.
        issued = sorted(axi_id for axi_id, _, _, _ in results)
        self._grade(
            issued == list(range(ID_MAX + 1)),
            f"CHK-ID-TOP FAIL: the reads covered IDs {issued}, not the whole "
            f"0..{ID_MAX} field the port carries. CHK-ID-ROUTE only compares the "
            "IDs it was given, so a short list would pass it while leaving the "
            "top of the ID field unexercised",
        )
        self.logger.info(
            "CHK-ID-TOP PASS: the routing compare covered every ID 0..%d the "
            "port's field carries, so no ID slot was left unexercised",
            ID_MAX,
        )
        close_graded_window(self.logger)
