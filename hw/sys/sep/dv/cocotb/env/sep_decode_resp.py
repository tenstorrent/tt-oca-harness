# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Unmapped-access responses stated by the SEP SystemRDL memory map.

``hw/sys/sep/regs/gen/py/sep_memory_map.py`` is generated from
``hw/sys/sep/regs/sep.rdl`` by ``tools/regs/rdlmap.py`` (the same model that
renders ``memory_map.adoc``). Its ``sep-components`` view gives each unit's
aperture (``base`` to ``end``), its Decoded Extent (``occupied_size``, the part
that registers or memory back), and the ``ocah_resp`` responses for a 32-bit
access that no register or memory backs, as seen at the SEP inbound AXI port:

* Hole in Extent (``hole_responses``): an unbacked offset inside the extent;
* Past Extent (``past_response``): the rest of the aperture.

A response gives the read code, the RDL read data and the write code
(``doc/trm/src/memory_map.adoc``, Decode Response Codes). A row with no
response has no such offset. The RDL notes on a row qualify its responses, and
this module models none of them.

``rdata`` in ``sep.rdl`` is a 64-bit field (``ocah_resp`` in
``hw/common/regs/regblock_udps.rdl``). A 64-bit RDL rdata states both words:
the low word for address bit 2 clear and the upper word for address bit 2 set.
An RDL rdata that carries no upper word (a 32-bit value such as
``0xBADCAB1E``) is the word a 32-bit read returns on either half of the bus
(the ``ocah_resp.rdata`` definition and Decode Response Codes in
``doc/trm/src/memory_map.adoc``), so every read has one stated word.

A lookup that meets a note, a row with more than one hole response, or
a response that is not a bus response (``FORWARD``, ``ADOPTER``) raises: the
expectation is not modeled, so the caller must not probe there.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

_GEN_PY = Path(__file__).resolve().parents[3] / "regs" / "gen" / "py"
if _GEN_PY.is_dir() and str(_GEN_PY) not in sys.path:
    sys.path.insert(0, str(_GEN_PY))

import sep_memory_map  # noqa: E402  (path bootstrap must precede the import)

_VIEW = "sep-components"

# AMBA AXI4 (IHI 0022) response codes.
RESP_CODE = {"OKAY": 0, "SLVERR": 2, "DECERR": 3}


@dataclass(frozen=True)
class Cell:
    """One response: the RDL read data as ``rdata_hi:rdata_lo``, where
    ``hi_noted`` says the RDL rdata states ``rdata_hi``."""

    text: str
    rresp: str | None = None
    rdata_lo: int = 0
    rdata_hi: int = 0
    hi_noted: bool = False
    bresp: str | None = None
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
    """What the RDL memory map states for one 32-bit access."""

    resp: int
    rdata: int | None  # None for a write
    row: str
    column: str
    cell: str


def _cell(parts: tuple, notes: tuple[str, ...]) -> Cell | None:
    if not parts:
        return None
    text = "; ".join(f"{label}: {resp['text']}" if label else resp["text"] for label, resp in parts)
    text += "".join(f" [note: {note}]" for note in notes)
    if len(parts) > 1:
        return Cell(text, unmodeled=f"cell {text!r} gives more than one hole response")
    resp = parts[0][1]
    if resp["rresp"] not in RESP_CODE or resp["bresp"] not in RESP_CODE:
        return Cell(text, unmodeled=f"cell {text!r} is not a bus response")
    rdata = int(resp["rdata"])
    unmodeled = f"note {notes[0]!r}" if notes else ""
    return Cell(
        text,
        resp["rresp"],
        rdata & 0xFFFF_FFFF,
        rdata >> 32,
        bool(rdata >> 32),
        resp["bresp"],
        unmodeled,
    )


@lru_cache(maxsize=1)
def sep_map_rows() -> tuple[MapRow, ...]:
    """The ``sep-components`` rows of the generated SEP memory map, in address order."""
    try:
        view = sep_memory_map.VIEWS[_VIEW]
    except KeyError as exc:
        raise ValueError(f"sep_memory_map.py: view {_VIEW} not found") from exc
    rows: list[MapRow] = []
    for r in view["rows"]:
        if r["end"] != r["base"] + r["aperture_size"] - 1:
            raise ValueError(f"sep_memory_map.py: {r['label']} size disagrees with its bounds")
        past = () if r["past_response"] is None else (("", r["past_response"]),)
        past_notes = (r["past_note"],) if r["past_note"] else ()
        rows.append(
            MapRow(
                r["base"],
                r["end"],
                r["occupied_size"],
                r["label"],
                _cell(r["hole_responses"], tuple(r["hole_notes"])),
                _cell(past, past_notes),
            )
        )
    if not rows:
        raise ValueError(f"sep_memory_map.py: view {_VIEW} has no rows")
    rows.sort(key=lambda row: row.base)
    for a, b in zip(rows, rows[1:]):
        if b.base <= a.end:
            raise ValueError(f"sep_memory_map.py: rows {a.unit} and {b.unit} overlap")
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
        # A 32-bit rdata answers on both halves; a 64-bit rdata gives the upper
        # word for address bit 2.
        rdata = cell.rdata_hi if addr & 0x4 and cell.hi_noted else cell.rdata_lo
        return Expected(RESP_CODE[cell.rresp], rdata, row.unit, column, cell.text)
    return Expected(RESP_CODE[cell.bresp], None, row.unit, column, cell.text)


def logical_region(key: str) -> tuple[int, int]:
    """``(base, end)`` of the ``sep-cpu-logical`` view row ``key``."""
    for r in sep_memory_map.VIEWS["sep-cpu-logical"]["rows"]:
        if r["key"] == key:
            return r["base"], r["end"]
    raise KeyError(f"sep_memory_map.py: sep-cpu-logical has no row {key}")


def _selftest() -> None:
    rows = sep_map_rows()
    # A parse that silently matched nothing would leave every lookup to raise.
    assert len(rows) >= 30, len(rows)
    assert rows[0].base == 0x1000_0000
    cells = [c for r in rows for c in (r.hole, r.past) if c is not None]
    # Every error slave answers the same word on both halves of the bus, so the
    # map states 32-bit rdata throughout and no cell carries an upper word.
    assert not any(c.hi_noted for c in cells), [c.text for c in cells if c.hi_noted]


_selftest()
