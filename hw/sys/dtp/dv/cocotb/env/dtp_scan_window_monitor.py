# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Per-TCK monitors of the DUT's scan controls and exported TAP state.

Post-transaction snapshots cannot prove that a control signal never pulsed
during a scan. The window monitor samples named TB-interface observables on
every rising TCK edge inside a window, so a gated operation can prove zero
pulses over the full window and an enabled operation can prove the expected
pulses occurred; it also counts the cycles the DUT's exported TAP state spent
in Shift-DR or Shift-IR, the DUT-side witness that the window covered a scan.
The shift monitor turns those Shift visits into episodes, one per scan, so the
scan-length evidence compares the length the DUT performed with the width the
sequence drove.
"""

from __future__ import annotations

from collections.abc import Iterable

import cocotb
from cocotb.triggers import ReadOnly, RisingEdge

from env.dtp_types import DtpTapState

_SHIFT_STATES = frozenset({int(DtpTapState.SHIFT_DR), int(DtpTapState.SHIFT_IR)})


class DtpScanControlWindowMonitor:
    """Count high samples of named observables on each rising TCK edge."""

    def __init__(self, tb_if, signals: Iterable[str]) -> None:
        self.tb_if = tb_if
        self.signals = tuple(signals)
        self.high_counts: dict[str, int] = {name: 0 for name in self.signals}
        self.edges = 0
        # TCK cycles the DUT's exported TAP state was Shift-DR or Shift-IR.
        self.dut_shift_cycles = 0
        self._task = None
        for name in self.signals:
            if not tb_if.has(name):
                raise AttributeError(f"{name} is not a DTP TB observable")

    async def _run(self) -> None:
        while True:
            await RisingEdge(self.tb_if.jtag.tck)
            await ReadOnly()
            self.edges += 1
            if self.tb_if.sample("jtag_ptap_state") in _SHIFT_STATES:
                self.dut_shift_cycles += 1
            for name in self.signals:
                if self.tb_if.sample(name):
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


class DtpTapShiftMonitor:
    """Shift-IR / Shift-DR episodes of the DUT's exported TAP state.

    One entry per visit of ``jtag_ptap_state`` to a Shift state, holding the TCK
    cycles the DUT spent there. The DUT moves one bit per cycle in a Shift
    state, so an episode is the scan length the DUT executed, whatever the
    driver requested. A TRST or power-on reset asserted at a TCK edge ends the
    visit without an entry.
    """

    def __init__(self, tb_if) -> None:
        self.tb_if = tb_if
        self.ir_lens: list[int] = []
        self.dr_lens: list[int] = []
        self._run_len = 0
        self._in_state: int | None = None
        self._task = None

    async def _run(self) -> None:
        while True:
            await RisingEdge(self.tb_if.jtag.tck)
            await ReadOnly()
            if not int(self.tb_if.jtag.trst_n.value) or not int(self.tb_if.por_rst_n.value):
                self._run_len = 0
                self._in_state = None
                continue
            state = self.tb_if.sample("jtag_ptap_state")
            current = state if state in _SHIFT_STATES else None
            if self._in_state is not None and current != self._in_state:
                lens = self.ir_lens if self._in_state == int(DtpTapState.SHIFT_IR) else self.dr_lens
                lens.append(self._run_len)
            if current is None:
                self._run_len = 0
            elif current == self._in_state:
                self._run_len += 1
            else:
                self._run_len = 1
            self._in_state = current

    def start(self) -> "DtpTapShiftMonitor":
        if self._task is not None:
            raise RuntimeError("TAP shift monitor is already running")
        self._task = cocotb.start_soon(self._run())
        return self

    def stop(self) -> None:
        if self._task is None:
            raise RuntimeError("TAP shift monitor was never started")
        self._task.kill()
        self._task = None
