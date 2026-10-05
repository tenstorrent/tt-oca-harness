#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Write the owning-tests table of a DUT's functional-coverage points from a finished run.

A cover property in `cov/sv` records that an event happened; which leaf made it
happen is a property of a run, not of the source. This tool reads every leaf's
native coverage database under a finished `run_dv.py --cov` run directory,
attributes each `user` point to the leaves whose database counts it, and writes
an AsciiDoc table per coverage module: the point, how many leaves reach it, the
leaf that reaches it most, and the policy disposition of a point no leaf
reaches. The table is the measured form of the owning-tests rule SEP states in
its coverage plan: a hole is not gradable without knowing which test was
supposed to fill it, and a point one leaf alone reaches is a dependency worth
naming.

    python3 tools/dv/fcov_owners.py --dut smc --run-dir <run dir> --output <adoc>
    python3 tools/dv/fcov_owners.py --dut smc --run-dir <run dir> --output <adoc> --check

Only Verilator databases are read: the per-leaf `coverage.dat` files, which are
the runner's own inputs to the merge stage.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from runlib.coverage_parsers.verilator import parse_verilator_details  # noqa: E402

SINGLE_OWNER_MARK = "single"


@dataclass
class PointOwners:
    hierarchy: str
    hits: dict[str, int] = field(default_factory=dict)  # leaf -> count over its seeds
    disposition: str | None = None
    category: str | None = None

    @property
    def module(self) -> str:
        parts = self.hierarchy.split(".")
        return parts[1] if len(parts) > 2 else parts[0]

    @property
    def name(self) -> str:
        parts = self.hierarchy.split(".")
        return ".".join(parts[2:]).replace("__DOT__", ".")

    @property
    def owner(self) -> tuple[str, int] | None:
        if not self.hits:
            return None
        return max(self.hits.items(), key=lambda item: (item[1], item[0]))


def attribute(counts_by_leaf: dict[str, dict[str, int]]) -> dict[str, PointOwners]:
    """Fold per-leaf `{hierarchy: count}` maps into one PointOwners per point."""
    points: dict[str, PointOwners] = {}
    for leaf, counts in sorted(counts_by_leaf.items()):
        for hierarchy, count in counts.items():
            point = points.setdefault(hierarchy, PointOwners(hierarchy))
            if count > 0:
                point.hits[leaf] = point.hits.get(leaf, 0) + count
    return points


def read_run(run_dir: Path, dut: str) -> tuple[dict[str, dict[str, int]], dict]:
    """Per-leaf user-point counts and the run's result.json."""
    result = json.loads((run_dir / "result.json").read_text(encoding="utf-8"))
    counts_by_leaf: dict[str, dict[str, int]] = defaultdict(dict)
    for path in sorted(run_dir.glob("*/seed_*/attempt_*/coverage/coverage.dat")):
        leaf = path.parents[3].name
        details = parse_verilator_details(
            dut=dut, tool="verilator", target=None, build_fingerprint=None, merged=path
        )
        for observation in details.observations:
            if observation.metric_family != "user" or observation.hierarchy is None:
                continue
            current = counts_by_leaf[leaf].get(observation.hierarchy, 0)
            counts_by_leaf[leaf][observation.hierarchy] = current + observation.count
    if not counts_by_leaf:
        sys.exit(f"{run_dir}: no leaf coverage.dat found; was the run made with --cov?")
    return counts_by_leaf, result


def apply_policy(points: dict[str, PointOwners], result: dict) -> None:
    """Take each unhit point's disposition from the run's coverage-details.json."""
    details_path = result.get("coverage", {}).get("coverage_details")
    if not details_path or not Path(details_path).is_file():
        return
    details = json.loads(Path(details_path).read_text(encoding="utf-8"))
    for observation in details.get("observations", []):
        point = points.get(observation.get("hierarchy") or "")
        if point is not None and observation.get("metric_family") == "user":
            point.disposition = observation.get("disposition")
            point.category = observation.get("category")


def render(points: dict[str, PointOwners], result: dict, dut: str, leaves: int) -> str:
    git = result.get("git", {})
    # The runner records the simulator's full banner; the table names the
    # simulator and its version only.
    simulator = " ".join(str(result.get("tool_version", "Verilator")).split()[:2])
    total = len(points)
    hit = [p for p in points.values() if p.hits]
    single = [p for p in hit if len(p.hits) == 1]
    unhit = total - len(hit)
    out = [
        "// SPDX-License-Identifier: Apache-2.0",
        "// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.",
        "",
        "// Generated by tools/dv/fcov_owners.py from a finished `run_dv.py --cov` run.",
        "// Regenerate rather than edit.",
        "",
        f"[[{dut}-fcov-owners]]",
        "==== Owning tests, measured",
        "",
        f"Measured on `--items {result.get('label', 'all')}` at commit "
        f"`{str(git.get('commit', ''))[:12]}` with {simulator}: "
        f"{leaves} leaves, {total} points, {len(hit)} hit, {unhit} unhit, "
        f"{len(single)} hit by exactly one leaf.",
        "",
        "A point one leaf alone reaches depends on that leaf: retire or narrow it and",
        "the point goes dark. A point no leaf reaches carries its policy disposition,",
        "or `unclassified` when the policy has none.",
        "",
    ]
    by_module: dict[str, list[PointOwners]] = defaultdict(list)
    for point in points.values():
        by_module[point.module].append(point)
    for module in sorted(by_module):
        out += [
            f"===== `{module}`",
            "",
            '[cols="4,1,4,2",options="header",]',
            "|===",
            "|Point |Leaves |Owner (hits) |Note",
        ]
        for point in sorted(by_module[module], key=lambda p: p.name):
            owner = point.owner
            if owner is None:
                disposition = point.disposition or "unclassified"
                note = disposition if point.category is None else f"{disposition}: {point.category}"
                out.append(f"|`{point.name}` |0 |none |{note}")
            else:
                note = SINGLE_OWNER_MARK if len(point.hits) == 1 else ""
                out.append(f"|`{point.name}` |{len(point.hits)} |`{owner[0]}` ({owner[1]}) |{note}")
        out += ["|===", ""]
    return "\n".join(out)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dut", required=True)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--check", action="store_true", help="fail if the file is stale")
    args = parser.parse_args()
    counts_by_leaf, result = read_run(args.run_dir, args.dut)
    points = attribute(counts_by_leaf)
    apply_policy(points, result)
    text = render(points, result, args.dut, len(counts_by_leaf))
    if args.check:
        if not args.output.is_file() or args.output.read_text(encoding="utf-8") != text:
            print(f"{args.output} is stale; rerun without --check", file=sys.stderr)
            return 1
        print(f"{args.output} is current")
        return 0
    args.output.write_text(text, encoding="utf-8")
    hit = sum(1 for p in points.values() if p.hits)
    print(f"wrote {args.output}: {len(points)} points, {hit} hit, {len(counts_by_leaf)} leaves")
    return 0


if __name__ == "__main__":
    sys.exit(main())
