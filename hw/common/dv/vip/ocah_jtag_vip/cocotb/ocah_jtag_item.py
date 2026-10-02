# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Plain JTAG transaction items for monitors, checkers, and scoreboards."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from .ocah_jtag_state import OcahJtagState

OcahJtagScanKind = Literal["IR", "DR"]
OcahJtagEventKind = Literal["STEP", "TRST"]


@dataclass(frozen=True)
class OcahJtagScanItem:
    """Immutable IR/DR scan record."""

    kind: OcahJtagScanKind
    tdi_value: int
    tdo_value: int
    bit_count: int
    instruction: int | None = None
    start_time_ns: float | None = None
    end_time_ns: float | None = None
    start_state: OcahJtagState | None = None
    end_state: OcahJtagState | None = None
    source: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def type(self) -> str:
        """Alias of ``kind``."""
        return self.kind

    @property
    def duration_ns(self) -> float | None:
        if self.start_time_ns is None or self.end_time_ns is None:
            return None
        return self.end_time_ns - self.start_time_ns

    @property
    def is_ir(self) -> bool:
        return self.kind == "IR"

    @property
    def is_dr(self) -> bool:
        return self.kind == "DR"

    def to_record(self) -> dict[str, Any]:
        """Return the scan as a plain dict keyed by record field name."""
        return {
            "type": self.kind,
            "tdi_value": self.tdi_value,
            "tdo_value": self.tdo_value,
            "bit_count": self.bit_count,
            "start_ns": self.start_time_ns,
            "end_ns": self.end_time_ns,
            "duration_ns": self.duration_ns,
            "instruction": self.instruction,
        }

    def __getitem__(self, key: str) -> Any:
        """Dict-style field access over ``to_record()``."""
        return self.to_record()[key]


@dataclass(frozen=True)
class OcahJtagStateItem:
    """Single TAP-state transition record."""

    previous_state: OcahJtagState
    tms: int
    next_state: OcahJtagState
    tdi: int = 0
    tdo: int = 0
    time_ns: float | None = None
    source: str = ""


@dataclass(frozen=True)
class OcahJtagEvent:
    """Passive monitor observation of one TCK cycle or one TRST edge.

    ``STEP`` is one completed TCK cycle: ``tms`` and ``tdi`` are the values
    the DUT captured on the rising edge, ``tdo`` the value stable before it,
    and ``trst_n`` the TRST level during the cycle (0 holds the TAP in
    reset). ``TRST`` is an asynchronous TRST edge; ``trst_asserted`` is 1 on
    assertion and 0 on release. The SV-UVM twin is ``ocah_jtag_event``.
    """

    kind: OcahJtagEventKind
    tms: int = 0
    tdi: int = 0
    tdo: int = 0
    trst_n: int = 1
    trst_asserted: int = 0
    index: int = 0
    time_ns: float | None = None
    source: str = ""
