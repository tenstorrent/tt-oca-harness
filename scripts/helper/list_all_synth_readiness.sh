#!/usr/bin/env bash

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &>/dev/null && pwd)
REPO_ROOT=$(cd -- $SCRIPT_DIR/../.. &>/dev/null && pwd)

_BLOCKS=$(make -s --eval='print-%: ; @echo $($*)' print-OCAH_FLOW_TARGETS)

echo

for BLOCK in $_BLOCKS; do
  log="$REPO_ROOT/local/synth_reports/${BLOCK}_readiness.log"
  if [ ! -f "$log" ]; then
    printf "\e[90m%-4s\e[0m No Log (not run)\n" "$BLOCK"
    continue
  fi
  line=$(grep -s 'STRUCTURAL_READINESS_PASS' "$log" | tail -1)

  if [ -z "$line" ]; then
    error=$(grep -s 'ERROR:' "$log")
    if [ -z "$error" ]; then
      printf "\e[36m%-4s\e[0m Still Running\n" "$BLOCK"
    else
      printf "\e[1;31m%-4s\e[0m Yosys Readiness Check Failed\n" "$BLOCK"
    fi
  else
    warnings_line=$(grep -s 'Build succeeded: 0 errors,' "$log" | tail -1)
    warnings=$(grep -oP '\K\d+(?= warnings?)' <<<"$warnings_line")

    if ((warnings > 0)); then
      printf "\e[33m%-4s\e[0m Readiness Pass - check $warnings warnings\n" "$BLOCK"
    else
      printf "\e[92m%-4s\e[0m Readiness Clean - no warnings\n" "$BLOCK"
    fi
  fi

done

echo
