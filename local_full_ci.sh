#!/bin/bash
# local_full_ci.sh - reproduce the whole CI locally: GitHub (lint.yml, sim.yml, spdx.yml, doc.yml)
# plus the GitLab nonfree child pipeline (nonfree/ci.yml), in paired git worktrees.
#
# Run from a LOGIN shell so the Environment Modules `module` function is inherited:
#     bash -l ./local_full_ci.sh [options]
#
# Options:
#   --nonfree-sha SHA   nonfree commit to pair with (default: HEAD of the nonfree checkout)
#   --harness-ref REF   harness commit to test (default: HEAD; uncommitted changes are NOT included)
#   --out DIR           output dir for logs/status/run dirs (default: <repo root>/local_ci/<timestamp>)
#   --work DIR          dir for the paired worktrees (default: <out>/wt)
# Env: TMPDIR must be set (AGENTS.md: never /tmp). UV_CACHE_DIR / npm_config_cache default under $TMPDIR
#      when unset; XDG_DATA_HOME (rootless podman store) is left alone unless you export it.
#   --jobs N            verilator build jobs per smoke (default 12)
#   --skip-lint | --skip-verilator | --skip-nonfree | --skip-docs | --skip-regen
#   --keep              keep the worktrees even when everything passes
#
# Phases: (0) venv + regen-regs gate ALONE (it deletes/regenerates all register collateral);
#         (1) three parallel lanes: lint, verilator smokes, nonfree VCS/Xcelium jobs (sequential);
#         (2) docs last (its `uv sync` prunes cocotb). HTML docs build in the MAIN checkout because
#             Antora refuses a worktree (.git is a file there); the venv is restored afterwards.
set -uo pipefail

MAIN="$(cd "$(dirname "${BASH_SOURCE[0]}")" && git rev-parse --show-toplevel)"
NONFREE_MAIN="$(cd -P "$MAIN/nonfree" && pwd)"
HARNESS_REF=HEAD
NONFREE_SHA="$(git -C "$NONFREE_MAIN" rev-parse HEAD)"
TS="$(date +%Y%m%d_%H%M%S)"
OUT="$MAIN/local_ci/$TS"
WORK=""
JOBS=12
KEEP=0; DO_LINT=1; DO_VLT=1; DO_NF=1; DO_DOCS=1; DO_REGEN=1
while [ $# -gt 0 ]; do
  case "$1" in
    --nonfree-sha) NONFREE_SHA=$2; shift 2;;
    --harness-ref) HARNESS_REF=$2; shift 2;;
    --out) OUT=$2; shift 2;;
    --work) WORK=$2; shift 2;;
    --jobs) JOBS=$2; shift 2;;
    --skip-lint) DO_LINT=0; shift;;
    --skip-verilator) DO_VLT=0; shift;;
    --skip-nonfree) DO_NF=0; shift;;
    --skip-docs) DO_DOCS=0; shift;;
    --skip-regen) DO_REGEN=0; shift;;
    --keep) KEEP=1; shift;;
    -h|--help) sed -n 2,22p "$0"; exit 0;;
    *) echo "unknown option: $1" >&2; exit 2;;
  esac
done
[ -n "$WORK" ] || WORK="$OUT/wt"

# ---------------------------------------------------------------- preconditions
if ! type module 2>/dev/null | grep -q function; then
  echo "ERROR: 'module' is not a shell function. Run as:  bash -l $0 ..." >&2; exit 2
fi
export -f module 2>/dev/null; export -f _module_raw 2>/dev/null; export -f ml 2>/dev/null
for t in vcs uv bender slang podman bwrap; do
  command -v $t >/dev/null || { echo "ERROR: $t not on PATH" >&2; exit 2; }
done
[ -x /tools_vendor/FOSS/verilator/5.050/bin/verilator ] || { echo "ERROR: verilator 5.050 missing (CI pins v5.050)" >&2; exit 2; }
if [ -n "$(git -C "$MAIN" status --porcelain -uno)" ]; then
  echo "WARNING: harness checkout has uncommitted tracked changes; they are NOT part of this run (testing $HARNESS_REF)." >&2
fi

# ---------------------------------------------------------------- environment (matches what CI gets)
[ -n "${TMPDIR:-}" ] && [ -d "$TMPDIR" ] || { echo "ERROR: TMPDIR must point at an existing large scratch dir (see AGENTS.md)" >&2; exit 2; }
export PATH=/tools_vendor/FOSS/verilator/5.050/bin:/opt/rh/gcc-toolset-13/root/bin:$PATH
export LD_LIBRARY_PATH=/opt/rh/gcc-toolset-13/root/usr/lib64:${LD_LIBRARY_PATH:-}
export UV_CACHE_DIR="${UV_CACHE_DIR:-$TMPDIR/uv_cache}"          # keep caches off a full /home
export npm_config_cache="${npm_config_cache:-$TMPDIR/npm_cache}"
export OCAH_NONFREE_REMOTE=skip                        # never let make try to (re)clone nonfree
mkdir -p "$UV_CACHE_DIR" "$npm_config_cache"

H="$WORK/h"; LOG="$OUT/logs"; ST="$OUT/status"; RUNS="$OUT/runs"
# The login shell may export OCH_ROOT/NONFREE_ROOT/ROOT for the MAIN checkout; nonfree/tools/packaged_sim_check.sh
# honours them (${OCH_ROOT:-...}) and would run against MAIN instead of the worktree pair -> pin to the worktree.
export OCH_ROOT="$H" NONFREE_ROOT="$H/nonfree" ROOT="$H"
mkdir -p "$LOG" "$ST" "$RUNS" "$WORK"
# keep the output dir out of `git status` without touching tracked ignore files
excl="$(git -C "$MAIN" rev-parse --git-common-dir)/info/exclude"
grep -qx "local_ci/" "$excl" 2>/dev/null || echo "local_ci/" >> "$excl"
exec > >(tee -a "$LOG/driver.log") 2>&1

# ---------------------------------------------------------------- worktrees
echo "== harness $MAIN @ $(git -C "$MAIN" rev-parse --short "$HARNESS_REF")  |  nonfree $NONFREE_MAIN @ ${NONFREE_SHA:0:8}"
printf "== output    %s\n== worktrees %s\n" "$OUT" "$WORK"
git -C "$MAIN" worktree add --detach "$H" "$HARNESS_REF" || exit 1
git -C "$NONFREE_MAIN" worktree add --detach "$H/nonfree" "$NONFREE_SHA" || exit 1
cd "$H" || exit 1
MAIN_STATUS_BEFORE="$(git -C "$MAIN" status --porcelain --untracked-files=all)"

cleanup() {
  git -C "$NONFREE_MAIN" worktree remove --force "$H/nonfree" 2>/dev/null
  git -C "$MAIN" worktree remove --force "$H" 2>/dev/null
  rmdir "$WORK" 2>/dev/null
}

# ---------------------------------------------------------------- job runner
# run_job <name> <G|A> <timeout_s> <cmd...>    (G = gating in CI, A = advisory / `|| true` in CI)
run_job() {
  local name=$1 kind=$2 to=$3; shift 3
  local t0=$SECONDS
  echo "[$(date +%T)] START $name"
  ( cd "$H" && timeout -k 60 "$to" bash -c "set -eo pipefail; $*" ) > "$LOG/$name.log" 2>&1
  local rc=$? res=PASS
  [ $rc -ne 0 ] && res=FAIL; [ $rc -eq 124 ] && res=TIMEOUT
  echo "$name|$kind|$res|$rc|$((SECONDS-t0))" > "$ST/$name"
  echo "[$(date +%T)] END   $name $res rc=$rc $((SECONDS-t0))s"
}
# Tree-wide formatters see nonfree files that GitHub never scans; re-judge on open-tree hits only.
rejudge_open_tree() {  # rejudge_open_tree <name> <grep-pattern-for-a-finding>
  local name=$1 pat=$2; local f="$ST/$name"
  grep -q "|FAIL|" "$f" || return 0
  local n; n=$(grep -E "$pat" "$LOG/$name.log" | grep -vc "/nonfree/")
  if [ "$n" -eq 0 ]; then
    sed -i 's/|FAIL|/|PASS(nonfree-only findings)|/' "$f"
    echo "[$(date +%T)] NOTE  $name: all findings are in nonfree/ (not scanned by GitHub) -> PASS"
  else
    echo "[$(date +%T)] NOTE  $name: $n open-tree finding(s)"
  fi
}

# ---------------------------------------------------------------- phase 0
run_job setup_venv G 1800 "uv sync --group dv"
if [ $DO_REGEN -eq 1 ]; then
  run_job gl_regen-regs-diff G 1800 "bash scripts/ci/check-regen-regs.sh . nonfree"
  for t in "$H" "$H/nonfree"; do
    git -C "$t" status --porcelain=v1 --untracked-files=all > "$LOG/regen_status_$(basename "$t").txt"
    git -C "$t" diff > "$LOG/regen_diff_$(basename "$t").patch"
    git -C "$t" checkout -q -- . ; git -C "$t" clean -fdq -- hw doc 2>/dev/null
  done
  run_job setup_venv_after_regen G 1800 "uv sync --group dv"
fi

# ---------------------------------------------------------------- phase 1 lanes
lane_lint() {
  run_job gh_lint-python G 1800 "make ocah-lint-python && make ocah-format-python-check"
  run_job gh_format-tcl-check G 1800 "make ocah-format-tcl-check";  rejudge_open_tree gh_format-tcl-check "needs reformatting"
  run_job gh_ADV_format-c A 1800 "make ocah-format-c-check";        rejudge_open_tree gh_ADV_format-c "clang-format-violations"
  run_job gh_ADV_lint-tcl A 1800 "make ocah-lint-tcl";              rejudge_open_tree gh_ADV_lint-tcl "^/"
  run_job gh_ADV_slang-smu A 1800 "make -C hw/sys/smu -f flow.mk ocah-lint-slang-flist OCAH_ROOT=$H && slang -f hw/sys/smu/build/lint/smu.f --top smu --timescale=1ns/1ps --lint-only --single-unit --compat vcs --error-limit 0"
  run_job gh_ADV_slang-aou A 1800 "make -C vendor/tenstorrent/aou/overlay -f flow.mk ocah-lint-slang-flist OCAH_ROOT=$H && slang -f vendor/tenstorrent/aou/overlay/build/lint/AOU_TOP.f --top AOU_TOP --timescale=1ns/1ps --lint-only --single-unit --compat vcs --error-limit 0"
  for b in aou dtp sep smc smu; do
    run_job gh_lint-sv-verilator_$b G 1800 "make ocah-lint-verilator-all BLOCK=$b"
  done
  # spdx.yml uses an external action; approximate: every added/modified text file vs origin/main has a header.
  run_job gh_spdx-approx G 600 '
    base=$(git merge-base HEAD origin/main); miss=0
    while IFS= read -r f; do
      [ -f "$f" ] || continue
      case "$f" in *.png|*.jpg|*.svg|*.hex|*.bin|*.mem|*.vh|*/gen/*|*.lock|*.json|*.md|*.txt|*.csv) continue;; esac
      grep -q "SPDX-License-Identifier" "$f" || { echo "MISSING SPDX: $f"; miss=1; }
    done < <(git diff --name-only --diff-filter=AM "$base" HEAD)
    exit $miss'
}
lane_verilator() {
  run_job gh_run_dv-validate G 600 "python3 tools/dv/run_dv.py --validate-configs"
  for d in dtp sep smu smc; do
    run_job gh_verilator-smoke_$d G 3600 "python3 tools/dv/run_dv.py --doctor --dut $d --tool verilator && python3 tools/dv/run_dv.py --dut $d --items smoke --tool verilator --sim-jobs 2 --build-jobs $JOBS --run-dir $RUNS/$d"
  done
}
lane_nonfree() {   # exact script lines from nonfree/ci.yml; `make ocah-nonfree-init` skipped (no-op in CI, breaks on worktree .git file)
  run_job gl_sep-smoke-test G 7200 "make fw-ci-sep-hello && make test-sep TEST_NAME=sep_hello_world_test STACK=clean,flist,compile,sim SEED=1"
  run_job gl_smc-smoke-test G 7200 "make fw-ci-smc-cpu && SIM_ARGS='+skip_fuse_sense' make test-smc TEST_NAME=smc_cpu_sanity_test STACK=clean,flist,compile_smc_chiplet,sim SEED=1 COMPILE_TARGET=compile_smc_chiplet"
  run_job gl_smc-rom-smoke-test G 7200 "make fw-ci-smc-rom && make test-smc TEST_NAME=smc_occp_sanity_test STACK=clean,flist,compile_w_master_bfm,sim SEED=1 COMPILE_TARGET=compile_w_master_bfm SIM_ARGS='+BOOT_I3C'"
  run_job gl_smc-fw-build G 7200 "make fw-ci-smc-all"
  run_job gl_sep-fw-build G 7200 "make fw-ci-sep-all"
  run_job gl_smu-build-smoke-sep G 7200 "make test-smu TEST_NAME=smu_smc_smoke_test STACK=clean,flist,compile_smu_chiplet_sep_rtl_ci COMPILE_TARGET=compile_smu_chiplet_sep_rtl_ci"
  run_job gl_smu-build-smoke-no-sep G 7200 "make test-smu TEST_NAME=smu_smc_smoke_test STACK=clean,flist,compile_smu_chiplet_no_sep_ci COMPILE_TARGET=compile_smu_chiplet_no_sep_ci"
  # NOTE: do not re-source the Modules init here; the inherited `module` function is what works.
  run_job gl_smu-xcelium-elab-smoke G 7200 "source nonfree/setup_env.sh; module load cadence/xcelium/24.03.003 || true; command -v xrun; make -f nonfree/tools/elab/bender-targets.mk customer_smu_filelist && make -f nonfree/tools/elab/xcelium.mk compile FILELIST=customer_smu.f TOP_MODULE=smu"
  run_job gl_packaged-sim-check_smc G 10800 "make fw-ci-smu-smc && export SMU_TEST=smu_smc_smoke_test SMU_COMPILE=compile_smu_chiplet_no_sep && SKIP_CGEN=1 PACKAGED_DIR=packaged_sim_ip_smc PACKAGED_VERSION=packaged-local nonfree/tools/packaged_sim_check.sh smu"
  run_job gl_packaged-sim-check_sep G 10800 "make fw-ci-smu-sep && export SMU_TEST=smu_sep_smoke_test SMU_COMPILE=compile_smu_chiplet_sep_rtl SMU_RUN_ARGS= && SKIP_CGEN=1 PACKAGED_DIR=packaged_sim_ip_sep PACKAGED_VERSION=packaged-local nonfree/tools/packaged_sim_check.sh smu"
}
# Lanes run in parallel; each line is tagged by job name (gh_*/gl_*) and also kept in $LOG/lane_*.out.
[ $DO_LINT -eq 1 ] && { lane_lint      2>&1 | tee "$LOG/lane_lint.out"; } &
[ $DO_VLT  -eq 1 ] && { lane_verilator 2>&1 | tee "$LOG/lane_verilator.out"; } &
[ $DO_NF   -eq 1 ] && { lane_nonfree   2>&1 | tee "$LOG/lane_nonfree.out"; } &
wait

# ---------------------------------------------------------------- phase 2 docs (last)
if [ $DO_DOCS -eq 1 ]; then
  # doc.yml: HTML site. Antora needs a real .git dir -> build in the MAIN checkout at the same commit, then restore cocotb.
  if [ "$(git -C "$MAIN" rev-parse HEAD)" = "$(git -C "$H" rev-parse HEAD)" ]; then
    t0=$SECONDS; echo "[$(date +%T)] START gh_doc-combined-html (in $MAIN)"
    ( cd "$MAIN" && timeout -k 60 3600 bash -c "set -eo pipefail; uv sync && make ocah-doc-combined-html OCAH_DOC_SITE_URL=/tt-oca-harness" ) > "$LOG/gh_doc-combined-html.log" 2>&1
    rc=$?; res=PASS; [ $rc -ne 0 ] && res=FAIL
    ( cd "$MAIN" && uv sync --group dv ) >> "$LOG/gh_doc-combined-html.log" 2>&1
    echo "gh_doc-combined-html|G|$res|$rc|$((SECONDS-t0))" > "$ST/gh_doc-combined-html"
    echo "[$(date +%T)] END   gh_doc-combined-html $res rc=$rc $((SECONDS-t0))s"
  else
    echo "gh_doc-combined-html|G|SKIP(main checkout not at $HARNESS_REF)|-|0" > "$ST/gh_doc-combined-html"
  fi
  # doc.yml: PDFs. asciidoctor-pdf is not installed natively on soc-l hosts; use the repo's container path.
  run_job gh_doc-pdf G 3600 "./scripts/docker-run.sh doc-pdf trm && ./scripts/docker-run.sh doc-pdf integrator"
fi

# ---------------------------------------------------------------- summary
echo; echo "================ SUMMARY  ($OUT) ================"
{ echo "job|kind|result|rc|secs"; cat "$ST"/*; } | column -t -s'|'
gating_fail=$(cat "$ST"/* | awk -F'|' '$2=="G" && $3!~/^PASS/ && $3!~/^SKIP/' | wc -l)
adv_fail=$(cat "$ST"/* | awk -F'|' '$2=="A" && $3!~/^PASS/' | wc -l)
echo; echo "gating failures: $gating_fail   advisory failures: $adv_fail   output: $OUT"
new_residue="$(comm -13 <(echo "$MAIN_STATUS_BEFORE" | sort) <(git -C "$MAIN" status --porcelain --untracked-files=all | grep -v " local_ci/" | sort))"
[ -n "$new_residue" ] && { echo; echo "NOTE: new untracked/modified files appeared in $MAIN during the run:"; echo "$new_residue"; }

if [ $gating_fail -eq 0 ] && [ $KEEP -eq 0 ]; then cleanup; echo "worktrees removed"; else echo "worktrees kept at $H (and $H/nonfree)"; fi
exit $(( gating_fail > 0 ))
