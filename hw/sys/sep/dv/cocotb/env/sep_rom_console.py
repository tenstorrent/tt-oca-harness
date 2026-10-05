# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SEP Boot ROM virtual-console decoder.

The Boot ROM has no UART. It emits output through SEP cold_scratch[2] (probe word
2) using the packed protocol in bootrom/prod/include/rom_virt_console.h:

    [31:8] payload   [7:4] reserved   [3:1] opcode   [0] toggle

    opcode 0 ASCII  - 3 characters in payload bytes [15:8], [23:16], [31:24]
    opcode 1 HEX16  - 16-bit value in payload [23:8]
    opcode 2 DEC24  - 24-bit value in payload [31:8]

All three must be decoded: the ROM prints every diagnostic number (mcause, mepc,
error codes, sizes) with simputhex32, which emits the literal "0x" as ASCII and
then two HEX16 words, high half first.

The toggle bit flips when consecutive values are identical so a repeat still
registers as a change; the decoder therefore samples on *change*, not every clock.

Shared by every ROM-boot test so the bit layout lives in one place.
"""

from __future__ import annotations

import logging

import cocotb
from cocotb.triggers import RisingEdge

# cold_scratch[2] occupies bits [95:64] of the packed probe bus.
_SCRATCH2_SHIFT = 64
_WORD_MASK = 0xFFFFFFFF
# Character lanes within the word, in emission order (c1, c2, c3).
_CHAR_SHIFTS = (8, 16, 24)
_ASCII_LF = 0x0A
_ASCII_PRINTABLE = range(0x20, 0x7F)

# rom_virt_console.h: opcode is [3:1], so shift right by 1 and mask 3 bits.
_OP_SHIFT = 1
_OP_MASK = 0x7
_OP_ASCII = 0
_OP_HEX16 = 1
_OP_DEC24 = 2


async def rom_console_task(
    logger: logging.Logger,
    sink: list[str] | None = None,
    prefix: str = "ROM> ",
) -> None:
    """Decode the ROM virt-console until the simulation tears down the clock.

    Logs one line per newline the ROM emits, and appends it to ``sink`` when one
    is given. The sink is what lets a test assert on *which* boot path the ROM
    took (e.g. BOOT_SPI vs WAIT_SMC_MANIFEST) rather than only that it finished.
    Intended to be launched with ``cocotb.start_soon(...)``; it never returns on
    its own.
    """
    dut = cocotb.top
    line = bytearray()
    prev = None
    try:
        while True:
            await RisingEdge(dut.clk_i)
            try:
                packed = int(dut.scratch_cold_probe_o.value)
            except Exception:  # noqa: BLE001 - X/Z during reset is not decodable
                continue
            word = (packed >> _SCRATCH2_SHIFT) & _WORD_MASK
            if word == prev:
                continue
            prev = word
            op = (word >> _OP_SHIFT) & _OP_MASK
            if op == _OP_HEX16:
                # simputhex32 emits "0x" then high half then low half, so plain
                # 4-digit concatenation reassembles the full 32-bit value.
                line.extend(f"{(word >> 8) & 0xFFFF:04x}".encode("ascii"))
                continue
            if op == _OP_DEC24:
                line.extend(str((word >> 8) & 0xFFFFFF).encode("ascii"))
                continue
            if op != _OP_ASCII:
                continue
            for shift in _CHAR_SHIFTS:
                char = (word >> shift) & 0xFF
                if char == 0:
                    continue
                if char == _ASCII_LF:
                    text = bytes(line).decode("ascii", "ignore")
                    logger.info("%s%s", prefix, text)
                    if sink is not None:
                        sink.append(text)
                    line = bytearray()
                elif char in _ASCII_PRINTABLE:
                    line.append(char)
    except Exception:  # noqa: BLE001 - end-of-sim kills the clock; stop cleanly
        return


def log_scratch_cold(logger: logging.Logger) -> None:
    """Dump the four cold-scratch words.

    cold_scratch[1] carries the ROM error code (STATUS_ENCODE: low 16 bits are
    ROM_ERR_*), so this is the first thing to read when a ROM boot fails early.
    """
    try:
        packed = int(cocotb.top.scratch_cold_probe_o.value)
    except Exception as exc:  # noqa: BLE001
        logger.info("scratch_cold dump failed: %s", exc)
        return
    for i in range(4):
        logger.info("scratch_cold[%d] = 0x%08x", i, (packed >> (32 * i)) & _WORD_MASK)
