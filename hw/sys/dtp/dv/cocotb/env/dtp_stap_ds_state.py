# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Downstream TAP behind one STAP host port, predicted from IEEE 1149.1.

The model is seeded from the attached device's register map and never reads
the VIP's device engine back. The SV-UVM twin is
``uvm/env/dtp_stap_ds_state.svh``.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ocah_jtag_vip import OcahJtagDevice

from .dtp_types import DtpScanKind

__all__ = ["STAP_DS_IR_CAPTURE", "DtpStapDsReg", "DtpStapDsState"]

# IEEE 1149.1: a TAP's IR capture presents 01 in its two LSBs.
STAP_DS_IR_CAPTURE = 0b01


@dataclass(frozen=True)
class DtpStapDsReg:
    """One data register of a downstream TAP."""

    name: str
    opcode: int
    width: int
    writable: bool


@dataclass
class DtpStapDsState:
    """Tracked state of the downstream TAP spliced behind one STAP host port.

    Seeded from the attached device's map (IR width, IDCODE, registers); the
    behavior is predicted here from IEEE 1149.1, not read back from the VIP
    engine: Test-Logic-Reset selects IDCODE, an unknown instruction selects
    the one-bit BYPASS, Capture-IR presents ``01`` in the IR LSBs, and a
    writable register latches the shifted-in value on Update-DR.
    """

    ir_width: int
    idcode: int
    idcode_opcode: int
    regs: dict[int, DtpStapDsReg]
    active_ir: int = 0
    values: dict[str, int] = field(default_factory=dict)

    @classmethod
    def from_device(cls, device: OcahJtagDevice) -> DtpStapDsState:
        """Build from an ``OcahJtagDevice``-shaped map (``ir_width``, ``idcode``, ``regs``)."""
        regs = {
            int(reg.opcode): DtpStapDsReg(
                reg.name, int(reg.opcode), int(reg.width), bool(reg.write)
            )
            for reg in device.regs.values()
        }
        idcode_reg = next((r for r in regs.values() if r.name == "IDCODE"), None)
        if idcode_reg is None:
            raise ValueError(f"downstream device {device.name!r} has no IDCODE register")
        bypass = (1 << int(device.ir_width)) - 1
        regs.setdefault(bypass, DtpStapDsReg("BYPASS", bypass, 1, False))
        ds = cls(
            ir_width=int(device.ir_width),
            idcode=int(device.idcode),
            idcode_opcode=idcode_reg.opcode,
            regs=regs,
            values={r.name: 0 for r in regs.values() if r.writable},
        )
        ds.reset_instruction()
        return ds

    @property
    def bypass_opcode(self) -> int:
        return (1 << self.ir_width) - 1

    def opcode_of(self, name: str) -> int:
        for reg in self.regs.values():
            if reg.name == name:
                return reg.opcode
        raise KeyError(f"downstream register {name!r} unknown; known: {sorted(self.values)}")

    def reg(self, name: str) -> DtpStapDsReg:
        return self.regs[self.opcode_of(name)]

    def selected(self) -> DtpStapDsReg | None:
        """The register the active instruction selects (None = BYPASS behavior)."""
        reg = self.regs.get(self.active_ir & self.bypass_opcode)
        if reg is None or reg.name == "BYPASS":
            return None
        return reg

    def selected_width(self, scan_kind: DtpScanKind = DtpScanKind.DR) -> int:
        """Chain segment width the downstream contributes to a composed scan."""
        if scan_kind == DtpScanKind.IR:
            return self.ir_width
        reg = self.selected()
        return reg.width if reg is not None and reg.width > 0 else 1

    def shift_default(self, scan_kind: DtpScanKind = DtpScanKind.DR) -> int:
        """Segment value a maintain scan shifts in: the stored value of a
        writable register (re-latched unchanged), the active IR for an IR
        scan, zero otherwise."""
        if scan_kind == DtpScanKind.IR:
            return self.active_ir
        reg = self.selected()
        if reg is not None and reg.writable:
            return self.values[reg.name]
        return 0

    def capture(self, scan_kind: DtpScanKind = DtpScanKind.DR) -> int:
        """Segment value the downstream captures at Capture-IR / Capture-DR."""
        if scan_kind == DtpScanKind.IR:
            return STAP_DS_IR_CAPTURE & ((1 << self.ir_width) - 1)
        reg = self.selected()
        if reg is None:
            return 0
        if reg.name == "IDCODE":
            return self.idcode
        return self.values.get(reg.name, 0)

    def latch(self, value: int) -> None:
        """Update-DR: a writable selected register takes the shifted value."""
        reg = self.selected()
        if reg is not None and reg.writable:
            self.values[reg.name] = int(value) & ((1 << reg.width) - 1)

    def update_ir(self, opcode: int) -> None:
        self.active_ir = int(opcode) & self.bypass_opcode

    def reset_instruction(self) -> None:
        """Test-Logic-Reset (TRST, or five parked TMS=1 cycles) selects IDCODE."""
        self.active_ir = self.idcode_opcode
