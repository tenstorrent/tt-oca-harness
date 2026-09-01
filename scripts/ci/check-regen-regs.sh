#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

set -euo pipefail

ROOT=$(git rev-parse --show-toplevel)
cd "$ROOT"

(($# == 0)) && set -- .

check_clean() {
  local tree=$1 status
  status=$(git -C "$tree" status --porcelain=v1 --untracked-files=all)
  [[ -z "$status" ]] && return
  echo "ERROR: register collateral is stale in '$tree'." >&2
  printf '%s\n' "$status" >&2
  git -C "$tree" --no-pager diff >&2
  git -C "$tree" --no-pager diff --cached >&2
  return 1
}

is_preserved_output() {
  local tree=$1 path=$2
  [[ $(git -C "$tree" rev-parse --show-toplevel) == "$ROOT" ]] &&
    [[ "$path" == "hw/ip/efuse/regs/gen/sv/efuse_bank_reg.sv" ||
      "$path" == "hw/ip/efuse/regs/gen/sv/efuse_bank_reg_pkg.sv" ]]
}

for tree in "$@"; do
  git -C "$tree" rev-parse --is-inside-work-tree >/dev/null
  check_clean "$tree"
done

# ocah-regen-regs-clean removes every declared Make output; deleting any
# tracked register file that survives that proves it is an obsolete,
# no-longer-generated artifact. The eFuse-bank SV is hand-edited and
# classified as external RTL, so it is the one file this check preserves.
make ocah-regen-regs-clean
for tree in "$@"; do
  while IFS= read -r -d '' path; do
    is_preserved_output "$tree" "$path" && continue
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
  check_clean "$tree" || stale=1
done
exit "$stale"
