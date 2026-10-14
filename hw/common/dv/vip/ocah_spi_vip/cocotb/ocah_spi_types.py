# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Opcodes, geometry, and status-bit constants shared by every ocah_spi_vip component.

The in-scope command set is the single-SPI NOR-flash baseline the flash model
answers, the monitor decodes, and the checker credits. An opcode outside
``IN_SCOPE_OPCODES`` is drained by the model, decoded as unknown by the
monitor, and counted but never credited by the checker.
"""

from __future__ import annotations

import dataclasses
import enum

__all__ = [
    "FRAME_SHAPE_REASONS",
    "IN_SCOPE_OPCODES",
    "LANE_OPCODES",
    "OcahSpiCommandFormat",
    "command_format",
    "lanes_to_bytes",
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
    """Pin-binding personalities of the flash model.

    ``single``, ``quad`` and ``octal`` run single-bit data timing on one line.
    ``quad_io`` binds four data lanes and runs the dual and quad commands of
    ``LANE_OPCODES`` on them; single-lane phases use lane 0 from the
    controller and lane 1 to the controller.
    """

    SINGLE = "single"
    QUAD = "quad"
    OCTAL = "octal"
    QUAD_IO = "quad_io"


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
    DUAL_OUTPUT_READ = 0x3B
    QUAD_OUTPUT_READ = 0x6B
    DUAL_IO_READ = 0xBB
    QUAD_IO_READ = 0xEB
    QUAD_PAGE_PROGRAM = 0x32


# Commands that need the four-lane binding (``SpiMode.QUAD_IO``).
LANE_OPCODES = frozenset(
    int(op)
    for op in (
        OcahSpiOpcode.DUAL_OUTPUT_READ,
        OcahSpiOpcode.QUAD_OUTPUT_READ,
        OcahSpiOpcode.DUAL_IO_READ,
        OcahSpiOpcode.QUAD_IO_READ,
        OcahSpiOpcode.QUAD_PAGE_PROGRAM,
    )
)

IN_SCOPE_OPCODES = frozenset(int(op) for op in OcahSpiOpcode)


@dataclasses.dataclass(frozen=True)
class OcahSpiCommandFormat:
    """Lanes and clocks of each phase of one command, after its single-lane command byte.

    ``addr_lanes`` 0 means no address phase. ``dummy_clocks`` counts clocks
    with no data. ``data_lanes`` is the width of the payload or response and
    ``response`` tells its direction (True: device to controller).
    """

    addr_lanes: int
    dummy_clocks: int
    data_lanes: int
    response: bool

    def input_clocks(self, addr_bytes: int) -> int:
        """Clocks of the command, address and dummy phases of a command with a response."""
        addr = (8 * addr_bytes) // self.addr_lanes if self.addr_lanes else 0
        return 8 + addr + self.dummy_clocks


# Formats of the commands with a response or a payload. The data bit order on
# several lanes is the SPI host's: the most significant bits first, and the
# least significant bit of each pair or nibble on lane 0.
_FORMATS = {
    int(OcahSpiOpcode.JEDEC_ID): OcahSpiCommandFormat(0, 0, 1, True),
    int(OcahSpiOpcode.READ_SR1): OcahSpiCommandFormat(0, 0, 1, True),
    int(OcahSpiOpcode.READ_SR2): OcahSpiCommandFormat(0, 0, 1, True),
    int(OcahSpiOpcode.READ): OcahSpiCommandFormat(1, 0, 1, True),
    int(OcahSpiOpcode.FAST_READ): OcahSpiCommandFormat(1, 8, 1, True),
    int(OcahSpiOpcode.DUAL_OUTPUT_READ): OcahSpiCommandFormat(1, 8, 2, True),
    int(OcahSpiOpcode.QUAD_OUTPUT_READ): OcahSpiCommandFormat(1, 8, 4, True),
    int(OcahSpiOpcode.DUAL_IO_READ): OcahSpiCommandFormat(2, 4, 2, True),
    int(OcahSpiOpcode.QUAD_IO_READ): OcahSpiCommandFormat(4, 6, 4, True),
    int(OcahSpiOpcode.PAGE_PROGRAM): OcahSpiCommandFormat(1, 0, 1, False),
    int(OcahSpiOpcode.QUAD_PAGE_PROGRAM): OcahSpiCommandFormat(1, 0, 4, False),
}


def command_format(opcode: int) -> OcahSpiCommandFormat | None:
    """Phase format of a command with a response or a payload; ``None`` otherwise."""
    return _FORMATS.get(int(opcode))


def lanes_to_bytes(values: list[int], lanes: int) -> tuple[bytes, int]:
    """Pack per-clock lane values into bytes, most significant bits first.

    ``values`` holds one sample per clock; for ``lanes`` 1, 2 or 4 the low
    ``lanes`` bits of each sample carry data, the least significant on lane
    0. Returns the complete bytes and the clocks of the byte left incomplete.
    """
    per_byte = 8 // lanes
    out = bytearray()
    full = len(values) - len(values) % per_byte
    mask = (1 << lanes) - 1
    for start in range(0, full, per_byte):
        value = 0
        for sample in values[start : start + per_byte]:
            value = (value << lanes) | (sample & mask)
        out.append(value)
    return bytes(out), len(values) - full


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
