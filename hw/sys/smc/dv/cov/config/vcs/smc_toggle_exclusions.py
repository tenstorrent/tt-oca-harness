# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Plan the SMC toggle exclusions whose fact holds for a whole signal or a fixed bit window.

A class whose fact is about the signal itself -- here a net inside a unit
graded on its ports -- takes the signal whole: every bit, both directions,
covered or not. A class whose fact names some bits of a signal takes those
bits, both directions. Both kinds are read from urg's templates alone, so the rows do not depend on which
points a run covers: they stay the same across seeds and runs of one build and
change only when the templates do. The classes whose fact is about individual
points, the review classes of smc_reviewed_exclusions.toml, stay report-gated
per bit and direction and are written by the other generators.

A row is written at MODULE scope when it holds for every instance of the
module and urg takes a toggle exclusion on the module's section, and at
INSTANCE scope otherwise: a fact about one instance, a module elaborated per
parameter set (urg takes no toggle exclusion on such a section), or a module
some of whose instances the fact does not reach. A signal is owned by the first
class that names it, in the order T1, then the manifest's units.

The ports-only units are planned here from the manifest's `[[unit]]` entries:
a unit root keeps the ports the run's report lists under Port Details and
loses every other net, and every instance beneath a root loses all of its nets.
The report is read for its port lists only, which do not depend on coverage.
"""

from __future__ import annotations

import re
import textwrap
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path

import smc_reviewed_exclusions as reviewed

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[6]
MODULE_OUT = HERE / "smc_toggle_module_exclusions.el"
INSTANCE_OUT = HERE / "smc_toggle_instance_exclusions.el"

Bit = reviewed.Bit


@dataclass(frozen=True)
class ToggleClass:
    """One class: its fact, its scope (design or bench) and what retires it."""

    id: str
    kind: str
    granularity: str
    summary: str
    fact: str
    retired_by: str


# T1 OPENTITAN-PORTS-ONLY: module -> the source the build compiles it from. The
# copyright line of each is checked at generation time and quoted in the file.
T1_UNITS: tuple[tuple[str, str], ...] = (
    ("i2c", "hw/ip/i2c/rtl/i2c.sv"),
    ("i2c_core", "hw/ip/i2c/rtl/i2c_core.sv"),
    ("i2c_controller_fsm", "hw/ip/i2c/rtl/i2c_controller_fsm.sv"),
    ("i2c_target_fsm", "hw/ip/i2c/rtl/i2c_target_fsm.sv"),
    ("i2c_bus_monitor", "hw/ip/i2c/rtl/i2c_bus_monitor.sv"),
    ("uart_16550", "hw/ip/uart/uart_16550/rtl/uart_16550.sv"),
    ("uart_core", "hw/ip/uart/uart_16550/rtl/uart_core.sv"),
    ("uart_rx", "hw/ip/uart/uart_16550/rtl/uart_rx.sv"),
    ("uart_tx", "hw/ip/uart/uart_16550/rtl/uart_tx.sv"),
    ("prim_clock_mux2", "hw/common/ocah_prim_generic/rtl/prim_clock_mux2.sv"),
)

CLASSES: dict[str, ToggleClass] = {
    c.id: c
    for c in (
        ToggleClass(
            "T1-OPENTITAN-PORTS-ONLY",
            "design",
            "whole signal",
            "a unit of OpenTitan origin is graded on its ports; every net it declares inside is excluded",
            "this unit comes from OpenTitan, whose own verification covers its internals, so the "
            "package grades it on its ports and excludes every net it declares inside. Every unit "
            "that is not from OpenTitan keeps all of its nets in the toggle score. The source's "
            "copyright line is quoted in the block.",
            "the unit's source losing its OpenTitan origin, or the package grading OpenTitan "
            "internals",
        ),
    )
}

COPYRIGHT = re.compile(r"^\s*//\s*Copyright.*?(lowRISC|OpenTitan).*$", re.I | re.M)
COMMENTS = re.compile(r"//[^\n]*|/\*.*?\*/", re.S)
PORT_NAME = re.compile(r"([A-Za-z_][A-Za-z_0-9$]*)\s*(?:\[[^\]]*\]\s*)*(?:=[^,]*)?$")


def copyright_line(path: Path) -> str:
    """The lowRISC or OpenTitan copyright line of a source, or stop."""
    head = "\n".join(path.read_text(errors="replace").splitlines()[:12])
    m = COPYRIGHT.search(head)
    if m is None:
        raise SystemExit(f"{path} carries no lowRISC or OpenTitan copyright line")
    return m.group(0).strip().lstrip("/").strip()


def _close(text: str, start: int) -> int:
    depth, j = 0, start
    while j < len(text):
        depth += text[j] == "("
        depth -= text[j] == ")"
        if depth == 0:
            return j
        j += 1
    return j


def module_ports(path: Path, module: str) -> set[str]:
    """The names in a module's ANSI port list."""
    text = COMMENTS.sub("", path.read_text(errors="replace"))
    m = re.search(r"\bmodule\s+(?:automatic\s+)?" + re.escape(module) + r"\b", text)
    if m is None:
        raise SystemExit(f"{path} declares no module {module}")
    hash_pos, start = text.find("#", m.end()), text.find("(", m.end())
    if hash_pos != -1 and hash_pos < start:
        start = text.find("(", _close(text, text.find("(", hash_pos)) + 1)
    end = _close(text, start)
    ports: set[str] = set()
    depth, cur = 0, ""
    for c in text[start + 1 : end] + ",":
        if c in "([{":
            depth += 1
        elif c in ")]}":
            depth -= 1
        if c == "," and depth == 0:
            name = PORT_NAME.search(cur.strip())
            if name:
                ports.add(name.group(1))
            cur = ""
            continue
        cur += c
    return ports


def head_name(signal: str) -> str:
    """The declared name a toggle point belongs to: `a.b[3].c` -> `a`."""
    return signal.split(".")[0].split("[")[0]


@dataclass
class Row:
    """One toggle row: the owning class, the select (empty for the whole signal)."""

    cls: str
    select: str


@dataclass
class TogglePlan:
    """Whole-signal and bit-window rows by scope, and the bits each takes."""

    db: reviewed.Database
    rows: dict[tuple[str, str], dict[str, Row]] = field(default_factory=lambda: defaultdict(dict))

    def owned(self, kind: str, scope: str, sc: reviewed.Scope, signal: str) -> bool:
        if signal in self.rows.get((kind, scope), {}):
            return True
        if kind == "INSTANCE":
            up = self.db.module_scope(sc, "tgl")
            return up is not None and signal in self.rows.get(("MODULE", up), {})
        return False

    def add(self, kind: str, scope: str, signal: str, cls: str, select: str = "") -> None:
        """Write a row at MODULE scope where urg takes it, on each instance otherwise.

        A module row is not written where every instance already owns the signal.
        """
        sc = (self.db.modules if kind == "MODULE" else self.db.instances)[scope]
        if signal not in sc.signals:
            return
        if kind == "MODULE":
            members = self.db.members(scope, "tgl")
            if members and all(self.owned(k, s, i, signal) for k, s, i in members):
                return
        for k, s, inst in self.db.split(kind, scope, "tgl"):
            if not self.owned(k, s, inst, signal):
                self.rows[(k, s)][signal] = Row(cls, select)

    def bits(self, kind: str, scope: str, sc: reviewed.Scope, signal: str) -> set[Bit]:
        """The bits of one signal the plan takes at this scope, its module's included."""
        out: set[Bit] = set()
        scopes = [(kind, scope)]
        if kind == "INSTANCE":
            up = self.db.module_scope(sc, "tgl")
            if up is not None:
                scopes.append(("MODULE", up))
        dims = reviewed.declared(signal, sc.signals.get(signal, ""))
        for key in scopes:
            row = self.rows.get(key, {}).get(signal)
            if row is not None:
                out |= reviewed.bits_of(dims, row.select) or set()
        return out

    def taken(self, kind: str, scope: str, sc: reviewed.Scope, signal: str) -> set[Bit]:
        """Bits a report-gated class must leave alone: the plan's, or every member's."""
        out = self.bits(kind, scope, sc, signal)
        if kind == "MODULE":
            members = self.db.members(scope, "tgl")
            if members:
                common = None
                for _, path, inst in members:
                    b = self.bits("INSTANCE", path, inst, signal)
                    common = b if common is None else common & b
                out |= common or set()
        return out


class Planner:
    """Resolves the toggle classes against urg's templates and the run's port lists."""

    def __init__(
        self, db: reviewed.Database, report: reviewed.Report, manifest: reviewed.Manifest
    ) -> None:
        self.db, self.report, self.manifest = db, report, manifest
        self.plan = TogglePlan(db)
        self.copyright: dict[str, str] = {}
        self.absent: list[str] = []
        self.order = ["T1-OPENTITAN-PORTS-ONLY"]
        self.order += [c for c in manifest.classes if c.startswith("T")]
        self.t1()
        self.units()

    def t1(self) -> None:
        for module, relative in T1_UNITS:
            scopes = [
                s for s in self.db.by_name.get(module, []) if "tgl" in self.db.modules[s].checksum
            ]
            if not scopes:
                self.absent.append(module)
                continue
            source = ROOT / relative
            ports = module_ports(source, module)
            self.copyright[module] = copyright_line(source)
            for scope in scopes:
                for signal in self.db.modules[scope].signals:
                    if head_name(signal) not in ports:
                        self.plan.add("MODULE", scope, signal, "T1-OPENTITAN-PORTS-ONLY")

    def units(self) -> None:
        """Every net inside a ports-only unit; the root's reported ports stay graded."""
        db, report = self.db, self.report
        roots: dict[str, str] = {}
        for entry in self.manifest.units:
            rx = reviewed.glob(entry["instance"])
            for path in sorted(p for p in db.instances if rx.match(p)):
                roots.setdefault(path, entry["class"])
        owner: dict[str, tuple[str, bool]] = {}
        for path in db.instances:
            outer = [r for r in roots if path.startswith(r + ".")]
            if outer:
                owner[path] = (roots[min(outer, key=len)], True)
            elif path in roots:
                owner[path] = (roots[path], False)
        inner_by_module: dict[str, dict[str, list[str]]] = defaultdict(lambda: defaultdict(list))
        for path, (cls, inner) in owner.items():
            sc = db.instances[path]
            if inner and "tgl" in sc.checksum:
                up = db.module_scope(sc, "tgl")
                if up is not None:
                    inner_by_module[up][cls].append(path)
        whole_modules: dict[str, str] = {}
        for up, by_cls in inner_by_module.items():
            members = db.members(up, "tgl")
            if len(by_cls) == 1 and members:
                ((cls, paths),) = by_cls.items()
                if {p for _, p, _ in members} == set(paths):
                    whole_modules[up] = cls
        for up, cls in sorted(whole_modules.items()):
            for signal in db.modules[up].signals:
                self.plan.add("MODULE", up, signal, cls)
        for path, (cls, inner) in sorted(owner.items()):
            sc = db.instances[path]
            if "tgl" not in sc.checksum:
                continue
            kept = set() if inner else report.ports("INSTANCE", path, sc, db)
            for signal in sc.signals:
                if signal not in kept:
                    self.plan.add("INSTANCE", path, signal, cls)

    def describe(self, cls: str) -> tuple[str, str, str]:
        """A class's one-line fact, its full fact and its retiring condition."""
        if cls in CLASSES:
            c = CLASSES[cls]
            return c.summary, c.fact, c.retired_by
        entry = self.manifest.classes[cls]
        sources = sorted(
            {e["source"] for e in self.manifest.units if e["class"] == cls},
            key=lambda s: self.manifest.sources[s],
        )
        review = self.manifest.review
        unit = entry["fact"].split(" is graded on its ports", 1)[0]
        summary = (
            f"{unit} is graded on its ports, as design engineering reviewed; every net inside it "
            "and every instance beneath it is excluded"
        )
        full = (
            f"{entry['fact']} Reviewed with design engineering in {review['repository']} "
            f"{', '.join(sources)} ({review['commit']})."
        )
        return summary, full, "design engineering withdrawing the review of the unit"

    def annotation(self, cls: str) -> str:
        summary, _, retired = self.describe(cls)
        return f'ANNOTATION: "SMC-{cls}: {summary}. Retired by {retired}."'

    def legend(self, classes: list[str]) -> list[str]:
        """Header comment lines stating each class's full fact once."""
        out: list[str] = []
        for cls in classes:
            _, full, retired = self.describe(cls)
            kind = CLASSES[cls].kind if cls in CLASSES else "design review"
            grain = CLASSES[cls].granularity if cls in CLASSES else "whole signal"
            body = f"{cls} ({kind}, {grain}): {full} Retired by {retired}."
            out += ["//", *("// " + line for line in textwrap.wrap(body, 96))]
        return out

    def render(self, kind: str) -> tuple[list[str], Counter]:
        """The `.el` blocks of one scope kind, in template order."""
        db, plan = self.db, self.plan
        rank = {c: i for i, c in enumerate(self.order)}
        counts: Counter = Counter()
        out: list[str] = []
        for (k, scope), signals in sorted(plan.rows.items(), key=lambda t: t[0][1]):
            if k != kind or not signals:
                continue
            sc = (db.modules if k == "MODULE" else db.instances)[scope]
            order = {}
            for item, i in sc.order["tgl"].items():
                m = reviewed.TOGGLE.match(item)
                if m:
                    order.setdefault(m.group(2), i)
            out += ["", f"CHECKSUM: {sc.checksum['tgl']}"]
            if k == "INSTANCE":
                out.append(f'ANNOTATION: "ModuleName: {sc.module}"')
            out.append(f"{k}: {scope}")
            by_cls: dict[str, list[str]] = defaultdict(list)
            for signal in sorted(signals, key=lambda s: (order.get(s, 1 << 30), s)):
                row = signals[signal]
                by_cls[row.cls].append(f'Toggle {signal}{row.select} "{sc.signals[signal]}"')
            for cls in sorted(by_cls, key=lambda c: rank.get(c, len(rank))):
                out.append(self.annotation(cls))
                if cls == "T1-OPENTITAN-PORTS-ONLY" and sc.module in self.copyright:
                    out.append(f'ANNOTATION: "{sc.module}: {self.copyright[sc.module]}"')
                out += by_cls[cls]
                counts[cls] += len(by_cls[cls])
        return out, counts


HEADER = (
    "// SPDX-License-Identifier: Apache-2.0",
    "// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.",
    "//==================================================",
    "// SMC VCS toggle exclusions, {scope} scope.",
    "// Format Version: 2",
    "// ExclMode: default",
    "//",
    "// Generated by gen_smc_toggle_exclusions.py from urg's templates; regenerate",
    "// rather than edit. Every row takes a whole signal, both directions, or the",
    "// bit window its class names, so the file depends on the build and not on",
    "// which points a run covers. {what}",
    "// Each block names its class; the classes below state their facts and",
    "// retiring conditions, and README.md gives every class's granularity.",
    "//==================================================",
)
WHAT = {
    "MODULE": "Each block holds for every instance of its module.",
    "INSTANCE": "Each block holds for one instance.",
}


def text(planner: Planner, kind: str) -> tuple[str, Counter]:
    rows, counts = planner.render(kind)
    head = [h.format(scope=kind.lower(), what=WHAT[kind]) for h in HEADER]
    used = [c for c in planner.order if c in counts]
    head[-1:-1] = planner.legend(used)
    return "\n".join([*head, *rows]) + "\n", counts


def plan(template_dir: Path, modinfo: Path) -> tuple[Planner, reviewed.Planner]:
    """The toggle plan and the report-gated plan that leaves its bits alone."""
    db = reviewed.Database(template_dir)
    report = reviewed.Report(modinfo)
    manifest = reviewed.Manifest()
    toggles = Planner(db, report, manifest)
    return toggles, reviewed.Planner(db, report, manifest, toggles.plan.taken)
