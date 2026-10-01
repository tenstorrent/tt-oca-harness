#!/usr/bin/env bash

SCRIPT_DIR=$( cd -- "$( dirname -- "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )
REPO_ROOT=$( cd -- $SCRIPT_DIR/../.. &> /dev/null && pwd)

DV_SCRIPT=$REPO_ROOT/tools/dv/run_dv.py
JOBS=$(python3 -c "print($(nproc)-2)")

#duts=$($DV_SCRIPT --list | grep verilator | awk '{print $1}' | grep -vxF -e dtp -e sep -e smc -e smu )
duts="smc"

mkdir -p $REPO_ROOT/local/sim_reports

for dut in $duts; do
    echo "$DV_SCRIPT --dut $dut --items all --sim-jobs $JOBS > $REPO_ROOT/local/sim_reports/$(echo $dut)_sim.log 2>&1";
    $DV_SCRIPT --dut $dut --items all --sim-jobs $JOBS > $REPO_ROOT/local/sim_reports/$(echo $dut)_sim.log 2>&1
done
