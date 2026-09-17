# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

"""Build validated, presentation-neutral memory-map views from SystemRDL."""

from __future__ import annotations

import json
import tomllib
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Iterable

from systemrdl import RDLCompiler
from systemrdl.node import AddrmapNode, MemNode, RegfileNode, RegNode, RootNode

AddressableNode = AddrmapNode | MemNode | RegNode | RegfileNode

_SELECT_KEYS = {
    "kind",
    "source",
    "selector",
    "label",
    "description",
    "aperture_size",
    "expected_address",
    "expected_occupied_size",
    "expected_count",
    "expected_stride",
    "expected_kind",
}
_REGION_KEYS = {
    "kind",
    "key",
    "label",
    "description",
    "source",
    "base",
    "size",
    "occupied_size",
    "count",
    "stride",
    "alias_of",
}
_GROUP_KEYS = {"kind", "key", "label", "description", "source", "members", "base", "size"}


@dataclass(frozen=True)
class MapRow:
    key: str
    label: str
    base: int
    occupied_size: int
    aperture_size: int
    description: str
    kind: str
    count: int = 1
    stride: int = 0
    source: str = "main"
    alias_of: str | None = None

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
    base_label: str = "BASE"


def compile_root(
    rdl: str | Path,
    udp: str | Path | None = None,
    incdirs: Iterable[str | Path] = (),
    top: str | None = None,
    parameters: dict[str, int] | None = None,
) -> RootNode:
    compiler = RDLCompiler()
    if udp:
        compiler.compile_file(str(udp))
    compiler.compile_file(str(rdl), incl_search_paths=[str(path) for path in incdirs])
    return compiler.elaborate(top, parameters=parameters)


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
        return (count - 1) * stride + size
    return int(getattr(node, "total_size", 0) or size)


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
        kind=node.__class__.__name__.removesuffix("Node").lower(),
        count=count,
        stride=stride,
        source=source,
    )


def load_config(path: str | Path) -> dict[str, Any]:
    with Path(path).open("rb") as stream:
        data = tomllib.load(stream)
    if data.get("version") != 1:
        raise ValueError(f"{path}: expected version = 1")
    _reject_unknown(data, {"version", "sources", "nodes", "views"}, str(path))
    source_names: set[str] = set()
    for index, source in enumerate(data.get("sources", ())):
        location = f"{path}:sources[{index}]"
        _reject_unknown(
            source,
            {"name", "rdl", "top", "incdirs", "parameters"},
            location,
        )
        name = source.get("name")
        if not isinstance(name, str) or not name or "rdl" not in source:
            raise ValueError(f"{location}: name and rdl are required")
        if name in source_names:
            raise ValueError(f"{path}: duplicate source name {name!r}")
        source_names.add(name)
    for index, node in enumerate(data.get("nodes", ())):
        _reject_unknown(node, _SELECT_KEYS - {"kind"}, f"{path}:nodes[{index}]")
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
                "base",
                "base_label",
                "source",
                "exclude",
                "include_all",
                "rows",
                "derive_gaps",
                "bounds_start",
                "bounds_end",
                "reserved_label",
                "reserved_description",
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
        if view.get("derive_gaps", False) and not {"bounds_start", "bounds_end"} <= set(view):
            raise ValueError(f"{location}: derive_gaps requires bounds_start and bounds_end")
        for row_index, row in enumerate(view.get("rows", ())):
            kind = row.get("kind", "node")
            keys = (
                _SELECT_KEYS if kind == "node" else _GROUP_KEYS if kind == "group" else _REGION_KEYS
            )
            _reject_unknown(row, keys, f"{location}.rows[{row_index}]")
    return data


def _reject_unknown(spec: dict[str, Any], allowed: set[str], location: str) -> None:
    unknown = set(spec) - allowed
    if unknown:
        raise ValueError(f"{location}: unknown key(s): {', '.join(sorted(unknown))}")


def _as_int(value: Any, field: str) -> int:
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        return int(value, 0)
    raise ValueError(f"{field} must be an integer or base-prefixed string")


def _assert_expected(spec: dict[str, Any], row: MapRow) -> None:
    checks = {
        "expected_address": row.base,
        "expected_occupied_size": row.occupied_size,
        "expected_count": row.count,
        "expected_stride": row.stride,
    }
    for field, actual in checks.items():
        if field in spec and _as_int(spec[field], field) != actual:
            raise ValueError(
                f"{row.key}: {field} expected 0x{_as_int(spec[field], field):X}, "
                f"elaborated 0x{actual:X}"
            )
    if "expected_kind" in spec and spec["expected_kind"] != row.kind:
        raise ValueError(
            f"{row.key}: expected_kind {spec['expected_kind']!r}, elaborated {row.kind!r}"
        )


def _select(
    spec: dict[str, Any],
    sources: dict[str, dict[str, MapRow]],
    used: set[str],
) -> MapRow:
    source = spec.get("source", "main")
    selector = spec.get("selector")
    if not selector:
        raise ValueError("node row requires selector")
    try:
        row = sources[source][selector]
    except KeyError as exc:
        raise ValueError(f"selector {source}:{selector} matched no elaborated node") from exc
    _assert_expected(spec, row)
    used.add(row.key)
    aperture = (
        _as_int(spec["aperture_size"], "aperture_size")
        if "aperture_size" in spec
        else row.aperture_size
    )
    if "aperture_size" in spec and aperture == row.aperture_size:
        raise ValueError(f"{row.key}: redundant aperture_size override")
    if aperture < row.occupied_size:
        raise ValueError(
            f"{row.key}: aperture 0x{aperture:X} is smaller than occupied "
            f"extent 0x{row.occupied_size:X}"
        )
    return replace(
        row,
        label=spec.get("label", row.label),
        description=spec.get("description", row.description),
        aperture_size=aperture,
    )


def _region(spec: dict[str, Any]) -> MapRow:
    base = _as_int(spec["base"], "base")
    size = _as_int(spec["size"], "size")
    return MapRow(
        key=spec.get("key", spec["label"]),
        label=spec["label"],
        base=base,
        occupied_size=_as_int(spec.get("occupied_size", size), "occupied_size"),
        aperture_size=size,
        description=spec.get("description", ""),
        kind=spec.get("kind", "region"),
        count=int(spec.get("count", 1)),
        stride=_as_int(spec.get("stride", 0), "stride"),
        source=spec.get("source", "synthetic"),
        alias_of=spec.get("alias_of"),
    )


def _group(
    spec: dict[str, Any],
    sources: dict[str, dict[str, MapRow]],
    used: set[str],
) -> MapRow:
    members = [
        _select({"selector": item, "source": spec.get("source", "main")}, sources, used)
        for item in spec.get("members", ())
    ]
    if not members:
        raise ValueError(f"group {spec.get('label', '<unnamed>')} has no members")
    base = min(row.base for row in members)
    end = max(row.end for row in members)
    if "base" in spec and _as_int(spec["base"], "base") != base:
        raise ValueError(f"group {spec['label']}: asserted base does not match members")
    size = _as_int(spec.get("size", end - base + 1), "size")
    if base + size - 1 < end:
        raise ValueError(f"group {spec['label']}: size does not contain members")
    return MapRow(
        key=spec.get("key", spec["label"]),
        label=spec["label"],
        base=base,
        occupied_size=end - base + 1,
        aperture_size=size,
        description=spec.get("description", ""),
        kind="group",
    )


def _validate(rows: list[MapRow], view_name: str) -> None:
    keys: set[str] = set()
    for row in rows:
        if row.aperture_size <= 0:
            raise ValueError(f"{view_name}:{row.key}: aperture must be positive")
        if row.key in keys:
            raise ValueError(f"{view_name}: duplicate row key {row.key}")
        keys.add(row.key)
    physical = sorted((row for row in rows if row.alias_of is None), key=lambda row: row.base)
    for left, right in zip(physical, physical[1:]):
        if right.base <= left.end:
            raise ValueError(
                f"{view_name}: {left.key} ending 0x{left.end:X} overlaps "
                f"{right.key} at 0x{right.base:X}"
            )
    by_key = {row.key: row for row in rows}
    for row in rows:
        if row.alias_of:
            if row.alias_of not in by_key:
                raise ValueError(f"{view_name}:{row.key}: unknown alias target {row.alias_of}")
            if row.aperture_size != by_key[row.alias_of].aperture_size:
                raise ValueError(f"{view_name}:{row.key}: alias size differs from target")


def build_views(
    config: dict[str, Any],
    roots: dict[str, RootNode],
) -> list[MapView]:
    sources: dict[str, dict[str, MapRow]] = {}
    for source, root in roots.items():
        nodes = _walk(_top(root))
        sources[source] = {key: _node_row(source, key, node) for key, node in nodes.items()}

    annotated: set[str] = set()
    for spec in config.get("nodes", ()):
        row = _select(spec, sources, annotated)
        _, selector = row.key.split(":", 1)
        sources[row.source][selector] = row

    views: list[MapView] = []
    for spec in config.get("views", ()):
        used: set[str] = set()
        auto_source = spec.get("source", "main")
        excluded = set(spec.get("exclude", ()))
        unknown_excluded = excluded - set(sources.get(auto_source, {}))
        if unknown_excluded:
            raise ValueError(
                f"{spec['name']}: excluded selectors matched no elaborated node: "
                f"{', '.join(sorted(unknown_excluded))}"
            )
        rows: list[MapRow] = (
            [
                row
                for key, row in sources.get(auto_source, {}).items()
                if "." not in key and key not in excluded
            ]
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
                row = _select(row_spec, sources, used)
                previous = next(
                    (index for index, old in enumerate(rows) if old.key == row.key), None
                )
                if previous is None:
                    rows.append(row)
                else:
                    rows[previous] = row
            elif kind == "group":
                rows.append(_group(row_spec, sources, used))
            elif kind in {"region", "reserved", "alias"}:
                rows.append(_region(row_spec))
            else:
                raise ValueError(f"unknown row kind {kind!r}")
        rows.sort(key=lambda row: row.base)
        if spec.get("derive_gaps", False):
            bounds_start = _as_int(spec["bounds_start"], "bounds_start")
            bounds_end = _as_int(spec["bounds_end"], "bounds_end")
            with_gaps: list[MapRow] = []
            cursor = bounds_start
            for row in rows:
                if row.base > cursor:
                    with_gaps.append(
                        MapRow(
                            key=f"reserved_{cursor:X}",
                            label=spec.get("reserved_label", "Reserved"),
                            base=cursor,
                            occupied_size=row.base - cursor,
                            aperture_size=row.base - cursor,
                            description=spec.get("reserved_description", "Reserved"),
                            kind="reserved",
                        )
                    )
                with_gaps.append(row)
                cursor = max(cursor, row.end + 1)
            if cursor < bounds_end:
                with_gaps.append(
                    MapRow(
                        key=f"reserved_{cursor:X}",
                        label=spec.get("reserved_label", "Reserved"),
                        base=cursor,
                        occupied_size=bounds_end - cursor,
                        aperture_size=bounds_end - cursor,
                        description=spec.get("reserved_description", "Reserved"),
                        kind="reserved",
                    )
                )
            rows = with_gaps
        _validate(rows, spec["name"])
        views.append(
            MapView(
                name=spec["name"],
                title=spec.get("title", spec["name"]),
                columns=tuple(spec.get("columns", ("base", "end", "size", "label", "description"))),
                rows=tuple(rows),
                base_mode=spec.get("base_mode", "absolute"),
                base=_as_int(spec.get("base", 0), "base"),
                base_label=spec.get("base_label", "BASE"),
            )
        )
    if not views:
        raise ValueError("configuration defines no [[views]]")
    return views


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
        return f"{view.base_label} + 0x{offset:X}"
    return f"0x{address:08X}"


def _cell(view: MapView, row: MapRow, column: str) -> str:
    values = {
        "base": _address(view, row.base),
        "end": _address(view, row.end),
        "range": f"{_address(view, row.base)} – {_address(view, row.end)}",
        "size": format_size(row.aperture_size),
        "occupied_size": format_size(row.occupied_size),
        "label": row.label,
        "description": row.description or "-",
        "kind": row.kind,
        "instances": f"{row.count} instance{'s' if row.count != 1 else ''}",
        "stride": format_size(row.stride) if row.stride else "-",
    }
    if column not in values:
        raise ValueError(f"{view.name}: unknown column {column!r}")
    return str(values[column]).replace("|", r"\|").replace("\n", " ")


_HEADINGS = {
    "base": "Base Address",
    "end": "End Address",
    "range": "Address Range",
    "size": "Size",
    "occupied_size": "Decoded Extent",
    "label": "Unit",
    "description": "Description",
    "kind": "Kind",
    "instances": "Instances",
    "stride": "Stride",
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
        for row in view.rows:
            lines.append("|" + " |".join(_cell(view, row, column) for column in view.columns))
        lines += ["|===", f"// end::{view.name}[]", ""]
    return "\n".join(lines)


def render_json(views: Iterable[MapView]) -> str:
    payload = {
        "schema": "ocah-memory-map-v1",
        "views": [
            {
                "name": view.name,
                "title": view.title,
                "base_mode": view.base_mode,
                "base": view.base,
                "rows": [
                    {
                        "key": row.key,
                        "label": row.label,
                        "base": row.base,
                        "end": row.end,
                        "occupied_size": row.occupied_size,
                        "aperture_size": row.aperture_size,
                        "description": row.description,
                        "kind": row.kind,
                        "count": row.count,
                        "stride": row.stride,
                        "source": row.source,
                        "alias_of": row.alias_of,
                    }
                    for row in view.rows
                ],
            }
            for view in views
        ],
    }
    return json.dumps(payload, indent=2, sort_keys=True) + "\n"
