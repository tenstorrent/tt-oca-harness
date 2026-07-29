<!-- SPDX-License-Identifier: Apache-2.0 -->
# OSS SMU Verification Plan

> **Canonical OSS SMU VPLAN** (this file). Bridges the legacy SMU DV tree
> (`dv/smu/tb/`) and the OCAH open-source TB (`hw/sys/smu/dv/`).
>
> - **Master P1+P2 plan:** `hw/sys/smu/dv/docs/SMU_VPLAN.md`
> - **Executable Phase-1 contract:** `SEP=0` density (**24** tests) — DONE VCS
> - **SEP=1 / interop catalog (2026-07-23):** synced from commercial
>   `oca_smu/dv/smu/tb` — probe vs `#3582` blocked-exec gates; see
>   `SMU_VPLAN.md` Appendix A.0 and `testlists/{sep,interop,deferred,wrapper}.toml`
> - **Implementation tree:** `hw/sys/smu/dv/`
> - **Runner:** `python3 tools/dv/run_dv.py --dut smu`
> - **Primary sim (bring-up):** VCS first; Verilator only after Phase-1 VCS green.
> - **Hard rule:** every PASS requires positive scoreboard evidence (no vacuous PASS).

| Field | Value |
|-------|-------|
| DUT | `smu` / `smu_wrapper` with **`SEP=0`** (Phase-1) |
| TB top | `hw/sys/smu/dv/tb/tb_top.sv` (`smu_uvm_top`) |
| Framework | cocotb + PyUVM (`env/` + `seq_lib/` + `tests/`) |
| Sim cfg | `hw/sys/smu/dv/smu_sim_cfg.toml` |
| Master P1/P2 VPLAN | `hw/sys/smu/dv/docs/SMU_VPLAN.md` |
| Phase-1 executable detail | `hw/sys/smu/dv/docs/SMU_OSS_VPLAN_PHASE1.md` |
| OUT / deferred | `testlists/deferred.toml` (+ `SMU_VPLAN.md` Appendix A) |
| FCOV | `hw/sys/smu/dv/docs/SMU_FCOV.md` |
| Legacy reference | `dv/smu/tb/doc/{smu_vplan,smu_all_testplan,SMU_INTEROP_*}.md` |
| Child TBs | OSS SMC (`--dut smc_wrapper`), OSS DTP (`--dut dtp`), OSS SEP (`--dut sep`) |

---

## 1. Goals

1. Prove SMU wrapper bring-up **without real SEP RTL** (`SEP=0`): SMC reset/boot
   observables, DTP/JTAG TAP, external SMN fabric path, no-SEP SEP-OTP err-slv.
2. Compress the legacy SMU universe (~224 named tests / ~109 OSS inventory
   entries) into a **lean Phase-1 regression (24 tests)** with the same
   SEP=0-reachable FCOV intent.
3. Keep SEP=1 / real SMC↔SEP interop / 3×3 `smu_axi_xbar` matrix **out of
   Phase-1** (colleague track → `deferred.toml`).
4. Enforce **real checkers**: `SmuScoreboard` refuses zero checks; parsers
   require positive cocotb evidence (`results.xml` + no hard-fail).

---

## 2. Hard rules

| Rule | Consequence |
|------|-------------|
| `SEP=0` only (Phase-1) | No real SEP CPU, no mailbox C/R with real SEP, no 3×3 xbar matrix |
| PyUVM-on-cocotb | No SV UVM test-class ports in the OSS TB |
| Density-first | Prefer supersets; one representative per coverage domain |
| No vacuous PASS | Scoreboard `checks > 0`; wrong expected must FAIL |
| VCS before Verilator | Land Phase-1 green on VCS; Verilator is a follow-on backend |
| Child-TB depth stays downstream | I2C/SMBus matrices → OSS SMC; crypto KAT → OSS SEP |
| ASCII in test docstrings/logs | Unicode in pyuvm descriptions can trigger parser hard-fail on Traceback |
| Scratch under `/localdev` | `export TMPDIR=/localdev/$USER/TMPDIR` — never `/tmp` |

---

## 3. Architecture (SEP=0)

```
                    jtag_* (OcahJtagTap)
                         |
                         v
   s_axi_*  --->  smu #(.SEP(0))  --->  smu_axi_out (TB RAM)
   (SMN in)           |
                      +-- SMC (real RTL)
                      +-- DTP (real RTL)
                      +-- gen_no_sep: iw_converter SMN<->SYS_IN
                      +-- sep_* aperture tie-off (== 0)
                      +-- SEP-OTP AXI-Lite -> DECERR err_slv
```

### Critical path facts (affect checkers)

| Fact | Implication for tests |
|------|------------------------|
| Under `SEP=0`, SMN `smu_axi_in` feeds SMC **`sys_axi_in`** via ID-width converter (8→6), **not** SEP_IN | CSR frontdoor at `0xC000_xxxx` goes through the **SYS_IN inbound filter** |
| SYS_IN `axi_filter_wrap` has **`BlockByDefault=1`** | Unprogrammed filter → **DECERR** + `axi_err_slv` poison `0xBADCAB1E` (low 32b of `64'hCA11AB1EBADCAB1E`) |
| OSS SMC CSR smoke uses **SEP_IN** (`s_axi` on SMC TB), which **bypasses** that filter | Do **not** expect `VERSION_LO==0x000100A0` via SMU SMN until filter is programmed or JTAG2AXI is used |
| Real `smc_reset_ctrl` needs ≥32-cycle cold deglitch + **255-cycle** extender on `clk_ref` | Bring-up must wait on `rst_cold_stable_ref_clk_no` / `rst_primary_smc_clk_no` |
| Use `+skip_fuse_sense` for Phase-1 smoke/fabric | Fuse-sense FSM skipped; `fuse_sense_done_o` rises without OTP preload |

### Reset / aperture observables (TB top)

| Port | Reset / SEP=0 expectation |
|------|---------------------------|
| `rst_cold_stable_ref_clk_no` | 1 after bring-up |
| `rst_primary_ref_clk_no` | 1 |
| `rst_primary_smc_clk_no` | 1 |
| `rst_primary_periph_clk_no` | 1 |
| `sep_global_base_o` / `sep_region_size_o` | 0 / 0 |
| `smc_global_base_o` | `0x4000_0000` (CSR reset default) |
| `smc_region_size_o` | `0x0100_0000` |
| `fuse_sense_done_o` | 1 with `+skip_fuse_sense` |

---

## 4. Coverage universe (Phase-1 slice)

### Blocks

- **SMC:** reset, mailbox (local), GPIO strap, eFuse reg, WDT, demote/PM, no-SEP config
- **DTP:** JTAG IDCODE/BYPASS, boot-stall, JTAG2AXI, OTP-over-JTAG, IC_RESET, clock-stop, xtrig
- **Fabric (SEP=0):** SMN port, ID-width converter, filter DECERR, ATOP non-support, global-base remap
- **No-SEP tie-off:** SEP aperture 0, SEP-OTP AXI-Lite err-slv

### FCOV bins Phase-1 must hit

| FCOV | Phase-1 expectation |
|------|---------------------|
| `smc_boot_cg` | Reset release + aperture defaults + SMN path live (filter DECERR is valid evidence until filter programmed) |
| `sep_boot_cg` | **`SEP=0` bin only** |
| `mailbox_interop_cg` | SMC-local mailbox / IRQ (no real SEP peer) |
| `xbar_route_cg` | SMC↔ext ID path + DECERR + ATOP reject; **not** full 3×3 matrix |
| `reg_access_cg` | JTAG2AXI / OTP-over-JTAG (when implemented) |
| `reset_clock_cg` | Cold / powergood / IC_RESET |
| `fuse_lifecycle_cg` | eFuse + lifecycle/debug / demote representative |
| `dtp_debug_cg` | Boot-stall, clock-stop, IC_RESET, JTAG2AXI |
| `xtrig_cg` | CTM / CLA representative |
| `interop_bins_cg` | **Deferred** (SEP=1) |

### Explicitly out of Phase-1

- All `smu_sep_*`, `smc_sep_*`, `smu_bidirect*`, real interop probes
- `smu_axi_xbar_connectivity_matrix_test` and other `SEP=1`-only fabric
- Wrapper toggle / signal-path coverage sweeps
- Modeled SEP-facing BFM protocol suites (use OSS SEP TB)
- Multicore / PLIC / GPIO mux depth (promote only if smoke gaps appear)

---

## 5. Selection — Smoke ⊂ TOP-5 ⊂ TOP-10 ⊂ Phase-1 (24)

### TIER 0 — Smoke (3) — MR gate

| # | OSS test | Real checker contract (must FAIL if wrong) | Status |
|---|----------|--------------------------------------------|--------|
| S1 | `smu_smc_smoke_test` | Reset high; `smc_global_base_o==0x40000000`; `smc_region_size_o==0x1000000`; `fuse_sense_done_o==1`; SMN read `0xC000_2900` → **DECERR** (filter BlockByDefault) | **VCS PASS** |
| S2 | `smu_dtp_jtag_smoke_test` | IDCODE == `0x00000001`; IDCODE lsb==1; BYPASS 1-TCK delay | **VCS PASS** |
| S3 | `smu_no_sep_configuration_test` | `sep_global_base_o==0`; `sep_region_size_o==0`; cold/primary reset high | **VCS PASS** |

### TIER 1 — TOP-5

| # | OSS test | Why / checker intent | Status |
|---|----------|----------------------|--------|
| 1 | `smu_smc_smoke_test` | Widest SMC bring-up under wrapper | **VCS PASS** |
| 2 | `smu_dft_dtp_boot_stall_test` | DTP→SMC boot-stall assert/release | **VCS PASS** |
| 3 | `smu_dtp_dtm_local_axi_test` | JTAG2AXI → SMC fabric (OKAY CSR after path open) | **VCS PASS** |
| 4 | `smc_cpu_traffic_ext_axi_test` | External SMN / CPU→ext path | **VCS PASS** |
| 5 | `smu_axi_id_width_conversion_test` | SMN→iw_converter→filter: completing DECERR + poison | **VCS PASS** |

### TIER 2 — TOP-10 (= TOP-5 + 5)

| # | OSS test | Adds | Status |
|---|----------|------|--------|
| 6 | `smu_axi_crossbar_error_handling_test` | Multi-addr DECERR + stable re-read | **VCS PASS** |
| 7 | `smu_jtag_reset_override_test` | IC_RESET 139-bit EXT/SMC cold override + clear | **VCS PASS** |
| 8 | `smu_cross_trigger_matrix_test` | TB↔DTP[9:2] remap + DTP_CTRL abs DECERR | **VCS PASS** |
| 9 | `smc_reset_ctrl_test` | Cold/primary/periph reset release + hold | **VCS PASS** |
| 10 | `smc_mailbox_int_test` | Mailbox data + IRQ | **VCS PASS** |

### TIER 3 — Phase-1 close (24 unique)

| # | OSS test | Stream | Checker intent (summary) | Status |
|---|----------|--------|--------------------------|--------|
| 11 | `smu_dtp_otp_debug_access_test` | dtp | OTP CAPS + gated idle vs ungated BUSY | **VCS PASS** |
| 12 | `smu_clock_stop_coordination_test` | dtp | DEBUG_CONTROL stop_clks + xtrig remap | **VCS PASS** |
| 13 | `smu_lifecycle_debug_policy_test` | dtp | lc_state=0xf0 + feat_ctrl ungating | **VCS PASS** |
| 14 | `smu_smc_dtp_jtag2axi_security_test` | dtp | JTAG2AXI gated deny/allow | **VCS PASS** |
| 15 | `smu_dft_gpio_boot_stall_test` | dtp | GPIO strap boot-stall | **VCS PASS** |
| 16 | `smc_gpio_strap_sanity_test` | smc | captured_straps → STRAPS_LO/HI | **VCS PASS** |
| 17 | `smc_efuse_reg_sanity_test` | smc | EFUSE_MAP + INTERFACE_CTRL | **VCS PASS** |
| 18 | `smc_wdt_sanity_test` | smc | Magic unlock + CMP program | **VCS PASS** |
| 19 | `smc_security_demote_pm_test` | smc | Demote tie-off + lc_sigint | **VCS PASS** |
| 20 | `smu_axi_external_port_connectivity_test` | fabric | SMN handshake + AW activity counter | **VCS PASS** |
| 21 | `smu_smc_global_base_remap_test` | fabric | Programmable remap | **VCS PASS** |
| 22 | `smu_axi_atomic_operation_test` | fabric | Non-ATOP path completes (ATOPs unsupported) | **VCS PASS** |
| S2 | `smu_dtp_jtag_smoke_test` | dtp | TAP smoke | **VCS PASS** |
| S3 | `smu_no_sep_configuration_test` | smc | SEP=0 signature | **VCS PASS** |

> Executable Phase-1 = TOP-10 (1–10) + (11–22) + smoke extras {S2, S3} = **24**
> unique tests. **Implemented on VCS with real checkers: 24 / 24** (2026-07-14).

---

## 6. FCOV → test traceability

| FCOV | Primary Phase-1 tests |
|------|------------------------|
| `smc_boot_cg` | `smu_smc_smoke_test`, `smc_reset_ctrl_test` |
| `sep_boot_cg` (SEP=0) | `smu_no_sep_configuration_test` |
| `mailbox_interop_cg` (SMC-local) | `smc_mailbox_int_test` |
| `xbar_route_cg` (SEP=0 slice) | `smc_cpu_traffic_ext_axi_test`, `smu_axi_id_width_conversion_test`, `smu_axi_crossbar_error_handling_test`, `smu_axi_atomic_operation_test`, `smu_axi_external_port_connectivity_test`, `smu_smc_global_base_remap_test` |
| `reg_access_cg` | `smu_dtp_dtm_local_axi_test`, `smu_dtp_otp_debug_access_test` |
| `reset_clock_cg` | `smc_reset_ctrl_test`, `smu_jtag_reset_override_test` |
| `fuse_lifecycle_cg` | `smc_efuse_reg_sanity_test`, `smu_lifecycle_debug_policy_test`, `smc_security_demote_pm_test` |
| `dtp_debug_cg` | `smu_dtp_jtag_smoke_test`, `smu_dft_dtp_boot_stall_test`, `smu_dft_gpio_boot_stall_test`, `smu_clock_stop_coordination_test`, `smu_smc_dtp_jtag2axi_security_test` |
| `xtrig_cg` | `smu_cross_trigger_matrix_test` |
| `interop_bins_cg` | *SEP=1 track* |

---

## 7. Test infrastructure

### Layout

```
hw/sys/smu/dv/
  tb/tb_top.sv                 # smu_uvm_top, SEP=0
  cocotb/env/                  # SmuEnv, SmuEnvCfg, SmuScoreboard, cocotb_compat
  cocotb/seq_lib/              # AXI helpers
  cocotb/tests/                # one module per testlist entry
  testlists/{smc,dtp,fabric,all,deferred}.toml
  smu_sim_cfg.toml
  docs/{SMU_OSS_VPLAN_PHASE1,SMU_VPLAN,SMU_FCOV,SMU_SPEC,...}.md
```

### Agents / VIPs

| Interface | VIP / model |
|-----------|-------------|
| Primary JTAG TAP | `ocah_jtag_vip.OcahJtagTap` |
| External SMN AXI4 | `cocotbext.axi.AxiMaster` on `s_axi_*` + TB outbound RAM |
| SMC CPU mem | `smc_cpu_mem_integration` (same as smc_wrapper / smu_wrapper) |
| Cross-trigger / iJTAG | OCAH-local BFM (later) |

### Scoreboard anti-vacuous contract

```text
SmuScoreboard:
  - expect_eq / expect_true increment checks
  - check_phase FAILS if checks == 0
  - check_phase FAILS if errors != 0
smu_base_test:
  - FAILS if run_scenario() did not complete
```

### Run modes / plusargs

| Run mode | Args |
|----------|------|
| `smoke` / `smc` / `dtp` / `fabric` | `+skip_fuse_sense` |

Defines: `SYNTHESIS`, `SIM` (efuse skip path).

---

## 8. Testlists and regression groups

| File | Role |
|------|------|
| `testlists/smc.toml` | Phase-1 SMC / no-SEP |
| `testlists/dtp.toml` | Phase-1 DTP |
| `testlists/fabric.toml` | Phase-1 SEP=0 fabric |
| `testlists/all.toml` | includes above + groups |
| `testlists/deferred.toml` | SEP=1 / interop / depth — **not** in default `all.toml` |

| Group | Contents |
|-------|----------|
| `smoke` | S1–S3 |
| `top5` | tests 1–5 |
| `top10` | tests 1–10 |
| `phase1` | all 24 |
| `smc` / `dtp` / `fabric` | per-stream subset |

---

## 9. Execution

```bash
cd /path/to/os_oca   # or tt-oca
source bin/setup_env.sh
export TMPDIR=/localdev/$USER/TMPDIR
mkdir -p "$TMPDIR"

# VCS first (Phase-1 bring-up)
python3 tools/dv/run_dv.py --dut smu --tool vcs --items smoke
python3 tools/dv/run_dv.py --dut smu --tool vcs --items top5
python3 tools/dv/run_dv.py --dut smu --tool vcs --items top10
python3 tools/dv/run_dv.py --dut smu --tool vcs --items phase1

# Verilator ONLY after Phase-1 is green on VCS
python3 tools/dv/run_dv.py --dut smu --tool verilator --items smoke

# Commercial coverage (signoff)
python3 tools/dv/run_dv.py --dut smu --items phase1 --tool xcelium --cov
```

| Cadence | Intent |
|---------|--------|
| Every MR | `--items smoke --tool vcs` |
| Daily | `--items top5 --tool vcs` |
| Weekly | `--items phase1 --tool vcs` |
| Signoff | `phase1` + commercial `--cov` + FCOV ledger green |
| OSS CI (later) | Verilator smoke/top5 after VCS parity |

---

## 10. Implemented checker detail (VCS green)

### `smu_no_sep_configuration_test`

| Check | Expected |
|-------|----------|
| `sep_global_base_o` | 0 |
| `sep_region_size_o` | 0 |
| `rst_cold_stable_ref_clk_no` | 1 |
| `rst_primary_smc_clk_no` | 1 |

### `smu_dtp_jtag_smoke_test`

| Check | Expected |
|-------|----------|
| IDCODE | `0x00000001` |
| IDCODE marker lsb | 1 |
| BYPASS captured | `(pattern & 0x7FFFFFFF) << 1` |

### `smu_smc_smoke_test`

| Check | Expected |
|-------|----------|
| Resets | cold/primary high |
| `smc_global_base_o` | `0x40000000` |
| `smc_region_size_o` | `0x01000000` |
| `fuse_sense_done_o` | 1 |
| SMN read `0xC000_2900` | **DECERR** (not VERSION_LO OKAY) |

### Fabric / reset (also VCS green)

| Test | Key checks |
|------|------------|
| `smu_axi_id_width_conversion_test` | Multiple aligned local-alias addrs → DECERR + `0xBADCAB1E` |
| `smu_axi_crossbar_error_handling_test` | Multi-addr DECERR; stable re-read |
| `smu_axi_external_port_connectivity_test` | Read DECERR; write advances `smu_axi_in_awvalid_count` |
| `smu_axi_atomic_operation_test` | Non-ATOP read completes with DECERR |
| `smc_reset_ctrl_test` | Cold/primary/periph high; hold after 100 ref cycles |

---

## 11. Deferred ownership (SEP=1 track)

| Bucket | Examples | Owner |
|--------|----------|-------|
| Real SEP under SMU | `smu_sep_smoke_test`, `smu_sep_sanity_test`, … | SEP=1 colleague |
| Real interop | `smc_sep_interoperability_test`, `smu_bidirect_test`, … | SEP=1 colleague |
| 3×3 xbar matrix | `smu_axi_xbar_connectivity_matrix_test`, full aperture decode | Needs `SEP=1` |
| Depth / toggle | Wrapper toggle sweeps, modeled protocol suites | Phase-2 / child TB |

Names live in `hw/sys/smu/dv/testlists/deferred.toml` and
`SMU_VPLAN.md` Appendix A.

---

## 12. Relationship to other plans

| Document | Role |
|----------|------|
| **`SMU_VPLAN.md`** (OSS tree) | **Master P1+P2 plan** (IF matrix, P2 contracts) |
| **This file** (`oss_smu_vplan.md`) | Team-facing P1 status + checker contracts |
| `SMU_OSS_VPLAN_PHASE1.md` | Phase-1 executable density contract |
| `SMU_FCOV.md` | Functional coverage bins |
| `smu_vplan.md` / `smu_all_testplan.md` | Legacy internal |
| `SMC_VPLAN.adoc` / DTP / SEP docs | Child TB depth |

---

## 13. Implementation roadmap

| Step | Exit criteria |
|------|---------------|
| A. TB + smoke on VCS | Smoke 3/3 PASS with real checkers | **DONE** |
| B. Fabric + reset on VCS | id_width / DECERR / external / ATOP / reset PASS | **DONE** |
| C. TOP-5 remainder | boot_stall, JTAG2AXI local AXI, cpu_traffic_ext | **DONE** |
| D. TOP-10 remainder | IC_RESET, xtrig, mailbox_int | **DONE** (TOP-10 = 10/10 VCS) |
| E. Phase-1 close | Non-Force density (see `SMU_VPLAN.md`) | **DONE** (`phase1` 14/14 VL; Force-era 24 superseded) |
| F. Verilator parity | Same smoke/top5 (then phase1) on Verilator | **DONE** (2026-07-29) |
| G. Signoff | Commercial `--cov` + FCOV ledger | After F |

---

## 14. Revision history

| Version | Date | Description |
|---------|------|-------------|
| 1.2 | 2026-07-29 | Policy sync: no Force/placeholder; live `phase1` 13; Force matrix → deferred |
| 1.1 | 2026-07-14 | Phase-1 close: 24/24 VCS green (OTP CAPS+gated/ungated, clock-stop, lifecycle feat_ctrl, GPIO straps, eFuse map, WDT unlock, demote/lc_sigint) |
| 1.0 | 2026-07-14 | Initial complete OSS SMU VPLAN: Phase-1 24-test contract, SEP=0 path facts (SYS_IN filter), VCS-first policy, real checker contracts, 8/24 VCS green status, deferred SEP=1 ownership |
