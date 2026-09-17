<!-- SPDX-License-Identifier: Apache-2.0 -->
<!-- SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. -->

# SMU wrapper VCS coverage scope

`smu_wrapper_cov_scope.hier` is passed to VCS at compile time as `-cm_hier`
plus `-cm_common_hier` (`[coverage.vcs]` in `smu_sim_cfg.toml`), so what it
drops never enters the coverage database. Edit the file then `--rebuild`; the
contents are not fingerprinted. It is the instance-tree form of
`../verilator/smu_wrapper_cov_scope.vlt`, which names the same trees by
source path; the two are kept in step by hand.

## What it excludes

    -tree smu_wrapper_uvm_top 1                          TB top's own body, children kept
    -tree smu_wrapper_uvm_top.u_dut.u_smu                the SMU block, graded on --dut smu_block
    -tree smu_wrapper_uvm_top.u_dut.u_smc_ip_integration SMC and its adopter-side collateral
    -tree smu_wrapper_uvm_top.u_dut.u_sep_ip_integration SEP and its adopter-side collateral

The wrapper is graded on its interface. Everything it instantiates is internal
logic with an owner of its own -- the SMU block on the block bench, SMC, DTP
and SEP in their own DV packages -- and grading it again here would attribute
their holes to SMU and bury the interface inside a denominator two orders of
magnitude larger. What remains is `hw/top/smu_wrapper.sv` itself and the
`cov/sv` functional-coverage modules under the TB top.

## Toggle on the ports only

    begin tgl(portsonly)
      +tree smu_wrapper_uvm_top.u_dut 0
    end

Toggle is collected on the ports of `smu_wrapper` and nothing else: `portsonly`
is urg's per-port view, in which a port has toggled when any of its bits has.
It is the same figure `../../interface_toggle.py` derives from a Verilator
database, where the per-bit points have to be folded back to the port by
hand. `-cm_common_hier` extends the scope to assertion coverage, which is what
carries the `cover property` points of the functional-coverage modules, so
`assert` stays in the `-cm` list.

No public CI job runs the VCS flow for this DUT; the scope is written to
mirror the Verilator one and has not been measured.
