# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Clocked stall counter for one flat AXI port of the bench."""

from __future__ import annotations

from cocotb.triggers import ReadOnly, RisingEdge


class SmcAxiPortWatch:
    """Count the cycles each address and response channel of a port spent stalled.

    A channel is stalled in a cycle when its VALID is high and its READY low.
    The counts are the measurement that a backpressure profile actually reached
    the bus; the caller decides which of them must be non-zero.
    """

    def __init__(self, dut, prefix: str) -> None:
        self.dut = dut
        self.prefix = prefix
        self.stop = False
        self.stalls = {"aw": 0, "ar": 0, "b": 0, "r": 0}

    def _read(self, name: str) -> int | None:
        value = getattr(self.dut, f"{self.prefix}_{name}").value
        return int(value) if value.is_resolvable else None

    async def run(self) -> None:
        while not self.stop:
            await RisingEdge(self.dut.clk_smc_i)
            await ReadOnly()
            for channel in self.stalls:
                if self._read(f"{channel}valid") == 1 and self._read(f"{channel}ready") == 0:
                    self.stalls[channel] += 1
