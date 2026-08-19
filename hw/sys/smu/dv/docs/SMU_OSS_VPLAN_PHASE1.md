<!-- SPDX-License-Identifier: Apache-2.0 -->
# SMU OSS VPLAN — Phase 1 (SEP=0 density-first)

> **Phase 1 — live green (policy 2026-07-29i):** `phase1` **14/14** Verilator
> (no Force / no TB placeholder). Historical Force-era 24/24 VCS enrollment is
> **superseded** — see [`SMU_VPLAN.md`](SMU_VPLAN.md) and
> Force / LCC / CTM-Force names → `testlists/deferred.toml`.
>
> **SEP=1 / interop / 3×3 xbar** = OUT (Appendix A / `deferred.toml`).

| Field | Value |
|-------|-------|
| DUT | `smu` / `smu_wrapper` with **`SEP=0`** |
| Framework | cocotb + PyUVM (`env/` + `seq_lib/` + `tests/`) |
| Runner | `python3 tools/dv/run_dv.py --dut smu` |
| Golden reference | `dv/smu/tb/doc/`, `testlist_smu_chiplet.yaml` |
| Master VPLAN | `docs/SMU_VPLAN.md` (P1+P2) |
| OUT / deferred | `testlists/deferred.toml` |
| Executable contract | This doc + `testlists/{smc,dtp,fabric,all}.toml` |
| FCOV contract | `docs/SMU_FCOV.md` (SEP=0 bins only in Phase 1) |

---

## 1. Goal

- **Fewest tests, same SEP=0 coverage intent** — one representative per
  coverage domain; prefer supersets.
- Prove SMU wrapper bring-up without real SEP RTL: SMC boot, DTP/JTAG,
  SMC↔external fabric, no-SEP OTP error-slave path.
- Keep the full inventory as a catalog; do **not** treat the 109-entry
  skeleton as the Phase-1 regression.

---

## 2. Hard rules

| Rule | Consequence |
|------|-------------|
| `SEP=0` only | No real SEP CPU, no mailbox challenge-response with real SEP, no 3×3 `smu_axi_xbar` matrix |
| PyUVM-on-cocotb | No SV UVM test-class ports |
| Density-first | Superset over single-feature; merge `*_strict_*` into plusargs later |
| Subsystem depth stays in child TBs | I2C/SMBus matrices → OSS SMC; crypto KAT matrices → OSS SEP |
| FCOV = ledger, not vdb % | Trace bins in §4; Verilator has no SV covergroups |
| Commercial sim for code/toggle | `--tool xcelium --cov` (or VCS) at signoff |

---

## 3. Coverage universe (Phase-1 slice)

### Blocks (SEP=0)

SMC boot/reset/mailbox/GPIO/eFuse/WDT/demote, DTP JTAG/boot-stall/JTAG2AXI/
OTP-over-JTAG/IC_RESET/clock-stop/xtrig, external SMN AXI + ID-width path,
SEP-OTP AXI-Lite error slave (`DECERR`), programmable SMC global-base remap.

### FCOV bins Phase-1 must hit

| FCOV | Phase-1 expectation |
|------|---------------------|
| `smc_boot_cg` | reset → ROM/fw → pass |
| `sep_boot_cg` | **`SEP=0` bin only** (via `smu_no_sep_configuration_test`) |
| `mailbox_interop_cg` | SMC-local mailbox sanity/IRQ (no real SEP peer) |
| `xbar_route_cg` | SMC↔`ext` path + ID width + unmapped/`DECERR` + SEP-OTP err-slv; **not** full 3×3 matrix |
| `reg_access_cg` | SMC fabric + DTP JTAG2AXI + SMC OTP-over-JTAG |
| `reset_clock_cg` | cold / powergood / IC_RESET |
| `fuse_lifecycle_cg` | eFuse reg + lifecycle/debug policy / demote representative |
| `dtp_debug_cg` | boot-stall, clock-stop, IC_RESET, JTAG2AXI |
| `xtrig_cg` | CTM matrix / CLA coordination representative |
| `interop_bins_cg` | **Deferred** to SEP=1 track |

### Explicitly out of Phase-1 (colleague / later)

- All `smu_sep_*`, `smc_sep_*`, `smu_bidirect*`, real interop probes
- `smu_axi_xbar_connectivity_matrix_test` and other `SEP=1`-only fabric
- Wrapper toggle / signal-path coverage sweeps
- Modeled SEP-facing BFM protocol suites
- Multicore / PLIC / GPIO mux depth (promote only if smoke gaps appear)

---

## 4. Selection — Smoke ⊂ TOP-5 ⊂ TOP-10 ⊂ Phase-1 (24)

### TIER 0 — Smoke (3) — MR gate

| # | OSS test | Legacy anchor | FCOV |
|---|----------|---------------|------|
| S1 | `smu_smc_smoke_test` | `smu_smc_smoke_test` | `smc_boot` |
| S2 | `smu_dtp_jtag_smoke_test` | `smu_dtp_jtag_smoke_test` | `dtp_debug` (TAP) |
| S3 | `smu_no_sep_configuration_test` | `smu_no_sep_configuration_test` | `sep_boot` (SEP=0) + OTP err-slv |

### TIER 1 — TOP-5 (= Smoke focus + 2 wider)

| # | OSS test | Why |
|---|----------|-----|
| 1 | `smu_smc_smoke_test` | Widest SMC bring-up under wrapper |
| 2 | `smu_dft_dtp_boot_stall_test` | DTP→SMC control edge (deeper than IDCODE) |
| 3 | `smu_dtp_dtm_local_axi_test` | JTAG2AXI → SMC fabric (`reg_access`) |
| 4 | `smc_cpu_traffic_ext_axi_test` | External SMN path |
| 5 | `smu_axi_id_width_conversion_test` | SEP=0 ID-width path (SMC↔ext) |

### TIER 2 — TOP-10 (= TOP-5 + 5)

| # | OSS test | Adds |
|---|----------|------|
| 6 | `smu_axi_crossbar_error_handling_test` | Unmapped/`DECERR` + SEP-OTP err-slv |
| 7 | `smu_jtag_reset_override_test` | IC_RESET (`reset_clock`) |
| 8 | `smu_cross_trigger_matrix_test` | `xtrig_cg` |
| 9 | `smc_reset_ctrl_test` | SMC reset controller |
| 10 | `smc_mailbox_int_test` | Mailbox data + IRQ (superset of sanity) |

### TIER 3 — Phase-1 close (24 unique)

| # | OSS test | Stream | FCOV / note |
|---|----------|--------|-------------|
| 11 | `smu_dtp_otp_debug_access_test` | dtp | SMC OTP-over-JTAG |
| 12 | `smu_clock_stop_coordination_test` | dtp | clock-stop × CLA |
| 13 | `smu_lifecycle_debug_policy_test` | dtp | `fuse_lifecycle` / debug gate |
| 14 | `smu_smc_dtp_jtag2axi_security_test` | dtp | JTAG2AXI gated |
| 15 | `smu_dft_gpio_boot_stall_test` | dtp | GPIO strap boot-stall |
| 16 | `smc_gpio_strap_sanity_test` | smc | strap / GPIO |
| 17 | `smc_efuse_reg_sanity_test` | smc | eFuse CSR |
| 18 | `smc_wdt_sanity_test` | smc | WDT |
| 19 | `smc_security_demote_pm_test` | smc | demote / PM |
| 20 | `smu_axi_external_port_connectivity_test` | fabric | SMN port |
| 21 | `smu_smc_global_base_remap_test` | fabric | programmable remap |
| 22 | `smu_axi_atomic_operation_test` | fabric | ATOP reject on active path |
| S2 | `smu_dtp_jtag_smoke_test` | dtp | TAP smoke (in `smoke`, not TOP-5) |
| S3 | `smu_no_sep_configuration_test` | smc | SEP=0 signature (in `smoke`) |

> Executable Phase-1 = TOP-10 (1–10) + (11–22) + smoke extras {S2, S3} = **24**
> unique tests. TOP-5 / TOP-10 are cumulative subsets for staged bring-up.

---

## 5. FCOV → test traceability (Phase-1)

| FCOV | Primary Phase-1 tests |
|------|------------------------|
| `smc_boot_cg` | `smu_smc_smoke_test` |
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

## 6. Environment bring-up (SEP=0 first)

Order matches `docs/SMU_TB_ARCH.md`, constrained to no-SEP:

1. **Filelist + `tb_top.sv`** — elaborate `smu_uvm_top` with `SEP=0`
2. **Clocks/resets + SMC scratch/pass observation**
3. **External AXI agents** — `ocah_axi_vip` master on `smu_axi_in`, `OcahAxiSlaveAgent` on `smu_axi_out`
4. **JTAG agent** — IDCODE/BYPASS → JTAG2AXI / IC_RESET
5. **Mailbox / GPIO / eFuse observe** — backdoor + polling (no SEP peer)
6. **Xtrig / clock-stop local BFM** — after JTAG path is stable
7. **Python FCOV counters** — map §5 bins

Reuse:

- OCAH VIP: `ocah_jtag_vip`, `ocah_axi_vip`
- Patterns from OSS SMC / SEP `tb_top` flatten + agents
- Do **not** require SEP TCM/OTP SEP-bank bring-up in this track

Sim config: `smu_sim_cfg.toml` Phase-1 default build must force **`SEP=0`**
(parameter / define as established during flist bring-up).

---

## 7. Testlists and regression groups

| File | Role |
|------|------|
| `testlists/smc.toml` | Phase-1 SMC / no-SEP tests |
| `testlists/dtp.toml` | Phase-1 DTP tests |
| `testlists/fabric.toml` | Phase-1 SEP=0 fabric tests |
| `testlists/all.toml` | includes above + groups `smoke`, `smc`, `dtp`, `fabric`, `top5`, `top10`, `phase1` |
| `testlists/deferred.toml` | Universe leftovers (SEP=1, depth, toggle) — **not** in default `all.toml` |

| Group | Contents |
|-------|----------|
| `smoke` | S1–S3 |
| `top5` | tests 1–5 |
| `top10` | tests 1–10 |
| `phase1` | all 24 |
| `smc` / `dtp` / `fabric` | per-stream Phase-1 subset |

---

## 8. Execution steps

```bash
cd /path/to/tt-oca   # or os_oca checkout
source bin/setup_env.sh
export TMPDIR=/localdev/$USER/TMPDIR
mkdir -p "$TMPDIR"

# A. Build only (flist / Verilator) — expect incremental bring-up
python3 tools/dv/run_dv.py --dut smu --build-only

# B. Inspect resolution
python3 tools/dv/run_dv.py --dut smu --items smoke --dry-run

# C. Staged regress
python3 tools/dv/run_dv.py --dut smu --items smoke
python3 tools/dv/run_dv.py --dut smu --items top5
python3 tools/dv/run_dv.py --dut smu --items top10
python3 tools/dv/run_dv.py --dut smu --items phase1

# D. Commercial coverage (signoff)
python3 tools/dv/run_dv.py --dut smu --items phase1 --tool xcelium --cov
```

| Cadence | Command intent |
|---------|----------------|
| Every MR | `--items smoke` |
| Daily | `--items top5` |
| Weekly | `--items phase1` |
| Signoff | `phase1` + commercial `--cov` + §5 FCOV ledger green |

---

## 9. Deferred ownership (SEP=1 track)

Recorded for handoff; live names remain in `testlists/deferred.toml` and
`docs/SMU_VPLAN.md` Streams 2/4/5 (SEP=1 fabric).

| Bucket | Examples | Owner note |
|--------|----------|------------|
| Real SEP under SMU | `smu_sep_smoke_test`, `smu_sep_sanity_test`, `smu_sep_modules_test`, … | SEP=1 colleague |
| Real interop | `smc_sep_interoperability_test`, `smc_sep_xbar_test`, `smu_bidirect_test`, strict/probes | SEP=1 colleague |
| 3×3 xbar matrix | `smu_axi_xbar_connectivity_matrix_test`, `smu_axi_xbar_address_decode_test` (full apertures) | Needs `SEP=1` |
| Depth / toggle | wrapper toggle sweeps, modeled protocol suites, multicore/PLIC depth | Phase-2 or child TB |

Phase-1 does **not** claim `interop_bins_cg` or `sep_boot_cg` (`SEP=1` /
executing) closure.

---

## 10. Revision history

| Version | Date | Description |
|---------|------|-------------|
| 1.0 | 2026-07-14 | Initial Phase-1 SEP=0 density plan: 24 tests, smoke/top5/top10 groups, deferred SEP=1 ownership |
