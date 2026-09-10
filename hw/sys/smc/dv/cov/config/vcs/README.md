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
  glue instantiated at 20 and 35 distinct places respectively, so no `-tree`
  reaches them without dropping real SMC RTL, and naming all 160 vendored
  modules with `-module` would be unmaintainable. The VCS file therefore names
  the two vendored blocks that *do* sit under one instance each — i3c-core and
  tt-hw-debug — and leaves pulp glue in.

## What the numbers are

Say which one you are quoting.

- **Verilator**: the SMC DUT **minus the CPU cluster, the I3C core, the
  lowRISC prims, and TB code** — pulp glue and tt-hw-debug still counted, see
  the known gap below. 20306 points.
- **VCS**: the SMC DUT **minus the CPU cluster, the I3C core, the debug-bus
  block, and TB code** — pulp glue still counted. 17629 points.

Neither is "SMC coverage". The two exclude overlapping but different sets, so
they are not comparable to each other either.

## What each file excludes

### `smc_cov_scope.hier` (VCS)

    -tree smc_uvm_top 1                     TB top's own body, children kept
    -tree ...u_smc_cpu_wrapper.gen_4core_cpu  chipyard-generated CPU cluster
    -tree ...u_smc_peripherals.u_i3ccore_wrapper  vendored i3c-core
    -tree ...u_internal_regs.u_smc_dfd_wrap   vendored tt-hw-debug trace/mmr

Each vendored tree is 100% contained by that one instance, checked against the
merged database rather than assumed.

### `../verilator/smc_cov_scope.vlt`

Same intent expressed over source paths. These are the patterns the file
carries, verbatim — note the absence of a `/` after the leading `*`, for the
reason measured under "Verilator glob matching" below:

    coverage_off -file "*hw/sys/smc/dv/tb/tb_top.sv"
    coverage_off -file "*hw/sys/smc/dv/tb/smc_tb_if.sv"
    coverage_off -file "*hw/sys/smc/dv/tb/verilator_stubs/*"
    coverage_off -file "*hw/sys/smc/dv/models/*"
    coverage_off -file "*chipyard_generated_files/*"
    coverage_off -file "*vendor/*"

`hw/sys/smc/dv/cov/sv/*` is deliberately **not** excluded — those files carry
the `OCAH_FCOV_COVER` points that populate the `user` metric family.

## Why these exclusions

Measured on weekly CI run 33982997638 (2026-09-05), 39602 points, 17531 unhit:

| Bucket | Points | % of denominator | Hit % |
| --- | ---: | ---: | ---: |
| `vendor/**` | 19437 | 49% | 55.7 |
| chipyard-generated CPU cluster | 10774 | 27% | 48.7 |
| `hw/ip/**` | 6941 | 18% | 58.9 |
| `hw/sys/smc/**` | 1657 | 4% | 78.9 |
| `hw/common/**` | 708 | 2% | 76.8 |

Third-party RTL plus the generated CPU cluster are 76% of the unscoped
denominator. This is the same argument SEP used to drop `sep_cpu`: a large,
barely-exercised third-party denominator makes the headline a statement about
someone else's code. `hw/ip/**` stays in — it is Tenstorrent IP that SMC
integrates, and integration coverage of those blocks is part of what SMC-level
DV is for, even though IP-level DV owns their internals.

## Effect, projected from the CI database

Recomputed by replaying each scope over that run's `cov/merged.dat`:

| Scope | Points | Total | line | branch |
| --- | ---: | ---: | ---: | ---: |
| none (today's headline) | 39602 | 55.73% | 61.90 | 53.63 |
| Verilator scope, as it actually behaves | 20306 | 61.73% | 66.59 | 59.50 |
| Verilator scope, if the gap below closed | 9227 | 63.83% | 65.88 | 62.77 |
| VCS scope | 17629 | 64.85% | 73.00 | 61.22 |

## Known gap in the Verilator scope

`coverage_off -file "*vendor/*"` drops chipsalliance/i3c-core and
lowRISC/opentitan but **not** `vendor/pulp-platform/**` or
`vendor/tenstorrent/tt-hw-debug/**`. Measured by counting `__vlCoverInsert`
sites in the generated model across four builds:

| Build | vendor sites | pulp-platform | tt-hw-debug |
| --- | ---: | ---: | ---: |
| no scope file | 873578 | 27942 | 13030 |
| `*/vendor/*` | 40972 | 27942 | 13030 |
| `*vendor/*` | 40972 | 27942 | 13030 |
| `*vendor/*` + `*pulp-platform/*` + `*tt-hw-debug/*` | 40972 | 27942 | 13030 |

95.3% of the vendored sites drop out; those two trees do not move for any
pattern. They are the structural glue Verilator inlines into its parents,
which is the working theory — not a confirmed cause. The ineffective patterns
were removed rather than left in place: config that looks like scope and does
nothing is worse than a documented gap.

Consequences: the scoped denominator is 20306 rather than 9227. The SYS_OUT
responder is the shared VIP slave agent, class code with no RTL to score; only
its interface instance and struct bridge sit in the TB body. The VCS `.hier`
file has no equivalent gap for the blocks it names by instance.

These are projections of the scope alone, not predictions of the next run.
That database was collected without `--coverage-expr` and without the
`cov/sv/` cover points, both of which are now in the build: the next weekly
run adds an `expression` family and a `user` family, so its denominator and
its headline will both move. Re-derive the numbers from the first run that
carries them rather than quoting this table as the new baseline.

## Verilator glob matching, measured

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
The first version of `smc_cov_scope.vlt` used `*/vendor/*` and left
pulp-platform/axi and tt-hw-debug fully instrumented while the rest of
`vendor/` dropped out; the build succeeded and nothing warned. Verify a scope
change by counting `__vlCoverInsert` sites per source bucket in the generated
model, not by the build passing.

## Status

- The Verilator scope is wired into `[coverage.verilator].build_args` and the
  instrumented model builds with it.
- **The VCS path has never been run.** No VCS binary is available in the
  development environment this was written in, so `[coverage.vcs]` and this
  `.hier` file are the SEP pattern transplanted, not a measured result. On its
  first use, check: the compile accepts `-lca -cm_common_hier`; the five
  `-tree` paths still resolve (instance names move when RTL is refactored, and
  VCS accepts a stale scope file silently); and `u_dut` matches `smc_uvm_top`
  in every column, which is what tells you assertions were scoped too.

## Carried over from SEP, so it is not rediscovered

- **An include-list does not restrict instrumentation.** `+tree` left SEP's
  design database essentially unscoped; only `-tree` took effect, and VCS
  accepted the file silently either way. Name what to drop.
- **`-cm_hier` alone does not scope assertions.** It governs line, condition,
  FSM, toggle and branch only; without `-cm_common_hier` the excluded
  hierarchy is gone from the code metrics but still graded for assertions.
- **`-cm_common_hier` needs `-lca`.** An opt-in switch, not a separate
  licence.
