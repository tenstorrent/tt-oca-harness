<!-- SPDX-License-Identifier: Apache-2.0 -->
<!-- SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. -->

# SMC coverage scope

SMC scopes coverage in two files because the two simulators scope by different
things, and neither can express the other's form:

| File | Flow | Mechanism |
| --- | --- | --- |
| `../verilator/smc_cov_scope.vlt` | public CI (graded) | `coverage_off -file`, globs |
| `smc_cov_scope.hier` | commercial signoff | `-cm_hier` / `-cm_common_hier`, design units named by `gen_smc_cov_scope.py` |

Both are applied at **compile** time, following what SEP measured
(`hw/sys/sep/dv/cov/config/vcs/README.md`): a report-time filter prunes the
report pages and still grades the whole database, so scope that has to hold
must keep the code out of the database. Edit either file then `--rebuild` —
neither is fingerprinted.

**The two files express one set.** Verilator's `coverage_off` takes `-file`
only, so the Verilator file drops trees by source path with globs. VCS scopes
by design unit or instance, and the trees SMC does not own -- vendored RTL,
`hw/ip`, `hw/common`, the chipyard-generated CPU cluster, the bench's own
models -- are instantiated at hundreds of places inside SMC's own modules, so
no `-tree` reaches them without dropping real SMC RTL. `gen_smc_cov_scope.py`
therefore reads the build filelists, takes every module, interface and
program compiled from those trees, and writes one `-module` line per unit;
the file is regenerated (`--check` says when it is stale) rather than kept by
hand.

## What the numbers are

Both grade what SMC owns: `hw/sys/smc/rtl/**` (less the chipyard-generated
cluster), `hw/sys/smc/regs/**`, the two `hw/top` integration shells and the
`cov/sv` points. They still differ in what a point is -- Verilator's
expression family against VCS's condition, FSM and toggle -- and Verilator
5.050 leaves some vendored files instrumented that VCS drops (the known gap
below), so quote the simulator with the number.

## What each file excludes

### `smc_cov_scope.hier` (VCS)

    -tree smc_uvm_top 1        TB top's own body, children kept
    -module <unit>             one line per design unit compiled from
                               vendor/, hw/ip/, hw/common/, the chipyard-
                               generated cluster, hw/sys/smc/dv/tb and
                               hw/sys/smc/dv/models

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

Third-party RTL and the chipyard-generated CPU cluster dominate the unscoped
denominator and are barely exercised by SMC-level tests, so an unscoped
headline is a statement about someone else's code — the same reason SEP drops
`sep_cpu`. `hw/ip/**` and `hw/common/**` are dropped for the same reason the SMU
and DTP scopes drop them: each block there carries its own DV package and its
own coverage, and grading its internals again here attributes its holes to SMC
and hides SMC's own integration inside a denominator an order of magnitude
larger. What SMC grades is what it owns: `hw/sys/smc/rtl/**`, `hw/sys/smc/regs/**`
and the `cov/sv` points. Whether an integrated block is *reached* from the SMC
boundary is a functional-coverage question and is answered by the `user` points,
not by that block's line count.

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
