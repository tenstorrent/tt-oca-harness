# SMU OCAH Open-Source TB

OCAH open-source DV testbench for the **SMU (System Management Unit)**.
Layout follows `hw/sys/sep/` (flow-first cocotb under `cocotb/`).
See [`docs/index.adoc`](docs/index.adoc) for the chapter set:
[`docs/SMU_TB_ARCH.adoc`](docs/SMU_TB_ARCH.adoc) for the testbench
architecture and [`docs/SMU_VPLAN.adoc`](docs/SMU_VPLAN.adoc) for the
verification plan.

**Executable contract:** enrolled groups in [`testlists/all.toml`](testlists/all.toml)
— live green `phase1` **49**, `sep0_all` **53** (no Force; product-pin CTM).

**Green / signoff policy (2026-07-29):** no DUT Force / no TB placeholder.
Raise-stub Force-era bodies live under `cocotb/tests_deferred/` +
`testlists/deferred.toml` — **not** reportable as PASS.

**Group ladder:** `smoke` ⊂ `top5` ⊂ `top10` ⊂ `phase1` (see `testlists/all.toml`).

**OUT / deferred** (SEP=1 / interop / toggle / `needs_real_lcc`): [`testlists/deferred.toml`](testlists/deferred.toml).

```
smu_<scenario>_test
  └─ SmuEnv (`cocotb/env/smu_env.py`)
       ├─ SMC boot / scratch + mailbox observation
       ├─ DTP JTAG TAP BFM
       ├─ External SMN AXI master / OcahAxiSlaveAgent
       └─ SmuScoreboard
```

| Path | Role |
|------|------|
| `tb/tb_top.sv` | `smu_uvm_top` — bare `smu #(.SEP(0))` density TB |
| `cocotb/{env,seq_lib,tests}/` | Live enrolled PyUVM tests |
| `cocotb/tests_deferred/` | Force-era raise stubs (catalog only) |
| `testlists/all.toml` | Enrolled SEP=0 groups (`sep0_all` = 53) |
| `testlists/deferred.toml` | Non-enrolled inventory (not default-included) |
| `smu_sim_cfg.toml` | `--dut smu` sim defaults |
| `smu_wrapper_sim_cfg.toml` | `--dut smu_wrapper` production-wrapper baseline |
| `tb/tb_wrapper_top.sv` | `smu_wrapper_uvm_top` — `hw/top/smu_wrapper` harness |
| `cocotb_wrapper/{env,seq_lib,tests}/` | Wrapper-baseline PyUVM tests |
| `testlists/wrapper.toml` | Wrapper baseline (≠ `sep0_all` signoff) |
| `fw/`, `tools/` | Firmware, readiness |

## BFM Policy

| Interface | VIP / Model |
|-----------|-------------|
| Primary JTAG TAP | `ocah_jtag_vip` |
| External SMN AXI4 | `ocah_axi_vip` (`OcahAxiSlaveAgent` / master) |
| SMC OTP AXI-Lite (over JTAG2AXI) | `ocah_axi_vip` AXI-Lite |
| SMC scratch / mailbox | Backdoor + cocotb polling |
| Cross-trigger / iJTAG | OCAH-local BFM (later) |

## Running (Phase-1 SEP=0)

```bash
# Simulator and bender on PATH (see AGENTS.md for the with/without-companion paths).
mkdir -p "${TMPDIR:?set TMPDIR to a large local scratch directory}"

python3 tools/dv/run_dv.py --dut smu --build-only
python3 tools/dv/run_dv.py --dut smu --items smoke --dry-run

python3 tools/dv/run_dv.py --dut smu --items smoke
python3 tools/dv/run_dv.py --dut smu --items top5
python3 tools/dv/run_dv.py --dut smu --items top10
python3 tools/dv/run_dv.py --dut smu --items phase1

python3 tools/dv/run_dv.py --dut smu --items phase1 --tool xcelium --cov
```

Groups: `smoke` (4), `top5` (5), `top10` (11), `phase1` (49), `smc` (12),
`dtp` (29), `fabric` (14), `phase2` (50), `phase3` (5), `phase4_sep0` (19),
`sep0_all` (53), `sep0_p4_all` (55).

## Signoff sources (dual TB)

| Source | DUT | Signoff role |
|--------|-----|--------------|
| Bare `--dut smu` | `tb/tb_top.sv` (`DUT_TAG=BARE`) | Density / CSR / fabric SEP=0 — `phase1` (49), `sep0_all` (53) |
| Wrapper `--dut smu_wrapper` | `tb/tb_wrapper_top.sv` (`DUT_TAG=WRAPPER`) | Production-pin boot / elab smoke — **≠** `sep0_all` density signoff |

Do not merge wrapper smoke PASS into bare `sep0_all` evidence. Logs carry
`DUT_TAG=` so scoreboards stay distinguishable.

## Production-wrapper baseline (`--dut smu_wrapper`)

A second sim config in this DV root builds `hw/top/smu_wrapper.sv` (via the
`smu_wrapper` Bender target) with two compile profiles:

- `compile_smu_chiplet_no_sep`: wrapper with `NoSepCfg`, `SEP=0`.
- `compile_smu_chiplet_sep_rtl`: wrapper with `DefaultCfg`, `SEP=1` and the
  real SEP EL2 CPU.

OSS already ships `hw/sys/sep/rtl/sep_tcm_wrapper.sv` (Bender). The DV TCM
shim was **removed** (no placeholder). SEP=1 wrapper elab/smoke stay in
`sep_tcm_deferred` until foundry `ram_*` ICCM/DCCM cells exist (the sim-cfg
exclude of `hw/sep/sep_tcm_wrapper.sv` is a stale path). Verilator tooling
shims (`prim_sync2/3`) are shared from
`hw/sys/smc/dv/tb/verilator_stubs/` (see SMC README B1/B2).

### Readiness gates

```bash
python3 hw/sys/smu/dv/tools/smu_wrapper_tb_readiness_test.py --phase source

python3 tools/dv/run_dv.py --dut smu_wrapper \
  --items smu_wrapper_elaboration_no_sep_test --stage flist
python3 hw/sys/smu/dv/tools/smu_wrapper_tb_readiness_test.py \
  --phase filelist \
  --filelist hw/sys/smu/dv/build/smu_wrapper_dut_compile.f
```

### Tests

| Test | Profile | Pass evidence |
|------|---------|---------------|
| `smu_wrapper_elaboration_no_sep_test` | no_sep | profile selection + reset propagation |
| `smu_wrapper_elaboration_sep_rtl_test` | sep_rtl | same, with the real SEP present |
| `smu_smc_smoke_test` | no_sep | SMC ROM firmware runs, scratch `TEST_PASS` |
| `smu_sep_smoke_test` | sep_rtl | boot readiness: SMC CLA arm, SEP boot-ROM fetch → ICCM execution, ≥16 distinct PCs, DCCM result stores |

The SEP smoke is a boot-readiness anchor mirroring the internal
`smu_sep_smoke_test` contract; console/STDOUT checking over the external AXI
path is tracked separately.

### Running

```bash
# Simulator and bender on PATH (see AGENTS.md).
mkdir -p "${TMPDIR:?set TMPDIR to a large local scratch directory}"
# Firmware toolchain: riscv64-unknown-elf-* on PATH, RISCV_TOOLCHAIN, or
# per-tool overrides (e.g. Homebrew): RISCV_GCC/RISCV_OBJCOPY/RISCV_NM.

# Full baseline (regression: no --seed; elab_no_sep + smc_smoke):
python3 tools/dv/run_dv.py --dut smu_wrapper --items smoke \
  --stage flist --stage c_compile --stage hdl_compile --stage sim

# Single test, cached model (--seed only with a single item):
python3 tools/dv/run_dv.py --dut smu_wrapper --items smu_sep_smoke_test \
  --seed 1 --stage c_compile --stage sim
```

Firmware images are built by `fw/build_firmware.py` into `build/firmware/`
(declared per test as `[c_build.*].outputs`, then staged into each per-test
run directory). Results land under `build/runs/<ts>__<tool>__<label>/` with
per-test `result.json` / `results.xml`; record issue evidence as commands,
seeds, and those run paths on the tracking GitHub issue.

## Status

The `SEP=0` `tb_top.sv`, `SmuEnv` and the sequence library are in place:
59 live test bodies under `cocotb/tests/`, 28 non-enrolled bodies under
`cocotb/tests_deferred/`. `sep0_all` (53) is the SMU nightly group in
`.github/workflows/sim.yml`.
