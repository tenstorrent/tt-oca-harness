# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Register model read from a generated Python register header.

``tools/regs/rdlpyhdr.py`` emits one flat module per register space. ``load_model``
reads such a module into address windows, register instances and field records,
joining every instance to its field contract through ``<INST>_REG_TYPE`` so no
caller rebuilds symbol names.

Symbols read, by suffix:

* ``_REG_MAP_BASE_ADDR`` / ``_REG_MAP_SIZE``  an addrmap window (a block)
* ``_REG_FILE_BASE_ADDR`` / ``_REG_FILE_SIZE`` a regfile window
* ``_MEM_BASE_ADDR`` / ``_MEM_SIZE``           a memory window
* ``_REG_ADDR`` / ``_REG_OFFSET`` / ``_REG_TYPE`` a register instance
* ``_REG_WIDTH`` / ``_REG_FIELDS``             a register type
"""

from __future__ import annotations

import importlib.util
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType

_INDEX = re.compile(r"_(\d+)_$")

_WINDOW_KINDS = (
    ("_REG_MAP_BASE_ADDR", "_REG_MAP_SIZE", "addrmap"),
    ("_REG_FILE_BASE_ADDR", "_REG_FILE_SIZE", "regfile"),
    ("_MEM_BASE_ADDR", "_MEM_SIZE", "mem"),
)


@dataclass(frozen=True)
class FieldSpec:
    """One ``_REG_FIELDS`` record: the field contract the RDL declares."""

    name: str
    lsb: int
    msb: int
    sw: str
    hw: str
    onwrite: str
    onread: str
    singlepulse: bool
    volatile: bool
    reset: int | None

    @property
    def width(self) -> int:
        return self.msb - self.lsb + 1

    @property
    def mask(self) -> int:
        return ((1 << self.width) - 1) << self.lsb


@dataclass(frozen=True)
class Window:
    """An addrmap, regfile or memory address range."""

    name: str
    base: int
    size: int
    kind: str

    @property
    def end(self) -> int:
        return self.base + self.size

    def contains(self, addr: int) -> bool:
        return self.base <= addr < self.end


@dataclass(frozen=True)
class RegInst:
    """One register instance: where it is, what type it is, and its fields.

    ``block`` is the innermost addrmap window whose name prefixes the symbol and
    whose range holds the address; ``name`` is the symbol with that prefix
    removed, so a register inside a regfile keeps the regfile's name in front
    (``INTR_BLOCK_RF_ERROR_INTR_T``), and ``offset`` is relative to that regfile
    rather than to the block. An element of a register array ends in ``_<n>_``
    and carries ``index``; an element of an array of blocks carries the index in
    ``block`` instead.
    """

    block: str
    name: str
    symbol: str
    type_name: str
    addr: int
    offset: int
    width: int
    index: int | None
    fields: tuple[FieldSpec, ...]

    @property
    def base_name(self) -> str:
        """``name`` without the array index: ``SCRATCH_0_`` -> ``SCRATCH``."""
        return _INDEX.sub("", self.name) if self.index is not None else self.name

    @property
    def words(self) -> int:
        """32-bit words the register spans; a narrower register is one word."""
        return max(1, self.width // 32)

    @property
    def reset(self) -> int:
        """Field resets assembled into a register value.

        A field without a constant reset contributes 0; ``reg_masks(...).unreset``
        names those bits, and a reset compare masks them out.
        """
        value = 0
        for field in self.fields:
            value |= ((field.reset or 0) << field.lsb) & field.mask
        return value

    def field(self, name: str) -> FieldSpec:
        for field in self.fields:
            if field.name == name:
                return field
        known = sorted(field.name for field in self.fields)
        raise KeyError(f"{self.symbol} has no field {name!r}; known: {known}")


class RegModel:
    """Every window and register instance of one generated header."""

    def __init__(
        self,
        name: str,
        windows: tuple[Window, ...],
        registers: tuple[RegInst, ...],
        types: dict[str, tuple[int, tuple[FieldSpec, ...]]],
    ) -> None:
        self.name = name
        self.windows = tuple(sorted(windows, key=lambda w: (w.base, -w.size, w.name)))
        self.blocks = tuple(w for w in self.windows if w.kind == "addrmap")
        self.regfiles = tuple(w for w in self.windows if w.kind == "regfile")
        self.mems = tuple(w for w in self.windows if w.kind == "mem")
        self.registers = tuple(sorted(registers, key=lambda r: (r.addr, r.symbol)))
        self.types = dict(types)
        self._window = {w.name: w for w in self.windows}
        self._symbol = {r.symbol: r for r in self.registers}
        self._addr: dict[int, list[RegInst]] = {}
        for reg in self.registers:
            self._addr.setdefault(reg.addr, []).append(reg)

    @property
    def top(self) -> Window:
        """The addrmap window that holds every register and every other window."""
        holders = [
            w
            for w in self.blocks
            if all(w.contains(r.addr) for r in self.registers)
            and all(w.base <= o.base and o.end <= w.end for o in self.windows)
        ]
        if not holders:
            raise LookupError(f"{self.name}: no addrmap window holds the whole register space")
        return min(holders, key=lambda w: len(w.name))

    def window(self, name: str) -> Window:
        try:
            return self._window[name]
        except KeyError as exc:
            raise KeyError(f"{self.name} declares no window {name!r}") from exc

    def block(self, name: str) -> Window:
        window = self.window(name)
        if window.kind != "addrmap":
            raise KeyError(f"{self.name}: {name!r} is a {window.kind}, not an addrmap")
        return window

    def by_symbol(self, symbol: str) -> RegInst:
        """The instance behind ``<symbol>_REG_ADDR``."""
        try:
            return self._symbol[symbol]
        except KeyError as exc:
            raise KeyError(f"{self.name} declares no register {symbol!r}") from exc

    def at(self, addr: int) -> tuple[RegInst, ...]:
        """Every instance whose base word is at ``addr``; a write and a read port can share one.

        The upper words of a register wider than 32 bits are not looked up here;
        ``word_view`` gives their addresses.
        """
        return tuple(self._addr.get(addr, ()))

    def by_addr(self, addr: int) -> RegInst:
        """The one instance whose base word is at ``addr``; see ``at``."""
        found = self.at(addr)
        if not found:
            raise KeyError(f"{self.name} declares no register at {addr:#010x}")
        if len(found) > 1:
            names = [r.symbol for r in found]
            raise LookupError(f"{self.name}: {len(found)} registers at {addr:#010x}: {names}")
        return found[0]

    def under(self, prefix: str) -> tuple[RegInst, ...]:
        """Every instance whose symbol is ``prefix`` or starts with ``prefix + "_"``."""
        return tuple(
            r for r in self.registers if r.symbol == prefix or r.symbol.startswith(prefix + "_")
        )

    def array_count(self, prefix: str) -> int:
        """How many ``<prefix>_<n>_`` windows or register instances the header declares.

        The indices must be contiguous from 0; a gap means the header and the RDL
        disagree, and a sweep built on the count would skip the hole.
        """
        indexed = re.compile(rf"^{re.escape(prefix)}_(\d+)_")
        found: set[int] = set()
        for name in [w.name for w in self.windows] + [r.symbol for r in self.registers]:
            match = indexed.match(name)
            if match:
                found.add(int(match.group(1)))
        if not found:
            raise KeyError(f"{self.name} declares no {prefix}_<n>_ window or register")
        if found != set(range(len(found))):
            missing = sorted(set(range(max(found) + 1)) - found)
            raise KeyError(f"{self.name}: {prefix} indices are not contiguous from 0: {missing}")
        return len(found)


def _import(path: Path) -> ModuleType:
    path = path.resolve()
    loaded = sys.modules.get(path.stem)
    if loaded is not None and Path(getattr(loaded, "__file__", "") or "").resolve() == path:
        return loaded
    spec = importlib.util.spec_from_file_location(path.stem, path)
    if spec is None or spec.loader is None:
        raise FileNotFoundError(path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _block_of(symbol: str, addr: int, blocks: list[Window], name: str) -> Window:
    named = [w for w in blocks if symbol.startswith(w.name + "_") and w.contains(addr)]
    if named:
        return max(named, key=lambda w: len(w.name))
    holding = [w for w in blocks if w.contains(addr)]
    if holding:
        return min(holding, key=lambda w: (w.size, len(w.name)))
    raise ValueError(f"{name}: no addrmap window holds {symbol} at {addr:#010x}")


def load_model(source: ModuleType | str | Path) -> RegModel:
    """Build a ``RegModel`` from a generated header module or its file path."""
    module = source if isinstance(source, ModuleType) else _import(Path(source))
    name = module.__name__
    ns = vars(module)

    windows: list[Window] = []
    for base_suffix, size_suffix, kind in _WINDOW_KINDS:
        for symbol, value in ns.items():
            if not symbol.endswith(base_suffix):
                continue
            stem = symbol[: -len(base_suffix)]
            size = ns.get(stem + size_suffix)
            if size is None:
                raise ValueError(f"{name}: {symbol} has no {stem}{size_suffix}")
            windows.append(Window(stem, int(value), int(size), kind))

    types: dict[str, tuple[int, tuple[FieldSpec, ...]]] = {}
    for symbol, records in ns.items():
        if not symbol.endswith("_REG_FIELDS"):
            continue
        stem = symbol[: -len("_REG_FIELDS")]
        width = ns.get(stem + "_REG_WIDTH")
        if width is None:
            raise ValueError(f"{name}: {symbol} has no {stem}_REG_WIDTH")
        fields = tuple(FieldSpec(*record) for record in records)
        types[stem] = (int(width), tuple(sorted(fields, key=lambda f: f.lsb)))

    blocks = [w for w in windows if w.kind == "addrmap"]
    registers: list[RegInst] = []
    for symbol, value in ns.items():
        if not symbol.endswith("_REG_ADDR"):
            continue
        stem = symbol[: -len("_REG_ADDR")]
        type_name = ns.get(stem + "_REG_TYPE")
        if type_name is None:
            raise ValueError(
                f"{name}: {symbol} has no {stem}_REG_TYPE; regenerate the Python register headers"
            )
        offset = ns.get(stem + "_REG_OFFSET")
        if offset is None:
            raise ValueError(f"{name}: {symbol} has no {stem}_REG_OFFSET")
        if type_name not in types:
            raise ValueError(f"{name}: {stem} names type {type_name!r}, which has no _REG_FIELDS")
        width, fields = types[type_name]
        addr = int(value)
        block = _block_of(stem, addr, blocks, name)
        inst = stem[len(block.name) + 1 :] if stem.startswith(block.name + "_") else stem
        match = _INDEX.search(inst)
        registers.append(
            RegInst(
                block=block.name,
                name=inst,
                symbol=stem,
                type_name=type_name,
                addr=addr,
                offset=int(offset),
                width=width,
                index=int(match.group(1)) if match else None,
                fields=fields,
            )
        )

    return RegModel(name, tuple(windows), tuple(registers), types)
