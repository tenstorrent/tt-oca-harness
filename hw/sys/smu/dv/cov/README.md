<!-- SPDX-License-Identifier: Apache-2.0 -->
<!-- SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. -->

# SMU coverage

On `--dut smu_block` SMU collects **toggle and functional coverage only**:
line, branch and expression have nothing to instrument under
`hw/sys/smu/rtl/`. The `--dut smu` wrapper is the other way round -- line,
expression and functional, with toggle off, because that DUT elaborates the
real SEP/SMC/DTP wrappers and unscoped toggle there is the 0.5 GB-per-leaf
case. Everything below is the block bench unless it says otherwise.

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

`cov/sv/` carries 11 modules of cover-property points, 120 points in all. The
block bench `tb/tb_top.sv` instantiates 9 of them (90 points elaborate there);
the wrapper bench `tb/tb_wrapper_top.sv` instantiates all 11, and 91 points
elaborate on its no-SEP target:

| Module | Points | Intent it makes real |
| --- | ---: | --- |
| `smu_xbar_fcov.sv` | 26 | window programming and reprogramming, inbound AXI handshake, all four response encodings, forwarded vs not-forwarded routing |
| `smu_boot_fcov.sv` | 21 | reset-release edges, boot-stall sources and release, lifecycle broadcast, fuse sense, SRAM auto-init |
| `smu_rst_fcov.sv` | 17 | cold-reset assertion and release, per-domain reset order, powergood |
| `smu_dbg_fcov.sv` | 13 | JTAG2AXI debug paths, security-disable, TAP state |
| `smu_ext_fcov.sv` | 10 | external boot-sequence gate and the external AXI boundary |
| `smu_nosep_fcov.sv` | 8 | the SEP=0 composition: what the boundary presents with no SEP elaborated |
| `smu_dtp_fcov.sv` | 7 | cross-trigger ports and XTRIG mode |
| `smu_lc_fcov.sv` | 6 | lifecycle state broadcast and demotion |
| `smu_alias_fcov.sv` | 6 | alias/remap manager scope at the SMU boundary |
| `smu_clk_fcov.sv` | 3 | clock mirrors only the wrapper bench exposes |
| `smu_clkstop_fcov.sv` | 3 | clock-stop request and grant |

`smu_alias_fcov.sv` and `smu_clk_fcov.sv` are wrapper-bench only:
`smu_clk_fcov` reads clock mirrors that only that bench publishes.

`smu_cell_map.json` traces every point back to the scenario that asked for it:
205 entries, 76 naming a point and 129 `UNMAPPED:` -- 118 `blocked` by an open
spec finding, 10 `unreachable_at_level`, 1 `tbd`.

`smu_fcov.py` is a static `TEST_FCOV_HITS` table mapping a test class name to
the bins it is *claimed* to hit — running the test marks the bins, no signal is
observed — and nothing under `tools/` or `.github/` reads its output. The
`cov/sv` points land in the `user` metric family, so they reach `cov_merge`,
`cov_report` and the coverage policy.

Points must need stimulus beyond power-up and reset release. A level true in
the quiescent state is either absent or qualified by a sticky flag recording
that its counterpart happened first, so "released" means "the stall lifted"
rather than "no stall was ever applied".

## `SepPresent`, the third scope mechanism

Two mechanisms keep a point out of a graded number, and `SepPresent` is a
third that is easy to confuse with them:

    smu_cov_scope.vlt / smu_wrapper_cov_scope.vlt
                       `coverage_off` -> the point never enters the database.
                       Structural OUT, by source file, at compile time.
    SepPresent         the `g_sep` generate blocks in cov/sv/*_fcov.sv. A point
                       whose observable only exists with SEP elaborated is not
                       elaborated at all on a SEP=0 build, so it never reaches
                       the database and no waiver has to name it. Structural
                       OUT, by elaboration.
    [[holes]]          the point exists and is not hit, carried with a
                       category, a rationale, an owner and an expiry.

`tb_wrapper_top.sv` passes `SepPresent = 1'b0` under the `SMU_NO_SEP`
define; the block bench passes `1'b0` unconditionally, because it hardcodes
SEP=0.

This matters because one Verilator policy grades both wrapper targets:
`policy_file` is resolved per tool, not per target. An accepted waiver whose
selector matches a *covered* point is a hard ConfigError, so the wrapper
policy's holes are generated from the no_sep run -- the target CI gates -- and
a point that can only fire with SEP present must not exist on that
elaboration. The `g_sep` guards are what makes that true.

## Fuse-sense run modes

Every run mode in `smu_sim_cfg.toml` passes `+skip_fuse_sense`, under which
`efuse_shadow_regs.sv` drives `fuse_sense_done` from the plusarg and loads the
shadow array from a preload file. A test that observes fuse-sense completion
has to run without it, so the eFuse bank models supply the sensed data.
`[run_modes.no_sep_fuse_sense]` and `[run_modes.sep_rtl_fuse_sense]` are the
two that leave the plusarg unset; they carry the only two tests that need it.

## `policy_file` rather than the canonical path

`smu` and `smu_block` are two DUTs sharing one `hw/sys/smu/dv` tree, so the
canonical `cov/config/<tool>/coverage_policy.toml` discovery resolves
identically for both and whichever DUT the file does not name fails
`--validate-configs`. `[coverage.verilator].policy_file` names a DUT-qualified
file instead: `smu_block_coverage_policy.toml` for the block bench and
`smu_wrapper_coverage_policy.toml` for `--dut smu`. Both grade the `user`
family against a 90% floor on the effective population, with one `[[holes]]`
entry per unhit point, each `disposition = "waive"`, `status = "accepted"` and
carrying an `expires` date after which it grades as open again.

`cov/config/vcs/` mirrors the same layout for VCS -- `smu_cov_scope.hier`, a
`README.md` and `smu_block_coverage_policy.toml` -- so scope, policy and README
sit in the same place on SMU as on SEP and SMC. **Nothing there has been run on
VCS**: the policy is a scope carrier with no thresholds and no holes, and no
compile passes the `.hier` file. See `cov/config/vcs/README.md`.
