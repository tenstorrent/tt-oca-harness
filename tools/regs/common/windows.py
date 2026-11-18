# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

"""Size the window each generated register block decodes from the maps that place it.

A generated register block decodes a power-of-two window and matches only the
low address bits of that window, so the window's base must be a multiple of its
size. The place of an instance gives the window it owns:

* A child of a page top starts on a 4 KiB boundary and owns whole pages.
* A child of a wrapper owns the space up to the next child, or to the end of
  the array element that holds it. The last child of a wrapper that is not an
  array keeps the window its registers need.
* An element of an array owns the array's stride.
* Any other block owns its ocah_aperture_size, or else the window its
  registers need.

The instances of one block share one generated module, so the block decodes
the smallest window any of its instances owns, and an instance with more room
leaves the rest to its wrapper.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import prod
from typing import Iterable

from systemrdl.node import AddrmapNode, MemNode, Node, RegfileNode, RegNode, RootNode

PAGE_SIZE = 0x1000
_ADDRESSABLE = (AddrmapNode, MemNode, RegfileNode, RegNode)
_FORWARDED = {"FORWARD", "ADOPTER"}


@dataclass(frozen=True)
class Placement:
    path: str
    needed: int
    decoded: int
    room: int
    owns_room: bool
    stated: int | None


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


def _stated(node: Node) -> int | None:
    value = node.get_property("ocah_aperture_size", default=None)
    return None if value is None else int(value)


def _forwarded(node: Node) -> bool:
    while not isinstance(node, RootNode):
        value = node.get_property("ocah_hole_resp", default=None)
        if value is not None:
            return bool({value.rresp.name, value.bresp.name} & _FORWARDED)
        node = node.parent
    return False


def _children(node: Node) -> list[Node]:
    return sorted(
        (child for child in node.children(unroll=False) if isinstance(child, _ADDRESSABLE)),
        key=lambda child: child.raw_address_offset,
    )


class WindowSizer:
    def __init__(self, regblocks: Iterable[str], wrappers: Iterable[str]) -> None:
        self.regblocks = set(regblocks)
        self.wrappers = set(wrappers)
        self.placements: dict[str, list[Placement]] = {}
        self.errors: list[str] = []

    def add_top(self, top: AddrmapNode, pages: bool) -> None:
        if pages:
            self._pages(top)
        elif type_name(top) in self.wrappers:
            self._split(top, int(top.size), False)
        else:
            for child in _children(top):
                if isinstance(child, AddrmapNode) and type_name(child) in self.regblocks:
                    self._visit(child, _stated(child) or needed_window(child), False)

    def _pages(self, top: AddrmapNode) -> None:
        children = _children(top)
        for child, following in zip(children, children[1:] + [None]):
            base = int(child.raw_address_offset)
            span = -(-max(int(child.total_size), _stated(child) or 0) // PAGE_SIZE) * PAGE_SIZE
            if base % PAGE_SIZE:
                self.errors.append(
                    f"{child.get_path()}: starts at 0x{base:X}, not on a 4 KiB boundary"
                )
                continue
            if following is not None and base + span > following.raw_address_offset:
                self.errors.append(
                    f"{child.get_path()}: its pages end at 0x{base + span - 1:X}, past "
                    f"{following.inst_name} at 0x{following.raw_address_offset:X}"
                )
            self._visit(child, span, True)

    def _split(self, wrapper: AddrmapNode, window: int, element: bool) -> None:
        children = _children(wrapper)
        for child, following in zip(children, children[1:] + [None]):
            base = int(child.raw_address_offset)
            end = window if following is None else int(following.raw_address_offset)
            if base + int(child.total_size) > end:
                self.errors.append(
                    f"{child.get_path()}: ends at 0x{base + int(child.total_size) - 1:X}, past "
                    f"the 0x{end:X} where its window in {wrapper.inst_name} ends"
                )
                continue
            self._visit(child, end - base, following is not None or element)

    def _visit(self, node: Node, room: int, owns_room: bool) -> None:
        if not isinstance(node, AddrmapNode) or _forwarded(node):
            return
        if node.is_array:
            stride = int(node.array_stride)
            if prod(node.array_dimensions) * stride > room:
                self.errors.append(f"{node.get_path()}: its elements reach past 0x{room:X}")
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
                    f"{node.get_path()}: owns 0x{room:X} bytes at 0x{base:X}, but a register "
                    "block decodes a power-of-two window whose base is a multiple of its size"
                )
                return
            self.placements.setdefault(name, []).append(
                Placement(
                    node.get_path(),
                    needed_window(node),
                    decoded_window(node),
                    room,
                    owns_room,
                    None if node.is_array else _stated(node),
                )
            )

    def widths(self) -> dict[str, int]:
        """Address width of each block whose window is wider than its registers need."""
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
            self.errors.extend(
                f"{place.path}: ocah_aperture_size is 0x{place.stated:X}, but {name} "
                f"decodes 0x{window:X}"
                for place in placements
                if place.stated is not None and place.stated != window
            )
            if window > decoded:
                widths[name] = window.bit_length() - 1
        return widths


def render_widths(widths: dict[str, int]) -> str:
    lines = [
        "# SPDX-License-Identifier: Apache-2.0",
        "# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.",
        "",
        "# Generated by tools/regs/rdlwindows.py; do not edit. The address width of",
        "# each register block whose window is wider than its registers need.",
        "",
        *(f"OCAH_REG_ADDR_WIDTH_{name} := {width}" for name, width in sorted(widths.items())),
    ]
    return "\n".join(lines) + "\n"
