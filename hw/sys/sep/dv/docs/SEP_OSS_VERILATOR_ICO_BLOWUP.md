<!-- SPDX-License-Identifier: Apache-2.0 -->

# SEP OSS Verilator ICO Blow-up — Root Cause & Fix (RESOLVED)

## Summary
The SEP OSS cocotb/Verilator model wedged (0-byte sim logs, ~770% CPU, 1800 s
timeout) while VCS/Xcelium ran fine. Root cause is **not** the DUT AXI fabric RTL.
It is the cocotb test runner forcing a global `--public-flat-rw`. Fixed entirely in
the DV toolchain/config — **no DUT or fabric RTL change**.

> Supersedes the earlier "AXI fabric needs cut/spill registers" escalation. That
> conclusion was disproved by the A/B below.

## Root cause
cocotb's `cocotb_tools/runner.py` hardcodes `--public-flat-rw` in the Verilator model
build (unconditional, inside `Verilator._build_command`). It marks **every** signal in
the design public so cocotb can read/write any of them via VPI.

For a large DUT like SEP that is toxic. With everything public, Verilator must
preserve the full internal structure and can no longer apply the `split_var` hints
**already present** in the AXI/common-cells RTL (`rr_arb_tree`, `lzc`, `axi_demux`).
Verilator literally warns:

```
%Warning-SPLITVAR: .../axi_demux_simple.sv:69: 'slv_resp_o' has split_var metacomment
                   but will not be split because it is public.
%Warning-SPLITVAR: .../rr_arb_tree (via lzc.sv): 'sel_nodes'/'index_nodes' ... not split (public)
```

With those pragmas disabled, the false combinational ready/valid loops in
`axi_demux` / `axi_burst_splitter` / `id_fifo` cannot be broken, so Verilator
schedules **951 SCCs** and a **3.2M-entry input-combinational (ICO) settle region**,
and the runtime wedges/crawls.

## Evidence (verilator `--stats`, same tree, A/B)
| metric | `--public-flat-rw` (baseline) | scoped public (fix) |
|---|---:|---:|
| `'ico' sense triggers` | 2574 | ~27 |
| `Cycles, unique SCCs` | 951 | **61** |
| `size of replicated logic: Input` (ICO region) | 3,223,597 | ~161,609 |
| `sep_axi_smoke_test` | wedge @1800 s | **PASS ~130 s** |

Ruled out by controlled A/B (both negative): tie-able reset/control inputs
(`wdt_rst_ni_i`/`ext_boot_seq_done_i`/`mpc_reset_run_req`/`i_cpu_run_req_i`); clock
gating (`prim_clkgater`/`prim_clock_gating` bypass shims, proven active, no change).

Also confirmed unneeded: a `split_var` edit on `axi_demux_simple.sv` `slv_resp_o`
gave 61 SCCs **with and without** it — the collapse comes entirely from un-blocking
the *pre-existing* `rr_arb_tree`/`lzc` pragmas. No RTL change kept.

## Fix
Expose only the **testbench top** (`sep_uvm_top`) to cocotb instead of the whole DUT.
cocotb needs the root handle + top-level ports (clocks/reset/boot + flat `s_axi_*`);
the CPU-LSU splice is an SV `force`/XMR inside `tb_top.sv`, not a cocotb VPI access.

Removing the global flag **entirely** breaks cocotb (`Can not find root handle
'sep_uvm_top'` — VPI needs the top public), so the flag is *replaced* with a scoped
Verilator config, not just dropped. `--public-depth N` does not work (inlining +
`--public-flat-rw` override → still global).

Three DV-config files (no RTL):
1. `sep_public_scope.vlt` — `public_flat_rw -module "sep_uvm_top" -var "*"`.
   ⚠️ The `.vlt` is preprocessed: no backticks, and no comment line may start with
   the word "verilator" (it parses as a metacomment directive otherwise).
2. `runlib/stages.py` `cocotb_public_scope()` — a context manager (mirroring the
   existing `cocotb_make_jobs`) that wraps `Verilator._build_command` to strip
   `--public-flat-rw` and inject the scoped `.vlt`. It does **not** edit the venv
   `runner.py`, which the flist/compile stages regenerate.
3. `sep_sim_cfg.toml` `[build.verilator] public_scope = "<path>"` — the config knob.

Validated end-to-end through `run.sh` → `run_dv` → runlib: hdl_compile PASS, sim
PASS ~130 s, 0 split-var-public warnings, `public_scope` artifact logged.

## Note
The `.vlt` is injected via the runtime monkeypatch (not cocotb `build_args`), so the
cocotb build cache does not see edits to it — clean the build dir if you change the
`.vlt`.
