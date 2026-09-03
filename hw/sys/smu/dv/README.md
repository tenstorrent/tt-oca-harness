# SMU OCAH Open-Source TB

OCAH open-source DV testbench for the **SMU (System Management Unit)**.
Layout follows `hw/sys/sep/` (flow-first cocotb under `cocotb/`).
See [`docs/index.adoc`](docs/index.adoc) for the chapter set:
[`docs/SMU_TB_ARCH.adoc`](docs/SMU_TB_ARCH.adoc) for the testbench
architecture, [`docs/SMU_VPLAN.adoc`](docs/SMU_VPLAN.adoc) for the
verification plan, and
[`docs/SMU_FEATURE_LIST.adoc`](docs/SMU_FEATURE_LIST.adoc) for the
candidate v0.5.0 SEP=0 feature subset (unsigned; #487).

**Executable contract:** enrolled groups in [`testlists/all.toml`](testlists/all.toml)
— live green `phase1` **49**, `sep0_all` **53** (no Force; product-pin CTM).

**Green / signoff policy (2026-07-29):** no DUT Force / no TB placeholder.
Raise-stub Force-era bodies live under `cocotb/tests_deferred/` +
not ported — **not** reportable as PASS.

**Group ladder:** `smoke` ⊂ `top5` ⊂ `top10` ⊂ `phase1` (see `testlists/all.toml`).

**OUT / deferred** (SEP=1 / interop / toggle / `needs_real_lcc`): not ported.

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

### Real SEP DV firmware (`--items sep_real_fw`)

These boot the images from `hw/sys/sep/dv/fw/tests/`, the same ones the internal
SMU suite uses, rather than this DV root's minimal freestanding smoke. They need
the toolchain container (see `[c_build.sep_dv_fw]`), so they are enrolled in
`sep_real_fw` rather than the merge gate until CI carries the image.

The verdict is always the firmware's own — a named terminal loop, or the STDOUT
mailbox handshake — and the testbench only observes. `seq_lib/sep_fw_common.py`
holds the symbol lookup and PC attribution; `seq_lib/sep_terminal_loop_seq.py`
is the shared loop classifier that most of these subclass in a few lines.

| Test | Firmware | Pass evidence |
|------|----------|---------------|
| `smu_sep_boot_health_test` | `sep_smu_boot_health` | boot-ROM reset vector → ICCM `_start` → pass loop |
| `smu_sep_sanity_test` | `sep_smu_sanity` | stage beacons 0–4 plus `TEST_MAGIC_PASS`: SHA-256 and SHA3-256 KATs matched on-chip |
| `smu_sep_efuse_test` | `sep_smu_efuse` | eFuse control + external-shim CSR read/write path |
| `smu_sep_wdt_test` | `sep_smu_wdt` | watchdog control and bark/bite threshold path |
| `smu_sep_dma_test` | `sep_smu_dma` | DMA engine register path |
| `smu_sep_spi_test` | `sep_smu_spi` | OpenTitan `spi_controller` command/address/read-back, six per-stage fail loops |
| `smu_sep_bidirect_test` | `sep_smu_bidirect` + `smu_sep_bidirect_arm` | SEP↔SMC both directions: scratch RW across the crossbar, then a four-pattern handshake |
| `smu_sep_remap_test` | `sep_smu_remap` | AP and STEE output-remap offsets match golden (TB-side compare; the image is a stimulus generator and cannot self-check) |
| `smu_sep_smc_notify_test` | `sep_smc_notify` | outbound egress walked segment by segment: SEP AW → SMU-boundary write → mailbox PASS |
| `smu_sep_rom_tcm_load_test` | `rom_no_tcm_preload_mem_init` | **no TB TCM preload**: ROM-fetched code secure-DMAs into ICCM and executes there |
| `smu_sep_lcc_flow_test` | `sep_smu_lcc_flow` | lifecycle controller driven from firmware: `DEMOTE_1`/`DEMOTE_2` written, write-once `lock` honoured, four named fail loops |
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

`smu_sep_modules_test` used to sit in this table, blocked on the entropy stack.
It is now enrolled in `sep_real_fw`: the entropy stack is brought up by firmware
(`sep_entropy_bringup()` in `hw/sys/sep/dv/fw/drivers/sep_entropy.h`) ahead of
the AES stage, with `+esrc_noise_force` supplying the raw noise the ring
oscillators cannot generate under Verilator. `sep_smu_aes` is enrolled on the
same basis. `sep_smu_otbn` was listed alongside them as entropy-blocked, which
was wrong: it only writes CSRs and never needed entropy at all.

`smu_sep_ext_axi_test` is now built end to end and blocked on the same preload
problem. Its three parties all exist: the SEP and SMC firmware halves, and an
ext_in AXI master played by the sequence on the flat `ext_in_*` pins the
testbench now exposes for `cocotbext.axi` (`smu_axi_in_req` used to be tied off,
so that third party could not exist at all). `smu_sep_ext_axi_arm` is an SMC ROM
that hands control to the scratch-RAM half, and the sequence reconciles its jump
target against `smu_sep_ext_axi_smc_entry` in the built `.sram.sym`.

What blocks it is preload lifetime, measured rather than assumed: the SMC boot
path writes every word of scratch RAM (4096 bus writes, exactly the RAM depth)
after the time-zero backdoor load, so the image is gone before firmware runs.
Swapping in the plain non-jumping ROM produces the same 4096 writes, so it is
not the handoff. The ext_in master itself is proven working by the same run — it
drives real AXI and gets real responses, including the DECERR the closed SMC
aperture correctly returns. Unblocking means moving the stripe load in
`hw/sys/smc/dv/models/smc_cpu_mem_dv.sv` to after that initialisation. That also
looks like the decisive cause behind `smu_sep_smc_xbar_test`, whose note
attributes the failure to the missing sys-inbound path to CPU-private RAM.

The SEP smoke is a boot-readiness anchor mirroring the internal
`smu_sep_smoke_test` contract; console/STDOUT checking over the external AXI
path is tracked separately.

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
  Its other shortcut, `+sep_crypto_edn_force`, is deliberately **not** adopted
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
