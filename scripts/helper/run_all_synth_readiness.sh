#!/usr/bin/env bash

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &>/dev/null && pwd)
REPO_ROOT=$(cd -- $SCRIPT_DIR/../.. &>/dev/null && pwd)

_ALL_BLOCKS=$(make -s --eval='print-%: ; @echo $($*)' print-OCAH_FLOW_TARGETS)

usage() {
  cat <<EOF
Usage: ${0##*/} [-h|--help] [BLOCK...]

Run the Yosys structural readiness check for each block and write the output
to local/synth_reports/<block>_readiness.log. With no BLOCK arguments, runs
every block: $_ALL_BLOCKS.

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

if (($# > 0)); then
  _BLOCKS="$*"
  for BLOCK in $_BLOCKS; do
    if ! grep -qxF -- "$BLOCK" < <(tr ' ' '\n' <<<"$_ALL_BLOCKS"); then
      echo "Unknown block '$BLOCK'. Available blocks: $_ALL_BLOCKS" >&2
      exit 1
    fi
  done
else
  _BLOCKS=$_ALL_BLOCKS
fi

mkdir -p $REPO_ROOT/local/synth_reports

for BLOCK in $_BLOCKS; do
  echo "OCAH_YOSYS_SYNTH_TCL=$REPO_ROOT/flows/synth/yosys/scripts/readiness.tcl make synth-yosys-all BLOCK=$BLOCK > $REPO_ROOT/local/synth_reports/$(echo $BLOCK)_readiness.log 2>&1"
  OCAH_YOSYS_SYNTH_TCL=$REPO_ROOT/flows/synth/yosys/scripts/readiness.tcl make synth-yosys-all BLOCK=$BLOCK >$REPO_ROOT/local/synth_reports/"$BLOCK"_readiness.log 2>&1
done

echo "Readiness Checks Complete - run $SCRIPT_DIR/list_all_synth_readiness.sh to see results"
