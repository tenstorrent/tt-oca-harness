# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Read-only hierarchy walk for the test inputs that ``test_en_i`` drives.

``hw/sys/sep/doc/port_table.adoc`` (``test_en_i``): "Drives clock-gater test
ports and AXI cell test inputs." The walk collects every pin of the two classes
below the walk root and labels each pin with a group. The walk selects no
graded pin: a leaf that grades pins takes its graded set from a committed
inventory and looks each inventory path up in the walk.

Pin classes (definition name of the cell instance, test port):

* ``clock_gater``: a definition name that contains ``clock_gat`` or
  ``clk_gat``; port ``test_en_i``.
* ``axi_cell``: a definition name that starts with ``axi_`` or is ``axi``;
  port ``test_i``.

Groups (for the log only). The group of a pin comes from the module that
instantiates its cell: the nearest scope above the cell that has a definition
name (a generate block has none). The simulator gives no source file of a
scope, so the walk reads the module declarations of the source tree:

* ``ocah``: the name is declared by a ``module`` statement in a source file
  under ``hw/`` of this repository that has no ``vendor``, ``dv`` or ``build``
  path component.
* ``sep_cpu``: every pin inside an instance of ``sep_cpu``.
* ``<org>/<library>``: the name is declared only under a ``vendor`` directory
  (for example ``pulp-platform/axi``).
* ``ambiguous``: the name is declared both in an ``ocah`` file and under a
  ``vendor`` directory.
* ``unresolved``: the name is declared nowhere in the scanned tree.

Unwalkable scopes. A scope whose children the simulator cannot iterate is
recorded with its path and the group of the module that the scope belongs to.
The walk cannot see a pin below such a scope.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

PIN_BOUND = 16  # clk_i cycles for a pin to equal test_en_i after an edge
CPU_MACRO = "sep_cpu"

# (class, definition-name pattern, test port)
PIN_CLASSES: tuple[tuple[str, re.Pattern[str], str], ...] = (
    ("clock_gater", re.compile(r"clock_gat|clk_gat", re.I), "test_en_i"),
    ("axi_cell", re.compile(r"^axi_|^axi$", re.I), "test_i"),
)
CLASS_NAMES = tuple(c for c, _p, _n in PIN_CLASSES)

OWNER_OCAH = "ocah"
OWNER_CPU = CPU_MACRO
OWNER_AMBIGUOUS = "ambiguous"
OWNER_UNRESOLVED = "unresolved"

_REPO_ROOT = Path(__file__).resolve().parents[6]
_MODULE_DECL = re.compile(
    r"^\s*(?:extern\s+)?(?:macro)?module\s+(?:automatic\s+|static\s+)?([A-Za-z_]\w*)", re.M
)
_SKIP_PARTS = ("dv", "build")


@dataclass(frozen=True)
class ModuleIndex:
    """Module names declared in OCAH-owned files and under ``vendor`` directories."""

    owned: frozenset[str]
    vendor: dict[str, frozenset[str]]
    files: int

    def owner(self, defn: str) -> str:
        if defn in self.owned:
            return OWNER_AMBIGUOUS if defn in self.vendor else OWNER_OCAH
        libs = self.vendor.get(defn)
        if libs:
            return ",".join(sorted(libs))
        return OWNER_UNRESOLVED


@lru_cache(maxsize=1)
def module_index(root: str = str(_REPO_ROOT)) -> ModuleIndex:
    """Scan ``hw/`` and ``vendor/`` of the repository for module declarations."""
    base = Path(root)
    owned: set[str] = set()
    vendor: dict[str, set[str]] = {}
    files = 0
    for top in (base / "hw", base / "vendor"):
        if not top.is_dir():
            continue
        for path in top.rglob("*"):
            if path.suffix not in (".sv", ".v") or not path.is_file():
                continue
            parts = path.relative_to(base).parts
            in_vendor = "vendor" in parts
            if not in_vendor and any(p in _SKIP_PARTS for p in parts):
                continue
            try:
                names = _MODULE_DECL.findall(path.read_text(errors="replace"))
            except OSError:
                continue
            files += 1
            if in_vendor:
                i = parts.index("vendor")
                lib = "/".join(parts[i + 1 : i + 3]) or "vendor"
                for n in names:
                    vendor.setdefault(n, set()).add(lib)
            else:
                owned.update(names)
    return ModuleIndex(frozenset(owned), {k: frozenset(v) for k, v in vendor.items()}, files)


@dataclass(frozen=True)
class TestEnPin:
    """One walked test pin."""

    path: str  # hierarchy path of the pin
    cls: str  # pin class
    cell: str  # definition name of the cell
    parent: str  # definition name of the instantiating module
    owner: str  # group: OWNER_OCAH, OWNER_CPU, a vendor library, ambiguous or unresolved
    handle: Any = field(compare=False, repr=False)

    def label(self) -> str:
        return f"{self.path} class={self.cls} cell={self.cell} parent={self.parent}"


@dataclass(frozen=True)
class UnwalkableScope:
    """One scope whose children the simulator cannot iterate."""

    path: str
    module: str  # definition name of the scope, or of the instantiating module
    owner: str  # group: OWNER_OCAH, OWNER_CPU, a vendor library, ambiguous or unresolved

    def label(self) -> str:
        return f"{self.path} module={self.module} owner={self.owner}"


@dataclass
class TestEnWalk:
    """Result of one walk."""

    root: str
    scopes: int
    pins: list[TestEnPin]
    index: ModuleIndex
    unwalkable: list[UnwalkableScope] = field(default_factory=list)

    def by_path(self) -> dict[str, TestEnPin]:
        return {p.path: p for p in self.pins}

    @staticmethod
    def group_counts(pins: list[TestEnPin]) -> dict[str, int]:
        """Pin count of each group in ``pins``."""
        return dict(sorted(Counter(p.owner for p in pins).items()))


def _def_name(h: Any) -> str:
    try:
        return str(h._def_name or "")
    except Exception:  # noqa: BLE001 - a scope without a definition name
        return ""


def walk_test_en_pins(root: Any, root_path: str) -> TestEnWalk:
    """Walk ``root`` (read only) and return every test pin of the two classes."""
    from cocotb.handle import HierarchyArrayObject, HierarchyObject

    index = module_index()
    pins: list[TestEnPin] = []
    unwalkable: list[UnwalkableScope] = []
    scopes = 0

    def items(scope: Any, path: str, module: str, in_cpu: bool) -> list[Any]:
        """Children of ``scope``; an unwalkable scope is recorded and yields none."""
        try:
            return list(scope)
        except Exception:  # noqa: BLE001 - a scope the simulator cannot iterate
            owner = OWNER_CPU if in_cpu else index.owner(module)
            unwalkable.append(UnwalkableScope(path, module, owner))
            return []

    def visit(h: Any, path: str, parent: str, in_cpu: bool) -> None:
        nonlocal scopes
        scopes += 1
        defn = _def_name(h)
        for cls, pat, port in PIN_CLASSES:
            if defn and pat.search(defn) and hasattr(h, port):
                pin = getattr(h, port, None)
                if pin is not None:
                    owner = OWNER_CPU if in_cpu else index.owner(parent)
                    pins.append(TestEnPin(f"{path}.{port}", cls, defn, parent, owner, pin))
        below = defn or parent
        cpu_below = in_cpu or defn == CPU_MACRO
        for child in items(h, path, below, cpu_below):
            name = getattr(child, "_name", "?")
            if isinstance(child, HierarchyArrayObject):
                for sub in items(child, f"{path}.{name}", below, cpu_below):
                    visit(sub, f"{path}.{getattr(sub, '_name', name)}", below, cpu_below)
            elif isinstance(child, HierarchyObject):
                visit(child, f"{path}.{name}", below, cpu_below)

    visit(root, root_path, _def_name(root), _def_name(root) == CPU_MACRO)
    return TestEnWalk(root_path, scopes, pins, index, unwalkable)


def pin_value(pin: TestEnPin) -> int | None:
    """Bit 0 of the pin, or None when the value holds X or Z."""
    v = pin.handle.value
    if not getattr(v, "is_resolvable", True):
        return None
    return int(v) & 1


def pins_not_equal(pins: list[TestEnPin], value: int) -> list[TestEnPin]:
    """The pins whose value is not ``value`` (an X or Z value counts as not equal)."""
    return [p for p in pins if pin_value(p) != value]
