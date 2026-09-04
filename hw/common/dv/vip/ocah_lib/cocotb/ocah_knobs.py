# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Knob accessor: the one place environment knobs are read.

A knob is a named integer control the runner exports as an environment
variable; the SV-UVM twin ``ocah_knobs`` reads the same name as a plusarg, so
bench code names knobs and never spells the transport. An absent or empty
variable is an unset knob. The simulator seed is not a knob: only
``OcahTest.base_seed`` reads it.
"""

from __future__ import annotations

import os

__all__ = ["OcahKnobError", "OcahKnobs"]


class OcahKnobError(ValueError):
    """Raised when a knob carries a value outside its contract."""


class OcahKnobs:
    """Static accessors over the environment."""

    @staticmethod
    def has_value(name: str) -> bool:
        """True when the knob carries a value, ``0`` included (``+NAME=`` in SV)."""
        return os.environ.get(name, "") != ""

    @staticmethod
    def get_int(name: str, default_value: int) -> int:
        """Integer knob with a default; decimal or ``0x``-prefixed text."""
        raw = os.environ.get(name, "")
        if raw == "":
            return default_value
        try:
            return int(raw, 0)
        except ValueError as exc:
            raise OcahKnobError(f"{name} must be an integer, got {raw!r}") from exc

    @staticmethod
    def get_int_min(name: str, default_value: int, minimum: int) -> int:
        """Integer knob with a lower bound: a value below it is a defect, never clamped."""
        value = OcahKnobs.get_int(name, default_value)
        if value < minimum:
            raise OcahKnobError(f"{name} must be >= {minimum}, got {value}")
        return value

    @staticmethod
    def is_set(name: str) -> bool:
        """Presence knob (``+NAME`` in SV): set unless absent, empty, or ``0``."""
        return os.environ.get(name, "") not in ("", "0")
