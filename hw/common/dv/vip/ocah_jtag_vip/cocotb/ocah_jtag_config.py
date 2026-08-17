# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Tenstorrent Inc.
"""Plain configuration object for the OCAH JTAG VIP components.

One `OcahJtagConfig` describes a TAP connection (naming, IR width, timing,
signal mapping, monitor bounds) and can be passed to `OcahJtagTap`,
`OcahJtagMonitor`, and `OcahJtagAgent` instead of repeating keyword
arguments. Explicit keyword arguments always override config fields, so
existing call sites keep working unchanged.
"""

from __future__ import annotations

from dataclasses import dataclass, field

__all__ = ["OcahJtagConfig"]


@dataclass
class OcahJtagConfig:
    """Configuration for one IEEE 1149.1 TAP connection."""

    name: str = "OcahJtag"
    ir_width: int = 5
    tck_period_ns: int = 10
    tap_type: str = "ptap"
    signal_map: dict[str, str] = field(default_factory=dict)
    time_unit: str = "ns"
    timeout_cycles: int = 10_000
    trst_active_high: bool = False
    # Passive monitor bound (retained scan items).
    max_history: int = 2000

    def driver_kwargs(self) -> dict:
        """Keyword arguments for `OcahJtagTap` construction."""
        return {
            "name": self.name,
            "tck_period_ns": self.tck_period_ns,
            "ir_width": self.ir_width,
            "tap_type": self.tap_type,
            "signal_map": dict(self.signal_map) or None,
            "time_unit": self.time_unit,
            "timeout_cycles": self.timeout_cycles,
            "trst_active_high": self.trst_active_high,
        }

    def monitor_kwargs(self) -> dict:
        """Keyword arguments for `OcahJtagMonitor` construction."""
        return {
            "name": f"{self.name}.monitor",
            "max_history": self.max_history,
            "signal_map": dict(self.signal_map) or None,
        }
