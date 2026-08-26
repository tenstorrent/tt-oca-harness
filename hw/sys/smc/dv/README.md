<!-- SPDX-License-Identifier: Apache-2.0 -->
# SMC OSS DV

Open-source DV environment for the SMC (System Management Controller) subsystem.
Flow = cocotb/PyUVM on Verilator (functional backend) and VCS/Xcelium (coverage),
driven by `tools/dv/run_dv.py`. See `docs/index.adoc` for the chapter set:
`docs/SMC_TB_ARCH.adoc` for test development, environment setup and run
recipes, `docs/SMC_VPLAN.adoc` for the verification plan, the porting plan and
the recorded sign-off evidence, and `docs/SMC_FCOV.adoc` for the coverage
pipeline.

**Green / signoff policy (2026-07-29):** only claim **real DUT RTL paths**.
I3C CCC/IBI / real-core protocol, adopter PLL/PVT OKAY wraps, and TB-glue
demos (e.g. hardcoded DFD capture token) belong in `testlists/deferred.toml`
— not reportable as feature PASS. Green `smc_i3c_to_fabric_test` is
**stub-signature only** (fabric → `i3ccore_stub` SLVERR). Checklist:
[`../doc/dv_hack_cleanup_checklist.md`](../doc/dv_hack_cleanup_checklist.md).

**`allow_timeout` review gate:** default `False`. New `allow_timeout=True`
call sites need a one-line rationale comment at the call (what hangs without
it, and why that is still a real DUT path). Inventory: `smc_*_utils.py` /
cluster helpers — do not add silently in PRs.

## Single DUT

**Launch entry: `--dut smc`** (discovered by the runner's directory
convention from `smc_sim_cfg.toml`). `tb/tb_top.sv` (`smc_uvm_top`) instantiates
`hw/top/smc_wrapper.sv` (`smc` + `smc_ip_integration` + `smc_cpu_mem_integration`),
so the bare DUT name selects the wrapper-based TB.

| | |
|---|---|
| select | `--dut smc` |
| config | `smc_sim_cfg.toml` |
| TB top | `smc_uvm_top` (`tb/tb_top.sv`) |
| DUT | `smc_wrapper` |
| cocotb | `cocotb/` (`SmcEnv`) |
| testlist | `testlists/all.toml` (deferred: `testlists/deferred.toml`, not included) |
| macros | inside `smc_ip_integration` (pll/pvt/efuse/pads) |
| CPU mem | inside wrapper via `smc_cpu_mem_integration` |
| still in TB | SYS_OUT=`axi_sim_mem` (pulp VIP); DTP CSR / I3C DAT ports **idle** on `smc_wrapper` (no TB terminator — tests deferred; DTP CSR is smc_wrapper-only boundary) |

## Verilator stubs policy

`tb/verilator_stubs/` may contain **tooling shims only** (`prim_sync2` /
`prim_sync3` for OSS prim port remap + X-init). Product-module overrides
(`smc_reset_*`, `smc_dfx_*`, …) are forbidden.

| ID | Issue | Status |
|----|--------|--------|
| B1 | PeakRDL nested hwif structs historically broke Verilator C++ codegen | Mitigated by `disable_public_flat_rw` + `smc_public_scope.vlt`; real RTL compiles |
| B2 | Product `och_prim` `prim_sync2/3` use private `.i_CK` ports vs OSS OT-style cells | Retained DV `prim_sync*` tooling stubs; product RTL not modified |

## Layout

```
hw/sys/smc/dv/
├── cocotb/                 # PyUVM env, seq_lib, tests
├── models/                 # pll/pvt PeakRDL wraps (adopter placeholders)
├── tb/                     # tb_top.sv, verilator_stubs/
├── testlists/
├── assets/
├── docs/                   # VPLAN, test-development, porting, execution guides
└── smc_sim_cfg.toml
```

## Run

```bash
module load verilator/5.050 gcc/13.2.1   # C++20 for cocotb -fcoroutines; 5.050 fixes bad C++ init of nested unpacked structs seen with 5.046
PY=tools/dv/run_dv.py
python3 $PY --dut smc --items smoke --tool verilator
python3 $PY --dut smc --items smc_cold_reset_test --stage flist --stage hdl_compile --stage sim
python3 $PY --dut smc --items all --stage sim --regress
```

PASS/FAIL is classified by the global parser registry
(`hw/common/dv/configs/parsers.toml`). The cocotb flow requires positive
evidence from `results.xml`; a clean simulator exit alone is not enough.
