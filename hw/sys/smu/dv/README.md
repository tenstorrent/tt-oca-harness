<!--
SPDX-License-Identifier: Apache-2.0
SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
-->
# SMU OCAH Open-Source TB

OCAH open-source DV testbench for the **SMU (System Management Unit)**.
Layout follows `hw/sys/sep/` (flow-first cocotb under `cocotb/`).
See [`docs/index.adoc`](docs/index.adoc) for the chapter set:
[`docs/SMU_TB_ARCH.adoc`](docs/SMU_TB_ARCH.adoc) for the testbench
architecture, [`docs/SMU_VPLAN.adoc`](docs/SMU_VPLAN.adoc) for the
verification plan, and
[`docs/SMU_FEATURE_LIST.adoc`](docs/SMU_FEATURE_LIST.adoc) for the
candidate v0.5.0 SEP=0 feature subset (unsigned; #487),
[`docs/SMU_SCOPE_TRACEABILITY.adoc`](docs/SMU_SCOPE_TRACEABILITY.adoc)
for the candidate requirement-to-test matrix (unsigned; #479), and
[`docs/SMU_DEFERRED_DISPOSITION.adoc`](docs/SMU_DEFERRED_DISPOSITION.adoc)
for the v0.5.0 deferred/OUT classification of the 123-entry catalog,
[`docs/SMU_RELEASE_MATRIX.adoc`](docs/SMU_RELEASE_MATRIX.adoc) for the
v0.5.0 release regression matrix (#485),
[`docs/SMU_COVERAGE_POLICY.adoc`](docs/SMU_COVERAGE_POLICY.adoc) for the
candidate coverage-target and waiver-field decision (#484), and
[`docs/SMU_SEP0_COMPONENT_SIGNOFF.adoc`](docs/SMU_SEP0_COMPONENT_SIGNOFF.adoc)
for the SEP=0 component signoff record (#481 / #482 / #483 / #490 / #491).

**Executable contract:** enrolled groups in
[`testlists/wrapper.toml`](testlists/wrapper.toml) — live green `all` **81**,
`sep0_all` **53** (no Force; product-pin CTM). `--dut smu` is the DUT;
[`testlists/all.toml`](testlists/all.toml) holds the two bare-`smu` leaves that
stayed, for the reasons recorded there.
**Green / signoff policy:** no DUT Force / no TB placeholder.
Raise-stub bodies live under `cocotb/tests_deferred/` and are not ported —
**not** reportable as PASS.

**Group ladder:** `build_smoke` ⊂ `smoke` ⊂ `all`, and `sep0_all` ⊂ `all`
(see `testlists/wrapper.toml`). `sep0_all` and `smoke` are siblings, not nested:
`sep0_all` is the toolchain-free SEP=0 set CI runs, while `smoke` reaches the
SEP=1 elaboration and both firmware smokes and so needs the RISC-V toolchain.
`all` is the union plus the SEP=1 firmware set.
**OUT / deferred** (SEP=1 / interop / toggle / `needs_real_lcc`): not ported.
Every named entry is classified in
[`docs/SMU_DEFERRED_DISPOSITION.adoc`](docs/SMU_DEFERRED_DISPOSITION.adoc).
None of those names is a v0.5.0 restore; raise stubs are not reportable as PASS.

```
smu_<scenario>_test
  └─ SmuEnv (`common/smu_dv_env/smu_env.py`)
       ├─ SMC boot / scratch + mailbox observation
       ├─ DTP JTAG TAP BFM
       ├─ External SMN AXI master / OcahAxiSlaveAgent
       └─ SmuScoreboard
```

| Path | Role |
|------|------|
| `tb/tb_top.sv` | `smu_uvm_top` — bare `smu #(.SEP(0))` density TB; one module, two shapes (cocotb pins by default, SV-UVM harness under `UVM`) |
| `tb/smu_tb_signal_list.svh`, `tb/smu_tb_if.sv` | The TB signals declared once for both shapes; the SMU-local TB interface of the SV-UVM view |
| `uvm/{env,seq_lib,tests}/` | SV-UVM realization (`--framework uvm`, VCS) |
| `cocotb/tests/` | The residual bare-`smu` test bodies plus their base test |
| `common/{smu_dv_env,seq_lib}/` | The PyUVM env and sequence library, shared by both DUTs |
| `cocotb/tests_deferred/` | Force-era raise stubs (catalog only); each body's docstring carries its blocker |
| `testlists/all.toml` | Residual `--dut smu_block` leaves (2) |
| `smu_block_sim_cfg.toml` | `--dut smu_block` sim defaults |
| `smu_sim_cfg.toml` | `--dut smu` sim defaults (`smu_wrapper` is a registered alias) |
| `tb/tb_wrapper_top.sv` | `smu_wrapper_uvm_top` — `hw/top/smu_wrapper` harness |
| `cocotb_wrapper/{env,tests}/` | PyUVM tests on this DUT |
| `testlists/wrapper.toml` | The SMU regression (`all` = 81, `sep0_all` = 53) |
| `fw/`, `tools/` | Firmware, readiness |

## BFM Policy

| Interface | VIP / Model |
|-----------|-------------|
| Primary JTAG TAP | `ocah_jtag_vip` |
| External SMN AXI4 | `ocah_axi_vip`: `OcahAxiSlaveAgent` on the outbound boundary (struct port bridged by `ocah_axi_struct_bridge`), master on the inbound pins |
| SMC OTP AXI-Lite (over JTAG2AXI) | `ocah_axi_vip` AXI-Lite |
| SMC scratch / mailbox | Backdoor + cocotb polling |
| Cross-trigger / iJTAG | OCAH-local BFM |

## Running

```bash
# Simulator and bender on PATH (see AGENTS.md for the with/without-companion paths).
mkdir -p "${TMPDIR:?set TMPDIR to a large local scratch directory}"

python3 tools/dv/run_dv.py --dut smu --build-only
python3 tools/dv/run_dv.py --dut smu --items sep0_all --dry-run

# SEP=0 release set: no RISC-V toolchain, no c_compile stage.
python3 tools/dv/run_dv.py --dut smu --items sep0_all

# The whole regression, including the SEP=1 firmware tests (needs the
# toolchain; the firmware c_compiles dominate the wall time).
python3 tools/dv/run_dv.py --dut smu --items all

# The residual bare block bench: two leaves (see testlists/all.toml for why).
python3 tools/dv/run_dv.py --dut smu_block --items all
```

Groups (`testlists/wrapper.toml`): `build_smoke` (2), `smoke` (4),
`sep0_all` (53), `all` (81), `migrated_fabric` (14), `migrated_smc` (12),
`migrated_dtp` (27), `sep_real_fw` (14), `sep_lifecycle` (6), `sep_chain` (2),
`sep_entropy` (1), `sep_rtl_only` (2).
### SystemVerilog UVM framework (`--framework uvm`)

The SV-UVM view shares this DV root, sim config, and testlist with the cocotb
flow: `smu_block_sim_cfg.toml` declares it as the `[frameworks.uvm]` overlay (same
Bender RTL recipe), and `--dut smu_block --framework uvm` selects it. A testlist
scenario carries both implementations in its `module` binding map
(`module = { cocotb = "...", uvm = "..." }`), so the same `--items` name
selects the same VPLAN scenario in either framework; the UVM class name is
the `uvm` entry (`+UVM_TESTNAME`). Selecting a scenario with no `uvm` entry
errors; `--skip-unimplemented` runs a group's UVM-implemented subset instead.
VCS only: Verilator has no SV-UVM support. The bench architecture is in
`docs/SMU_TB_ARCH.adoc` ("SystemVerilog UVM Realization"); the framework
conventions it follows are in `hw/common/dv/docs/uvm-framework.adoc`.

SMU integrates DTP, so the SMU bench checks the embedded DTP with the DTP
bench's own reference models, TAP FSM checker, and scoreboard
(`hw/sys/dtp/dv/uvm/env`), attached through a `dtp_tb_if` instance the SMU
top wires to the DTP instance. The first bound scenario is
`smu_dtp_jtag_smoke_test` (SMU_ALL_005): TAP reset, IDCODE against the
`smu_pkg` configuration, BYPASS one-TCK latency (directed plus seeded random
patterns), TRST and power-on reset back to Test-Logic-Reset, over 16 seeded
passes; every IDCODE and BYPASS scan is predicted by the DTP reference models
and paired by the always-on scoreboard, and the sequence records named
`CHK-*` evidence (`CHECKER_SUMMARY name=smu_scenario`).

```bash
# SV-UVM build only (VCS). --skip-unimplemented (or an --items selection) is required:
# without it the runner selects the cocotb-only scenarios and stops before compiling.
python3 tools/dv/run_dv.py --dut smu_block --framework uvm --build-only --skip-unimplemented

# PyUVM (cocotb) and SV-UVM, same logical scenario name
python3 tools/dv/run_dv.py --dut smu_block --items smu_dtp_jtag_smoke_test --tool verilator
python3 tools/dv/run_dv.py --dut smu_block --framework uvm --items smu_dtp_jtag_smoke_test --seed 1

# Smoke group, UVM-implemented subset
python3 tools/dv/run_dv.py --dut smu_block --framework uvm --items smoke --skip-unimplemented

# Negative validation: a wrong expected IDCODE in both the reference model and
# the scenario evidence must FAIL the run
python3 tools/dv/run_dv.py --dut smu_block --framework uvm --items smu_dtp_jtag_smoke_test \
  --plusarg +SMU_PTAP_IDCODE_NEGATIVE

# Loop-count knobs, resolved specific-first (per test, per group, suite-wide);
# every looped test runs at least 16 seeded passes by default
python3 tools/dv/run_dv.py --dut smu_block --framework uvm --items smu_dtp_jtag_smoke_test \
  --plusarg +SMU_DTP_JTAG_SMOKE_TEST_LOOPS=4
python3 tools/dv/run_dv.py --dut smu_block --framework uvm --items smoke --skip-unimplemented \
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

## Signoff source

| Source | DUT | Signoff role |
|--------|-----|--------------|
| `--dut smu` (alias `smu_wrapper`) | `tb/tb_wrapper_top.sv` (`DUT_TAG=WRAPPER`) | The SMU regression: SEP=0 density / CSR / fabric / DTP (`sep0_all` = 53) plus the SEP=1 firmware set (`all` = 81) |
| `--dut smu_block` | `tb/tb_top.sv` (`DUT_TAG=BARE`) | Two leaves: `smu_dtp_jtag2axi_abort_mid_op_test`, which needs an unterminated OTP interface, and `smu_dtp_jtag_smoke_test`, which carries the SV-UVM binding (the SV-UVM harness is this TB's `UVM` shape) |

One signoff source: the wrapper is the same `smu` with the open-source IP
integration attached, so there is no second catalog to reconcile against.

`--dut smu` selects the wrapper; the bare block bench is `--dut smu_block`.
`smu_wrapper` is registered as an alias of `smu` (`alias_of` in
hw/common/dv/configs/duts.toml), so the two names resolve to one config, one
build cache and one identity. Logs still carry `DUT_TAG=`.

## Compile profiles (`--dut smu`)

`smu_sim_cfg.toml` builds `hw/top/smu_wrapper.sv` (via the `smu_wrapper` Bender
target) with two compile profiles:

- `compile_smu_chiplet_no_sep`: wrapper with `NoSepCfg`, `SEP=0`.
- `compile_smu_chiplet_sep_rtl`: wrapper with `DefaultCfg`, `SEP=1` and the
  real SEP EL2 CPU.

OSS ships `hw/sys/sep/rtl/sep_tcm_wrapper.sv` (Bender) and needs no DV TCM
shim: the `ram_<depth>x39` ICCM/DCCM macros it instantiates come from the
upstream VeeR `mem_lib.sv` already on the `sep_el2` Bender closure (the sim-cfg
exclude of `hw/sep/sep_tcm_wrapper.sv` is a stale path). Those macros have no
init-file hook, so `tb/tb_wrapper_top.sv` backdoor-loads `+sep_itcm_hex` /
`+sep_dtcm_hex` into their `ram_core` arrays at time zero — de-interleaved into
the EL2 bank/row layout with per-word Hsiao ECC — and counts qualified bank
writes at the `sep_tcm_wrapper` request port for the DCCM-store evidence. This
mirrors the SEP DV TB backdoor (`hw/sys/sep/dv/tb/tb_top.sv`, `` `BD_ICCM ``
/ `` `BD_DCCM ``). A missing image is fatal at t=0 rather than a boot timeout.
Verilator tooling shims (`prim_sync2/3`) are shared from
`hw/sys/smc/dv/tb/verilator_stubs/` (see SMC README B1/B2).

### Readiness gates

```bash
python3 hw/sys/smu/dv/tools/smu_wrapper_tb_readiness_test.py --phase source

python3 tools/dv/run_dv.py --dut smu \
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

### Real SEP DV firmware (`--items sep_real_fw`)

These boot the images from `hw/sys/sep/dv/fw/tests/`, the same ones the internal
SMU suite uses, rather than this DV root's minimal freestanding smoke. They need
the toolchain container (see `[c_build.sep_dv_fw]`), so they are enrolled in
`sep_real_fw` rather than the merge gate.

The verdict is always the firmware's own — a named terminal loop, or the STDOUT
mailbox handshake — and the testbench only observes. `seq_lib/sep_fw_common.py`
holds the symbol lookup and PC attribution; `seq_lib/sep_terminal_loop_seq.py`
is the shared loop classifier that most of these subclass in a few lines.
`cocotb_wrapper/env/smu_sep_cpu_trace_monitor.py` is the passive SEP
processor-state monitor every wrapper test builds: a failing scenario ends with
its symbolized SEP call stack, trap records, and recent-PC tail in the log, and
`+sep_trace_log` streams every retirement to `sep_trace.log` (see
`docs/SMU_TB_ARCH.adoc`).

| Test | Firmware | Pass evidence |
|------|----------|---------------|
| `smu_sep_boot_health_test` | `sep_smu_boot_health` | boot-ROM reset vector → ICCM `_start` → pass loop |
| `smu_sep_sanity_test` | `sep_smu_sanity` | stage beacons 0–4 plus `TEST_MAGIC_PASS`: SHA-256 and SHA3-256 KATs matched on-chip |
| `smu_sep_efuse_test` | `sep_smu_efuse` | eFuse control + external-shim CSR read/write path |
| `smu_sep_wdt_test` | `sep_smu_wdt` | eight WDT CSRs programmed then read back on-chip; the bark, bite and wakeup thresholds are a reset-to-programmed delta, and the first mismatch parks the firmware in its fail loop |
| `smu_sep_dma_test` | `sep_smu_dma` | DMA engine register path |
| `smu_sep_spi_test` | `sep_smu_spi` | OpenTitan `spi_controller` command/address/read-back, six per-stage fail loops |
| `smu_sep_bidirect_test` | `sep_smu_bidirect` + `smu_sep_bidirect_arm` | SEP↔SMC both directions: scratch RW across the crossbar, then a four-pattern handshake |
| `smu_sep_remap_test` | `sep_smu_remap` | AP and STEE output-remap offsets match golden (TB-side compare; the image is a stimulus generator and cannot self-check) |
| `smu_sep_smc_notify_test` | `sep_smc_notify` | outbound egress walked segment by segment: SEP AW → SMU-boundary write → mailbox PASS |
| `smu_sep_rom_tcm_load_test` | `rom_no_tcm_preload_mem_init` | **no TB TCM preload**: ROM-fetched code secure-DMAs into ICCM and executes there |
| `smu_sep_lcc_flow_test` | `sep_smu_lcc_flow` | lifecycle controller driven from firmware: `DEMOTE_1`/`DEMOTE_2` written, write-once `lock` honoured, four named fail loops; plus the posture at two consumers — `lc_state` `0x0f`→`0xf0` at the SMC and `dbg_disable` cleared at the DTP, each a delta off the pre-sense baseline compared against the default eFuse image's TEST_DEV contract |
| `smu_sep_modules_test` | `sep_smu_modules` | module matrix: AES ECB-128 vector, HMAC and KMAC, each with its own fail loop. Brings the entropy stack up first (see below) |
| `smu_sep_aes_test` | `sep_smu_aes` | dedicated AES-128 ECB known-answer test, a second independent vector; alert status checked before parking |
| `smu_sep_otbn_test` | `sep_smu_otbn` | **reachability only**: five OTBN CSR writes cross the SEP outbound fabric without a store access fault. No IMEM/DMEM load, no EXECUTE, and the firmware's own fail branch is unreachable — see the seq docstring before reading anything more into a PASS |

`smu_sep_rom_tcm_load_test` is the exception to the backdoor. Every other anchor has its
ICCM/DCCM placed by the testbench, because the product boot path (ROM → SPI
flash → manifest → BL1) needs the SPI flash models this tree excludes; that
backdoor matches what the OSS SEP DV testbench does. `rom_no_tcm_preload_mem_init`
is the one image that boots from ROM and loads its own TCM, so it covers the
step the backdoor hides. Its boot ROM is loaded exactly as the SEP DV testbench
loads one — `+sep_boot_rom_hex` into `u_sep_boot_rom.mem` — and
`+sep_no_tcm_preload` leaves the TCM zeroed at reset. That plusarg is opt-in on
purpose: for every other test a missing TCM image stays fatal, because silently
booting a zeroed ICCM is the exact failure the loader exists to prevent.

Two images build but are not enrolled, each blocked on a prerequisite rather
than on a test defect — see the notes on their testlist entries:

| Test | Group | Blocked on |
|------|-------|-----------|
| `smu_sep_smc_xbar_test` | `sep_smc_sram_blocked` | SEP-driven SMC bring-up polls SMC SRAM for an image cookie, but that RAM sits on the CPU-private memory interface, so a master arriving through sys-inbound cannot see it. Also blocks `sep_smc_interop` and `sep_smc_mbox_irq`. |
| `smu_sep_ext_axi_test` | `sep_smc_sram_blocked` | Tile reset is taken and released, then no core fetches: neither the ROM nor the scratch read counter moves again. The preload and re-vector both land. |

`smu_sep_modules_test` and `sep_smu_aes` are enrolled in `sep_real_fw`: the
entropy stack is brought up by firmware (`sep_entropy_bringup()` in
`hw/sys/sep/dv/fw/drivers/sep_entropy.h`) ahead of the AES stage, with
`+esrc_noise_force` supplying the raw noise the ring oscillators cannot generate
under Verilator. `sep_smu_otbn` only writes CSRs and needs no entropy.

`smu_sep_ext_axi_test` is built end to end. Its three parties all exist: the SEP
and SMC firmware halves, and an ext_in AXI master played by the sequence on the
flat `ext_in_*` pins the testbench exposes for `cocotbext.axi`. The ext_in
master drives real AXI and gets real responses, including the DECERR the
closed SMC aperture correctly returns.

The SMC boot path's MEM_ZERO FSM writes every word of scratch RAM (4096 bus
writes, exactly the RAM depth) after the time-zero backdoor load unless held
off. `tb_wrapper_top.sv` asserts that hold whenever `+smc_scratch_ram_hex`
supplies an image, so the writes go to 0 and the image survives into firmware.
Handing over by jumping from the ROM leaves the core carrying the ROM's
`mtvec`; `seq_lib/smc_cpu_revector.py` programs `RESET_VECTOR` on all
four cores and forces a tile-reset pulse over the DTP's JTAG2AXI instead, the
way `hw/sys/smc/dv/cocotb/seq_lib/smc_cpu_vip_utils.py` does it over its CSR
agent.

That sequence is applied, not merely issued, and was checked against the
design's own gating rather than its own return codes. A JTAG2AXI write to
CPU_CTRL lands: writing `SCRATCH_0` moves the value observed on
`smc_scratch_0_o` off the `0xACAFACA1` the ROM left. Issued at the right time —
after the SMC has left reset, since `RESET_VECTOR` resets to its own default and
vectors programmed earlier are simply thrown away — `smc_cpu_ctrl_wrap` reaches
`force_apply=1` / `withhold=0`, and all four cores go to `core_reset_n=0` and
back to 1. The cluster never drains, so the `RESET_TIMEOUT` force is what
applies the reset, which is what that register exists for. The tile reset really
is taken and released.

What still blocks it is that nothing follows the release: neither the ROM nor
the scratch read counter moves again and no further instruction retires, so the
cores issue no fetch at all rather than fetching the wrong thing. The image
itself is present; the backdoor reports its stripe load. Whatever answers that
also answers `smu_sep_smc_xbar_test`, blocked on the CPU-private-SRAM limit, and
both tests sit in the `sep_smc_sram_blocked` group until then.

The SEP smoke is a boot-readiness anchor mirroring the internal
`smu_sep_smoke_test` contract; console/STDOUT checking over the external AXI
path is out of scope.

### Entropy stack (`--items sep_entropy`)

| Test | Firmware | Pass evidence |
|------|----------|---------------|
| `smu_sep_entropy_test` | `sep_smu_entropy_bringup` | the chain flows, not just its registers: driven noise reaches `dcor.noise_i`, ESRC produces an accepted seed, CSRNG consumes it (`es_ack`), and the CTR_DRBG produces `genbits` |

The firmware drives the documented order — PHASE-A with the generators off,
generators on, wait for `MAIN_SM_STATUS.BOOT_PHASE_DONE`, then EDN last — and
marks each phase in SEP cold scratch1. It waits on the boot gate rather than on
a delay, and parks in distinct fail loops for "gate never opened" versus
"`ALERT`/`ERR` latched", because an FSM that escalated to AlertHang will never
produce entropy and that is a different verdict from "not yet".

Two things this needs that the rest of the suite does not:

* **`entropy_rosc_sample_clk_i`**, the ESRC ring-oscillator sample clock, is a
  separate and faster clock than `clk_smu`. The TB drives it at 3 ns, matching
  `hw/sys/sep/dv`. With it static the entropy source produces nothing however
  the stack is programmed.
* **`+esrc_noise_force`** drives the 12 `dcor.noise_i` lanes from a per-lane
  LFSR, because the ring oscillators do not self-oscillate under Verilator.
  This is the one forced signal, it is inert without the plusarg, and the
  downstream taps are read-only. `hw/sys/sep/dv` takes the same exception.
  Its other shortcut, `+sep_crypto_edn_force`, is **not** adopted
  here: it would skip the logic these tests exist to exercise.

### Lifecycle and the DTP → SEP → SMC chain

| Group | Tests | Pass evidence |
|-------|-------|---------------|
| `sep_lifecycle` | 6 | per-LC-state feature profile (Table 50): `lc_state` to the SMC, `dbg_disable` to the DTP, `feat_ctrl`, across `TEST_DEV` / `PROD` / `PROD_END` / `RMA_CHIPLET`, plus JTAG debug gating in the two extreme states |
| `sep_chain` | 2 | the full lifecycle path end to end in `PROD` and `PROD_END`: eFuse shadow → SEP lifecycle controller → `dbg_disable` gating the DTP's JTAG2AXI → `lc_state` observed by the SMC, with the SMC's own firmware marker confirming it got there |

LC states are supplied by `hw/sys/smu/dv/assets/sep_efuse_shadow_lc_*.preload`,
which set the diff-encoded state word (`{~x, x}`, so `TEST_DEV` raw `0x0` is
`0xF0`). Posture is sampled only after the fuse sense completes — before that
`lc_state` reads `0x0f`, which is not a state.

### Running

```bash
# Simulator and bender on PATH (see AGENTS.md).
mkdir -p "${TMPDIR:?set TMPDIR to a large local scratch directory}"
# Firmware toolchain: riscv64-unknown-elf-* on PATH, RISCV_TOOLCHAIN, or
# per-tool overrides (e.g. Homebrew): RISCV_GCC/RISCV_OBJCOPY/RISCV_NM.

# Full baseline (regression: no --seed; both profiles incl. real-SEP boot):
python3 tools/dv/run_dv.py --dut smu --items smoke \
  --stage flist --stage c_compile --stage hdl_compile --stage sim

# Single test, cached model (--seed only with a single item):
python3 tools/dv/run_dv.py --dut smu --items smu_sep_smoke_test \
  --seed 1 --stage c_compile --stage sim
```

Firmware images are built by `fw/build_firmware.py` into `build/firmware/`
(declared per test as `[c_build.*].outputs`, then staged into each per-test
run directory). Results land under `build/runs/<ts>__<tool>__<label>/` with
per-test `result.json` / `results.xml`; record issue evidence as commands,
seeds, and those run paths on the tracking GitHub issue.

## Enrollment

`smu_wrapper` carries the regression: 81 enrolled leaves green, of which 53 are
the toolchain-free SEP=0 set CI runs (`.github/workflows/regress.yml`, nightly
at one seed per test, weekly at three) and the rest are the SEP=1 firmware
tests. 28 non-enrolled bodies remain under `cocotb/tests_deferred/`.

Three leaves are enrolled but not in the wrapper's `all`, each with its reason
on its own group: the two `sep_smc_sram_blocked` images, and
`smu_dtp_jtag2axi_abort_mid_op_test`, which stayed on the bare DUT along with
`smu_dtp_jtag_smoke_test` (there for the SV-UVM binding; its cocotb side is
enrolled here in `migrated_dtp`).

Two bodies under `cocotb/tests/` predate the migration, are enrolled nowhere,
and have no wrapper twin: `smu_ext_axi_global_addr_smoke_test` (the OSS `s_axi`
is a LOCAL aperture, so `GLOBAL_BASE + offset` DECERRs) and
`smu_smc_gpio_strap_sanity_test`. Their docstrings carry the reasons.