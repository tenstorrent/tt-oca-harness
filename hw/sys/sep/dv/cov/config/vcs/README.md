<!-- SPDX-License-Identifier: Apache-2.0 -->
<!-- SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. -->

# SEP VCS coverage scope

`sep_cov_scope.hier` is passed to VCS at compile time as `-cm_hier` plus
`-cm_common_hier` (`[coverage.vcs]` in `sep_sim_cfg.toml`), so what it drops
never enters the coverage database. The file's hash and the coverage arg list
are both folded into the build fingerprint: edit either and the next `--cov` run
recompiles instead of reusing a build instrumented under the old scope.

## What it excludes

    -tree sep_uvm_top 1                       TB top's own body, children kept
    -tree sep_uvm_top.u_smc_mem               axi_sim_mem backdoor (rom_boot only)
    -tree sep_uvm_top.u_mbx                   sep_outbound_mbx
    -module ocah_axi_sva                      u_m_axi_sva, u_s_axi_sva, key_manager bind
    -tree sep_uvm_top.u_dut.u_sep.sep_cpu     CPU subtree

`-module` rather than instance paths for the SVA, because the third instance is
a `bind key_manager` and lands *inside* the DUT hierarchy; no `-tree` under
`u_dut` reaches it without dropping real DUT code.

The CPU exclusion does two jobs. It keeps a large, barely-exercised third-party
denominator out of a SEP number -- only the `cpu` tests reach it. It is also what
makes the cross-target merge sound: `sep.sv` instantiates `sep_cpu sep_cpu`, and
the CPU-stub target's `sep_cpu_stub.sv` declares `module sep_cpu` too, so the
same instance path carries two unrelated bodies. `urg` accumulates by hierarchy
name and would otherwise sum bins that do not correspond.

## What the number is

The SEP DUT **minus the CPU subtree**. Not "SEP DUT coverage" -- say which.

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
