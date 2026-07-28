<!-- SPDX-License-Identifier: Apache-2.0 -->
# SMC OSS DV

Open-source DV environment for the SMC (System Management Controller) subsystem.
Flow = cocotb/PyUVM on Verilator (functional backend) and VCS/Xcelium (coverage),
driven by `tools/dv/run_dv.py`. See `docs/SMC_VPLAN.md` for the verification plan,
`docs/oss_smc_dev.md` for the porting/design plan, and
`docs/smc_oss_execution_guide.md` for run recipes and recorded sign-off evidence.

## Two DUTs / two sim configs

| | bare SMC | SMC wrapper |
|---|---|---|
| select | `--dut smc` | `--dut smc_wrapper` |
| config | `smc_sim_cfg.toml` | `smc_wrapper_sim_cfg.toml` |
| TB top | `smc_uvm_top` (`tb/tb_top.sv`) | `smc_wrapper_uvm_top` (`tb/tb_wrapper_top.sv`) |
| env | `cocotb/` (full PyUVM env) | `cocotb_wrapper/` (pad-level baseline) |
| memory | TB responder shims (`shims/mem/*.sv`) | wrapper RTL integration models |

The bare-`smc` catalog is the primary DV surface (large PyUVM env, ~130 tests).
The `smc_wrapper` catalog is deferred and intentionally unregistered: its
wrapper API, Bender targets, and SEP prim shim still need porting to the current
repository before its elaboration test can run.

## Layout

```
hw/sys/smc/dv/
├── cocotb/                 # bare-SMC PyUVM env
│   ├── env/                #   agents, monitors, scoreboard, memory model, env cfg
│   ├── seq_lib/            #   sequences + protocol VIP/BFM helpers (*_vip_utils, *_vip.py)
│   └── tests/              #   @pyuvm.test() entries + smc_base_test.py
├── cocotb_wrapper/         # smc_wrapper PyUVM env (separate base_test + env_cfg)
├── shims/                  # TB behavioral responders (mem/analog) + wrapper padring
├── tb/                     # tb_top.sv, tb_wrapper_top.sv, verilator_stubs/
├── testlists/             # native TOML testlists (per-feature leaves + all.toml groups)
├── assets/                 # ROM/eFuse/shadow preload images
├── docs/                   # VPLAN, porting plan, execution guide, upgrade notes
├── smc_sim_cfg.toml        # bare-SMC build/filelist manifest, modes, tool flags
└── smc_wrapper_sim_cfg.toml
```

## Environment shape (bare SMC)

PyUVM env (`cocotb/env/smc_env.py`) with agents split by honesty class:

- **SAMPLE-only agents** (observability sampling, not protocol BFMs):
  `i2c / reset / clk / irq / gpio / axil`.
- **Protocol / traffic agents**: `sys_axi` (SEP_IN, `s_axi_*`), `sys_in_axi`
  (`sys_axi_*`), `jtag_axi` (`jtag_axi_*`) — all `SmcSysAxiDriver` subclasses over
  `ocah_axi_vip.OcahAxiMaster`; plus `protocol_vip` (records high-level scenario
  evidence).
- **Passive monitors**: `axi_monitor` (SEP_IN), `output_axi_monitor` (SYS_OUT).

All agents feed one `SmcScoreboard` (`cocotb/env/smc_scoreboard.py`), a
multi-item-type dispatcher that per-type checks invariants, emits
`FUNC_COV_VALUE` coverage, and (for `sys_axi`) compares against the TB-local
`SmcMemoryModel` golden. `check_phase` asserts total evidence `> 0` (non-vacuity).

Tests inherit `cocotb/tests/smc_base_test.py`, which builds the env, runs the
power-good + cold-reset bring-up, and overrides `run_scenario()`. See
`docs/smc_oss_execution_guide.md` §6 for the protocol-VIP pattern and the
promotion history from CSR-only proxy to `proxy=False` evidence.

## Run

```bash
PY=tools/dv/run_dv.py
python3 $PY --dut smc --items smc_cold_reset_test --tool verilator
python3 $PY --dut smc --items smc_canonical_smoke_test --stage flist --stage sim
python3 $PY --dut smc --items all --tag smoke --stage sim       # smoke subset
python3 $PY --dut smc --items all --tag smoke --tool vcs --cov  # coverage on VCS
python3 $PY --dut smc --items all --stage sim --regress         # full regression
```

PASS/FAIL is classified by the global parser registry
(`hw/common/dv/configs/parsers.toml`). The cocotb flow requires positive
evidence from `results.xml`; a clean simulator exit alone is not enough.

The shared OSS runner uses Bender to generate the SMC RTL filelist, then appends
the TB top and the local memory-responder/stub sources listed in the sim cfg.
The public filelist is vendor-clean (verify with
`tools/dv/check_no_vendor_paths.py --filelist hw/sys/smc/dv/build/smc_bender.f --target smc`).
