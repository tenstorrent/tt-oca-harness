<!-- SPDX-License-Identifier: Apache-2.0 -->
# SMC OSS DV

Open-source DV environment for the SMC (System Management Controller) subsystem,
built on cocotb/PyUVM and driven by `tools/dv/run_dv.py --dut smc`, with a
SystemVerilog UVM realization of the same testbench top selected by
`--framework uvm` (VCS).

**DUT** = `smc_wrapper` (`hw/top/smc_wrapper.sv`) — the `smc` core plus
`smc_ip_integration` (pll/pvt/eFuse/pad macros, I3C DAT-DCT-RLT) and
`smc_cpu_mem_integration` (the CPU ROM and scratch memories).
**What the bench verifies** = the SMC CSR surface and fabric decode reached over
the SEP_IN AXI port, the SYS_OUT boundary, reset / clock / interrupt behaviour
observed on the wrapper pins, the I2C / I3C / UART / GPIO / JTAG peripherals
through pin-level VIPs, and firmware-boot scenarios that run OSS-owned images
on the SMC CPU. `docs/SMC_VPLAN.adoc` carries the per-test contracts.
**Stimulus** = an `ocah_axi_vip` master on SEP_IN, a slave agent answering
SYS_OUT, pin-level protocol VIPs, and the firmware images under `fw/`.
**Backend** = Verilator is the acceptance backend (CI and nightly); VCS runs
the SV-UVM shape and `--cov` coverage. Xcelium builds the model but has no
coverage configuration in this tree.

See `docs/index.adoc` for the chapter set: `docs/SMC_TB_ARCH.adoc` for the
testbench architecture and test development, `docs/SMC_VPLAN.adoc` for what
each test proves together with the signoff package, the release qualification
rules, the component signoff records and every disposition (retired modules,
catalog-only names, bench stand-ins and tie-offs, held-out leaves, firmware
images), and `docs/SMC_FCOV.adoc` for coverage intent and the coverage policy.

**Green / signoff policy:** only claim **real DUT RTL paths**. A test that
reaches a placeholder, a TB-glue stand-in, or a decode-only window is not
reportable as feature PASS; `docs/SMC_VPLAN.adoc` states what each enrolled
test proves and, under Known Limitations, why every catalogued name without a
module is out.

**`allow_timeout` review gate:** default `False`. New `allow_timeout=True`
call sites need a one-line rationale comment at the call (what hangs without
it, and why that is still a real DUT path). The helpers that set it live in
`smc_*_utils.py` and the cluster helpers.

## Prerequisites

| Need | Why | Notes |
|---|---|---|
| Verilator 5.050 | the functional acceptance backend | 5.050 specifically: 5.046 miscompiles the C++ init of nested unpacked structs this TB elaborates |
| g++ 13.2.1 | C++20 for cocotb `-fcoroutines` | an older g++ fails with `unrecognized command line option '-fcoroutines'` |
| Python ≥ 3.11 | launcher | `tools/dv/run_dv.py` bootstraps the locked uv-managed DV env itself (root `uv.lock`, `dv` group → cocotb + pyuvm + cocotbext-axi); there is nothing to source. Set `OCAH_DV_SKIP_UV=1` only inside a pre-provisioned environment that already supplies the `dv` group |
| Bender | filelist (`--stage flist`) | must be on `PATH` |
| RISC-V GCC with picolibc, or a container engine | firmware images for `all` (`fw/`) | `docker` or `podman` for `scripts/docker-run.sh`, which builds the images in the `ocah-toolchain` container; not needed for `smoke` or `hosted` |
| VCS | `--framework uvm`, and `--cov` coverage | Verilator has no SV-UVM support; see `frameworks` in `hw/common/dv/configs/simulators.toml` |

`python3 tools/dv/run_dv.py --doctor --dut smc --tool verilator` reports which
of these tools the machine can see and whether the DV configs are consistent,
before anything is built.

Environment variables the DV code itself reads (all optional — every one has a
default, and the runner sets the first three):

| Variable | Effect |
|---|---|
| `RANDOM_SEED` | seeds every randomized scenario and the eFuse image regeneration; a run is reproducible from it |
| `OCH_ROOT` | repo root override for asset and register-map lookup |
| `OCAH_SIM_BUILD_DIR` | exported sim build directory, used to locate the elaborated model |
| `SMC_DV_RUN_LOGDIR` | where a sequence writes its coverage artefact |
| `COCOTB_RESULTS_FILE` | cocotb `results.xml` path; PASS/FAIL classification reads it |
| `RISCV_TOOLCHAIN` | directory of a picolibc-enabled RISC-V GCC; when unset the `c_compile` stage builds the `fw` and `dual` images through `scripts/docker-run.sh` |
| `OCAH_TOOLCHAIN_ROOTFS` | a toolchain rootfs extracted from the `ocah-toolchain` image; when set and `bwrap` is present, `scripts/docker-run.sh` runs the firmware builds in a bubblewrap sandbox instead of a container (`scripts/docker.md`) |

The SV-UVM loop knobs (`SMC_TEST_LOOPS`, `SMC_<TEST>_LOOPS`) are **plusargs**,
not environment variables — see the `--framework uvm` section.

## Quick start

```bash
PY=tools/dv/run_dv.py

# What tests exist (testlists/ is the authoritative index).
python3 $PY --dut smc --items all --list
```

Every command below builds what it needs: with no `--stage` the runner
resolves the filelist, elaborates the Verilator model, builds any firmware the
selected leaves need, then simulates. On a fresh checkout, do not pass
`--stage sim` alone — it reuses whatever model is on disk and there is none.

Group and test names go to `--items`. `--tag` matches the `tags` field of a
testlist entry, which is a different and mostly narrower set, so a group name
passed to `--tag` can select nothing.

After the one-time model build, Python-only edits to sequences, scoreboards
or testlists reuse the model with `--stage sim`; the C++ compile is the
expensive step. Pass `--rebuild` after changing `tb/`, `verilator_stubs/`,
RTL, or the Bender filelist inputs; `MAKEFLAGS=-jN` shortens it. Two builds
share the Bender filelist step and race when run concurrently, so run them
serially.

### CI `smoke` group

The pull-request and push gate (`.github/workflows/sim.yml`, tier `smoke`)
runs the `smoke` group on Verilator through `.github/actions/dv-run`. No
firmware toolchain is needed:

```bash
python3 tools/dv/run_dv.py --dut smc --items smoke --tool verilator
```

### Nightly `all` group

The nightly command for the `all` group (every test the VPLAN grades:
`hosted` + `fw` + `dual`; `testlists/all.toml` defines the set), one
fresh seed per leaf:

```bash
# No --stage: builds the filelist, the firmware images and the model, then
# regresses. Check `nproc` before raising --sim-jobs.
python3 tools/dv/run_dv.py --dut smc --items all --tool verilator --regress --sim-jobs 6
```

`all` includes the fifteen `fw` leaves, the three dual-target leaves and the two
MMIO isolate-flush leaves, so a picolibc-enabled RISC-V GCC (or
`scripts/docker-run.sh`) must be available: the
`c_compile` stage builds the images with it (see
[Prerequisites](#prerequisites)), in the toolchain container when
`RISCV_TOOLCHAIN` is unset. To build the images ahead of the run:

```bash
./scripts/docker-run.sh run-here make -f ocah.mk ocah-dv-fw-tests TARGET=smc
```

On a host where `scripts/docker-run.sh` cannot build or start the container
(no container engine, or a nix-less host that cannot build the image), extract
the toolchain rootfs once and point `OCAH_TOOLCHAIN_ROOTFS` at it; the script
then runs the same builds under `bwrap`. The extraction commands and the
sandbox's limits are in `scripts/docker.md` ("bubblewrap"). A host RISC-V GCC
with picolibc works too: set `RISCV_TOOLCHAIN` to its directory and no
container or rootfs is needed.

Hosted GitHub nightly and weekly (`.github/workflows/regress.yml`) run
`--items hosted` with one seed per leaf (`reseed: 1`) instead, because those
runners have no RISC-V toolchain. `hosted` is `all` without twenty leaves: the
fifteen `fw` leaves, the three dual-target leaves, and
`smc_cpu_mmio_read_wedge_test` and `smc_cpu_mmio_write_wedge_test`.
`testlists/holdout.toml` defines every leaf outside `all` and `docs/SMC_VPLAN.adoc` (Known Limitations)
records each with the reason, its owner and its closing condition.

```bash
python3 tools/dv/run_dv.py --dut smc --items hosted --tool verilator --regress --reseed 1
```

`--reseed N` runs N random seeds per leaf when more stimulus variety is wanted.

### One named test

Include `--stage flist --stage hdl_compile`: `--stage sim` alone reuses whatever
model is on disk, and a stale one can report a pass that the current RTL would
not give.

```bash
python3 tools/dv/run_dv.py --dut smc --items smc_cold_reset_test \
  --stage flist --stage hdl_compile --stage sim
```

Reproduce a single failing leaf from a regression with `--stage sim --seed N`
against the model that regression built.

## Results and evidence

Per-run logs land in `build/runs/<run-id>/` (gitignored). PASS/FAIL is read
from cocotb's `results.xml`. A test passing is the entry condition for reading
its checkers, never a substitute for them: every graded contract in
`docs/SMC_VPLAN.adoc` names the `CHK-*` line the run must carry.

### The evidence gate

A test that exits cleanly without checking anything is not a pass, and
`smc_base_test` is the mechanism that makes such a run fail. Every graded
check logs a `CHK-<ID>: ...` line; the base class reads the IDs off the log
records as they are emitted (sequences log through `cocotb.log`, components
through their pyuvm logger, and the record factory sees both) and prints one
line per test:

```
EVIDENCE_SUMMARY test=<name> observed=N own=N required=N missing=N ids=...
```

`own` excludes the lines `smc_base_test` emits during bring-up (the model
identity line and the `CHK-PROBE-*` positive controls), so a leaf cannot
satisfy the gate on infrastructure alone. A leaf whose `own` count is zero
**fails** — unless it is named in `_EvidenceRecorder.NO_OWN_EVIDENCE`, which
lists the leaves that grade through another channel (sequence-level asserts,
the scoreboard's `expected=` compares, a protocol-VIP record with a stimulus
floor) together with the reason for each. That list may only shrink; retire
an entry by making the check that already runs log a `CHK-` line where it
happens.

Leaves may also declare more: `min_evidence = N` sets a floor on `own`, and
`required_evidence = ("CHK-A", ...)` names IDs that must appear.

The gate proves a check ran. It does not prove the check was right. The
scoreboard's `check_phase` is the second gate: it fails a run whose sequence
produced no compared item at all.

The gate grades every leaf in `all`, on either harness. `smc_base_test` grades
the leaves built on that class. The three `target = "dual"` leaves in `all`
(`smc_dual_axi_sram_probe_test`, `smc_dual_elaboration_test`,
`smc_occp_sanity_test`) are plain cocotb tests on the `SMC_DUAL` harness, and
they reach the same gate through the `dual_test` decorator: it builds
`SmcDualHarness` from the leaf's module-level `REQUIRED_EVIDENCE` and runs
`finalize_evidence()` once the leaf has returned, which prints the
`EVIDENCE_SUMMARY` line above and fails a run whose `own` count is zero or
whose required IDs never appeared.
`tools/dv/tests/test_smc_required_evidence.py` holds each of the three to its
SMC_VPLAN card and to registration through the decorator, so a dual leaf can
neither build the harness nor call the gate itself.

The dual path has fewer escapes than the `smc_base_test` one: no
`min_evidence` floor and no `NO_OWN_EVIDENCE` exemption, so a dual leaf that
emits no `CHK-*` line of its own always fails. The one `target = "dual"` leaf
outside `all` is `smc_occp_dual_unsecure_boot_test`, held out on runtime and
run as `occp_dual`; it still builds the harness directly, so it prints no
`EVIDENCE_SUMMARY`.

## Code coverage

`--cov` collects native coverage. VCS grades the SV covergroups under
`cov/sv/` (`cov/config/vcs/`); on Verilator, `cov/config/verilator/coverage_policy.toml`
grades the `cov/sv` cover properties in the `user` family together with line,
branch and expression. Neither
scheduled tier collects coverage (`.github/workflows/regress.yml`): the coverage
regression runs on the licensed flow outside hosted CI. Coverage intent, the
VPLAN-to-FCOV traceability and the closure policy (public versus commercial
evidence, structural OUT versus waiver holes, waiver fields) are in
`docs/SMC_FCOV.adoc`.

```bash
# Coverage merge accepts one elaboration. `hosted` and `fw` build the default
# model. `--target` over `all` would run the three `dual` leaves on that model.
python3 tools/dv/run_dv.py --dut smc --items hosted fw --tool vcs --regress --cov

# SMC_DUAL is a separate pass and collects no coverage.
python3 tools/dv/run_dv.py --dut smc --items dual --tool vcs --regress --target dual
```

## Run modes, targets, and groups

The run mode selects the images the bench loads at time zero; the RTL target
selects which elaboration is built; groups in `testlists/all.toml` pick the
leaf set. Use `--dut smc --items all --list` for the catalog.

| Group | Role |
|---|---|
| `smoke` | CI gate (`sim.yml`): `smc_canonical_smoke_test`, `smc_cold_reset_test`, `smc_register_sanity_test` |
| `all` | every test the VPLAN grades: `hosted` ∪ `fw` ∪ `dual`; `expected_count` is the membership gate. The coverage set is `hosted fw`: `dual` elaborates a second build target the coverage merge cannot combine with `default` |
| `hosted` | toolchain-free class, single-instance model; the nightly and weekly tiers (one seed) |
| `fw` | firmware class: the fifteen CPU-boot leaves whose image `c_compile` builds |
| `dual` | SMC_DUAL class: the three `target = "dual"` leaves, each loading a ROM or firmware image |
| `axil`, `clock`, `combined`, `gpio`, `i2c`, `irq`, `reset`, `uart` | feature subsets of `all` for a local run of one area |
| `occp_boot`, `occp_dual`, `held_out` | on-demand hold-outs (runtime, or waiting on an RTL fix); not in `all` |

Every leaf outside `all` is defined in `testlists/holdout.toml`, which states
why, and has its card under Known Limitations in `docs/SMC_VPLAN.adoc`.

| Run mode / target | Meaning |
|---|---|
| `run_modes.smoke` (default) | single instance; loads `assets/smc_efuse_default.hex` and `assets/smc_rom_default.hex` at time zero |
| `run_modes.prod_rom` | single instance; the default eFuse image plus the production boot ROM built in `c_compile` and loaded through `+rom_bin64` (`occp_boot`) |
| `run_modes.dual` | SMC_DUAL; the eFuse image `efuse_preload/` generates into `build/efuse/` plus the built ROM / firmware images |
| `targets.default` / `targets.dual` | `smc_uvm_top` with one `smc_wrapper`, or two plus the shared I3C bus (`SMC_DUAL`) |

### Single DUT

**Launch entry: `--dut smc`** (discovered by the runner's directory
convention from `smc_sim_cfg.toml`). `tb/tb_top.sv` (`smc_uvm_top`) instantiates
`hw/top/smc_wrapper.sv` (`smc` + `smc_ip_integration` + `smc_cpu_mem_integration`),
so the bare DUT name selects the wrapper-based TB.

| | |
|---|---|
| select | `--dut smc` |
| config | `smc_sim_cfg.toml` |
| TB top | `smc_uvm_top` (`tb/tb_top.sv`) |
| DUT | `smc_wrapper` |
| cocotb | `cocotb/` (`SmcEnv`) |
| testlist | `testlists/all.toml` |
| macros | inside `smc_ip_integration` (pll/pvt/efuse/pads/I3C DAT-DCT-RLT) |
| CPU mem | inside wrapper via `smc_cpu_mem_integration` |
| in TB | SYS_OUT=`ocah_axi_vip` slave agent behind `ocah_axi_struct_bridge`; DTP CSR **idle** on `smc_wrapper` (no TB terminator; DTP CSR is a smc_wrapper-only boundary) |

### Bench stand-ins

Two pieces of DV-owned RTL answer in place of something else on this bench:

| Stand-in | Where | Reaches |
|----------|-------|---------|
| `tb/verilator_stubs/prim_sync3.sv` | `smc_sim_cfg.toml` `[build].stubs`, emitted ahead of the Bender filelist | Verilator and Xcelium compile it; on VCS only, the runner drops a stub whose basename the Bender graph supplies, so VCS elaborates the product `ocah_prim` cell |
| `models/axil_okay_slv.sv` behind `models/pll_wrap.sv` / `pvt_wrap.sv` | Bender `smc_wrapper` target, inside `smc_ip_integration` | every tool |

Which product cell each stand-in replaces, which enrolled leaves read a signal
behind one, what each verdict reads, and the control that keeps each claim
honest are the *Bench stand-ins* record under Known Limitations in
`docs/SMC_VPLAN.adoc`. This README owns layout and run recipes; that record
owns the dispositions and is not restated here.

### Retired and catalog-only names

Every `@pyuvm.test()` module under `cocotb/tests/` is in at least one testlist.
The names the package catalogues without a module -- retired modules whose
blocker is outside the test, and commercial aliases a live enrolled name
already proves -- are dispositioned under Known Limitations in
`docs/SMC_VPLAN.adoc`. A retired module's code is in git history and is
restored when the blocker in its row clears. The firmware images under
`fw/tests/` have their own record there too (enrolled, external-consumer,
deferred and superseded image names); `fw/README.md` states the rule for
adding one.

## SystemVerilog UVM framework (`--framework uvm`)

The SV-UVM view shares this DV root, sim config, and testlist with the cocotb
flow: `smc_sim_cfg.toml` declares it as the `[frameworks.uvm]` overlay (same
Bender RTL recipe), and `--dut smc --framework uvm` selects it. A testlist
scenario carries both implementations in its `module` binding map
(`module = { cocotb = "...", uvm = "..." }`), so the same `--items` name
selects the same VPLAN scenario in either framework; the UVM class name is
the `uvm` entry (`+UVM_TESTNAME`). A group runs its UVM-implemented subset;
naming a scenario with no `uvm` entry errors. VCS only: Verilator has no
SV-UVM support. The bench architecture is in `docs/SMC_TB_ARCH.adoc`
("SystemVerilog UVM Realization"); the framework conventions it follows are
in `hw/common/dv/docs/uvm-framework.adoc`.

The first bound scenario is `smc_register_sanity_test`:
SEP_IN AXI4 idle-read / write / readback / restore of the `SCRATCH_COLD` and
`SCRATCH_COLD_WARM` registers over 16 seeded passes. In the SV-UVM shape every
scratch read is predicted by `smc_scratch_csr_ref_model`, paired by the
always-on `smc_scoreboard`, and recorded as named `CHK-*` evidence
(`CHECKER_SUMMARY name=smc_csr`). The cocotb shape of the same scenario grades
through the scoreboard's `expected=` compares on each read and emits no
`CHK-*` line of its own.

```bash
# SV-UVM build only (VCS)
python3 tools/dv/run_dv.py --dut smc --framework uvm --build-only

# PyUVM (cocotb) and SV-UVM, same logical scenario name
python3 tools/dv/run_dv.py --dut smc --items smc_register_sanity_test --tool verilator
python3 tools/dv/run_dv.py --dut smc --framework uvm --items smc_register_sanity_test --seed 1

# Smoke group, UVM-implemented subset
python3 tools/dv/run_dv.py --dut smc --framework uvm --items smoke

# Scoreboard negative validation: a corrupted scratch readback prediction
# must FAIL the run
python3 tools/dv/run_dv.py --dut smc --framework uvm --items smc_register_sanity_test \
  --plusarg +SMC_CSR_SCOREBOARD_NEGATIVE

# Loop-count knobs, resolved specific-first (per test, per group, suite-wide);
# every looped test runs at least 16 seeded passes by default
python3 tools/dv/run_dv.py --dut smc --framework uvm --items smc_register_sanity_test \
  --plusarg +SMC_REGISTER_SANITY_TEST_LOOPS=4
python3 tools/dv/run_dv.py --dut smc --framework uvm --items smoke \
  --plusarg +SMC_TEST_LOOPS=1
```

To port another cocotb scenario: add `uvm/seq_lib/<name>_seq.svh` on
`smc_base_test_seq` (CSR accesses through `csr_write` / `csr_read`, named
evidence through `attach_evidence` / `check_evidence` / `finalize_evidence`),
add `uvm/tests/<name>.svh` on `smc_base_test` (override
`create_scenario_seq()`, the loop-knob hooks, and `configure_test_cfg()` for
the scoreboard features it requires), add both `include`s to the package and
the manifest, and change the scenario's testlist entry to the binding map. A
pin the scenario needs that the harness ties off is promoted into
`tb/smc_tb_if.sv` first.

## Layout

Every directory and top-level file under `dv/` is listed here. This tree is
the authoritative layout.

```
hw/sys/smc/dv/```
hw/sys/smc/dv/
├── cocotb/                 # flow-first: PyUVM env + stimulus + tests
│   ├── env/                #   agents, scoreboard, monitors, env cfg
│   ├── seq_lib/            #   sequences (the VPLAN scenarios) + shared VIP helpers
│   └── tests/              #   @pyuvm.test() entries, one per VPLAN testcase
├── uvm/                    # SV-UVM realization (--framework uvm, VCS)
│   ├── env/                #   smc_env_pkg: types, cfgs, ref model, scoreboard, env
│   ├── seq_lib/            #   smc_seq_lib_pkg: operations + scenario sequences
│   └── tests/              #   thin test classes + smc_tests.sv include manifest
├── cov/                    # coverage collateral: cov/config/{vcs,verilator}/
│                           #   and cov/sv/. --cov is graded on VCS; see
│                           #   docs/SMC_FCOV.adoc
├── docs/                   # index.adoc plus the three role chapters it
│                           #   includes: SMC_TB_ARCH.adoc (testbench
│                           #   architecture, test development),
│                           #   SMC_VPLAN.adoc (test intent, signoff package,
│                           #   release qualification, component signoff,
│                           #   known limitations and dispositions) and
│                           #   SMC_FCOV.adoc (coverage intent and policy)
├── models/                 # SMC-local sim models: axil_okay_slv.sv,
│                           #   smc_cpu_mem_dv.sv (observability counters + the
│                           #   time-0 ROM/scratch image backdoors),
│                           #   smc_scratch_map_pkg.sv (the scratch-bank decode
│                           #   the backdoors share), the pll/pvt adopter
│                           #   placeholder wraps, and models/regs/ their
│                           #   PeakRDL sources + generated views.
│                           #   Each stand-in is declared in models/README.md
├── fw/                     # OSS-owned SMC firmware built into the CPU-boot
│                           #   tests: common/ drivers/ include/ link/ startup/
│                           #   scripts/ tests/ plus fw.mk, toolchain.mk,
│                           #   postprocess.mk. Needs the RISC-V toolchain; not
│                           #   required by the `smoke` or `hosted` groups. The Boot ROM is NOT
│                           #   here — it lives outside DV at ../bootrom/prod/
├── efuse_preload/          # generator for the eFuse OTP image the `dual` run
│                           #   mode senses: efuse_schema.toml declares the
│                           #   fields, configurations/*.toml an image, and
│                           #   generate_efuse_preload.py / randomize_efuse.py
│                           #   emit build/efuse/smc_efuse_generated.hex at
│                           #   c_compile. Build-time tooling, not part of any
│                           #   test's proof path
├── assets/                 # the committed images: the hand-maintained eFuse
│                           #   image and shadow-register preload the
│                           #   single-instance run modes load
│                           #   (smc_efuse_default.hex,
│                           #   default_efuse_shadow_reg.preload) and the
│                           #   ROM/ECC ones (smc_rom_default.hex,
│                           #   min_pass.rom.hex, min_pass.ecc.hex)
├── tb/                     # DUT-only top + helper RTL: tb_top.sv (module
│                           #   smc_uvm_top, one module with a cocotb pin shape
│                           #   and an SV-UVM harness shape),
│                           #   smc_tb_signal_list.svh (every TB signal declared
│                           #   once, shared by both shapes), smc_tb_if.sv,
│                           #   smc_public_scope.vlt, verilator_stubs/
├── testlists/              # native TOML testlists: all.toml owns the groups
│                           #   and includes the per-feature leaf files;
│                           #   holdout.toml defines every leaf outside `all`
├── smc_sim_cfg.toml        # sole launch config: build/filelist manifest, run
│                           #   modes, tool knobs, [frameworks.cocotb] +
│                           #   [frameworks.uvm]
├── smc_sim.core            # optional FuseSoC/CAPI-2 view for an external
│                           #   consumer; run_dv.py does not parse it
├── build/                  # generated: per-tool models and build/runs/<run-id>/
│                           #   logs (gitignored, never committed)
├── build_dual/             # generated: the SMC_DUAL model the target = "dual"
│                           #   leaves elaborate (gitignored, never committed)
├── .gitignore              # DV-local ignores for simulator temporaries that
│                           #   land beside the sources (Xcelium tmpdir, waves,
│                           #   coverage databases); the root .gitignore owns
│                           #   build/
└── README.md
```

`assets/`, `efuse_preload/`, `fw/`, `models/`, `uvm/`, `smc_sim.core` and`assets/`, `efuse_preload/`, `fw/`, `models/`, `uvm/`, `smc_sim.core` and
`.gitignore` are additional to the shared DV directory set (`cocotb/`, `docs/`,
`tb/`, `testlists/` plus the launch config); each is held here because:

* `assets/` — a preload image is an input to a scenario, so it belongs beside
  the testlist that names it rather than in a shared pool where a rebuild for
  one subsystem would move another's expectations.
* `fw/` — the CPU-boot scenarios need firmware whose source is versioned with
  the tests that run it; it is built by the toolchain container and consumed as
  a ROM image, never compiled by the DV runner.
* `models/` — bus terminators and register stand-ins, each declared in
  `models/README.md` with what it replaces and why the shared component does
  not fit.
* `uvm/` — the SV-UVM shape of the same scenarios, selected by
  `--framework uvm`; it shares `tb/tb_top.sv` with the cocotb shape.
* `efuse_preload/` — the schema and generator that produce the eFuse image the
  `dual` run mode senses (`build/efuse/smc_efuse_generated.hex`). It does not
  produce `assets/smc_efuse_default.hex`, which is hand-maintained; the two
  targets sense different images, and `smc_sim_cfg.toml` (`[run_modes.dual]`)
  says why. Keeping the generator beside the schema is what lets a reviewer
  read which field a configuration sets.
* `smc_sim.core` — a FuseSoC/CAPI-2 view of the same Bender targets for an
  external consumer; `run_dv.py` does not read it, and it is kept here so the
  two descriptions of the build sit in one directory.
* `.gitignore` — the simulator temporaries some tools write next to the
  sources rather than under `build/`.

`tb/tb_top.sv` is ONE module with two shapes: the cocotb pin port list by
default, and under the bare `+define+UVM` (set by the native profile's
`[frameworks.uvm]` overlay) a self-contained SV-UVM harness that `include`s
`uvm/tests/smc_tests.sv`. Every TB signal is declared once in
`tb/smc_tb_signal_list.svh`. The SV-UVM realization is described in
`docs/SMC_TB_ARCH.adoc` ("SystemVerilog UVM Realization"); the framework
conventions it follows are in `hw/common/dv/docs/uvm-framework.adoc`.

`cocotb/env/smc_cpu_trace_monitor.py` is the passive hart-0 processor-state
monitor (symbolized call stack, trap records, hang watch) that both the
single-instance and the dual bench run; a failing test ends with its dump in
the log. `cocotb/env/smc_virt_console.py` decodes the firmware virtual console
on scratch register 2 for both benches.

## OSS hygiene

Verify the filelist is vendor-clean:

```bash
python3 tools/dv/check_no_vendor_paths.py --filelist <smc.flist>
```

Bender targets, the DV-owned stand-ins and what stays off the filelist are in
`docs/SMC_TB_ARCH.adoc`; the stand-ins' dispositions are under Known
Limitations in `docs/SMC_VPLAN.adoc`.

## Troubleshooting

**`Cannot open -f command file ... files.f`** on a fresh checkout -- `--stage sim`
was passed alone. Drop `--stage` (or add `--stage flist --stage hdl_compile`)
so the filelist and model are built first.

**`no picolibc-enabled RISC-V toolchain`** -- the host `RISCV_TOOLCHAIN` has no
`--specs=picolibc.specs`. Leave `RISCV_TOOLCHAIN` unset and keep
`scripts/docker-run.sh` runnable, or point it at a picolibc-enabled GCC.

**Firmware leaves time out with no console output** after a toolchain image
rebuild -- stale objects were linked against a new C library. Run
`make -f ocah.mk ocah-dv-fw-clean TARGET=smc` and rebuild.

**`[BUILD-MODEL-IDENTITY] the working tree ... has N uncommitted change(s)`** --
the bench refuses to grade a run whose inputs are not the committed tree.
Commit the change (a local commit is enough) and rerun.

**`malformed or corrupted precompiled file ... Vtop__pch.h`** during the model
build -- ccache is serving a precompiled header from a checkout that has moved.
Set `CCACHE_DISABLE=1` for the build, or clear the entry.

**Two builds race** -- the Bender filelist step is shared, so run concurrent
builds serially.

PASS/FAIL is classified by the global parser registry
(`hw/common/dv/configs/parsers.toml`). The cocotb flow requires positive
evidence from `results.xml`; a clean simulator exit alone is not enough.
