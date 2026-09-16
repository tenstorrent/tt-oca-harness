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
# a nightly did not publish.
#
# Env: OCAH_ROOT                    repository root (default: this script's repo)
#      OCAH_DASHBOARD_DATA_DIR      where the published summary is cached
#      OCAH_DASHBOARD_DATA_REF      git ref carrying the data branch
#      OCAH_DASHBOARD_DATA_PATH     path to summary.json within that ref
#      OCAH_DASHBOARD_HISTORY_PATH  path to history.json within that ref
set -euo pipefail

root="${OCAH_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd -P)}"
data_dir="${OCAH_DASHBOARD_DATA_DIR:-$root/doc/_build/dashboard-data}"
ref="${OCAH_DASHBOARD_DATA_REF:-origin/dv-dashboard-data}"
path="${OCAH_DASHBOARD_DATA_PATH:-latest/summary.json}"
history_path="${OCAH_DASHBOARD_HISTORY_PATH:-data/history.json}"
site="${1:-}"

summary="$data_dir/summary.json"
history="$data_dir/history.json"

if [ ! -f "$summary" ]; then
  mkdir -p "$data_dir"
  if git -C "$root" show "$ref:$path" >"$summary.tmp" 2>/dev/null; then
    mv "$summary.tmp" "$summary"
    echo "Staged dashboard data from $ref."
  else
    rm -f "$summary.tmp"
    echo "warning: $ref:$path not found." >&2
    echo "         the dashboard page will render its unavailable state." >&2
    echo "         run: git fetch origin ${ref#origin/}" >&2
    exit 0
  fi
fi

if [ ! -f "$history" ]; then
  git -C "$root" show "$ref:$history_path" >"$history.tmp" 2>/dev/null &&
    mv "$history.tmp" "$history" || rm -f "$history.tmp"
fi

[ -n "$site" ] || exit 0

if [ ! -f "$summary" ]; then
  echo "warning: no dashboard data at $summary;" >&2
  echo "         the dashboard page will render its unavailable state." >&2
  echo "         run: make ocah-doc-dashboard-data" >&2
  exit 0
fi

data="$site/ocah-docs/latest/data"
mkdir -p "$data"
trim="$root/tools/doc/trim_dashboard_data.py"
python3 "$trim" summary "$summary" "$data/summary.json" --tests-out "$data/tests.json"
if [ -f "$history" ]; then
  python3 "$trim" history "$history" "$data/history.json"
fi
echo "Staged dashboard data into $data/"
