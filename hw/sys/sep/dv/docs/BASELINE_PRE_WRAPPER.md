# SEP OSS DV — Pre-wrapper baseline regression

Branch `3759-smu-cla-sep-cpu-debug` (== main for hw/ + the OSS DV tree; only a fw test dir differs).
Reference: 07-15 Verilator `all` = 69/69 pass.

## Verilator (authoritative gate)
- **verilator**: exit=0 total=69 pass=69 fail=0 flaky=0 pass_rate=1.0 dur=269.884s
  - run_dir: `20260717_030448__verilator__all`

## VCS (cross-check)
- **vcs**: exit=0 total=69 pass=69 fail=0 flaky=0 pass_rate=1.0 dur=667.806s
  - run_dir: `20260717_030934__vcs__all`


---
**RESULT: 69/69 PASS on BOTH engines (Verilator + VCS), exit 0.** This is the
pre-wrapper golden baseline. Post-integration, re-run the identical
`./run.sh all --regress --stage flist,hdl_compile,sim` on each tool and diff the
pass list against this — any test that passed here must still pass.
