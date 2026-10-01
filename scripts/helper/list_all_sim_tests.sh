#!/usr/bin/env bash

SCRIPT_DIR=$( cd -- "$( dirname -- "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )
REPO_ROOT=$( cd -- $SCRIPT_DIR/../.. &> /dev/null && pwd)
DV_SCRIPT=$REPO_ROOT/tools/dv/run_dv.py

duts=$($DV_SCRIPT --list | grep verilator | awk '{print $1}')

echo

width=0
for dut in $duts; do (( ${#dut} > width )) && width=${#dut}; done

for dut in $duts; do
    log="$REPO_ROOT/local/sim_reports/${dut}_sim.log"
    if [ ! -f "$log" ]; then
        printf "\e[90m%-*s\e[0m No Log (not run)\n" "$width" "$dut"
        continue
    fi
    line=$(grep -s 'summary    passing=' "$log" | tail -1)

    if [ -z "$line" ]; then
        error=$(grep -s 'status=ERROR' "$log")
        if [ -z "$error" ]; then
            printf "\e[36m%-*s\e[0m Still Running\n" "$width" "$dut"
        else
            printf "\e[1;31m%-*s\e[0m Verilator Build Failed\n" "$width" "$dut"
        fi
        continue
    fi

    declare -A kv=()
    for tok in $line; do
        [[ $tok == *=* ]] && kv[${tok%%=*}]=${tok#*=}
    done

    if (( kv[failing] > 0 )); then colour=$'\e[31m'; else colour=$'\e[92m'; fi
    printf '%s%-*s\e[0m TOTAL =%4s PASS =%4s FAIL =%4s SKIP =%4s\n' \
        "$colour" "$width" "$dut" \
        "${kv[total]}" "${kv[passing]}" "${kv[failing]}" "${kv[skipped]}"

done

echo
