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


def opcode_name(opcode: int) -> str:
    """Symbolic name of an in-scope opcode, ``UNKNOWN(0xNN)`` otherwise."""
    try:
        return OcahSpiOpcode(opcode & 0xFF).name
    except ValueError:
        return f"UNKNOWN(0x{opcode & 0xFF:02X})"
