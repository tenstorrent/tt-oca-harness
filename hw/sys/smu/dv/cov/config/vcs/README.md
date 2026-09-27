<!-- SPDX-License-Identifier: Apache-2.0 -->
<!-- SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. -->

# SMU VCS coverage scope

`smu_wrapper_cov_scope.hier` is passed to VCS at compile time as `-cm_hier`
plus `-cm_common_hier` (`[coverage.vcs]` in `smu_sim_cfg.toml`), so what it
drops never enters the coverage database. `gen_smu_cov_scope.py` writes it
from the build filelists; regenerate it after a build and `--rebuild`, and
`--check` tells whether the committed file is stale. The contents are not
fingerprinted, and VCS accepts a stale file silently.

    python3 tools/dv/run_dv.py --dut smu --items smoke      # any build
    python3 hw/sys/smu/dv/cov/config/vcs/gen_smu_cov_scope.py

## The rule

The scope follows the rule `hw/sys/sep/dv/cov/config/vcs/sep_cov_scope.hier`
states and `hw/sys/smc/dv/cov/config/vcs/smc_cov_scope.hier` applies, so the
three subsystems' signoff figures are read on one definition: the bench and
the library and interconnect cells leave the database, a block graded on a
bench of its own leaves as an instance tree, and the rest stays graded.

| Drop | Form | Why |
|---|---|---|
| TB top's own body | `-tree smu_wrapper_uvm_top 1` | testbench code; its children are named below or stay |
| `u_dut.u_smu.u_smc`, `u_dut.u_smu.u_dtp`, `u_dut.u_smu.gen_sep.u_sep` | `-tree` | SMC, DTP and SEP are graded on their own benches (`hw/sys/smc/dv`, `hw/sys/dtp/dv`, `hw/sys/sep/dv`); grading them here attributes their holes to SMU, the argument SMC uses to drop its I3C controllers |
| `u_dut.u_smc_ip_integration`, `u_dut.u_sep_ip_integration` | `-tree` | adopter-side collateral of SMC and SEP, owned by those packages |
| `u_axi_out_bridge`, `u_axi_out_cut`, `u_axi_out_if` | `-tree` | bench-side AXI egress glue carrying the outbound port to the bench slave |
| bench units (every unit compiled from a `dv/` directory: testbench tops, models, VIP and the `hw/common/dv/shims` wire models such as the open-drain cross-trigger wire) | `-module` | testbench code, wherever the bench instantiates it; no DUT source lives under `dv/`. A bench stand-in named like the product cell it replaces is listed once, as the product |
| library cells (pulp `common_cells`, OpenTitan `prim*`, OCAH `ocah_prim`) | `-module` | leaf primitives whose behaviour is the same in every design; the same list SMC drops |
| interconnect cells (vendored pulp AXI, APB, register_interface, AXI-Stream, OBI) | `-module` | the pulp `axi_xbar` inside `smu_axi_xbar` and the `axi_iw_converter` ID adapters; `smu_axi_xbar`, which configures and wraps them, stays graded, so a decode fault lands on SMU's own module |
| `axi_pkg` | `-module` | a package, which would report an assertion row with no logic behind it |
| `cov/sv` monitors | `-module` inside `begin line+cond+fsm+branch+tgl` | bench code for the code and toggle metrics; outside that block they stay in the assertion metric, which carries their `cover property` points, and their covergroups are outside `-cm_hier` altogether |

The `-module` lines are generated because VCS scopes by design unit or
instance and a library cell is instantiated where no `-tree` reaches it. VCS
warns `VCM-HFUFF` once per listed unit the elaboration did not instantiate;
that is the list being a superset of one build, not an error.

What stays graded is the SMU's own logic: `hw/top/smu_wrapper.sv`,
`hw/sys/smu/rtl/smu.sv`, `smu_axi_xbar.sv` and any other unit instantiated under `u_smu` outside the three subsystem trees.
urg's `hierarchy.txt` for a finished run is the check: at the top it lists
`u_dut` and the `cov/sv` monitors and nothing else, and under `u_dut` it lists
`u_smu` and, below it, only those units.

## Two populations

`../verilator/smu_wrapper_cov_scope.vlt` keeps a narrower set: it turns
coverage off for `hw/sys/smu/rtl/*` as well, so the public Verilator figure
is the wrapper and the `cov/sv` points, while the VCS figure is the SMU block
under the rule above. Verilator's `coverage_off` takes source-path globs
only, and the public runner compiles the coverage-instrumented model in a
fixed time budget, so widening its population is a separate decision with a
measurement of its own. Quote the flow with the number.

## Toggle on every net

Toggle covers every net of the units the scope keeps, in both directions, as
on the SMC scope. `-cm_tgl portsonly` is not used: with `u_smu` graded the
kept population is no longer one wiring module, and `smu.sv` and
`smu_axi_xbar.sv` hold the region registers, address decode and ID
remapping whose internal nets a ports-only count would hide. SMC grades a
unit of OpenTitan origin on its ports only, at report time; no unit the SMU
scope keeps is of OpenTitan origin (the OpenTitan units in the build are
library cells above or sit inside the SEP and SMC trees), so there is no such
file here.

`-cm_noconst` and `-cm_seqnoconst` drop nets a constant drives from the toggle
population, so a port tied off is not a hole; the DTP scope sets the same two
options.

## Port toggle exclusions

`smu_wrapper.sv` is wiring: three instances, no assign, no process, no
generate. Every port is a point-to-point connection to a subsystem port, so
the wrapper's ports are graded per field, with the fields below left out
through
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
| `RTL-CONSTANT` | `lsio_interface_select_o` | driven from a constant inside the SMU |
| `UNION-ALIAS` | `smc_shadow_regs_o.locks.*`, `smc_shadow_regs_o.fields.*` | `efuse_map_t` is a packed union; urg lists the same 8192 flops under three views, and `values` carries every bit once |
| `SEP-OWNED` | `sep_io_spi_req_o`, `sep_cpu_trace_o`, `sep_lockstep_*`, `sep_ext_interrupts_i`, `entropy_rosc_sample_clk_i`, `lc_sigint_err_o` | no wrapper-level observable; each is graded on the SEP bench |
| `OCTS-COUNT-DEPTH` | `timer_count_o[63:20]` | bit k first rises after 2^k reference clocks |
| `REGISTER-WIDTH` | `sep_region_size_o[55:32]` | `sep_cpu_ctrl` SEP_REGION_SIZE carries its size in [31:0] and reserves [63:32], so the port's upper bits are zero-extension; `smu_toggle_exclusions.el` takes the same bits of `smu`'s port |

Everything else on the port list is graded per field, both directions, and a
field that stays uncovered is a stimulus gap for a leaf on this bench.

## Block exclusions

`smu_toggle_exclusions.el` (`-elfile`, named by the policy's `[[native_files]]`)
leaves out toggle points of `smu`, `smu_wrapper` and `smu_axi_xbar`, and the
condition rows of the lifecycle integrity error, each for a stated fact. `gen_smu_cov_toggle_exclusions.py` writes
it from urg's `-dump full_exclusions` templates of the merged database and the
run's raw report, so every checksum and signature comes from urg, and
`--check` tells whether the committed file is stale:

    urg -dir <run dir>/cov/merged.vdb -dump full_exclusions tgl+cond+branch -report <dir>
    python3 hw/sys/smu/dv/cov/config/vcs/gen_smu_cov_toggle_exclusions.py \
        fullexclude_module.tgl <run dir>/cov/report_raw/modinfo.txt \
        --cond fullexclude_module.cond --branch fullexclude_module.branch

The file is generated from an `all` run, the coverage set: a point `all`
leaves uncovered is uncovered in `hosted` too, so the file holds for both.
An entry names only what the raw report marks uncovered: a toggle field wholly
uncovered is excluded whole, otherwise each uncovered range in the direction
the report marks missing, clipped to the bits a class names; a partly
uncovered multi-dimensional range stays graded; a condition row or branch arm
is taken only where the report says Not Covered. Fields
`smu_wrapper_toggle_exclusions.el` already names are skipped.

| Class | Fact | Retired by |
|---|---|---|
| `MEM-MACRO` | data, mask, strobe, parity and ECC words of the SMC and SEP RAM, ROM and TCM interfaces; `smu.sv` connects each such `u_smc`/`u_sep` port straight to its own port and `smu_wrapper.sv` connects that to `hw/top/smc_ip_integration.sv` or `hw/top/sep_ip_integration.sv`, where the macros are; no SMU logic reads or writes the words | an SMU process on these words, or the macros moving under `u_smu` |
| `AXI-USER` | the user sideband, which the pulp crossbar and the ID converters copy beside the channel | an SMU decode or remap that reads it |
| `AXI-DATA` | write data, write strobe and read data of every AXI and AXI-Lite channel; the SMU decodes addresses and converts ids and passes data through | an SMU unit that inspects or rewrites data or strobe |
| `RTL-CONSTANT` | `lsio_interface_select_o` following the SPI enable `smu.sv` assigns 1 with SEP present | the SPI enable becoming programmable |
| `UNION-ALIAS` | the `locks` and `fields` views of the packed-union eFuse shadow map; `values` stays graded | `efuse_map_t` ceasing to be a union |
| `SEP-OWNED` | `sep_io_spi_req_o`, `sep_cpu_trace_o`, the lockstep pair, `sep_ext_interrupts_i` and `entropy_rosc_sample_clk_i`, which `smu.sv` only routes and the SEP bench grades | SMU logic consuming one of them |
| `LC-SIGINT-ENCODED` | design fact: `efuse_shadow_regs.sv` (282-285, 350) keeps the raw 4-bit LC_STATE and re-encodes it with `prim_diff_encode_multi`, so the word the SEP exports is always a valid differential pair and the decoders in `sep_lifecycle_ctrl.sv` and `smc_efuse_wrapper.sv` fire only on corruption in flight. Takes `lc_sigint_err_o`, `sep_lc_sigint_err` and `efuse_lc_sigint_err` in `smu`, and the uncovered rows of the `smu.sv` assignments to `lc_sigint_err_o`, which the generator finds in the source | a fault-injection bench that corrupts the exported pair |
| `ATOP-DISABLED` | `smu_axi_xbar.sv` (131) builds the crossbar with `ATOPs(1'b0)` and `tb_wrapper_top.sv` ties the inbound AWATOP to 0; takes every `aw.atop` field | a crossbar built with ATOPs enabled |
| `FIXED-OUTBOUND-ATTRIBUTES` | AxCACHE, AxPROT, AxQOS, AxREGION, AxLOCK and AxBURST on `smc_output_axi_req` and the crossbar's `smc_out` port; both SMC masters a toolchain-free leaf drives hold them constant (`jtag2axi.sv` 1184-1216, the iDMA frontend `idma_reg.sv.tpl` 155-159). The crossbar's `ext_out` side and `smu_axi_out` also carry SEP traffic and stay graded | outbound traffic from the SMC CPU |
| `APERTURE-ALIGNMENT` | `smc_base_config.rdl` (38) requires GLOBAL_BASE and LOCAL_BASE to be aligned to REGION_SIZE; JTAG2AXI reaches BASE_CONFIG through the local window, so no size below 128 KiB can be followed by another setting, and base, rule start and rule end bits [16:0] stay 0; LOCAL_BASE is fixed at `0xC000_0000`, so REGION_SIZE[31] is never legal. Takes only those bits | a programmable LOCAL_BASE or a BASE_CONFIG path outside the local window |

The SEP aperture and the SEP's outbound and dedicated SMC channels take no
class: SEP firmware images program the region size,
`smu_dtp_sep_dm_sba_test` programs the base and sends a read and a write
out through the crossbar, and `smu_sep_bidirect_test` drives the dedicated
channel, so a bit left uncovered there is a stimulus gap.

Cover properties are not excluded here. The ones a legal operating mode of
this bench cannot reach -- the two EXOKAY responses, the lifecycle
signal-integrity error and the zero SMC window -- are the Phase 2 set of
`hw/sys/smu/dv/docs/SMU_FCOV.adoc`, left out of the compile rather than
excluded from a report.

Address, id and handshake fields outside the classes that name them stay
graded, and a hole in one is a stimulus gap.

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
python3 tools/dv/run_dv.py --dut smu --tool vcs --items all --cov
```

`all` is the coverage set, as it is for SEP: the 108 leaves of the package
regression, including the SEP firmware and lifecycle leaves whose images the
`c_compile` stage builds with the RISC-V toolchain. `hosted` is the
toolchain-free subset the workflows run and leaves that stimulus out.

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
The same payload, sideband and SEP-owned fields reappear as ports and nets of
`smu` and are graded there until a class of the same kind names them.

No public CI job runs the VCS flow for this DUT.
