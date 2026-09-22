<!-- SPDX-License-Identifier: Apache-2.0 -->
<!-- SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. -->

# SMC coverage scope

SMC scopes coverage in two files because the two simulators scope by different
things, and the two flows answer different questions:

| File | Flow | Mechanism | Population |
| --- | --- | --- | --- |
| `smc_cov_scope.hier` | commercial signoff | `-cm_hier` / `-cm_common_hier`, design units named by `gen_smc_cov_scope.py` | the SEP rule: DUT minus the bench, the CPU subtree and the library cells; functional third-party IP stays graded |
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
    // bench                   units compiled from hw/sys/smc/dv/tb and
                               hw/sys/smc/dv/models
    // cpu subtree             the chipyard-generated CPU cluster, the same
                               argument SEP uses to drop sep_cpu
    // library cells           vendor/pulp-platform/common_cells and the
                               OpenTitan prim library, the cells SEP drops
    // package                 axi_pkg, which would report an assertion row
                               with no logic behind it

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

## Why these exclusions

The chipyard-generated CPU cluster dominates the unscoped denominator and is
reached only by the CPU-boot tests, so an unscoped headline is a statement
about a core nobody grades here -- the same reason SEP drops `sep_cpu`. The
library cells (pulp `common_cells`, OpenTitan `prim*`) are leaf primitives
whose branches depend on parameters no SMC test chooses. Everything else the
build compiles stays graded: the vendored I3C controller, DMA, debug and trace
blocks and AXI fabric, and the `hw/ip` and `hw/common` blocks SMC integrates,
because SMC tests drive them by name and their reachability from the SMC
boundary is part of what this bench claims. The Verilator public-CI scope
keeps the narrower owned-files set for the reasons above.

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
