# SMU OCAH Open-Source TB

OCAH open-source DV testbench for the **SMU (System Management Unit)**.
Layout follows `hw/sys/sep/` (flow-first cocotb under `cocotb/`).

**Master VPLAN (P1 + P2):** [`docs/SMU_VPLAN.md`](docs/SMU_VPLAN.md)
— P1 **24/24 VCS DONE**; P2 SMC↔DTP protocol ~14 planned; no P3/P4.

**P1 executable detail:** [`docs/SMU_OSS_VPLAN_PHASE1.md`](docs/SMU_OSS_VPLAN_PHASE1.md)
(`smoke` ⊂ `top5` ⊂ `top10` ⊂ `phase1`).

**OUT / deferred** (SEP=1 / interop / toggle): [`testlists/deferred.toml`](testlists/deferred.toml)
+ `SMU_VPLAN.md` Appendix A.

```
smu_<scenario>_test
  └─ SmuEnv (planned)
       ├─ SMC boot / scratch + mailbox observation
       ├─ DTP JTAG TAP BFM
       ├─ External SMN AXI master / OcahAxiRam
       └─ SmuScoreboard
```

| Path | Role |
|------|------|
| `docs/` | SPEC, CSR, TB_ARCH, **VPLAN (P1/P2 master)**, PHASE1 detail, FCOV |
| `tb/tb_top.sv` | `smu_uvm_top` skeleton → wire `SEP=0` DUT next |
| `cocotb/{env,seq_lib,tests}/` | PyUVM layers (bodies = later phase) |
| `testlists/all.toml` | Phase-1 includes only (`smc`/`dtp`/`fabric`) |
| `testlists/deferred.toml` | Non-Phase-1 inventory (not default-included) |
| `smu_sim_cfg.toml` | `--dut smu` sim defaults |
| `smu_wrapper_sim_cfg.toml` | `--dut smu_wrapper` production-wrapper baseline |
| `tb/tb_wrapper_top.sv` | `smu_wrapper_uvm_top` — `hw/top/smu_wrapper` harness |
| `cocotb_wrapper/{env,seq_lib,tests}/` | Wrapper-baseline PyUVM tests |
| `testlists/wrapper.toml` | Wrapper baseline catalog |
| `shims/mem/`, `fw/`, `tools/` | OSS TCM stand-in, firmware, readiness |

## BFM Policy

| Interface | VIP / Model |
|-----------|-------------|
| Primary JTAG TAP | `ocah_jtag_vip` |
| External SMN AXI4 | `ocah_axi_vip` (`OcahAxiRam` / master) |
| SMC OTP AXI-Lite (over JTAG2AXI) | `ocah_axi_vip` AXI-Lite |
| SMC scratch / mailbox | Backdoor + cocotb polling |
| Cross-trigger / iJTAG | OCAH-local BFM (later) |

## Running (Phase-1 SEP=0)

```bash
source bin/setup_env.sh
export TMPDIR=/localdev/$USER/TMPDIR
mkdir -p "$TMPDIR"

python3 tools/dv/run_dv.py --dut smu --build-only
python3 tools/dv/run_dv.py --dut smu --items smoke --dry-run

python3 tools/dv/run_dv.py --dut smu --items smoke
python3 tools/dv/run_dv.py --dut smu --items top5
python3 tools/dv/run_dv.py --dut smu --items top10
python3 tools/dv/run_dv.py --dut smu --items phase1

python3 tools/dv/run_dv.py --dut smu --items phase1 --tool xcelium --cov
```

Groups: `smoke`, `top5`, `top10`, `phase1`, `smc`, `dtp`, `fabric`.

## Production-wrapper baseline (`--dut smu_wrapper`)

A second sim config in this DV root builds `hw/top/smu_wrapper.sv` (via the
`smu_wrapper` Bender target) with two compile profiles:

- `compile_smu_chiplet_no_sep`: wrapper with `NoSepCfg`, `SEP=0`.
- `compile_smu_chiplet_sep_rtl`: wrapper with `DefaultCfg`, `SEP=1` and the
  real SEP EL2 CPU.

The foundry `sep_tcm_wrapper` is replaced by the vendor-free
`shims/mem/sep_tcm_wrapper.sv` (exclude_files + sources). There are **no**
DV shadows that override product wrapper / SMC reset / DFX modules.
Verilator tooling shims (`prim_sync2/3`) are shared from
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
source bin/setup_env.sh
export TMPDIR="$PWD/hw/sys/smu/dv/build/TMPDIR"
mkdir -p "$TMPDIR"
# Firmware toolchain: riscv64-unknown-elf-* on PATH, RISCV_TOOLCHAIN, or
# per-tool overrides (e.g. Homebrew): RISCV_GCC/RISCV_OBJCOPY/RISCV_NM.

# Full baseline (both profiles compile; all four tests):
python3 tools/dv/run_dv.py --dut smu_wrapper --items smoke --seed 1 \
  --stage flist --stage c_compile --stage hdl_compile --stage sim

# Single test, cached model:
python3 tools/dv/run_dv.py --dut smu_wrapper --items smu_sep_smoke_test \
  --seed 1 --stage c_compile --stage sim
```

Firmware images are built by `fw/build_firmware.py` into `build/firmware/`
(declared per test as `[c_build.*].outputs`, then staged into each per-test
run directory). Results land under `build/runs/<ts>__<tool>__<label>/` with
per-test `result.json` / `results.xml`; record issue evidence as commands,
seeds, and those run paths on the tracking GitHub issue.

## Status

Docs + Phase-1 testlists are in place. Cocotb env/sequences/test bodies and a
fully-wired `SEP=0` `tb_top.sv` are the next implementation step
(`SMU_OSS_VPLAN_PHASE1.md` §6).
