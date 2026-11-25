# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Expected SEP status-ring entries under the severity reservation of the ROM spec.

rom.adoc, Status Reporting:

    [SEP-ROM-STAT-020] Capacity shall be reserved by severity so an error can always be
    recorded: `INFO`-class inserts require 3 free slots and degrade to an `INFO_OVERFLOW`
    marker at exactly 3; `WARN` requires 2, degrading to `WARNING_OVERFLOW`; `ERROR` inserts
    down to the last free slot.

    Status ring | SMC SRAM (offset from scratch[11]) | Every non-`DEBUG` status, consumed by
    the SMC and forwarded to the platform (OCCP).

status-errors.adoc, Status ring:

    Capacity is reserved by severity. Informational status preserves space for a warning and
    an error; warning status preserves space for an error. At the reservation boundary BL0
    inserts the corresponding overflow marker. An error can use the final free entry.

The model starts from an empty ring (head == tail) that nothing drains. Inferences, since the
SEP ROM docs leave these points open:

* The header holds only `head` and `tail`, so head == tail must mean empty and a ring of
  `num_entries` slots holds at most `num_entries - 1` entries: the free count is
  `num_entries - 1 - used`.
* A status with fewer free slots than its class requires is dropped, and an ERROR is dropped at
  0 free; the spec says "require" and "preserve" but does not name the outcome below the reserve.
* The spec names the overflow markers but not their type byte; the model writes the class type
  (INFO for INFO_OVERFLOW, WARN for WARNING_OVERFLOW) and `entry_matches` does not grade it.
* The spec does not say which class `INFO_EXT` belongs to; the model counts it as INFO-class.
  The other reading, that an `INFO_EXT` payload shares the fate of its preceding status, is
  not modelled.

Run ``python3 sep_rom_status_ring_model.py`` for the self-test.
"""

from __future__ import annotations

TYPE_INFO = 0x01
TYPE_WARN = 0x08
TYPE_ERROR = 0x0F
TYPE_DEBUG = 0x80
TYPE_INFO_EXT = 0x81
BL0_ID = 0x01
INFO_OVERFLOW = 0xFFFE
WARNING_OVERFLOW = 0xFFFF
_MARKERS = (INFO_OVERFLOW, WARNING_OVERFLOW)


def encode(kind: int, code: int) -> int:
    """STATUS_ENCODE(type, value) of a BL0 status."""
    return (kind & 0xFF) << 24 | BL0_ID << 16 | code & 0xFFFF


def kind(word: int) -> int:
    return word >> 24 & 0xFF


def ring_trace(words, capacity: int) -> list[tuple[int, str, int | None]]:
    """(offered word, action, entry written or None) per non-DEBUG word; action is
    insert, marker or drop."""
    if capacity < 1:
        raise ValueError(f"num_entries {capacity} leaves no slot; a ring needs at least one")
    free = capacity - 1
    out: list[tuple[int, str, int | None]] = []
    for w in words:
        t = kind(w)
        if t == TYPE_DEBUG:
            continue
        if t == TYPE_ERROR:
            need, marker = 1, None
        elif t == TYPE_WARN:
            need, marker = 2, encode(TYPE_WARN, WARNING_OVERFLOW)
        elif t in (TYPE_INFO, TYPE_INFO_EXT):
            need, marker = 3, encode(TYPE_INFO, INFO_OVERFLOW)
        else:
            raise ValueError(f"status 0x{w:08x} has type 0x{t:02x}, which the spec does not define")
        if free < need:
            out.append((w, "drop", None))
        elif free == need and marker is not None:
            out.append((w, "marker", marker))
            free -= 1
        else:
            out.append((w, "insert", w))
            free -= 1
    return out


def expected_ring(words, capacity: int) -> list[int]:
    """Entries the ring holds, oldest first, after the statuses `words` were offered."""
    return [e for _, _, e in ring_trace(words, capacity) if e is not None]


def entry_matches(got: int, exp: int) -> bool:
    """Compares one entry; the type byte of an overflow marker is not graded."""
    if exp & 0xFFFF in _MARKERS:
        return got & 0x00FF_FFFF == exp & 0x00FF_FFFF
    return got == exp


def _selftest() -> None:
    def info(c):
        return encode(TYPE_INFO, c)

    def ext(c):
        return encode(TYPE_INFO_EXT, c)

    def warn(c):
        return encode(TYPE_WARN, c)

    def err(c):
        return encode(TYPE_ERROR, c)

    i_ovf = 0x0101_FFFE
    w_ovf = 0x0801_FFFF
    assert (
        encode(TYPE_INFO, INFO_OVERFLOW) == i_ovf and encode(TYPE_WARN, WARNING_OVERFLOW) == w_ovf
    )

    # INFO inserts while 4+ slots are free, the marker at exactly 3, drops below; DEBUG skipped.
    words = [info(0x10), ext(0x64), encode(TYPE_DEBUG, 0x44), info(0x11), ext(0), info(0x12)]
    words += [info(0x13), info(0x14)]
    got = expected_ring(words, 8)
    assert got == [info(0x10), ext(0x64), info(0x11), ext(0), i_ovf], [hex(w) for w in got]
    acts = [a for _, a, _ in ring_trace(words, 8)]
    assert acts == ["insert"] * 4 + ["marker", "drop", "drop"], acts

    # Run shape: INFO fills to the boundary, then WARN degrades and ERROR takes the last slot.
    words = [info(c) for c in range(1, 7)] + [warn(0x2A), err(0x2A), err(0x213)]
    got = expected_ring(words, 8)
    assert got == [info(1), info(2), info(3), info(4), i_ovf, w_ovf, err(0x2A)], got
    assert [a for _, a, _ in ring_trace(words, 8)][-3:] == ["marker", "insert", "drop"]

    # WARN inserts while 3+ are free, the marker at exactly 2, drops at 1; ERROR fills the last.
    words = [warn(1), warn(2), warn(3), info(1), err(1), err(2)]
    got = expected_ring(words, 4)
    assert got == [warn(1), w_ovf, err(1)], [hex(w) for w in got]
    assert [a for _, a, _ in ring_trace(words, 4)] == [
        "insert",
        "marker",
        "drop",
        "drop",
        "insert",
        "drop",
    ]

    # A WARN that takes the INFO boundary slot leaves no INFO marker; ERROR uses both last slots.
    words = [info(c) for c in range(1, 5)] + [warn(1), info(5), err(1), err(2), err(3)]
    got = expected_ring(words, 8)
    assert got == [info(1), info(2), info(3), info(4), warn(1), err(1), err(2)], got

    # The first INFO of a 4-slot ring is already at the boundary.
    assert expected_ring([info(1), info(2), err(1)], 4) == [i_ovf, err(1)]

    assert entry_matches(0x0F01_FFFE, i_ovf) and not entry_matches(0x0102_FFFE, i_ovf)
    assert not entry_matches(0x0801_002A, 0x0101_002A)
    for bad in ((info(1),), 0), ((0x0201_0001,), 8):
        try:
            expected_ring(*bad)
        except ValueError:
            pass
        else:
            raise AssertionError(f"expected_ring{bad} must refuse")
    print("sep_rom_status_ring_model self-test PASS")


if __name__ == "__main__":
    _selftest()
