<!-- SPDX-License-Identifier: Apache-2.0 -->
<!-- SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. -->

# SMC coverage scope

SMC scopes coverage in two files because the two simulators scope by different
things, and neither can express the other's form:

| File | Flow | Mechanism |
| --- | --- | --- |
| `../verilator/smc_cov_scope.vlt` | public CI (graded) | `coverage_off -file`, globs |
| `smc_cov_scope.hier` | commercial signoff | `-cm_hier` / `-cm_common_hier`, instance trees |

Both are applied at **compile** time, following what SEP measured
(`hw/sys/sep/dv/cov/config/vcs/README.md`): a report-time filter prunes the
report pages and still grades the whole database, so scope that has to hold
must keep the code out of the database. Edit either file then `--rebuild` —
neither is fingerprinted.

**The two files must be kept in step by hand.** They do not express the same
set, and cannot:

- Verilator's `coverage_off` takes `-file` only. There is no `-module` form;
  `coverage_off -module "prim_rom"` is a syntax error. Globbing source paths
  makes dropping all of `vendor/**` a one-liner.
- VCS scopes by hierarchy. Vendored pulp `axi` / `common_cells` are structural
  glue instantiated at dozens of distinct places, so no `-tree` reaches them
  without dropping real SMC RTL, and naming every vendored module with
  `-module` would be unmaintainable. The VCS file therefore names
  the two vendored blocks that *do* sit under one instance each — i3c-core and
  tt-hw-debug — and leaves pulp glue in.

## What the numbers are

Say which one you are quoting.

- **Verilator**: the SMC DUT **minus the CPU cluster, the I3C core, the
  lowRISC prims, and TB code** — pulp glue and tt-hw-debug still counted, see
  the known gap below.
- **VCS**: the SMC DUT **minus the CPU cluster, the I3C core, the debug-bus
  block, and TB code** — pulp glue still counted.

Neither is "SMC coverage". The two exclude overlapping but different sets, so
they are not comparable to each other either.

## What each file excludes

### `smc_cov_scope.hier` (VCS)

    -tree smc_uvm_top 1                     TB top's own body, children kept
    -tree ...u_smc_cpu_wrapper.u_smc_cpu      chipyard-generated CPU cluster
    -tree ...u_smc_peripherals.u_i3ccore_wrapper  vendored i3c-core
    -tree ...u_internal_regs.u_smc_dfd_wrap   vendored tt-hw-debug trace/mmr

Each vendored tree is 100% contained by that one instance.

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
score; only its interface instance and struct bridge sit in the TB body. The
VCS `.hier` file has no equivalent gap for the blocks it names by instance.

The `hw/ip/**` and `hw/common/**` exclusion has no `.hier` equivalent either:
VCS scopes by instance tree and those blocks are instantiated in dozens of
places, so the commercial number still includes them until the `.hier` file
names each tree.

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

On a VCS run check that: the compile accepts `-lca -cm_common_hier`; the
`-tree` paths in `smc_cov_scope.hier` resolve (instance names move when RTL is
refactored, and VCS accepts a stale scope file silently); and `u_dut` matches
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
