# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Frontdoor per-IP reset pulses for the `sep_cov_*_reset_*` stimulus leaves.

Stimulus only. Nothing here compares a read value against an expectation.

Why a reset pulse is coverage stimulus: an FSM whose state flop takes its
reset value scores that transition in VCS exactly like a `case`-arm assignment.
The arcs `<any running state> -> <reset state>` have no `case` arm anywhere in
the SEP tree, so a reset applied while the FSM is running is the only stimulus
that takes them.

The reset used is the architected per-IP software reset: `SW_RESET_N` in
`sep_reset_ctrl` (`hw/sys/sep/regs/blocks/sep_reset_ctrl/sep_reset_ctrl.rdl`),
active-low, one bit per engine. Clearing a bit raises that engine's isolate
request (`hw/sys/sep/rtl/sep_reset_ctrl.sv:155-238`); `sep_isolate_rst_seq`
waits for the host and KM AXI ports to report isolated and only then drops the
engine's `gated_rst_no`, which is the engine wrapper's `rst_ni`. So the CSR
write is a legal frontdoor request and the hardware picks the safe moment.

Safety: every pulse releases the engine before it returns, and
:meth:`SepCovEngineReset.restore` puts `SW_RESET_N` back to the value the leaf
started from. A leaf calls `restore` from a `finally`, so an engine is never
left held in reset for whatever runs next in the same regression.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import ClockCycles
from env.sep_seeded_rng import SepSeededRng

from seq_lib.sep_sw_reset_seq import SepSwReset

__all__ = ["SepCovEngineReset"]


class SepCovEngineReset:
    """Pulse one engine's `SW_RESET_N` bit while that engine is running."""

    def __init__(self, test, engine: str, *, settle_cycles: int = 400) -> None:
        self.test = test
        self.engine = engine
        self.settle_cycles = settle_cycles
        self.log = test.logger
        self.swrst = SepSwReset(test)
        self._entry_value = self.swrst.value
        self.pulses = 0

    def delay(self, rng: SepSeededRng, lo: int, hi: int) -> int:
        """A seeded cycle count in [lo, hi].

        The offset from the operation start decides which state the FSM sits in
        when the reset lands. It is a pure function of the run seed, so
        `--stage sim --seed N` replays the same landing points. It is not a
        key, nonce or token and nothing derived from it leaves the simulation.
        """
        return lo + (rng.getrandbits(32) % (hi - lo + 1))

    async def pulse(self, *, delay_cycles: int, tag: str) -> None:
        """Wait `delay_cycles`, hold the engine in reset, then release it."""
        clk = cocotb.top.clk_i
        await ClockCycles(clk, delay_cycles)
        await self.swrst.park(self.engine)
        await ClockCycles(clk, self.settle_cycles)
        await self.swrst.release(self.engine)
        await ClockCycles(clk, self.settle_cycles)
        self.pulses += 1
        self.log.info(
            "COV-STIM reset_arc %s: %s held in SW reset %d cycles into the operation, "
            "then released",
            tag,
            self.engine,
            delay_cycles,
        )

    async def restore(self) -> None:
        """Put `SW_RESET_N` back to the value this helper started from."""
        # `release()` with no engine names writes the shadow as it stands.
        self.swrst.value = self._entry_value
        await self.swrst.release()
        self.log.info(
            "COV-STIM reset_arc: SW_RESET_N restored to 0x%08x after %d %s pulse(s)",
            self._entry_value,
            self.pulses,
            self.engine,
        )
