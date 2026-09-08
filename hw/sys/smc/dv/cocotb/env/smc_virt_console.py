# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Decoder for the SMC firmware virtual console (scratch register 2).

The firmware side is hw/sys/smc/dv/fw/drivers/virt_console.c (and the identical
encoder in hw/sys/smc/bootrom/prod/lib/src/virt_console.c). Every simputs()
character stream is packed into 32-bit writes to scratch 2:

    [31:8] payload
    [7:4]  reserved, must be 0
    [3:1]  opcode   0 = three ASCII bytes, payload LSB first
                    1 = 16-bit hex value
                    2 = 24-bit decimal (not implemented in the firmware)
    [0]    toggle   flipped when a write would otherwise repeat the previous
                    value, so the observer can tell two identical writes apart

Without this decoder the controller's own OCCP trace is invisible: the DV
firmware's simputs() is unconditional, so it is always being written, and a
dual-firmware failure is otherwise a silent hang.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import ValueChange

OPCODE_ASCII = 0
OPCODE_HEX16 = 1
OPCODE_DEC24 = 2


class VirtConsole:
    """Reassembles one instance's simputs() stream into log lines."""

    def __init__(self, signal, name: str) -> None:
        self.signal = signal
        self.name = name
        self._line = ""
        self.lines: list[str] = []

    def _emit(self, chunk: str) -> None:
        self._line += chunk
        while "\n" in self._line:
            head, self._line = self._line.split("\n", 1)
            self.lines.append(head)
            cocotb.log.info("[%s] %s", self.name, head)

    def _decode(self, word: int) -> None:
        opcode = (word >> 1) & 0x7
        payload = (word >> 8) & 0xFF_FFFF
        if opcode == OPCODE_ASCII:
            chunk = ""
            for shift in (0, 8, 16):
                byte = (payload >> shift) & 0xFF
                if byte:
                    chunk += chr(byte)
            self._emit(chunk)
        elif opcode == OPCODE_HEX16:
            self._emit(f"{payload & 0xFFFF:#06x}")
        elif opcode == OPCODE_DEC24:
            self._emit(str(payload))
        # Other opcodes are reserved; ignore rather than corrupt the stream.

    def flush(self) -> None:
        """Emit any partial line, e.g. at the end of a test."""
        if self._line:
            self.lines.append(self._line)
            cocotb.log.info("[%s] %s", self.name, self._line)
            self._line = ""

    async def run(self) -> None:
        """Watch scratch 2 forever. Intended to be started with start_soon."""
        last = None
        while True:
            await ValueChange(self.signal)
            if not self.signal.value.is_resolvable:
                continue
            word = int(self.signal.value)
            if word == last:
                continue
            last = word
            self._decode(word)

    def tail(self, count: int = 40) -> str:
        """Last few decoded lines, for assertion messages."""
        recent = self.lines[-count:]
        if self._line:
            recent = recent + [self._line + " <partial>"]
        return "\n".join(f"    [{self.name}] {line}" for line in recent)
