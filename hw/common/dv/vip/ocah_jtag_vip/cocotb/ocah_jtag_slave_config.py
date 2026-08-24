# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Plain configuration object for the slave-side (device) VIP components.

One `OcahJtagSlaveConfig` describes a reactive TAP device: its IDCODE, IR
width, data-register map, and pin binding. `build_device()` materializes the
`OcahJtagDevice` the slave driver executes; explicit keyword arguments always
override config fields.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .ocah_jtag_device import OcahJtagDevice

__all__ = ["OcahJtagSlaveConfig"]


@dataclass
class OcahJtagSlaveConfig:
    """Configuration for one reactive IEEE 1149.1 TAP device."""

    name: str = "OcahJtagSlave"
    idcode: int = 0x0000_0001
    ir_width: int = 5
    # {name: (width, opcode) or (width, opcode, writable)}; BYPASS is always
    # present and IDCODE should be included when the device implements one.
    registers: dict[str, tuple] = field(default_factory=dict)
    device: OcahJtagDevice | None = None
    signal_map: dict[str, str] = field(default_factory=dict)
    drive_tdo_oen: bool = True
    # Passive monitor bound (retained scan items).
    max_history: int = 2000

    def build_device(self) -> OcahJtagDevice:
        """Return the configured device map (the instance wins when set)."""
        if self.device is not None:
            return self.device
        registers = dict(self.registers)
        if "IDCODE" not in registers:
            registers["IDCODE"] = (32, 0x01)
        return OcahJtagDevice.from_registers(
            name=self.name,
            idcode=self.idcode,
            ir_width=self.ir_width,
            registers=registers,
        )

    def driver_kwargs(self) -> dict:
        """Keyword arguments for `OcahJtagSlaveDriver` construction."""
        return {
            "name": f"{self.name}.driver",
            "signal_map": dict(self.signal_map) or None,
            "drive_tdo_oen": self.drive_tdo_oen,
        }

    def monitor_kwargs(self) -> dict:
        """Keyword arguments for `OcahJtagSlaveMonitor` construction."""
        return {
            "name": f"{self.name}.monitor",
            "max_history": self.max_history,
            "signal_map": dict(self.signal_map) or None,
        }
