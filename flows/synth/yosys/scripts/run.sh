#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

set -euo pipefail

: "${OCAH_YOSYS_SYNTH_TCL:?OCAH_YOSYS_SYNTH_TCL is required}"
: "${TOP_DESIGN:?TOP_DESIGN is required}"
: "${SV_FLIST:?SV_FLIST is required}"
: "${OUT_DIR:?OUT_DIR is required}"
: "${TIMESCALE:?TIMESCALE is required}"

expected_error_files=(${OCAH_SLANG_EXPECTED_ERROR_FILES:-})

if ((${#expected_error_files[@]})); then
  report_dir="$OUT_DIR/reports"
  preflight_log="$report_dir/${PROJ_NAME:-$TOP_DESIGN}_slang_preflight.log"
  mkdir -p "$report_dir"

  set +e
  slang --top "$TOP_DESIGN" --single-unit --allow-use-before-declare \
    --error-limit=0 --timescale="$TIMESCALE" \
    -f "$SV_FLIST" 2>&1 | tee "$preflight_log"
  preflight_status=${PIPESTATUS[0]}
  set -e

  expected_count=0
  pattern_failure=0
  for expected_file in "${expected_error_files[@]}"; do
    while IFS= read -r pattern || [[ -n "$pattern" ]]; do
      [[ -z "$pattern" || "$pattern" == \#* ]] && continue
      ((expected_count += 1))
      match_count=$(grep -Ec -- "$pattern" "$preflight_log" || true)
      if ((match_count != 1)); then
        echo "error: expected one Slang diagnostic matching '$pattern', found $match_count" >&2
        pattern_failure=1
      fi
    done <"$expected_file"
  done

  actual_count=$(grep -Ec ': error: ' "$preflight_log" || true)
  if ((pattern_failure != 0 || actual_count != expected_count)); then
    echo "error: Slang preflight found $actual_count errors; expected $expected_count; see $preflight_log" >&2
    exit 1
  fi
  if ((preflight_status == 0 && actual_count != 0)); then
    echo "error: Slang reported diagnostics without a failing status; see $preflight_log" >&2
    exit 1
  fi
  echo "Slang preflight accepted $actual_count expected errors; see $preflight_log"
fi

# OCAH-Nix provisioned Yosys already loads slang, but from a different path, the
# default -m slang results in a load error
yosys_args=()
[[ -z "${OCAH_YOSYS_BUNDLED_SLANG:-}" ]] && yosys_args+=(-m slang)

exec yosys "${yosys_args[@]}" -c "$OCAH_YOSYS_SYNTH_TCL"
