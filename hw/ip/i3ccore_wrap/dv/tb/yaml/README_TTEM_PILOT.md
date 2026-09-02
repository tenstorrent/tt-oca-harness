# i3ccore block TB under TTEM — Option-A pilot

Runs the block-level **pure-cocotb** i3ccore tests (top `tb_i3ccore`, no UVM)
through **TTEM** instead of the bare `make MODULE=...` flow, so they gain LSF
parallelism, seed/regression management and coverage-merge integration — while
keeping the existing cocotb test files unchanged.

**Status: validated.** Both pilot entries pass end-to-end through TTEM:

- `i3c_setnewda_test`  → `TESTS=1 PASS=1 FAIL=0`  (single-test module)
- `i3c_error_sanity_test` → `TESTS=4 PASS=4 FAIL=0` (multi-test module, all 4 `@cocotb.test` run)

## Files

| File | Role |
|------|------|
| `yaml/project_default.yaml` | Copy of the generic TTEM base (anchors: `*compile`, `*simulate`, `*variables`, `*lsf`, `*waves`, `*coverage`). `#include` needs same-dir bare filenames, so it is copied here. |
| `yaml/project_i3ccore.yaml` | Block project: pinned tool roots, `PYTHONPATH`, the `compile_i3ccore` target (`cocotb: true`, TOPLEVEL `tb_i3ccore`), and the `i3ccore_simulate` base. |
| `yaml/testlist_i3ccore.yaml` | One entry per cocotb module. `cocotb_top:` selects the `.py` module (= cocotb `MODULE`). |
| `../i3ccore_ttem.f` | Wrapper compile filelist preserving the prim_assert→i3c-core→tb ordering from the block Makefile. |

## How to run

```bash
source $OCH_ROOT/bin/setup_env.sh          # loads X-2025.06 + cocotb venv (cd's to repo root)
cd $OCH_ROOT/hw/ip/i3ccore_wrap/dv/tb     # MUST run from the TB dir (see gotcha #2)
rm -f $OCH_ROOT/out/STOP_ON_FAIL           # clear any stale stop flag from a prior fail

# full build + run
ttem --config $OCH_ROOT/.ttem/i3ccore yaml/testlist_i3ccore.yaml i3c_setnewda_test \
     --stack compile_i3ccore,sim -c compile_i3ccore --no-lsf --seed 1

# reuse the compiled simv, just simulate
ttem --config $OCH_ROOT/.ttem/i3ccore yaml/testlist_i3ccore.yaml i3c_error_sanity_test \
     --stack sim -c compile_i3ccore --no-lsf

# regenerate the bender filelist first (only if RTL/file set changed)
#   add `flist,` to the stack: --stack flist,compile_i3ccore,sim
```

## Adding more tests

Append an entry to `testlist_i3ccore.yaml` (the key **must contain `_test`** — TTEM
only treats such keys as runnable testcases):

```yaml
  i3c_back_to_back_test:
    name: i3c_back_to_back_test
    cocotb_top: i3c_back_to_back          # the .py module name (no extension)
    compile_target: compile_i3ccore
    <<: *i3ccore_sim_base
```

To pin a single `@cocotb.test` inside a multi-test module, add `cocotb_test:`:

```yaml
  i3c_fifo_overflow_only_test:
    name: i3c_fifo_overflow_only_test
    cocotb_top: i3c_error_sanity
    cocotb_test: i3c_fifo_overflow        # one testcase, not the whole module
    compile_target: compile_i3ccore
    <<: *i3ccore_sim_base
```

For the X-reading register-survey module add `RESOLVE_X=ZEROS` equivalent via a
`run_args`/env (test_i3ccore needs `COCOTB_RESOLVE_X=ZEROS`); not in this pilot.

## LSF (the payoff)

Drop `--no-lsf` to fan the testlist across LSF — the whole suite then runs in
parallel instead of the ~40-min serial `make all_tests`.

## Gotchas discovered while bringing this up (read before extending)

1. **`coverage`/`waves` must be non-null.** `project_default` leaves them empty;
   TTEM schema validation rejects nulls. `project_i3ccore.yaml` overrides both
   with dummy-but-valid values.
2. **`TB_ROOT` is forced to `.` by TTEM** before the testlist variables load
   (`set_tb_root` runs in `setup_repo_manager`, and `store_vars(override=False)`
   won't overwrite it). So:
   - In path expressions (filelist, include_dirs, flist `cd`) use **`$OCH_ROOT/...`
     absolute**, never `$TB_ROOT`.
   - The sim-stage symlink `ln -s {tb_root}/{module}.py` uses `Path(".").resolve()`
     = the **cwd you launched ttem from**, so you **must run from the TB dir**.
3. **Test keys need `_test`.** `ttem.py` builds the runnable-test list from any
   top-level key containing `_test`/`_regress`. Name the template without `_test`
   (`i3ccore_sim_base`) so it isn't mistaken for a test.
4. **Sibling imports go through `PYTHONPATH`.** TTEM only symlinks the one
   `cocotb_top` module into the run dir; `i3c_test_base`/`i3c_rand`/`i3c_api`/
   `I3CCSR_reg`/`constrained_random`/`cocotbext_i3c` are all reached via the
   `PYTHONPATH` set in `project_i3ccore.yaml`.
5. **`out/STOP_ON_FAIL`** is left behind by a failed stage and blocks reruns —
   delete it before retrying.
