<!-- SPDX-License-Identifier: Apache-2.0 -->
<!-- SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. -->

# SMU coverage

SMU collects **toggle and functional coverage only**: line, branch and
expression have nothing to instrument under `hw/sys/smu/rtl/`.

## Why toggle, and not line/branch/expression

SMU is an integration level: `hw/sys/smu/rtl/smu.sv` wires SMC, DTP, SEP and
the AXI crossbar together and carries almost no procedural logic. Verilator
emits **zero** line, branch or expression instrumentation sites for anything
under `hw/sys/smu/rtl/`.

An unscoped line/branch/expression build produces on the order of 1.3 million
sites, every one of them outside SMU: the vendored trees, the
chipyard-generated CPU cluster, `hw/ip`, `hw/common`, `hw/sys/smc` and the TB
account for all of them, and `hw/sys/smu/rtl/` for none.

Those three families cannot grade SMU because there is nothing of SMU's for
them to instrument. Toggle instruments nets, which is what an integration
level owns: whether the interconnect it wires up was actually exercised. Each
subsystem grades its own internals in its own DV package.

## Why scope is what makes toggle affordable here

Toggle over the whole elaborated model -- SMC cluster and vendored fabric
included -- produces a ~0.5 GB database per leaf. `smu_cov_scope.vlt` drops all
of it at compile time, so the toggle denominator is SMU's own RTL; enabling
toggle without the scope reproduces that database.

## What the number is

The SMU integration RTL **plus two vendored trees the tool cannot exclude**.
Not "SMU coverage". `vendor/pulp-platform/axi` (`axi_lite_demux.sv`) and
`vendor/tenstorrent/tt-hw-debug` (`generic_dff*`) hold the large majority of
the scoped toggle sites; `hw/sys/smu/rtl/smu.sv` and `cov/sv` hold the rest.

Every vendored site sits under `.u_smc` or `.u_dtp` — none is under SMU's own
crossbar — so the intent is unambiguous and only the mechanism falls short.
`cov/config/verilator/smu_block_coverage_policy.toml` records the two hierarchy
selectors that close it and why their counts can only come from a coverage
database.

The `cov/sv` modules' own registers are toggle sites too. `coverage_off` is
whole-file, so excluding them would delete the `user` points; they stay in the
denominator, named here.

## Verilator glob matching

`coverage_off -file` matches the path as Verilator **opened** the file, not
the absolute path it records in the generated code, and `+incdir+`-resolved
files are opened relative. A leading `*/` therefore scopes only half the tree:
`*vendor/*` matches both forms, `*/vendor/*` matches only the absolute one.

Two vendored trees are unreachable by any file pattern: `*vendor/*`,
`*pulp-platform/*`, `*tt-hw-debug/*` and the bare `*axi_lite_demux.sv` /
`*generic_dff.sv` forms all leave the site count unchanged, so none of them is
in the scope file.

Verify a scope change by counting `__vlCoverToggleInsert` sites per source
bucket in the generated model, not by the build passing — a wrong scope
changes nothing and warns about nothing.

## Functional coverage

`cov/sv/` carries two modules of cover-property points, instantiated in the
shared `tb/tb_top.sv`:

| Module | Intent it makes real |
| --- | --- |
| `smu_boot_fcov.sv` | `smc_boot_cg` bringup: reset-release edges, boot-stall sources and release, lifecycle broadcast |
| `smu_xbar_fcov.sv` | `xbar_route_cg` filter and `reg_access_cg` outcome: window programming and reprogramming, inbound AXI handshake and all four response encodings, forwarded vs not-forwarded routing |

`smu_fcov.py` is a static `TEST_FCOV_HITS` table mapping a test class name to
the bins it is *claimed* to hit — running the test marks the bins, no signal is
observed — and nothing under `tools/` or `.github/` reads its output. The
`cov/sv` points land in the `user` metric family, so they reach `cov_merge`,
`cov_report` and the coverage policy.

Points must need stimulus beyond power-up and reset release. A level true in
the quiescent state is either absent or qualified by a sticky flag recording
that its counterpart happened first, so "released" means "the stall lifted"
rather than "no stall was ever applied".

## `policy_file` rather than the canonical path

`smu` and `smu_block` are two DUTs sharing one `hw/sys/smu/dv` tree, so the
canonical `cov/config/<tool>/coverage_policy.toml` discovery resolves
identically for both and whichever DUT the file does not name fails
`--validate-configs`. `[coverage.verilator].policy_file` names a DUT-qualified
file instead.
