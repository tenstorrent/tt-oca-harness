#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

# Run the selected native OCAH DV profiles with VCS, normalize every native
# result, and build a data-only dashboard bundle. Regressions intentionally do
# not stop at the first failure: publication completes before this script
# returns the aggregate status.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
readonly SCRIPT_DIR
if [[ -n "${OCAH_ROOT:-}" ]]; then
    resolved_root="$OCAH_ROOT"
else
    resolved_root="$(cd "$SCRIPT_DIR/../../.." && pwd)"
fi
readonly OCAH_ROOT="$resolved_root"
readonly OUT_ROOT="${OCAH_OUT_ROOT:-$OCAH_ROOT/build/jenkins-vcs-dashboard}"
readonly RUNS_DIR="$OUT_ROOT/runs"
readonly DASHBOARD_DIR="$OUT_ROOT/dashboard-data"
readonly STATUS_FILE="$OUT_ROOT/run-status.tsv"
readonly PROFILES_CSV="${PROFILES:-dtp,dtp_uvm,sep,smc_wrapper,smu,smu_wrapper}"
readonly RESEED_COUNT="${RESEED:-1}"
readonly SIM_JOB_COUNT="${SIM_JOBS:-4}"
readonly BUILD_JOB_COUNT="${BUILD_JOBS:-$SIM_JOB_COUNT}"
readonly RETRY_COUNT="${RETRY:-0}"
readonly MAX_FAILURE_COUNT="${MAX_FAILURES:-}"
readonly DRY_RUN_MODE="${DRY_RUN:-false}"
readonly COVERAGE_MODE="${COVERAGE:-true}"
readonly HISTORY_INPUT="${HISTORY_IN:-}"

die() {
    echo "ERROR: $*" >&2
    exit 2
}

require_uint() {
    local name="$1"
    local value="$2"
    local minimum="$3"
    [[ "$value" =~ ^[0-9]+$ ]] ||
        die "$name must be an integer, got '$value'"
    ((10#$value >= minimum)) ||
        die "$name must be >= $minimum, got '$value'"
}

group_for_profile() {
    case "$1" in
        dtp) echo "all" ;;
        dtp_uvm) echo "smoke" ;;
        sep) echo "all" ;;
        smc_wrapper) echo "project_p0_triplets" ;;
        smu) echo "sep0_p4_all" ;;
        smu_wrapper) echo "all" ;;
        *) return 1 ;;
    esac
}

# Coverage follows each flow's stage graph: the native-cocotb profile declares
# cov_merge/cov_report, while native-uvm (dtp_uvm) has none and run_dv.py
# rejects --cov there before any stage executes.
cov_supported_for_profile() {
    case "$1" in
        dtp | sep | smc_wrapper | smu | smu_wrapper) echo "true" ;;
        dtp_uvm) echo "false" ;;
        *) return 1 ;;
    esac
}

trim() {
    local value="$1"
    value="${value#"${value%%[![:space:]]*}"}"
    value="${value%"${value##*[![:space:]]}"}"
    printf '%s' "$value"
}

[[ -f "$OCAH_ROOT/Bender.yml" && -f "$OCAH_ROOT/pyproject.toml" ]] ||
    die "OCAH_ROOT is not a repository root: $OCAH_ROOT"
case "$OUT_ROOT" in
    "" | "/" | "$OCAH_ROOT")
        die "unsafe OCAH_OUT_ROOT: '$OUT_ROOT'"
        ;;
esac

command -v uv >/dev/null 2>&1 || die "uv is required"
command -v python3 >/dev/null 2>&1 || die "python3 is required"

require_uint RESEED "$RESEED_COUNT" 1
require_uint SIM_JOBS "$SIM_JOB_COUNT" 1
require_uint BUILD_JOBS "$BUILD_JOB_COUNT" 1
require_uint RETRY "$RETRY_COUNT" 0
if [[ -n "$MAX_FAILURE_COUNT" ]]; then
    require_uint MAX_FAILURES "$MAX_FAILURE_COUNT" 1
fi
case "$DRY_RUN_MODE" in
    true | false) ;;
    *) die "DRY_RUN must be true or false, got '$DRY_RUN_MODE'" ;;
esac
case "$COVERAGE_MODE" in
    true | false) ;;
    *) die "COVERAGE must be true or false, got '$COVERAGE_MODE'" ;;
esac

IFS=',' read -r -a raw_profiles <<<"$PROFILES_CSV"
profiles=()
seen=","
for raw_profile in "${raw_profiles[@]}"; do
    profile="$(trim "$raw_profile")"
    [[ -n "$profile" ]] || die "PROFILES contains an empty entry"
    group_for_profile "$profile" >/dev/null ||
        die "unsupported profile '$profile'"
    [[ "$seen" != *",$profile,"* ]] ||
        die "duplicate profile '$profile'"
    profiles+=("$profile")
    seen+="$profile,"
done
((${#profiles[@]} > 0)) || die "PROFILES selected no profiles"

rm -rf "$RUNS_DIR" "$DASHBOARD_DIR"
mkdir -p "$RUNS_DIR" "$DASHBOARD_DIR"
printf 'profile\tgroup\trunner_rc\tcollector_rc\trun_dir\n' >"$STATUS_FILE"

cd "$OCAH_ROOT" || die "cannot enter repository root"

overall_rc=0
for profile in "${profiles[@]}"; do
    group="$(group_for_profile "$profile")" ||
        die "no group mapping for '$profile'"
    run_dir="$RUNS_DIR/$profile"
    runner=(
        python3 tools/dv/run_dv.py
        --dut "$profile"
        --items "$group"
        --tool vcs
        --regress
        --reseed "$RESEED_COUNT"
        --sim-jobs "$SIM_JOB_COUNT"
        --build-jobs "$BUILD_JOB_COUNT"
        --retry "$RETRY_COUNT"
        --run-dir "$run_dir"
        --ui plain
    )
    if [[ -n "$MAX_FAILURE_COUNT" ]]; then
        runner+=(--max-failures "$MAX_FAILURE_COUNT")
    fi
    if [[ "$COVERAGE_MODE" == "true" &&
        "$(cov_supported_for_profile "$profile")" == "true" ]]; then
        runner+=(--cov)
    fi
    if [[ "$DRY_RUN_MODE" == "true" ]]; then
        runner+=(--dry-run)
    fi

    echo
    echo "=== VCS profile=$profile group=$group ==="
    if "${runner[@]}"; then
        runner_rc=0
    else
        runner_rc=$?
    fi
    ((runner_rc == 0)) || overall_rc=1

    if [[ "$DRY_RUN_MODE" == "true" ]]; then
        printf '%s\t%s\t%d\t%s\t%s\n' \
            "$profile" "$group" "$runner_rc" "-" "$run_dir" >>"$STATUS_FILE"
        continue
    fi

    normalized="$DASHBOARD_DIR/$profile.result.json"
    if uv run --project "$OCAH_ROOT" --locked --group dv \
        python tools/dv/run_dashboard.py collect \
            --dut "$profile" \
            --run-dir "$run_dir" \
            --output "$normalized"; then
        collector_rc=0
    else
        collector_rc=$?
    fi
    ((collector_rc == 0)) || overall_rc=1
    printf '%s\t%s\t%d\t%d\t%s\n' \
        "$profile" "$group" "$runner_rc" "$collector_rc" "$run_dir" \
        >>"$STATUS_FILE"
done

if [[ "$DRY_RUN_MODE" == "true" ]]; then
    if ((overall_rc != 0)); then
        echo "One or more VCS dry-runs failed." >&2
    else
        echo "All ${#profiles[@]} VCS profile/group dry-runs resolved."
    fi
    exit "$overall_rc"
fi

dashboard=(
    uv run --project "$OCAH_ROOT" --locked --group dv
    python tools/dv/run_dashboard.py dashboard
    --results "$DASHBOARD_DIR/*.result.json"
    --summary-out "$DASHBOARD_DIR/summary.json"
    --history-out "$DASHBOARD_DIR/history.json"
)
if [[ -n "$HISTORY_INPUT" && -f "$HISTORY_INPUT" ]]; then
    dashboard+=(--history-in "$HISTORY_INPUT")
fi

if "${dashboard[@]}"; then
    dashboard_rc=0
else
    dashboard_rc=$?
fi
((dashboard_rc == 0)) || overall_rc=1

if uv run --project "$OCAH_ROOT" --locked --group dv python - \
    "$STATUS_FILE" \
    "$DASHBOARD_DIR" \
    "$dashboard_rc" \
    "${profiles[@]}" <<'PY'
from __future__ import annotations

import csv
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


status_path = Path(sys.argv[1]).resolve()
dashboard_dir = Path(sys.argv[2]).resolve()
dashboard_rc = int(sys.argv[3])
expected_profiles = sys.argv[4:]


def load_json(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


rows: list[dict[str, object]] = []
with status_path.open(newline="", encoding="utf-8") as stream:
    for row in csv.DictReader(stream, delimiter="\t"):
        run_dir = Path(row["run_dir"]).resolve()
        native_path = run_dir / "result.json"
        normalized_path = dashboard_dir / f"{row['profile']}.result.json"
        native = load_json(native_path)
        normalized = load_json(normalized_path)
        rows.append(
            {
                "profile": row["profile"],
                "group": row["group"],
                "tool": "vcs",
                "runner_rc": int(row["runner_rc"]),
                "collector_rc": int(row["collector_rc"]),
                "run_dir": str(run_dir),
                "native_result": str(native_path),
                "native_status": native.get("status", "MISSING"),
                "normalized_result": str(normalized_path),
                "normalized_status": normalized.get("status", "MISSING"),
            }
        )

summary_path = dashboard_dir / "summary.json"
history_path = dashboard_dir / "history.json"
summary = load_json(summary_path)
history = load_json(history_path)
actual_profiles = [str(result.get("flow", "")) for result in summary.get("results", [])]
errors: list[str] = []

if dashboard_rc != 0:
    errors.append(f"dashboard command returned {dashboard_rc}")
if len(rows) != len(expected_profiles):
    errors.append(f"status rows={len(rows)} expected={len(expected_profiles)}")
if set(actual_profiles) != set(expected_profiles):
    errors.append(
        f"summary flows={sorted(actual_profiles)} "
        f"expected={sorted(expected_profiles)}"
    )
if int((summary.get("flows") or {}).get("total") or 0) != len(expected_profiles):
    errors.append("summary flow count does not match the selected matrix")
if not isinstance(history.get("points"), list) or not history["points"]:
    errors.append("history contains no trend point")

for row in rows:
    if row["runner_rc"] != 0:
        errors.append(f"{row['profile']}: runner rc={row['runner_rc']}")
    if row["collector_rc"] != 0:
        errors.append(f"{row['profile']}: collector rc={row['collector_rc']}")
    if row["native_status"] != "PASS":
        errors.append(
            f"{row['profile']}: native status={row['native_status']}"
        )
    if row["normalized_status"] != "PASS":
        errors.append(
            f"{row['profile']}: normalized status={row['normalized_status']}"
        )

try:
    commit = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], text=True
    ).strip()
except (OSError, subprocess.CalledProcessError):
    commit = ""

manifest = {
    "schema_version": 1,
    "generated_at": datetime.now(timezone.utc).isoformat(),
    "git": {
        "commit": commit,
        "requested_ref": os.environ.get("OCAH_GIT_REF", ""),
    },
    "jenkins": {
        "job_name": os.environ.get("JOB_NAME", ""),
        "job_url": os.environ.get("JOB_URL", ""),
        "build_number": os.environ.get("BUILD_NUMBER", ""),
        "build_url": os.environ.get("BUILD_URL", ""),
    },
    "matrix": rows,
    "aggregate": {
        "summary": str(summary_path),
        "history": str(history_path),
        "flows": summary.get("flows", {}),
        "tests": summary.get("tests", {}),
        "history_points": len(history.get("points") or []),
    },
    "status": "PASS" if not errors else "FAIL",
    "errors": errors,
}
(dashboard_dir / "manifest.json").write_text(
    json.dumps(manifest, indent=2, sort_keys=True) + "\n",
    encoding="utf-8",
)

if errors:
    for error in errors:
        print(f"ERROR: {error}", file=sys.stderr)
    raise SystemExit(1)

print(
    f"Dashboard data PASS: flows={len(expected_profiles)} "
    f"history_points={len(history['points'])}"
)
PY
then
    manifest_rc=0
else
    manifest_rc=$?
fi
((manifest_rc == 0)) || overall_rc=1

if ((overall_rc != 0)); then
    echo "VCS regression dashboard completed with non-passing evidence." >&2
else
    echo "VCS regression dashboard PASS: $DASHBOARD_DIR"
fi
exit "$overall_rc"
