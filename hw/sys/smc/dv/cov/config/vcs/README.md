<!-- SPDX-License-Identifier: Apache-2.0 -->
<!-- SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. -->

# SMC coverage scope

SMC scopes coverage in two files because the two simulators scope by different
things, and the two flows answer different questions:

| File | Flow | Mechanism | Population |
| --- | --- | --- | --- |
| `smc_cov_scope.hier` | commercial signoff | `-cm_hier` / `-cm_common_hier`, design units named by `gen_smc_cov_scope.py` | the SEP rule: DUT minus the bench, the CPU subtree, the library and interconnect cells and the I3C controllers; every other functional third-party IP stays graded |
| `../verilator/smc_cov_scope.vlt` | public CI | `coverage_off -file`, globs | what SMC owns: `hw/sys/smc/rtl/**`, `hw/sys/smc/regs/**`, the `hw/top` shells and the `cov/sv` points |

Both are applied at **compile** time, following what SEP measured
(`hw/sys/sep/dv/cov/config/vcs/README.md`): a report-time filter prunes the
report pages and still grades the whole database, so scope that has to hold
must keep the code out of the database. Edit either file then `--rebuild` --
neither is fingerprinted.

The VCS scope follows the rule `hw/sys/sep/dv/cov/config/vcs/sep_cov_scope.hier`
states, so the two subsystems' signoff figures are read on one definition:
the bench, the CPU subtree and the library cells leave the database, and
functional third-party IP stays graded regardless of authorship, because SMC
tests target it by name (the I3C controller, the DMA, the debug and trace
blocks, the AXI fabric). VCS scopes by design unit or instance, and those
trees are instantiated at hundreds of places inside SMC's own modules where
no `-tree` reaches them, so `gen_smc_cov_scope.py` reads the build filelists,
takes every module, interface and program compiled from the dropped trees,
and writes one `-module` line per unit under the reason it leaves; the file is
regenerated (`--check` says when it is stale) rather than kept by hand.

The Verilator scope keeps the narrower owned-files set. Verilator's
`coverage_off` takes source-path globs only, it does not apply to a file whose
last line has no newline (which is the state of several vendored files), and
the public runner compiles the coverage-instrumented model within a fixed
time budget, so widening its population to the vendored trees is a separate
decision with a measurement of its own.

## What the numbers are

The VCS figure is the SMC DUT minus the CPU subtree and the library cells,
functional third-party IP included. Not "SMC-owned RTL coverage": say which.
The Verilator figure is SMC-owned RTL. They also differ in what a point is --
Verilator's expression family against VCS's condition, FSM and toggle -- and
Verilator 5.050 leaves some vendored files instrumented that its scope names
(the known gap below), so quote the flow with the number.

## What each file excludes

### `smc_cov_scope.hier` (VCS)

    -tree smc_uvm_top 1        TB top's own body, children kept
    // bench                   units compiled from hw/sys/smc/dv/tb,
                               hw/sys/smc/dv/models and the dv/ trees of the
                               hw/ip blocks (the eFuse bank model and its
                               register block), as SEP drops efuse_bank_model
    // cpu subtree             the chipyard-generated CPU cluster, the same
                               argument SEP uses to drop sep_cpu
    // library cells           vendor/pulp-platform/common_cells, the OpenTitan
                               prim library (the cells SEP drops) and the OCAH
                               och_prim library, the same kind of leaf cell
    // interconnect cells      the vendored pulp AXI, APB, register_interface,
                               AXI-Stream and OBI mux, demux, crossbar and
                               converter children; the SMC fabric wrappers that
                               instantiate them stay graded, so a decode or
                               isolation fault still lands on SMC's own module
    // package                 axi_pkg, which would report an assertion row
                               with no logic behind it
    // i3c controllers         -tree ...u_smc_peripherals.u_i3ccore_wrapper: the six
                               I3C controllers and their AXI-Lite demux, a large
                               third-party block that one SMC leaf reaches and
                               that has its own bench (hw/ip/i3ccore_wrap/dv),
                               the same argument SEP uses to drop sep_cpu

The `-module` lines are generated:

    python3 tools/dv/run_dv.py --dut smc --items smoke      # any build
    python3 hw/sys/smc/dv/cov/config/vcs/gen_smc_cov_scope.py

VCS warns `VCM-HFUFF` once per listed unit the current elaboration did not
instantiate; that is the list being a superset of one build, not an error.

### `../verilator/smc_cov_scope.vlt`

Same intent expressed over source paths. These are the patterns the file
carries, verbatim — note the absence of a `/` after the leading `*`, for the
reason under "Verilator glob matching" below:

    coverage_off -file "*hw/sys/smc/dv/tb/tb_top.sv"
    coverage_off -file "*hw/sys/smc/dv/tb/smc_tb_if.sv"
    coverage_off -file "*hw/sys/smc/dv/tb/verilator_stubs/*"
    coverage_off -file "*hw/sys/smc/dv/models/*"
    coverage_off -file "*chipyard_generated_files/*"
    coverage_off -file "*vendor/*"

`hw/sys/smc/dv/cov/sv/*` is **not** excluded — those files carry
the `OCAH_FCOV_COVER` points that populate the `user` metric family.

## Exclusion files

`coverage_policy.toml` beside this file names five `-elfile` files the report
applies, the form `hw/sys/sep/dv/cov/config/vcs/coverage_policy.toml` uses.
The first four are written by `gen_smc_cov_exclusions.py` from urg's exclusion
templates and the run's raw report (`cov/report_raw`, written without the
exclusion files). The condition, branch and F2 entries list only points that
report marks uncovered, so a reachable point is never hidden by a pattern;
F1 and F3 take a whole state variable that is not a reachable control FSM, F4
a state whose decode arm a parameter leaves unelaborated, F5 the uncovered
edges that exist only as a state register's reset assignment, and F6 those a
state register's enable-edge load cannot reach:

    urg -dir <run dir>/cov/merged.vdb -dump full_exclusions cond+branch+fsm -report <dir>
    python3 hw/sys/smc/dv/cov/config/vcs/gen_smc_cov_exclusions.py <dir> <run dir>/cov/report_raw/modinfo.txt

| File | Class | Fact |
| --- | --- | --- |
| `smc_regblock_exclusions.el` | A1 NO-STALL | a PeakRDL regblock without external registers hardwires `cpuif_req_stall_rd/wr` to zero: the valid-without-ready row of each AXI-Lite handshake condition and the stall branches cannot occur |
| `smc_regblock_exclusions.el` | A2 NO-ERROR | a regblock generated with "No valid address check" never sets `decoded_err`, `cpuif_wr_err` or `cpuif_rd_err`: its error branches and SLVERR responses cannot occur |
| `smc_regblock_exclusions.el` | A3 NO-READ-CHANNEL | the UART's read-channel select has no branch for the write-only register map, so that block's AR channel is never driven and no access can produce a condition over it |
| `smc_regblock_exclusions.el` | A4 READ-NEVER-ERRORS | in the vendored iDMA register top `reg_re` and `reg_we` are mutually exclusive, `wr_err` is gated on `reg_we` and `addrmiss` requires that no address hit, so the per-address read term crossed with an error cannot occur |
| `smc_regblock_exclusions.el` | A5 INPUT-UNCONNECTED | the SMC integration leaves that block's `devmode_i` unconnected, so the explicit-error-on-unmapped-access term it gates never evaluates true |
| `smc_xor_network_exclusions.el` | X1 XOR-NETWORK | a CRC or parity network is an XOR of four or more terms; condition coverage enumerates 2^n input combinations of a function the tests compare by its output |
| `smc_fsm_exclusions.el` | F1 LOOPVAR | `telemetry_receiver.block_index` is the message decoder's loop variable, extracted as an FSM because it is a state-shaped register; its settled value is fixed by `NUM_BLOCKS_PER_PACKET`, and urg's FSM score counts transitions, which no ATB stimulus can move |
| `smc_fsm_exclusions.el` | F2 DEFAULT | `avsbus_controller.cur_state` has `next_state = AVS_IDLE` as its always_comb default, which the extractor lists as an edge from every state to AVS_IDLE; every case arm assigns next_state, so the default never fires |
| `smc_fsm_exclusions.el` | F3 TIEOFF | `trace_axi_master.state` cannot leave RESET_VALUE: `smc_dfd_wrap` ties every `m_trc_axi_*` response input to zero, so the write master never sees a handshake |
| `smc_fsm_exclusions.el` | F4 PARAM-OFF | `efuse_interface_controller.efuse_reg_select` selects EFUSE_MMR_REG_MAP only when the instance has lifecycle state (`hw/ip/efuse/doc/memmap.adoc`); `smc_efuse_wrapper` sets `HAS_LC_STATE = 0`, so the arm is not elaborated and the state and its edges have no access that reaches them |
| `smc_fsm_exclusions.el` | F5 RESET-EDGE | a state register's reset assignment is expanded into a transition from every state; where no case arm assigns the reset state, the edge exists only if the block's reset is asserted while the FSM occupies that one state, and the package grades reset behaviour through its reset leaves |
| `smc_fsm_exclusions.el` | F6 ENABLE-EDGE | the bus monitor loads StBusBusyHigh only on the monitor enable's rising edge in multi-controller mode, and its disabled branch parks the register at StBusFree, so an edge into it from any other state cannot occur |
| `smc_disabled_feature_exclusions.el` | P1 NTRACE-OFF | the DFD top instantiates the trace wrapper with `NUM_NTRACE_INST(0)` and `NTRACE_SUPPORT(0)`, so the trace sink's N-trace half has no source; only its uncovered `trntr` conditions are listed |
| `smc_disabled_feature_exclusions.el` | P2 SKIP-TIED-OFF | both SMC fabrics instantiate the AXI filter with `filter_skip_i` tied to zero, so the skip arm of its filter decision never runs |
| `smc_disabled_feature_exclusions.el` | P3 WREN-TIED | the CLA assigns twenty of its MMR hardware write-enables a constant one (`cla_counter.sv`, `core_logic_analyzer.sv`), so the enable never reads zero and the write-data ternary never takes its else arm |
| `smc_disabled_feature_exclusions.el` | P4 SINGLE-SOURCE | with one trace source the two-source term of `TrRamPendPkt*WrEn` is always false and the per-way pending count, which only increments from those enables, stays at zero (`trace_sink.sv` pending logic); every `TrRamPend*` and south-port condition follows |
| `smc_disabled_feature_exclusions.el` | P5 INSTR-TYPE-CONST | `reg_wr_instr_type` has no driver outside the MMR files, so the other instruction-type encoding is never presented |

A regblock whose stall is `external_pending` (it has external registers)
gets A2 only; a regblock that decodes errors gets neither. `--check` reports
when the committed files no longer match the templates.

The fifth file is a covergroup exclusion. `-cm_hier` scopes line, condition,
FSM, toggle and branch, and `-cm_common_hier` extends it to assertions;
neither reaches a covergroup, so a covergroup declared inside RTL is graded
wherever the elaboration instantiates it. The six
`cg_bus_event_fsm_transitions` groups the chipsalliance I3C core declares in
`i3c_target_fsm.sv` therefore land in urg's GROUP score beside SMC's own
`cov/sv` covergroups even though the scope file drops the `u_i3ccore_wrapper`
tree from every code metric. `gen_smc_group_exclusions.py` writes
`smc_group_exclusions.el` from urg's group template, so the definition
checksum and every instance path come from urg, and `--check` tells whether
the committed file is stale. Every covergroup under `u_dut` must fall in a
class the script names; one that does not stops the script.

    urg -dir <run dir>/cov/merged.vdb -dump full_exclusions group -report <dir>
    python3 hw/sys/smc/dv/cov/config/vcs/gen_smc_group_exclusions.py <dir>/fullexclude.tb_def

| File | Class | Fact |
| --- | --- | --- |
| `smc_group_exclusions.el` | VENDORED-I3C | the I3C controllers' internals are graded by `hw/ip/i3ccore_wrap/dv`; SMC reaches them through its own fabric and grades that reach with the `cov/sv` points |

What remains in GROUP is the `u_smc_*_fcov::cg_*` set, the covergroup half of
SMC's functional coverage; the `cov/sv` cover properties are the other half
and are read under `assertion`.

## Why these exclusions

The chipyard-generated CPU cluster dominates the unscoped denominator and is
reached only by the CPU-boot tests, so an unscoped headline is a statement
about a core nobody grades here -- the same reason SEP drops `sep_cpu`. The
six I3C controllers are the same case at the peripheral level: one SMC leaf
reaches them, they carried three fifths of the uncovered points under the
SEP rule, and `hw/ip/i3ccore_wrap/dv` grades their internals. The library
cells (pulp `common_cells`, OpenTitan `prim*`, OCAH `och_prim`) are leaf
primitives whose branches depend on parameters no SMC test chooses, and the
vendored interconnect cells (pulp AXI/APB mux, demux, crossbar and converter
children) are the same kind of parameterised library inside the fabric; SMC's
own fabric wrappers around them stay graded. Everything else the build
compiles stays graded: the vendored DMA, debug and trace blocks, and the
`hw/ip` and `hw/common` blocks SMC integrates, because SMC tests drive them
by name and their reachability from the SMC boundary is part of what this
bench claims. The Verilator public-CI scope keeps the narrower
owned-files set for the reasons above.

## Known gap in the Verilator scope

`coverage_off -file "*vendor/*"` drops chipsalliance/i3c-core and
lowRISC/opentitan but **not** `vendor/pulp-platform/**` or
`vendor/tenstorrent/tt-hw-debug/**`. No file pattern reaches those two trees
(`*pulp-platform/*` and `*tt-hw-debug/*` are inert), so they stay in the
denominator. Patterns that do nothing are not carried in the scope file:
config that looks like scope and does nothing is worse than a documented gap.

The SYS_OUT responder is the shared VIP slave agent, class code with no RTL to
score; only its interface instance and struct bridge sit in the TB body. VCS
has no equivalent gap: `-module` names every unit regardless of where its
source file ends.

## Verilator glob matching

`coverage_off -file` matches the path as Verilator **opened** the file, not the
absolute path it records in the generated code. The filelist is absolute, but
files reached through `+incdir+` are opened relative, so a pattern has to cover
both forms:

| Pattern | relative open | absolute open |
| --- | --- | --- |
| `*/vendor/*` | not matched | matched |
| `*vendor/*` | matched | matched |
| `*vendor*` | matched | matched |

A leading `*/` therefore scopes only half the tree and says nothing about it.
The relatively-opened half then stays fully instrumented while the build
succeeds and nothing warns. Verify a scope
change by counting `__vlCoverInsert` sites per source bucket in the generated
model, not by the build passing.

## VCS bring-up checklist

On a VCS run check that: the compile accepts `-lca -cm_common_hier`; 
`gen_smc_cov_scope.py --check` passes (a unit added to a vendored tree since
the file was generated would otherwise be graded, and VCS accepts a stale
scope file silently); and `u_dut` matches
`smc_uvm_top` in every column, which is what shows assertions were scoped too.

## VCS scope behaviour

- **An include-list does not restrict instrumentation.** `+tree` leaves the
  design database unscoped; only `-tree` takes effect, and VCS accepts the
  file silently either way. Name what to drop.
- **`-cm_hier` alone does not scope assertions.** It governs line, condition,
  FSM, toggle and branch only; without `-cm_common_hier` the excluded
  hierarchy is gone from the code metrics but still graded for assertions.
- **`-cm_common_hier` needs `-lca`.** An opt-in switch, not a separate
  licence.
