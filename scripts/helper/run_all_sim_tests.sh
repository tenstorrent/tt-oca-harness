#!/usr/bin/env bash

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &>/dev/null && pwd)
REPO_ROOT=$(cd -- $SCRIPT_DIR/../.. &>/dev/null && pwd)

DV_SCRIPT=$REPO_ROOT/tools/dv/run_dv.py
JOBS=$(python3 -c "print($(nproc)-2)")

usage() {
  cat <<EOF
Usage: ${0##*/} [-h|--help] [DUT...]

Run every test of each DUT with run_dv.py and write the output to
local/sim_reports/<dut>_sim.log. With no DUT arguments, runs every
Verilator DUT reported by 'run_dv.py --list'.

Options:
  -h, --help   Print this help and exit
EOF
}

case "${1:-}" in
-h | --help)
  usage
  exit 0
  ;;
esac

all_duts=$($DV_SCRIPT --list | grep verilator | awk '{print $1}')

if (($# > 0)); then
  duts="$*"
  for dut in $duts; do
    if ! grep -qxF -- "$dut" <<<"$all_duts"; then
      echo "Unknown DUT '$dut'. Available DUTs:" >&2
      sed 's/^/  /' <<<"$all_duts" >&2
      exit 1
    fi
  done
else
  duts=$all_duts
fi

mkdir -p $REPO_ROOT/local/sim_reports

for dut in $duts; do
  echo "$DV_SCRIPT --dut $dut --items all --sim-jobs $JOBS > $REPO_ROOT/local/sim_reports/${dut}_sim.log 2>&1"
  $DV_SCRIPT --dut $dut --items all --sim-jobs $JOBS >$REPO_ROOT/local/sim_reports/${dut}_sim.log 2>&1
done
