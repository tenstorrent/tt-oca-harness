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
"""

from __future__ import annotations

import pyuvm
from sep_base_test import sep_base_test
from seq_lib.sep_axi_id_routing_seq import (
    ID_MAX,
    RESP_OKAY,
    SCRATCH_WORDS,
    SepAxiIdRouting,
)


@pyuvm.test()
class sep_axi_id_routing_test(sep_base_test):
    """Concurrent reads on distinct AXI IDs land on their own requests."""

    async def run_scenario(self) -> None:
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
        results = await idr.concurrent_reads(ids)
        assert len(results) == SCRATCH_WORDS, (
            f"CHK-ID-ROUTE FAIL: {len(results)} of {SCRATCH_WORDS} reads returned a result at all"
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
        assert not problems, (
            f"CHK-ID-ROUTE FAIL: {len(problems)} of {SCRATCH_WORDS} concurrent "
            f"reads did not get their own word: {problems[0]}"
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
        assert issued == list(range(ID_MAX + 1)), (
            f"CHK-ID-TOP FAIL: the reads covered IDs {issued}, not the whole "
            f"0..{ID_MAX} field the port carries. CHK-ID-ROUTE only compares the "
            "IDs it was given, so a short list would pass it while leaving the "
            "top of the ID field unexercised"
        )
        self.logger.info(
            "CHK-ID-TOP PASS: the routing compare covered every ID 0..%d the "
            "port's field carries, so no ID slot was left unexercised",
            ID_MAX,
        )
