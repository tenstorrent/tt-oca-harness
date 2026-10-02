<!--
SPDX-License-Identifier: Apache-2.0
SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
-->

# CDC/RDC sign-off collateral

This directory holds the shared pieces of the clock- and reset-domain-crossing
sign-off constraints. The per-block pieces live beside each subsystem:

| Path | Contents |
|---|---|
| `flows/synth/constraints/hier_reuse_procs.tcl` | Hierarchy-reuse hooks (`::cdc_hier_prefix`, clock and reset aliases, `::cdc_scenario`), the procs every constraint file uses, `cdc_create_port_reset` and the apply-once convergence configuration |
| `flows/cdc/cdc_rdc_setup.tcl` | Type-level synchronizer, verified-IP and gray-signal setup shared by every block; applies once per session |
| `hw/sys/<block>/synth/<block>_{clocks,clock_groups,io_delays}.sdc` | Clocks, generated clocks, async groups and IO delays; the synthesis SDC `constraints.sdc` composes the same files |
| `hw/sys/<block>/cdc/<block>.cdc_rdc.tcl` | Entry point: sources the block's files in dependency order |
| `hw/sys/<block>/cdc/<block>.{resets,case_analysis,static_signals,cdc_rdc_setup}.tcl` | Reset tree and assertion sequences, functional case analysis, quasi-static signals, instance-level synchronizer annotation |
| `hw/sys/<block>/cdc/<block>.vccdc*.waiver.tcl`, `hw/sys/<block>/rdc/<block>.vcrdc*.waiver.tcl` | Reviewed CDC and RDC waivers |

## Knobs

- `::cdc_app` — `cdc` (default) or `rdc`. Selects the application-specific files
  an entry sources (quasi-static signals and convergence constraints are CDC only).
- `::cdc_scenario` — `synth` (default) or `functional`. The functional scenario is
  the sign-off run: its case-analysis files pin the DFT and strap ports, so those
  ports take no IO delay. The synth scenario applies every IO delay. Both declare
  the async groups through `set_async_clock_groups` (`-allow_paths` plus the
  default bounds); the per-instance max-delay layer is applied only by
  `constraints.sdc`, which the sign-off entry does not source.

## Replaying a block under a parent

`hw/sys/smu/cdc/smu.cdc_rdc.tcl` shows the pattern: `cdc_begin_block <prefix>
{clock aliases} {reset aliases}`, source the child's entry, `cdc_end_block`. The
child's boundary constraints (port clocks, IO delays, port resets, its own
`cdc_apply_async_groups`) are skipped under a prefix; its internal constraints
re-anchor through `cdc_inst`, and generated clocks it registers with
`cdc_group_extra` land in the parent's async groups.

## Primitive leaf names

The constraints and waivers are written against the generic primitives the open
tree elaborates (`hw/common/ocah_prim_generic`, the OpenTitan `prim_generic`
set): a three-stage synchroniser is `<inst>/q_d`, `q_dd`, `q_ddd` (the tool
reports crossings and synchroniser outputs on `q_d`), a two-stage one is
`<inst>/u_sync_1/q_o` and `u_sync_2/q_o`, a flop is `<inst>/q_o`, the hardened
reset flop is `<inst>/q_d`, and a clock gate is the `<inst>/en_latch` latch.
Object types are `flop` and `latch`. A technology swap that replaces these
primitives changes every one of those names, so run with the generic set or
re-anchor the collateral.

## Editing

Every file here is Tcl and goes through `make lint-tcl` and `make format-tcl-check`.
Waiver files carry `# tclint-disable line-length`; keep their `-comment {}` text to
the mechanism and put longer analysis in review notes rather than in the file.
