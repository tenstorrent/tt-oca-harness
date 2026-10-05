# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""OCAH JTAG device/register map wrappers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from cocotbext.jtag import JTAGDevice


@dataclass(frozen=True)
class OcahJtagRegister:
    """Plain OCAH JTAG data-register description."""

    name: str
    width: int
    opcode: int
    write: bool = False


class OcahJtagDevice:
    """Plain wrapper for a JTAG device and its IR-to-DR register map."""

    def __init__(
        self,
        *,
        name: str = "default",
        idcode: int = 0x0000_0001,
        ir_width: int = 4,
        idle_delay: int = 0,
        add_bypass: bool = True,
    ) -> None:
        self.name = name
        self.idcode = int(idcode)
        self.ir_width = int(ir_width)
        self.idle_delay = int(idle_delay)
        self.regs: dict[str, OcahJtagRegister] = {}
        if add_bypass:
            self.add_reg("BYPASS", 1, (1 << self.ir_width) - 1)

    def add_reg(self, name: str, width: int, opcode: int, *, write: bool = False) -> None:
        """Add a named JTAG data register."""
        if width < 0:
            raise ValueError(f"{name}: JTAG register width must be >= 0, got {width}")
        if opcode < 0 or opcode >= (1 << self.ir_width):
            raise ValueError(
                f"{name}: opcode 0x{opcode:x} does not fit in IR width {self.ir_width}"
            )
        self.regs[name] = OcahJtagRegister(
            name=name,
            width=int(width),
            opcode=int(opcode),
            write=bool(write),
        )

    def reg(self, name: str) -> OcahJtagRegister:
        """Return a named register or raise a useful error."""
        try:
            return self.regs[name]
        except KeyError as exc:
            known = ", ".join(sorted(self.regs)) or "<none>"
            raise KeyError(f"unknown JTAG register {name!r}; known: {known}") from exc

    def to_backend(self) -> JTAGDevice:
        """Build a `cocotbext-jtag` device for advanced backend flows.

        The backend package is bound here and nowhere else in this module, so
        device maps, the reactive device, and the checker import without it.
        """
        from cocotbext.jtag import JTAGDevice

        backend = JTAGDevice(name=self.name, idcode=self.idcode, ir_len=self.ir_width, init=False)
        for reg in self.regs.values():
            backend.add_jtag_reg(reg.name, reg.width, reg.opcode, write=reg.write)
        backend.idle_delay = self.idle_delay
        return backend

    @classmethod
    def from_registers(
        cls,
        *,
        name: str,
        idcode: int,
        ir_width: int,
        registers: dict[str, tuple[int, int] | tuple[int, int, bool]],
        idle_delay: int = 0,
        add_bypass: bool = True,
    ) -> "OcahJtagDevice":
        """Build a device from `{name: (width, opcode[, write])}` entries."""
        device = cls(
            name=name,
            idcode=idcode,
            ir_width=ir_width,
            idle_delay=idle_delay,
            add_bypass=add_bypass,
        )
        for reg_name, spec in registers.items():
            if len(spec) == 2:
                width, opcode = spec
                write = False
            else:
                width, opcode, write = spec
            device.add_reg(reg_name, width, opcode, write=write)
        return device
