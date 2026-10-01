#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Write the L1 and L2 exclusion files from the archived tt-oca-hw SMC exclusion files.

L1 LEGACY-DE-APPROVED carries one fact, a provenance: the SMC bench of the
archived tt-oca-hw repository excluded these objects in the files LEGACY_FILES
names, and design engineering reviewed those files in that repository. The
class states no design fact of its own. An object leaves when an enrolled leaf
covers it, or when design engineering withdraws the approval.

The file is report-gated, as the SMU MEM-MACRO class is: it holds only the
legacy objects the graded run's raw report (`cov/report_raw/modinfo.txt`,
written without exclusion files) marks uncovered, so nothing a leaf already
covers is waived. It is regenerated from each graded run, and `--check`
compares the committed file against the run it is given. A toggle is decided
per bit and direction, a line block by its source line, an FSM state or
transition by name and a condition row by source line and vector; a point the
report does not name is left graded.

The legacy files are not part of this repository. Pass the directory that holds
them, `dv/smc/tb/tb_uvm/exclusion_files/` of tt-oca-hw at LEGACY_COMMIT; the
output header records the repository, the commit and the file names, never the
local path. The legacy files name the SMC under `smc_uvm_top.u_smc_wrapper` and
an older bench under `smc_uvm_top.tt_smc`; this bench names it
`smc_uvm_top.u_dut`. Each object is mapped onto the current hierarchy, and urg's
`-dump full_exclusions` templates of the merged database decide what exists:

* a MODULE-scope object stays MODULE scope, on every parameter section of the
  module the template reports, where the module's report section, the union of
  its instances, marks it uncovered; where only some instances leave it
  uncovered it is written on those instances. urg takes no toggle exclusion on
  a parameterised MODULE section, so a toggle there is written on each instance
  of the section;
* an INSTANCE-scope object stays INSTANCE scope where the instance still
  exists, found by its path with `u_smc_wrapper` read as `u_dut`, then by the
  same path compared without the `u_` or `i_` instance prefix and without
  unindexed generate blocks, which this tree renamed or removed; the match must
  name one current instance of the module the legacy file gives. An instance
  point a MODULE-scope object of the same module already excludes is not
  repeated;
* a toggle maps by signal name, a port this tree renamed from `i_x` or `o_x`
  to `x_i` or `x_o` under its new name; a bit or part select is kept only where
  every index lies within the signal's current declaration, and a whole-signal
  exclusion takes the signal at its current width. A name the template splits
  into fields takes each field;
* a line block maps by its block checksum, then by its statement text when that
  names one block; an FSM by its name, then each state or transition by name;
  a condition row by expression checksum and vector, then by expression text;
* every entry is written with the checksum, identifier and text the current
  template gives it, never the legacy file's.

L2 LEGACY-INSTANCE-CHILDREN carries the legacy INSTANCE lines with no object
under them, each of which excluded a whole instance, into
smc_legacy_children_exclusions.el: the instance keeps its own ports graded, the
ports being the signals the report lists under Port Details, and every
uncovered toggle bit and direction, line block, FSM state or transition and
condition row of its internal signals and of every instance beneath it is
written, under the same report gate. An excluded instance inside another is
part of the outer one's internals, so only the outermost keeps its ports. A
point L1 already writes is not repeated. `--stats` counts, by file and reason,
every object that does not map or that the run covers, and what each L2
instance contributed and the port half-toggles it kept graded.

    urg -full64 -dir <run dir>/cov/merged.vdb -dump full_exclusions tgl+line+fsm+cond \\
        -report <dir>
    python3 gen_smc_legacy_exclusions.py <legacy dir> <dir> <run dir>/cov/report_raw/modinfo.txt
    python3 gen_smc_legacy_exclusions.py <legacy dir> <dir> <modinfo> --check
"""

from __future__ import annotations

import argparse
import itertools
import json
import re
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE / "smc_legacy_exclusions.el"
CHILDREN_OUT = HERE / "smc_legacy_children_exclusions.el"
SCOPE_FILE = HERE / "smc_cov_scope.hier"

LEGACY_REPO = "tt-oca-hw"
LEGACY_COMMIT = "cb678bff"
LEGACY_PATH = "dv/smc/tb/tb_uvm/exclusion_files"
# The six files exclude_filelist.f names, then the five the same directory
# carries beside them.
LEGACY_FILES: tuple[str, ...] = (
    "smc_chiplet_synced/smc_exclusions_path_valid.el",
    "smc_synced_fullexclude.fsm.el",
    "smc_synced_module_filtered.tgl.el",
    "smc_synced_module_filtered.line.el",
    "smc_synced_module_filtered.fsm.el",
    "smc_synced_inst_filtered.tgl.el",
    "smc_cluster.el",
    "smc_filter.el",
    "smc_env_apb_axi_if.el",
    "uart_log_engine_rep0_self_toggle_exclusions.el",
    "uart_log_engine_rep0_wrapper_toggle_exclusions.el",
)

TOP = "smc_uvm_top"
DUT = f"{TOP}.u_dut"
LEGACY_TOPS = (f"{TOP}.u_smc_wrapper", f"{TOP}.tt_smc")
METRICS = ("tgl", "line", "fsm", "cond")
REPORT_METRIC = {"tgl": "Toggle", "line": "Line", "fsm": "FSM", "cond": "Cond"}
KEYWORDS = ("Toggle", "Block", "Fsm", "State", "Transition", "Condition")
METRIC_OF = {
    "Toggle": "tgl",
    "Block": "line",
    "Fsm": "fsm",
    "State": "fsm",
    "Transition": "fsm",
    "Condition": "cond",
}
DIRECTIONS = ("1to0", "0to1")


# L1 rows are owned by a legacy file name, L2 rows by the same name behind CHILDREN.
CHILDREN = "L2:"
OWNERS: tuple[str, ...] = LEGACY_FILES + tuple(CHILDREN + name for name in LEGACY_FILES)


def annotation(owner: str) -> str:
    if owner.startswith(CHILDREN):
        return (
            f'ANNOTATION: "SMC-L2-LEGACY-INSTANCE-CHILDREN: carried from {LEGACY_REPO} '
            f"{owner[len(CHILDREN) :]} ({LEGACY_COMMIT}) whole-instance exclusion, reviewed with "
            "design engineering in that repository; the instance's ports stay graded and its "
            "internals are excluded while uncovered; retired when an enrolled leaf covers the "
            'object or design engineering withdraws the approval"'
        )
    return (
        f'ANNOTATION: "SMC-L1-LEGACY-DE-APPROVED: carried from {LEGACY_REPO} {owner} '
        f"({LEGACY_COMMIT}), reviewed with design engineering in that repository; retired "
        'when an enrolled leaf covers the object or design engineering withdraws the approval"'
    )


TOGGLE = re.compile(r'^Toggle\s+(?:(0to1|1to0)\s+)?(\S+)(?:\s+((?:\[[^\]]*\])+))?\s+"([^"]*)"\s*$')
BLOCK = re.compile(r'^Block\s+(\d+)\s+"(\d+)"\s+"(.*)"\s*$')
FSM = re.compile(r'^Fsm\s+(\S+)\s+"(\d+)"\s*$')
STATE = re.compile(r'^(State|Transition)\s+(.*\S)\s+"([^"]*)"\s*$')
COND = re.compile(r'^Condition\s+(\d+)\s+"(\d+)"\s+"(.*)"(?:\s+\((\d+)\s+"([^"]*)"\))?\s*$')
SCOPE = re.compile(r"^(INSTANCE|MODULE):\s*(.+?)\s*$")
MODULE_NAME = re.compile(r'^ANNOTATION:\s*"ModuleName:\s*([^"\s]+)')
LINE_NUMBER = re.compile(r"LineNumber:\s*(\d+)")
DIMS = re.compile(r"\[(\d+)(?::(\d+))?\]")
SPACE = re.compile(r"\s+")
PREFIX = re.compile(r"^(?:u|i)_(?=.)")
PORT = re.compile(r"^(i|o)_([A-Za-z0-9_]+)(?=$|[.\[])")
GENERATE = re.compile(r"^(?:gen|g)_[A-Za-z0-9_]*$|^genblk\d+$")
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
        scope = SCOPE_FILE.read_text().splitlines()
        self.dropped = {line.split()[1] for line in scope if line.startswith("-module ")}
        self.trees = tuple(
            line.split()[1]
            for line in scope
            if line.startswith("-tree ") and len(line.split()) == 2
        )
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
        self.normal: dict[tuple[str, ...], list[str]] = defaultdict(list)
        self.count: Counter = Counter()
        for path, sc in self.instances.items():
            self.normal[normal(path)].append(path)
            self.count[sc.module] += 1

    def instance(self, legacy: str, module: str | None) -> tuple[str | None, str]:
        """The current instance a legacy path names, and how it was found."""
        for top in LEGACY_TOPS:
            if legacy == top or legacy.startswith(top + "."):
                direct = DUT + legacy[len(top) :]
                break
        else:
            direct = legacy
        if direct in self.instances and module in (None, self.instances[direct].module):
            return direct, "path"
        hits = self.normal.get(normal(direct), [])
        if len(hits) > 1:
            return None, "instance-ambiguous"
        if hits and module in (None, self.instances[hits[0]].module):
            return hits[0], "renamed-path"
        if direct.startswith(tuple(t + "." for t in self.trees)):
            return None, "tree-out-of-scope"
        if module is not None and module not in self.by_name:
            return None, self.gone(module)
        return None, "instance-gone"

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

    def gone(self, module: str | None) -> str:
        """Why the database holds no section for a module."""
        return "module-out-of-scope" if module in self.dropped else "module-not-built"


def normal(path: str) -> tuple[str, ...]:
    """A path's components without the `u_`/`i_` prefix and without unindexed generate blocks."""
    return tuple(PREFIX.sub("", c) for c in path.split(".") if not GENERATE.match(c))


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


def map_toggle(scope: Scope, item: str) -> tuple[list[tuple[str, str, tuple[str, ...]]], str]:
    """(signal, select, directions) targets of one legacy toggle object."""
    m = TOGGLE.match(item)
    if not m:
        return [], "unparsed"
    direction, name, select, legacy_signature = m.groups()
    dirs = (direction,) if direction else DIRECTIONS
    renamed, how = PORT.sub(r"\2_\1", name, count=1), "signal"
    if name not in scope.signals and name not in scope.children and renamed != name:
        if renamed in scope.signals or renamed in scope.children:
            name, how = renamed, "renamed-port"
    signature = scope.signals.get(name)
    if signature is None:
        children = scope.children.get(name)
        if children and not select:
            return [(c, "", dirs) for c in children if c in scope.signals], f"{how}-fields"
        return [], "signal-gone"
    if select:
        if bits_of(declared(name, signature), select) is None:
            return [], "select-out-of-range"
        return [(name, select, dirs)], how
    if how == "signal" and legacy_signature != signature:
        how = "signal-resized"
    return [(name, "", dirs)], how


def map_block(scope: Scope, item: str) -> tuple[list[str], str]:
    m = BLOCK.match(item)
    if not m:
        return [], "unparsed"
    if m.group(2) in scope.blocks:
        return [scope.blocks[m.group(2)]], "checksum"
    hits = scope.block_text.get(norm(m.group(3)), [])
    if len(hits) == 1:
        return hits, "text"
    return [], "block-gone" if not hits else "block-ambiguous"


def map_cond(scope: Scope, item: str) -> tuple[list[str], str]:
    m = COND.match(item)
    if not m:
        return [], "unparsed"
    _, cksum, expr, _, vec = m.groups()
    if (cksum, vec) in scope.cond_rows:
        return [scope.cond_rows[(cksum, vec)]], "checksum"
    hits = scope.cond_text.get((norm(expr), vec), [])
    if len(hits) == 1:
        return hits, "text"
    return [], "condition-gone" if not hits else "condition-ambiguous"


@dataclass
class Plan:
    """What to write: toggle bit-directions and other entries, by scope and legacy file."""

    toggles: dict[tuple[str, str], dict[str, dict[tuple[Bit, str], str]]] = field(
        default_factory=lambda: defaultdict(lambda: defaultdict(dict))
    )
    entries: dict[tuple[str, str, str], dict[str, set[str]]] = field(
        default_factory=lambda: defaultdict(lambda: defaultdict(set))
    )
    owner: dict[tuple[str, str, str, str], str] = field(default_factory=dict)
    stats: Counter = field(default_factory=Counter)
    unmapped: dict[str, Counter] = field(default_factory=lambda: defaultdict(Counter))
    # The legacy half-toggles that map and that the run covers, by scope and signal.
    covered: dict[tuple[str, str], dict[str, set[tuple[Bit, str]]]] = field(
        default_factory=lambda: defaultdict(lambda: defaultdict(set))
    )

    # Per L2 root: what it contributed, and the port half-toggles it keeps graded.
    children: dict[str, Counter] = field(default_factory=lambda: defaultdict(Counter))

    def add(self, kind: str, scope: str, metric: str, name: str, entry: str) -> bool:
        key = (kind, scope, metric, entry)
        if key in self.owner:
            return False
        self.owner[key] = name
        self.entries[(kind, scope, metric)][name].add(entry)
        return True


class Builder:
    """Maps legacy sections onto the database and keeps what the report leaves uncovered."""

    def __init__(self, db: Database, report: Report) -> None:
        self.db, self.report, self.plan = db, report, Plan()

    def section(self, name: str, sec: Section) -> None:
        db, plan = self.db, self.plan
        by_metric: dict[str, list[str]] = defaultdict(list)
        for item in sec.items:
            by_metric[METRIC_OF[item.split(" ", 1)[0]]].append(item)
        if sec.kind == "INSTANCE" and not sec.items:
            path, _ = db.instance(sec.scope, sec.module)
            plan.stats[f"{name}\twhole-instance\t{'exists' if path else 'gone'}"] += 1
            return
        if sec.kind == "MODULE":
            targets = [("MODULE", s, db.modules[s]) for s in db.by_name.get(sec.module or "", [])]
            reason = db.gone(sec.module)
        else:
            path, reason = db.instance(sec.scope, sec.module)
            targets = [("INSTANCE", path, db.instances[path])] if path else []
            if path:
                plan.stats[f"{name}\tinstance-by-{reason}"] += 1
        for metric, items in by_metric.items():
            live = [
                t for k, s, sc in targets if metric in sc.checksum for t in db.split(k, s, metric)
            ]
            if sec.kind == "MODULE":
                live += [i for k, s, _ in targets for i in db.members(s, metric)]
            if not live:
                why = reason if not targets else "metric-gone"
                plan.unmapped[f"{name}\t{metric}"][why] += len(items)
                continue
            getattr(self, metric)(name, live, items)

    def tgl(self, name: str, live, items: list[str]) -> None:
        plan = self.plan
        for item in items:
            for kind, scope, sc in live:
                targets, how = map_toggle(sc, item)
                if not targets:
                    plan.unmapped[f"{name}\ttgl"][how] += 1
                    continue
                plan.stats[f"{name}\ttgl\tmapped-by-{how}"] += 1
                uncovered = self.report.toggles(kind, scope, sc, self.db)
                above: dict[str, dict[tuple[Bit, str], str]] = {}
                if kind == "INSTANCE":
                    up = self.db.module_scope(sc, "tgl")
                    above = plan.toggles.get(("MODULE", up), {}) if up else {}
                for signal, select, dirs in targets:
                    bits = bits_of(declared(signal, sc.signals[signal]), select) or set()
                    have = uncovered.get(signal, {})
                    owned = plan.toggles[(kind, scope)][signal]
                    for b in bits:
                        for d in dirs:
                            if d not in have.get(b, ()):
                                plan.covered[(kind, scope)][signal].add((b, d))
                            elif (b, d) not in above.get(signal, {}):
                                owned.setdefault((b, d), name)

    def line(self, name: str, live, items: list[str]) -> None:
        for item in items:
            for kind, scope, sc in live:
                mapped, how = map_block(sc, item)
                if not mapped:
                    self.plan.unmapped[f"{name}\tline"][how] += 1
                    continue
                unexecuted = self.report.unexecuted_lines(kind, scope, sc, self.db)
                for entry in mapped:
                    if sc.line_of.get(entry) not in unexecuted:
                        self.plan.stats[f"{name}\tline\tcovered"] += 1
                        continue
                    self.write(name, kind, scope, sc, "line", entry)

    def cond(self, name: str, live, items: list[str]) -> None:
        for item in items:
            for kind, scope, sc in live:
                mapped, how = map_cond(sc, item)
                if not mapped:
                    self.plan.unmapped[f"{name}\tcond"][how] += 1
                    continue
                rows = self.report.cond_rows(kind, scope, sc, self.db)
                for entry in mapped:
                    m = COND.match(entry)
                    vec = m.group(5) if m else None
                    line_no = sc.line_of.get(entry)
                    if vec is None or line_no is None or not rows.get((line_no, vec), False):
                        self.plan.stats[f"{name}\tcond\tcovered"] += 1
                        continue
                    self.write(name, kind, scope, sc, "cond", entry)

    def fsm(self, name: str, live, items: list[str]) -> None:
        fsm: str | None = None
        for item in items:
            m = FSM.match(item)
            if m:
                fsm = m.group(1)
                continue
            m = STATE.match(item)
            if not m or fsm is None:
                self.plan.unmapped[f"{name}\tfsm"]["unparsed"] += 1
                continue
            key = f"{m.group(1)} {m.group(2)}"
            for kind, scope, sc in live:
                if fsm not in sc.fsms:
                    self.plan.unmapped[f"{name}\tfsm"]["fsm-gone"] += 1
                    continue
                header, members = sc.fsms[fsm]
                if key not in members:
                    self.plan.unmapped[f"{name}\tfsm"][f"{m.group(1).lower()}-gone"] += 1
                    continue
                if key not in self.report.fsm_points(kind, scope, sc, self.db).get(fsm, set()):
                    self.plan.stats[f"{name}\tfsm\tcovered"] += 1
                    continue
                self.write(name, kind, scope, sc, "fsm", f"{header}\n{members[key]}")

    def children(self, name: str, root: str) -> None:
        """L2: every uncovered point inside one instance, its own ports excepted."""
        db, plan, report = self.db, self.plan, self.report
        owner = CHILDREN + name
        tally = plan.children[root]
        scopes = [root] + sorted(p for p in db.instances if p.startswith(root + "."))
        for path in scopes:
            sc = db.instances[path]
            kept = report.ports("INSTANCE", path, sc, db) if path == root else set()
            if "tgl" in sc.checksum:
                up = db.module_scope(sc, "tgl")
                above = plan.toggles.get(("MODULE", up), {}) if up else {}
                for signal, bits in report.toggles("INSTANCE", path, sc, db).items():
                    if signal in kept:
                        tally["port half-toggles kept uncovered"] += sum(
                            len(d) for d in bits.values()
                        )
                        continue
                    owned = plan.toggles[("INSTANCE", path)][signal]
                    for b, dirs in bits.items():
                        for d in dirs:
                            if (b, d) in owned or (b, d) in above.get(signal, {}):
                                continue
                            owned[(b, d)] = owner
                            tally["tgl half-toggles"] += 1
            if path == root:
                for signal in kept:
                    n = len(bits_of(declared(signal, sc.signals[signal]), "") or ())
                    tally["port half-toggles kept"] += 2 * n
            if "line" in sc.checksum:
                unexecuted = report.unexecuted_lines("INSTANCE", path, sc, db)
                for entry in sc.order["line"]:
                    if BLOCK.match(entry) and sc.line_of.get(entry) in unexecuted:
                        tally["line"] += self.write(owner, "INSTANCE", path, sc, "line", entry)
            if "fsm" in sc.checksum:
                points = report.fsm_points("INSTANCE", path, sc, db)
                for fsm, (header, members) in sc.fsms.items():
                    for key, member in members.items():
                        if key in points.get(fsm, set()):
                            entry = f"{header}\n{member}"
                            tally["fsm"] += self.write(owner, "INSTANCE", path, sc, "fsm", entry)
            if "cond" in sc.checksum:
                rows = report.cond_rows("INSTANCE", path, sc, db)
                for entry in sc.order["cond"]:
                    m = COND.match(entry)
                    if (
                        m
                        and m.group(5) is not None
                        and rows.get((sc.line_of.get(entry), m.group(5)))
                    ):
                        tally["cond"] += self.write(owner, "INSTANCE", path, sc, "cond", entry)

    def write(self, name: str, kind: str, scope: str, sc: Scope, metric: str, entry: str) -> bool:
        plan = self.plan
        if kind == "INSTANCE":
            up = self.db.module_scope(sc, metric)
            if up and ("MODULE", up, metric, entry) in plan.owner:
                return False
        if plan.add(kind, scope, metric, name, entry):
            plan.stats[f"{name}\t{metric}\tentries"] += 1
            return True
        return False


def legacy_sections(legacy_dir: Path) -> list[tuple[str, Section]]:
    sections: list[tuple[str, Section]] = []
    for name in LEGACY_FILES:
        path = legacy_dir / name
        if not path.is_file():
            raise SystemExit(f"{path} not found: pass {LEGACY_PATH} of {LEGACY_REPO}")
        for sec in read_sections(path.read_text(errors="replace"), commented=False):
            sections.append((name, sec))
    # A legacy INSTANCE without a ModuleName annotation takes the module another
    # legacy file gives the same path.
    modules = {s.scope: s.module for _, s in sections if s.kind == "INSTANCE" and s.module}
    for _, sec in sections:
        if sec.kind == "INSTANCE" and sec.module is None:
            sec.module = modules.get(sec.scope)
    return sections


def build(legacy_dir: Path, db: Database, report: Report) -> Plan:
    builder = Builder(db, report)
    sections = legacy_sections(legacy_dir)
    # MODULE scope first, so an instance point its module already carries is not repeated.
    for name, sec in sections:
        if sec.kind == "MODULE":
            builder.section(name, sec)
    for name, sec in sections:
        if sec.kind == "INSTANCE":
            builder.section(name, sec)
    # L2 after every L1 object, so a point either class names is written once, as L1.
    # An excluded instance inside another is part of the outer one's internals.
    whole: dict[str, str] = {}
    for name, sec in sections:
        if sec.kind == "INSTANCE" and not sec.items:
            path, _ = db.instance(sec.scope, sec.module)
            if path:
                whole.setdefault(path, name)
    for path, name in sorted(whole.items()):
        if not any(path.startswith(other + ".") for other in whole):
            builder.children(name, path)
    return builder.plan


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


L1_TEXT = ("// it and that run leaves it uncovered, with the template's checksum and text.",)
L2_TEXT = (
    "// it and that run leaves it uncovered, with the template's checksum and text.",
    "// This file holds the whole-instance exclusions of those files: each instance",
    "// keeps its own ports graded, and its internal signals and every instance",
    "// beneath it are excluded while uncovered. An excluded instance inside another",
    "// is part of the outer one's internals.",
)


def render(
    plan: Plan, db: Database, owners: tuple[str, ...], title: str, text: tuple[str, ...]
) -> tuple[str, Counter]:
    out = [
        "// SPDX-License-Identifier: Apache-2.0",
        "// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.",
        "//==================================================",
        f"// SMC VCS coverage exclusions -- {title}.",
        "// Format Version: 2",
        "// ExclMode: default",
        "//",
        "// Generated by gen_smc_legacy_exclusions.py from urg's full_exclusions",
        "// templates and the raw report of one graded run, and the SMC exclusion files",
        f"// of the archived {LEGACY_REPO} repository at commit {LEGACY_COMMIT},",
        f"// {LEGACY_PATH}/:",
        *(f"//   {name}" for name in LEGACY_FILES),
        "// Design engineering reviewed those files in that repository. Each object is",
        "// mapped onto this bench's hierarchy and written only where the database holds",
        *text,
        "// Regenerate from each graded run rather than edit. README.md states the",
        "// class; the ANNOTATION before each group names the legacy file.",
        "//==================================================",
    ]
    counts: Counter = Counter()
    blocks: list[tuple[tuple[str, str, str], list[str]]] = []
    for (kind, scope), signals in plan.toggles.items():
        sc = (db.modules if kind == "MODULE" else db.instances)[scope]
        order = {}
        for entry, i in sc.order["tgl"].items():
            m = TOGGLE.match(entry)
            if m:
                order.setdefault(m.group(2), i)
        body: list[str] = []
        for name in owners:
            rows: list[str] = []
            for signal in sorted(signals, key=lambda s: (order.get(s, 1 << 30), s)):
                owned: dict[Bit, set[str]] = defaultdict(set)
                for (b, d), owner in signals[signal].items():
                    if owner == name:
                        owned[b].add(d)
                        counts["tgl half-toggles"] += 1
                if owned:
                    rows += toggle_rows(signal, sc.signals[signal], owned)
            if rows:
                counts["tgl"] += len(rows)
                body += [annotation(name), *rows]
        if body:
            blocks.append(((kind, scope, "tgl"), body))
    for (kind, scope, metric), files in plan.entries.items():
        sc = (db.modules if kind == "MODULE" else db.instances)[scope]
        order = sc.order[metric]
        body = []
        for name in owners:
            if name not in files:
                continue
            body.append(annotation(name))
            rows = sorted(
                files[name], key=lambda e: ([order.get(x, 1 << 30) for x in e.split("\n")], e)
            )
            counts[metric] += len(rows)
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
    for (kind, scope, metric), body in sorted(blocks, key=lambda b: (b[0][2], b[0][0], b[0][1])):
        sc = (db.modules if kind == "MODULE" else db.instances)[scope]
        out += ["", f"CHECKSUM: {sc.checksum[metric]}", f"{kind}: {scope}", *body]
    return "\n".join(out) + "\n", counts


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("legacy_dir", type=Path, help=f"{LEGACY_PATH} of {LEGACY_REPO}")
    ap.add_argument(
        "template_dir", type=Path, help="holds fullexclude{,_module}.{tgl,line,fsm,cond}"
    )
    ap.add_argument("modinfo", type=Path, help="the run's cov/report_raw/modinfo.txt")
    ap.add_argument("--check", action="store_true", help="fail if the file is stale for this run")
    ap.add_argument("--stats", type=Path, help="write mapping counts, by file and reason, as JSON")
    args = ap.parse_args()
    db = Database(args.template_dir)
    plan = build(args.legacy_dir, db, Report(args.modinfo))
    l2 = tuple(CHILDREN + name for name in LEGACY_FILES)
    outputs = [
        (OUT, *render(plan, db, LEGACY_FILES, "L1 LEGACY-DE-APPROVED", L1_TEXT)),
        (CHILDREN_OUT, *render(plan, db, l2, "L2 LEGACY-INSTANCE-CHILDREN", L2_TEXT)),
    ]
    counts = Counter()
    for path, _, c in outputs:
        counts.update({f"{path.name} {k}": v for k, v in c.items()})
    if args.stats:
        covered = sum(len(v) for s in plan.covered.values() for v in s.values())
        args.stats.write_text(
            json.dumps(
                {
                    "mapped": dict(sorted(plan.stats.items())),
                    "unmapped": plan.unmapped,
                    "written": dict(counts),
                    "tgl covered half-toggles": covered,
                    "children": {root: dict(c) for root, c in sorted(plan.children.items())},
                },
                indent=1,
                sort_keys=True,
            )
        )
    if args.check:
        stale = [
            path for path, text, _ in outputs if not path.is_file() or path.read_text() != text
        ]
        for path in stale:
            print(f"{path} is stale for this run; rerun without --check", file=sys.stderr)
        if stale:
            return 1
        print(" and ".join(path.name for path, _, _ in outputs) + " are current")
        return 0
    for path, text, _ in outputs:
        path.write_text(text)
    print("wrote " + ", ".join(f"{k} {v}" for k, v in sorted(counts.items())))
    return 0


if __name__ == "__main__":
    sys.exit(main())
