<!--
SPDX-License-Identifier: Apache-2.0
SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
-->

# CDC/RDC sign-off collateral

This directory holds the shared pieces of the clock- and reset-domain-crossing
sign-off constraints. The per-block pieces live beside each subsystem:

| Path | Contents |
|---|---|
| `flows/synth/constraints/cdc_hier_procs.tcl` | Hierarchy-reuse hooks (`::cdc_hier_prefix`, clock and reset aliases, `::cdc_scenario`, `::cdc_bound_crossings`) and the procs every constraint file uses |
| `flows/cdc/vc_procs.tcl` | Sign-off helpers on top of those hooks: `cdc_create_port_reset`, the apply-once convergence configuration |
| `flows/cdc/cdc_rdc_setup.tcl` | Type-level synchronizer, verified-IP and gray-signal setup shared by every block; applies once per session |
| `hw/sys/<block>/synth/constraints.sdc` | Clocks, generated clocks, IO delays and async groups; also the synthesis SDC |
| `hw/sys/<block>/cdc/<block>.cdc_rdc.tcl` | Entry point: sources the block's files in dependency order |
| `hw/sys/<block>/cdc/<block>.{resets,case_analysis,static_signals,cdc_rdc_setup}.tcl` | Reset tree and assertion sequences, functional case analysis, quasi-static signals, instance-level synchronizer annotation |
| `hw/sys/<block>/cdc/<block>.vccdc*.waiver.tcl`, `hw/sys/<block>/rdc/<block>.vcrdc*.waiver.tcl` | Reviewed CDC and RDC waivers |

## Knobs

- `::cdc_app` — `cdc` (default) or `rdc`. Selects the application-specific files
  an entry sources (quasi-static signals and convergence constraints are CDC only).
- `::cdc_scenario` — `synth` (default) or `functional`. The functional scenario is
  the sign-off run: its case-analysis files pin the DFT and strap ports, so those
  ports take no IO delay, and the async groups are declared with a bare
  `set_clock_groups -asynchronous`. The synth scenario applies every IO delay and
  declares the groups with `-allow_paths` plus default bounds.
- `::cdc_bound_crossings` — `1` (default) bounds the crossings in the synth
  scenario: `-allow_paths` groups with default bounds plus the block's per-instance
  max-delay layer. `0` declares bare async groups and applies no bound.

## Replaying a block under a parent

`hw/sys/smu/cdc/smu.cdc_rdc.tcl` shows the pattern: `cdc_begin_block <prefix>
{clock aliases} {reset aliases}`, source the child's entry, `cdc_end_block`. The
child's boundary constraints (port clocks, IO delays, port resets, its own
`cdc_apply_async_groups`) are skipped under a prefix; its internal constraints
re-anchor through `cdc_inst`, and generated clocks it registers with
`cdc_group_extra` land in the parent's async groups.

## Editing

Every file here is Tcl and goes through `make lint-tcl` and `make format-tcl-check`.
Waiver files carry `# tclint-disable line-length`; keep their `-comment {}` text to
the mechanism and put longer analysis in review notes rather than in the file.
