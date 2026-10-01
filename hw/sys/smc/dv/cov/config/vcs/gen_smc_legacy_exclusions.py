#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Write smc_legacy_exclusions.el from the archived tt-oca-hw SMC exclusion files.

L1 LEGACY-DE-APPROVED carries one fact, a provenance: the SMC bench of the
archived tt-oca-hw repository excluded these objects in the files LEGACY_FILES
names, and design engineering reviewed those files in that repository. The
class states no design fact of its own. An object leaves when an enrolled leaf
covers it, or when design engineering withdraws the approval.

The legacy files are not part of this repository. Pass the directory that holds
them, `dv/smc/tb/tb_uvm/exclusion_files/` of tt-oca-hw at LEGACY_COMMIT; the
output header records the repository, the commit and the file names, never the
local path. The legacy files name the SMC under `smc_uvm_top.u_smc_wrapper` and
an older bench under `smc_uvm_top.tt_smc`; this bench names it
`smc_uvm_top.u_dut`. Each object is mapped onto the current hierarchy, and urg's
`-dump full_exclusions` templates of the merged database decide what exists:

* a MODULE-scope object stays MODULE scope, on every parameter section of the
  module the template reports; urg takes no toggle exclusion on a parameterised
  MODULE section, so a toggle there is written on each instance of the section;
* an INSTANCE-scope object stays INSTANCE scope where the instance still
  exists, found by its path with `u_smc_wrapper` read as `u_dut`, then by the
  same path compared without the `u_` or `i_` instance prefix and without
  unindexed generate blocks, which this tree renamed or removed; the match must
  name one current instance of the module the legacy file gives. An instance
  object a MODULE-scope object of the same module already excludes is not
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

Whether the run covers an object does not decide whether it is written: every
object that exists is, so the file does not change from seed to seed. An
INSTANCE line with no object under it, which excludes a whole instance, is not
an object of any metric and is not carried; `--stats` counts those, and every
object that does not map, by reason.

    urg -full64 -dir <run dir>/cov/merged.vdb -dump full_exclusions tgl+line+fsm+cond \\
        -report <dir>
    python3 gen_smc_legacy_exclusions.py <legacy dir> <dir>
    python3 gen_smc_legacy_exclusions.py <legacy dir> <dir> --check
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE / "smc_legacy_exclusions.el"
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
KEYWORDS = ("Toggle", "Block", "Fsm", "State", "Transition", "Condition")
METRIC_OF = {
    "Toggle": "tgl",
    "Block": "line",
    "Fsm": "fsm",
    "State": "fsm",
    "Transition": "fsm",
    "Condition": "cond",
}


def annotation(name: str) -> str:
    return (
        f'ANNOTATION: "SMC-L1-LEGACY-DE-APPROVED: carried from {LEGACY_REPO} {name} '
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
DIMS = re.compile(r"\[(\d+)(?::(\d+))?\]")
SPACE = re.compile(r"\s+")
PREFIX = re.compile(r"^(?:u|i)_(?=.)")
PORT = re.compile(r"^(i|o)_([A-Za-z0-9_]+)(?=$|[.\[])")
GENERATE = re.compile(r"^(?:gen|g)_[A-Za-z0-9_]*$|^genblk\d+$")


@dataclass
class Section:
    """One CHECKSUM block of an exclusion file or template."""

    kind: str
    scope: str
    module: str | None
    checksum: str
    items: list[str] = field(default_factory=list)


def read_sections(text: str, commented: bool) -> list[Section]:
    """Split an exclusion file, or a commented urg template, into sections."""
    out: list[Section] = []
    checksum, module = "", None
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
        m = SCOPE.match(line)
        if m:
            kind, scope = m.groups()
            name = scope.split()[0] if kind == "MODULE" else module
            current = Section(kind, scope, name, checksum)
            out.append(current)
            continue
        if current is not None and line.split(" ", 1)[0] in KEYWORDS:
            current.items.append(line)
    return out


def dims(name: str, signature: str) -> list[tuple[int, int]]:
    """A declaration's dimensions in select order: unpacked after the name, then packed."""
    at = signature.rfind(name)
    if at < 0:
        return []
    packed = signature[:at].rsplit(" ", 1)[-1] if " " in signature[:at] else signature[:at]
    unpacked = signature[at + len(name) :]
    out = []
    for group in (unpacked, packed):
        for a, b in DIMS.findall(group):
            hi, lo = int(a), int(b if b else a)
            out.append((min(hi, lo), max(hi, lo)))
    return out


def select_fits(name: str, select: str, signature: str) -> bool:
    """Whether every index of a bit or part select lies inside the declaration."""
    groups = DIMS.findall(select)
    declared = dims(name, signature)
    if not groups or len(groups) > len(declared):
        return False
    for (a, b), (lo, hi) in zip(groups, declared, strict=False):
        for v in (int(a), int(b if b else a)):
            if not lo <= v <= hi:
                return False
    return True


def norm(text: str) -> str:
    return SPACE.sub("", text)


class Scope:
    """The objects urg's templates report for one module section or instance."""

    def __init__(self, module: str | None) -> None:
        self.module = module
        self.checksum: dict[str, str] = {}
        self.order: dict[str, dict[str, int]] = {m: {} for m in METRICS}
        self.signals: dict[str, str] = {}
        self.children: dict[str, list[str]] = defaultdict(list)
        self.blocks: dict[str, str] = {}
        self.block_text: dict[str, list[str]] = defaultdict(list)
        self.fsms: dict[str, tuple[str, dict[str, str]]] = {}
        self.cond_rows: dict[tuple[str, str | None], str] = {}
        self.cond_text: dict[tuple[str, str | None], list[str]] = defaultdict(list)

    def add(self, metric: str, checksum: str, items: list[str]) -> None:
        self.checksum[metric] = checksum
        order = self.order[metric]
        fsm: str | None = None
        for item in items:
            order.setdefault(item, len(order))
            if metric == "tgl":
                m = TOGGLE.match(item)
                if m and not m.group(1) and not m.group(3):
                    name, signature = m.group(2), m.group(4)
                    self.signals[name] = signature
                    for cut in range(len(name)):
                        if name[cut] in ".[" and cut:
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
                    table[sec.scope].add(metric, sec.checksum, sec.items)
        self.normal: dict[tuple[str, ...], list[str]] = defaultdict(list)
        for path in self.instances:
            self.normal[normal(path)].append(path)

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

    def gone(self, module: str | None) -> str:
        """Why the database holds no section for a module."""
        return "module-out-of-scope" if module in self.dropped else "module-not-built"


def normal(path: str) -> tuple[str, ...]:
    """A path's components without the `u_`/`i_` prefix and without unindexed generate blocks."""
    return tuple(PREFIX.sub("", c) for c in path.split(".") if not GENERATE.match(c))


def map_toggle(scope: Scope, item: str) -> tuple[list[str], str]:
    m = TOGGLE.match(item)
    if not m:
        return [], "unparsed"
    direction, name, select, legacy_signature = m.groups()
    prefix = f"Toggle {direction} " if direction else "Toggle "
    renamed, how = PORT.sub(r"\2_\1", name, count=1), "signal"
    if name not in scope.signals and name not in scope.children and renamed != name:
        if renamed in scope.signals or renamed in scope.children:
            name, how = renamed, "renamed-port"
    signature = scope.signals.get(name)
    if signature is None:
        children = scope.children.get(name)
        if children and not select:
            return [f'{prefix}{c} "{scope.signals[c]}"' for c in children], f"{how}-fields"
        return [], "signal-gone"
    if select:
        if not select_fits(name, select, signature):
            return [], "select-out-of-range"
        return [f'{prefix}{name} {select} "{signature}"'], how
    if how == "signal" and legacy_signature != signature:
        how = "signal-resized"
    return [f'{prefix}{name} "{signature}"'], how


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
    """The entries to write, by scope, metric, legacy file and template order."""

    entries: dict[tuple[str, str, str], dict[str, set[str]]] = field(
        default_factory=lambda: defaultdict(lambda: defaultdict(set))
    )
    owner: dict[tuple[str, str, str, str], str] = field(default_factory=dict)
    stats: Counter = field(default_factory=Counter)
    unmapped: dict[str, Counter] = field(default_factory=lambda: defaultdict(Counter))

    def add(self, kind: str, scope: str, metric: str, name: str, entry: str) -> bool:
        key = (kind, scope, metric, entry)
        if key in self.owner:
            return False
        self.owner[key] = name
        self.entries[(kind, scope, metric)][name].add(entry)
        return True


def map_section(db: Database, plan: Plan, name: str, sec: Section) -> None:
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
        live = [t for k, s, sc in targets if metric in sc.checksum for t in db.split(k, s, metric)]
        if not live:
            plan.unmapped[f"{name}\t{metric}"][reason if not targets else "metric-gone"] += len(
                items
            )
            continue
        if metric == "fsm":
            map_fsm(db, plan, name, live, items)
            continue
        mapper = {"tgl": map_toggle, "line": map_block, "cond": map_cond}[metric]
        for item in items:
            for kind, scope, sc in live:
                mapped, how = mapper(sc, item)
                if not mapped:
                    plan.unmapped[f"{name}\t{metric}"][how] += 1
                    continue
                plan.stats[f"{name}\t{metric}\tmapped-by-{how}"] += 1
                for entry in mapped:
                    if kind == "INSTANCE" and module_has(db, plan, sc.module, metric, entry):
                        plan.stats[f"{name}\t{metric}\tinstance-entry-under-module"] += 1
                        continue
                    if plan.add(kind, scope, metric, name, entry):
                        plan.stats[f"{name}\t{metric}\tentries"] += 1


def module_has(db: Database, plan: Plan, module: str | None, metric: str, entry: str) -> bool:
    """Whether a MODULE-scope entry of the instance's module already excludes this entry."""
    if module is None:
        return False
    return any(("MODULE", s, metric, entry) in plan.owner for s in db.by_name.get(module, []))


def map_fsm(db: Database, plan: Plan, name: str, live, items: list[str]) -> None:
    fsm: str | None = None
    for item in items:
        m = FSM.match(item)
        if m:
            fsm = m.group(1)
            continue
        m = STATE.match(item)
        if not m or fsm is None:
            plan.unmapped[f"{name}\tfsm"]["unparsed"] += 1
            continue
        key = f"{m.group(1)} {m.group(2)}"
        for kind, scope, sc in live:
            if fsm not in sc.fsms:
                plan.unmapped[f"{name}\tfsm"]["fsm-gone"] += 1
                continue
            header, members = sc.fsms[fsm]
            if key not in members:
                plan.unmapped[f"{name}\tfsm"][f"{m.group(1).lower()}-gone"] += 1
                continue
            plan.stats[f"{name}\tfsm\tmapped-by-name"] += 1
            entry = f"{header}\n{members[key]}"
            if kind == "INSTANCE" and module_has(db, plan, sc.module, "fsm", entry):
                plan.stats[f"{name}\tfsm\tinstance-entry-under-module"] += 1
                continue
            if plan.add(kind, scope, "fsm", name, entry):
                plan.stats[f"{name}\tfsm\tentries"] += 1


def build(legacy_dir: Path, db: Database) -> Plan:
    plan = Plan()
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
    # MODULE scope first, so an instance entry its module already carries is not repeated.
    for name, sec in sections:
        if sec.kind == "MODULE":
            map_section(db, plan, name, sec)
    for name, sec in sections:
        if sec.kind == "INSTANCE":
            map_section(db, plan, name, sec)
    return plan


def render(plan: Plan, db: Database) -> str:
    out = [
        "// SPDX-License-Identifier: Apache-2.0",
        "// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.",
        "//==================================================",
        "// SMC VCS coverage exclusions -- L1 LEGACY-DE-APPROVED.",
        "// Format Version: 2",
        "// ExclMode: default",
        "//",
        "// Generated by gen_smc_legacy_exclusions.py from urg's full_exclusions",
        "// templates of the merged database and the SMC exclusion files of the archived",
        f"// {LEGACY_REPO} repository at commit {LEGACY_COMMIT}, {LEGACY_PATH}/:",
        *(f"//   {name}" for name in LEGACY_FILES),
        "// Design engineering reviewed those files in that repository. Each object is",
        "// mapped onto this bench's hierarchy and written only where the database holds",
        "// it, with the template's checksum and text; regenerate rather than edit.",
        "// README.md states the class; the ANNOTATION before each group names the file.",
        "//==================================================",
    ]
    for kind, scope, metric in sorted(plan.entries, key=lambda k: (k[2], k[0], k[1])):
        sc = (db.modules if kind == "MODULE" else db.instances)[scope]
        order = sc.order[metric]
        out += ["", f"CHECKSUM: {sc.checksum[metric]}", f"{kind}: {scope}"]
        files = plan.entries[(kind, scope, metric)]
        for name in LEGACY_FILES:
            if name not in files:
                continue
            out.append(annotation(name))
            rows = sorted(
                files[name], key=lambda e: ([order.get(x, 1 << 30) for x in e.split("\n")], e)
            )
            if metric == "fsm":
                last = None
                for row in rows:
                    header, member = row.split("\n")
                    if header != last:
                        out.append(header)
                        last = header
                    out.append(member)
            else:
                out += rows
    return "\n".join(out) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("legacy_dir", type=Path, help=f"{LEGACY_PATH} of {LEGACY_REPO}")
    ap.add_argument(
        "template_dir", type=Path, help="holds fullexclude{,_module}.{tgl,line,fsm,cond}"
    )
    ap.add_argument("--check", action="store_true", help="fail if the committed file is stale")
    ap.add_argument("--stats", type=Path, help="write mapping counts, by file and reason, as JSON")
    args = ap.parse_args()
    db = Database(args.template_dir)
    plan = build(args.legacy_dir, db)
    text = render(plan, db)
    if args.stats:
        args.stats.write_text(
            json.dumps(
                {"mapped": dict(sorted(plan.stats.items())), "unmapped": plan.unmapped},
                indent=1,
                sort_keys=True,
            )
        )
    if args.check:
        if not OUT.is_file() or OUT.read_text() != text:
            print(f"{OUT} is stale; rerun without --check", file=sys.stderr)
            return 1
        print(f"{OUT} is current")
        return 0
    OUT.write_text(text)
    counts = Counter(
        m for (_, _, m), files in plan.entries.items() for f in files.values() for _ in f
    )
    print(f"wrote {OUT.name}: " + ", ".join(f"{m} {counts[m]}" for m in METRICS))
    return 0


if __name__ == "__main__":
    sys.exit(main())
