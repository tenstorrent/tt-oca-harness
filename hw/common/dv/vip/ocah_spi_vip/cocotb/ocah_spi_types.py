# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Opcodes, geometry, and status-bit constants shared by every ocah_spi_vip component.

The in-scope command set is the single-SPI NOR-flash baseline the flash model
answers, the monitor decodes, and the checker credits. An opcode outside
``IN_SCOPE_OPCODES`` is drained by the model, decoded as unknown by the
monitor, and counted but never credited by the checker.
"""

from __future__ import annotations

import enum

__all__ = [
    "FRAME_SHAPE_REASONS",
    "IN_SCOPE_OPCODES",
    "PAGE_SIZE",
    "SECTOR_SIZE",
    "SR1_BUSY",
    "SR1_WEL",
    "OcahSpiOpcode",
    "SpiMode",
    "opcode_name",
]

PAGE_SIZE = 256
SECTOR_SIZE = 4096
SR1_BUSY = 0x01
SR1_WEL = 0x02


class SpiMode(str, enum.Enum):
    """Pin-binding personalities of the flash model; every mode runs single-bit data timing."""

    SINGLE = "single"
    QUAD = "quad"
    OCTAL = "octal"


class OcahSpiOpcode(enum.IntEnum):
    """Single-SPI NOR-flash command opcodes in the baseline scope."""

    JEDEC_ID = 0x9F
    READ = 0x03
    FAST_READ = 0x0B
    READ_SR1 = 0x05
    READ_SR2 = 0x35
    WRITE_ENABLE = 0x06
    WRITE_DISABLE = 0x04
    PAGE_PROGRAM = 0x02
    SECTOR_ERASE = 0x20


IN_SCOPE_OPCODES = frozenset(int(op) for op in OcahSpiOpcode)

# Flash record reasons for a frame refused for its shape: the controller ended
# a phase early or sent bits after the command's last one.
FRAME_SHAPE_REASONS = frozenset(
    (
        "partial_opcode",
        "partial_address",
        "partial_dummy",
        "partial_byte",
        "no_payload",
        "unexpected_payload",
    )
)


def opcode_name(opcode: int) -> str:
    """Symbolic name of an in-scope opcode, ``PARTIAL_OPCODE`` for -1, ``UNKNOWN(0xNN)`` otherwise."""
    if opcode < 0:
        return "PARTIAL_OPCODE"
    try:
        return OcahSpiOpcode(opcode & 0xFF).name
    except ValueError:
        return f"UNKNOWN(0x{opcode & 0xFF:02X})"
