<!-- SPDX-License-Identifier: Apache-2.0 -->
# SMC wrapper cocotb flavor (elaboration)

Thin pad-level PyUVM bring-up that lives under `cocotb/wrapper/`. The default
`--dut smc_wrapper` flow now reuses the bare `SmcEnv` catalog via
`smc_wrapper_sim_cfg.toml` (`python_root = cocotb/`, `testlists/all.toml`)
because `tb/tb_wrapper_top.sv` exposes the same cocotb port surface as
`tb_top.sv` while instantiating `smc_wrapper` (`smc` + `smc_ip_integration` +
`smc_cpu_mem_integration`). CPU ROM/scratch/L1$ are absorbed via
`OCAH4CORECluster_mems` (`prim_rom`/`prim_ram_1p`, SEP-aligned).

This tree remains for a dedicated elaboration sequence that checks the
elaboration-alias ports (`dut_present_o`, `powergood_o`, `rst_cold_n_o`,
`smc_reset_n_o`). Point `python_root` / `test_dir` at `cocotb/wrapper` and use
`testlists/wrapper.toml` only when running that entry in isolation.

| Path | Role |
|------|------|
| `env/smc_wrapper_env_cfg.py` | `SmcWrapperEnvCfg` (clock/reset timing only) |
| `tests/smc_wrapper_base_test.py` | Wrapper powergood/cold-reset bring-up |
| `tests/smc_wrapper_elaboration_test.py` | Pad-level elaboration entry |
| `seq_lib/smc_wrapper_elaboration_seq.py` | Checks `dut_present_o` / reset outs |

Functional smoke:

```bash
python3 tools/dv/run_dv.py --dut smc_wrapper --items smoke --tool verilator
```
