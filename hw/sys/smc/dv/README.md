<!-- SPDX-License-Identifier: Apache-2.0 -->
# SMC OSS DV

Open-source DV environment for the SMC (System Management Controller) subsystem.
Flow = cocotb/PyUVM on Verilator (functional backend) and VCS/Xcelium (coverage),
driven by `tools/dv/run_dv.py`. See `docs/ref_test_dev.md` for the
test-development reference and `docs/SMC_VPLAN.adoc` for the verification plan
(AsciiDoc for TRM integration under `docs/trm`).

## Single DUT

**Launch entry: `--dut smc`.** `tb/tb_top.sv` (`smc_uvm_top`) instantiates
`hw/top/smc_wrapper.sv` (`smc` + `smc_ip_integration` + `smc_cpu_mem_integration`).
There is no separate `smc_wrapper` DUT alias; sim config is solely
`smc_sim_cfg.toml`.

| | |
|---|---|
| select | `--dut smc` |
| config | `smc_sim_cfg.toml` |
| TB top | `smc_uvm_top` (`tb/tb_top.sv`) |
| DUT | `smc_wrapper` |
| cocotb | `cocotb/` (`SmcEnv`) |
| testlist | `testlists/all.toml` |
| macros | inside `smc_ip_integration` (pll/pvt/efuse/pads) |
| CPU mem | inside wrapper via `smc_cpu_mem_integration` |
| still in TB | output AXI + I3C DAT/DCT + DTP err_slv |

## Layout

```
hw/sys/smc/dv/
├── cocotb/                 # PyUVM env, seq_lib, tests
├── models/                 # TB responders (output AXI, I3C DAT/DCT, …)
├── tb/                     # tb_top.sv, verilator_stubs/
├── testlists/
├── assets/
├── docs/
└── smc_sim_cfg.toml
```

## Run

```bash
PY=tools/dv/run_dv.py
python3 $PY --dut smc --items smoke --tool verilator
python3 $PY --dut smc --items smc_canonical_smoke_test --stage flist --stage sim
python3 $PY --dut smc --items all --stage sim --regress
```

PASS/FAIL is classified by the global parser registry
(`hw/common/dv/configs/parsers.toml`). The cocotb flow requires positive
evidence from `results.xml`; a clean simulator exit alone is not enough.
