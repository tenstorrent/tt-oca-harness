# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Every-clock trace of the ESRC SHA-256 whitener, and its exact 16 -> 8 count.

Contract: with whitening on, 16 input words give 8 digest words
(``hw/ip/entropy_source/doc/architecture.adoc:142``). ``SHA256_STATUS.INPUT_COUNT``
is the number of words in the open input block, ``OUTPUT_COUNT`` the digest words
left for output, and ``BUSY`` is set while a digest is in processing or output
(``hw/ip/entropy_source/regs/gen/adoc/entropy_source.adoc:206-209``).

Probes (``hw/sys/sep/dv/docs/SEP_TB_ARCH.adoc``): ``esrc_sha256_status_o`` (the
SHA256_STATUS fields on every clock: bit 0 BUSY, then INPUT_COUNT, then
OUTPUT_COUNT), ``esrc_whiten_push_o`` (one whitener input word) and
``esrc_compress_vld_o`` (one word written into the FIFO, architecture.adoc:148).

``quiet_span`` gives the counts between the first and the last quiet clock of the
trace. A quiet clock reads BUSY = 0 and OUTPUT_COUNT = 0, with no input or output
word within ``QUIET_GUARD`` clocks. At a quiet clock no digest is in processing
or in output, so every block that completes inside the span gives all its 8 words
inside the span, and the exact relation is

    2 x out_words == in_first + in_words - in_last

with ``in_first`` and ``in_last`` the INPUT_COUNT at the two quiet clocks.

``output_count_walk`` grades OUTPUT_COUNT step by step: it "reports 8 when a
digest becomes available, decrements through 0 as words are accepted"
(``entropy_source.adoc:206``). The FIFO write strobe has no backpressure
(``architecture.adoc:148``), so a word on the strobe is accepted on its clock. A
trace sample is taken after a rising edge, so a word on clock i - 1 is accepted
at the edge that starts clock i, and its decrement shows at clock i.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import ReadOnly, RisingEdge
from sep_reg_meta import ENTROPY_SOURCE

DIGEST_WORDS = 8
BLOCK_WORDS = 16
# A quiet clock has no input or output word within this many clocks on either side.
QUIET_GUARD = 2

_IN_BW = ENTROPY_SOURCE.fields("SHA256_STATUS")["INPUT_COUNT"]["bw"]
_OUT_BW = ENTROPY_SOURCE.fields("SHA256_STATUS")["OUTPUT_COUNT"]["bw"]
IN_SHIFT = 1
IN_MASK = (1 << _IN_BW) - 1
OUT_SHIFT = 1 + _IN_BW
OUT_MASK = (1 << _OUT_BW) - 1


class SepEsrcShaTap:
    """Every-clock reader of the SHA-256 status tap, the whitener input strobe and
    the FIFO write strobe.

    ``trace`` holds one ``(busy, output_count, input_count, pushes, words)`` per
    clock, with ``pushes`` and ``words`` the running counts including that clock.
    ``rd`` reads a DUT signal as int (``sep_base_test.rd``).
    """

    def __init__(self, rd) -> None:
        self.rd = rd
        self.dut = cocotb.top
        self.pushes = 0
        self.words = 0
        self.trace: list[tuple[int, int, int, int, int]] = []
        self.out_max = 0
        self.out_last = 0
        self.clocks = 0
        self._on = False
        self._task = None

    def start(self) -> SepEsrcShaTap:
        self._on = True
        self._task = cocotb.start_soon(self._run())
        return self

    async def stop(self) -> None:
        self._on = False
        if self._task is not None:
            await self._task
            self._task = None

    async def _run(self) -> None:
        rd = self.rd
        while self._on:
            await RisingEdge(self.dut.clk_i)
            await ReadOnly()
            self.clocks += 1
            status = rd(self.dut.esrc_sha256_status_o)
            out = (status >> OUT_SHIFT) & OUT_MASK
            self.out_max = max(self.out_max, out)
            self.out_last = out
            if rd(self.dut.esrc_whiten_push_o):
                self.pushes += 1
            if rd(self.dut.esrc_compress_vld_o):
                self.words += 1
            self.trace.append(
                (status & 1, out, (status >> IN_SHIFT) & IN_MASK, self.pushes, self.words)
            )

    def quiet_clocks(self) -> list[int]:
        """Trace indexes of the quiet clocks, in order."""
        tr = self.trace
        g = QUIET_GUARD
        quiet = []
        for i in range(g + 1, len(tr) - g):
            busy, out, _, _, _ = tr[i]
            if busy or out:
                continue
            before, after = tr[i - g - 1], tr[i + g]
            # No input or output strobe on the clocks i - g .. i + g.
            if after[3] == before[3] and after[4] == before[4]:
                quiet.append(i)
        return quiet

    def quiet_span(self) -> dict[str, int] | None:
        """Counts between the first and the last quiet clock; None with fewer than two."""
        quiet = self.quiet_clocks()
        if len(quiet) < 2:
            return None
        a, b = self.trace[quiet[0]], self.trace[quiet[-1]]
        return {
            "span_clk": quiet[-1] - quiet[0],
            "in_first": a[2],
            "in_last": b[2],
            "in_words": b[3] - a[3],
            "out_words": b[4] - a[4],
        }

    def quiet_after(self, index: int) -> bool:
        """True when a quiet clock lies after trace index ``index``."""
        return any(q > index for q in self.quiet_clocks())

    def output_count_steps(self) -> list[tuple[int, int, int, int]]:
        """One ``(clock, before, after, accepted)`` per clock i >= 1 where
        OUTPUT_COUNT changes or a word was accepted on clock i - 1.

        ``before`` and ``after`` are OUTPUT_COUNT at clocks i - 1 and i;
        ``accepted`` is the number of FIFO write strobes on clock i - 1 (0 or 1).
        """
        tr = self.trace
        steps = []
        for i in range(1, len(tr)):
            prev_words = tr[i - 2][4] if i >= 2 else 0
            accepted = tr[i - 1][4] - prev_words
            before, after = tr[i - 1][1], tr[i][1]
            if accepted or after != before:
                steps.append((i, before, after, accepted))
        return steps

    def output_count_walk(self) -> dict:
        """Grade every OUTPUT_COUNT step of a whitened trace (entropy_source.adoc:206).

        A step with an accepted word must be -1; a step without one must be the
        report of a new digest, 0 -> 8. A run starts at a 0 -> 8 step and is
        complete when OUTPUT_COUNT reaches 0; it must hold exactly 8 steps of -1.
        Steps before the first 0 -> 8 (a digest already in output at trace start)
        follow the same step rules but do not count as a run. ``errors`` lists
        each failed rule as ``(clock, before, after, accepted, rule)``.
        """
        errors: list[tuple[int, int, int, int, str]] = []
        runs: list[int] = []
        run_steps: int | None = None
        steps = self.output_count_steps()
        for clk, before, after, accepted in steps:
            if accepted:
                if after != before - 1:
                    errors.append((clk, before, after, accepted, "accepted_not_minus_1"))
                    run_steps = None
                    continue
                if run_steps is not None:
                    run_steps += 1
                    if after == 0:
                        runs.append(run_steps)
                        run_steps = None
            elif before == 0 and after == DIGEST_WORDS:
                run_steps = 0
            else:
                errors.append((clk, before, after, accepted, "change_without_word"))
                run_steps = None
        return {
            "steps": len(steps),
            "runs": runs,
            "open_run_steps": run_steps,
            "errors": errors,
        }
