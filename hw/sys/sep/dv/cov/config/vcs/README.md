<!-- SPDX-License-Identifier: Apache-2.0 -->
<!-- SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. -->

# SEP VCS coverage scope

`sep_cov_scope.hier` is passed to VCS at compile time as `-cm_hier` plus
`-cm_common_hier` (`[coverage.vcs]` in `sep_sim_cfg.toml`), so what it drops
never enters the coverage database. Edit the file then `--rebuild`; the
contents are not fingerprinted.

## What it excludes

    -tree sep_uvm_top 1                       TB top's own body, children kept
    -tree sep_uvm_top.u_mbx                   sep_outbound_mbx
    -module ocah_axi_sva                      u_m_axi_sva, u_s_axi_sva, key_manager bind
    -tree sep_uvm_top.u_dut.u_sep.sep_cpu     CPU subtree

`-module` rather than instance paths for the SVA, because the third instance is
a `bind key_manager` and lands *inside* the DUT hierarchy; no `-tree` under
`u_dut` reaches it without dropping real DUT code.

The CPU exclusion keeps a large, barely-exercised third-party denominator out
of a SEP number -- only the `cpu` tests reach it. Coverage compiles the full
CPU once (`--target default`); the subtree is not instrumented.

## What the number is

The SEP DUT **minus the CPU subtree**. Not "SEP DUT coverage" -- say which.

Phase 1 FCOV is the URG **Group** report on `sep_uvm_top.u_sep_fcov`, not this
SCORE. That instance is a TB sampler, so its own line/cond weight is testbench,
not a DUT cone. The scope file does not `-tree` it out: covergroup collection
is what the instance is for, and its code weight is noise against the DUT
denominator.

## Measured, so the next attempt does not repeat these

- **An include-list does not restrict instrumentation.** `+tree sep_uvm_top.u_dut.u_sep`
  (with and without comments) left the design database at 3.2M against 3.4M
  unscoped: only the `-tree` exclusion took effect. VCS accepted the file
  silently either way. A scope that has to hold must name what to drop.
- **`urg -hier` at report time does not change the score.** It prunes report
  pages and grades the whole database: the hierarchy listing fell 85,152 ->
  49,771 lines while the total moved 24.72 -> 24.70. Scope belongs at compile
  time.
- **`-cm_hier` alone does not scope assertions.** It governs line, condition,
  FSM, toggle and branch only. Measured on a merged database: `sep_cpu`,
  `u_m_axi_sva` and `u_s_axi_sva` each reported an ASSERT score with every code
  column `--`, and the composite carried them. `-cm_common_hier` extends the same
  file to both families; after it, those instances leave the hierarchy entirely
  and `sep_uvm_top` matches `u_dut` in all six columns.
- **`-cm_common_hier` needs `-lca`.** VCS refuses the compile otherwise
  ("Limited Customer Availability feature is used ... requires a special
  option"). It is an opt-in switch, not a separate licence, and it stays in the
  SEP coverage compile args rather than becoming a global VCS default.

## Known residue

`axi_pkg` remains at top level with an ASSERT column, scoring 0.00. A package
rather than testbench hierarchy, and it contributes nothing to the total.
