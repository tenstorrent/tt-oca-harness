# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Transport-level evidence from the SPI flash BFM, for the address-detect tests.

The console cannot establish which flash ADDRESS the ROM interrogated, what the
device answered, or in what order -- ``MANIFEST_SRC=`` proves only what the ROM
intended to read. Without the device side, these tests would check only
manifest integrity.

``OcahSpiFlash.get_transactions()`` records are
``{opcode, addr, data_out, data_in, ok}``, ``data_out`` holding the bytes the flash
streamed back (``ocah_spi_flash.py``, the transaction record dict). ``stop()``
only kills the protocol task and logs a count, so the history survives it.

Everything here matches on "the read whose span COVERS this address" rather than
"addr EQUALS it": the driver may split one ROM request into several CS-framed
bursts, and equality would silently stop checking the first time the
chunk size changed.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence, Tuple

from env import sep_manifest_mutate as mm

# Opcodes per the ocah_spi_flash.py module docstring. The ROM's manifest and payload
# fetches are plain and fast reads; the other opcodes the model decodes (JEDEC ID,
# status, program, erase) are not part of a boot fetch and are excluded so a status
# poll cannot be mistaken for a data read.
READ_OPCODES = (0x03, 0x0B)

Txn = Dict[str, Any]


def reads(transactions: Sequence[Txn]) -> List[Txn]:
    """The data-read transactions, in the order the device served them."""
    return [t for t in transactions if t["opcode"] in READ_OPCODES]


def read_span(txn: Txn) -> Tuple[int, int]:
    """``(start, end)`` flash byte range a read transaction returned."""
    start = int(txn["addr"])
    return start, start + len(txn["data_out"])


def covering_read(rds: Sequence[Txn], addr: int) -> Optional[Tuple[int, Txn]]:
    """First read whose returned span covers ``addr``, as ``(index, txn)``.

    The index is into ``rds`` and is what the ordering assertions compare, so a
    caller can say "the primary was interrogated before the backup" using the
    device's own record rather than the ROM's console.
    """
    for i, t in enumerate(rds):
        start, end = read_span(t)
        if start <= addr < end:
            return i, t
    return None


def bytes_at(txn: Txn, addr: int, count: int) -> bytes:
    """The ``count`` bytes this read returned for flash address ``addr``."""
    start, end = read_span(txn)
    if not (start <= addr and addr + count <= end):
        raise AssertionError(
            f"read at 0x{start:x}..0x{end:x} does not cover 0x{addr:x}..0x{addr + count:x}"
        )
    off = addr - start
    return bytes(txn["data_out"][off : off + count])


def slot_read_indices(rds: Sequence[Txn], slot: str, image_len: int) -> List[int]:
    """Indices of every read that landed inside ``slot``'s flash span.

    Uses the whole slot span, not just the manifest header, because a slot's
    payload is fetched at a manifest-relative offset inside the same span
    (``oca_locate_payload()`` in ``oca_boot.c``) -- so payload traffic is also
    evidence that this address was the one being booted from.
    """
    lo, hi = mm.slot_span(image_len, slot)
    out: List[int] = []
    for i, t in enumerate(rds):
        start, end = read_span(t)
        if start < hi and end > lo:  # any overlap
            out.append(i)
    return out


def all_erased(data: bytes) -> bool:
    """True iff every byte is the erased value, i.e. the address read blank."""
    return len(data) > 0 and all(b == mm.ERASED_BYTE for b in data)


def summarize(transactions: Sequence[Txn], image_len: int, *, limit: int = 12) -> str:
    """Compact one-line-per-read digest for the run log.

    Logged by every one of these testcases whether it passes or fails, so an
    ordering-assertion failure can be read from the address sequence.
    """
    rds = reads(transactions)
    lines = [
        f"{len(transactions)} transactions, {len(rds)} reads; "
        f"primary reads={slot_read_indices(rds, 'primary', image_len)} "
        f"backup reads={slot_read_indices(rds, 'backup', image_len)}"
    ]
    for i, t in enumerate(rds[:limit]):
        start, end = read_span(t)
        head = bytes(t["data_out"][:4])
        lines.append(
            f"  read[{i}] op=0x{t['opcode']:02x} 0x{start:06x}..0x{end:06x} "
            f"({end - start} B) first4={head.hex()}"
            f"{' ALL-0xFF' if all_erased(bytes(t['data_out'])) else ''}"
        )
    if len(rds) > limit:
        lines.append(f"  ... {len(rds) - limit} more reads")
    return "\n".join(lines)
