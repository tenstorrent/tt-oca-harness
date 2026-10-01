#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Write the SMC toggle exclusions whose classes name whole signals or bit windows.

smc_toggle_module_exclusions.el holds the rows that hold for every instance of
a module, smc_toggle_instance_exclusions.el the rows that hold for one
instance. smc_toggle_exclusions.py plans both and README.md states every class,
its fact and its granularity: T1 OPENTITAN-PORTS-ONLY and the ports-only units
T2 to T12 of smc_reviewed_exclusions.toml, UNION-ALIAS, EFUSE-IMAGE-COPY,
EFUSE-FIELD-MAP-CONST, VERSION-ID-CONST, ATOP-ZERO, EXT-IRQ-TIED and
PARTIAL-VECTOR.

Every checksum and signature comes from urg's templates; the run's raw report
gives the unit roots' port lists and the bit-directions the run leaves
uncovered, the only ones written, so the files belong to that graded run::

    urg -dir <run dir>/cov/merged.vdb -dump full_exclusions tgl+line+fsm+cond+branch \
        -report <dir>
    python3 gen_smc_toggle_exclusions.py <dir> <run dir>/cov/report_raw/modinfo.txt
    python3 gen_smc_toggle_exclusions.py <dir> <modinfo> --check

A T1 unit the database does not hold, because the build did not elaborate it,
contributes nothing and is named on stderr as skipped.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import smc_toggle_exclusions as toggles


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("template_dir", type=Path, help="holds the fullexclude templates")
    ap.add_argument("modinfo", type=Path, help="the run's cov/report_raw/modinfo.txt")
    ap.add_argument("--check", action="store_true", help="fail if the committed files are stale")
    args = ap.parse_args()
    planner, _ = toggles.plan(args.template_dir, args.modinfo)
    for module in planner.absent:
        print(f"skipped {module}: the database has no MODULE {module}", file=sys.stderr)
    outputs = []
    summary = []
    for kind, path in (("MODULE", toggles.MODULE_OUT), ("INSTANCE", toggles.INSTANCE_OUT)):
        text, counts = toggles.text(planner, kind)
        outputs.append((path, text))
        summary.append(
            f"{path.name}: {sum(counts.values())} rows ("
            + ", ".join(f"{k} {v}" for k, v in sorted(counts.items()))
            + ")"
        )
    if args.check:
        stale = [p for p, t in outputs if not p.is_file() or p.read_text() != t]
        for p in stale:
            print(f"{p} is stale; rerun without --check", file=sys.stderr)
        return 1 if stale else 0
    for p, t in outputs:
        p.write_text(t)
    print("wrote " + "; ".join(summary))
    return 0


if __name__ == "__main__":
    sys.exit(main())
