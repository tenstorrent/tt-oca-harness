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

See `docs/index.adoc` for the chapter set:
`docs/SMC_TB_ARCH.adoc` for test development, environment setup and run
recipes, `docs/SMC_VPLAN.adoc` for the verification plan,
`docs/SMC_FCOV.adoc` for the coverage pipeline, and
`docs/SMC_SCOPE_TRACEABILITY.adoc` for the requirement-to-test matrix,
`docs/SMC_CANONICAL_BRINGUP_SIGNOFF.adoc` for the canonical bring-up /
CSR signoff, `docs/SMC_FABRIC_PERIPH_SIGNOFF.adoc` for the fabric /
peripheral honesty signoff, `docs/SMC_RELEASE_MATRIX.adoc` for the release
regression matrix, `docs/SMC_COVERAGE_POLICY.adoc` for the coverage-target
and waiver-field policy, and `docs/SMC_RESET_CLOCK_IRQ_SIGNOFF.adoc` for the
reset / clock / IRQ signoff.

**Green / signoff policy:** only claim **real DUT RTL paths**.
I3C CCC/IBI / real-core protocol, adopter PLL/PVT OKAY wraps, and TB-glue
demos (e.g. hardcoded DFD capture token) are not enrolled and are not
reportable as feature PASS. `smc_i3c_to_fabric_test` is
**decode only** (fabric → real OCA core `HCI_VERSION`) and is **not**
in `smoke` or `functional`. Run it via `i3c_depth`
or by name.

**`allow_timeout` review gate:** default `False`. New `allow_timeout=True`
call sites need a one-line rationale comment at the call (what hangs without
it, and why that is still a real DUT path). The helpers that set it live in
`smc_*_utils.py` and the cluster helpers.

## Prerequisites

| Need | Why | Notes |
|---|---|---|
| Verilator 5.050 | the functional acceptance backend | 5.050 specifically: 5.046 miscompiles the C++ init of nested unpacked structs this TB elaborates |
| g++ 13.2.1 | C++20 for cocotb `-fcoroutines` | an older g++ fails with `unrecognized command line option '-fcoroutines'` |
| Python ≥ 3.11 | launcher | `tools/dv/run_dv.py` bootstraps the locked uv-managed DV env itself (root `uv.lock`, `dv` group → cocotb + pyuvm + cocotbext-axi) |
| Bender | filelist (`--stage flist`) | must be on `PATH` |
| RISC-V GCC with picolibc, or a container engine | firmware images for `all` (`fw/`) | `docker` or `podman` for `scripts/docker-run.sh`, which builds the images in the `ocah-toolchain` container; not needed for `smoke` or `hosted` |
| VCS | `--framework uvm`, and `--cov` coverage | Verilator has no SV-UVM support; see `frameworks` in `hw/common/dv/configs/simulators.toml` |

Environment variables the DV code itself reads (all optional — every one has a
default, and the runner sets the first three):

| Variable | Effect |
|---|---|
| `RANDOM_SEED` | seeds every randomized scenario and the eFuse image regeneration; a run is reproducible from it |
| `OCH_ROOT` | repo root override for asset and register-map lookup |
| `OCAH_SIM_BUILD_DIR` | exported sim build directory, used to locate the elaborated model |
| `SMC_DV_RUN_LOGDIR` | where a sequence writes its coverage artefact |
| `COCOTB_RESULTS_FILE` | cocotb `results.xml` path; PASS/FAIL classification reads it |

The SV-UVM loop knobs (`SMC_TEST_LOOPS`, `SMC_<TEST>_LOOPS`) are **plusargs**,
not environment variables — see the `--framework uvm` section.

## Present but not enrolled

These modules exist under `cocotb/tests/` and are in no testlist, so they are
not in `all`. Where a blocker tag applies it lives in the file's docstring
(`# deferred: <reason>`); `testlists/all.toml` carries the same list beside the
`all` group, and `docs/SMC_DEFERRED_DISPOSITION.adoc` is the disposition of
record. SMU's matching catalog is `hw/sys/smu/dv/docs/SMU_DEFERRED_DISPOSITION.adoc`.

| Test | Reason |
|------|--------|
| `smc_i3c_ccc_ibi_full_test` | `needs_i3c_dat_dct` — no TB DAT/DCT RAM |
| `smc_macro_axil_routing_test` | `needs_dtp_csr_sub` / `rtl_placeholder` — DTP CSR idle; pll/pvt OKAY wraps |
| `smc_pll_pvt_clock_config_test` | `rtl_placeholder` |
| `smc_pll_dvfs_depth_test` | `rtl_placeholder` |
| `smc_pll_cgm_awm_config_test` | `rtl_placeholder` |
| `smc_pll_awm_freq_sweep_test` | `rtl_placeholder` |
| `smc_pvt_analog_sensor_test` | `rtl_placeholder` |
| `smc_pvt_droop_test` | `rtl_placeholder` |
| `smc_sideband_avsbus_octs_bfm_test` | `fake_bfm` — no pad BFM |
| `smc_dfd_dbs_fault_inject_test` | `tb_glue` — hardcoded capture token, not `smc_dfd_wrap` |
| `smc_captured_straps_test` | `no_dut_port` — `smc_wrapper` declares no `captured_straps_i`, so there is no tap to drive |
| `smc_clint_csr_test` | the `0xC8xx_xxxx` cluster-local window folds onto `0xC0xx_xxxx` on SEP_IN, so the reads never reach the CLINT |
| `smc_cluster_plic_csr_test` | the `0xC400_0000` PLIC aperture accepts SEP_IN writes with OKAY and stores nothing, and its `+2 MB` context pages return non-OKAY |

One enrolled carve-out keeps its reason next to the stimulus:
`HYST_LEGAL_LO` in `smc_clk_multi_window_test_seq.py` (hysteresis encodings
0..8 are never programmed by that testcase).

## Single DUT

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

## Verilator stubs policy

`tb/verilator_stubs/` may contain **tooling shims only** (`prim_sync2` /
`prim_sync3` for OSS prim port remap + X-init). Product-module overrides
(`smc_reset_*`, `smc_dfx_*`, …) are forbidden.

| Concern | Handling |
|---------|----------|
| PeakRDL nested hwif structs break Verilator C++ codegen | `disable_public_flat_rw` + `smc_public_scope.vlt`; the real RTL compiles |
| `och_prim` `prim_sync2/3` start with X on the first flop stage and the X persists, because the wrapper port exposes no `rst_ni` | DV `prim_sync*` tooling stubs are the same two-stage flop with explicit `initial` values, so the synchronizer resolves without an external reset; product RTL is untouched. The ports are identical (`i_clk` / `i_d` / `o_q`) — port remapping is **not** the reason, and `.i_CK` appears only in the `prim_sync*r` resettable variants, which these stubs do not replace |

## Layout

Every directory and top-level file under `dv/` is listed here. This table is
the authoritative layout; `docs/SMC_TB_ARCH.adoc` sketches a subset and defers
to this one.

```
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
├── docs/                   # index.adoc plus the role chapters: TB_ARCH (test
│                           #   development, environment, run recipes), VPLAN,
│                           #   FCOV, and the scope/disposition/signoff records
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
│                           #   required by the `smoke` tag. The Boot ROM is NOT
│                           #   here — it lives outside DV at ../bootrom/prod/
├── efuse_preload/          # generator for the committed eFuse OTP images:
│                           #   efuse_schema.toml declares the fields,
│                           #   configurations/*.toml an image, and
│                           #   generate_efuse_preload.py / randomize_efuse.py
│                           #   emit the assets/ hex. Build-time tooling, not
│                           #   part of any test's proof path
├── assets/                 # the committed images those generators produce plus
│                           #   the ROM/ECC ones: smc_efuse_default.hex,
│                           #   smc_rom_default.hex, min_pass.rom.hex,
│                           #   min_pass.ecc.hex, default_efuse_shadow_reg.preload
├── tb/                     # DUT-only top + helper RTL: tb_top.sv (module
│                           #   smc_uvm_top, one module with a cocotb pin shape
│                           #   and an SV-UVM harness shape),
│                           #   smc_tb_signal_list.svh (every TB signal declared
│                           #   once, shared by both shapes), smc_tb_if.sv,
│                           #   smc_public_scope.vlt, verilator_stubs/
├── testlists/              # native TOML testlists: all.toml aggregates the
│                           #   per-feature leaves
├── smc_sim_cfg.toml        # sole launch config: build/filelist manifest, run
│                           #   modes, tool knobs, [frameworks.cocotb] +
│                           #   [frameworks.uvm]
├── smc_sim.core            # optional FuseSoC/CAPI-2 view for an external
│                           #   consumer; run_dv.py does not parse it
├── build/                  # generated: per-tool models and build/runs/<run-id>/
│                           #   logs (gitignored, never committed)
├── .gitignore              # DV-local ignores for simulator temporaries that
│                           #   land beside the sources (Xcelium tmpdir, waves,
│                           #   coverage databases); the root .gitignore owns
│                           #   build/
└── README.md
```

`assets/`, `efuse_preload/`, `fw/`, `models/`, `uvm/`, `smc_sim.core` and
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
* `efuse_preload/` — the schema and generator that produce the eFuse images in
  `assets/`; keeping the generator beside its output is what lets a reviewer
  regenerate an image and diff it against the committed one.
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

### CI `smoke` group

The pull-request and push gate (`.github/workflows/sim.yml`, tier `smoke`)
runs the `smoke` group on Verilator through `.github/actions/dv-run`. No
firmware toolchain is needed:

```bash
python3 tools/dv/run_dv.py --dut smc --items smoke --tool verilator
```

That group is `smc_canonical_smoke_test`, `smc_cold_reset_test` and
`smc_register_sanity_test`, all three members of `all`.

### Nightly `hosted` group

The scheduled nightly and weekly (`.github/workflows/regress.yml`) run the
`hosted` group on Verilator with three seeds per leaf. `hosted` is `all` minus
the five leaves that need a RISC-V toolchain or an `SMC_DUAL` elaboration,
which the hosted GitHub runners do not have; `testlists/all.toml` names the
five and guards the set with `expected_count`.

```bash
python3 tools/dv/run_dv.py --dut smc --items hosted --tool verilator --regress --reseed 3
```

One seed per leaf (`--reseed 1`) is the quick local form of the same run.

### Package `all` group

`all` is every test the VPLAN grades. It includes the firmware-boot leaves, so
the firmware images must exist before the run. With no site RISC-V toolchain,
build them once in the toolchain container (`docker` or `podman` on `PATH`):

```bash
./scripts/docker-run.sh run-here make -f ocah.mk ocah-dv-fw-tests TARGET=smc
python3 tools/dv/run_dv.py --dut smc --items all --tool verilator --regress
```

Not every test the package defines is in `all` — `testlists/all.toml` names
the held-out testcases and why.

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

### SystemVerilog UVM framework (`--framework uvm`)

The SV-UVM view shares this DV root, sim config, and testlist with the cocotb
flow: `smc_sim_cfg.toml` declares it as the `[frameworks.uvm]` overlay (same
Bender RTL recipe), and `--dut smc --framework uvm` selects it. A testlist
scenario carries both implementations in its `module` binding map
(`module = { cocotb = "...", uvm = "..." }`), so the same `--items` name
selects the same VPLAN scenario in either framework; the UVM class name is
the `uvm` entry (`+UVM_TESTNAME`). Selecting a scenario with no `uvm` entry
errors; `--skip-unimplemented` runs a group's UVM-implemented subset instead.
VCS only: Verilator has no SV-UVM support. The bench architecture is in
`docs/SMC_TB_ARCH.adoc` ("SystemVerilog UVM Realization"); the framework
conventions it follows are in `hw/common/dv/docs/uvm-framework.adoc`.

The first bound scenario is `smc_register_sanity_test`:
SEP_IN AXI4 idle-read / write / readback / restore of the `SCRATCH_COLD` and
`SCRATCH_COLD_WARM` registers over 16 seeded passes. In the SV-UVM shape every
scratch read is predicted by `smc_scratch_csr_ref_model`, paired by the
always-on `smc_scoreboard`, and recorded as named `CHK-*` evidence
(`CHECKER_SUMMARY name=smc_csr`). The cocotb shape of the same scenario grades
through the scoreboard's `expected=` compares on each read and emits no
`CHK-*` line of its own.

```bash
# SV-UVM build only (VCS). --skip-unimplemented (or an --items selection) is required:
# without it the runner selects the cocotb-only scenarios and stops before compiling.
python3 tools/dv/run_dv.py --dut smc --framework uvm --build-only --skip-unimplemented

# PyUVM (cocotb) and SV-UVM, same logical scenario name
python3 tools/dv/run_dv.py --dut smc --items smc_register_sanity_test --tool verilator
python3 tools/dv/run_dv.py --dut smc --framework uvm --items smc_register_sanity_test --seed 1

# Smoke group, UVM-implemented subset
python3 tools/dv/run_dv.py --dut smc --framework uvm --items smoke --skip-unimplemented

# Scoreboard negative validation: a corrupted scratch readback prediction
# must FAIL the run
python3 tools/dv/run_dv.py --dut smc --framework uvm --items smc_register_sanity_test \
  --plusarg +SMC_CSR_SCOREBOARD_NEGATIVE

# Loop-count knobs, resolved specific-first (per test, per group, suite-wide);
# every looped test runs at least 16 seeded passes by default
python3 tools/dv/run_dv.py --dut smc --framework uvm --items smc_register_sanity_test \
  --plusarg +SMC_REGISTER_SANITY_TEST_LOOPS=4
python3 tools/dv/run_dv.py --dut smc --framework uvm --items smoke --skip-unimplemented \
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

PASS/FAIL is classified by the global parser registry
(`hw/common/dv/configs/parsers.toml`). The cocotb flow requires positive
evidence from `results.xml`; a clean simulator exit alone is not enough.
