<!-- SPDX-License-Identifier: Apache-2.0 -->
# SMC OSS DV

Open-source DV environment for the SMC (System Management Controller) subsystem.
Flow = cocotb/PyUVM on Verilator (functional backend) and VCS/Xcelium (coverage),
driven by `tools/dv/run_dv.py`. See `docs/ref_test_dev.md` for the
test-development reference and `docs/SMC_VPLAN.adoc` for the verification plan
(AsciiDoc for TRM integration under `docs/trm`).

## Two DUTs / two sim configs

**Official entry: `--dut smc_wrapper`.** Bare `--dut smc` is secondary (TB stubs
for macros the wrapper absorbs).

| | **SMC wrapper (primary)** | bare SMC (secondary) |
|---|---|---|
| select | `--dut smc_wrapper` | `--dut smc` |
| config | `smc_wrapper_sim_cfg.toml` | `smc_sim_cfg.toml` |
| TB top | `smc_wrapper_uvm_top` (`tb/tb_wrapper_top.sv`) | `smc_uvm_top` (`tb/tb_top.sv`) |
| DUT | `smc_wrapper` (`smc` + `smc_ip_integration` + `smc_cpu_mem_integration`) | `smc` |
| cocotb | `cocotb/` (`SmcEnv`) | same |
| testlist | `testlists/all.toml` (`smoke` = 37) | same |
| macros | inside `smc_ip_integration` (pll_wrap/pvt_wrap/efuse/pads) | PLL/PVT/ext/GPIO-ctrl DECERR; eFuse = shared bank/shim |
| CPU mem | absorbed: `smc_cpu_mem_integration` | TB: same integration |
| still in TB | output AXI + I3C DAT/DCT + DTP err_slv | output AXI + I3C DAT/DCT + eFuse bank/shim + DTP/PLL/PVT DECERR |

Both DUTs share the bare `SmcEnv` smoke catalog. `cocotb/wrapper/` keeps a
thin pad-level elaboration sequence (alias ports on `tb_wrapper_top`).

## Layout (aligned with DTP / SEP)

```
hw/sys/smc/dv/
├── cocotb/                 # bare-SMC PyUVM env
│   ├── env/                #   agents, monitors, scoreboard, memory model, env cfg
│   ├── seq_lib/            #   sequences + protocol VIP/BFM helpers (*_vip_utils, *_vip.py)
│   ├── tests/              #   @pyuvm.test() entries + smc_base_test.py
│   └── wrapper/            #   smc_wrapper pad-level flavor (own base_test + env_cfg)
├── models/                 # behavioral / sim stand-ins (mem, analog, PLL/PVT, padring)
├── tb/                     # tb_top.sv, tb_wrapper_top.sv, verilator_stubs/
├── testlists/              # native TOML testlists (per-feature leaves + all.toml groups)
├── assets/                 # ROM/eFuse/shadow preload images
├── docs/                   # VPLAN (.adoc), upgrade notes, ref_test_dev.md
├── smc_sim_cfg.toml        # bare-SMC build/filelist manifest, modes, tool flags
└── smc_wrapper_sim_cfg.toml
```

Taxonomy (shared across SMC / DTP / SEP):

- **vip/** — protocol agents only under `hw/common/dv/vip/ocah_*_vip/`
- **models/** — DUT-local behavioral / reference / sim stand-ins
- **tb/verilator_stubs/** — Verilator-only module overrides (see that README)
- **shim** — design-owned RTL bridges stay in the RTL / top tree, not under `dv/`

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
`docs/ref_test_dev.md` for the full test/sequence/scoreboard walkthrough and the
protocol-VIP proxy pattern.

## Run

```bash
PY=tools/dv/run_dv.py
# Primary entry (smc_wrapper + shared smoke)
python3 $PY --dut smc_wrapper --items smoke --tool verilator
python3 $PY --dut smc_wrapper --items smc_canonical_smoke_test --stage flist --stage sim
python3 $PY --dut smc_wrapper --items all --stage sim --regress
# Secondary bare-smc path (TB macro stubs)
python3 $PY --dut smc --items smoke --tool verilator
python3 $PY --dut smc --items all --tag smoke --tool vcs --cov
```

PASS/FAIL is classified by the global parser registry
(`hw/common/dv/configs/parsers.toml`). The cocotb flow requires positive
evidence from `results.xml`; a clean simulator exit alone is not enough.

The shared OSS runner uses Bender to generate the SMC RTL filelist, then appends
the TB top and the local `models/` + `tb/verilator_stubs/` sources listed in the
sim cfg.
The public filelist is vendor-clean (verify with
`tools/dv/check_no_vendor_paths.py --filelist build/smc_bender.f --target smc`).

## Smoke parity (`--items smoke`, 37 tests)

Bare and wrapper share the same catalog. Verilator baseline (primary = wrapper):

| DUT | Result | Notes |
|---|---|---|
| `--dut smc_wrapper` | **37/37** | official entry |
| `--dut smc` | 37/37 (target) | secondary; same catalog |

I2C note: Verilator codegen of `i2c_wrap`'s `MAX_NUM_I2CS` always_comb can zero
`i2c_en_o`; sequences force GPIO `DATA_CTRL.lsio_select` on I2C0 pads so
`scl_i`/`sda_i` track the OD bus. I3C smoke uses HCI base `0xC000_5000`
(stub `0xBADCAB1E`), not the unmapped `0xC003_A000` hole.

Wrapper-specific notes:
- PLL/PVT windows return OKAY+0 from `pll_wrap`/`pvt_wrap` inside
  `smc_ip_integration` (bare TB used DECERR `0xBADCAB1E`); smoke sequences
  accept either signature as reachability proof.
- CPU ROM/scratch/L1$ use `OCAH4CORECluster_mems` (`prim_rom` /
  `prim_ram_1p`, same macros as SEP) with time-zero backdoor into `.mem` on
  both bare (TB-instantiated integration) and wrapper.
- SYS_OUT stays a TB `tb_smc_output_mem_responder` (SEP outbound posture) with
  `prim_ram_1p` storage; I3C DAT/DCT use `tb_smc_i3c_mem_responder`.
- Bare TB no longer ships local mem/efuse responders: CPU uses
  `smc_cpu_mem_integration`, eFuse uses shared `efuse_bank_model`, GPIO-ctrl
  is DECERR (same as `smc_ip_integration`).
