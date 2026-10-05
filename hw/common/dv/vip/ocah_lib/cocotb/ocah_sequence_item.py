# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Sequence item base for DUT-local agents and monitors.

Every published item carries the observation timestamp and the evidence
context, so a scoreboard can name the transaction it compared. The SV-UVM twin
is ``ocah_sequence_item``.
"""

from __future__ import annotations

from pyuvm import uvm_sequence_item

__all__ = ["OcahSequenceItem"]


class OcahSequenceItem(uvm_sequence_item):
    """Timestamp and evidence context on every DUT-local item."""

    def __init__(self, name: str = "ocah_sequence_item") -> None:
        super().__init__(name)
        # Simulation time in ns the item was issued or observed; the driver
        # or monitor that publishes the item sets it.
        self.timestamp: float = 0.0
        # Free-form evidence context (``context=`` in a CHK line).
        self.context: str = ""

    def do_copy(self, rhs: object) -> None:
        super().do_copy(rhs)
        if not isinstance(rhs, OcahSequenceItem):
            raise TypeError(f"do_copy type mismatch: {type(rhs).__name__}")
        self.timestamp = rhs.timestamp
        self.context = rhs.context

    def __str__(self) -> str:
        return f"{self.get_type_name()} @{self.timestamp:g}ns {self.context}"
