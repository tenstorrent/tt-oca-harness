<!-- SPDX-License-Identifier: Apache-2.0 -->
<!-- SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. -->

# SMU VCS coverage scope

**Nothing here has been run on VCS.** No SMU coverage compile, merge or report
on VCS exists, so this directory has produced no score. It is the carrier that
puts scope and policy in the same place on SMU as on SEP
(`hw/sys/sep/dv/cov/config/vcs/`) and SMC (`hw/sys/smc/dv/cov/config/vcs/`);
the graded SMU policies today are the Verilator ones in `../verilator/`.

`[coverage.vcs]` in `smu_block_sim_cfg.toml` names
`smu_block_coverage_policy.toml` and nothing else, so the policy is reachable
and `--validate-configs` checks it, but no compile passes
`smu_cov_scope.hier`. Wiring it up means adding `-cm_hier <that file> -lca
-cm_common_hier` to `[coverage.vcs].compile_args`, the way
`hw/sys/smc/dv/smc_sim_cfg.toml` does.

The policy is named per DUT rather than left at the canonical
`cov/config/vcs/coverage_policy.toml`: `smu` and `smu_block` share this DV
root, so the canonical path resolves identically for both and whichever DUT the
file does not name fails `--validate-configs`. The Verilator policies next door
are split for the same reason.

## What `smu_cov_scope.hier` excludes

It is the hierarchy form of `../verilator/smu_cov_scope.vlt`, which scopes by
source path. The two must be kept in step by hand: Verilator's `coverage_off`
takes `-file` globs only, VCS scopes by instance tree, and neither can express
the other's form.

    -tree smu_uvm_top 1                       TB top's own body, children kept
    -tree smu_uvm_top.u_tb_if                 smu_tb_if.sv
    -tree smu_uvm_top.u_dtp_tb_if             dtp_tb_if.sv
    -tree smu_uvm_top.u_jtag_if               VIP interfaces and the struct
    -tree smu_uvm_top.u_axi_out_if            bridge, all hw/common
    -tree smu_uvm_top.u_axi_out_bridge
    -tree smu_uvm_top.u_smc_cpu_mem           chipyard-generated CPU memories
    -module ocah_jtag_sva                     the TAP protocol checker
    -tree smu_uvm_top.u_dut.u_smc             SMC subsystem
    -tree smu_uvm_top.u_dut.u_dtp             DTP subsystem
    -tree smu_uvm_top.u_dut.gen_sep.u_sep     SEP subsystem

Paths are the `--dut smu_block` bench (`smu_uvm_top`, DUT instance `u_dut`).
The wrapper bench is a different top, `smu_wrapper_uvm_top`, and is not named
here.

`-module` for the TAP checker rather than an instance path: both benches
instantiate it, and naming it by module covers either without a `-tree` that
also reaches real DUT code -- the same reason SEP names `ocah_axi_sva` that
way.

`smu_uvm_top.u_dut.gen_sep.u_sep` exists only on a SEP=1 elaboration. The
block bench hardcodes SEP=0, so on that bench the path resolves to nothing.
VCS accepts a `-tree` path that does not resolve **silently**, which is
convenient here and a hazard in general: an instance name that moves in an RTL
refactor leaves a scope file that looks right and excludes nothing.

## Why these exclusions

Each integration level grades what it owns. SMU instantiates SMC, DTP and SEP,
each of which has its own DV package and its own coverage; grading them again
here would attribute their holes to SMU and hide SMU's own interconnect inside
a denominator two orders of magnitude larger.

`hw/sys/smu/dv/cov/sv/*` is **not** excluded -- those files carry the
`OCAH_FCOV_COVER` points that populate the `user` metric family, and the
`u_smu_*_fcov` instances under the TB top are kept by the depth-1 form of the
first entry.

## Known gap

`vendor/**` and `hw/ip/**` are dropped by source pattern in the Verilator
scope and have no `-tree` equivalent: pulp `axi` and `common_cells` are
structural glue instantiated at dozens of distinct places, so no instance tree
reaches them without dropping real SMU RTL, and naming every vendored module
with `-module` would be unmaintainable. On VCS those sites would stay in the
denominator. `../verilator/smu_block_coverage_policy.toml` records the two
hierarchy selectors that close the equivalent Verilator gap.

## What the number would be

The SMU integration RTL **plus the vendored trees the tool cannot exclude**.
Not "SMU coverage" -- say which, as `../README.md` does for the Verilator
numbers.

## VCS behaviour a scope file depends on

- **An include-list does not restrict instrumentation.** `+tree` leaves the
  design database unscoped; only `-tree` takes effect, and VCS accepts the file
  silently either way. Name what to drop.
- **`urg -hier` at report time does not change the score.** It prunes report
  pages and grades the whole database. Scope belongs at compile time.
- **`-cm_hier` alone does not scope assertions.** It governs line, condition,
  FSM, toggle and branch only; without `-cm_common_hier` the excluded
  hierarchy leaves the code metrics but is still graded for assertions.
- **`-cm_common_hier` needs `-lca`.** VCS refuses the compile otherwise. It is
  an opt-in switch, not a separate licence.
