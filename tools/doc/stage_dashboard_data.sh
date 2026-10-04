#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

# Fetch the published dashboard summary and stage a trimmed copy into a built
# site, for doc/trm/src/dashboard.adoc to fetch at page load.
#
#   stage_dashboard_data.sh              fetch only, into OCAH_DASHBOARD_DATA_DIR
#   stage_dashboard_data.sh <site-root>  fetch if needed, then trim into the site
#
# Missing data is a warning, never an error: a doc build must not fail because
# a run did not publish.
#
# Env: OCAH_ROOT                    repository root (default: this script's repo)
#      OCAH_DASHBOARD_DATA_DIR      where the published data is cached
#      OCAH_DASHBOARD_DATA_REF      git ref carrying the data branch
#      OCAH_DASHBOARD_PUBLISHERS    directory within that ref holding one
#                                   subdirectory per publisher
#      OCAH_DASHBOARD_RUNS_LIMIT    newest N archives to aggregate (0 = all)
set -euo pipefail

root="${OCAH_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd -P)}"
data_dir="${OCAH_DASHBOARD_DATA_DIR:-$root/doc/_build/dashboard-data}"
ref="${OCAH_DASHBOARD_DATA_REF:-origin/dv-dashboard-data}"
publishers="${OCAH_DASHBOARD_PUBLISHERS:-vcs}"
runs_limit="${OCAH_DASHBOARD_RUNS_LIMIT:-0}"
site="${1:-}"

trim="$root/tools/doc/trim_dashboard_data.py"
summary="$data_dir/summary.json"
history="$data_dir/history.json"

# Each publisher keeps its own directory, holding the same latest/ and data/
# layout, and reports one series. Every one found is staged.
mapfile -t configs < <(git -C "$root" ls-tree --name-only "$ref" "$publishers/" 2>/dev/null |
  sed "s|^$publishers/||" | grep -v '^$' || true)

if [ ${#configs[@]} -eq 0 ] && [ ! -f "$summary" ]; then
  echo "warning: $ref:$publishers/ holds no publishers." >&2
  echo "         the dashboard page will render its unavailable state." >&2
  echo "         run: git fetch origin ${ref#origin/}" >&2
  exit 0
fi

if [ ! -f "$summary" ]; then
  mkdir -p "$data_dir"
  summaries=()
  histories=()
  for config in "${configs[@]}"; do
    if git -C "$root" show "$ref:$publishers/$config/latest/summary.json" \
      >"$data_dir/$config.summary.json" 2>/dev/null; then
      summaries+=("$data_dir/$config.summary.json")
    else
      rm -f "$data_dir/$config.summary.json"
      echo "warning: $publishers/$config published no summary" >&2
    fi
    if git -C "$root" show "$ref:$publishers/$config/data/history.json" \
      >"$data_dir/$config.history.json" 2>/dev/null; then
      histories+=("$data_dir/$config.history.json")
    else
      rm -f "$data_dir/$config.history.json"
    fi
  done

  if [ ${#summaries[@]} -eq 0 ]; then
    echo "warning: no publisher under $ref:$publishers/ has a summary." >&2
    echo "         the dashboard page will render its unavailable state." >&2
    exit 0
  fi

  python3 "$trim" combine "$summary" "${summaries[@]}"
  [ ${#histories[@]} -eq 0 ] || python3 "$trim" combine "$history" "${histories[@]}"
  echo "Staged ${#summaries[@]} of ${#configs[@]} publishers from $ref."
fi

[ -n "$site" ] || exit 0

if [ ! -f "$summary" ]; then
  echo "warning: no dashboard data at $summary;" >&2
  echo "         the dashboard page will render its unavailable state." >&2
  echo "         run: make ocah-doc-dashboard-data" >&2
  exit 0
fi

# A site carries one TRM version: latest, or the release a snapshot stamped.
dashboard=$(find "$site/ocah-docs" -mindepth 2 -maxdepth 2 -name dashboard.html -print -quit 2>/dev/null || true)
if [ -n "$dashboard" ]; then
  data="$(dirname "$dashboard")/data"
else
  data="$site/ocah-docs/latest/data"
fi
mkdir -p "$data"
python3 "$trim" summary "$summary" "$data/summary.json" --tests-out "$data/tests.json"
if [ -f "$history" ]; then
  python3 "$trim" history "$history" "$data/history.json"
fi

if [ ${#configs[@]} -eq 0 ]; then
  echo "warning: $ref:$publishers/ is unreadable; per-test history not rebuilt" >&2
else
  runs_dirs=()
  for config in "${configs[@]}"; do
    runs_dirs+=(--runs-dir "$publishers/$config/data/runs/")
  done
  python3 "$root/tools/doc/aggregate_test_history.py" "$data/test-history.json" \
    --ref "$ref" "${runs_dirs[@]}" --limit "$runs_limit"
fi
python3 "$root/tools/doc/render_badges.py" "$summary" "$data"
echo "Staged dashboard data into $data/"
