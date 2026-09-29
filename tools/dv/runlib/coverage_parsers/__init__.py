# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

"""Backend-specific detailed coverage report parsers."""

from __future__ import annotations

from pathlib import Path

from ..coverage_model import CoverageDetails
from .imc import parse_imc_details
from .urg import parse_urg_details
from .verilator import parse_verilator_details


def parse_coverage_details(
    *,
    parser: str,
    dut: str,
    tool: str,
    target: str | None,
    build_fingerprint: str | None,
    report_dir: Path,
    merged: Path,
    log_path: Path | None = None,
    raw_report_dir: Path | None = None,
) -> CoverageDetails:
    common = {
        "dut": dut,
        "tool": tool,
        "target": target,
        "build_fingerprint": build_fingerprint,
    }
    if parser == "verilator":
        return parse_verilator_details(merged=merged, **common)
    if parser == "urg":
        return parse_urg_details(
            report_dir=report_dir,
            log_path=log_path,
            raw_report_dir=raw_report_dir,
            **common,
        )
    if parser == "imc":
        return parse_imc_details(
            report_dir=report_dir,
            log_path=log_path,
            **common,
        )
    return CoverageDetails(
        details_available=False,
        warnings=[f"no detailed coverage parser is registered for `{parser}`"],
        **common,
    )
