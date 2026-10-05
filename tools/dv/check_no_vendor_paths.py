#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
#
# check_no_vendor_paths.py
#
# Scans a Verilog/SystemVerilog filelist (.f file) or a directory tree for
# references to forbidden vendor or foundry paths.  Forbidden prefixes are
# configured in check_no_vendor_paths.yaml (sibling file by default).
#
# Usage:
#   # Scan a single filelist
#   python3 check_no_vendor_paths.py --filelist path/to/compile.f
#
#   # Recursively scan a directory tree
#   python3 check_no_vendor_paths.py --scan-dir hw/
#
#   # Quiet mode (CI): single summary line, exit nonzero on failure
#   python3 check_no_vendor_paths.py --filelist compile.f --quiet
#
#   # Verbose mode: print every file checked
#   python3 check_no_vendor_paths.py --filelist compile.f --verbose
#
#   # Use a named target to apply per-target allowlist overrides
#   python3 check_no_vendor_paths.py --filelist compile.f --target smc
#
# Exit codes:
#   0   All checks passed (no forbidden paths found).
#   1   One or more forbidden paths found.
#   2   Configuration or argument error.

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import NamedTuple

try:
    import yaml  # type: ignore[import]

    _HAS_YAML = True
except ImportError:
    _HAS_YAML = False


# ---------------------------------------------------------------------------
# Default paths (resolved relative to this script's directory)
# ---------------------------------------------------------------------------
_SCRIPT_DIR = Path(__file__).resolve().parent
_DEFAULT_CONFIG = _SCRIPT_DIR / "check_no_vendor_paths.yaml"


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


class ForbiddenPrefix(NamedTuple):
    prefix: str
    description: str


class Violation(NamedTuple):
    path: str  # The forbidden path token found
    matched_prefix: str
    source_file: str  # Filelist or source file that contained this token
    source_line: int  # 1-based line number in source_file


# ---------------------------------------------------------------------------
# Config loading
# ---------------------------------------------------------------------------


def _load_config(
    config_path: Path, target: str | None
) -> tuple[list[ForbiddenPrefix], list[str], list[str]]:
    """Return (forbidden_prefixes, allowed_prefixes, checked_extensions)."""
    if not config_path.exists():
        _die(f"Config file not found: {config_path}")

    raw: dict = {}
    if _HAS_YAML:
        with config_path.open() as fh:
            raw = yaml.safe_load(fh) or {}
    else:
        # Fallback parser: handles only the list-of-dicts shape of check_no_vendor_paths.yaml.
        raw = _minimal_yaml_load(config_path)

    forbidden: list[ForbiddenPrefix] = []
    for entry in raw.get("forbidden_prefixes", []):
        forbidden.append(
            ForbiddenPrefix(
                prefix=entry["prefix"],
                description=entry.get("description", ""),
            )
        )

    # Build per-target allowlist
    allowed: list[str] = []
    if target:
        for tgt_entry in raw.get("per_target_allowlist", []) or []:
            if isinstance(tgt_entry, dict) and tgt_entry.get("target") == target:
                allowed.extend(tgt_entry.get("allow", []))

    extensions: list[str] = raw.get(
        "checked_extensions",
        [
            ".sv",
            ".v",
            ".vp",
            ".svh",
            ".vh",
        ],
    )
    return forbidden, allowed, extensions


def _minimal_yaml_load(path: Path) -> dict:
    """Extremely minimal YAML loader for the specific config shape."""
    # Handles only the shape of check_no_vendor_paths.yaml; PyYAML is used when importable.
    lines = path.read_text().splitlines()
    result: dict = {
        "forbidden_prefixes": [],
        "per_target_allowlist": [],
        "checked_extensions": [".sv", ".v", ".vp", ".svh", ".vh"],
        "filelist_path_directives": ["+incdir+", "-f ", "-F "],
    }
    current_section: str | None = None
    current_item: dict | None = None

    for line in lines:
        stripped = line.strip()
        if stripped.startswith("#") or not stripped:
            continue

        # Top-level keys
        if not line.startswith(" ") and not line.startswith("\t") and ":" in stripped:
            key, _, rest = stripped.partition(":")
            key = key.strip()
            rest = rest.strip()
            if key in (
                "forbidden_prefixes",
                "per_target_allowlist",
                "checked_extensions",
                "filelist_path_directives",
            ):
                current_section = key
                current_item = None
            continue

        # List items under a section
        if current_section == "forbidden_prefixes" and stripped.startswith("- prefix:"):
            prefix_val = stripped[len("- prefix:") :].strip().strip('"').strip("'")
            current_item = {"prefix": prefix_val, "description": ""}
            result["forbidden_prefixes"].append(current_item)
        elif (
            current_section == "forbidden_prefixes"
            and stripped.startswith("description:")
            and current_item
        ):
            desc = stripped[len("description:") :].strip().strip('"').strip("'")
            current_item["description"] = desc
        elif current_section == "checked_extensions" and stripped.startswith("- "):
            ext = stripped[2:].strip().strip('"').strip("'")
            result["checked_extensions"].append(ext)
        elif current_section == "filelist_path_directives" and stripped.startswith("- "):
            d = stripped[2:].strip().strip('"').strip("'")
            result["filelist_path_directives"].append(d)

    # Deduplicate defaults
    result["checked_extensions"] = list(dict.fromkeys(result["checked_extensions"]))
    return result


# ---------------------------------------------------------------------------
# Filelist parsing
# ---------------------------------------------------------------------------

_FILELIST_PATH_PREFIXES = ("+incdir+", "-f ", "-F ")
_FLAG_PREFIXES = (
    "+define+",
    "-Wno-",
    "--",
    "-sv",
    "-cc",
    "-Wall",
    "+timescale",
    "+librescan",
    "+notimingcheck",
)


def _is_flag_line(token: str) -> bool:
    """Return True if this token looks like a Verilator/VCS flag, not a path."""
    for p in _FLAG_PREFIXES:
        if token.startswith(p):
            return True
    return False


def _extract_path_tokens(line: str) -> list[str]:
    """Extract all path tokens from a single filelist line."""
    stripped = line.strip()
    if not stripped or stripped.startswith("//") or stripped.startswith("#"):
        return []

    tokens: list[str] = []

    # +incdir+<path>[+<path>...]
    if stripped.startswith("+incdir+"):
        rest = stripped[len("+incdir+") :]
        for part in rest.split("+"):
            p = part.strip()
            if p:
                tokens.append(p)
        return tokens

    # -f <path> or -F <path>
    if stripped.startswith(("-f ", "-F ")):
        path_part = stripped[3:].strip()
        if path_part:
            tokens.append(path_part)
        return tokens

    # Plain path (no leading flag)
    if not _is_flag_line(stripped):
        tokens.append(stripped)

    return tokens


def _collect_filelist_paths(
    filelist: Path,
    checked_extensions: list[str],
    visited: set[Path] | None = None,
) -> list[tuple[str, Path, int]]:
    """
    Recursively follow -f directives in a filelist.

    Returns a list of (path_token, source_file, source_line_number) tuples
    for every path token found.  Source tokens are returned only when they
    carry a checked extension; +incdir+ tokens are directories (no source
    extension) and are always returned so a licensed include dir cannot slip
    past the extension filter; -f sub-filelists are followed regardless of
    extension.
    """
    if visited is None:
        visited = set()

    resolved = filelist.resolve()
    if resolved in visited:
        return []
    visited.add(resolved)

    if not resolved.exists():
        return []

    results: list[tuple[str, Path, int]] = []
    lines = resolved.read_text(errors="replace").splitlines()

    for lineno, line in enumerate(lines, start=1):
        line_stripped = line.strip()
        is_incdir = line_stripped.startswith("+incdir+")
        tokens = _extract_path_tokens(line)
        for token in tokens:
            token_path = Path(token)
            # Resolve relative paths against the filelist's directory
            if not token_path.is_absolute():
                token_path = (resolved.parent / token_path).resolve()
                token = str(token_path)

            # Follow sub-filelists regardless of extension
            if line_stripped.startswith(("-f ", "-F ")):
                sub = _collect_filelist_paths(Path(token), checked_extensions, visited)
                results.extend(sub)
            elif is_incdir:
                # +incdir+ tokens are directories (no source extension); check
                # them directly so a licensed include dir cannot slip past the
                # extension filter (e.g. /vendor_ip/synopsys/.../src).
                results.append((token, resolved, lineno))
            elif any(token.endswith(e) for e in checked_extensions):
                results.append((token, resolved, lineno))

    return results


# ---------------------------------------------------------------------------
# Directory scanner
# ---------------------------------------------------------------------------


def _collect_dir_paths(
    scan_dir: Path, checked_extensions: list[str]
) -> list[tuple[str, Path, int]]:
    """Return (path, source_file, 0) for every file in scan_dir with a checked extension."""
    results: list[tuple[str, Path, int]] = []
    for root, _dirs, files in os.walk(scan_dir):
        for fname in files:
            fpath = Path(root) / fname
            if any(fname.endswith(e) for e in checked_extensions):
                results.append((str(fpath.resolve()), fpath, 0))
    return results


# ---------------------------------------------------------------------------
# Violation detection
# ---------------------------------------------------------------------------


def _check_tokens(
    tokens: list[tuple[str, Path, int]],
    forbidden: list[ForbiddenPrefix],
    allowed: list[str],
) -> list[Violation]:
    violations: list[Violation] = []
    for path_token, source_file, source_line in tokens:
        # Check if allowed by per-target override
        if any(path_token.startswith(a) for a in allowed):
            continue
        for fp in forbidden:
            if fp.prefix in path_token:
                violations.append(
                    Violation(
                        path=path_token,
                        matched_prefix=fp.prefix,
                        source_file=str(source_file),
                        source_line=source_line,
                    )
                )
                break  # Report the first matched prefix per token
    return violations


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------


def _report(violations: list[Violation], quiet: bool, verbose: bool) -> None:
    if not violations:
        if not quiet:
            print("PASS: No forbidden vendor paths found.")
        return

    if not quiet:
        print(f"\nFAIL: {len(violations)} forbidden path(s) found.\n")
        for v in violations:
            print(f"  {v.path}")
            print(f"    matched prefix : {v.matched_prefix}")
            if v.source_line:
                print(f"    referenced from: {v.source_file}:{v.source_line}")
            else:
                print(f"    found in       : {v.source_file}")
            print()
    else:
        print(f"FAIL: {len(violations)} forbidden vendor path(s) found in public filelist.")


def _summary_line(violations: list[Violation], quiet: bool) -> None:
    if violations:
        if not quiet:
            print(f"SUMMARY: FAIL — {len(violations)} forbidden vendor path(s) present.")
    else:
        if not quiet:
            print("SUMMARY: PASS — public filelist is free of vendor/foundry paths.")


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------


def _die(msg: str) -> None:
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(2)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Check a Verilog filelist or directory tree for forbidden vendor/foundry path prefixes. "
            "Exit 0 on clean, exit 1 if violations found, exit 2 on usage error."
        )
    )
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument(
        "--filelist",
        metavar="FILE",
        help="Path to a .f filelist to scan (follows -f sub-filelists recursively).",
    )
    source.add_argument(
        "--scan-dir",
        metavar="DIR",
        help="Recursively scan a directory tree for source files with checked extensions.",
    )
    parser.add_argument(
        "--config",
        metavar="FILE",
        default=str(_DEFAULT_CONFIG),
        help="Path to the YAML config file (default: %(default)s).",
    )
    parser.add_argument(
        "--target",
        metavar="TARGET",
        default=None,
        help="Named target for per-target allowlist overrides defined in the config.",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress per-violation detail; print only a summary line. Useful for CI.",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Print every file checked, not just violations.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    config_path = Path(args.config)

    # Load config
    forbidden, allowed, checked_extensions = _load_config(config_path, args.target)
    if not forbidden:
        _die("No forbidden_prefixes found in config. Check the config file.")

    # Collect path tokens
    if args.filelist:
        filelist_path = Path(args.filelist)
        if not filelist_path.exists():
            _die(f"Filelist not found: {filelist_path}")
        tokens = _collect_filelist_paths(filelist_path, checked_extensions)
    else:
        scan_dir = Path(args.scan_dir)
        if not scan_dir.is_dir():
            _die(f"Scan directory not found: {scan_dir}")
        tokens = _collect_dir_paths(scan_dir, checked_extensions)

    if args.verbose and not args.quiet:
        print(
            f"Checking {len(tokens)} path token(s) against {len(forbidden)} forbidden prefix(es)..."
        )
        for path_token, source_file, source_line in tokens:
            loc = f"{source_file}:{source_line}" if source_line else str(source_file)
            print(f"  [check] {path_token}  (from {loc})")

    # Detect violations
    violations = _check_tokens(tokens, forbidden, allowed)

    # Report
    _report(violations, args.quiet, args.verbose)
    _summary_line(violations, args.quiet)

    return 1 if violations else 0


if __name__ == "__main__":
    sys.exit(main())
