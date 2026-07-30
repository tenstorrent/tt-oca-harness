<!-- SPDX-License-Identifier: Apache-2.0 -->
# SMU OCAH Open-Source Verification Plan

## Overview

| Field | Value |
|-------|-------|
| Design Under Test | `smu` / `smu_wrapper` |
| Repository | `tt-oca` / OCAH |
| Framework | cocotb + pyuvm (`run_dv.py`) |
| Active build | **`SEP=0` only** |
| Primary sim | **VCS first**; Verilator after P1 green |
| Runner | `python3 tools/dv/run_dv.py --dut smu` |
| Reference SPEC / CSR / FCOV | `SMU_SPEC.md`, `SMU_CSR.md`, `SMU_FCOV.md` |
| Executable P1 detail | `SMU_OSS_VPLAN_PHASE1.md`, `dv/smu/tb/doc/oss_smu_vplan.md` |
| OUT / deferred names | `../testlists/deferred.toml` |

> **Canonical program (policy 2026-07-29):** no DUT Force / no TB placeholder.
> Live green surface: `phase1` **14**, `sep0_all` **19**, `phase4_sep0` **2**,
> `sep0_p4_all` **19** (see `testlists/all.toml`). Force / LCC / hier-AXIL /
> CTM-Force names live in `testlists/deferred.toml` (`needs_real_lcc` /
> `needs_real_stimulus`) — see `testlists/deferred.toml`.
> Historical ledger rows below that still say PASS for Force-era tests are
> **stale** until rewritten; do not report them as current green.
> **SEP=1 / Appendix A** still OUT. This file is the master VPLAN for OSS SMU DV.
> Satellite notes (`SMU_OSS_COMPLETE_TESTPLAN.md`, `SMU_OSS_VPLAN_P1_P2.md`)
> redirect here.

| Phase | Content | Count | Status |
|-------|---------|-------|--------|
| **P0/P1** | SEP=0 density without Force (smoke ⊂ top5 ⊂ top10 ⊂ phase1) | **14** | **14/14 Verilator PASS (2026-07-29i)** |
| **P2 deepeners** | boot-stall / IC_RESET (non-Force) | **2** enrolled | green under `sep0_all` |
| **P3 corner** | dual-domain illegal + stall vs IC_RESET | **2** enrolled | green under `sep0_all` |
| **P4** | SS IC_RESET + BSR EXTEST only | **2** | enrolled (`phase4_sep0`) |
| — | Force / LCC / CTM-Force / OTP-Force / WDT-Force matrix | OUT | `deferred.toml` |
| — | P1+P2+P3 historical 55 Force-era enrollment | **superseded** | see cleanup log |
| — | **SEP=0 enrolled total** (`sep0_all`) | **19** | **19/19 Verilator (2026-07-29i)** |
| — | **SEP=0 + P4** (`sep0_p4_all`) | **19** | enrolled rollup |

**Status ledger:** full testplan + testcase matrix → **§12** (historical Force PASS rows are stale).

---

## 1. Scope lock

### In scope

- SEP=0 SMU TB glue: SMC + DTP under wrapper
- Real protocol checking (G2+) on shared SMC↔DTP / SMN / JTAG interfaces
- Density-first P1/P2: one representative per IF atom; supersets preferred
- **P3:** corner / race / illegal / dual-agent (G3/G4) deepeners on the same IF set

### Explicitly OUT of P1–P4 (do not schedule)

| Category | Examples |
|----------|----------|
| Glue still OUT | cool pin / memrepair sticky / `ss_reset_complete` (VL stub / dead inputs); dual OCTS; ext IRQ→PLIC; trace mem; true pad BSR / SEP STAP |
| SEP=1 / interop | 3×3 xbar, mailbox C/R, `smu_sep_*`, `smc_sep_*`, SPI bridge, fuse-sense, real LCC #3538 |
| Child TB depth | ROM scratch / CPU bring-up, full I2C/GPIO mux, crypto KAT |
| BLOCKED RTL | CTP pad, NDM reset, TRNG/DMI |
| Commercial | `*_toggle_*` / line-cov as sole pass |

**P4-SEP0 enrolled glue** (not OUT): macro AXIL PLL/PVT/ext, OCTS single-timer CSR, IC_RESET SS cold/warm, EXTEST loopback, telemetry ATB ch0, secure_tm Force, WDT isolate clamp.

OUT names may remain in `deferred.toml` / Appendix A — **not** part of P1–P4 exit.

### Check grades (anti-toggle)

| Grade | Meaning | P1/P2/P3 PASS? |
|-------|---------|----------------|
| **G0** Toggle | Drive net; observe flip | **No** (commercial only) |
| **G1** Connectivity | Remap / port exists | Supporting only inside G2+ |
| **G2** Protocol | Handshake / AXI status / JTAG DR / sticky / policy | **Yes** — P2 minimum |
| **G3** Semantic | Exact CSR/data, aperture, CLA, IRQ | **Yes** — preferred; **P3 minimum** |
| **G4** System | Multi-agent ordering / race | **Yes** — P3 highlight |

**Scoreboard:** `SmuScoreboard.checks > 0`; wrong expected must FAIL.

**Forbidden as sole pass criteria:** `smu_*_toggle_*`, wrapper toggles,
`smu_dtp_jtag2axi_signal_toggle_test`, “port exists / width covers bit N”.

---

## 2. Verification strategy

1. **Stimulus:** `OcahJtagTap` (DTP TAP), cocotbext-axi / `ocah_axi_vip` (SMN + OTP),
   OCAH-local models for xtrig; avoid DTP `env` on PYTHONPATH (clashes with SMU `env`).
2. **Checking:** protocol/status/data scoreboard — not toggle-as-pass.
3. **Lifecycle:** default operational; policy tests Force `feat_ctrl` under SEP=0
   but must still prove gate decision (allow vs deny contrast).
4. **Coverage:** Python FCOV ledger (`SMU_FCOV.md` v1.2 + `smu_fcov.py`); commercial `--cov` optional.

### Naming rules

| Rule | Requirement |
|------|-------------|
| SMU-level | Prefix `smu_` |
| Sub-block reused | Keep `smc_*` where that is the inventory name |
| Strict variants | Suffix `_strict_test` |
| Files | One cocotb test + one sequence per case under `cocotb/` |

### BFM policy

| Interface | Replacement |
|-----------|-------------|
| Primary JTAG TAP | `OcahJtagTap` |
| External SMN AXI4 | AXI master + `AxiRam` |
| OTP AXI-Lite | AXI-Lite VIP / responder (P2) |
| Cross-trigger | OCAH-local / TB ports |
| Scratch / mailbox | Backdoor + poll |

### SEP=0 checker facts

| Fact | Implication |
|------|-------------|
| SYS_IN `BlockByDefault=1` | Unprogrammed SMN CSR → **DECERR** is positive |
| JTAG2AXI bypasses SYS_IN filter | Prefer JTAG2AXI for OKAY CSR checks |
| CTN wire-OR may force `dst_ack=0` | Do not require impossible level handshake |
| CTN CSR relative `[0,0x300)` | Abs `0xC000F000` never reaches DTP: **local xbar periph ends `0xC000E800`** (hole). P1 DECERR is local-xbar, not CTN. |
| OTP bank may be TB-tied | Completing OTP needs responder / shadow |
| `feat_ctrl` tied `'0` under SEP=0 | **OUT** Force ungating — use real LCC (`needs_real_lcc`) |

Scratch: `export TMPDIR=/localdev/$USER/TMPDIR && mkdir -p "$TMPDIR"`.

---

## 3. SMC↔DTP interface inventory (I1–I12)

| ID | Interface | Direction | Protocol to prove | P1 today | P2 target |
|----|-----------|-----------|-------------------|----------|-----------|
| I1 | Fabric JTAG2AXI | DTP→SMC | SINGLE_OP SUCCESS + data; gated deny | G3 smoke | G3 matrix + error |
| I2 | OTP JTAG2AXI | DTP→SMC | CAPS + complete R/W or known DECERR | G2 CAPS/BUSY | **G3 complete** |
| I3 | Boot-stall JTAG | DTP→SMC | sticky gate/release | G3 | + cold-reset matrix |
| I4 | Boot-stall GPIO | pad→SMC | sticky | G3 | keep |
| I5 | IC_RESET TDR | DTP→SMC/EXT | 139-bit domain-correct | G3 | multi-port |
| I6 | Clock-stop / CLA | DTP↔SMC | outs + **CLA feedback** | G2 observe | **G3 loop** |
| I7 | CTM xtrig | DTP↔SMC | remap + **four-phase** where defined | G1/G2 | **G3** |
| I8 | SMC→DTP CSR | SMC→DTP | Local-xbar hole (abs DECERR, no AXIL) + hier CTN OKAY+data | **VCS DONE** | G3 |
| I9 | feat_ctrl / LC | →bridges | allow/deny matrix | G2 Force | G3 matrix |
| I10 | SYS_IN filter | SMN/JTAG | program → OKAY vs DECERR | G2 DECERR | **G3** |
| I11 | Straps/eFuse/WDT | via JTAG2AXI | CSR semantic | G3 light | WDT timeout/IRQ |
| I12 | SEP-OTP err_slv | DTP→err_slv | handshake DECERR+poison | partial | G3 |

---

## 4. In-scope IF matrix

Legend: **DONE** · **P2** · **N/A** (BLOCKED) · **CHILD** · **OUT**

### 4.1 Clocks / resets

| ID | Function | Status | Test | Min |
|----|----------|--------|------|-----|
| IF-CLK-01 | `clk_smu` / ref / periph | DONE | bring-up | G2 |
| IF-RST-01 | cold / powergood / primary_* | DONE | smoke, `smc_reset_ctrl` | G3 |
| IF-RST-03 | IC_RESET TDR | DONE→P2 | override; P2 multi-domain | G3 |
| IF-PWR-01 | powergood → DTP | DONE | bring-up | G2 |
| IF-RST-04 | NDM reset | N/A | BLOCKED | — |

### 4.2 SMN AXI fabric

| ID | Function | Status | Test | Min |
|----|----------|--------|------|-----|
| IF-AXI-01 | SMN subordinate | DONE | smoke DECERR, id, ext | G3 |
| IF-AXI-02 | SMN manager + RAM | DONE | cpu_traffic, atomic | G3 |
| IF-AXI-03 | SYS_IN BlockByDefault | DONE | smoke DECERR | G3 |
| IF-AXI-04 | Filter program → OKAY | P2 | `smu_sys_in_filter_program_jtag_test` | G3 |
| IF-AXI-05 | ID-width SEP=0 | DONE | id_width_conversion | G3 |
| IF-AXI-06 | ATOP reject | DONE | atomic_operation | G3 |
| IF-AXI-07 | GLOBAL_BASE remap | DONE | global_base_remap | G3 |
| IF-AXI-08 | Unmapped DECERR | DONE | crossbar_error | G3 |

### 4.3 DTP JTAG / debug bridges

| ID | Function | Status | Test | Min |
|----|----------|--------|------|-----|
| IF-JTAG-01 | PTAP IDCODE/BYPASS | DONE | jtag_smoke | G3 |
| IF-JTAG-02 | Fabric JTAG2AXI | DONE→P2 | local_axi; P2 rw/error | G3 |
| IF-JTAG-03 | JTAG2AXI security | DONE→P2 | security; P2 feat_ctrl | G3 |
| IF-JTAG-04 | OTP JTAG2AXI | DONE→P2 | CAPS/BUSY; P2 complete | G3 |
| IF-JTAG-05 | Boot-stall | DONE→P2 | stall; P2 cold matrix | G3 |
| IF-JTAG-06 | IC_RESET | DONE→P2 | override; multi-domain | G3 |
| IF-JTAG-07 | Clock-stop / CLA | DONE→P2 | observe; CLA loop | G3 |
| IF-JTAG-08 | SMC→DTP CSR | DONE (P2) | `smu_dtp_csr_access_test` (hole + hier CTN) | G3 |
| IF-JTAG-09 | Cross-domain fabric | P2 | `smu_fabric_smc_dtp_cross_domain_test` | G3 |

### 4.4 Cross-trigger

| ID | Function | Status | Test | Min |
|----|----------|--------|------|-----|
| IF-XT-01 | CTM remap [9:2]↔TB[7:0] | DONE | cross_trigger_matrix | G2 |
| IF-XT-02 | CTM four-phase | P2 | `smu_xtrig_ctm_four_phase_test` | G3 |
| IF-XT-03 | CTM SMC [1:0] / CLA | P2 | `smu_dtp_xtrigger_smc_cla_test` | G3 |
| IF-XT-04 | CTP 16-port pad | N/A | BLOCKED | — |
| IF-XT-05 | Clock-stop remap | DONE→P2 | clock_stop + CLA | G3 |

### 4.5 SMC local via debug glue

| ID | Function | Status | Test | Min |
|----|----------|--------|------|-----|
| IF-SMC-01 | Reset controller | DONE | `smc_reset_ctrl_test` | G3 |
| IF-SMC-02 | Mailbox + IRQ | DONE | `smc_mailbox_int_test` | G3 |
| IF-SMC-04 | GPIO straps | DONE | gpio_strap_sanity | G3 |
| IF-SMC-06 | eFuse map/iface | DONE | efuse_reg_sanity | G3 |
| IF-SMC-08 | WDT unlock/CMP | DONE | wdt_sanity | G3 |
| IF-SMC-09 | WDT timeout/IRQ | P2 | wdt_timeout + scratch | G3 |
| IF-SMC-10 | Demote / lc_sigint | DONE | demote_pm | G2 |
| IF-SMC-05+ | GPIO mux / PLIC / FW / peri | CHILD/OUT | — | — |

### 4.6 Config / no-SEP

| ID | Function | Status | Test | Min |
|----|----------|--------|------|-----|
| IF-CFG-01 | SEP=0 aperture | DONE | no_sep_configuration | G3 |
| IF-CFG-02 | SEP-OTP err_slv | P2 | `smu_dtp_otp_sep0_err_slv_test` | G3 |

---

## 5. Phase-1 catalog (DONE — 24)

Do **not** expand P1 count without removing an equivalent item.
Groups: `smoke` ⊂ `top5` ⊂ `top10` ⊂ `phase1` in `../testlists/`.

### 5.1 Smoke (3)

| # | Test | Pass contract (summary) |
|---|------|-------------------------|
| S1 | `smu_smc_smoke_test` | Reset high; GLOBAL_BASE/SIZE; fuse_sense; SMN DECERR |
| S2 | `smu_dtp_jtag_smoke_test` | IDCODE / BYPASS |
| S3 | `smu_no_sep_configuration_test` | SEP apertures zero |

### 5.2 TOP-5 / TOP-10 / remaining Phase-1

| # | Test | Stream | Grade |
|---|------|--------|-------|
| 1 | `smu_smc_smoke_test` | smc | G2 |
| 2 | `smu_dft_dtp_boot_stall_test` | dtp | G3 |
| 3 | `smu_dtp_dtm_local_axi_test` | dtp | G3 |
| 4 | `smc_cpu_traffic_ext_axi_test` | fabric | G3 |
| 5 | `smu_axi_id_width_conversion_test` | fabric | G3 |
| 6 | `smu_axi_crossbar_error_handling_test` | fabric | G3 |
| 7 | `smu_jtag_reset_override_test` | dtp | G3 |
| 8 | `smu_cross_trigger_matrix_test` | dtp | G1/G2 |
| 9 | `smc_reset_ctrl_test` | smc | G3 |
| 10 | `smc_mailbox_int_test` | smc | G3 |
| 11 | `smu_dtp_otp_debug_access_test` | dtp | G2 |
| 12 | `smu_clock_stop_coordination_test` | dtp | G2 |
| 13 | `smu_lifecycle_debug_policy_test` | dtp | G2 |
| 14 | `smu_smc_dtp_jtag2axi_security_test` | dtp | G3 |
| 15 | `smu_dft_gpio_boot_stall_test` | dtp | G3 |
| 16 | `smc_gpio_strap_sanity_test` | smc | G3 |
| 17 | `smc_efuse_reg_sanity_test` | smc | G3 |
| 18 | `smc_wdt_sanity_test` | smc | G3 light |
| 19 | `smc_security_demote_pm_test` | smc | G2 |
| 20 | `smu_axi_external_port_connectivity_test` | fabric | G3 |
| 21 | `smu_smc_global_base_remap_test` | fabric | G3 |
| 22 | `smu_axi_atomic_operation_test` | fabric | G3 |
| S2 | `smu_dtp_jtag_smoke_test` | dtp | G3 |
| S3 | `smu_no_sep_configuration_test` | smc | G3 |

Detail / run commands: `SMU_OSS_VPLAN_PHASE1.md`, `oss_smu_vplan.md`.

### 5.3 Honesty — P1 items that need P2 deepeners

| P1 test | Gap | P2 ID |
|---------|-----|-------|
| `smu_dtp_otp_debug_access_test` | No completing OTP RDATA | P2-I2a |
| `smu_clock_stop_coordination_test` | No CLA feedback loop | P2-I6a |
| `smu_cross_trigger_matrix_test` | Not four-phase CTM | P2-I7a |
| `smu_lifecycle_debug_policy_test` | Not full feat_ctrl matrix | P2-I9a |
| `smu_dtp_dtm_local_axi_test` | No series/error/WSTRB | P2-I1a |
| `smu_smc_dtp_jtag2axi_security_test` | Complement with LC matrix | P2-I9a |
| *(was missing)* | Local-xbar hole + hier CTN CSR | P2-I8a **VCS PASS** |
| `smu_smc_smoke_test` | Filter never programmed | P2-I10a |
| `smc_wdt_sanity_test` | No timeout/IRQ | P2-I11a |

P1 already protocol-grade (keep): boot-stall sticky, IC_RESET, GLOBAL_BASE,
fabric DECERR/ATOP/id-width, mailbox IRQ, straps, eFuse CSR, IDCODE/BYPASS,
no-SEP zeros.

---

## 6. Phase-2 catalog (DONE — 15)

### 6.1 Scope rules

| In P2 | Out |
|-------|-----|
| I1–I12 under SEP=0 | SEP=1 mailbox/xbar/interop |
| SMC↔DTP both directions | Toggle sweeps |
| OTP complete + err_slv | Child I2C/GPIO/crypto |
| CTM four-phase / CLA loop | Scan / shim / telemetry |
| Filter program → OKAY | Commercial toggle % |
| feat_ctrl matrix (Force **removed**) | Real LCC #3538 enforce |

### 6.2 Tests + pass contracts

#### Stream A — DTP→SMC data planes

| ID | Test | Must FAIL if… |
|----|------|---------------|
| P2-I1a | `smu_dtp_jtag2axi_smc_rw_matrix_test` | SIZE/WSTRB/addr wrong; status mishandled; sticky (**VCS PASS**) |
| P2-I1b | `smu_dtp_jtag2axi_smc_error_path_test` | Unmapped/poison missed; busy timeout wrong (**VCS PASS**) |
| P2-I2a | `smu_dtp_otp_smc_complete_rw_test` | RDATA ≠ shadow; gated write updates map (**VCS PASS**) |
| P2-I2b | `smu_dtp_otp_sep0_err_slv_test` | No handshake or resp≠DECERR/poison (**VCS PASS**) |

#### Stream B — Control / reset / stall

| ID | Test | Must FAIL if… |
|----|------|---------------|
| P2-I3a | `smu_boot_stall_jtag_cold_reset_matrix_test` | Sticky broken; wrong TRST clear (**VCS PASS**) |
| P2-I5a | `smu_ic_reset_smc_multi_domain_test` | Wrong port toggles wrong reset (**VCS PASS**) |

#### Stream C — Clock-stop + xtrig

| ID | Test | Must FAIL if… |
|----|------|---------------|
| P2-I6a | `smu_dtp_clock_stop_smc_cla_loop_test` | stop_clks / CLA en / **feedback** mismatch (**VCS PASS**) |
| P2-I7a | `smu_xtrig_ctm_four_phase_test` | Illegal four-phase / wrong SMC bits (**VCS PASS**) |
| P2-I7b | `smu_dtp_xtrigger_smc_cla_test` | DTP→SMC CLA path silent (**VCS PASS**) |

If RTL wire-OR forces ack=0, assert **that** (positive) — do not invent handshakes.

#### Stream D — SMC→DTP CSR

| ID | Test | Must FAIL if… |
|----|------|---------------|
| P2-I8a | `smu_dtp_csr_access_test` | Abs access reaches DTP AXIL or CTN readback wrong / unmapped≠DECERR (**VCS PASS**) |
| P2-I8b | `smu_fabric_smc_dtp_cross_domain_test` | Only one direction works (**VCS PASS**) |

#### Stream E — Policy / filter / WDT

| ID | Test | Must FAIL if… |
|----|------|---------------|
| P2-I9a | `smu_dtp_feat_ctrl_gate_matrix_test` | Gate polarities disagree with golden (**VCS PASS**) |
| P2-I10a | `smu_sys_in_filter_program_jtag_test` | After program, SMN still DECERR on allowed window (**VCS PASS**) |
| P2-I11a | `smc_wdt_timeout_irq_test` | Unlock ok but WDOGIP0 never fires (**VCS PASS**) |
| P2-I11b | `smc_reset_unit_wdt_scratch_test` | WDT reset clears wrong scratch domain (**VCS PASS**) |

### 6.3 Bring-up order

**I8a → I2a → I6a → I7a → I10a → matrices / error deepeners.**

### 6.4 TB infra before coding P2

| Need | Unblocks |
|------|----------|
| Keep SEP=0 `tb_top` + JTAG/SMN/xtrig/strap | P1 done |
| OTP map abs addr + shadow observe | P2-I2a **done** (no bank RAM needed) |
| DTP CSR relative map path | P2-I8* |
| CLA feedback observe | P2-I6a **done** (Force fb → req[0]/stop/TDR) |
| Filter program helper | P2-I10a **done** (narrow page window) |
| Xtrig four-phase checker | P2-I7a **done** |

---

## 7. Phase-3 catalog (DONE on VCS — SEP=0 corner / G4)

> **Intent:** P2 proved each I1–I12 atom once (happy + one deny). P3 attacks
> **hazard classes** the density program intentionally skipped: races,
> illegal sequences, window edges, mid-transaction policy flips, dual-agent
> ordering. Still **SEP=0 only**. Still **G2+ required** (prefer G3/G4).
> Still **no** toggle-as-pass / SEP=1 / BLOCKED RTL / child peri depth.

### 7.1 Scope rules

| In P3 | Out (still Appendix A / BLOCKED) |
|-------|----------------------------------|
| Race / concurrent on I1–I12 + SMN | SEP=1 mailbox / 3×3 / interop |
| Illegal protocol that RTL must reject or ignore safely | Invented handshakes (wire-OR ack=0 stays positive) |
| Address / WSTRB / filter **boundary** | Scan / shim / telemetry / cool / ss_reset |
| Mid-op `feat_ctrl` Force (policy flip) | Real LCC #3538 E2E |
| Dual-agent G4 (JTAG2AXI ∥ SMN ∥ hier AXIL) | Child I2C/GPIO/crypto KAT |
| Recovery after illegal | CTP pad / NDM / TRNG |

**Anti-patterns (reject as P3):**
- Remap-only / width-covers-bit-N
- Force without observable scoreboard contrast
- “Settle more cycles” as the fix
- Duplicate P2 with a different seed

### 7.2 Hazard classes → test IDs

| Class | Hazard | Primary IF | P3 IDs |
|-------|--------|------------|--------|
| **H1 Protocol illegal** | Bad phase / abort / mid-DR IR change | I1, I7 | P3-H1a..c |
| **H2 Boundary / partial** | WSTRB/SIZE/filter window edge | I1, I10 | P3-H2a..c |
| **H3 Race / dual-agent** | Two managers same resource | I1+I8+I10 | P3-H3a..c |
| **H4 Policy mid-flight** | Gate flip during outstanding | I9, I2 | P3-H4a..b |
| **H5 Reset / stall priority** | Overlapping reset domains | I3, I5, I11 | P3-H5a..c |
| **H6 Xtrig / CLA stress** | Illegal CTM + concurrent CLA | I6, I7 | P3-H6a..b |

Target count: **14** directed tests (one primary per row below; no matrix explosion).

### 7.3 Planned tests + pass contracts

#### Stream H1 — Illegal / abort (must not corrupt sticky state)

| ID | Test (proposed) | Stimulus corner | Must FAIL if… | Grade |
|----|-----------------|-----------------|---------------|-------|
| P3-H1a | `smu_dtp_jtag2axi_abort_mid_op_test` | Change IR / TRST / TAP reset while SINGLE_OP BUSY | After abort, VERSION_LO SUCCESS+data wrong **or** sticky CSR corrupted | G3 **VCS PASS** |
| P3-H1b | `smu_dtp_jtag2axi_back_to_back_error_ok_test` | DECERR then immediate SUCCESS (no long idle) | Recovery needs “magic delay”; second op status/data wrong | G3 **VCS PASS** |
| P3-H1c | `smu_xtrig_ctm_illegal_phase_test` | ack-before-req; req drop before ack held; double-req | Scoreboard accepts illegal order **or** SMC[1:0] polluted | G3 **VCS PASS** |

#### Stream H2 — Boundary / partial beat

| ID | Test (proposed) | Stimulus corner | Must FAIL if… | Grade |
|----|-----------------|-----------------|---------------|-------|
| P3-H2a | `smu_dtp_jtag2axi_wstrb_partial_sticky_test` | Non-0xF WSTRB write; readback; adjacent word untouched | Partial merge wrong; neighbor word changes | G3 **VCS PASS** |
| P3-H2b | `smu_sys_in_filter_window_edge_test` | Page edges (VERSION/SCRATCH OKAY; ±1 page DECERR) | Edge inside ≠ OKAY **or** edge outside ≠ DECERR | G3 **VCS PASS** |
| P3-H2c | `smu_sys_in_filter_reprogram_shrink_test` | Program wide → access OK → shrink/clear → same addr | After shrink still OKAY (hole) **or** clear does not restore BlockByDefault DECERR | G3 **VCS PASS** |

#### Stream H3 — Dual-agent / race (G4)

| ID | Test (proposed) | Stimulus corner | Must FAIL if… | Grade |
|----|-----------------|-----------------|---------------|-------|
| P3-H3a | `smu_jtag2axi_vs_smn_same_csr_race_test` | JTAG2AXI write VERSION/scratch **while** SMN (filter OK) reads/writes same | Lost update / wrong RDATA without detecting conflict; or SMN sees stale after J2A | **G4 VCS PASS** |
| P3-H3b | `smu_otp_vs_fabric_map_race_test` | OTP JTAG2AXI write MAP word ∥ fabric JTAG2AXI read/write same abs | Shadow ≠ either writer’s last commit; silent tear | **G4 VCS PASS** |
| P3-H3c | `smu_hier_ctn_vs_jtag2axi_concurrent_test` | Hier CTN CONFIG R/W ∥ fabric JTAG2AXI traffic to SMC | CTN readback wrong **or** SMC VERSION_LO breaks | **G4 VCS PASS** |

#### Stream H4 — Policy flip mid-op

| ID | Test (proposed) | Stimulus corner | Must FAIL if… | Grade |
|----|-----------------|-----------------|---------------|-------|
| P3-H4a | `smu_feat_ctrl_flip_mid_jtag2axi_test` | Start ungated SINGLE_OP; Force clear soc/ap mid-BUSY | Completes as SUCCESS+good data after gate **or** hangs forever without bounded status | G3 **VCS PASS** |
| P3-H4b | `smu_feat_ctrl_partial_bit_corner_test` | OTP needs fuse∧soc∧ap: enable only {fuse}, only {soc,ap}, only {fuse,soc} | Any incomplete set still completes OTP MAP write into shadow | G3 **VCS PASS** |

#### Stream H5 — Reset / stall / WDT priority

| ID | Test (proposed) | Stimulus corner | Must FAIL if… | Grade |
|----|-----------------|-----------------|---------------|-------|
| P3-H5a | `smu_ic_reset_dual_domain_illegal_test` | Assert two SMC IC_RESET ports in one DR | Only one of pair asserts; third domain asserts; or ovrd sticks after DEFAULT | G3 **VCS PASS** |
| P3-H5b | `smu_boot_stall_vs_ic_reset_priority_test` | Stall sticky + IC_RESET cold/warm + TRST matrix | Stall clears when it must not **or** survives when TRST should clear | G3 **VCS PASS** |
| P3-H5c | `smc_wdt_scratch_double_pulse_test` | Seed cold+cold_warm; Force second-timeout twice; re-seed mid | Cold sticky clears **or** cold_warm not cleared on first pulse | G3 **VCS PASS** |

#### Stream H6 — CLA / xtrig concurrency

| ID | Test (proposed) | Stimulus corner | Must FAIL if… | Grade |
|----|-----------------|-----------------|---------------|-------|
| P3-H6a | `smu_cla_and_xtrig_concurrent_test` | CLA en+fb stop_clks **while** CTM four-phase on [9:2] | stop_clks drops early **or** CTM lanes corrupt SMC[1:0] | G3 **VCS PASS** |
| P3-H6b | `smu_clock_stop_jtag_vs_cla_fb_race_test` | JTAG DEBUG_CONTROL clock_stop bit ∥ Force CLA fb | TDR bit4 / stop_clks disagree with OR of sources | G3 **VCS PASS** |

### 7.4 Honesty — what P3 will **not** claim

| Topic | Honest limit |
|-------|--------------|
| I11a IRQ/PLIC | Still OUT without CPU/PLIC bring-up; P3 stays CSR/scratch |
| I11b real ChipYard WDT | Force / stub path OK; no claim on cluster isolate export |
| I2b SEP OTP bridge | Still absent under SEP=0; no inventing SEP OTP SUCCESS |
| CTM wire-OR ack | Illegal-phase test asserts **reject/ignore**, not fake ack=1 |
| Verilator packed Force | Mid-op feat_ctrl needs Force-shadow; document tool caveat |

### 7.5 Bring-up order (coding)

1. **H2b / H2c** — filter edges (extends P2-I10a helpers; lowest TB risk)
2. **H2a / H1b** — JTAG2AXI partial + back-to-back (extends P2-I1*)
3. **H4b** — partial feat_ctrl (extends P2-I9a; Verilator shadow RMW already ready)
4. **H5a / H5b** — IC_RESET / stall priority
5. **H1c / H6*** — xtrig/CLA stress
6. **H3*** — dual-agent G4 last (hardest scoreboard)
7. **H1a / H4a** — abort / mid-op gate (needs BUSY observe + bounded timeout)

### 7.6 TB infra before coding P3

| Need | Unblocks |
|------|----------|
| Filter window program + edge addr helper | H2b/c |
| JTAG2AXI BUSY/status poll with abort hook | H1a, H4a |
| Dual-master scheduler (J2A + SMN + optional hier) | H3* |
| Illegal CTM phase injector (reuse four-phase) | H1c, H6a |
| feat_ctrl Force-shadow (done) | H4* |
| IC_RESET multi-port pack (done) | H5a |

### 7.7 Regression group (when enrolled)

| Group | Contents |
|-------|----------|
| `phase3_corner` | §7 H1–H6 (~14) |
| `phase3` | phase2_smc_dtp + phase3_corner |

Exit: each P3 test `SmuScoreboard.checks > 0`, wrong expected must FAIL, VCS first;
Verilator parity after VCS green (same Force/packed rules as P2).

---

## 8. RDL / register policy

| Block | SMU-level requirement |
|-------|------------------------|
| SMU top | **No RDL** — N/A |
| SMC CSRs | Sample via JTAG2AXI / filter: VERSION, GLOBAL_BASE, STRAPS, EFUSE, WDT, mailbox, filter, DTP window |
| DTP TDRs / CTN | IR+DR + relative CSR (P2-I8) |
| Full CSR walk | Child TB — not this gate |

Complete ≠ 100% CSR walk. Complete = every in-scope IF-* at G2+.

---

## 9. FCOV mapping (P1 + P2 + P3)

| FCOV | P1 | P2 adds |
|------|----|---------|
| `smc_boot_cg` | smoke / reset | filter OKAY |
| `xbar_route_cg` | SEP=0 slice | cross-domain SMC↔DTP |
| `reg_access_cg` | JTAG2AXI / OTP CAPS | CSR + OTP complete + error |
| `reset_clock_cg` | cold / IC | multi IC / CLA stop |
| `fuse_lifecycle_cg` | eFuse / lc / demote | feat_ctrl matrix |
| `dtp_debug_cg` | stall / sec / clock-stop | CLA / CSR / OTP complete |
| `xtrig_cg` | remap | four-phase / CLA |
| `sep_boot_cg` / `mailbox_interop_cg` / `interop_bins_cg` | SEP=0 / local | **OUT** |

Ledger detail: `SMU_FCOV.md` (v1.2) + Python `cocotb/env/smu_fcov.py`
(`TEST_FCOV_HITS` auto-hit at end of `run_scenario`). Skill-1 CHK map:
`SMU_FEATURE_LIST.md` (v0.2, P3 CHKs). The scoreboard logs one check token per
named check (log line format `EVIDENCE: <TOKEN>`).

---

## 10. Regression groups

| Group | Contents |
|-------|----------|
| `smoke` / `top5` / `top10` / `phase1` | P1 24 (existing toml) |
| `fabric` | Phase-1 fabric slice |
| `smc` / `dtp` | Phase-1 stream + corresponding P2 deepeners |
| `phase2_smc_dtp` | §6 Stream A–E (**15/15 VCS + Verilator**) |
| `phase2` | phase1 + phase2_smc_dtp |
| `phase3_corner` | §7 H1–H6 (**16** enrolled) |
| `phase3` | phase2_smc_dtp + phase3_corner |
| **`sep0_all`** | **phase1 + phase2_smc_dtp + phase3_corner = 55** (full SEP=0 enrolled) |
| **`phase4_sep0`** | **P4 deepen + glue = 7** |
| **`sep0_p4_all`** | **sep0_all + phase4_sep0 = 62** |
| `deferred` | OUT / SEP=1 / BLOCKED |

```bash
source bin/setup_env.sh
export TMPDIR=/localdev/$USER/TMPDIR && mkdir -p "$TMPDIR"
python3 tools/dv/run_dv.py --dut smu --tool vcs --items phase4_sep0
python3 tools/dv/run_dv.py --dut smu --tool verilator --items phase4_sep0
# After tb_top / .vlt changes: rm -rf hw/sys/smu/dv/build/cocotb/{vcs,verilator}
```

---

## 11. Exit criteria

| Gate | Definition |
|------|------------|
| **P1 done** | 24/24 VCS G2+ — **met**; Verilator parity — **met (24/24)** |
| **P2 done** | All §6 tests G2+ on VCS — **met (15/15)**; Verilator parity — **met (15/15)**; FCOV ledger **updated** (v1.2 + `smu_fcov.py`) |
| **P3 done** | All §7 corner tests G3/G4 on VCS — **met (16/16)**; Verilator parity — **met (16/16)** |
| **P4 done** | All `phase4_sep0` G2+/G3 on VCS — **met (7/7)**; Verilator parity — **met (7/7)** |
| **P1+P2 complete** | **39/39** enrollment — **met**. Does **not** claim full SMU/chiplet coverage |
| **SEP=0 program** | **`sep0_all` 55/55 VCS + Verilator PASS**; P1–P3 exit; FCOV v1.2 + Skill-1 draft — **met** (designer approval still pending) |
| **SEP=0 + P4** | **`phase4_sep0` 7/7** VCS+VL — **met**; `sep0_p4_all` (62) enrolled only — **not** a full 62/62 signoff |

**Honest progress:** SEP=0 P1+P2+P3 **closed** (`sep0_all` 55/55). P4-SEP0 deepen+glue **closed** on `phase4_sep0` 7/7 (re-verified after vacuity fixes). Appendix A / SEP=1 remain OUT.

Notes (honest caveats, not vacuous PASS):
- Policy 2026-07-29: **no DUT Force / no TB placeholder**. Force-era deepeners
  (JTAG2AXI ungating, WDT Force pulse, hier AXIL, CTM Force, secure_tm Force)
  are **OUT** in `testlists/deferred.toml` until real LCC / legal pins exist.
  Tracker: `testlists/deferred.toml`.
- I2b / I11b / P4 secure_tm / P4 WDT clamp: deferred (`needs_real_lcc` /
  `needs_real_stimulus`); do not report historical Force PASS as current.
- Live green: frontdoor JTAG / SMN / observe-only demote+lc_state / boot-stall /
  IC_RESET / BSR EXTEST (see `testlists/all.toml`).
- FCOV: `SMU_FCOV.md` v1.2 + `smu_fcov.py` P1–P3 bins enrolled; commercial SV covergroups still optional.
- aidv Skill-1: `SMU_FEATURE_LIST.md` draft + scoreboard check tokens — **designer approval still pending** (checker list not signed off).

### Non-goals

- Replace child SMC/DTP regressions with SMU toggles
- Claim P1 OTP/xtrig as full protocol closure
- Fake SEP=1 interop under SEP=0 BFMs
- Vacuous PASS on remap-only / Force-only without contrast
- Re-enroll Force helpers or TB placeholders to inflate green counts

### Execution sequence

1. P1+P2 frozen green (**39**) — **done**.
2. Lock P3 §7 scope (SEP=0 corner only; no Appendix A creep) — **done**.
3. Implement §7 in bring-up order (H2 → H1/H4 → H5 → H6 → H3) — **done**.
4. Enroll `phase3_corner`; VCS then Verilator — **done** (16/16 each).
5. Hygiene: `sep0_all` VCS **55/55** + FCOV v1.2 + FEATURE_LIST v0.2 — **done**.
6. P1 Verilator parity + `sep0_all` Verilator **55/55** — **done** (GPIO drive TB port; reset_unit stub STRAPS AXI; feat_ctrl/lc Force).
7. P4-SEP0 deepen + glue (`phase4_sep0` 7) VCS then Verilator — **done**.

---

## 12. Status ledger (canonical — 2026-07-20; policy sync 2026-07-29)

> Single place for **testplan document status** + **enrolled testcase status**.
> **Current executable groups** (`testlists/all.toml`, 2026-07-29): `sep0_all`
> **17**, `phase4_sep0` **2**, `sep0_p4_all` **19**. Force / LCC / hier /
> CTM-Force names are in `deferred.toml` — **not** reportable as PASS.
> The historical Force-era table rows below are marked **DEFERRED** (not green).
> OUT names also stay in Appendix A / `deferred.toml`.
> Latest signoff: VCS/VL `sep0_all` **55/55** (2026-07-17); VCS/VL `phase4_sep0` **7/7** (2026-07-20 honesty re-verify).

### 12.1 Testplan / document inventory

| Document | Role | Status |
|----------|------|--------|
| **`SMU_VPLAN.md` (this file)** | Master P1–P4 plan + status ledger | **Active** (rev 2.26) |
| `SMU_OSS_VPLAN_PHASE1.md` | P1 density / executable contract detail | Active satellite |
| `SMU_OSS_COMPLETE_TESTPLAN.md` | Stub → this file | Redirect only |
| `SMU_OSS_VPLAN_P1_P2.md` | Stub → this file | Redirect only |
| `SMU_SPEC.md` | Feature / IF spec reference | Active |
| `SMU_CSR.md` | CSR / address map reference | Active |
| `SMU_FCOV.md` | Functional coverage intent | Active **v1.4** (P1–P4 bins) |
| `SMU_FEATURE_LIST.md` | Skill-1 FEATURE/CHK/EVIDENCE map | Draft **v0.4**; designer approval **pending** |
| `SMU_TB_ARCH.md` | TB architecture | Active |
| **§13 (this file)** | Result-reporting policy (scenario + checks) | Active |
| `../testlists/all.toml` | Runnable groups (`smoke`…`sep0_p4_all`) | Active |
| `../testlists/{smc,dtp,fabric}.toml` | Enrolled test entries | Active (**62** unique) |
| `../testlists/deferred.toml` | OUT / SEP=1 / toggle / child names + blocker banners | Reference only (**~107** unique names); never reportable as passing |
| `../testlists/{sep,interop}.toml` | SEP=1 / interop **catalog groups** (probe vs blocked-exec) | OUT (not in `all.toml`); names in `deferred.toml` |
| `../testlists/wrapper.toml` | `--dut smu_wrapper`: green `all` = elab+SMC; `sep_exec_blocked` holds `smu_sep_smoke` | Wrapper merge-gate; SEP exec not reportable |
| `cocotb/env/smu_fcov.py` | Python FCOV ledger hits | Active |
| Internal `oca_smu/.../smu_all_testplan.md` | Legacy full SMU universe | **External reference**; not OSS exit gate |

### 12.2 Phase / group rollup

| Phase / group | Count | VCS | Verilator | Notes |
|---------------|------:|-----|-----------|-------|
| P1 `phase1` | 24 | **24/24 PASS** | **24/24 PASS** | Density gate; smoke⊂top5⊂top10⊂phase1 |
| P2 `phase2_smc_dtp` | 15 | **15/15 PASS** | **15/15 PASS** | I1–I12 deepeners |
| P3 `phase3_corner` | 16 | **16/16 PASS** | **16/16 PASS** | H1–H6 corner + G4 |
| **P4 `phase4_sep0`** | **7** | **7/7 PASS** | **7/7 PASS** | Deepen + glue remainder |
| **`sep0_all`** | **55** | **55/55 PASS** | **55/55 PASS** | Canonical SEP=0 enrolled |
| **`sep0_p4_all`** | **62** | enrolled (not full run) | enrolled (not full run) | sep0_all + phase4_sep0 |
| `phase2` | 39 | PASS (subset of sep0) | PASS | phase1+phase2_smc_dtp |
| `phase3` | 31 | PASS | PASS (P2+P3) | phase2_smc_dtp+phase3_corner |
| `deferred` / Appendix A | ~107 unique names | N/A | N/A | SEP=1 / interop / toggle / CHILD — **OUT** |

### 12.3 Enrolled testcase matrix (`sep0_all`)

| Phase | ID | Test | Stream | Grade | VCS | Verilator |
|-------|----|------|--------|-------|-----|-----------|
| P1 | S1 | `smu_smc_smoke_test` | smc | G2+ | PASS | PASS |
| P1 | S2 | `smu_dtp_jtag_smoke_test` | dtp | G3 | PASS | PASS |
| P1 | S3 | `smu_no_sep_configuration_test` | smc | G3 | PASS | PASS |
| P1 | 2 | `smu_dft_dtp_boot_stall_test` | dtp | G3 | PASS | PASS |
| P1 | 3 | `smu_dtp_dtm_local_axi_test` | dtp | G3 | DEFERRED | DEFERRED |
| P1 | 4 | `smc_cpu_traffic_ext_axi_test` | fabric | G3 | DEFERRED | DEFERRED |
| P1 | 5 | `smu_axi_id_width_conversion_test` | fabric | G3 | PASS | PASS |
| P1 | 6 | `smu_axi_crossbar_error_handling_test` | fabric | G3 | PASS | PASS |
| P1 | 7 | `smu_jtag_reset_override_test` | dtp | G3 | PASS | PASS |
| P1 | 8 | `smu_cross_trigger_matrix_test` | dtp | G1/G2 | DEFERRED | DEFERRED |
| P1 | 9 | `smc_reset_ctrl_test` | smc | G3 | PASS | PASS |
| P1 | 10 | `smc_mailbox_int_test` | smc | G3 | DEFERRED | DEFERRED |
| P1 | 11 | `smu_dtp_otp_debug_access_test` | dtp | G2 | DEFERRED | DEFERRED |
| P1 | 12 | `smu_clock_stop_coordination_test` | dtp | G2 | PASS | PASS |
| P1 | 13 | `smu_lifecycle_debug_policy_test` | dtp | G2 | DEFERRED | DEFERRED |
| P1 | 14 | `smu_smc_dtp_jtag2axi_security_test` | dtp | G3 | DEFERRED | DEFERRED |
| P1 | 15 | `smu_dft_gpio_boot_stall_test` | dtp | G3 | PASS | PASS |
| P1 | 16 | `smc_gpio_strap_sanity_test` | smc | G3 | DEFERRED | DEFERRED |
| P1 | 17 | `smc_efuse_reg_sanity_test` | smc | G3 | DEFERRED | DEFERRED |
| P1 | 18 | `smc_wdt_sanity_test` | smc | G3 light | DEFERRED | DEFERRED |
| P1 | 19 | `smc_security_demote_pm_test` | smc | G2 | PASS | PASS |
| P1 | 20 | `smu_axi_external_port_connectivity_test` | fabric | G3 | PASS | PASS |
| P1 | 21 | `smu_smc_global_base_remap_test` | fabric | G3 | DEFERRED | DEFERRED |
| P1 | 22 | `smu_axi_atomic_operation_test` | fabric | G3 | PASS | PASS |
| P2 | I8a | `smu_dtp_csr_access_test` | dtp | G3 | DEFERRED | DEFERRED |
| P2 | I2a | `smu_dtp_otp_smc_complete_rw_test` | dtp | G3 | DEFERRED | DEFERRED |
| P2 | I6a | `smu_dtp_clock_stop_smc_cla_loop_test` | dtp | G3 | DEFERRED | DEFERRED |
| P2 | I7a | `smu_xtrig_ctm_four_phase_test` | dtp | G3 | DEFERRED | DEFERRED |
| P2 | I10a | `smu_sys_in_filter_program_jtag_test` | dtp | G3 | DEFERRED | DEFERRED |
| P2 | I1a | `smu_dtp_jtag2axi_smc_rw_matrix_test` | dtp | G3 | DEFERRED | DEFERRED |
| P2 | I1b | `smu_dtp_jtag2axi_smc_error_path_test` | dtp | G3 | DEFERRED | DEFERRED |
| P2 | I2b | `smu_dtp_otp_sep0_err_slv_test` | dtp | G3 | DEFERRED | DEFERRED |
| P2 | I3a | `smu_boot_stall_jtag_cold_reset_matrix_test` | dtp | G3 | PASS | PASS |
| P2 | I5a | `smu_ic_reset_smc_multi_domain_test` | dtp | G3 | PASS | PASS |
| P2 | I7b | `smu_dtp_xtrigger_smc_cla_test` | dtp | G3 | DEFERRED | DEFERRED |
| P2 | I8b | `smu_fabric_smc_dtp_cross_domain_test` | dtp | G3 | DEFERRED | DEFERRED |
| P2 | I9a | `smu_dtp_feat_ctrl_gate_matrix_test` | dtp | G3 | DEFERRED | DEFERRED |
| P2 | I11a | `smc_wdt_timeout_irq_test` | smc | G3 | DEFERRED | DEFERRED |
| P2 | I11b | `smc_reset_unit_wdt_scratch_test` | smc | G3 | DEFERRED | DEFERRED |
| P3 | H2b | `smu_sys_in_filter_window_edge_test` | dtp | G3 | DEFERRED | DEFERRED |
| P3 | H2c | `smu_sys_in_filter_reprogram_shrink_test` | dtp | G3 | DEFERRED | DEFERRED |
| P3 | H2a | `smu_dtp_jtag2axi_wstrb_partial_sticky_test` | dtp | G3 | DEFERRED | DEFERRED |
| P3 | H1b | `smu_dtp_jtag2axi_back_to_back_error_ok_test` | dtp | G3 | DEFERRED | DEFERRED |
| P3 | H4b | `smu_feat_ctrl_partial_bit_corner_test` | dtp | G3 | DEFERRED | DEFERRED |
| P3 | H5a | `smu_ic_reset_dual_domain_illegal_test` | dtp | G3 | PASS | PASS |
| P3 | H5b | `smu_boot_stall_vs_ic_reset_priority_test` | dtp | G3 | PASS | PASS |
| P3 | H1c | `smu_xtrig_ctm_illegal_phase_test` | dtp | G3 | DEFERRED | DEFERRED |
| P3 | H6a | `smu_cla_and_xtrig_concurrent_test` | dtp | G3 | DEFERRED | DEFERRED |
| P3 | H6b | `smu_clock_stop_jtag_vs_cla_fb_race_test` | dtp | G3 | DEFERRED | DEFERRED |
| P3 | H5c | `smc_wdt_scratch_double_pulse_test` | smc | G3 | DEFERRED | DEFERRED |
| P3 | H1a | `smu_dtp_jtag2axi_abort_mid_op_test` | dtp | G3 | DEFERRED | DEFERRED |
| P3 | H4a | `smu_feat_ctrl_flip_mid_jtag2axi_test` | dtp | G3 | DEFERRED | DEFERRED |
| P3 | H3a | `smu_jtag2axi_vs_smn_same_csr_race_test` | dtp | G4 | DEFERRED | DEFERRED |
| P3 | H3b | `smu_otp_vs_fabric_map_race_test` | dtp | G4 | DEFERRED | DEFERRED |
| P3 | H3c | `smu_hier_ctn_vs_jtag2axi_concurrent_test` | dtp | G4 | DEFERRED | DEFERRED |
| P4 | D1 | `smc_efuse_secure_tm_force_test` | smc | G3 | DEFERRED | DEFERRED |
| P4 | D2 | `smc_wdt_ip0_isolate_clamp_test` | smc | G3 | DEFERRED | DEFERRED |
| P4 | G1 | `smu_macro_axil_pll_pvt_route_test` | smc | G3 | DEFERRED | DEFERRED |
| P4 | G2 | `smu_octs_timer_count_csr_test` | smc | G3 | DEFERRED | DEFERRED |
| P4 | G3 | `smu_ic_reset_ss_domain_matrix_test` | dtp | G3 | PASS | PASS |
| P4 | G4 | `smu_dtp_bsr_extest_loopback_test` | dtp | G2 | PASS | PASS |
| P4 | G5 | `smu_telemetry_atb_handshake_test` | smc | G2+ | DEFERRED | DEFERRED |

**Totals (current, 2026-07-29i):** `sep0_all` **19** · `phase4_sep0` **2** ·
`sep0_p4_all` **19**. Historical Force-era 55/62 rollup is **superseded**.

### 12.4 OUT / deferred (not enrolled — do not promote into SEP=0)

| Category | Examples | Count (approx) |
|----------|----------|----------------|
| SEP=1 under SMU | `smu_sep_*`, programmable xbar | see `deferred.toml` / §A.1 |
| SMC/SEP interop | `smc_sep_*`, `smu_bidirect_*`, fuse-sense, SPI bridge | §A.2 |
| Fabric SEP=1 / stress | `smu_axi_xbar_{address_decode,connectivity_matrix,...}` | §A.3 |
| Toggle / wrapper | `smu_wrapper_*_toggle_*`, signal_path, JTAG2AXI signal toggle | §A.4 |
| Child / FW depth | ROM scratch / CPU bring-up, `smc_cpu_sanity`, PLIC, I2C/GPIO mux | §A.5 / CHILD |
| Glue still OUT | cool pin, memrepair sticky, `ss_reset_complete`, dual OCTS, ext IRQ, trace | P4 remainder |
| Security E2E #3538 | Real LCC → feat_ctrl → gated txn | OUT (`needs_real_lcc`; Force matrix **removed**) |
| Force / hier / CTM inject | WDT Force, secure_tm Force, feat_ctrl Force, CTM/CLA Force | `needs_real_lcc` / `needs_real_stimulus` |

### 12.5 Honest caveats (policy 2026-07-29)

- No DUT Force / no TB placeholder — see `testlists/deferred.toml`.
- I2b / I11b / P4 secure_tm / P4 WDT clamp / CTM Force suite: **deferred** (raise stubs).
- `smc_security_demote_pm_test`: observe-only demote + default lc_state (Force sigint inject deferred).
- P4 EXTEST: TB scan loopback + one-hot decode — **not** functional pad BSR / SEP STAP.
- Skill-1: `SMU_FEATURE_LIST.md` designer approval still **pending**.

---

## 13. Result reporting

Rules for every reported SMU DV result. The content of a pass claim is the
**scenario exercised** and the **failures the checks would detect** — run
metadata (command, seed, run dir) exists so anyone can reproduce and audit
that claim.

**Scenario exercised.** State what stimulus actually ran: configuration,
sequence, and corner (e.g. "programs the SYS_IN filter window to the
aperture edge, then reprograms it smaller mid-traffic"), not just the test
name. The per-test pass contracts (§6.2, §7.3) and FCOV bins are the
reference vocabulary.

**Failures detected.** State what fault would have flipped the result to
FAIL ("would fail if the filter kept blocking after reprogramming"), and
note known non-detections where they matter. Named scoreboard checks carry
this: `SmuScoreboard.checks > 0` is mandatory, a wrong expected value must
FAIL, and each check logs a token (log line format `EVIDENCE: <TOKEN>`,
mapped in `SMU_FEATURE_LIST.md`). Check grades (§1) rank detection
strength; toggle-only observation is never a pass criterion.

**Sources.** Reportable passing results come only from
`../testlists/all.toml` (+`smc/dtp/fabric.toml`, `--dut smu`) and
`../testlists/wrapper.toml` (`--dut smu_wrapper`). Names in
`../testlists/deferred.toml` are **never** reported as passing; their
`BLOCKER:`/`PLANNED:` reasons live in that file's section banners
(currently: SEP console-path stall in `sep_system_peripherals`; SEP mailbox
demux/select mapping; BLOCKED RTL IF-XT-04 / IF-RST-04, §4). Legacy
internal YAMLs under `dv/smu/tb/tb_uvm/yaml/` are reference-only.
Deferred → enrolled promotion requires a §12 ledger update in the same
change.

**Configuration.** Classify each result as exactly one of **no-SEP**
(`--dut smu`, or wrapper `no_sep` target/run mode), **SEP BFM** (TB-modeled
SEP behavior; `modeled` tag), or **real SEP RTL** (wrapper `sep_rtl` target;
`real_rtl` tag). The same test name is a different claim in each.

**Reproduce metadata.** Quote the exact `run_dv.py` command: items,
`--stage` sequence, compile target (`smu_wrapper`:
`compile_smu_chiplet_no_sep` / `compile_smu_chiplet_sep_rtl`; bare `smu`:
single SEP=0 build), waves flag, and firmware/preload artifacts (declared
per test in the testlist; staged into the attempt dir). Group runs
randomize the seed per leaf (`--seed` rejected; `--reseed N` for sweeps);
single-test reproduce is `--items <test> --stage sim --seed <N>`. Runs land
in `../build/runs/<ts>__<tool>__<item>/`; per leaf
`<test>/seed_<N>/attempt_<K>/` holds `logs/<test>.log` (scoreboard
`CHECK PASS/FAIL`, check-token, and `FCOV hits:` lines), `result.json`,
`results/results.xml`, staged `*.hex`, and the exact rerun script under
`scripts/`. Quote the repo-relative run dir for every claim.

**Traceability.** Each reported result cites test name → testlist file +
group → VPLAN row (§12.3 ID or §4 `IF-*`).

---

## Appendix A — OUT / deferred universe (reference only)

Not part of P1–P4 exit. Names retained for later programs / `deferred.toml`.
**Commercial sync (2026-07-23):** inventory aligned to
`oca_smu/dv/smu/tb` (`testlist_smu_chiplet.yaml`, `SMU_INTEROP_VPLAN.md`,
`SMU_DV_CLEANUP_PLAN.md` §27). Catalog groups:
`testlists/sep.toml`, `testlists/interop.toml` (not in `all.toml`).
**Legacy tree sync (2026-07-28):** `os_oca/dv/smu/tb` Jul mid adds audited —
bodies **not** enrolled; names + disposition in **§A.7** / `deferred.toml`.

### A.0 Commercial gate mapping (oca_smu → OSS)

| Commercial regression | Intent | OSS home |
|----------------------|--------|----------|
| `SMU_Dev_with_SEP_Regression` | Probe / connectivity; **no** SEP CPU exec | `sep.toml` → `sep_probe`; `deferred.toml` tag `sep_probe` |
| `Manual_SMU_Blocked_SEP_Exec_Regression` | Needs real SEP fetch/retire | `sep.toml` → `sep_exec_blocked`; wrapper `sep_exec_blocked` |
| `SMU_Dev_without_SEP` / nightly | SEP=0 green | `all.toml` `sep0_*` (already enrolled) |

**#3582 blocker (shared):** `mpc_reset_run_req` invert + `dbg_rstb→powergood_stable`
landed; CLA fw half is `{1,4}` (not `{1,2,4}`). **Residual:** SEP CPU can be
fully released (`mpc_reset_run=1`, clocks, resets) yet **IFU never asserts
boot-ROM req** (`boot_rom_reqs=0`, `halt=X`, `pc=0`). OSS
`--dut smu_wrapper` `smu_sep_smoke_test` reproduces this (2026-07-23).

**OSS wrapper merge-gate:** `wrapper.toml` `all` / `smoke` = elaboration +
`smu_smc_smoke` only. `smu_sep_smoke_test` is **quarantined** under
`sep_exec_blocked` / `all_with_sep_exec` — not reportable as PASS (§13).

### A.1 SMU-level SEP — blocked execution (`blocked_sep_exec`)

Needs `compile_smu_chiplet_sep_rtl` **and** first-instruction retire:

`smu_sep_smoke_test`, `smu_sep_sanity_test`, `smu_sep_spi_test`,
`smu_sep_modules_test`, `smu_sep_dma_test`, `smu_sep_efuse_test`,
`smu_sep_wdt(_strict)_test`, `smu_sep_aes(_strict)_test`,
`smu_sep_otbn(_strict)_test`,
`smu_cla_sep_cpu_debug_control_test` (**new**, SEP_SMU_022 CLA action map).

### A.1b SMU-level SEP — probe / connectivity (`sep_probe`)

Commercial green SEP gate (no retire required). Catalogued for OSS handoff;
**not** enrolled until wrapper scoreboards exist:

`smu_sep_smc_xbar_programmable_addr_test`, `smu_sep_wdt_reset_to_smc_test`,
`smu_sep_spi_bridge_test`, `smu_sep_axi_extension_decode_test`,
`smu_sep_external_irq_test`, `smu_sep_alias_mailbox_interrupt_probe_test`,
`smu_sep_ext_axi_combined_probe_test`, `smu_sep_km_otbn_memory_test`,
`smu_sep_debug_bus_test`, `smu_fuse_sense_handshake_test`,
`smu_lifecycle_security_handoff_test`, `smu_feat_ctrl_monitor_test`,
`smu_sep_filter_{rule_matrix,skip_wire}_test`,
`smu_sep_ap_stee_{output_remap,remap_region_matrix}_test`,
`smu_sep_outbound_demux_{decode,full_decode}_test`,
`smu_sep_smc_{alias_remap_consistency,egress_unfiltered,addr_route_bug}_test`,
`smu_sep_spi_mux_ctrl_wire_test`, `smu_sep_wdt_cdc_path_test`,
`smu_ic_reset_sep_ext_slice_test`, `smu_sep_memory_integrity_test`,
`smu_sep_otbn_execute_flow_probe_test`,
`smu_sep_interrupt_error_recovery_matrix_test`.

### A.2 SMC/SEP interop

**Real (blocked_sep_exec):** `smc_sep_interoperability(_strict)_test`,
`smc_sep_xbar(_strict)_test`, `smu_bidirect(_strict)_test`,
`smu_smc_stall_sep_test` (**updated**, SEP_SMU_004 CLA stall/release handshake).

**Modeled BFM:** `smc_sep_{interaction,multi_cmd,service_req,error_recovery,
seq_validation,notification,fw_request,bidirectional}_test`.

**Other:** `smu_interop_negative_recovery_test`,
`smu_interop_functional_coverage_bins_test`,
`smu_dtp_sep_debug_enhanced_test`, `smu_dtp_sep_stap_reset_smoke_test`,
`smu_dtp_sep_ic_reset_hold_test` (legacy P3; SEP=1).

### A.3 Fabric SEP=1

`smu_axi_xbar_connectivity_matrix_test`, `smu_axi_xbar_address_decode_test`,
performance / structure / ID stress beyond SEP=0 slice.

### A.4 Toggle / wrapper coverage (commercial)

`smu_wrapper_*_toggle_test`, `smu_u_smc_interface_toggle_test`,
`smu_signal_path_verification_test`, `smu_dtp_jtag2axi_signal_toggle_test`,
`smu_wrapper_pin_matrix` (helper; toggle-as-pass **OUT**).

### A.5 Child / dual reference

SMC dual_* / master-BFM references — not SMU signoff.

### A.6 OCAC mapping (reportable, not compliance claim)

| Domain | Anchor (P1/P2 or OUT) |
|--------|------------------------|
| Foundations / Boot | smoke, no_sep; SEP smoke = OUT (`sep_exec_blocked`) |
| Debug / DTP | jtag, stall, OTP, JTAG2AXI, P2 deepeners |
| Addressing | fabric SEP=0 slice; 3×3 = OUT |
| Security | demote, lifecycle; #3538 E2E = OUT |
| Protocols | xtrig P1/P2; OCTS dual = OUT |
| SEP CLA / interop | OUT until #3582 IFU fix (`stall_sep`, `cla_sep_cpu_debug`) |

### A.7 Legacy `os_oca/dv/smu/tb` Jul-2026 adds (catalog only)

Source: `os_oca` commits around `#3909` / `#3926` / `#3966` / `#3971` /
`#3973` and P3 expand `e84dfe55d` (`smu_p3_feature_list.md` /
`smu_all_testplan.md`). **Do not enroll** into `all.toml` / `sep0_*`.
Disposition:

| Legacy name | OSS disposition | Enrolled near-relative (if any) |
|-------------|-----------------|----------------------------------|
| `smu_ctm_channel_matrix_test` | **superseded** | `smu_cross_trigger_matrix_test`, `smu_xtrig_ctm_four_phase_test`, `smu_xtrig_ctm_illegal_phase_test` |
| `smu_dtp_feat_ctrl_gated_jtag2axi_test` | **superseded** | `smu_dtp_feat_ctrl_gate_matrix_test`, `smu_feat_ctrl_*` |
| `smu_dtp_feat_ctrl_gated_stap_test` | **superseded** / SEP=1 STAP | gate_matrix (J2A); STAP remains OUT |
| `smc_efuse_secure_tm_test` | **superseded** | `smc_efuse_secure_tm_force_test` (P4) |
| `smu_wrapper_pin_matrix` | **OUT** toggle | wrapper elab + `smu_smc_smoke` |
| `smu_dtp_dual_cpu_{bringup,jtag2axi}_test` | **blocked_sep_exec** | none (needs real SEP + pad TB) |
| `smu_dtp_jtag2axi_sep_otp_path_test` | **sep1** catalog | SEP=0 OTP: `smu_dtp_otp_*` / `smu_dtp_otp_sep0_err_slv_test` |
| `smu_dtp_ptap_otp_instr_scan_test` | **sep1** catalog | same |
| `smu_dtp_sep_ic_reset_hold_test` | **sep1** catalog | SEP=0 IC_RESET: `smu_ic_reset_*` |
| `smu_sep_smoke` / `smc_sep_{xbar,interoperability}` / `stall_sep` / `cla_sep_*` | already §A.1–A.2 | wrapper smoke skeleton only |

**P1–P4 / `sep0_all` testplan rows:** **no change** — Jul legacy adds do not
alter enrolled exit criteria.

---

## Document map

See **§12.1** for the full testplan/document inventory and status.
Satellite detail: `SMU_OSS_VPLAN_PHASE1.md`. Stubs redirect here:
`SMU_OSS_COMPLETE_TESTPLAN.md`, `SMU_OSS_VPLAN_P1_P2.md`.

---

## Revision History

| Version | Date | Description |
|---------|------|-------------|
| 1.0 | 2026-07-07 | Initial universe catalog (SMC/SEP/DTP/interop/fabric streams) |
| 1.1 | 2026-07-14 | Mark as catalog; point executable Phase-1 to PHASE1 doc |
| 2.0 | 2026-07-15 | Consolidate P1/P2 master plan here; scope lock (no P3/P4) |
| 2.1 | 2026-07-15 | P2-I8a `smu_dtp_csr_access_test` VCS PASS: local-xbar hole + hier CTN CSR |
| 2.2 | 2026-07-15 | P2-I2a `smu_dtp_otp_smc_complete_rw_test`: OTP map abs R/W + shadow + gated |
| 2.3 | 2026-07-15 | P2-I6a `smu_dtp_clock_stop_smc_cla_loop_test`: CLA fb→req[0]→stop/TDR |
| 2.4 | 2026-07-15 | P2-I7a `smu_xtrig_ctm_four_phase_test`: dest/src 4-phase + SMC[1:0] |
| 2.5 | 2026-07-15 | P2-I10a `smu_sys_in_filter_program_jtag_test`: SMN DECERR→OKAY window |
| 2.6 | 2026-07-15 | P2-I1a `smu_dtp_jtag2axi_smc_rw_matrix_test`: SIZE/WSTRB + sticky |
| 2.7 | 2026-07-15 | P2-I1b `smu_dtp_jtag2axi_smc_error_path_test`: DECERR+poison+recovery |
| 2.8 | 2026-07-15 | aidv harden: deny `expect_j2a_payload_denied`, `require_complete`, I9a OTP shadow, FCOV OPEN, groups |
| 2.9 | 2026-07-15 | Skill-1 `SMU_FEATURE_LIST.md`; FCOV v1.1 + `smu_fcov.py`; scoreboard `EVIDENCE:` tokens |
| 2.10 | 2026-07-15 | Verilator bring-up: exclude sep×sim tech/SPI; prim_assert + SMC stubs; scoped `smu_public_scope.vlt` + packed feat_ctrl Force |
| 2.11 | 2026-07-15 | Verilator `phase2_smc_dtp` **15/15 PASS**: feat_ctrl Force-shadow RMW, packed AXIL/IC_RESET helpers, `.vlt` forceable, stub WDT warm pulse |
| 2.12 | 2026-07-15 | P3 corner plan (§7): H1–H6 ~14 G3/G4 tests; SEP=0 only; SEP=1/BLOCKED still OUT |
| 2.13 | 2026-07-15 | P3 H2 **3/3 VCS PASS**: filter window edge/shrink, WSTRB neighbor; `phase3_corner` group |
| 2.14 | 2026-07-15 | P3 H1b + H4b **VCS PASS**: b2b DECERR→OK; incomplete feat_ctrl OTP deny; `phase3_corner` =5 |
| 2.15 | 2026-07-15 | P3 H5a/H5b **VCS PASS**: dual IC_RESET pack; stall sticky vs IC_RESET + TRST; `phase3_corner` =7 |
| 2.16 | 2026-07-15 | Clean old `out/`/runs (~70G); P3 H1c+H6a/b **VCS PASS**; `phase3_corner` =10 |
| 2.17 | 2026-07-16 | P3 H5c+H1a+H4a **VCS PASS**: WDT double pulse; abort mid-op; feat_ctrl mid-BUSY+TRST; `phase3_corner` =13 |
| 2.18 | 2026-07-16 | P3 H3a/b/c **VCS PASS** (G4): J2A∥SMN; OTP∥fabric MAP; CTN∥JTAG2AXI; **P3 16/16** |
| 2.19 | 2026-07-17 | P3 Verilator parity **16/16 PASS**; P3 closed on VCS+Verilator |
| 2.20 | 2026-07-17 | SEP=0 hygiene: `sep0_all` (55); FCOV v1.2; FEATURE_LIST v0.2 P3 CHKs; exit gate |
| 2.21 | 2026-07-17 | VCS `sep0_all` **55/55 PASS** (~671s); SEP=0 program closed on signoff gate |
| 2.23 | 2026-07-17 | Verilator P1 parity + `sep0_all` **55/55**; stub STRAPS AXI; gpio_boot_stall_drive_i; lc Force |
| 2.24 | 2026-07-19 | §13 result-reporting policy (scenario exercised + failures detected + config classes + reproduce metadata); `deferred.toml` blocker banners (SEP console path, mailbox demux, IF-XT-04/IF-RST-04); DV-friendly terminology sweep (check grades, check tokens) |
| 2.25 | 2026-07-20 | P4-SEP0 (`phase4_sep0` 7): secure_tm Force, WDT clamp, macro AXIL, OCTS, SS IC_RESET, EXTEST, ATB; VCS+VL **7/7**; FCOV v1.3 |
| 2.26 | 2026-07-20 | P4 honesty: secure_tm→blocked_o; WDT isolate/raw clamp↔passthru contrast (TB Force gen_4core); OCTS CSR-required; EXTEST one-hot; IF-SMC-11; sep0_p4_all not full signoff; VCS+VL **7/7** |
| 2.27 | 2026-07-23 | Sync SEP/interop catalog from `oca_smu/dv/smu/tb`: Appendix A.0–A.2 (probe vs `#3582` blocked-exec); `deferred.toml` + `sep.toml`/`interop.toml` groups; wrapper `all` drops `smu_sep_smoke` → `sep_exec_blocked`; add CLA/stall/filter/ap_stee/demux names |
| 2.28 | 2026-07-28 | Audit `os_oca/dv/smu/tb` Jul adds vs OSS: **no enrolled body migrate**; Appendix **A.7** disposition table; `deferred.toml` catalog names; deferred count ~107 unique; P1–P4/`sep0_all` unchanged |
