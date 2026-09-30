# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

"""Build validated, presentation-neutral memory-map views from SystemRDL."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Callable, Iterable

from systemrdl.node import AddrmapNode, MemNode, RegfileNode, RegNode, RootNode
from systemrdl.rdltypes import NoValue

from .rdlview import compile_root as compile_rdl

AddressableNode = AddrmapNode | MemNode | RegNode | RegfileNode

_SELECT_KEYS = {"kind", "source", "selector", "label"}
_GROUP_KEYS = {"kind", "label", "description", "members"}
_RESPONSE_COLUMNS = {"hole_resp", "past_resp"}
_BUS_RESPONSES = {"OKAY", "SLVERR", "DECERR"}
_OPAQUE_RESPONSES = {"FORWARD", "ADOPTER"}


@dataclass(frozen=True)
class Response:
    rresp: Any
    rdata: int
    bresp: Any

    @classmethod
    def from_rdl(cls, value: Any, location: str) -> Response:
        if value is None:
            raise ValueError(f"{location} is not set")
        if value is NoValue:
            raise ValueError(f"{location} has no value")
        rdata = int(value.rdata)
        if rdata and value.rresp.name not in _BUS_RESPONSES:
            raise ValueError(f"{location}: {value.rresp.name} read carries read data")
        return cls(value.rresp, rdata, value.bresp)

    @property
    def opaque(self) -> bool:
        return bool({self.rresp.name, self.bresp.name} & _OPAQUE_RESPONSES)

    @property
    def text(self) -> str:
        return self.adoc(lambda note: "")

    def adoc(self, mark: Callable[[str], str]) -> str:
        """Render the response; read data wider than 32 bits shows its low word."""
        if self.rresp.name not in _BUS_RESPONSES:
            read = self.rresp.rdl_name or self.rresp.name
            if self.bresp.name == self.rresp.name:
                return read
        else:
            read = f"{self.rresp.name}, 0x{self.rdata & 0xFFFFFFFF:X}"
            if self.rdata >> 32:
                read += mark(
                    f"A 32-bit read with address bit 2 set returns 0x{self.rdata >> 32:X}."
                )
        return f"{read} / {self.bresp.rdl_name or self.bresp.name}"


@dataclass(frozen=True)
class MapRow:
    key: str
    label: str
    base: int
    occupied_size: int
    aperture_size: int
    description: str
    count: int = 1
    stride: int = 0
    kind: str = "node"
    hole_responses: tuple[tuple[str, Response], ...] = ()
    past_response: Response | None = None
    hole_notes: tuple[str, ...] = ()
    past_note: str = ""

    @property
    def end(self) -> int:
        return self.base + self.aperture_size - 1


@dataclass(frozen=True)
class MapView:
    name: str
    title: str
    columns: tuple[str, ...]
    rows: tuple[MapRow, ...]
    base_mode: str = "absolute"
    base: int = 0


def compile_root(
    rdl: str | Path,
    udp: str | Path | None = None,
    incdirs: Iterable[str | Path] = (),
    top: str | None = None,
    parameters: dict[str, int] | None = None,
) -> RootNode:
    # Dynamic instance properties create derived RDL types. Enable map annotations
    # only here so other exporters retain their established software and RTL names.
    return compile_rdl(
        str(rdl),
        str(udp) if udp else None,
        [str(path) for path in incdirs],
        top,
        parameters,
        defines={"OCAH_DOC_MEMORY_MAP": ""},
    )


def _top(root: RootNode) -> AddressableNode:
    children = list(root.children(unroll=False))
    if len(children) != 1:
        raise ValueError(f"expected one elaborated top, found {len(children)}")
    node = children[0]
    if not isinstance(node, (AddrmapNode, MemNode, RegNode, RegfileNode)):
        raise ValueError(f"top {node.get_path()} is not addressable")
    return node


def _walk(node: AddressableNode, prefix: str = "") -> dict[str, AddressableNode]:
    result: dict[str, AddressableNode] = {}
    for child in node.children(unroll=False):
        if not isinstance(child, (AddrmapNode, MemNode, RegNode, RegfileNode)):
            continue
        key = f"{prefix}.{child.inst_name}" if prefix else child.inst_name
        if key in result:
            raise ValueError(f"duplicate elaborated path {key}")
        result[key] = child
        if isinstance(child, (AddrmapNode, MemNode, RegfileNode)):
            result.update(_walk(child, key))
    return result


def _node_extent(node: AddressableNode) -> int:
    size = int(getattr(node, "size", 0) or 0)
    if getattr(node, "is_array", False):
        count = 1
        for dimension in node.array_dimensions or ():
            count *= int(dimension)
        stride = int(getattr(node, "array_stride", 0) or 0)
        if _inherited(node, "ocah_full_stride_extent"):
            return count * stride
        return (count - 1) * stride + size
    return int(getattr(node, "total_size", 0) or size)


def _count(node: AddressableNode) -> int:
    count = 1
    for dimension in getattr(node, "array_dimensions", None) or ():
        count *= int(dimension)
    return count


def _own(node: AddressableNode, name: str) -> Any:
    return node.get_property(name, default=None)


def _note(node: AddressableNode, name: str) -> str:
    value = _own(node, name)
    if value is NoValue:
        raise ValueError(f"{node.get_path()}: {name} has no value")
    return value or ""


def _inherited(node: AddressableNode, name: str) -> Any:
    while not isinstance(node, RootNode):
        value = _own(node, name)
        if value is not None:
            return value
        node = node.parent
    return None


def _hole_response(node: AddressableNode) -> Response:
    return Response.from_rdl(
        _inherited(node, "ocah_hole_resp"), f"{node.get_path()}: ocah_hole_resp"
    )


def _gap_response(node: AddressableNode) -> Response:
    value = _own(node, "ocah_gap_resp")
    if value is None:
        return _hole_response(node)
    return Response.from_rdl(value, f"{node.get_path()}: ocah_gap_resp")


def _opaque_response(node: AddressableNode) -> Response | None:
    value = _inherited(node, "ocah_hole_resp")
    if value is None:
        return None
    response = Response.from_rdl(value, f"{node.get_path()}: ocah_hole_resp")
    return response if response.opaque else None


def _has_gap(intervals: list[tuple[int, int]], size: int) -> bool:
    cursor = 0
    for start, end in sorted(intervals):
        if start > cursor:
            return True
        cursor = max(cursor, end)
    return cursor < size


def _extent_responses(
    node: AddressableNode, memo: dict[str, tuple[tuple[str, Response], ...]]
) -> tuple[tuple[str, Response], ...]:
    """Responses of the unbacked space inside one element of node, labelled by where it lies."""
    key = node.get_path()
    if key in memo:
        return memo[key]
    opaque = _opaque_response(node)
    if opaque is not None:
        memo[key] = (("", opaque),)
        return memo[key]
    if isinstance(node, (MemNode, RegNode)):
        # A memory is backed throughout unless it states how its whole window answers.
        own = _own(node, "ocah_hole_resp")
        memo[key] = (
            ()
            if own is None
            else (("", Response.from_rdl(own, f"{node.get_path()}: ocah_hole_resp")),)
        )
        return memo[key]
    children = [
        child
        for child in node.children(unroll=False)
        if isinstance(child, (AddrmapNode, MemNode, RegNode, RegfileNode))
    ]
    blocks = [child for child in children if not isinstance(child, RegNode)]
    intervals: list[tuple[int, int]] = []
    for child in children:
        offset = int(child.raw_address_offset)
        if isinstance(child, RegNode) and child.is_array and child.array_stride > child.size:
            starts = range(offset, offset + _count(child) * child.array_stride, child.array_stride)
            intervals += [(start, start + child.size) for start in starts]
        else:
            intervals.append((offset, offset + int(child.total_size)))
    parts: list[tuple[str, Response]] = []
    if _has_gap(intervals, int(node.size)):
        parts.append(
            ("between sub-blocks", _gap_response(node)) if blocks else ("", _hole_response(node))
        )
    for block in blocks:
        parts += _extent_responses(block, memo)
        if block.is_array and block.array_stride > block.size:
            tail = _own(block, "ocah_gap_resp")
            parts.append(
                (
                    "between sub-blocks",
                    _gap_response(node)
                    if tail is None
                    else Response.from_rdl(tail, f"{block.get_path()}: ocah_gap_resp"),
                )
            )
    memo[key] = tuple(dict.fromkeys(parts))
    return memo[key]


def _hole_parts(
    node: AddressableNode, memo: dict[str, tuple[tuple[str, Response], ...]]
) -> tuple[tuple[str, Response], ...]:
    parts = _extent_responses(node, memo)
    if (
        _opaque_response(node) is None
        and node.is_array
        and (_count(node) > 1 or _inherited(node, "ocah_full_stride_extent"))
        and node.array_stride > node.size
    ):
        parts = (*parts, ("between instances", _gap_response(node)))
    labels: dict[str, set[Response]] = {}
    for label, response in parts:
        labels.setdefault(label, set()).add(response)
    for label, responses in labels.items():
        if len(responses) > 1:
            texts = ", ".join(sorted(response.text for response in responses))
            where = f" {label}" if label else ""
            raise ValueError(f"{node.get_path()}: holes{where} answer differently: {texts}")
    default = labels.pop("", set())
    return (*(("", response) for response in default),) + tuple(
        (label, response) for label, (response,) in labels.items() if response not in default
    )


def _node_row(source: str, key: str, node: AddressableNode) -> MapRow:
    count = 1
    for dimension in getattr(node, "array_dimensions", None) or ():
        count *= int(dimension)
    stride = int(getattr(node, "array_stride", 0) or 0)
    occupied = _node_extent(node)
    aperture = node.get_property("ocah_aperture_size", default=None)
    aperture = occupied if aperture is None else int(aperture)
    return MapRow(
        key=f"{source}:{key}",
        label=node.get_property("name", default=None) or node.inst_name,
        base=int(node.raw_absolute_address),
        occupied_size=occupied,
        aperture_size=aperture,
        description=node.get_property("desc", default="") or "",
        count=count,
        stride=stride,
    )


def load_config(path: str | Path) -> dict[str, Any]:
    with Path(path).open("rb") as stream:
        data = tomllib.load(stream)
    if data.get("version") != 1:
        raise ValueError(f"{path}: expected version = 1")
    for key, value in data.items():
        if key != "version":
            _reject_numeric_values(value, f"{path}:{key}")
    _reject_unknown(data, {"version", "sources", "views"}, str(path))
    source_names: set[str] = set()
    for index, source in enumerate(data.get("sources", ())):
        location = f"{path}:sources[{index}]"
        _reject_unknown(
            source,
            {"name", "rdl", "top"},
            location,
        )
        name = source.get("name")
        if not isinstance(name, str) or not name or "rdl" not in source:
            raise ValueError(f"{location}: name and rdl are required")
        if name in source_names:
            raise ValueError(f"{path}: duplicate source name {name!r}")
        source_names.add(name)
    view_names: set[str] = set()
    for index, view in enumerate(data.get("views", ())):
        location = f"{path}:views[{index}]"
        _reject_unknown(
            view,
            {
                "name",
                "title",
                "columns",
                "base_mode",
                "base_source",
                "source",
                "include_all",
                "rows",
                "derive_gaps",
                "bounds_source",
                "bounds_selector",
            },
            location,
        )
        name = view.get("name")
        if not isinstance(name, str) or not name:
            raise ValueError(f"{location}: name must be a non-empty string")
        if name in view_names:
            raise ValueError(f"{path}: duplicate view name {name!r}")
        view_names.add(name)
        if view.get("base_mode", "absolute") not in {"absolute", "relative"}:
            raise ValueError(f"{location}: base_mode must be 'absolute' or 'relative'")
        columns = view.get("columns", ("base", "end", "size", "label", "description"))
        unknown_columns = set(columns) - set(_HEADINGS)
        if unknown_columns:
            raise ValueError(f"{location}: unknown column(s): {', '.join(sorted(unknown_columns))}")
        for row_index, row in enumerate(view.get("rows", ())):
            kind = row.get("kind", "node")
            keys = _SELECT_KEYS if kind == "node" else _GROUP_KEYS if kind == "group" else set()
            if not keys:
                raise ValueError(f"{location}.rows[{row_index}]: unknown row kind {kind!r}")
            _reject_unknown(row, keys, f"{location}.rows[{row_index}]")
    return data


def _reject_unknown(spec: dict[str, Any], allowed: set[str], location: str) -> None:
    unknown = set(spec) - allowed
    if unknown:
        raise ValueError(f"{location}: unknown key(s): {', '.join(sorted(unknown))}")


def _reject_numeric_values(value: Any, location: str) -> None:
    if isinstance(value, bool):
        return
    if isinstance(value, (int, float)):
        raise ValueError(f"{location}: numeric hardware data is not allowed")
    if isinstance(value, dict):
        for key, child in value.items():
            _reject_numeric_values(child, f"{location}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _reject_numeric_values(child, f"{location}[{index}]")


def _select(
    spec: dict[str, Any],
    sources: dict[str, dict[str, MapRow]],
) -> MapRow:
    source = spec.get("source", "main")
    selector = spec.get("selector")
    if not selector:
        raise ValueError("node row requires selector")
    try:
        row = sources[source][selector]
    except KeyError as exc:
        raise ValueError(f"selector {source}:{selector} matched no elaborated node") from exc
    return replace(
        row,
        label=spec.get("label", row.label),
    )


def _group(
    spec: dict[str, Any],
    sources: dict[str, dict[str, MapRow]],
) -> MapRow:
    members = [_select({"selector": item}, sources) for item in spec.get("members", ())]
    if not members:
        raise ValueError(f"group {spec.get('label', '<unnamed>')} has no members")
    base = min(row.base for row in members)
    end = max(row.end for row in members)
    return MapRow(
        key=spec["label"],
        label=spec["label"],
        base=base,
        occupied_size=end - base + 1,
        aperture_size=end - base + 1,
        description=spec.get("description", members[0].description if len(members) == 1 else ""),
        kind="group",
    )


def _validate(rows: list[MapRow], view_name: str) -> None:
    keys: set[str] = set()
    for row in rows:
        if row.aperture_size <= 0:
            raise ValueError(f"{view_name}:{row.key}: aperture must be positive")
        if row.aperture_size < row.occupied_size:
            raise ValueError(
                f"{row.key}: aperture 0x{row.aperture_size:X} is smaller than occupied "
                f"extent 0x{row.occupied_size:X}"
            )
        if row.key in keys:
            raise ValueError(f"{view_name}: duplicate row key {row.key}")
        keys.add(row.key)
    for left, right in zip(rows, rows[1:]):
        if right.base <= left.end:
            raise ValueError(
                f"{view_name}: {left.key} ending 0x{left.end:X} overlaps "
                f"{right.key} at 0x{right.base:X}"
            )


def _fill_responses(
    view_name: str,
    rows: list[MapRow],
    requested: set[str],
    nodes: dict[str, AddressableNode],
    top: AddressableNode | None,
    memo: dict[str, tuple[tuple[str, Response], ...]],
) -> list[MapRow]:
    filled: list[MapRow] = []
    for index, row in enumerate(rows):
        if row.kind == "group":
            raise ValueError(f"{view_name}:{row.key}: a group row cannot state responses")
        if row.kind == "reserved":
            if top is None:
                raise ValueError(f"{view_name}: row source top not found")
            if "hole_resp" in requested:
                previous = rows[index - 1] if index else None
                notes = (
                    _note(top, "ocah_gap_note"),
                    _note(nodes[previous.key], "ocah_following_gap_note")
                    if previous is not None and previous.kind == "node"
                    else "",
                )
                row = replace(
                    row,
                    hole_responses=(("", _gap_response(top)),),
                    hole_notes=tuple(note for note in notes if note),
                )
            filled.append(row)
            continue
        node = nodes[row.key]
        if "hole_resp" in requested:
            row = replace(
                row,
                hole_responses=_hole_parts(node, memo),
                hole_notes=tuple(note for note in (_note(node, "ocah_hole_note"),) if note),
            )
        if "past_resp" in requested:
            past = None
            if row.aperture_size > row.occupied_size:
                past = Response.from_rdl(
                    _inherited(node, "ocah_past_extent_resp"),
                    f"{node.get_path()}: ocah_past_extent_resp",
                )
            row = replace(row, past_response=past, past_note=_note(node, "ocah_past_extent_note"))
        filled.append(row)
    return filled


def build_views(
    config: dict[str, Any],
    roots: dict[str, RootNode],
) -> list[MapView]:
    sources: dict[str, dict[str, MapRow]] = {}
    source_tops: dict[str, MapRow] = {}
    source_nodes: dict[str, AddressableNode] = {}
    top_nodes: dict[str, AddressableNode] = {}
    memo: dict[str, tuple[tuple[str, Response], ...]] = {}
    for source, root in roots.items():
        top = _top(root)
        nodes = _walk(top)
        sources[source] = {key: _node_row(source, key, node) for key, node in nodes.items()}
        source_tops[source] = _node_row(source, top.inst_name, top)
        source_nodes.update({f"{source}:{key}": node for key, node in nodes.items()})
        top_nodes[source] = top

    views: list[MapView] = []
    for spec in config.get("views", ()):
        auto_source = spec.get("source", "main")
        rows: list[MapRow] = (
            [row for key, row in sources.get(auto_source, {}).items() if "." not in key]
            if spec.get("include_all", False)
            else []
        )
        for row_spec in spec.get("rows", ()):
            kind = row_spec.get("kind", "node")
            if kind == "node":
                if spec.get("include_all", False) and set(row_spec) <= {
                    "kind",
                    "selector",
                    "source",
                }:
                    raise ValueError(
                        f"{spec['name']}:{row_spec.get('selector')}: redundant included row"
                    )
                row = _select(row_spec, sources)
                previous = next(
                    (index for index, old in enumerate(rows) if old.key == row.key), None
                )
                if previous is None:
                    rows.append(row)
                else:
                    rows[previous] = row
            elif kind == "group":
                rows.append(_group(row_spec, sources))
            else:
                raise ValueError(f"unknown row kind {kind!r}")
        rows.sort(key=lambda row: row.base)
        if spec.get("derive_gaps", False):
            bounds_source = spec.get("bounds_source", auto_source)
            bounds_selector = spec.get("bounds_selector")
            try:
                bounds = (
                    sources[bounds_source][bounds_selector]
                    if bounds_selector
                    else source_tops[bounds_source]
                )
            except KeyError as exc:
                target = f"{bounds_source}:{bounds_selector or '<top>'}"
                raise ValueError(f"{spec['name']}: gap bounds {target} not found") from exc
            bounds_start = bounds.base if bounds_selector else min(row.base for row in rows)
            bounds_end = bounds.end + 1
            bounded_rows = [
                row for row in rows if row.base >= bounds_start and row.end < bounds_end
            ]
            outside_rows = [row for row in rows if row.end < bounds_start or row.base >= bounds_end]
            if len(bounded_rows) + len(outside_rows) != len(rows):
                raise ValueError(f"{spec['name']}: row crosses gap bounds")
            with_gaps: list[MapRow] = []
            cursor = bounds_start
            for row in bounded_rows:
                if row.base > cursor:
                    with_gaps.append(
                        MapRow(
                            key=f"reserved_{cursor:X}",
                            label="Reserved",
                            base=cursor,
                            occupied_size=row.base - cursor,
                            aperture_size=row.base - cursor,
                            description="Reserved",
                            kind="reserved",
                        )
                    )
                with_gaps.append(row)
                cursor = max(cursor, row.end + 1)
            if cursor < bounds_end:
                with_gaps.append(
                    MapRow(
                        key=f"reserved_{cursor:X}",
                        label="Reserved",
                        base=cursor,
                        occupied_size=bounds_end - cursor,
                        aperture_size=bounds_end - cursor,
                        description="Reserved",
                        kind="reserved",
                    )
                )
            rows = sorted([*outside_rows, *with_gaps], key=lambda row: row.base)
        requested = _RESPONSE_COLUMNS & set(spec.get("columns", ()))
        if requested:
            rows = _fill_responses(
                spec["name"], rows, requested, source_nodes, top_nodes.get(auto_source), memo
            )
        _validate(rows, spec["name"])
        relative_base = 0
        if spec.get("base_mode", "absolute") == "relative":
            base_source = spec.get("base_source", auto_source)
            try:
                relative_base = min(
                    row.base for key, row in sources[base_source].items() if "." not in key
                )
            except (KeyError, ValueError) as exc:
                raise ValueError(f"{spec['name']}: base source {base_source!r} not found") from exc
        views.append(
            MapView(
                name=spec["name"],
                title=spec.get("title", spec["name"]),
                columns=tuple(spec.get("columns", ("base", "end", "size", "label", "description"))),
                rows=tuple(rows),
                base_mode=spec.get("base_mode", "absolute"),
                base=relative_base,
            )
        )
    if not views:
        raise ValueError("configuration defines no [[views]]")
    return views


def _check_regblocks(
    node: AddressableNode,
    err_check_blocks: set[str],
    no_rtl_blocks: set[str],
    err_checked: bool,
    errors: list[str],
) -> None:
    for child in node.children(unroll=False):
        if not isinstance(child, AddrmapNode):
            continue
        name = child.orig_type_name
        if name in no_rtl_blocks or _opaque_response(child) is not None:
            continue
        checked = err_checked or name in err_check_blocks
        if any(isinstance(grand, (RegNode, RegfileNode)) for grand in child.children()):
            expected = "SLVERR" if checked else "OKAY"
            for resolve in (_hole_response,) if child.is_array else (_hole_response, _gap_response):
                try:
                    response = resolve(child)
                except ValueError as exc:
                    errors.append(str(exc))
                    break
                stated = (response.rresp.name, response.rdata, response.bresp.name)
                if stated != (expected, 0, expected):
                    errors.append(
                        f"{child.get_path()}: regblock answers {expected}, 0x0 / {expected}"
                        f" but the RDL states {response.text}"
                    )
        _check_regblocks(child, err_check_blocks, no_rtl_blocks, checked, errors)


def check_regblock_responses(
    views: Iterable[MapView],
    roots: dict[str, RootNode],
    err_check_blocks: Iterable[str],
    no_rtl_blocks: Iterable[str],
) -> None:
    """Hold the stated hole response of every generated regblock to its generator options."""
    if not any(_RESPONSE_COLUMNS & set(view.columns) for view in views):
        return
    errors: list[str] = []
    for root in roots.values():
        _check_regblocks(_top(root), set(err_check_blocks), set(no_rtl_blocks), False, errors)
    if errors:
        raise ValueError("\n".join(dict.fromkeys(errors)))


def format_size(size: int) -> str:
    for divisor, suffix in ((1024**3, "GiB"), (1024**2, "MiB"), (1024, "KiB")):
        if size >= divisor and size % divisor == 0:
            return f"{size // divisor} {suffix}"
    return f"{size} B"


def _address(view: MapView, address: int) -> str:
    if view.base_mode == "relative":
        offset = address - view.base
        if offset < 0:
            raise ValueError(f"{view.name}: address 0x{address:X} is below relative base")
        return f"BASE + 0x{offset:X}"
    return f"0x{address:08X}"


def _hole_text(parts: tuple[tuple[str, Response], ...], mark: Callable[[str], str]) -> str:
    if not parts:
        return "-"
    if len(parts) == 1:
        return parts[0][1].adoc(mark)
    return "; ".join(
        f"{label}: {response.adoc(mark)}" if label else response.adoc(mark)
        for label, response in parts
    )


def _notes(view: MapView) -> tuple[Callable[[str], str], list[str]]:
    """Return a marker linking to its note, and the list it numbers each distinct note into."""
    notes: list[str] = []

    def mark(note: str) -> str:
        if not note:
            return ""
        if note not in notes:
            notes.append(note)
        number = notes.index(note) + 1
        return f"^<<{view.name}-note-{number},[{number}]>>^"

    return mark, notes


def _cell(view: MapView, row: MapRow, column: str, mark: Callable[[str], str]) -> str:
    values = {
        "base": lambda: _address(view, row.base),
        "end": lambda: _address(view, row.end),
        "range": lambda: f"{_address(view, row.base)} – {_address(view, row.end)}",
        "size": lambda: format_size(row.aperture_size),
        "occupied_size": lambda: format_size(row.occupied_size),
        "label": lambda: row.label,
        "description": lambda: row.description or "-",
        "instances": lambda: f"{row.count} instance{'s' if row.count != 1 else ''}",
        "stride": lambda: format_size(row.stride) if row.stride else "-",
        "hole_resp": lambda: (
            _hole_text(row.hole_responses, mark) + "".join(mark(note) for note in row.hole_notes)
        ),
        "past_resp": lambda: (
            (row.past_response.adoc(mark) if row.past_response else "-") + mark(row.past_note)
        ),
    }
    if column not in values:
        raise ValueError(f"{view.name}: unknown column {column!r}")
    return str(values[column]()).replace("|", r"\|").replace("\n", " ")


_HEADINGS = {
    "base": "Base Address",
    "end": "End Address",
    "range": "Address Range",
    "size": "Size",
    "occupied_size": "Decoded Extent",
    "label": "Unit",
    "description": "Description",
    "instances": "Instances",
    "stride": "Stride",
    "hole_resp": "Hole in Extent (R / W)",
    "past_resp": "Past Extent (R / W)",
}


def render_adoc(views: Iterable[MapView]) -> str:
    lines = [
        "// SPDX-License-Identifier: Apache-2.0",
        "// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.",
        "",
        "// Generated by tools/regs/rdlmap.py. Do not edit.",
        "",
    ]
    for view in views:
        lines += [
            f"// tag::{view.name}[]",
            f".{view.title}",
            f'[cols="{",".join("<" for _ in view.columns)}",options="header"]',
            "|===",
            "|" + " |".join(_HEADINGS[column] for column in view.columns),
        ]
        mark, notes = _notes(view)
        for row in view.rows:
            lines.append("|" + " |".join(_cell(view, row, column, mark) for column in view.columns))
        lines.append("|===")
        if notes:
            lines += ["", ".Notes"]
            lines += [
                f"[[{view.name}-note-{number}]]^[{number}]^ {note}"
                + (" +" if number < len(notes) else "")
                for number, note in enumerate(notes, 1)
            ]
        lines += [f"// end::{view.name}[]", ""]
    return "\n".join(lines)
