# SEP VCS coverage scope

`sep_cov_scope.hier` is passed to VCS as `-cm_hier` at compile time
(`[coverage.vcs]` in `sep_sim_cfg.toml`), so what it drops never enters the
coverage database. Its content is hashed into the build fingerprint: edit it and
the next `--cov` run recompiles instead of reusing a build instrumented under the
old scope.

## What it does

Drops the CPU subtree, `sep_uvm_top.u_dut.u_sep.sep_cpu`. The core is third
party, only the 20 `cpu` tests reach it, and in the CPU-stub build that subtree
is a stub rather than hardware -- so counting it puts a large, barely-exercised
denominator into a SEP number.

## What it does NOT do yet: exclude the testbench

The testbench top, the backdoor memories, the outbound mailbox, the cocotb VIP
and the AXI SVA module are still in the denominator, so the reported percentage
is not a DUT-only figure and must not be quoted as "SEP DUT coverage".

Two things were measured and ruled out while trying to fix that:

- `urg -hier <file>` at report time prunes the report *pages* but still scores
  the whole database. Measured: the hierarchy listing fell from 85,152 lines to
  49,771 while the total moved 24.72 -> 24.70.
- An include-list in the `-cm_hier` file does not restrict instrumentation.
  Measured: `+tree sep_uvm_top.u_dut.u_sep` (with and without comments in the
  file) left the design database at 3.2M against 3.4M unscoped, i.e. only the
  `-tree` CPU exclusion took effect. VCS accepted the file silently, with no
  warning either way.

So a DUT-only scope needs the *exclusion* form spelled out -- naming the
testbench instances to drop rather than naming the DUT to keep -- or the
`-elfile` object-exclusion route. Both are mechanical once the instance list is
settled; neither is guesswork worth doing at 3 minutes per compile.
