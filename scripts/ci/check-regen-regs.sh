#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

set -euo pipefail

ROOT=$(git rev-parse --show-toplevel)
cd "$ROOT"

if (($# == 0)); then
  set -- .
fi

check_clean() {
  local tree=$1
  local status

  status=$(git -C "$tree" status --porcelain=v1 --untracked-files=all)
  if [[ -z "$status" ]]; then
    return
  fi

  echo "ERROR: register collateral is stale in '$tree'." >&2
  printf '%s\n' "$status" >&2
  git -C "$tree" --no-pager diff >&2
  git -C "$tree" --no-pager diff --cached >&2
  return 1
}

for tree in "$@"; do
  git -C "$tree" rev-parse --is-inside-work-tree >/dev/null
  check_clean "$tree"
done

# The Make clean target removes every currently declared output and ignored
# build artifact. Deleting any remaining tracked register outputs additionally
# proves that obsolete files, which are no longer Make targets, are not retained.
make ocah-regen-regs-clean
for tree in "$@"; do
  while IFS= read -r -d '' path; do
    rm -f -- "$tree/$path"
  done < <(
    git -C "$tree" ls-files -z -- \
      ':(glob)**/regs/**/gen/**' \
      ':(glob)**/registers/**/gen/**'
  )
done

# -B prevents checkout or filesystem timestamps from suppressing any recipe.
make -B ocah-regen-regs ocah-regen-regs-adoc ocah-regen-regs-html

python3 scripts/ci/validate-regen-regs.py "$@"
python3 hw/sys/sep/dv/cocotb/env/sep_reg_meta.py

stale=0
for tree in "$@"; do
  if ! check_clean "$tree"; then
    stale=1
  fi
done
exit "$stale"
