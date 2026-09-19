#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

set -euo pipefail

ROOT=$(git rev-parse --show-toplevel)
cd "$ROOT"

skip_if_unrelated=0
if [[ ${1:-} == --skip-if-unrelated ]]; then
  skip_if_unrelated=1
  shift
fi

(($# == 0)) && set -- .

if ((skip_if_unrelated)); then
  if python3 scripts/ci/diff_class.py --is-register-regen-required; then
    echo "Register inputs or generated collateral changed; running regeneration check."
  else
    echo "No register inputs, generated collateral, or generator infrastructure changed; skipping."
    exit 0
  fi
fi

readonly BATCH_SIZE=128
readonly -a GENERATED_PATHS=(
  ':(glob)**/regs/**/gen/**'
  ':(glob)**/registers/**/gen/**'
  # Vendored overlay RDL files exported as standalone blocks (see discover.mk):
  # unlike every other block, their gen/ sits beside the .rdl under overlay/rdl/
  # rather than under a regs/ or registers/ dir (e.g. pulp-platform idma's
  # dma_ctrl).
  ':(glob)**/rdl/**/gen/**'
)

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

remove_tracked_outputs() {
  local tree=$1 path
  local -a batch=()

  while IFS= read -r -d '' path; do
    batch+=("$tree/$path")
    if ((${#batch[@]} == BATCH_SIZE)); then
      rm -f -- "${batch[@]}"
      batch=()
    fi
  done < <(git -C "$tree" ls-files -z -- "${GENERATED_PATHS[@]}")
  ((${#batch[@]} == 0)) || rm -f -- "${batch[@]}"
}

stamp_generated_outputs() {
  local tree=$1 path
  local -a batch=()

  while IFS= read -r -d '' path; do
    batch+=("$tree/$path")
    if ((${#batch[@]} == BATCH_SIZE)); then
      python3 "$ROOT/tools/regs/stamp_spdx.py" "${batch[@]}"
      batch=()
    fi
  done < <(
    git -C "$tree" ls-files -z -- "${GENERATED_PATHS[@]}"
    git -C "$tree" ls-files -z --others --exclude-standard -- "${GENERATED_PATHS[@]}"
  )
  ((${#batch[@]} == 0)) ||
    python3 "$ROOT/tools/regs/stamp_spdx.py" "${batch[@]}"
}

for tree in "$@"; do
  git -C "$tree" rev-parse --is-inside-work-tree >/dev/null
  check_clean "$tree"
done

# ocah-regen-regs-clean removes every declared Make output; deleting any
# tracked register file that survives that proves it is an obsolete,
# no-longer-generated artifact.
make ocah-regen-regs-clean
for tree in "$@"; do
  remove_tracked_outputs "$tree"
done

# Sync once before the forced build. Without the skip, Make runs this phony
# prerequisite while remaking depfiles and then again after it restarts.
make uv-sync

# Vendor RDLs are committed generator outputs, but are not prerequisites of the
# downstream collateral target. Check their own round trip explicitly.
OCAH_REG_SKIP_UV_SYNC=1 make ocah-regen-vendor-rdl CHECK=1
.venv/bin/python -m unittest tools.regs.tests.test_reggen_wrapper

# -B prevents checkout or filesystem timestamps from suppressing any generator.
# Batch SPDX stamping after generation: starting one Python interpreter for
# every output dominates this metadata-heavy check when runners are busy.
OCAH_REG_SKIP_UV_SYNC=1 OCAH_REG_DEFER_STAMP=1 \
  make -B ocah-regen-regs ocah-regen-regs-adoc ocah-regen-regs-html
for tree in "$@"; do
  stamp_generated_outputs "$tree"
done

python3 scripts/ci/validate-regen-regs.py "$@"
python3 hw/sys/sep/dv/cocotb/env/sep_reg_meta.py

stale=0
for tree in "$@"; do
  check_clean "$tree" || stale=1
done
exit "$stale"
