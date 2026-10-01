# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Plan the exclusions smc_reviewed_exclusions.toml records, for the generators that write them.

The manifest records exclusions design engineering reviewed for the SMC bench in
an earlier repository, by category, against this tree's names: an object entry
names a module or an instance (an instance path may use `[*]` for any index)
and the toggle signals (globs: `[*]` for any index, `p.*` for every field
under `p`, `*` for every signal), bit or part selects, line blocks by statement
text (with its position among blocks of the same text where the text repeats),
FSM states or transitions and condition rows it covers; a unit entry
names an instance whose own ports stay graded while its internal signals and
every instance beneath it are excluded. Each entry carries the class it belongs
to and the reviewed file it comes from; the class carries the fact, the
retiring condition and the reviewer.

Every point of an object entry, and every line, FSM and condition point of a
unit, is report-gated: it is written only where urg's templates of the merged
database hold it and the run's raw report (written without exclusion files)
marks it uncovered, so nothing a leaf covers is waived, and the output belongs
to one graded run. A unit's toggle points are not planned here but in
smc_toggle_exclusions.py, gated the same way, and an object entry leaves alone
the bits that plan names. A toggle is
decided per bit and direction, a line block by its source line, an FSM state
or transition by name and a condition row by source line and vector. A module entry is written at module scope where
the module's report section, the union of its instances, marks the point
uncovered, and on each instance that still leaves it uncovered otherwise; urg
takes no toggle exclusion on a parameterised MODULE section, so a toggle there
is written on each instance of the section. Inside a unit, a PeakRDL register
block's line and condition points go to the unit register-block class and FSM
points to the unit FSM class the manifest names, so each lands in the file of
its category. A point is written once, to the first entry that names it.
"""

from __future__ import annotations

import itertools
import re
import tomllib
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

HERE = Path(__file__).resolve().parent
MANIFEST = HERE / "smc_reviewed_exclusions.toml"

METRICS = ("tgl", "line", "fsm", "cond")
REPORT_METRIC = {"tgl": "Toggle", "line": "Line", "fsm": "FSM", "cond": "Cond"}
KEYWORDS = ("Toggle", "Block", "Fsm", "State", "Transition", "Condition")
DIRECTIONS = ("1to0", "0to1")

TOGGLE = re.compile(r'^Toggle\s+(?:(0to1|1to0)\s+)?(\S+)(?:\s+((?:\[[^\]]*\])+))?\s+"([^"]*)"\s*$')
BLOCK = re.compile(r'^Block\s+(\d+)\s+"(\d+)"\s+"(.*)"\s*$')
FSM = re.compile(r'^Fsm\s+(\S+)\s+"(\d+)"\s*$')
STATE = re.compile(r'^(State|Transition)\s+(.*\S)\s+"([^"]*)"\s*$')
COND = re.compile(r'^Condition\s+(\d+)\s+"(\d+)"\s+"(.*)"(?:\s+\((\d+)\s+"([^"]*)"\))?\s*$')
SCOPE = re.compile(r"^(INSTANCE|MODULE):\s*(.+?)\s*$")
MODULE_NAME = re.compile(r'^ANNOTATION:\s*"ModuleName:\s*([^"\s]+)')
LINE_NUMBER = re.compile(r"LineNumber:\s*(\d+)")
FILE_NAME = re.compile(r"FileName:\s*([^,\s]+)")
DIMS = re.compile(r"\[(\d+)(?::(\d+))?\]")
SPACE = re.compile(r"\s+")
RANGES = re.compile(r"(\[[^\]]*\])$")
HEADER = re.compile(r"^(Line|Toggle|FSM|Cond|Branch|Assert) Coverage for (Module|Instance) : (.*)$")
SELF_INSTANCES = re.compile(r"^\w+ Coverage for Module self-instances :")
REPORT_LINE = re.compile(r"^(\d+)\s+(?:==>\s+)?(\d+)/(\d+)\b")
FSM_ROW = re.compile(r"^(.*\S)\s+\d+\s+(Not Covered|Covered|Excluded)\b")
COND_ROW = re.compile(r"^\s*((?:[01-]\s+)+)(Not Covered|Covered|Excluded)\b")

Bit = tuple[int, ...]


@dataclass
class Section:
    """One CHECKSUM block of an exclusion file or template."""

    kind: str
    scope: str
    module: str | None
    checksum: str
    items: list[str] = field(default_factory=list)
    lines: list[int | None] = field(default_factory=list)
    source: str = ""


def read_sections(text: str, commented: bool) -> list[Section]:
    """Split an exclusion file, or a commented urg template, into sections."""
    out: list[Section] = []
    checksum, module, line_no = "", None, None
    current: Section | None = None
    for raw in text.splitlines():
        if commented:
            if not raw.startswith("// "):
                continue
            line = raw[3:].strip()
        else:
            if raw.lstrip().startswith("//"):
                continue
            line = raw.strip()
        if not line:
            continue
        if line.startswith("CHECKSUM:"):
            checksum, module, current = line.split(":", 1)[1].strip(), None, None
            continue
        m = MODULE_NAME.match(line)
        if m:
            module = m.group(1)
            continue
        if line.startswith("ANNOTATION:"):
            m = LINE_NUMBER.search(line)
            line_no = int(m.group(1)) if m else line_no
            m = FILE_NAME.search(line)
            if m and current is not None and not current.source:
                current.source = m.group(1)
            continue
        m = SCOPE.match(line)
        if m:
            kind, scope = m.groups()
            name = scope.split()[0] if kind == "MODULE" else module
            current = Section(kind, scope, name, checksum)
            out.append(current)
            continue
        if current is not None and line.split(" ", 1)[0] in KEYWORDS:
            current.items.append(line)
            current.lines.append(line_no)
    return out


def declared(name: str, signature: str) -> list[tuple[int, int]]:
    """A declaration's (msb, lsb) dimensions in select order: unpacked, then packed."""
    at = signature.rfind(name)
    if at < 0:
        return []
    head = signature[:at]
    packed = head.rsplit(" ", 1)[-1] if " " in head else head
    unpacked = signature[at + len(name) :]
    return [(int(a), int(b if b else a)) for g in (unpacked, packed) for a, b in DIMS.findall(g)]


def span(a: int, b: int) -> range:
    return range(min(a, b), max(a, b) + 1)


def bits_of(dims: list[tuple[int, int]], select: str) -> set[Bit] | None:
    """The bits a select names, trailing dimensions taken whole; None if it does not fit."""
    groups = [(int(a), int(b if b else a)) for a, b in DIMS.findall(select)]
    if len(groups) > len(dims):
        return None
    axes = []
    for i, (msb, lsb) in enumerate(dims):
        full = span(msb, lsb)
        if i < len(groups):
            sub = span(*groups[i])
            if sub.start < full.start or sub.stop > full.stop:
                return None
            axes.append(sub)
        else:
            axes.append(full)
    return set(itertools.product(*axes))


def norm(text: str) -> str:
    return SPACE.sub("", text)


class Scope:
    """The objects urg's templates report for one module section or instance."""

    def __init__(self, module: str | None) -> None:
        self.module = module
        self.source = ""
        self.checksum: dict[str, str] = {}
        self.order: dict[str, dict[str, int]] = {m: {} for m in METRICS}
        self.line_of: dict[str, int | None] = {}
        self.signals: dict[str, str] = {}
        self.children: dict[str, list[str]] = defaultdict(list)
        self.blocks: dict[str, str] = {}
        self.block_text: dict[str, list[str]] = defaultdict(list)
        self.fsms: dict[str, tuple[str, dict[str, str]]] = {}
        self.cond_rows: dict[tuple[str, str | None], str] = {}
        self.cond_text: dict[tuple[str, str | None], list[str]] = defaultdict(list)

    def add(self, metric: str, checksum: str, items: list[str], lines: list[int | None]) -> None:
        self.checksum[metric] = checksum
        order = self.order[metric]
        fsm: str | None = None
        for item, line_no in zip(items, lines, strict=True):
            order.setdefault(item, len(order))
            self.line_of.setdefault(item, line_no)
            if metric == "tgl":
                m = TOGGLE.match(item)
                if m and not m.group(1) and not m.group(3):
                    name, signature = m.group(2), m.group(4)
                    self.signals[name] = signature
                    for cut in range(1, len(name)):
                        if name[cut] in ".[":
                            self.children[name[:cut]].append(name)
            elif metric == "line":
                m = BLOCK.match(item)
                if m:
                    self.blocks.setdefault(m.group(2), item)
                    self.block_text[norm(m.group(3))].append(item)
            elif metric == "fsm":
                m = FSM.match(item)
                if m:
                    fsm = m.group(1)
                    self.fsms[fsm] = (item, {})
                    continue
                m = STATE.match(item)
                if m and fsm is not None:
                    self.fsms[fsm][1][f"{m.group(1)} {m.group(2)}"] = item
            elif metric == "cond":
                m = COND.match(item)
                if m:
                    _, cksum, expr, _, vec = m.groups()
                    self.cond_rows.setdefault((cksum, vec), item)
                    self.cond_text[(norm(expr), vec)].append(item)


class Database:
    """The modules and instances urg's templates report, by metric."""

    def __init__(self, template_dir: Path) -> None:
        self.modules: dict[str, Scope] = {}
        self.by_name: dict[str, list[str]] = defaultdict(list)
        self.instances: dict[str, Scope] = {}
        for metric in METRICS:
            for path, kind in (
                (template_dir / f"fullexclude_module.{metric}", "MODULE"),
                (template_dir / f"fullexclude.{metric}", "INSTANCE"),
            ):
                if not path.is_file():
                    raise SystemExit(f"{path} not found: dump {'+'.join(METRICS)} from the run")
                for sec in read_sections(path.read_text(errors="replace"), commented=True):
                    if sec.kind != kind:
                        continue
                    table = self.modules if kind == "MODULE" else self.instances
                    if sec.scope not in table:
                        table[sec.scope] = Scope(sec.module)
                        if kind == "MODULE" and sec.module:
                            self.by_name[sec.module].append(sec.scope)
                    table[sec.scope].add(metric, sec.checksum, sec.items, sec.lines)
                    table[sec.scope].source = table[sec.scope].source or sec.source
        self.count: Counter = Counter()
        for sc in self.instances.values():
            self.count[sc.module] += 1

    def split(self, kind: str, scope: str, metric: str) -> list[tuple[str, str, Scope]]:
        """The scopes an entry for this section is written under.

        urg reports toggle per parameter set in its module template but takes no
        toggle exclusion on a parameterised MODULE section, so a toggle entry for one
        is written on each instance of that set, which carries the same checksum.
        """
        sc = (self.modules if kind == "MODULE" else self.instances)[scope]
        if kind == "MODULE" and metric == "tgl" and " ( parameter " in scope:
            return [
                ("INSTANCE", p, i)
                for p, i in self.instances.items()
                if i.module == sc.module and i.checksum.get("tgl") == sc.checksum["tgl"]
            ]
        return [(kind, scope, sc)]

    def members(self, scope: str, metric: str) -> list[tuple[str, str, Scope]]:
        """The instances of a MODULE section, for one metric."""
        sc = self.modules[scope]
        if metric not in sc.checksum or (metric == "tgl" and " ( parameter " in scope):
            return []
        return [
            ("INSTANCE", p, i)
            for p, i in self.instances.items()
            if i.module == sc.module and i.checksum.get(metric) == sc.checksum[metric]
        ]

    def module_scope(self, sc: Scope, metric: str) -> str | None:
        """The MODULE section an instance belongs to for one metric."""
        for name in self.by_name.get(sc.module or "", []):
            if self.modules[name].checksum.get(metric) == sc.checksum.get(metric):
                return name
        return None


class Report:
    """The uncovered points of a urg text report, by metric and scope."""

    def __init__(self, modinfo: Path) -> None:
        self.text = modinfo.read_text(errors="replace").splitlines()
        self.sections: dict[tuple[str, str, str], tuple[int, int]] = {}
        self.owner: dict[tuple[str, str], str] = {}
        marks: list[tuple[int, tuple[str, str, str] | None]] = []
        for i, line in enumerate(self.text):
            m = HEADER.match(line)
            if m:
                name = norm(re.sub(r"\((?:x|X)\)\s*$", "", m.group(3)))
                marks.append((i, (m.group(1), m.group(2), name)))
            elif line.startswith("====="):
                marks.append((i, None))
        ends = [i for i, _ in marks[1:]] + [len(self.text)]
        for (i, key), j in zip(marks, ends, strict=True):
            if key is None:
                continue
            self.sections[key] = (i + 1, j)
            if key[1] == "Module" and i + 1 < j and SELF_INSTANCES.match(self.text[i + 1]):
                for path in self.text[i + 2 : j]:
                    if not path.strip():
                        break
                    self.owner[(key[0], path.strip())] = key[2]
        self._toggles: dict[tuple[str, str], dict[str, dict[Bit, set[str]]]] = {}
        self._ports: dict[tuple[str, str], set[str]] = {}

    def ports(self, kind: str, scope: str, sc: Scope, db: Database) -> set[str]:
        """The signals the report lists under Port Details for one scope."""
        self.toggles(kind, scope, sc, db)
        return self._ports.get((kind, scope), set())

    def lines(self, metric: str, kind: str, scope: str, sc: Scope, db: Database) -> list[str]:
        """The report section of one scope; an only instance reads its module's."""
        rm = REPORT_METRIC[metric]
        key = (rm, "Instance" if kind == "INSTANCE" else "Module", norm(scope))
        if key not in self.sections and kind == "INSTANCE":
            owner = self.owner.get((rm, scope))
            if owner is None and db.count[sc.module] == 1:
                up = db.module_scope(sc, metric)
                owner = norm(up) if up else None
            key = (rm, "Module", owner) if owner else key
        if key not in self.sections:
            return []
        i, j = self.sections[key]
        return self.text[i:j]

    def toggles(
        self, kind: str, scope: str, sc: Scope, db: Database
    ) -> dict[str, dict[Bit, set[str]]]:
        """signal -> bit -> the directions the report marks uncovered."""
        if (kind, scope) in self._toggles:
            return self._toggles[(kind, scope)]
        rows: dict[str, list[tuple[str | None, str, str]]] = defaultdict(list)
        ports: set[str] = set()
        in_ports = False
        for line in self.lines("tgl", kind, scope, sc, db):
            if line.startswith(("Port Details", "Signal Details")):
                in_ports = line.startswith("Port Details")
                continue
            p = line.split()
            if p[:3] == ["Other", "bits", "of"] and len(p) >= 7:
                name, t10, t01, other = p[3], p[5], p[6], True
            elif len(p) >= 4 and p[1] in ("Yes", "No", "Excluded"):
                name, t10, t01, other = p[0], p[2], p[3], False
            else:
                continue
            base = name
            while base not in sc.signals:
                m = RANGES.search(base)
                if not m:
                    break
                base = base[: m.start()]
            if base in sc.signals:
                rows[base].append((None if other else name[len(base) :], t10, t01))
                if in_ports:
                    ports.add(base)
        self._ports[(kind, scope)] = ports
        out: dict[str, dict[Bit, set[str]]] = {}
        for name, entries in rows.items():
            dims = declared(name, sc.signals[name])
            status: dict[Bit, set[str]] = {}
            listed: set[Bit] = set()
            fits = True
            for suffix, t10, t01 in entries:
                if suffix is None:
                    continue
                bits = bits_of(dims, suffix)
                if bits is None:
                    fits = False
                    break
                listed |= bits
                missing = {d for d, t in zip(DIRECTIONS, (t10, t01), strict=True) if t == "No"}
                for b in bits:
                    status[b] = missing
            if not fits:
                continue
            for suffix, t10, t01 in entries:
                if suffix is not None:
                    continue
                missing = {d for d, t in zip(DIRECTIONS, (t10, t01), strict=True) if t == "No"}
                for b in (bits_of(dims, "") or set()) - listed:
                    status[b] = missing
            out[name] = {b: d for b, d in status.items() if d}
        self._toggles[(kind, scope)] = out
        return out

    def unexecuted_lines(self, kind: str, scope: str, sc: Scope, db: Database) -> set[int]:
        """Source lines every statement of which the report marks unexecuted."""
        seen: dict[int, bool] = {}
        for line in self.lines("line", kind, scope, sc, db):
            m = REPORT_LINE.match(line)
            if m:
                n = int(m.group(1))
                seen[n] = seen.get(n, True) and int(m.group(2)) == 0
        return {n for n, unexecuted in seen.items() if unexecuted}

    def fsm_points(self, kind: str, scope: str, sc: Scope, db: Database) -> dict[str, set[str]]:
        """FSM name -> the `State x` and `Transition a->b` points the report marks uncovered."""
        out: dict[str, set[str]] = defaultdict(set)
        fsm, part = None, None
        for line in self.lines("fsm", kind, scope, sc, db):
            if "Details for FSM ::" in line:
                fsm = line.split("::", 1)[1].strip()
                continue
            head = line.split()
            if head[:1] in (["states"], ["transitions"]):
                part = "State" if head[0] == "states" else "Transition"
                continue
            m = FSM_ROW.match(line)
            if m and fsm and part and m.group(2) == "Not Covered":
                out[fsm].add(f"{part} {m.group(1)}")
        return out

    def cond_rows(
        self, kind: str, scope: str, sc: Scope, db: Database
    ) -> dict[tuple[int, str], bool]:
        """(source line, vector) -> whether every report row with them is uncovered."""
        out: dict[tuple[int, str], bool] = {}
        line_no = None
        for line in self.lines("cond", kind, scope, sc, db):
            p = line.split()
            if p[:1] == ["LINE"] and len(p) > 1 and p[1].isdigit():
                line_no = int(p[1])
                continue
            m = COND_ROW.match(line)
            if m and line_no is not None:
                key = (line_no, "".join(m.group(1).split()))
                out[key] = out.get(key, True) and m.group(2) == "Not Covered"
        return out


def selects(bits: set[Bit], dims: list[tuple[int, int]]) -> list[str]:
    """Bit or part selects naming exactly `bits`, runs taken along the last dimension."""
    if not dims:
        return [""]
    msb, lsb = dims[-1]
    step = -1 if msb >= lsb else 1
    by_head: dict[Bit, list[int]] = defaultdict(list)
    for b in bits:
        by_head[b[:-1]].append(b[-1])
    out = []
    for head in sorted(by_head):
        prefix = "".join(f"[{i}]" for i in head)
        idx = sorted(by_head[head], reverse=step < 0)
        for _, run in itertools.groupby(enumerate(idx), key=lambda t: t[1] - step * t[0]):
            r = [v for _, v in run]
            sel = f"[{r[0]}:{r[-1]}]" if len(r) > 1 else f"[{r[0]}]"
            out.append(f" {prefix}{sel}")
    return out


def toggle_rows(signal: str, signature: str, owned: dict[Bit, set[str]]) -> list[str]:
    """Toggle entries for exactly the owned bits and directions of one signal."""
    dims = declared(signal, signature)
    every = bits_of(dims, "") or set()
    both = {b for b, d in owned.items() if len(d) == 2}
    if both == every:
        return [f'Toggle {signal} "{signature}"']
    out = [f'Toggle {signal}{s} "{signature}"' for s in selects(both, dims)] if both else []
    for d in DIRECTIONS:
        only = {b for b, ds in owned.items() if ds == {d}}
        if only and only == every:
            out.append(f'Toggle {d} {signal} "{signature}"')
        elif only:
            out += [f'Toggle {d} {signal}{s} "{signature}"' for s in selects(only, dims)]
    return out


def glob(pattern: str) -> re.Pattern[str]:
    """A manifest pattern: `[*]` any index, a trailing `.*` any field below, `*` anything."""
    if pattern == "*":
        return re.compile(r"^.*$")
    rx = re.escape(pattern).replace(r"\[\*\]", r"\[\d+\]")
    if rx.endswith(r"\.\*"):
        rx = rx[: -len(r"\.\*")] + r"\..*"
    return re.compile("^" + rx + "$")


@dataclass
class Plan:
    """Points to write, by scope, owned by the first (class, reviewed file) that names them."""

    toggles: dict[tuple[str, str], dict[str, dict[tuple[Bit, str], tuple[str, str]]]] = field(
        default_factory=lambda: defaultdict(lambda: defaultdict(dict))
    )
    entries: dict[tuple[str, str, str], dict[tuple[str, str], set[str]]] = field(
        default_factory=lambda: defaultdict(lambda: defaultdict(set))
    )
    owner: dict[tuple[str, str, str, str], tuple[str, str]] = field(default_factory=dict)
    counts: Counter = field(default_factory=Counter)

    def add(self, kind: str, scope: str, metric: str, owner: tuple[str, str], entry: str) -> bool:
        key = (kind, scope, metric, entry)
        if key in self.owner:
            return False
        self.owner[key] = owner
        self.entries[(kind, scope, metric)][owner].add(entry)
        return True


class Manifest:
    """smc_reviewed_exclusions.toml."""

    def __init__(self, path: Path = MANIFEST) -> None:
        data = tomllib.loads(path.read_text())
        self.review = data["review"]
        self.classes = {c["id"]: c for c in data["class"]}
        self.order = {c["id"]: i for i, c in enumerate(data["class"])}
        self.sources = {name: i for i, name in enumerate(self.review["files"])}
        self.objects = data.get("object", [])
        self.units = data.get("unit", [])
        for entry in self.objects + self.units:
            if entry["class"] not in self.classes:
                raise SystemExit(f"{path}: entry names unknown class {entry['class']}")
            if entry["source"] not in self.sources:
                raise SystemExit(f"{path}: entry names unknown reviewed file {entry['source']}")

    def annotation(self, owner: tuple[str, str]) -> str:
        cls = self.classes[owner[0]]
        review = self.review
        return (
            f'ANNOTATION: "SMC-{owner[0]}: {cls["fact"]} Reviewed with design engineering in '
            f"{review['repository']} {owner[1]} ({review['commit']}). "
            f'Retired by {cls["retired_by"]}."'
        )

    def classes_in(self, file: str) -> set[str]:
        return {cid for cid, c in self.classes.items() if c["file"] == file}


class Planner:
    """Resolves the manifest against the templates and keeps what the report leaves uncovered."""

    def __init__(
        self,
        db: Database,
        report: Report,
        manifest: Manifest,
        taken: Callable[[str, str, Scope, str], set[Bit]] | None = None,
    ) -> None:
        self.db, self.report, self.manifest, self.plan = db, report, manifest, Plan()
        self.taken = taken or (lambda kind, scope, sc, signal: set())
        for entry in manifest.objects:
            self.object(entry)
        for entry in manifest.units:
            rx = glob(entry["instance"])
            for path in sorted(p for p in db.instances if rx.match(p)):
                self.unit(entry, path)

    def targets(self, entry: dict, metric: str) -> list[tuple[str, str, Scope]]:
        db = self.db
        if "module" in entry:
            scopes = [("MODULE", s, db.modules[s]) for s in db.by_name.get(entry["module"], [])]
        else:
            rx = glob(entry["instance"])
            scopes = [("INSTANCE", p, db.instances[p]) for p in db.instances if rx.match(p)]
        live = [t for k, s, sc in scopes if metric in sc.checksum for t in db.split(k, s, metric)]
        if "module" in entry:
            live += [i for _, s, _ in scopes for i in db.members(s, metric)]
        return live

    def object(self, entry: dict) -> None:
        owner = (entry["class"], entry["source"])
        if entry.get("toggles") or entry.get("toggle_selects"):
            for kind, scope, sc in self.targets(entry, "tgl"):
                wanted: dict[str, list[tuple[str, tuple[str, ...]]]] = defaultdict(list)
                for pattern in entry.get("toggles", []):
                    rx = glob(pattern)
                    for signal in sc.signals:
                        if rx.match(signal):
                            wanted[signal].append(("", DIRECTIONS))
                for signal, select, direction in entry.get("toggle_selects", []):
                    if signal in sc.signals:
                        dirs = DIRECTIONS if direction == "both" else (direction,)
                        wanted[signal].append((select, dirs))
                self.toggle(owner, kind, scope, sc, wanted)
        if entry.get("blocks"):
            for kind, scope, sc in self.targets(entry, "line"):
                unexecuted = self.report.unexecuted_lines(kind, scope, sc, self.db)
                for ref in entry["blocks"]:
                    text, index = (ref, 0) if isinstance(ref, str) else ref
                    hits = sc.block_text.get(norm(text), [])
                    if isinstance(ref, str) and len(hits) != 1 or index >= len(hits):
                        continue
                    if sc.line_of.get(hits[index]) in unexecuted:
                        self.write(owner, kind, scope, sc, "line", hits[index])
        if entry.get("fsm"):
            for kind, scope, sc in self.targets(entry, "fsm"):
                points = self.report.fsm_points(kind, scope, sc, self.db)
                for fsm, key in entry["fsm"]:
                    if fsm not in sc.fsms:
                        continue
                    header, members = sc.fsms[fsm]
                    for name, member in members.items():
                        if key in ("*", name) and name in points.get(fsm, set()):
                            self.write(owner, kind, scope, sc, "fsm", f"{header}\n{member}")
        if entry.get("conditions"):
            for kind, scope, sc in self.targets(entry, "cond"):
                rows = self.report.cond_rows(kind, scope, sc, self.db)
                for expr, vec in entry["conditions"]:
                    hits = sc.cond_text.get((norm(expr), vec), [])
                    if len(hits) == 1 and rows.get((sc.line_of.get(hits[0]), vec), False):
                        self.write(owner, kind, scope, sc, "cond", hits[0])

    def toggle(self, owner, kind: str, scope: str, sc: Scope, wanted) -> None:
        plan = self.plan
        uncovered = self.report.toggles(kind, scope, sc, self.db)
        above: dict = {}
        if kind == "INSTANCE":
            up = self.db.module_scope(sc, "tgl")
            above = plan.toggles.get(("MODULE", up), {}) if up else {}
        for signal, picks in wanted.items():
            dims = declared(signal, sc.signals[signal])
            have = uncovered.get(signal, {})
            owned = plan.toggles[(kind, scope)][signal]
            taken = self.taken(kind, scope, sc, signal)
            for select, dirs in picks:
                for b in (bits_of(dims, select) or set()) - taken:
                    for d in dirs:
                        if d in have.get(b, ()) and (b, d) not in above.get(signal, {}):
                            owned.setdefault((b, d), owner)

    def unit(self, entry: dict, root: str) -> None:
        """Every uncovered line, FSM and condition point inside one instance.

        A unit's toggle points are planned by smc_toggle_exclusions.py.
        """
        db, report = self.db, self.report
        review = self.manifest.review
        own = (entry["class"], entry["source"])
        regblock = (review["unit_regblock_class"], entry["source"])
        fsm_owner = (review["unit_fsm_class"], entry["source"])
        scopes = [root] + sorted(p for p in db.instances if p.startswith(root + "."))
        for path in scopes:
            sc = db.instances[path]
            owner = regblock if "/regs/gen/" in sc.source else own
            if "line" in sc.checksum:
                unexecuted = report.unexecuted_lines("INSTANCE", path, sc, db)
                for item in sc.order["line"]:
                    if BLOCK.match(item) and sc.line_of.get(item) in unexecuted:
                        self.write(owner, "INSTANCE", path, sc, "line", item)
            if "fsm" in sc.checksum:
                points = report.fsm_points("INSTANCE", path, sc, db)
                for fsm, (header, members) in sc.fsms.items():
                    for key, member in members.items():
                        if key in points.get(fsm, set()):
                            self.write(
                                fsm_owner, "INSTANCE", path, sc, "fsm", f"{header}\n{member}"
                            )
            if "cond" in sc.checksum:
                rows = report.cond_rows("INSTANCE", path, sc, db)
                for item in sc.order["cond"]:
                    m = COND.match(item)
                    if (
                        m
                        and m.group(5) is not None
                        and rows.get((sc.line_of.get(item), m.group(5)))
                    ):
                        self.write(owner, "INSTANCE", path, sc, "cond", item)

    def write(self, owner, kind: str, scope: str, sc: Scope, metric: str, entry: str) -> None:
        if kind == "INSTANCE":
            up = self.db.module_scope(sc, metric)
            if up and ("MODULE", up, metric, entry) in self.plan.owner:
                return
        self.plan.add(kind, scope, metric, owner, entry)

    def blocks(self, classes: set[str]) -> tuple[list[str], Counter]:
        """The `.el` blocks of the named classes, in a fixed order."""
        db, plan, manifest = self.db, self.plan, self.manifest
        owners = sorted(
            {o for s in plan.toggles.values() for v in s.values() for o in v.values()}
            | {o for f in plan.entries.values() for o in f},
            key=lambda o: (manifest.order[o[0]], manifest.sources[o[1]]),
        )
        owners = [o for o in owners if o[0] in classes]
        counts: Counter = Counter()
        blocks: list[tuple[tuple[str, str, str], list[str]]] = []
        for (kind, scope), signals in plan.toggles.items():
            sc = (db.modules if kind == "MODULE" else db.instances)[scope]
            order: dict[str, int] = {}
            for item, i in sc.order["tgl"].items():
                m = TOGGLE.match(item)
                if m:
                    order.setdefault(m.group(2), i)
            body: list[str] = []
            for owner in owners:
                rows: list[str] = []
                for signal in sorted(signals, key=lambda s: (order.get(s, 1 << 30), s)):
                    owned: dict[Bit, set[str]] = defaultdict(set)
                    for (b, d), who in signals[signal].items():
                        if who == owner:
                            owned[b].add(d)
                    if owned:
                        counts[f"{owner[0]} tgl half-toggles"] += sum(
                            len(d) for d in owned.values()
                        )
                        rows += toggle_rows(signal, sc.signals[signal], owned)
                if rows:
                    counts[f"{owner[0]} tgl"] += len(rows)
                    body += [manifest.annotation(owner), *rows]
            if body:
                blocks.append(((kind, scope, "tgl"), body))
        for (kind, scope, metric), files in plan.entries.items():
            sc = (db.modules if kind == "MODULE" else db.instances)[scope]
            order = sc.order[metric]
            body = []
            for owner in owners:
                if owner not in files:
                    continue
                body.append(manifest.annotation(owner))
                rows = sorted(
                    files[owner], key=lambda e: ([order.get(x, 1 << 30) for x in e.split("\n")], e)
                )
                counts[f"{owner[0]} {metric}"] += len(rows)
                if metric == "fsm":
                    last = None
                    for row in rows:
                        header, member = row.split("\n")
                        if header != last:
                            body.append(header)
                            last = header
                        body.append(member)
                else:
                    body += rows
            if body:
                blocks.append(((kind, scope, metric), body))
        out: list[str] = []
        for (kind, scope, metric), body in sorted(
            blocks, key=lambda b: (b[0][2], b[0][0], b[0][1])
        ):
            sc = (db.modules if kind == "MODULE" else db.instances)[scope]
            out += ["", f"CHECKSUM: {sc.checksum[metric]}", f"{kind}: {scope}", *body]
        return out, counts
