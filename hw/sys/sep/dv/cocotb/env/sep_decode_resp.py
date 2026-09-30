# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Unmapped-access responses stated by the generated SEP memory map.

``hw/sys/sep/regs/gen/adoc/memory_map.adoc`` (tag ``sep-components``) is the
SEP components table, rendered from ``hw/sys/sep/regs/sep.rdl``. Each row gives
a unit's aperture (Base Address to End Address), its Decoded Extent (the part
that registers or memory back), and two response cells for a 32-bit access
that no register or memory backs, as seen at the SEP inbound AXI port:

* Hole in Extent: an unbacked offset inside the decoded extent;
* Past Extent: the rest of the aperture.

A cell reads ``RRESP, RDATA / BRESP`` (``doc/trm/src/memory_map.adoc``,
Decode Response Codes). ``-`` means no such offset exists. A numbered note
qualifies a cell. This module models the two notes a SEP inbound probe can
meet, each through a strict pattern:

* read data: "A 32-bit read with address bit 2 set returns 0x<word>.";
* write code: "A write to a reserved address in <range> or <range> answers
  <code>."

The table carries the RDL read data exactly. ``rdata`` in ``sep.rdl`` is a
64-bit value (``ocah_resp`` in ``hw/common/regs/regblock_udps.rdl``), and the
renderer (``tools/regs/common/memorymap.py``, ``Response.adoc``) prints its low
word and adds the bit-2 note exactly when the upper word is non-zero. A cell
with no note therefore states an upper word of 0 in the RDL.

For a read with address bit 2 set, a cell with no note and a non-zero low word
is not graded on its data: the RDL states 0 there, while the Decode Response
Codes definition of a cell gives one read word per 32-bit access. The two
readings disagree, so ``Expected.rdata`` is None and ``rdata_note`` says why;
the response code is still graded. Every other read has one stated word.

A lookup that meets any other note, or a cell that is not a bus response
(``Forwarded``, ``Adopter-defined``), raises: the expectation is not modeled,
so the caller must not probe there.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

_REPO = Path(__file__).resolve().parents[6]
_MAP = _REPO / "hw" / "sys" / "sep" / "regs" / "gen" / "adoc" / "memory_map.adoc"
_TAG = "sep-components"

# AMBA AXI4 (IHI 0022) response codes.
RESP_CODE = {"OKAY": 0, "SLVERR": 2, "DECERR": 3}

_NOTE_REF = r"(?:\^<<" + _TAG + r"-note-(\d+),\[\d+\]>>\^)?"
_CODE = r"(OKAY|SLVERR|DECERR)"
_CELL = re.compile(rf"^{_CODE}, 0x([0-9A-Fa-f]+){_NOTE_REF} / {_CODE}{_NOTE_REF}$")
_NOTE_DEF = re.compile(r"^\[\[" + _TAG + r"-note-(\d+)\]\]\^\[\d+\]\^ (.*?)(?: \+)?$")
_NOTE_RDATA = re.compile(r"^A 32-bit read with address bit 2 set returns 0x([0-9A-Fa-f]+)\.$")
_RANGE = r"0x[0-9A-Fa-f_]+-0x[0-9A-Fa-f_]+"
_NOTE_WRITE = re.compile(
    rf"^A write to a reserved address in ({_RANGE}(?: or {_RANGE})*) answers {_CODE}\.$"
)
_SIZE = re.compile(r"^(\d+) (B|KiB|MiB|GiB)$")
_UNIT = {"B": 1, "KiB": 1 << 10, "MiB": 1 << 20, "GiB": 1 << 30}


@dataclass(frozen=True)
class Cell:
    """One response cell: the RDL read data as ``rdata_hi:rdata_lo``, where
    ``hi_noted`` says the bit-2 note stated ``rdata_hi``; ``write_ranges`` and
    ``write_code`` override ``bresp`` there."""

    text: str
    rresp: str | None = None
    rdata_lo: int = 0
    rdata_hi: int = 0
    hi_noted: bool = False
    bresp: str | None = None
    write_ranges: tuple[tuple[int, int], ...] = ()
    write_code: str | None = None
    unmodeled: str = ""


@dataclass(frozen=True)
class MapRow:
    base: int
    end: int
    extent: int
    unit: str
    hole: Cell | None
    past: Cell | None


@dataclass(frozen=True)
class Expected:
    """What the map states for one 32-bit access."""

    resp: int
    rdata: int | None  # None for a write, or for a read whose data is not graded
    row: str
    column: str
    cell: str
    rdata_note: str = ""  # why a read's data is not graded


def _size(text: str) -> int:
    m = _SIZE.match(text.strip())
    if not m:
        raise ValueError(f"memory_map.adoc: size {text!r} is not '<n> B|KiB|MiB|GiB'")
    return int(m.group(1)) * _UNIT[m.group(2)]


def _cell(text: str, notes: dict[str, str]) -> Cell | None:
    text = text.strip()
    if text == "-":
        return None
    m = _CELL.match(text)
    if not m:
        return Cell(text, unmodeled=f"cell {text!r} is not a bus response")
    rresp, rdata, rnote, bresp, wnote = m.groups()
    hi = 0
    noted = False
    ranges: tuple[tuple[int, int], ...] = ()
    wcode = None
    unmodeled = ""
    if rnote:
        n = _NOTE_RDATA.match(notes[rnote])
        if n:
            hi = int(n.group(1), 16)
            noted = True
        else:
            unmodeled = f"read note [{rnote}] {notes[rnote]!r}"
    if wnote:
        n = _NOTE_WRITE.match(notes[wnote])
        if n:
            spans = []
            for r in n.group(1).split(" or "):
                lo, hi_end = (int(x.replace("_", ""), 16) for x in r.split("-"))
                spans.append((lo, hi_end))
            ranges = tuple(spans)
            wcode = n.group(2)
        else:
            unmodeled = f"write note [{wnote}] {notes[wnote]!r}"
    return Cell(text, rresp, int(rdata, 16), hi, noted, bresp, ranges, wcode, unmodeled)


@lru_cache(maxsize=1)
def sep_map_rows() -> tuple[MapRow, ...]:
    """Parse the ``sep-components`` table of the generated SEP memory map."""
    text = _MAP.read_text(encoding="utf-8")
    try:
        body = text.split(f"// tag::{_TAG}[]", 1)[1].split(f"// end::{_TAG}[]", 1)[0]
    except IndexError as exc:
        raise ValueError(f"{_MAP}: tag {_TAG} not found") from exc
    notes: dict[str, str] = {}
    for line in body.splitlines():
        m = _NOTE_DEF.match(line.strip())
        if m:
            notes[m.group(1)] = m.group(2)
    rows: list[MapRow] = []
    header_ok = False
    for line in body.splitlines():
        line = line.strip()
        if line.startswith("|Base Address"):
            cols = [c.strip() for c in line[1:].split(" |")]
            header_ok = cols == [
                "Base Address",
                "End Address",
                "Size",
                "Decoded Extent",
                "Unit",
                "Description",
                "Hole in Extent (R / W)",
                "Past Extent (R / W)",
            ]
            if not header_ok:
                raise ValueError(f"{_MAP}: unexpected {_TAG} columns {cols}")
            continue
        if not line.startswith("|0x"):
            continue
        cols = [c.strip() for c in line[1:].split(" |")]
        if len(cols) != 8:
            raise ValueError(f"{_MAP}: row has {len(cols)} cells, want 8: {line}")
        base, end = int(cols[0], 16), int(cols[1], 16)
        if _size(cols[2]) != end - base + 1:
            raise ValueError(f"{_MAP}: {cols[4]} size {cols[2]} disagrees with its bounds")
        rows.append(
            MapRow(
                base,
                end,
                _size(cols[3]),
                cols[4],
                _cell(cols[6], notes),
                _cell(cols[7], notes),
            )
        )
    if not header_ok or not rows:
        raise ValueError(f"{_MAP}: no {_TAG} table found")
    for a, b in zip(rows, rows[1:]):
        if b.base <= a.end:
            raise ValueError(f"{_MAP}: rows {a.unit} and {b.unit} overlap or are out of order")
    return tuple(rows)


def sep_map_row(addr: int) -> MapRow:
    for row in sep_map_rows():
        if row.base <= addr <= row.end:
            return row
    raise KeyError(f"0x{addr:08x} is outside the SEP components table")


def expected_unbacked(addr: int, op: str) -> Expected:
    """The response the map states for a 32-bit ``op`` ("r" | "w") at ``addr``.

    ``addr`` must be an offset that no register or memory backs. Raises if the
    map has no cell for it, or if the cell carries a note this module does not
    model.
    """
    if addr % 4:
        raise ValueError(f"0x{addr:08x} is not a 32-bit word address")
    row = sep_map_row(addr)
    in_extent = addr < row.base + row.extent
    column = "Hole in Extent" if in_extent else "Past Extent"
    cell = row.hole if in_extent else row.past
    where = f"0x{addr:08x} ({row.unit}, {column})"
    if cell is None:
        raise ValueError(f"{where}: the map gives no response here; nothing unbacked to probe")
    if cell.unmodeled:
        raise ValueError(f"{where}: {cell.unmodeled} is not modeled")
    if op == "r":
        if not addr & 0x4:
            rdata = cell.rdata_lo
        elif cell.hi_noted or cell.rdata_lo == 0:
            rdata = cell.rdata_hi
        else:
            note = (
                f"sep.rdl states upper word 0x{cell.rdata_hi:08x}; the cell states one word "
                f"0x{cell.rdata_lo:08x} for a 32-bit access"
            )
            return Expected(RESP_CODE[cell.rresp], None, row.unit, column, cell.text, note)
        return Expected(RESP_CODE[cell.rresp], rdata, row.unit, column, cell.text)
    code = cell.bresp
    if cell.write_code and any(lo <= addr <= hi for lo, hi in cell.write_ranges):
        code = cell.write_code
    return Expected(RESP_CODE[code], None, row.unit, column, cell.text)


def _selftest() -> None:
    rows = sep_map_rows()
    # A parse that silently matched nothing would leave every lookup to raise.
    assert len(rows) >= 30, len(rows)
    assert rows[0].base == 0x1000_0000
    cells = [c for r in rows for c in (r.hole, r.past) if c is not None]
    # Both modeled notes must parse somewhere, or a reworded note would silently
    # drop the bit-2 read word or the write-code override.
    assert any(c.hi_noted for c in cells)
    assert any(c.write_ranges for c in cells)


_selftest()
