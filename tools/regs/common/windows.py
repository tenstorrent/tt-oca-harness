# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

"""Size the window each unit of a map owns from the place the map gives it.

A generated register block decodes a power-of-two window and matches only the
low address bits of that window, so the window's base must be a multiple of its
size. The place of an instance gives the window it owns:

* A child of a page top starts on a 4 KiB boundary and owns the whole pages its
  registers or memory reach.
* A child of a wrapper owns the space up to the next child, or to the end of
  the wrapper's window. A register block that is the last child, outside an
  array element, keeps the window its registers need.
* An element of an array owns the array's stride.
* A register block in any other map keeps the window its registers need.

The instances of one block share one generated module, so the block decodes
the smallest window any of its instances owns, and an instance with more room
leaves the rest to its wrapper.

A register block answers between and past its registers as its generator
options make it, and a wrapper placed in a page top answers past its sub-blocks
as it does between them. WindowSizer.sized records all of this once; the
address widths, the window packages and the memory maps are read from that
record. A map line states a window only for a unit the flow generates no
decoder for, and only one wider than its pages in a page top or narrower than
the space a wrapper leaves it.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from math import prod
from typing import Any, Iterable

from systemrdl.node import AddrmapNode, MemNode, Node, RegfileNode, RegNode, RootNode

PAGE_SIZE = 0x1000
_ADDRESSABLE = (AddrmapNode, MemNode, RegfileNode, RegNode)
_PROPERTIES = {
    "size": "ocah_aperture_size",
    "hole": "ocah_hole_resp",
    "past": "ocah_past_extent_resp",
}


@dataclass(frozen=True)
class Placement:
    path: str
    needed: int
    decoded: int
    room: int
    owns_room: bool


def _clog2(value: int) -> int:
    return max(0, (value - 1).bit_length())


def _is_pow2(value: int) -> bool:
    return value > 0 and not value & (value - 1)


def _largest_aligned(base: int, room: int) -> int:
    size = 1 << (room.bit_length() - 1)
    while base % size:
        size >>= 1
    return size


def needed_window(node: AddrmapNode) -> int:
    """The smallest window that holds the block's registers."""
    return 1 << _clog2(int(node.size))


def decoded_window(node: AddrmapNode) -> int:
    """The window the register block decodes without an address width override."""
    width = max(
        (
            int(reg.get_property("accesswidth"))
            for reg in node.descendants()
            if isinstance(reg, RegNode)
        ),
        default=8,
    )
    return max(needed_window(node), 1 << (_clog2(width // 8) + 1))


def type_name(node: Node) -> str:
    return node.orig_type_name or node.type_name


def _path(node: Node) -> str:
    names = []
    while not isinstance(node, RootNode):
        names.append(node.inst_name)
        node = node.parent
    return ".".join(reversed(names))


def _inherited(node: Node, name: str) -> Any:
    while not isinstance(node, RootNode):
        value = node.get_property(name, default=None)
        if value is not None:
            return value
        node = node.parent
    return None


def _answers_as(node: Node, *codes: str) -> bool:
    value = _inherited(node, "ocah_hole_resp")
    return value is not None and bool({value.rresp.name, value.bresp.name} & set(codes))


def _response(rresp: str, rdata: int = 0, bresp: str | None = None) -> dict[str, str]:
    return {"rresp": rresp, "rdata": f"0x{rdata:X}", "bresp": bresp or rresp}


def _children(node: Node) -> list[Node]:
    return sorted(
        (child for child in node.children(unroll=False) if isinstance(child, _ADDRESSABLE)),
        key=lambda child: child.raw_address_offset,
    )


class WindowSizer:
    def __init__(
        self,
        regblocks: Iterable[str],
        wrappers: Iterable[str],
        err_check: Iterable[str] = (),
        no_err: Iterable[str] = (),
    ) -> None:
        self.regblocks = set(regblocks)
        self.wrappers = set(wrappers)
        self.err_check = set(err_check)
        self.no_err = set(no_err)
        self.placements: dict[str, list[Placement]] = {}
        self.units: dict[str, dict[str, Any]] = {}
        self.errors: list[str] = []

    def add_top(self, top: AddrmapNode, pages: bool) -> None:
        """Size the windows under one map."""
        if pages:
            self._pages(top)
        elif type_name(top) in self.wrappers:
            self._split(top, int(top.size), False)
        else:
            children = _children(top)
            for child, following in zip(children, children[1:] + [None]):
                if type_name(child) not in self.regblocks:
                    continue
                room = (
                    max(int(child.total_size), decoded_window(child))
                    if following is None
                    else int(following.raw_address_offset) - int(child.raw_address_offset)
                )
                self._visit(child, room, False)

    def _pages(self, top: AddrmapNode) -> None:
        for child in _children(top):
            base = int(child.raw_address_offset)
            if base % PAGE_SIZE:
                self.errors.append(f"{_path(child)}: starts at 0x{base:X}, not on a 4 KiB boundary")
                continue
            if _answers_as(child, "ADOPTER"):
                continue
            span = -(-int(child.total_size) // PAGE_SIZE) * PAGE_SIZE
            name = type_name(child)
            if name in self.regblocks:
                self.units[_path(child)] = {"size": span}
            else:
                self._record(child, span, True)
            gap = _inherited(child, "ocah_gap_resp")
            if name in self.wrappers and gap is not None:
                self._derived(child, "a wrapper placed in a page top", "past")["past"] = _response(
                    gap.rresp.name, int(gap.rdata), gap.bresp.name
                )
            self._visit(child, span, True)

    def _split(self, wrapper: AddrmapNode, window: int, element: bool) -> None:
        children = _children(wrapper)
        for child, following in zip(children, children[1:] + [None]):
            base = int(child.raw_address_offset)
            end = window if following is None else int(following.raw_address_offset)
            name = type_name(child)
            if base + int(child.total_size) > end:
                self.errors.append(
                    f"{_path(child)}: ends at 0x{base + int(child.total_size) - 1:X}, past "
                    f"the 0x{end:X} where its window in {wrapper.inst_name} ends"
                )
            elif name in self.regblocks or name in self.wrappers:
                self._visit(child, end - base, following is not None or element)
            elif not child.is_array and not _answers_as(child, "FORWARD", "ADOPTER"):
                self._record(child, end - base, False)

    def _visit(self, node: Node, room: int, owns_room: bool) -> None:
        if not isinstance(node, AddrmapNode) or _answers_as(node, "FORWARD", "ADOPTER"):
            return
        if node.is_array:
            stride = int(node.array_stride)
            if prod(node.array_dimensions) * stride > room:
                self.errors.append(f"{_path(node)}: its elements reach past 0x{room:X}")
                return
            room, owns_room = stride, True
        base = int(node.raw_absolute_address)
        if not owns_room:
            room = _largest_aligned(base, room)
        name = type_name(node)
        if name in self.wrappers:
            self._split(node, room, node.is_array)
        elif name in self.regblocks:
            if owns_room and not (_is_pow2(room) and base % room == 0):
                self.errors.append(
                    f"{_path(node)}: owns 0x{room:X} bytes at 0x{base:X}, but a register "
                    "block decodes a power-of-two window whose base is a multiple of its size"
                )
                return
            self.placements.setdefault(name, []).append(
                Placement(_path(node), needed_window(node), decoded_window(node), room, owns_room)
            )
            unit = self._derived(node, "a register block", *_PROPERTIES)
            if node.is_array:
                unit.setdefault("size", int(node.total_size))
            checked = name in self.err_check
            unit["hole"] = _response("SLVERR" if checked else "OKAY")
            unit["past"] = _response("SLVERR" if checked or name not in self.no_err else "OKAY")

    def _record(self, node: Node, size: int, widens: bool) -> None:
        """Give a unit with no generated decoder its window, unless its line states one."""
        stated = node.get_property("ocah_aperture_size", default=None)
        if stated is None:
            self.units[_path(node)] = {"size": size}
        elif stated == size or (stated > size) != widens:
            self.errors.append(
                f"{_path(node)}: ocah_aperture_size 0x{int(stated):X} does not "
                f"{'widen' if widens else 'narrow'} the 0x{size:X} window the map gives the "
                "unit; remove the assignment"
            )

    def _derived(self, node: Node, kind: str, *keys: str) -> dict[str, Any]:
        """The record of a unit whose line may not state what the generator derives."""
        self.errors.extend(
            f"{_path(node)}: states {_PROPERTIES[key]}, which the generator derives for "
            f"{kind}; remove the assignment"
            for key in keys
            if node.get_property(_PROPERTIES[key], default=None) is not None
        )
        return self.units.setdefault(_path(node), {})

    def sized(self) -> dict[str, dict[str, Any]]:
        """The address width of each block wider than its registers need, and each unit's window.

        A register block's window is the one its instances share.
        """
        widths: dict[str, int] = {}
        for name, placements in sorted(self.placements.items()):
            needed = max(place.needed for place in placements)
            decoded = max(place.decoded for place in placements)
            owned = [place.room for place in placements if place.owns_room]
            window = min(owned) if owned else decoded
            if not needed <= window <= min(place.room for place in placements):
                self.errors.append(
                    f"{name}: no one window suits every instance: "
                    + "; ".join(
                        f"{place.path} needs 0x{place.needed:X} and has room for 0x{place.room:X}"
                        for place in placements
                    )
                )
                continue
            for place in placements:
                self.units[place.path].setdefault("size", max(window, decoded))
            if window > decoded:
                widths[name] = window.bit_length() - 1
        return {
            "addr_widths": widths,
            "windows": {
                path: {
                    "size": f"0x{unit['size']:X}",
                    **{key: unit[key] for key in ("hole", "past") if key in unit},
                }
                for path, unit in self.units.items()
                if "size" in unit
            },
        }


def state_windows(top: AddrmapNode, windows: dict[str, dict[str, Any]]) -> None:
    """Give the units of a map the windows and responses the generator sized.

    The values become the units' own properties, so every reader of the map sees
    them.
    """
    struct = top.env.property_rules.user_properties["ocah_past_extent_resp"].valid_type
    codes = {code.name: code for code in struct._members["rresp"]}
    unplaced = {path for path in windows if path.startswith(f"{top.inst_name}.")}
    for node in top.descendants(unroll=False):
        unit = windows.get(_path(node))
        if unit is None:
            continue
        unplaced.discard(_path(node))
        properties = node.inst.properties
        for key in ("hole", "past"):
            if key in unit:
                properties[_PROPERTIES[key]] = struct(
                    {
                        "rresp": codes[unit[key]["rresp"]],
                        "rdata": int(unit[key]["rdata"], 16),
                        "bresp": codes[unit[key]["bresp"]],
                    }
                )
        properties["ocah_aperture_size"] = int(unit["size"], 16)
    if unplaced:
        raise ValueError(
            f"{top.inst_name}: the windows file sizes units this map does not place: "
            + ", ".join(sorted(unplaced))
        )


def render_windows(sized: dict[str, dict[str, Any]]) -> str:
    """The record as JSON, with one block or unit to a line."""
    sections = (
        f"  {json.dumps(section)}: {{\n"
        + ",\n".join(
            f"    {json.dumps(key)}: {json.dumps(value)}" for key, value in entries.items()
        )
        + "\n  }"
        for section, entries in sized.items()
    )
    return "{\n" + ",\n".join(sections) + "\n}\n"


def render_window_pkg(top: str, sized: dict[str, dict[str, Any]]) -> str:
    """The window of each unit placed directly in a page top."""
    sizes = (
        f"localparam longint unsigned {path.replace('.', '_').upper()}_WINDOW_SIZE"
        f" = 64'h{unit['size'][2:]};"
        for path, unit in sized["windows"].items()
        if path.split(".")[:-1] == [top]
    )
    lines = [
        "// SPDX-License-Identifier: Apache-2.0",
        "// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.",
        "",
        "// Generated by tools/regs/rdlwindows.py; do not edit. The window each unit",
        f"// of {top} owns: the whole 4 KiB pages from its base address.",
        "",
        f"package {top}_window_pkg;",
        "",
        *sizes,
        "",
        "endpackage",
    ]
    return "\n".join(lines) + "\n"
