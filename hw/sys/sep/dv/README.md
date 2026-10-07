<!-- SPDX-License-Identifier: Apache-2.0 -->
# SEP DV

## Overview

DV environment for the SEP (Security Processor) subsystem. The DUT is
`sep_wrapper` (`hw/top/sep_wrapper.sv`): the bare `sep` core
(`hw/sys/sep/rtl/sep.sv`) plus its IP integration
(`hw/top/sep_ip_integration.sv`: real memory macros and the generic eFuse
model). One testbench top (`tb/tb_top.sv`) serves two realizations: PyUVM on
cocotb, and SystemVerilog UVM on VCS (`--framework uvm`). Stimulus is a
cocotbext-axi master on the CPU LSU splice (`s_axi_*`), a second master on the
SMN-inbound port (`m_axi_*`), and VeeR EL2 firmware boot on the `cpu` and
`rom_fw` paths. Verilator is the acceptance backend. VCS and Xcelium are
development backends, and VCS runs the graded coverage and the SV-UVM
realization.

## Getting Started

```bash
python3 tools/dv/run_dv.py --dut sep --items all --list               # the test catalog
python3 hw/sys/sep/dv/cocotb/env/run_golden_selftests.py               # golden-model self-tests, no simulator
python3 tools/dv/run_dv.py --dut sep --build-only                      # filelist and Verilator build
python3 tools/dv/run_dv.py --dut sep --items smoke                     # the pull-request gate
python3 tools/dv/run_dv.py --dut sep --items all --regress \
  --sim-jobs 8 --build-jobs 24                                         # every graded test
python3 tools/dv/run_dv.py --dut sep --framework uvm --items smoke     # the SV-UVM subset, on VCS
```

`--items` takes a test name or a testlist group: `smoke`, `all`, `cpu_stub`,
`cpu`, `rom_fw` or `rom_fw_smoke`. The "Regression Groups" section of
`docs/SEP_VPLAN.adoc` defines the groups and the CI tiers that run them.

* Pass both job counts. `--sim-jobs` defaults to 1, which runs the leaves one
  at a time, and `--build-jobs` uses the `--sim-jobs` value when it is not
  given. Set both from `nproc`. Keep the
  firmware classes near 8, because the threaded VeeR EL2 model can stall near
  reset.
* `all` contains the `cpu` firmware tests, so it needs a picolibc-enabled
  RISC-V GCC (see [Prerequisites](#prerequisites)). `smoke` needs no firmware
  toolchain.
* For one named test, include `--stage hdl_compile`. `--stage sim` alone reuses
  the model on disk, and a stale model can report a pass that the current RTL
  does not give:

  ```bash
  python3 tools/dv/run_dv.py --dut sep --items sep_axi_smoke_test \
    --stage flist --stage hdl_compile --stage sim
  ```

* `--stage hdl_compile` rebuilds the model when an SV source or the build
  configuration changes. A Python-only change reuses the model.

* Firmware tests build their image in `--stage c_compile` (`fw/fw.mk`).
* Reproduce a failing leaf with `--stage sim --seed N`.

Per-run logs go to `build/runs/<run-id>/` (gitignored). A PASS needs positive
evidence from `results.xml`. A clean simulator exit is not evidence.

| Document | What it covers |
| --- | --- |
| [`docs/index.adoc`](docs/index.adoc) | The SEP DV book: the three top-level documents below |
| [`docs/SEP_TB_ARCH.adoc`](docs/SEP_TB_ARCH.adoc) | VIP selection, testbench hierarchy, HDL top and its probe exceptions, run modes and RTL targets, eFuse content selection, memory, eFuse and SPI models, CPU-trace reconstruction, Boot ROM and Key Manager `rom_main` builds, the SV-UVM realization and adding a scenario |
| [`docs/SEP_VPLAN.adoc`](docs/SEP_VPLAN.adoc) | Verification strategy, scope, traceability, testcase summaries, shared Phase 3 rules, regression groups, SV-UVM smoke set and known limitations; includes the testcase contracts below |
| [`docs/SEP_VPLAN_TEST_CONTRACTS.adoc`](docs/SEP_VPLAN_TEST_CONTRACTS.adoc) | Detailed testcase procedures, checkers, controls, logged proof and pass criteria; included by `SEP_VPLAN.adoc` |
| [`docs/SEP_FCOV.adoc`](docs/SEP_FCOV.adoc) | Functional coverage plan, code-coverage collection, the compile-time scope and the exclusion lists, closure policy |
| [`doc/integrator/src/defines.adoc`](../../../../doc/integrator/src/defines.adoc) | Project defines chapter of the Integrator Guide |
| [`../doc/index.adoc`](../doc/index.adoc) | Design specification |
| [`hw/common/dv/README.md`](../../../common/dv/README.md) | Shared VIPs, BFM ownership, and the promotion checklist |
| [`tools/dv/doc/run-dv.adoc`](../../../../tools/dv/doc/run-dv.adoc) | Runner options, the site layer, and the coverage stages |

## Prerequisites

| Need | Why | Notes |
|---|---|---|
| Verilator 5.x (the tag `.github/actions/dv-run/action.yml` pins) | the acceptance backend | 5.046 fails the `--cov` C++ compile (`__PVT__MLKEM_SHARED_KEY`) |
| g++ ≥ 10 | Verilator `--timing` / `-fcoroutines` | g++ 8.5 fails with `unrecognized command line option '-fcoroutines'` |
| Python ≥ 3.11 | launcher | `pyproject.toml` `requires-python` |
| uv | every stage, including `--items smoke` | Must be on `PATH`. `run_dv.py` runs itself again inside the locked DV environment (root `uv.lock`, `dv` group). A missing binary exits 2 before any stage runs |
| Bender | filelist (`--stage flist`) | Must be on `PATH` |
| ccache | Verilator object cache | `[build.verilator] ccache = true`. A missing binary fails the C++ compile |
| RISC-V GCC + picolibc | `--stage c_compile` (TCM firmware, Boot ROM, KM `rom_main`) | A host GCC without `--specs=picolibc.specs` falls back to the `ocah-container` image (`scripts/docker-run.sh`, built from `nix/container.nix`). Not needed for `--items smoke` |
| VCS | graded `--cov` and SV-UVM | `VCS_HOME`, the simulator license variable and any library path your VCS install needs (site layer, `tools/dv/doc/run-dv.adoc`) |

| Variable | When it is needed |
|---|---|
| `PATH` | `uv`, `verilator`, `python3`, `bender` and `ccache`; a RISC-V GCC for `--items all`, `cpu`, `rom_fw` and `--tag boot` |
| `RISCV_TOOLCHAIN`, `RISCV_PREFIX` | Optional override for `--stage c_compile`. Unset, the stage probes a site toolchain, then a local xPack install, then the container |
| `OCAH_DV_SKIP_UV` | `1` on a host that already supplies the `dv` dependency group. It skips only the uv re-execution |
| `OCAH_ROOT` | Firmware `make` by hand only (`OCAH_ROOT="$PWD"` from the repository root) |
| `TMPDIR` | Large local scratch for sim and build temporaries |

The VeeR EL2 config snapshot is committed collateral, so no setup step is
needed. See [Troubleshooting](#troubleshooting) if a build complains about it.

## Layout

| Path | Contents |
| --- | --- |
| `tb/` | `sep_uvm_top` (`tb_top.sv`), the core both realizations share, the TB signal list, the outbound-mailbox console model, and the preload images |
| `cocotb/` | PyUVM realization: `env/`, `seq_lib/`, `tests/`, and the pre-sim hook `dv_sim_prestage.py` |
| `uvm/` | SV-UVM realization: `env/`, `seq_lib/`, `tests/` |
| `cov/` | VCS code-coverage scope and exclusion lists (`cov/config/vcs/`) and the FCOV sampler (`cov/sv/sep_fcov.sv`, VCS only) |
| `fw/` | DV firmware (`fw.mk`, built by `c_compile`); the shared engine finds it at `hw/{ip,sys}/*/dv/fw/fw.mk`. The product Boot ROM is at `../bootrom/` |
| `testlists/` | TOML testlists; `all.toml` defines the groups |
| `models/` | The DV-owned `sep_external` RDL and its generated headers |
| `shims/` | The `sep_cpu` stub (no_cpu build) and the entropy ring oscillator |
| `docs/` | The documents above |
| `sep_sim_cfg.toml` | Simulation configuration |
| `sep_public_scope.vlt` | Scoped Verilator public list |

## Troubleshooting

**`Define or directive not defined: '`TEC_RV_ICG'`** (from
`vendor/chipsalliance/Cores-VeeR-EL2/upstream/design/lib/beh_lib.sv`) — the
committed VeeR EL2 config snapshot is missing or damaged. Check it:

```bash
grep TEC_RV_ICG vendor/chipsalliance/Cores-VeeR-EL2/overlay/snapshots/sep/common_defines.vh
# expect: `define TEC_RV_ICG clockhdr
```

Restore it from git. Do not regenerate it. The snapshot is committed
collateral (see that package's `Bender.yml`). It is in `overlay/`, so
`bender vendor init`, which recreates `upstream/` only, does not touch it.

**`unrecognized command line option '-fcoroutines'`** — g++ is too old for
Verilator `--timing`. See [Prerequisites](#prerequisites).

**`no picolibc-enabled RISC-V toolchain`** — host `RISCV_TOOLCHAIN` has no
`--specs=picolibc.specs`. Leave `RISCV_TOOLCHAIN` unset and keep
`scripts/docker-run.sh` runnable, or point `RISCV_TOOLCHAIN` at a picolibc
install.

**`No module named tt_boot_manifest`** — the manifest packer submodule is not
checked out. Only Boot ROM builds need it. See "Boot ROM Firmware Builds" in
[`docs/SEP_TB_ARCH.adoc`](docs/SEP_TB_ARCH.adoc#_boot_rom_firmware_builds).

**`[ocah_path_plusargs] +<name>=<path> is not a readable file`** at time 0 —
the bench opens every file-path plusarg it consumes (`+sep_boot_rom_hex`,
`+km_rom_hex`, `+sep_efuse_hex`, `+sep_shadow_reg_preload`, ...) before any
clock or image load. `ocah_require_file_plusargs`
(`hw/common/dv/vip/ocah_lib/uvm/ocah_path_plusargs.svh`) does this from
`tb/tb_top.sv`, and `require_file_plusargs` (`ocah_lib`) does it from
`sep_base_test.build_phase`. A stale or mistyped path fails the run at once,
not after the boot timeout. Fix the path in the testlist entry or the run
mode. An absent plusarg is not an error.

## Contributing

Read [`CONTRIBUTING.md`](../../../../CONTRIBUTING.md) for the pull-request
process, SPDX headers, and the lint and format commands. A new scenario is one
test in `cocotb/` and, optionally, its SV-UVM twin in `uvm/`; "Adding a
Scenario to the SV-UVM Realization" in
[`docs/SEP_TB_ARCH.adoc`](docs/SEP_TB_ARCH.adoc) is the checklist. Before a
pull request, check that the filelist is vendor-clean:

```bash
python3 tools/dv/check_no_vendor_paths.py --filelist <sep.flist>
```
