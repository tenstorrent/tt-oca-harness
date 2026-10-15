# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Raw-noise stimulus for the ESRC lanes.

Under Verilator the ESRC ring oscillators do not self-oscillate, so the 12
decorrelator lanes are driven from here and forced into the DUT (see the policy
note in tb_wrapper_top.sv). The lanes need enough variety for the health tests
to pass and a seed to accumulate. Bit-exact prediction of the decorrelator and
CSRNG output is the SEP DV environment's; the claim here is that entropy flows
end to end.

Each lane gets its own LFSR seed so the lanes are not identical, which the
repetition-count health test would otherwise flag.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import RisingEdge

NUM_LANES = 12
_LFSR_TAPS = 0xB400  # 16-bit maximal-length


class SmuEsrcNoiseDriver:
    """Drive `esrc_noise_ext_i` with twelve independent LFSR lanes."""

    def __init__(self, dut, *, seed: int = 0xACE1) -> None:
        self.dut = dut
        # Distinct, non-zero seeds: a zero LFSR state is a lock-up, and equal
        # seeds would make every lane produce the same bit.
        self._state = [((seed + i * 0x1D7B) & 0xFFFF) | 1 for i in range(NUM_LANES)]
        self._task = None

    def _step(self) -> int:
        value = 0
        for i, state in enumerate(self._state):
            lsb = state & 1
            state >>= 1
            if lsb:
                state ^= _LFSR_TAPS
            self._state[i] = state
            value |= (state & 1) << i
        return value

    def start(self) -> None:
        """Begin driving; runs until the test ends."""
        if self._task is None:
            self._task = cocotb.start_soon(self._run())

    async def _run(self) -> None:
        while True:
            await RisingEdge(self.dut.clk_smu_i)
            self.dut.esrc_noise_ext_i.value = self._step()
