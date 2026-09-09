<!-- SPDX-License-Identifier: Apache-2.0 -->
<!-- SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. -->

# SMU coverage

SMU collects **toggle and functional coverage only**. It does not collect
line, branch or expression, and that is a measurement rather than a
preference.

## Why toggle, and not line/branch/expression

SMU is an integration level. `hw/sys/smu/rtl/smu.sv` is 1326 lines carrying
two `always` blocks, 79 continuous assigns and one `if`/`case`; it wires SMC,
DTP, SEP and the AXI crossbar together. Verilator emits **zero** line, branch
or expression instrumentation sites for anything under `hw/sys/smu/rtl/` —
counted on the built model, not assumed.

The argument list this replaced produced 1350556 sites, and every one of them
belonged to somebody else:

| Tree | Sites | Share |
| --- | ---: | ---: |
| `vendor/**` | 886526 | 65.6% |
| chipyard-generated CPU cluster | 272220 | 20.2% |
| `hw/ip/**` | 132652 | 9.8% |
| `hw/common/**` | 49040 | 3.6% |
| `hw/sys/smc/**` | 9928 | 0.7% |
| `hw/sys/smu/dv/**` (TB) | 186 | 0.0% |
| `hw/sys/smu/rtl/**` | **0** | **0.0%** |

Those three families cannot grade SMU because there is nothing of SMU's for
them to instrument. Toggle instruments nets, which is what an integration
level owns: whether the interconnect it wires up was actually exercised. Each
subsystem grades its own internals in its own DV package.

## Why this is not the 0.5 GB toggle run the config used to warn about

`[coverage.verilator]` previously recorded that toggle on this DUT produces a
~0.5 GB database per leaf. That figure was toggle over the whole elaborated
model, SMC cluster and vendored fabric included. `smu_cov_scope.vlt` drops all
of it at compile time:

| | Sites | Model dir | Build |
| --- | ---: | ---: | ---: |
| line+branch+expression, unscoped | 1350556 | 3.0 GB | ~350 s |
| toggle+user, scoped | 19728 | 909 MB | ~140 s |

Scope is what makes toggle affordable here. Enabling toggle without it
reproduces the database the old comment recorded.

## What the number is

The SMU integration RTL **plus two vendored trees the tool cannot exclude**.
Not "SMU coverage". Of the 19728 toggle sites:

| Source | Sites | Share |
| --- | ---: | ---: |
| `vendor/pulp-platform/axi` (`axi_lite_demux.sv`) | 12886 | 65.3% |
| `vendor/tenstorrent/tt-hw-debug` (`generic_dff*`) | 5705 | 28.9% |
| `hw/sys/smu/rtl/smu.sv` + `cov/sv` | 1137 | 5.8% |

Every one of those 18591 vendored sites sits under `.u_smc` or `.u_dtp` —
none is under SMU's own crossbar — so the intent is unambiguous and only the
mechanism falls short. `cov/config/verilator/smu_block_coverage_policy.toml` records
the two hierarchy selectors that close it and why they cannot be written
before a run exists.

Of the 1137 SMU-side sites, 117 are the `cov/sv` modules' own registers.
`coverage_off` is whole-file, so excluding them would delete the `user` points
too; the distortion is left in and named rather than traded for the functional
coverage.

## Verilator glob matching, measured

`coverage_off -file` matches the path as Verilator **opened** the file, not
the absolute path it records in the generated code, and `+incdir+`-resolved
files are opened relative. A leading `*/` therefore scopes only half the tree:
`*vendor/*` matches both forms, `*/vendor/*` matches only the absolute one.

Two vendored trees are unreachable by any file pattern. `*vendor/*`,
`*pulp-platform/*`, `*tt-hw-debug/*` and the bare `*axi_lite_demux.sv` /
`*generic_dff.sv` forms were each built and counted, on this DUT and on SMC,
and every one left the numbers unchanged. The ineffective patterns are not in
the file: config that looks like scope and does nothing is worse than a
documented gap.

Verify a scope change by counting `__vlCoverToggleInsert` sites per source
bucket in the generated model, not by the build passing — a wrong scope
changes nothing and warns about nothing.

## Functional coverage

`cov/sv/` carries two modules, 46 cover-property points, instantiated in the
shared `tb/tb_top.sv`:

| Module | Intent it makes real |
| --- | --- |
| `smu_boot_fcov.sv` | `smc_boot_cg` bringup: reset-release edges, boot-stall sources and release, lifecycle broadcast |
| `smu_xbar_fcov.sv` | `xbar_route_cg` filter and `reg_access_cg` outcome: window programming and reprogramming, inbound AXI handshake and all four response encodings, forwarded vs not-forwarded routing |

These replace nothing; `smu_fcov.py` stays. What they add is coverage the
tooling can consume. `smu_fcov.py` is a static `TEST_FCOV_HITS` table mapping
a test class name to the bins it is *claimed* to hit — running the test marks
the bins, no signal is observed — and nothing under `tools/` or `.github/`
reads its output. The `cov/sv` points land in the `user` metric family, so
they reach `cov_merge`, `cov_report` and the coverage policy.

Points must need stimulus beyond power-up and reset release. A level true in
the quiescent state is either absent or qualified by a sticky flag recording
that its counterpart happened first, so "released" means "the stall lifted"
rather than "no stall was ever applied".

## Status

- The scoped toggle+user model builds on `--dut smu_block`;
  `--validate-configs` passes for both `smu` and `smu_block`.
- **No SMU coverage database exists yet.** The weekly job records
  `coverage: enabled=false, status=SKIP` — its `coverage:` flag is gated on
  `DV_LARGE_RUNNER` — and a local `--cov` run aborts on
  `free(): invalid pointer` as Verilator writes the database. That abort
  follows the SMC model: SMU instantiates SMC, DTP and CTP collect cleanly on
  the same local Verilator, and the local build reports
  `rev v5.050 (mod)` against CI's `rev v5.050`. See
  `hw/sys/smc/dv/docs/local_records.adoc` for the elimination table.
- So every number here is a build-time site count, which needs no simulation.
  The hit percentages, the policy holes and any threshold need the first run
  that carries this configuration.

## `policy_file` rather than the canonical path

`smu` and `smu_block` are two DUTs sharing one `hw/sys/smu/dv` tree, so the
canonical `cov/config/<tool>/coverage_policy.toml` discovery resolves
identically for both and whichever DUT the file does not name fails
`--validate-configs`. `[coverage.verilator].policy_file` names a DUT-qualified
file instead, which leaves room for the wrapper `--dut smu` to add its own.
