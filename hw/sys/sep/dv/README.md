<!-- SPDX-License-Identifier: Apache-2.0 -->
# SEP OSS DV

Open-source DV environment for the SEP (Security Processor) subsystem, built on
cocotb/PyUVM and driven by `tools/dv/run_dv.py --dut sep`, with a SystemVerilog
UVM realization of the same testbench top selected by `--framework uvm` (VCS).

**DUT** = `sep_wrapper` (`hw/top/sep_wrapper.sv`) — the bare `sep` core
(`hw/sys/sep/rtl/sep.sv`) plus its IP integration
(`hw/top/sep_ip_integration.sv`: real memory macros and the generic eFuse model).
The OpenTitan SPI host is inside the `sep` core (`sep_io` / `sep_ot_spi_wrap`);
its pads come out of the wrapper. There is no SPI pad mux in this build.
**Stimulus** = a cocotbext-axi master on the CPU LSU splice (`s_axi_*`), a second
master on the real SMN-inbound port (`m_axi_*`, inbound filter), and VeeR EL2
firmware boot on the `cpu` / `rom_fw` paths.
**Backend** = Verilator is the acceptance backend; VCS and Xcelium are the
commercial development backends (`sep_sim_cfg.toml` `tools`), and VCS is the
one graded coverage and SV-UVM run on.
Everything the environment needs lives under this tree.

## Prerequisites

| Need | Why | Notes |
|---|---|---|
| Verilator 5.x (CI pin `v5.052`) | the acceptance backend | `.github/actions/dv-run/action.yml`. 5.046 fails the `--cov` C++ compile (`__PVT__MLKEM_SHARED_KEY`) |
| g++ ≥ 10 | Verilator `--timing` / `-fcoroutines` | RHEL-8 g++ 8.5 fails with `unrecognized command line option '-fcoroutines'` |
| Python ≥ 3.11 | launcher | `pyproject.toml` `requires-python` |
| uv (CI: `astral-sh/setup-uv@v6`) | every stage, including `--items smoke` | must be on `PATH`. `run_dv.py` re-executes itself inside the locked uv-managed DV env (root `uv.lock`, `dv` group → cocotb + pyuvm + cocotbext-axi). A missing binary exits 2 before any stage runs. No SEP-owned semver pin; the dependency pin is `uv.lock` |
| Bender (CI: `pulp-actions/bender-install@v2.5.1`) | filelist (`--stage flist`) | must be on `PATH`. A missing binary fails filelist generation. No SEP-owned semver pin |
| ccache (CI: Ubuntu apt) | Verilator object cache | `[build.verilator] ccache = true`. Absence fails the C++ compile (`ccache: No such file or directory` / make Error 127) |
| RISC-V GCC + picolibc (`ocah-toolchain`) | `--stage c_compile` (TCM firmware, Boot ROM, KM `rom_main`) | `tools/docker/Dockerfile`: Debian trixie `gcc-riscv64-unknown-elf` + `picolibc-riscv64-unknown-elf` (packages float; the base image digest is pinned). Host without `--specs=picolibc.specs` fails unless `scripts/docker-run.sh` is available. Not needed for `--items smoke` |
| VCS (commercial; no public pin) | develop, graded `--cov`, and SV-UVM | Missing `VCS_HOME` / `SNPSLMD_LICENSE_FILE` or the 32-bit `vcs` driver's python-3.9 lib on `LD_LIBRARY_PATH` fails the driver |

### Environment variables

| Variable / action | When it is needed |
|---|---|
| `PATH` | must contain `uv`, `verilator`, `python3`, `bender`; `ccache` for the Verilator model; a RISC-V GCC for `--items all`, `--items cpu`, `--items rom_fw`, and `--tag boot` |
| `source /opt/rh/gcc-toolset-11/enable` | RHEL-8 hosts whose default g++ is 8.5 (sets `PATH` to g++ ≥ 10) |
| `RISCV_TOOLCHAIN`, `RISCV_PREFIX` | optional override for `--stage c_compile`. Unset, the stage probes a site toolchain then a local xPack install, then `scripts/docker-run.sh` when picolibc is missing |
| `OCAH_DV_SKIP_UV` | set to `1` on a pre-provisioned host that already supplies the `dv` dependency group. It skips only the uv re-execution; `run_dv.py` still exports the root and sets the Python path |
| `OCAH_ROOT` | firmware `make` only (`OCAH_ROOT="$PWD"` from the repository root) |
| `TMPDIR` | large local scratch for sim/build temporaries; do not use `/tmp` |
| `VCS_HOME`, `SNPSLMD_LICENSE_FILE`, `LD_LIBRARY_PATH` | VCS only (license file plus the 32-bit `vcs` driver's python-3.9 lib dir) |

No VeeR EL2 setup step is needed — the config snapshot is committed collateral.
See [Troubleshooting](#troubleshooting) if a build complains about it.

## Quick start

```bash
PY=tools/dv/run_dv.py

# What tests exist (testlists/ is the authoritative index).
python3 $PY --dut sep --items all --list

# Check every golden model against its own vectors. No simulator, no build --
# run it before trusting a golden a checker compares against.
python3 hw/sys/sep/dv/cocotb/env/run_golden_selftests.py
```

### CI `smoke` group

The pull-request and push gate (`.github/workflows/sim.yml`) runs the `smoke`
group on Verilator. No firmware toolchain is needed:

```bash
python3 tools/dv/run_dv.py --dut sep --items smoke
```

That group is `sep_axi_smoke_test` only. `--items all --tag smoke` is a tag
filter over `all` and is not the CI command.

### Full regression, the `all` group

The command for the `all` group (every test this VPLAN grades), one fresh seed
per leaf. It is a local command -- no CI tier runs it, see below:

```bash
# No --stage: builds the filelist, the firmware and the model, then regresses.
#
# Pass both job counts. --sim-jobs defaults to 1 and --build-jobs inherits it:
# the bare command takes about ten hours, against seventy minutes measured at
# --sim-jobs 8. The values below suit a 32-core host -- check `nproc` and stay
# under it (on four cores, --build-jobs 3).
#
# Fan-out is per runtime class: no_cpu wide, firmware and VCS at 8, because the
# threaded VeeR EL2 model can stall near reset.
python3 tools/dv/run_dv.py --dut sep --items all --regress \
  --sim-jobs 8 --build-jobs 24
```

`all` includes the `cpu` firmware-boot tests, so a picolibc-enabled RISC-V GCC
(or `scripts/docker-run.sh`) must be available -- the `c_compile` stage above
builds the images with it (see [Prerequisites](#prerequisites)). `rom_fw` stays
out of `all`; run it with `--items rom_fw`.

`all` enrolls 112 leaves. `cpu_stub` (92) and `cpu` (20) are disjoint and
together hold all of them. The class commands below are the pre-merge gate.

### Scheduled tiers

Both scheduled tiers in `.github/workflows/regress.yml` run
`--items cpu_stub`, not `all`: the nightly tier (cron `0 18 * * 0-5`) and the
weekly coverage tier (cron `0 18 * * 6`). Their runners are GitHub-hosted and
the shared `dv-run` action installs uv, Bender and Verilator only, so a
`c_compile` stage has no RISC-V toolchain to call.

The consequence for reading a green CI badge: the `cpu` and `rom_fw` runtime
classes are **never** exercised by any CI tier. Firmware-boot evidence comes
only from a local `all` / `cpu` / `rom_fw` run on a host that has the
toolchain.

The pre-merge class split is the reliable local gate. `rom_fw` is a separate
owner and is not a member of `all`:

```bash
python3 tools/dv/run_dv.py --dut sep --items cpu_stub --regress \
  --tool verilator --stage flist --stage hdl_compile --stage sim \
  --sim-jobs 24 --build-jobs 24
python3 tools/dv/run_dv.py --dut sep --items cpu --regress \
  --tool verilator --stage flist --stage c_compile --stage hdl_compile --stage sim \
  --sim-jobs 8 --build-jobs 24
python3 tools/dv/run_dv.py --dut sep --items rom_fw --regress \
  --tool verilator --stage flist --stage c_compile --stage hdl_compile --stage sim \
  --sim-jobs 8 --build-jobs 24
```

Add `--stage c_compile` to `cpu_stub` when KM `rom_main` images are stale.

### One named test

Include `--stage hdl_compile`: `--stage sim` alone reuses whatever model is on
disk, and a stale one can report a pass that the current RTL would not give.

```bash
python3 tools/dv/run_dv.py --dut sep --items sep_axi_smoke_test \
  --stage flist --stage hdl_compile --stage sim
```

Firmware-boot tests build their image in `--stage c_compile` (shared engine,
`fw/fw.mk`):

```bash
python3 tools/dv/run_dv.py --dut sep --items sep_hello_world_test \
  --stage c_compile --stage flist --stage hdl_compile --stage sim
```

The model rebuilds on SV/config change; Python-only changes reuse it. `all` is
the maximum VPLAN-graded group and tags select subsets. For a randomized test
that should run multiple seeds in one regression, set `reseed = N` in its TOML
entry; reproduce a single failing leaf with `--stage sim --seed N`.

## Results and evidence

Per-run logs land in `build/runs/<run-id>/` (gitignored).

**PASS/FAIL requires positive evidence from `results.xml` — a clean simulator
exit alone is not enough.** A test passing is the entry condition for reading
its checkers, never a substitute for them, and a checker row exists only if a run
can prove it. A log tag is not the proof.

### The evidence gate

A test that exits cleanly without checking anything is not a pass, and
`sep_base_test` is the mechanism that makes such a run fail. Every check logs
`CHK-<ID> PASS`; the base class counts the distinct IDs a leaf emitted and
prints one line per test:

```
EVIDENCE_SUMMARY test=<name> observed=N own=N required=N missing=N ids=...
```

`own` excludes the records `sep_base_test` emits during bring-up, so a leaf
cannot satisfy the gate on infrastructure alone. A leaf whose `own` count is
zero **fails**. Firmware-console leaves emit `CHK-FW-CONSOLE` from `poll_boot`
after the mailbox PASS magic, and that ID is not in `BASE_IDS`, so it counts
as the leaf's own evidence. `_EvidenceFilter.NO_OWN_EVIDENCE` is empty and
may only shrink.

Leaves may also declare more: `min_evidence = N` sets a floor on `own`, and
`required_evidence = ("CHK-A", ...)` names IDs that must appear.

The gate proves a check ran. It does not prove the check was right.

The contracts themselves:

* [`docs/index.adoc`](docs/index.adoc) — SEP DV documentation book (entry point)
* [`docs/SEP_TB_ARCH.adoc`](docs/SEP_TB_ARCH.adoc) — testbench architecture: VIP
  policy, env hierarchy, HDL top, stimulus and checking. Also the detail the
  README leaves out — eFuse content selection (the `+sep_efuse_preload` selector,
  the `SepEfuseImage` golden, the sense-and-compare flow), what backs the memory
  / eFuse / SPI ports inside `sep_wrapper` and their backdoor plusargs, CPU-trace
  reconstruction and symbolization, and the Boot ROM image builds.
* [`docs/SEP_VPLAN.adoc`](docs/SEP_VPLAN.adoc) — verification plan: per-test
  contracts and checkers, naming rules, VIP policy, iconic feature scorecard.

## Code coverage

`--cov` is collected on VCS. Only `[coverage.vcs]` applies the compile-time
scope, so that is the graded number. It instruments the build, writes one
native database per test leaf (`coverage/simv.vdb` under each leaf), and
merges/reports through the `cov_merge`/`cov_report` stages into
`<run_dir>/cov/merged.vdb`. That is `-cm line+cond+tgl+fsm+branch+assert` at
both compile (`{build_cov_dir}`) and sim (`{cov_dir}/simv.vdb`), merged by
`urg`. `--cov --tool verilator` is not the graded number. Verilator 5.046
fails that C++ compile (`__PVT__MLKEM_SHARED_KEY` under `VM_COVERAGE=1`);
5.050 compiles. Hosted weekly coverage (`.github/workflows/regress.yml`) is
Verilator `--items cpu_stub` on the large runner, not this VCS number.

```bash
python3 tools/dv/run_dv.py --dut sep --items all --regress --cov --tool vcs \
  --target default --sim-jobs 32 --build-jobs 32
```

`all` is the coverage set: 112 leaves, `cpu_stub` (92) plus `cpu` (20).
Boot ROM firmware (`rom_fw`) is not a member -- another owner, a third RTL
target, firmware rather than hardware contracts -- so reaching those tests
means naming `rom_fw`. `expected_count` is 112.

`--target default` compiles the full CPU once. no_cpu leaves force-splice the
LSU VIP onto the post-remap request; cpu leaves run as firmware. Every leaf is
one elaboration. Edit `cov/config/vcs/sep_cov_scope.hier` then `--rebuild`.

What the resulting number is not:

* **Not functional coverage.** These are code metrics only. Phase 1 functional
  coverage is a separate number: the URG **Group** report on
  `sep_uvm_top.u_sep_fcov` (`cov/sv/sep_fcov.sv`, VCS only -- Verilator does not
  compile `covergroup`), planned in
  [`docs/SEP_FCOV.adoc`](docs/SEP_FCOV.adoc). A covergroup bin records that an
  interface event happened, never that it was correct, so "did the DUT do the
  right thing" stays with the checkers in
  [`docs/SEP_VPLAN.adoc`](docs/SEP_VPLAN.adoc).
* **TT-owned SEP integration RTL, not the whole DUT.**
  `cov/config/vcs/sep_cov_scope.hier` removes the testbench, CPU subtree,
  library-class cells, DV models and complete third-party IP modules at compile
  time across code and assertion coverage (`-cm_hier` with
  `-cm_common_hier`). Quote that scope with the percentage; never call it bare
  "SEP DUT coverage". `urg -hier` at report time prunes report pages and still
  grades the whole database, so the scope is this compile-time file.
* **Not a read on assertions.** Assertion coverage counts elaborated assertions
  only, and SEP gates those through the `prim_assert` shim. Confirm assertions
  are live before reading that column.
* **One seed per leaf.** `--regress` takes a fresh seed per leaf, so a randomized
  test contributes one sample. Pin seeds for any number that gets cited.

### Boot ROM firmware coverage

Boot ROM C source coverage is separate from simulator-native RTL coverage.
Run the `rom_fw` group with `--plusarg +sep_rom_fw_coverage`; the existing
CPU trace monitor then writes a Renode-format retired-PC trace into each
simulation leaf. Generate the report from that exact run directory:

```bash
uv run --locked python3 tools/dv/fw_coverage/gen_sep_rom_coverage.py \
  --run-dir "$RUN_DIR"
```

The generator accepts only passing, complete traces and uses the leaf-local
`boot_rom.elf` staged by the firmware profile. It reports `boot_rom`,
`boot_rom_ot`, and `boot_rom_ot_pio` separately because their PCs cannot be
interpreted with one shared ELF. See
[`tools/dv/fw_coverage/README.md`](../../../../tools/dv/fw_coverage/README.md)
for the complete command and tool prerequisites.

## Run modes, targets, and groups

The run mode selects who owns the CPU master buses. The RTL target selects which
CPU image is compiled. Groups in `testlists/all.toml` pick the leaf set. The
entries below are entry points — use `--items all --list` for the catalog.

| Group | Role |
|---|---|
| `smoke` | CI gate: `sep_axi_smoke_test` only |
| `all` | 112 leaves: `cpu_stub` (92) and `cpu` (20). `expected_count` is 112 |
| `cpu_stub` | CPU not alive (`sep_cpu` stub, `target = lsu_stub_all_live`) |
| `cpu` | full-CPU firmware daily class (fallback `target = default`) |
| `rom_fw` | production Boot ROM firmware; `rom_boot` target; not a member of `all` |

### No-CPU AXI — `run_modes.no_cpu`

The CPU is held off (`mpc_reset_run_req=0`). Two masters can drive the DUT:

* **LSU splice (`s_axi_*`).** The `lsu_stub_all_live` target swaps in
  `shims/cpu/sep_cpu_stub.sv`, which is the sole driver of `lsu_axi_req` and
  drives it from `tb_top`'s `lsu_req_drive` with a plain `assign` — not a
  `force`. This path has no inbound filter. On a full-CPU VCS
  `--target default` elaboration, a no_cpu test force-splices the same
  post-remap node.
* **SMN-inbound (`m_axi_*`).** A second `SepAxiAgent` on the real
  `smn_inbound` port. It idles unless the test starts an ext sequence. This
  path traverses `u_inbound_filter` (block-by-default → DECERR unless
  `feat_ctrl.sep_debug=1`).

* `sep_axi_smoke_test` — reset-value read of `sep_cpu_ctrl.SEP_LOCAL_BASE_ADDR`
  (`+0x0C8`) for decode sanity, then a masked write/readback walk of
  `SEP_SW_DEBUG`, `SEP_NMI_VEC`, and `PKA_CTRL`.
* `sep_address_map_test` — `sep_cpu_ctrl` sweep plus one CSR per LSU-reachable
  block (DMA, WDT, scratch, reset, OTBN/AES/HMAC/KMAC, CSRNG/EDN/ESRC, ABR,
  entropy pool, lifecycle, KM/AXI mailbox, eFuse shadow, inbound filter,
  alias/outbound remap, SPI), and a complete-and-not-alias check of the
  reserved span inside `sep_cpu_ctrl`. Not CSR bit-bash and not a full
  dead-space walk.

### CPU firmware boot — `run_modes.cpu`

`+cpu_boot` runs the full-CPU build, so the core owns its buses and runs firmware
from the wrapper's real TCM macros, backdoor-loaded by `tb_backdoor_mem` in
`tb/tb_top.sv`. `--stage c_compile` builds the gitignored
`fw/build/tests/<name>/{.itcm,.dtcm}.hex` images through `fw/fw.mk`.

* `sep_hello_world_test` — loads the OSS `fw/tests/hello_world` image into
  ICCM/DCCM and passes `rst_vec=0xC0000000` to `tb_top.sv`, which drives the
  wrapper's direct reset-vector input before reset releases and sets
  `mpc_reset_run_req=1`. The test boots VeeR EL2 and checks PC advance
  (`sep_cpu_trace`) plus the firmware banner and PASS magic on the outbound
  mailbox (`tb/sep_outbound_mbx.sv`).

Boot/reset invariant: `ext_boot_seq_done_i=1`. Fuse-sense policy is testcase
metadata, not a run mode: non-eFuse tests usually add `+skip_fuse_sense` to their
testlist entry's `args` to bypass the slow sense path. Real eFuse tests omit that
bypass and let the RTL fuse-sense FSM finish against the generic eFuse model.

Production Boot ROM firmware tests belong to the ROM-FW owner, use the `rom_boot`
target, and need extra `c_compile` profiles — see
[`docs/SEP_TB_ARCH.adoc`](docs/SEP_TB_ARCH.adoc#_boot_rom_firmware_builds).
Key Manager `rom_main` tests declare
`firmware = { name = "rom_main", mode = "km_rom_main" }` so `c_compile` builds
the gitignored `rom_main.rom.parhex`.

## SystemVerilog UVM framework (`--framework uvm`)

The SV-UVM view shares this DV root, sim config, and testlist with the cocotb
flow: `sep_sim_cfg.toml` declares it as the `[frameworks.uvm]` overlay (same
Bender RTL recipe, stubs, and shims), and `--dut sep --framework uvm` selects
it. A testlist entry binds both implementations of one scenario
(`module = { cocotb = "...", uvm = "..." }`), so the same `--items` name
selects the same VPLAN scenario in either framework; the UVM class name is
the `uvm` entry (`+UVM_TESTNAME`). A group runs its UVM-implemented subset;
naming a scenario with no `uvm` entry errors. `sep_axi_smoke_test` is the
scenario with a `uvm` binding. VCS only: Verilator has no SV-UVM support. The
bench architecture is in `docs/SEP_TB_ARCH.adoc` ("SystemVerilog UVM
Realization"); the framework conventions it follows are in
`hw/common/dv/docs/uvm-framework.adoc`.

`tb/tb_top.sv` is one module with two shapes: the cocotb pin port list by
default, internal TB signals plus the SV-UVM harness under the bare `UVM`
define. Every TB signal is declared once in `tb/sep_tb_signal_list.svh`. The
no_cpu scenarios keep `target = "lsu_stub_all_live"`, so the `sep_cpu` stub is
the sole LSU driver and the shared `ocah_axi_vip` master drives the `s_axi_*`
splice through it.

```bash
# SV-UVM build only (VCS)
python3 tools/dv/run_dv.py --dut sep --framework uvm --build-only

# PyUVM (cocotb) and SV-UVM, same logical scenario name
python3 tools/dv/run_dv.py --dut sep --items sep_axi_smoke_test --seed 1
python3 tools/dv/run_dv.py --dut sep --framework uvm --items sep_axi_smoke_test --seed 1

# Smoke group, UVM-implemented subset
python3 tools/dv/run_dv.py --dut sep --framework uvm --items smoke

# Negative validation: a corrupted scoreboard prediction must make the run FAIL
python3 tools/dv/run_dv.py --dut sep --framework uvm --items sep_axi_smoke_test \
  --plusarg +SEP_CSR_SCOREBOARD_NEGATIVE

# Loop and volume knobs (specific-first): +SEP_AXI_SMOKE_TEST_LOOPS=N,
# +SEP_SYSTEM_TEST_LOOPS=N, +SEP_TEST_LOOPS=N, +SEP_RANDOM_COUNT=N
python3 tools/dv/run_dv.py --dut sep --framework uvm --items sep_axi_smoke_test \
  --plusarg +SEP_TEST_LOOPS=4
```

To port another cocotb scenario: add `uvm/seq_lib/<name>_seq.svh` on
`sep_base_test_seq`, a thin `uvm/tests/<name>.svh` on `sep_base_test`, list
both in their package and manifest, and give the testlist entry its `uvm`
binding.

## Layout

Must: `cocotb/`, `cov/`, `docs/`, `tb/`, `testlists/`, `uvm/`, `README.md`,
`sep_sim_cfg.toml`, and `fw/`. `fw/` is must because the shared engine discovers
`hw/{ip,sys}/*/dv/fw/fw.mk` (same path as SMC and Key Manager). Product Boot ROM
stays at `../bootrom/`.

Optional: `models/` (open `sep_external` stand-in), `shims/` (`sep_cpu` stub +
analog), `.gitignore` (SEP-local generated products), `sep_public_scope.vlt`
(scoped Verilator public list).

```
hw/sys/sep/dv/
├── cocotb/              # PyUVM env, sequences, tests; dv_sim_prestage.py
├── uvm/                 # SV-UVM realization (`--framework uvm`, VCS)
├── cov/                 # VCS code-coverage scope (`cov/config/vcs/`) and the Phase 1 FCOV sampler (`cov/sv/sep_fcov.sv`, VCS only)
├── docs/                # TB architecture, VPLAN, FCOV
├── fw/                  # DV firmware (`fw.mk` / `c_compile`)
├── tb/                  # sep_uvm_top, mailbox, preload images
├── testlists/           # leaf lists + all.toml groups
├── models/              # optional: open sep_external RDL + generated headers
├── shims/               # optional: sep_cpu stub, analog oscillator
├── sep_sim_cfg.toml     # native runner config
├── sep_public_scope.vlt # optional: scoped Verilator public list
├── .gitignore           # optional: SEP-local generated products
└── README.md            # how to build and run, and this layout
```

## OSS hygiene

Verify the filelist is vendor-clean:

```bash
python3 tools/dv/check_no_vendor_paths.py --filelist <sep.flist>
```

Bender targets, shims, and what stays off the filelist are in
`docs/SEP_TB_ARCH.adoc` (Canonical RTL and Shim Selection).

## Troubleshooting

**`Define or directive not defined: '`TEC_RV_ICG'`** (from
`vendor/chipsalliance/Cores-VeeR-EL2/upstream/design/lib/beh_lib.sv`) — the committed VeeR EL2 config snapshot is
missing or was clobbered. Check it:

```bash
grep TEC_RV_ICG vendor/chipsalliance/Cores-VeeR-EL2/overlay/snapshots/sep/common_defines.vh
# expect: `define TEC_RV_ICG clockhdr
```

Restore it from git rather than regenerating. The snapshot is committed
collateral (see that package's `Bender.yml`), so a fresh clone builds as is; it
lives in `overlay/` so `bender vendor init` — which wipes and recreates
`upstream/` only — never touches it.

**`unrecognized command line option '-fcoroutines'`** — g++ is too old for
Verilator `--timing`. See [Prerequisites](#prerequisites).

**`no picolibc-enabled RISC-V toolchain`** — host `RISCV_TOOLCHAIN` has no
`--specs=picolibc.specs`. Leave `RISCV_TOOLCHAIN` unset and keep
`scripts/docker-run.sh` runnable, or point `RISCV_TOOLCHAIN` at a picolibc
install. See [Prerequisites](#prerequisites).

**`No module named tt_boot_manifest`** — the manifest packer submodule is not
checked out; only affects Boot ROM builds. See
[`docs/SEP_TB_ARCH.adoc`](docs/SEP_TB_ARCH.adoc#_boot_rom_firmware_builds).
