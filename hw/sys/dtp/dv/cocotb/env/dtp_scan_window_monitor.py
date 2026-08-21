# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Transaction-window monitor for DTP scan-control observables.

Post-transaction snapshots cannot prove that a control signal never pulsed
during a scan. This monitor samples named tb_top observables on every rising
TCK edge inside a window, so a gated operation can prove zero pulses over the
full window and an enabled operation can prove the expected pulses occurred.
"""

from __future__ import annotations

from collections.abc import Iterable

import cocotb
from cocotb.triggers import ReadOnly, RisingEdge


class DtpScanControlWindowMonitor:
    """Count high samples of named observables on each rising TCK edge."""

    def __init__(self, signals: Iterable[str]) -> None:
        self.signals = tuple(signals)
        self.high_counts: dict[str, int] = {name: 0 for name in self.signals}
        self.edges = 0
        self._task = None
        dut = cocotb.top
        for name in self.signals:
            if not hasattr(dut, name):
                raise AttributeError(f"{name} is not exposed by tb_top")

    async def _run(self) -> None:
        dut = cocotb.top
        while True:
            await RisingEdge(dut.jtag_tck)
            await ReadOnly()
            self.edges += 1
            for name in self.signals:
                if int(getattr(dut, name).value):
                    self.high_counts[name] += 1

    def start(self) -> "DtpScanControlWindowMonitor":
        if self._task is not None:
            raise RuntimeError("scan window monitor is already running")
        self._task = cocotb.start_soon(self._run())
        return self

    def stop(self) -> tuple[int, dict[str, int]]:
        """End the window; return (tck_edges, high sample count per signal)."""
        if self._task is None:
            raise RuntimeError("scan window monitor was never started")
        self._task.kill()
        self._task = None
        return self.edges, dict(self.high_counts)
