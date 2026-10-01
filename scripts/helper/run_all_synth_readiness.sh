#!/usr/bin/env bash

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &>/dev/null && pwd)
REPO_ROOT=$(cd -- $SCRIPT_DIR/../.. &>/dev/null && pwd)

_BLOCKS="smc sep smu aou dtp"

mkdir -p $REPO_ROOT/local/synth_reports

for BLOCK in $_BLOCKS; do
  echo "OCAH_YOSYS_SYNTH_TCL=$REPO_ROOT/flows/synth/yosys/scripts/readiness.tcl make synth-yosys-all BLOCK=$BLOCK > $REPO_ROOT/local/synth_reports/$(echo $BLOCK)_readiness.log 2>&1"
  OCAH_YOSYS_SYNTH_TCL=$REPO_ROOT/flows/synth/yosys/scripts/readiness.tcl make synth-yosys-all BLOCK=$BLOCK >$REPO_ROOT/local/synth_reports/"$BLOCK"_readiness.log 2>&1
done
