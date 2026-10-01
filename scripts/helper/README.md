<!--
SPDX-License-Identifier: Apache-2.0
SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
-->

# Helper scripts

Wrappers that run every block's Verilator DV regression or Yosys structural
readiness check in one go, and summarise the results. Each `run_*` script
writes one log per block under `local/`; the matching `list_*` script reads
those logs and prints a colour-coded one-line status per block.

Run them from anywhere: each script locates the repository root from its own
path.

| Script | Purpose | Output |
|---|---|---|
| `run_all_sim_tests.sh` | Runs `tools/dv/run_dv.py --dut <dut> --items all` with `--sim-jobs` set to `nproc - 2` | `local/sim_reports/<dut>_sim.log` |
| `list_all_sim_tests.sh` | Summarises the sim logs for every Verilator DUT reported by `run_dv.py --list` | stdout |
| `run_all_synth_readiness.sh` | Runs `make synth-yosys-all BLOCK=<block>` with `OCAH_YOSYS_SYNTH_TCL` set to `flows/synth/yosys/scripts/readiness.tcl` for `smc sep smu aou dtp` | `local/synth_reports/<block>_readiness.log` |
| `list_all_synth_readiness.sh` | Summarises the readiness logs for the same blocks | stdout |

## Typical use

```bash
scripts/helper/run_all_sim_tests.sh        # long-running; blocks run one after another
scripts/helper/list_all_sim_tests.sh       # safe to run while the above is in progress

scripts/helper/run_all_synth_readiness.sh
scripts/helper/list_all_synth_readiness.sh
```

The `list_*` scripts only read logs, so they can be rerun at any time.
Do not start a second `run_*` script while one is still going: both write the
same logs and build directories.

## Reading the status output

Simulation (`list_all_sim_tests.sh`):

| Status | Meaning |
|---|---|
| `TOTAL / PASS / FAIL / SKIP` counts, green | The log has a `summary` line and no failures |
| Same counts, red | The `summary` line reports failing tests |
| `No Log (not run)` (grey) | `local/sim_reports/<dut>_sim.log` does not exist |
| `Still Running` (cyan) | No `summary` line and no `status=ERROR` in the log yet |
| `Verilator Build Failed` (bold red) | No `summary` line and the log contains `status=ERROR` |

Synthesis readiness (`list_all_synth_readiness.sh`):

| Status | Meaning |
|---|---|
| `Readiness Clean - no warnings` (green) | `STRUCTURAL_READINESS_PASS` found and the build reports 0 warnings |
| `Readiness Pass - check warnings` (yellow) | `STRUCTURAL_READINESS_PASS` found, but the build reports warnings; review them as `flows/synth/yosys/README.md` requires |
| `No Log (not run)` (grey) | `local/synth_reports/<block>_readiness.log` does not exist |
| `Still Running` (cyan) | Neither the pass marker nor an `ERROR:` line is in the log yet |
| `Yosys Readiness Check Failed` (bold red) | No pass marker and the log contains `ERROR:` |

## Changing the scope

- `run_all_sim_tests.sh` currently runs a single DUT (`duts="smc"`). The
  commented-out line above it derives the full list from `run_dv.py --list`.
  Edit `duts` to choose which DUTs to run.
- The block list for the readiness scripts is `_BLOCKS` at the top of each
  script. Keep the two copies in step.
- `local/` holds machine-specific scratch output and is not part of the
  open tree.
