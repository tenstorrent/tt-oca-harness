#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

"""
Render status badges from the published dashboard summary.

Each badge is fetched from shields.io and stored beside the dashboard data::

    badge-dtp-status.svg      passing / failing / no data
    badge-dtp-tests.svg       the test pass rate
    badge-dtp-coverage.svg    total coverage

A badge that cannot be fetched leaves the previous one in place.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlencode

BADGE_URL = "https://img.shields.io/badge/"
TIMEOUT_S = 10

# shields.io rejects the default urllib agent.
USER_AGENT = "tt-oca-harness-doc-build (+https://github.com/tenstorrent/tt-oca-harness)"

# Colours and thresholds mirror the styles in doc/ui-supplemental/.
GREEN = "#3A863D"
AMBER = "#f6c343"
RED = "#C55050"
GREY = "#9f9f9f"

PASS_AT = 95.0
WARN_AT = 70.0

# Statuses reporting no verdict, banded grey rather than as a failure.
UNMEASURED = {"", "SKIP", "NOTRUN"}

# A flow names a file, so it is restricted rather than escaped.
FLOW = re.compile(r"^[A-Za-z_]+$")


def percent(value: Any) -> float | None:
    """
    Read a percentage from the summary.

    Args:
        value: The published value, of any type

    Returns:
        The percentage, or None when it is absent or not a number
    """
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def measure(value: float | None) -> str:
    """
    Render a percentage as badge text.

    Args:
        value: The percentage, or None when the run measured none

    Returns:
        The rounded percentage, or "no data"
    """
    return f"{round(value, 1)} %" if value is not None else "no data"


def band(value: float | None) -> str:
    """
    Pick the badge colour for a percentage.

    Args:
        value: Percentage between 0 and 100, or None when unmeasured

    Returns:
        A hex colour string
    """
    if value is None:
        return GREY
    if value >= PASS_AT:
        return GREEN
    if value >= WARN_AT:
        return AMBER
    return RED


def fetch(label: str, message: str, colour: str) -> bytes | None:
    """
    Fetch one badge from shields.io.

    Args:
        label: Left-hand panel text
        message: Right-hand panel text
        colour: Right-hand panel background, as a hex string

    Returns:
        The SVG document, or None when it cannot be fetched
    """
    # shields.io splits the path on "-" and renders "_" as a space, so a
    # literal one of either is written twice. The label is a query parameter
    # and is taken as it stands.
    literal = message.replace("-", "--").replace("_", "__")
    url = BADGE_URL + quote(f"{literal}-{colour.lstrip('#')}") + "?" + urlencode({"label": label})
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_S) as response:
            return bytes(response.read())
    except (urllib.error.URLError, OSError, ValueError) as error:
        print(f"warning: cannot fetch {label} badge: {error}", file=sys.stderr)
        return None


def badges_for(
    dut: dict[str, Any], coverage: dict[str, Any] | None
) -> dict[str, tuple[str, str, str]]:
    """
    Build the badge set for one block.

    Args:
        dut: A dut_status entry from the published summary
        coverage: The matching results[].coverage entry, if any

    Returns:
        Mapping of badge kind to its (label, message, colour)
    """
    status = str(dut.get("status") or "").upper()
    rate = percent(dut.get("pass_rate"))
    total = percent((coverage or {}).get("total_percent"))

    if status == "PASS":
        state, colour = "passing", GREEN
    elif status in UNMEASURED:
        state, colour = status.lower() or "no data", GREY
    else:
        state, colour = status.lower(), RED

    return {
        "status": (str(dut.get("flow") or "block"), state, colour),
        "tests": ("tests", measure(rate), band(rate)),
        "coverage": ("coverage", measure(total), band(total)),
    }


def main() -> int:
    """
    Read the published summary and write one badge set per block.

    Returns:
        0 on success, 1 when the summary is unreadable
    """
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("source", type=Path, help="published summary.json")
    parser.add_argument("outdir", type=Path, help="directory to write badges into")
    args = parser.parse_args()

    try:
        summary = json.loads(args.source.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        print(f"error: cannot read {args.source}: {error}", file=sys.stderr)
        return 1

    coverage_by_flow = {
        result["flow"]: result.get("coverage")
        for result in summary.get("results") or []
        if isinstance(result, dict) and result.get("flow")
    }

    args.outdir.mkdir(parents=True, exist_ok=True)
    intended: set[Path] = set()
    fetched = 0
    for dut in summary.get("dut_status") or []:
        if not isinstance(dut, dict) or not dut.get("flow"):
            continue
        flow = str(dut["flow"])
        if not FLOW.match(flow):
            print(f"warning: skipping badges for {flow!r}", file=sys.stderr)
            continue
        for kind, (label, message, colour) in badges_for(dut, coverage_by_flow.get(flow)).items():
            path = args.outdir / f"badge-{flow}-{kind}.svg"
            # Intended before the fetch, so a failed fetch keeps the existing file.
            intended.add(path)
            svg = fetch(label, message, colour)
            if svg is None:
                continue
            path.write_bytes(svg)
            fetched += 1

    # Badges left by an earlier run, for blocks this summary no longer has.
    dropped = [path for path in args.outdir.glob("badge-*.svg") if path not in intended]
    for path in dropped:
        path.unlink()

    print(f"Fetched {fetched} badges into {args.outdir}/, removed {len(dropped)} stale")
    if fetched < len(intended):
        print(
            f"warning: {len(intended) - fetched} of {len(intended)} badges unavailable; "
            "any previously fetched copy is still in place",
            file=sys.stderr,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
