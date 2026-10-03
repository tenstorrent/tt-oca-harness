<!--
SPDX-License-Identifier: Apache-2.0
SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
-->
# SMU OCAH Open-Source TB

Open-source DV package for the **SMU (System Management Unit)**, the
integration level that wires the SMC, the DTP, the SEP and the AXI crossbar
together. This file owns the build-and-run recipes and the package layout.
The other owners are `docs/SMU_TB_ARCH.adoc` (testbench architecture and the
BFM table), `docs/SMU_VPLAN.adoc` (what every enrolled test intends and
checks, and under its Signoff Package the feature list, the scope and
traceability matrix, the release matrix and the component scope),
`docs/SMU_FCOV.adoc` (coverage intent), and the two decision records under
`hw/sys/smu/dv/docs/` (`SMU_DEFERRED_DISPOSITION`, `SMU_COVERAGE_POLICY`).
`docs/index.adoc` is the chapter set.

## What the bench is

**DUT.** `--dut smu` builds `hw/top/smu_wrapper.sv` -- the SMU with the
open-source IP integration attached -- under `tb/tb_wrapper_top.sv`
(`smu_wrapper_uvm_top`), in one compile profile, `compile_smu_chiplet`
(`SEP=1`, the real SEP EL2 core). Every leaf of the regression runs on that
elaboration, so a regression pays one Verilator build and coverage merges across
the whole selection. `smu_wrapper` is a registered
alias of `smu` (`hw/common/dv/configs/duts.toml`), so the two names resolve to
one config, one build cache and one identity; logs carry `DUT_TAG=WRAPPER`.
The `SEP=0` composition (`smu #(.CFG(smu_pkg::NoSepCfg))`: no crossbar, direct ID converters,
SEP aperture and lifecycle tie-offs) is not elaborated by this package; the
names that need it, and the JTAG2AXI abort scenario, which needs an OTP
interface that hangs, are catalogued in
`hw/sys/smu/dv/docs/SMU_DEFERRED_DISPOSITION.adoc`.

**What it verifies.** With `elaboration` firmware, four surfaces of the SMU at its
own boundary: the fabric and address decode (external SMN AXI into SMC,
ID-width conversion, crossbar error handling, alias remap, the inbound and
outbound filters); the SMC reached through the SMU (bring-up, reset control,
mailbox, watchdog, OCTS, security demote); the DTP reached through the SMU
(primary JTAG, STAP selection, boundary scan, the OTP bridge over JTAG2AXI,
cross-trigger routing); and clock, reset and boot sequencing (clock stop,
boot stall, IC_RESET domains, the external boot-sequence gate). With the
real SEP firmware images, the SEP firmware set: SEP boot and firmware execution
under the SMU, lifecycle state broadcast from the SEP eFuse shadow to the SMC
and the DTP, and the entropy stack. `docs/SMU_VPLAN.adoc` cards every leaf.

**Stimulus.** JTAG through `ocah_jtag_vip`; external SMN AXI through
`ocah_axi_vip` (master on the inbound pins, `OcahAxiSlaveAgent` answering the
outbound boundary); product pins driven by the sequences; SMC ROM and SEP
ITCM/DTCM images loaded at time zero; eFuse shadow preload images from
`assets/`. Verdicts are `SmuScoreboard` compares, or -- for the firmware
leaves -- the firmware's own terminal loop, observed by the bench. The one
signal the bench forces (`+esrc_noise_force`, the ESRC raw-noise lanes) and
the other stand-ins on a proof path are recorded, with their scope and
approval fields, in the *Bench stand-ins and exceptions* section of
`hw/sys/smu/dv/docs/SMU_DEFERRED_DISPOSITION.adoc`.

**Simulators.** Verilator runs every enrolled group and is the only
simulator with a build and a coverage section in the sim config; it is
what CI runs. `smu_sim_cfg.toml`
lists `vcs` and `xcelium` as selectable tools, but no enrolled group
runs on them: the cocotb targets on VCS fail the runner on live RTL
assertions while every test passes (issue #1755, open), and `smu_sim_cfg.toml`
declares no Xcelium target of its own -- only the shared
`hw/common/dv/configs/profiles/native.toml` defaults, which no SMU group
selects.

**Frameworks.** cocotb/PyUVM is the default framework and the one every
enrolled group runs. Five scenarios also carry a SystemVerilog UVM
implementation of the same name, selected with `--framework uvm` on VCS
(see "SystemVerilog UVM framework" below); the SV-UVM view shares the sim
config, the testlist and the testbench top with the cocotb flow.

## Tools

Versions are the repository's pins; the second column says where each comes
from, and a value with no pin says so.

| Tool | Version | Pinned in |
|---|---|---|
| Verilator | `v5.052`, built from source in CI and packaged in the `ocah-container` image | `.github/actions/dv-run/action.yml`, `verilator-version` default; `flake.lock` (nixpkgs) for the image |
| Python | 3.11 in CI; `>=3.11,<3.14` accepted | `.github/actions/dv-run/action.yml`, `python-version` default; `pyproject.toml`, `requires-python` |
| cocotb / pyuvm / cocotbext-axi | 2.0.1 / 4.0.1 / 0.1.28 | `uv.lock` (`dv` group); `run_dv.py` bootstraps this environment itself |
| Bender | whatever `pulp-platform/pulp-actions/bender-install@v2.5.1` installs; no Bender version is pinned in this repository | `.github/actions/dv-run/action.yml` |
| g++ | the `g++` package of `ubuntu-latest` at run time; no version pinned. cocotb 2.x compiles with `-fcoroutines`, so a C++20 compiler is required | `.github/actions/dv-run/action.yml` |
| RISC-V GCC (firmware leaves only) | `gcc-riscv64-unknown-elf` + `picolibc-riscv64-unknown-elf` from Debian trixie in the `ocah-toolchain` image; the base image is pinned by digest, the package version floats | `tools/docker/Dockerfile`; `tools/docker/README.md` |

Environment variables the package reads:

| Variable | Read by | Effect |
|---|---|---|
| `TMPDIR` | the runner and the container scripts | scratch; must exist and be large (`AGENTS.md`). Never `/tmp` |
| `RANDOM_SEED` | `smu_base_test`, two fabric sequences | the run seed; set by the runner from `--seed` or its own draw |
| `RISCV_TOOLCHAIN`, `RISCV_PREFIX` | `fw/build_firmware.py`, i.e. every `[c_build.*]` stage | directory and tool prefix (default `riscv64-unknown-elf-`) of a RISC-V toolchain that has picolibc; unset, or without picolibc, the stage re-runs itself in the `ocah-toolchain` container through `scripts/docker-run.sh run-here`. No `PATH` or site probe |
| `SMU_SMC_BOOT_MAX_CYCLES` | `smu_smc_smoke_seq.py` | SMC ROM boot budget in `clk_smu` cycles |
| `SMU_SEP_BOOT_MAX_CYCLES` | `smu_sep_smoke_seq.py`, `smu_sep_boot_health_seq.py` | SEP boot budget |
| `SMU_SEP_FW_MAX_CYCLES` | the `sep_real_fw`, lifecycle and chain sequences | terminal-loop budget for a SEP firmware image |
| `SMU_SEP_SANITY_MAX_CYCLES`, `SMU_SEP_MODULES_MAX_CYCLES`, `SMU_SEP_ENTROPY_MAX_CYCLES` | the sequence of the same name | per-image budgets for the longer firmware runs |
| `OCAH_TOOLCHAIN_ROOTFS` | `scripts/docker-run.sh`, i.e. every `[c_build.*]` stage when `RISCV_TOOLCHAIN` is unset | a toolchain rootfs extracted from the `ocah-toolchain` image; when set and `bwrap` is present the firmware builds run in a bubblewrap sandbox instead of a container (`scripts/docker.md`) |
| `OCAH_BWRAP_EXTRA_BINDS` | `scripts/docker-run.sh`, bubblewrap backend only | space-separated host paths bound into the sandbox at their own paths. The sandbox holds the rootfs (read-only), this repository at its real path and `/tmp`, and nothing else, so every host path a firmware build reaches outside those is listed here: the paths your `uv` binary and the Python interpreter behind the repository's `.venv` live under, `TMPDIR` when it is not under `/tmp` (gcc writes its temporaries there), and any `RISCV_TOOLCHAIN` |
| `UV` (or `PYTHON`) | `hw/common/dv/fw/preamble.mk`, i.e. the SEP firmware engine that every `[c_build.sep_dv_fw*]` stage and `sep_smoke` run | `PYTHON` defaults to `$(UV) --directory <repo> run --locked` and `UV` to `uv`; the SEP engine's ELF-to-vmem step runs through it. The toolchain rootfs carries no `uv` and the sandbox replaces `PATH`, so a sandboxed build sets `UV` to the absolute path of a host `uv` on a bound path (or `PYTHON` to an interpreter that has `pyelftools`). The bubblewrap backend forwards the caller's environment; `make -f ocah.mk ... UV=<path>` passes the same value to a standalone firmware build |

## Quick start

Three commands matter, and each runs in a different place.

```bash
mkdir -p "${TMPDIR:?set TMPDIR to a large local scratch directory}"
python3 tools/dv/run_dv.py --validate-configs
python3 tools/dv/run_dv.py --dut smu --list

# 1. PR gate. `.github/workflows/sim.yml` runs the default `smoke` group on
#    every hardware diff on a hosted runner (Verilator, no RISC-V toolchain):
#    two toolchain-free leaves.
python3 tools/dv/run_dv.py --dut smu --items smoke

# 2. Nightly and weekly. `.github/workflows/regress.yml` runs this as the
#    release qualification set: 69 toolchain-free leaves, one seed nightly,
#    three weekly with --cov on the large runner. Their `elaboration` firmware
#    stage only writes zero-filled preload images (Python, no toolchain).
python3 tools/dv/run_dv.py --dut smu --items hosted

# 3. The whole package: `all` adds the SEP firmware set (101 leaves). The
#    firmware c_build stages build every image in the toolchain container
#    (unless RISCV_TOOLCHAIN names a picolibc gcc), so make that toolchain
#    available once first -- the container image, as below, or the rootfs
#    route under "Firmware toolchain". Nothing schedules this group: the
#    hosted runners have Verilator and no container toolchain, so the run of
#    record for `all` is a developer or self-hosted run.
./scripts/docker-run.sh build
python3 tools/dv/run_dv.py --dut smu --items all
```

`fw_boot` (the elaboration leaf plus `smu_smc_smoke_test` and
`smu_sep_smoke_test`) is the firmware boot smoke; it needs the SMC and SEP
firmware compiles, so it is not the CI tier. `elaboration` is the elaboration
leaf alone. Every group of the testlist, with its size and what it is for,
is the *Regression Groups* section of `docs/SMU_VPLAN.adoc`.

### Firmware toolchain

Every `[c_build.*]` stage except `elaboration` runs `fw/build_firmware.py`,
which uses the caller's `RISCV_TOOLCHAIN` when that gcc has picolibc and
otherwise re-runs itself through `scripts/docker-run.sh run-here`. A
firmware leaf is therefore satisfied in one of three ways:

* **A picolibc gcc on the host.** Export `RISCV_TOOLCHAIN=<dir>` (and
  `RISCV_PREFIX` if the tools are not `riscv64-unknown-elf-`); no container or
  sandbox is entered. `uv` must be on `PATH` for the SEP engine's post-link
  step.
* **The container image.** `./scripts/docker-run.sh build` builds it with Nix
  and needs a container engine (Docker or rootless Podman); on a host without
  Nix the script runs Nix inside `docker.io/nixos/nix`, so the engine must be
  able to pull that image (`scripts/docker.md`).
* **An extracted rootfs under bubblewrap**, for a host where no container
  engine works. Extract the image's rootfs once (`scripts/docker.md`,
  "Bubblewrap backend"), then export, before `run_dv.py`:
  `OCAH_TOOLCHAIN_ROOTFS=<rootfs>`; `OCAH_BWRAP_EXTRA_BINDS` naming the host
  paths the build still reaches outside the repository, `/tmp` and the rootfs
  (where your `uv` binary and the interpreter behind `.venv` live, `TMPDIR`
  when it is not under `/tmp`); and `UV=<absolute path of that uv>`, because
  the sandbox replaces `PATH` with the rootfs's and the rootfs has no `uv`.
  The bubblewrap backend forwards the caller's environment, so those three
  exports reach the `make` the SEP engine runs; a standalone
  `make -f ocah.mk ocah-dv-fw-tests TARGET=sep TEST=<name> UV=<path>` takes
  the same value on its command line.

Results land under `build/runs/<timestamp>__<tool>__<label>/` with a per-test
`result.json` and `results.xml`. `--seed` applies to a single item; a
multi-item regression draws its own seeds and reports them per test.

## SystemVerilog UVM framework (`--framework uvm`)

The SV-UVM view shares this DV root, sim config, testlist and testbench top
with the cocotb flow: `smu_sim_cfg.toml` declares it as the `[frameworks.uvm]`
overlay (same Bender RTL recipe), and `--dut smu --framework uvm` selects it.
A testlist scenario carries both implementations in its `module` binding map
(`module = { cocotb = "...", uvm = "..." }`), so the same `--items` name
selects the same VPLAN scenario in either framework; the UVM class name is
the `uvm` entry (`+UVM_TESTNAME`). A group runs its UVM-implemented subset;
naming a scenario with no `uvm` entry errors.
VCS only: Verilator has no SV-UVM support. The bench architecture is in
`docs/SMU_TB_ARCH.adoc` ("SystemVerilog UVM Realization"); the framework
conventions it follows are in `hw/common/dv/docs/uvm-framework.adoc`.

Five scenarios are bound, each covering a different class of SMU behaviour,
and each judged by an always-on scoreboard feature whose reference model is
independent of the sequence that drove the stimulus:

| Scenario | Aspect | Scoreboard feature | Negative plusarg |
|---|---|---|---|
| `smu_dtp_jtag_smoke_test` | primary TAP: IDCODE, BYPASS latency, TRST and power-on reset back to Test-Logic-Reset | the embedded DTP's `ir_decode`, `idcode`, `bypass` | `+SMU_PTAP_IDCODE_NEGATIVE` |
| `smu_jtag_reset_override_test` | IC_RESET TDR: the external and SMC cold-reset slices overridden one at a time, readback of the 155-bit register | `ic_reset_tdr` | `+SMU_IC_RESET_SCOREBOARD_NEGATIVE` |
| `smu_smc_dtp_jtag2axi_smoke_test` | SMC-fabric JTAG2AXI: CAPS, SINGLE_OP 32- and 64-bit write/readback, series INCR write/readback | the embedded DTP's `jtag2axi_req` (passive monitor on the DTP's SMC debug port) and `jtag2axi_status` | `+SMU_J2A_SCOREBOARD_NEGATIVE` |
| `smu_boot_stall_jtag_cold_reset_matrix_test` | DEBUG_CONTROL boot stall across cold reset, TRST and the GPIO pad, on the real eFuse sense | `debug_control_tdr`, `boot_gate` | `+SMU_DEBUG_CONTROL_SCOREBOARD_NEGATIVE`, `+SMU_BOOT_GATE_SCOREBOARD_NEGATIVE` |
| `smu_ext_boot_seq_gate_test` | the external boot-sequence gate on the SMC fuse-reset release | `boot_gate` | `+SMU_BOOT_GATE_SCOREBOARD_NEGATIVE` |

Every scenario runs at least 16 seeded passes in one simulation
(`ocah_test.MinDefaultLoops`) and hands the DUT back as it found it. The
SV-UVM loop knobs (`SMU_TEST_LOOPS`, `SMU_<TEST>_LOOPS`, `SMU_RANDOM_COUNT`)
are **plusargs**, not environment variables.

```bash
# SV-UVM build only (VCS)
python3 tools/dv/run_dv.py --dut smu --framework uvm --build-only

# PyUVM (cocotb) and SV-UVM, same logical scenario name
python3 tools/dv/run_dv.py --dut smu --items smu_dtp_jtag_smoke_test --tool verilator
python3 tools/dv/run_dv.py --dut smu --framework uvm --items smu_dtp_jtag_smoke_test --seed 1

# Smoke group, UVM-implemented subset
python3 tools/dv/run_dv.py --dut smu --framework uvm --items smoke

# Scoreboard negative validation: a corrupted prediction must FAIL the run
python3 tools/dv/run_dv.py --dut smu --framework uvm --items smu_jtag_reset_override_test \
  --plusarg +SMU_IC_RESET_SCOREBOARD_NEGATIVE

# Loop-count knobs, resolved specific-first (per test, per group, suite-wide)
python3 tools/dv/run_dv.py --dut smu --framework uvm --items smu_ext_boot_seq_gate_test \
  --plusarg +SMU_EXT_BOOT_SEQ_GATE_TEST_LOOPS=4
```

To port another cocotb scenario: add `uvm/seq_lib/<name>_seq.svh` on
`smu_base_test_seq` (TAP operations, TDR and JTAG2AXI accesses, bounded pin
waits and named evidence through `attach_evidence` / `check_evidence` /
`finalize_evidence`), add `uvm/tests/<name>.svh` on `smu_base_test`
(override `create_scenario_seq()`, the loop-knob hooks, and
`configure_test_cfg()` for the scoreboard features it requires), add both
`include`s to `smu_seq_lib_pkg.sv` and `smu_tests.sv`, and give the
testlist entry a `uvm` binding. A scenario whose claim no existing feature
judges adds a reference model and a feature to `smu_scoreboard` first.

## Layout

Every directory and top-level file under `dv/` is listed here.

| Path | Role |
|---|---|
| `README.md` | this file: build, run, layout |
| `assets/` | the five SEP eFuse shadow preload images: `default_sep_efuse_shadow_reg.preload` and `sep_efuse_shadow_lc_{test_dev,prod,prod_end,rma_chiplet}.preload`, which set the diff-encoded lifecycle state word. Each carries its SPDX header as `//` comment lines, which the preload readers skip |
| `cocotb/{env,seq_lib}/` | the shared half of the PyUVM environment: `env/` holds `SmuEnv`, `SmuScoreboard`, the evidence map and `smu_fcov.py`; `seq_lib/` the sequences and helpers written against the SMU's own interfaces (address map, lifecycle table, AXI, JTAG and filter helpers, the PTAP smoke sequence) |
| `cocotb_wrapper/{env,seq_lib,tests}/` | the `--dut smu` framework tree: `tests/` holds every test body and the base test; `env/` the wrapper env pieces (`smu_boot_scoreboard.py`, `smu_sep_cpu_trace_monitor.py`, `smu_env_cfg.py`); `seq_lib/` the wrapper sequences. `env` and `seq_lib` are namespace packages spanning this tree and `cocotb/`, so an import resolves in either |
| `cov/` | coverage collateral: `config/verilator/smu_wrapper_cov_scope.vlt` and `smu_wrapper_coverage_policy.toml`, `config/vcs/smu_wrapper_cov_scope.hier` (written by `gen_smu_cov_scope.py`; its README states the rule and how it differs from the Verilator scope), and `sv/` with the ten cover-property modules; intent in `docs/SMU_FCOV.adoc` |
| `docs/` | `index.adoc` and the three chapters: `SMU_TB_ARCH.adoc`, `SMU_VPLAN.adoc`, `SMU_FCOV.adoc` |
| `fw/` | this root's own firmware: `build_firmware.py`, `common/` (SMC and SEP start-up and linker files), `tests/` (the SMC smoke, the SEP smoke and the two SEP arm images). The `sep_real_fw` images come from `hw/sys/sep/dv/fw/` instead |
| `tb/` | `tb_wrapper_top.sv` (the HDL top, `smu_wrapper_uvm_top`, one module in two shapes: the cocotb port list and the SV-UVM harness), `smu_tb_signal_list.svh` (the single declaration of its TB signals, expanded as ports or as internal signals), `smu_tb_if.sv` (the SMU-local TB interface of the SV-UVM shape) and `smu_wrapper_public_scope.vlt` (the Verilator public-signal scope `smu_sim_cfg.toml` `[build.verilator].public_scope` names) |
| `uvm/{env,seq_lib,tests}/` | the SV-UVM realization (`--framework uvm`, VCS): `env/` holds the bench constants, the two cfg levels, the virtual sequencer, the SMU-level reference models, the reset-release monitor, `smu_scoreboard` and `smu_env`; `seq_lib/` the JTAG and JTAG2AXI operation sequences, `smu_base_test_seq` and one scenario sequence per bound test; `tests/` `smu_base_test`, one thin test class per scenario and the `smu_tests.sv` manifest the top includes |
| `testlists/` | `all.toml`, the SMU regression and the one root `smu_sim_cfg.toml` selects |
| `tools/` | `smu_wrapper_tb_readiness_test.py`, the static readiness gates below |
| `smu_sim_cfg.toml` | the `--dut smu` launch config: Bender targets, the single compile profile, run modes, `c_build` stages, the coverage scope and policy files |
| `build/` | generated: models, firmware, `build/runs/`; gitignored |

`assets/`, `cocotb_wrapper/`, `fw/`, `tools/` and `uvm/` are additional to the shared
DV directory set (`cocotb/`, `cov/`, `docs/`, `tb/`, `testlists/`); each is
held here because:

* `assets/` -- a preload image is an input to a scenario, so it belongs beside
  the testlist that names it; the lifecycle leaves select their image by name.
* `cocotb_wrapper/` -- `smu_sim_cfg.toml` names it as the framework tree of
  `--dut smu`, so the runner resolves the test bodies there, and the env and
  sequences written against the SMU's own interfaces stay under `cocotb/`,
  which the same config puts on the import path as the other half of the
  `env` and `seq_lib` namespace packages.
* `fw/` -- the SMC smoke and the SEP smoke/arm images are stimulus whose source
  must be versioned with the tests that boot it; `build_firmware.py` builds
  them into `build/firmware/`.
* `tools/` -- the readiness gates check the wrapper TB against its source and
  its filelist without a simulation, and are not tests.
* `uvm/` -- the SystemVerilog UVM realization of the scenarios that carry
  one, the same layout the DTP, SEP and SMC benches use for theirs
  (`hw/common/dv/docs/uvm-framework.adoc`).

## Compile profile and images (`--dut smu`)

The `ram_<depth>x39` ICCM/DCCM macros that `hw/sys/sep/rtl/sep_tcm_wrapper.sv`
instantiates come from the upstream VeeR `mem_lib.sv` on the `sep_el2` Bender
closure and have no init-file hook, so `tb/tb_wrapper_top.sv` backdoor-loads
`+sep_itcm_hex` / `+sep_dtcm_hex` into their `ram_core` arrays at time zero,
de-interleaved into the EL2 bank/row layout with per-word Hsiao ECC, and counts
qualified bank writes at the `sep_tcm_wrapper` request port for the DCCM-store
evidence. This mirrors the SEP DV TB backdoor (`hw/sys/sep/dv/tb/tb_top.sv`,
`` `BD_ICCM `` / `` `BD_DCCM ``). A missing image is fatal at t=0 rather than
a boot timeout. `smu_sep_rom_tcm_load_test` is the exception: it boots from
`+sep_boot_rom_hex` with `+sep_no_tcm_preload` and loads its own TCM, covering
the step the backdoor hides.

The SMC boot path's MEM_ZERO FSM writes every word of scratch RAM after the
time-zero backdoor load unless held off; `tb_wrapper_top.sv` asserts that hold
whenever `+smc_scratch_ram_hex` supplies an image.

Firmware images are declared per test as `[c_build.*].outputs` and staged
into each per-test run directory. Every stage runs `fw/build_firmware.py`: its
own freestanding images land in `build/firmware/`, and for the SEP=1 leaves it
also builds the selected image of the SEP firmware engine (`hw/sys/sep/dv/fw`,
`--sep-test {fw_target}`; the dual leaves add one SMC engine image) into
`hw/sys/<sys>/dv/fw/build/tests/`. Those link against picolibc and `libsep.a`,
so the builder uses the caller's `RISCV_TOOLCHAIN` only when that gcc has
picolibc and otherwise re-runs itself inside the `ocah-toolchain` container
(`scripts/docker-run.sh run-here`).

`+esrc_noise_force` (three entries of `sep_real_fw` / `sep_entropy`) drives
the twelve ESRC raw-noise lanes from `cocotb_wrapper/seq_lib/esrc_noise.py`, because
the ring oscillators do not self-oscillate under Verilator; the ESRC sample
clock `entropy_rosc_sample_clk_i` is driven at 3 ns by the TB for the same
leaves. What that force does and does not prove is recorded in the disposition
record's stand-ins section, together with `+skip_fuse_sense`, the `prim_sync`
stand-ins and the eFuse models.

`+skip_fuse_sense` replaces the SMC (and, on `sep_rtl`, the SEP) eFuse sense
with the shadow-register preload named beside it. It is declared per test in
`testlists/all.toml`, each entry carrying the reason its claim tolerates
the skip; no `[run_modes.*]` table passes it. The five boot-stall leaves
(`smu_boot_stall_*`, `smu_dft_*_boot_stall_test`, `smu_clock_stop_coordination_test`)
carry no skip: the SMC eFuse controller senses the `+smc_efuse_hex` image
through the wrapper's eFuse model, so the `smc_fuse_reset_n_delayed_o` release
they gate is the controller's own, and their log reads `Not skipping fuse sense`.

### Readiness gates

```bash
python3 hw/sys/smu/dv/tools/smu_wrapper_tb_readiness_test.py --phase source

python3 tools/dv/run_dv.py --dut smu \
  --items smu_wrapper_elaboration_test --stage flist
python3 hw/sys/smu/dv/tools/smu_wrapper_tb_readiness_test.py \
  --phase filelist \
  --filelist hw/sys/smu/dv/build/smu_wrapper_dut_compile.f
```

### Single test, cached model

```bash
# Firmware toolchain (firmware leaves only): RISCV_TOOLCHAIN with picolibc,
# otherwise the ocah-toolchain container via scripts/docker-run.sh run-here.
python3 tools/dv/run_dv.py --dut smu --items smu_sep_smoke_test \
  --seed 1 --stage c_compile --stage sim
```

## Enrollment

`--dut smu` carries the regression: `all` is every entry of
`testlists/all.toml` (101), `hosted` is the toolchain-free subset the workflows
run (69), and the rest of `all` is the SEP firmware set.

Every test entry of the testlist is in `all`, and every test module under
`cocotb_wrapper/tests/` is enrolled. Names that cannot run or cannot pass on
this bench -- among them the SEP=0 composition proofs, which need the
`smu #(.CFG(smu_pkg::NoSepCfg))` elaboration this package does not build -- are enrolled
nowhere and have no module in the tree:
`hw/sys/smu/dv/docs/SMU_DEFERRED_DISPOSITION.adoc` catalogues each with the
condition it needs, and a body written for one of them is kept in git history
and restored when that condition clears.
