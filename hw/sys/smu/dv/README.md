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
checks), `docs/SMU_FCOV.adoc` (coverage intent), and the decision records
under `hw/sys/smu/doc/dv/` (`SMU_FEATURE_LIST`, `SMU_SCOPE_TRACEABILITY`,
`SMU_DEFERRED_DISPOSITION`, `SMU_RELEASE_MATRIX`, `SMU_COVERAGE_POLICY`,
`SMU_HOSTED_COMPONENT_SIGNOFF`). `docs/index.adoc` is the chapter set.

## What the bench is

**DUT.** `--dut smu` builds `hw/top/smu_wrapper.sv` -- the SMU with the
open-source IP integration attached -- under `tb/tb_wrapper_top.sv`
(`smu_wrapper_uvm_top`), in one compile profile, `compile_smu_chiplet`
(`SEP=1`, the real SEP EL2 core). Every leaf of the regression runs on that
elaboration, so a regression pays one Verilator build and coverage merges across
the whole selection. `smu_wrapper` is a registered
alias of `smu` (`hw/common/dv/configs/duts.toml`), so the two names resolve to
one config, one build cache and one identity; logs carry `DUT_TAG=WRAPPER`.
The bare block bench, `--dut smu_block`, builds `smu #(.SEP(0))` with its
technology interfaces tied off under `tb/tb_top.sv` (`smu_uvm_top`,
`DUT_TAG=BARE`) and holds the leaves that need `SEP=0`
(`testlists/block.toml`): the five SEP=0 composition proofs (`nosep`: no
crossbar, direct ID converters, SEP aperture and lifecycle tie-offs, DTP
without its SEP debug slice), the JTAG2AXI abort test, which needs an OTP
interface that hangs, and the JTAG smoke, which carries the SV-UVM binding.

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
`hw/sys/smu/doc/dv/SMU_DEFERRED_DISPOSITION.adoc`.

**Simulators.** Verilator runs every enrolled group and is the only
simulator with a build and a coverage section in either sim config; it is
what CI runs. VCS runs the SystemVerilog UVM view of `--dut smu_block`
(`--framework uvm`; Verilator has no SV-UVM support). `smu_sim_cfg.toml`
lists `vcs` and `xcelium` as selectable tools, but no enrolled cocotb group
runs on them: the cocotb targets on VCS fail the runner on live RTL
assertions while every test passes (issue #1755, open), and `smu_sim_cfg.toml`
declares no Xcelium target of its own -- only the shared
`hw/common/dv/configs/profiles/native.toml` defaults, which no SMU group
selects.

## Tools

Versions are the repository's pins; the second column says where each comes
from, and a value with no pin says so.

| Tool | Version | Pinned in |
|---|---|---|
| Verilator | `v5.050`, built from source | `.github/actions/dv-run/action.yml`, `verilator-version` default |
| Python | 3.11 in CI; `>=3.11,<3.14` accepted | `.github/actions/dv-run/action.yml`, `python-version` default; `pyproject.toml`, `requires-python` |
| cocotb / pyuvm / cocotbext-axi | 2.0.1 / 4.0.1 / 0.1.28 | `uv.lock` (`dv` group); `run_dv.py` bootstraps this environment itself |
| Bender | whatever `pulp-platform/pulp-actions/bender-install@v2.5.1` installs; no Bender version is pinned in this repository | `.github/actions/dv-run/action.yml` |
| g++ | the `g++` package of `ubuntu-latest` at run time; no version pinned. cocotb 2.x compiles with `-fcoroutines`, so a C++20 compiler is required | `.github/actions/dv-run/action.yml` |
| RISC-V GCC (firmware leaves only) | `gcc-riscv64-unknown-elf` + `picolibc-riscv64-unknown-elf` from Debian trixie in the `ocah-toolchain` image; the base image is pinned by digest, the package version floats | `tools/docker/Dockerfile`; `tools/docker/README.md` |
| VCS (`--framework uvm` only) | not pinned in this repository | `hw/common/dv/configs/simulators.toml` names the tool |

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
#    release qualification set: 64 toolchain-free leaves, one seed nightly,
#    three weekly with --cov on the large runner. Their `elaboration` firmware
#    stage only writes zero-filled preload images (Python, no toolchain).
python3 tools/dv/run_dv.py --dut smu --items hosted

# 3. The whole package: `all` adds the SEP firmware set (96 leaves). The
#    firmware c_build stages build every image in the toolchain container
#    (unless RISCV_TOOLCHAIN names a picolibc gcc), so build that image once
#    first. Nothing schedules this group: the hosted runners have Verilator
#    and no container toolchain, so the run of record for `all` is a
#    developer or self-hosted run.
./scripts/docker-run.sh build
python3 tools/dv/run_dv.py --dut smu --items all
```

`fw_smoke` (the elaboration leaf plus `smu_smc_smoke_test` and
`smu_sep_smoke_test`) is the firmware smoke; it needs the SMC and SEP firmware
compiles, so it is not the CI tier. The block bench is
`python3 tools/dv/run_dv.py --dut smu_block --items all` (seven leaves, no
toolchain; `nosep` is the five SEP=0 composition proofs); `sim.yml` runs its
`smoke` group (two leaves) on every hardware PR, and `regress.yml` is the
schedule of record for the rest. Every group of both testlists, with its size
and what it is for, is the *Regression Groups* section of
`docs/SMU_VPLAN.adoc`.

Results land under `build/runs/<timestamp>__<tool>__<label>/` with a per-test
`result.json` and `results.xml`. `--seed` applies to a single item; a
multi-item regression draws its own seeds and reports them per test.

## Layout

Every directory and top-level file under `dv/` is listed here.

| Path | Role |
|---|---|
| `README.md` | this file: build, run, layout |
| `assets/` | the five SEP eFuse shadow preload images: `default_sep_efuse_shadow_reg.preload` and `sep_efuse_shadow_lc_{test_dev,prod,prod_end,rma_chiplet}.preload`, which set the diff-encoded lifecycle state word. Each has a REUSE `.license` sidecar because the hex format has no comment syntax |
| `cocotb/{env,seq_lib,tests}/` | the `--dut smu_block` framework tree: `tests/` holds its test bodies and base test; `env/` the PyUVM env both DUTs share (`SmuEnv`, `SmuScoreboard`, the evidence map, `smu_fcov.py`, the block bench's `SmuEnvCfg`); `seq_lib/` the sequences and helpers both DUTs share |
| `cocotb_wrapper/{env,seq_lib,tests}/` | the `--dut smu` framework tree: `tests/` holds its test bodies and base test; `env/` the wrapper-only env pieces (`smu_boot_scoreboard.py`, `smu_sep_cpu_trace_monitor.py`, `smu_env_cfg.py`); `seq_lib/` the wrapper-only sequences. `env` and `seq_lib` are namespace packages spanning this tree and `cocotb/`, so a wrapper import resolves in either |
| `cov/` | coverage collateral: `config/verilator/smu_cov_scope.vlt` and `smu_block_coverage_policy.toml`, and `sv/` with the two cover-property modules; intent in `docs/SMU_FCOV.adoc` |
| `docs/` | `index.adoc` and the three chapters: `SMU_TB_ARCH.adoc`, `SMU_VPLAN.adoc`, `SMU_FCOV.adoc` |
| `fw/` | this root's own firmware: `build_firmware.py`, `common/` (SMC and SEP start-up and linker files), `tests/` (the SMC smoke, the SEP smoke and the two SEP arm images). The `sep_real_fw` images come from `hw/sys/sep/dv/fw/` instead |
| `tb/` | `tb_wrapper_top.sv` (`--dut smu`), `tb_top.sv` (`--dut smu_block`; one module with a cocotb pin shape and an SV-UVM harness shape), `smu_tb_signal_list.svh`, `smu_tb_if.sv`, `smu_wrapper_public_scope.vlt` |
| `testlists/` | `all.toml` (`--dut smu`: the SMU regression) and `block.toml` (`--dut smu_block`); each sim config selects its own root and neither includes the other |
| `tools/` | `smu_wrapper_tb_readiness_test.py`, the static readiness gates below |
| `uvm/{env,seq_lib,tests}/` | the SV-UVM realization (`--dut smu_block --framework uvm`, VCS) |
| `smu_sim_cfg.toml` | `--dut smu` launch config: Bender targets, the single compile profile, run modes, `c_build` stages |
| `smu_block_sim_cfg.toml` | `--dut smu_block` launch config: `[frameworks.cocotb]` + `[frameworks.uvm]` |
| `smu_public_scope.vlt` | Verilator public-signal scope of the block bench (`smu_block_sim_cfg.toml` `[build.verilator].public_scope`); the wrapper's is `tb/smu_wrapper_public_scope.vlt` |
| `build/` | generated: models, firmware, `build/runs/`; gitignored |

`assets/`, `cocotb_wrapper/`, `fw/`, `tools/` and `uvm/` are additional to
the shared DV directory set (`cocotb/`, `cov/`, `docs/`, `tb/`, `testlists/`);
each is held here because:

* `assets/` -- a preload image is an input to a scenario, so it belongs beside
  the testlist that names it; the lifecycle leaves select their image by name.
* `cocotb_wrapper/` -- two DUTs share this root, and each has its own
  framework tree with `env/`, `seq_lib/` and `tests/`. The wrapper's test
  bodies cannot live in `cocotb/tests/`, which the runner resolves for
  `--dut smu_block`, without the two benches' base tests colliding; the env and
  sequences both DUTs share live once, under `cocotb/`, and the wrapper flow
  puts that tree on its path.
* `fw/` -- the SMC smoke and the SEP smoke/arm images are stimulus whose source
  must be versioned with the tests that boot it; `build_firmware.py` builds
  them into `build/firmware/`.
* `tools/` -- the readiness gates check the wrapper TB against its source and
  its filelist without a simulation, and are not tests.
* `uvm/` -- the SV-UVM shape of the same scenarios, selected by
  `--framework uvm`; it shares `tb/tb_top.sv` with the cocotb shape.

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

## SystemVerilog UVM framework (`--framework uvm`)

The SV-UVM view shares this DV root, sim config and testlist with the cocotb
flow: `smu_block_sim_cfg.toml` declares it as the `[frameworks.uvm]` overlay
(same Bender RTL recipe), and `--dut smu_block --framework uvm` selects it on
VCS. A testlist scenario carries both implementations in its `module` binding
map (`module = { cocotb = "...", uvm = "..." }`), so the same `--items` name
selects the same VPLAN scenario in either framework; the UVM class name is the
`uvm` entry (`+UVM_TESTNAME`). A scenario declared `uvm = false` in its map is
skipped from group selections under the UVM view; selecting one with no `uvm`
entry errors, and `--skip-unimplemented` skips those from a group selection as
well.
The bound scenario is `smu_dtp_jtag_smoke_test`; its architecture is in
`docs/SMU_TB_ARCH.adoc` ("SystemVerilog UVM Realization") and the framework
conventions in `hw/common/dv/docs/uvm-framework.adoc`.


```bash
# SV-UVM build only (VCS); the default selection is the smoke group
python3 tools/dv/run_dv.py --dut smu_block --framework uvm --build-only

# PyUVM (cocotb) and SV-UVM, same logical scenario name
python3 tools/dv/run_dv.py --dut smu_block --items smu_dtp_jtag_smoke_test --tool verilator
python3 tools/dv/run_dv.py --dut smu_block --framework uvm --items smu_dtp_jtag_smoke_test --seed 1

# Smoke group; `all` needs the flag while any of its scenarios lacks a uvm entry
python3 tools/dv/run_dv.py --dut smu_block --framework uvm --items smoke
python3 tools/dv/run_dv.py --dut smu_block --framework uvm --items all --skip-unimplemented

# Negative validation: a wrong expected IDCODE in both the reference model and
# the scenario evidence must FAIL the run
python3 tools/dv/run_dv.py --dut smu_block --framework uvm --items smu_dtp_jtag_smoke_test \
  --plusarg +SMU_PTAP_IDCODE_NEGATIVE

# Loop-count knobs, resolved specific-first (per test, per group, suite-wide);
# every looped test runs at least 16 seeded passes by default
python3 tools/dv/run_dv.py --dut smu_block --framework uvm --items smu_dtp_jtag_smoke_test \
  --plusarg +SMU_DTP_JTAG_SMOKE_TEST_LOOPS=4
python3 tools/dv/run_dv.py --dut smu_block --framework uvm --items smoke \
  --plusarg +SMU_TEST_LOOPS=1
```

To port another cocotb scenario: add `uvm/seq_lib/<name>_seq.svh` on
`smu_base_test_seq` (JTAG operations through `load_ir` / `dr_scan` /
`step`, named evidence through `attach_evidence` / `check_evidence` /
`finalize_evidence`), add `uvm/tests/<name>.svh` on `smu_base_test`
(override `create_scenario_seq()`, the loop-knob hooks, and
`configure_test_cfg()` for the scoreboard features it requires), add both
`include`s to the package and the manifest, and change the scenario's
testlist entry to the binding map. A pin the scenario needs that the harness
ties off is promoted into `tb/smu_tb_if.sv` first; a new embedded-IP
feature reuses that IP bench's reference model and scoreboard through
`smu_env` and `smu_scoreboard`.

## Enrollment

`--dut smu` carries the regression: `all` is every entry of
`testlists/all.toml` (96), `hosted` is the toolchain-free subset the workflows
run (64), and the rest of `all` is the SEP firmware set. The SEP=0 composition
proofs are enrolled on `--dut smu_block` (`nosep`, in `testlists/block.toml`),
beside `smu_dtp_jtag2axi_abort_mid_op_test`, which runs there because it needs
an OTP interface that holds SINGLE_OP in BUSY, and `smu_dtp_jtag_smoke_test`,
which runs there for its SV-UVM binding while its cocotb side is enrolled here
in `dtp_under_smu`.

Every test entry of both testlists is in its `all`. Bodies that cannot run or
cannot pass on either bench are enrolled nowhere and are catalogued, with the
condition each needs, in `hw/sys/smu/doc/dv/SMU_DEFERRED_DISPOSITION.adoc`:
under `cocotb_wrapper/tests/`, the SEP-driven SMC bring-up images
(`smu_sep_smc_xbar_test`, `smu_sep_ext_axi_test`, `smu_sep_debug_bus_test`,
`smu_sep_wdt_reset_to_smc_test`, `smu_sep_lc_handoff_test`,
`smu_cla_sep_cpu_debug_test`: they poll SMC SRAM that no sys-inbound master can
reach) and `smu_cold_reset_async_assert_test` (the asynchronous cold-reset
assertion `port_table.adoc` states and the SMC reset controller does not
implement); under `cocotb/tests/`, `smu_ext_axi_global_addr_smoke_test` (the
OSS `s_axi` is a LOCAL aperture, so `GLOBAL_BASE + offset` DECERRs). Their
docstrings carry the same reasons.
