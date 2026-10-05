# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Independent golden for the Key Manager CRC co-processor.

A reflected (LSB-first) bit-serial CRC step, applied once per byte, with the
running state masked to the mode's width after the load XOR and after every
shift. Its parameters are pinned by the published check values asserted at the
bottom of this file, so its authority is those external values, not the design
it grades.

The engine applies NO initial value and NO final inversion -- both belong to
the caller -- so :func:`step` and :func:`word_update` return the raw chaining
state. ``init``/``xorout`` appear only in :func:`crc32c` and :func:`crc8_rohc`,
which exist to anchor this file against published check values.

A golden derived as "four byte steps", compared against
hardware that is also "four byte steps", agrees even when the polynomial or the
byte order is wrong in both. The self-tests below pin the polynomial,
reflection and byte order to values published outside this repository, so a
transcription error fails at import rather than passing a run. CRC-8/ROHC
parameters (poly ``0x07`` / reflected ``0xE0``, init ``0xFF``, RefIn/RefOut,
XorOut ``0x00``, check ``"123456789"`` → ``0xD0``) are
``hw/ip/key_manager/doc/firmware.adoc`` HEADER_CRC8 and the CRC-8/ROHC table.
"""

from __future__ import annotations

CRC32C_POLY = 0x82F6_3B78
CRC32C_MASK = 0xFFFF_FFFF
CRC8_ROHC_POLY = 0x0000_00E0
CRC8_MASK = 0x0000_00FF

MODE_32C_WORD = 0
MODE_32C_BYTE = 1
MODE_8_ROHC = 2

_MODE_PARAMS = {
    MODE_32C_WORD: (CRC32C_POLY, CRC32C_MASK),
    MODE_32C_BYTE: (CRC32C_POLY, CRC32C_MASK),
    MODE_8_ROHC: (CRC8_ROHC_POLY, CRC8_MASK),
}


def step(state: int, data_byte: int, poly: int, mask: int) -> int:
    """One reflected CRC byte step: XOR the byte in, then shift eight times."""
    crc = (state ^ (data_byte & 0xFF)) & mask
    for _ in range(8):
        if crc & 1:
            crc = ((crc >> 1) ^ poly) & mask
        else:
            crc = (crc >> 1) & mask
    return crc & mask


def update(mode: int, state: int, data: int) -> int:
    """Apply one instruction's worth of work and return the raw result.

    Word mode consumes all four operand bytes least-significant first. Both
    byte modes consume only ``data[7:0]`` and ignore the upper 24 bits, and
    CRC-8/ROHC additionally masks its result to eight bits, so ``rd[31:8]``
    comes back clear.
    """
    poly, mask = _MODE_PARAMS[mode]
    crc = state & 0xFFFF_FFFF
    if mode == MODE_32C_WORD:
        for shift in (0, 8, 16, 24):
            crc = step(crc, (data >> shift) & 0xFF, poly, mask)
        return crc
    return step(crc, data & 0xFF, poly, mask)


def crc32c(data: bytes) -> int:
    """CRC-32C over a byte string, with the caller-side init and final XOR."""
    crc = 0xFFFF_FFFF
    for byte in data:
        crc = step(crc, byte, CRC32C_POLY, CRC32C_MASK)
    return crc ^ 0xFFFF_FFFF


def crc8_rohc(data: bytes) -> int:
    """CRC-8/ROHC over a byte string. XorOut is zero, so no final inversion."""
    crc = 0xFF
    for byte in data:
        crc = step(crc, byte, CRC8_ROHC_POLY, CRC8_MASK)
    return crc


# Published check values for both algorithms over the string "123456789".
# These pin the polynomial and the reflection convention to a source outside
# this repository.
assert crc32c(b"123456789") == 0xE306_9283, "CRC-32C golden self-test failed"
assert crc8_rohc(b"123456789") == 0xD0, "CRC-8/ROHC golden self-test failed"

# Word mode must consume the operand least-significant byte first, and that is
# anchored OUTSIDE this file rather than against its own byte path: running
# "123456789" as two little-endian words plus one trailing byte has to reach
# the published CRC-32C check value. A big-endian transcription of word mode
# reaches a different value and fails here.
_CHECK_WORDS = (0x3433_3231, 0x3837_3635)  # "1234", "5678" little-endian
_crc = 0xFFFF_FFFF
for _w in _CHECK_WORDS:
    _crc = update(MODE_32C_WORD, _crc, _w)
_crc = update(MODE_32C_BYTE, _crc, ord("9"))
assert (_crc ^ 0xFFFF_FFFF) == 0xE306_9283, "CRC-32C word-mode byte-order self-test failed"
del _crc, _w
