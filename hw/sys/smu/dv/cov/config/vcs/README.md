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
    -tree smu_wrapper_uvm_top.u_dut.u_smu                the SMU block
    -tree smu_wrapper_uvm_top.u_dut.u_smc_ip_integration SMC and its adopter-side collateral
    -tree smu_wrapper_uvm_top.u_dut.u_sep_ip_integration SEP and its adopter-side collateral
    -tree smu_wrapper_uvm_top.u_axi_out_bridge           bench-side AXI egress glue: the struct
    -tree smu_wrapper_uvm_top.u_axi_out_cut               bridge, register cut and interface that
    -tree smu_wrapper_uvm_top.u_axi_out_if                carry the DUT's outbound port to the
                                                          bench slave; testbench code, not DUT
    begin assert / -tree axi_pkg / end                    package-level assertions of the vendored
                                                          AXI package

The wrapper is graded on its interface. Everything it instantiates is internal
logic: SMC, DTP and SEP are graded in their own DV packages, and the SMU
block's own nets are the wiring between them. Grading any of it here would
attribute their holes to SMU and bury the interface inside a denominator two
orders of magnitude larger. What remains is `hw/top/smu_wrapper.sv` itself and the
`cov/sv` functional-coverage modules under the TB top. urg's `hierarchy.txt`
for a finished run is the check: it lists `u_dut` and the ten `u_smu_*_fcov`
instances and nothing under `u_dut`.

## Toggle on the ports only

`-cm_tgl portsonly` in `[coverage.vcs]` keeps toggle on module ports, and with
the subtrees above dropped the ports that remain are `smu_wrapper`'s. The
graded figure is urg's `TOGGLE` column, the `Port Bits` row of the module's
section in `modinfo.txt`: every bit of every port, each in both directions,
after the exclusions below. That is the runner's `toggle` family, the one
every DUT is graded on. urg also prints a `Ports` row, its per-field view in
which a struct field counts only when every bit of it toggled both ways; it
is informative and is not graded.

A `begin tgl(portsonly) ... end` block in the hierarchy file does not do this:
VCS keeps the excluded subtrees' toggle points when the metric block is
present, so the option is given on the command line instead.

`-cm_noconst` and `-cm_seqnoconst` drop nets a constant drives from the toggle
population, so a port the wrapper ties off is not a hole; the DTP scope sets
the same two options.

## Port toggle exclusions

`smu_wrapper.sv` is wiring: three instances, no assign, no process, no
generate. Every port is a point-to-point connection to a subsystem port, so
the wrapper's toggle is graded on urg's per-field `Ports` view of its own
ports, with the fields below left out through
`smu_wrapper_toggle_exclusions.el` (`-elfile`, named by the policy's
`[[native_files]]`). `gen_smu_wrapper_toggle_exclusions.py` writes that file
from urg's `-dump full_exclusions tgl` template of the merged database, so the
module checksum and every field signature come from urg, and `--check` tells
whether the committed file is stale.

| Class | Fields | Why they are not the wrapper's to toggle |
|---|---|---|
| `AXI-USER` | `aw/ar/w/r/b.user` on both crossbar ports | the SMU neither reads nor writes the user sideband |
| `AXI-DATA` | `w.data`, `w.strb`, `r.data` on both crossbar ports | the data path passes through untouched; address and id stay graded because the crossbar decodes and remaps them |
| `ATB-PAYLOAD` | `telemetry_atdata_i`, `telemetry_atid_i` | consumed by the SMC telemetry receivers, graded there |
| `DFT` | `test_en_i`, `scan_rst_ni` | held at their functional value in simulation |
| `RTL-CONSTANT` | `lcc_demote_state_*_o`, `lsio_interface_select_o` | driven from a constant inside the SMU |
| `UNION-ALIAS` | `smc_shadow_regs_o.locks.*`, `smc_shadow_regs_o.fields.*` | `efuse_map_t` is a packed union; urg lists the same 8192 flops under three views, and `values` carries every bit once |
| `SEP-OWNED` | `sep_io_spi_req_o`, `sep_cpu_trace_o`, `sep_lockstep_*`, `sep_global_base_o`, `sep_region_size_o`, `sep_ext_interrupts_i`, `entropy_rosc_sample_clk_i`, `lc_sigint_err_o` | no wrapper-level observable; each is graded on the SEP bench |
| `PARTIAL` | `timer_count_o[63:20]` | bit k first rises after 2^k reference clocks |

Everything else on the port list is graded per field, both directions, and a
field that stays uncovered is a stimulus gap for a leaf on this bench.

## Covergroups from vendored RTL

`-cm_hier` scopes line, condition, FSM, toggle and branch, and `-cm_common_hier`
extends it to assertions; neither reaches a covergroup. A covergroup declared
inside RTL is graded wherever the elaboration instantiates it, so the six
`cg_bus_event_fsm_transitions` groups the chipsalliance I3C core declares in
`i3c_target_fsm.sv` land in urg's GROUP score beside the wrapper's own
`cov/sv` covergroups, and none of the wrapper leaves drive an I3C bus event.
`smu_wrapper_group_exclusions.el` (`-elfile`, named by the policy's
`[[native_files]]`) drops them at report time.
`gen_smu_wrapper_group_exclusions.py` writes that file from urg's
`-dump full_exclusions group` template of the merged database, so the
definition checksum and every instance path come from urg, and `--check`
tells whether the committed file is stale. Every covergroup under `u_dut`
must fall in a class the script names; one that does not stops the script,
so a covergroup a future vendored block adds is a decision, not a silent
inclusion.

| Class | Covergroups | Why they are not the wrapper's to fill |
|---|---|---|
| `VENDORED-I3C` | `xi3c_target_fsm::cg_bus_event_fsm_transitions`, six instances | the I3C controllers' internals are graded by `hw/ip/i3ccore_wrap/dv`; the wrapper reaches them only through the SMC |

What remains in GROUP is the `u_smu_*_fcov::cg_*` set, the covergroup half of
the wrapper's functional coverage; `cov/sv` cover properties are the other
half and are read under `assertion`.

## Reading a finished run

```
python3 tools/dv/run_dv.py --dut smu --tool vcs --items hosted --cov
```

The runner compiles with the scope, runs the group, merges, writes the urg
report with the exclusion files, and prints one `coverage` line with every
family as raw/effective; `smu_wrapper_coverage_policy.toml` floors `toggle`
and `assertion` at 80 percent and the result carries `coverage=PASS` or
`FAIL`. Nothing else is run. `toggle` is urg's TOGGLE column after the
exclusions; `assertion` is where urg reads the cov/sv `cover property` points,
together with the `assert property` statements left in scope, and
`cov/report/asserts.txt` splits the two. Per-port detail is in the `Port
Details` rows of the module's section in `cov/report/modinfo.txt`, with
`Excluded` and the class annotation on every field the exclusion file dropped.

No public CI job runs the VCS flow for this DUT.
