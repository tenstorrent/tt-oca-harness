<!-- SPDX-License-Identifier: Apache-2.0 -->
# SMC OSS DV

Open-source DV environment for the SMC (System Management Controller) subsystem.
Flow = cocotb/PyUVM on Verilator (functional backend) and VCS/Xcelium (coverage),
driven by `tools/dv/run_dv.py`. See `docs/ref_test_dev.md` for the
test-development reference and `docs/SMC_VPLAN.adoc` for the verification plan
(AsciiDoc for TRM integration under `docs/trm`).

## Single DUT

**Launch entry: `--dut smc_wrapper`** (registered in
`hw/common/dv/configs/duts.toml`). `tb/tb_top.sv` (`smc_uvm_top`) instantiates
`hw/top/smc_wrapper.sv` (`smc` + `smc_ip_integration` + `smc_cpu_mem_integration`).
Bare `--dut smc` is not supported.

| | |
|---|---|
| select | `--dut smc_wrapper` |
| config | `smc_wrapper_sim_cfg.toml` |
| TB top | `smc_uvm_top` (`tb/tb_top.sv`) |
| DUT | `smc_wrapper` |
| cocotb | `cocotb/` (`SmcEnv`) |
| testlist | `testlists/all.toml` |
| macros | inside `smc_ip_integration` (pll/pvt/efuse/pads) |
| CPU mem | inside wrapper via `smc_cpu_mem_integration` |
| still in TB | SYS_OUT=`axi_sim_mem` + I3C `prim_ram_1p` (in `tb_top`) + DTP err_slv |

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
├── docs/
└── smc_wrapper_sim_cfg.toml
```

## Run

```bash
module load verilator/5.046 gcc/13.2.1   # C++20 for cocotb -fcoroutines
PY=tools/dv/run_dv.py
python3 $PY --dut smc_wrapper --items smoke --tool verilator
python3 $PY --dut smc_wrapper --items smc_cold_reset_test --stage flist --stage hdl_compile --stage sim
python3 $PY --dut smc_wrapper --items all --stage sim --regress
```

PASS/FAIL is classified by the global parser registry
(`hw/common/dv/configs/parsers.toml`). The cocotb flow requires positive
evidence from `results.xml`; a clean simulator exit alone is not enough.
