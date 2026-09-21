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

`-cm_tgl portsonly` in `[coverage.vcs]` keeps toggle on module ports, and with
the subtrees above dropped the ports that remain are `smu_wrapper`'s. urg then
reports two toggle figures for the module, and they answer different
questions:

* `Port Bits`: every bit of every port, each in both directions. This is the
  number urg puts in its `TOGGLE` column and in the dashboard score.
* `Ports`: urg's per-field view. A struct port is split into its fields and
  bit slices, and a row counts covered only when every bit of it toggled in
  both directions.

The interface figure in `SMU_COVERAGE_POLICY.adoc` is a third one: a port of
`smu_wrapper` has toggled when any bit of it moved in either direction, so a
256-bit struct port is one interface. `../../interface_toggle.py` derives it
from the urg text report (`urg -dir merged.vdb -report <dir> -format text
-metric tgl -show tests`, then pass its `modinfo.txt`) exactly as it does from
a Verilator database, so the two simulators are compared on one definition.

A `begin tgl(portsonly) ... end` block in the hierarchy file does not do this:
VCS keeps the excluded subtrees' toggle points when the metric block is
present, so the option is given on the command line instead.

`-cm_noconst` and `-cm_seqnoconst` drop nets a constant drives from the toggle
population, so a port the wrapper ties off is not a hole; the DTP scope sets
the same two options.

## Reading a finished run

```
python3 tools/dv/run_dv.py --dut smu --tool vcs --items hosted --cov --rebuild
python3 hw/sys/smu/dv/cov/interface_toggle.py <run dir>/cov/report/modinfo.txt \
    --module hw/top/smu_wrapper.sv
```

The first command prints the runner's families and grades them against
`smu_wrapper_coverage_policy.toml`, which floors `assertion` at 80 percent:
urg reads the cov/sv `cover property` points under its assert metric together
with the `assert property` statements left in scope, and
`cov/report/asserts.txt` splits the two. The second command folds the
`Port Details` rows of the report the first one wrote into the interface
figure; `--list` names the ports that never toggled. The runner's own
`toggle` column stays `Port Bits`.

No public CI job runs the VCS flow for this DUT.
