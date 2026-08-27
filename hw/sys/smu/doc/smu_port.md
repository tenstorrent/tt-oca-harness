<!-- SPDX-License-Identifier: Apache-2.0 -->
<!-- SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. -->
# SMU DV Port Plan — local nonfree2 → local oss2

**Date:** 2026-08-19  
**Workspace roots (local only):**

| Role | Absolute path |
|------|---------------|
| Source tree | `/proj_soc/user_dev/minshaoho/tryrun/nonfree2` |
| Destination tree | `/proj_soc/user_dev/minshaoho/tryrun/oss2` |

**Sources compared:**

| Side | Path | Role |
|------|------|------|
| Commercial / nonfree2 | `/proj_soc/user_dev/minshaoho/tryrun/nonfree2/hw/sys/smu/dv/tb/tb_uvm/yaml/testlist_smu_chiplet.yaml` | Full chiplet UVM+cocotb catalog + Jenkins gates |
| Commercial audit | `/proj_soc/user_dev/minshaoho/tryrun/nonfree2/hw/sys/smu/dv/tb/doc/smu_audit_status.md` | without-SEP green status |
| Local enrolled | `/proj_soc/user_dev/minshaoho/tryrun/oss2/hw/sys/smu/dv/testlists/all.toml` (+ leaf tomls) | Reportable PASS surface |
| Local deferred | `/proj_soc/user_dev/minshaoho/tryrun/oss2/hw/sys/smu/dv/testlists/deferred.toml` | Named but not enrollable |
| Local live | `cd /proj_soc/user_dev/minshaoho/tryrun/oss2 && python3 tools/dv/run_dv.py --dut smu --list` | Runnable modules |

**Local OSS policy (binding):** no DUT Force / no TB placeholder; toggle sweeps are not
sole PASS criteria; `deferred.toml` names never report as enrolled PASS.
See `hw/sys/smu/dv/README.md` and `hw/sys/smc/doc/dv_hack_cleanup_checklist.md`
under the destination tree.

Related pin / interconnect notes: [`port_table.adoc`](port_table.adoc).

---

## 1. Scale snapshot

| Metric | Count |
|--------|------:|
| nonfree2 leaf `*_test` entries | 144 |
| nonfree2 `SMU_Dev_without_SEP_Regression` (green gate) | 60 |
| Local live modules (`--dut smu --list`) | 24 |
| Local `sep0_all` (density signoff) | 20 |
| Local `sep0_p4_all` | 22 |
| Local `deferred.toml` catalog | ~145 |

**without-SEP (60) vs local disposition (approx.):**

| Bucket | Count | Meaning |
|--------|------:|---------|
| Already LIVE in local oss2 | ~11 | Core smoke / fabric anchors already in `sep0_all` |
| Named in local `deferred.toml` | ~32 | Do not re-invent; promote when blockers clear |
| Missing from local entirely | ~17 | Primary port candidates (Tier A/C below) |

Local also has deepeners **not** on the commercial without-SEP list
(`smu_boot_stall_*`, `smu_ic_reset_*`, `smu_xtrig_ctm_*`). Keep those; they are
local-ahead progress, not gaps.

---

## 2. Commercial gates to track

| Jenkins / regression | Compile | Notes for local port |
|----------------------|---------|---------------|
| `SMU_Dev_without_SEP_Regression` | `compile_smu_chiplet_no_sep` | Primary port source (60 tests, Phase B expanded) |
| `Main_SMU_Chiplet_Nightly_Regression` | aliases without-SEP | Same surface |
| `SMU_SMC_Global_Base_Remap_Regression` | no_sep | `smu_smc_global_base_remap_test` + `smu_ext_axi_global_addr_smoke_test` |
| `DTP_SMC_Interface_Coverage_Regression` | — | J2A / CTM / PLL-stop cluster |
| `SMU_Dev_with_SEP_Regression` | `sep_rtl` | SEP=1 colleague track — not Phase-1 local enroll |
| `Manual_SMU_Blocked_SEP_Exec_Regression` | SEP exec | Quarantine; maps to local `blocked_sep_exec` |

Commercial holds already removed from green (do not port as PASS):

- `smu_axi_crossbar_performance_test` — empty body
- `smu_axi_atomic_awatop_reject_test` — deferred hold
- `smu_atb_telemetry_path_test` — ATB held

---

## 3. Port tiers

### Tier A — Fabric deepen (highest value)

Commercial without-SEP already enrolled and audit CLEAN; **local oss2 has no name yet**
(not even in `deferred.toml`). Port inventory first, then rewrite without Force.

| Test | Intent | Port action |
|------|--------|-------------|
| `smu_axi_filter_in_instance_matrix_test` | Inbound filter instance independence | Add to `deferred.toml` (`fabric`,`depth`); rewrite no-Force; then consider `fabric` / `sep0_p4` |
| `smu_axi_filter_out_instance_matrix_test` | Outbound filter CSR addressing | Same |
| `smu_axi_filter_allow_ns_test` | `allow_ns` non-secure admission | Same — good first implementer |
| `smu_axi_alias_remap_manager_scope_test` | Alias-remap scope across managers | Same |
| `smu_axi_prot_encoding_decode_test` | AxPROT as decode input | Same — good first implementer |
| `smu_ext_axi_global_addr_smoke_test` | LOCAL_BASE vs GLOBAL_BASE view | Pair with deferred `smu_smc_global_base_remap_test` |
| `smu_smc_external_axil_path_test` | SMC AXI-Lite external window | Same |
| `local_fabric_reg_bar_wr_test` | Local fabric reg-bar delivery | Same |

**Suggested first implementers (2–3):**

1. `smu_axi_filter_allow_ns_test`
2. `smu_axi_prot_encoding_decode_test`
3. `smu_ext_axi_global_addr_smoke_test`

**Constraint:** nonfree2 sources still contain Force-ish / deposit paths marked
good-to-have. Local enrollment requires product-pin / frontdoor stimulus only.

Commercial reference sources live under:

```text
/proj_soc/user_dev/minshaoho/tryrun/nonfree2/hw/sys/smu/dv/tb/tb_uvm/cocotb_tests/
```

Local implementation landing zones:

```text
/proj_soc/user_dev/minshaoho/tryrun/oss2/hw/sys/smu/dv/cocotb/tests/
/proj_soc/user_dev/minshaoho/tryrun/oss2/hw/sys/smu/dv/cocotb/seq_lib/
/proj_soc/user_dev/minshaoho/tryrun/oss2/hw/sys/smu/dv/testlists/
```

### Tier B — Already in local deferred (promote, do not re-port)

Track blockers; promote into enrolled groups only when tags clear.

| Test | Deferred tags (local) | Promote when |
|------|---------------------|--------------|
| `smu_smc_global_base_remap_test` | `needs_real_lcc`,`sep1`,`no_force` | Real LCC / feat_ctrl ungating without Force |
| `smu_axi_xbar_structure_test` | `fabric` | SEP=0 structure story accepted |
| `smu_axi_xbar_address_decode_test` | `fabric`,`sep1` | SEP manager port / SEP=1 bring-up |
| `smu_axi_xbar_connectivity_matrix_test` | `fabric`,`sep1` | Same (full 3×3) |
| `smu_fabric_smc_dtp_cross_domain_test` | `fabric`,`needs_real_lcc`,`sep1` | LCC + cross-domain frontdoor |
| `smu_dtp_csr_access_test` | `needs_real_lcc`,`sep1` | J2A ungating without Force |
| `smu_dtp_dtm_local_axi_test` | `needs_real_lcc`,`sep1` | Same |
| `smu_smc_dtp_jtag2axi_security_test` | `needs_real_lcc`,`sep1` | LCC path |
| `smu_smc_cpu_traffic_smoke_test` | `smc`,`depth` | SEP=0 depth OK once modeled path honest |
| `smu_cross_trigger_matrix_test` | `needs_real_lcc`,`sep1` | Prefer product pins over Force |
| `smu_dft_lifecycle_matrix_test` | `dtp`,`depth` | Depth phase |
| `smu_dtp_basic_verification_test` | `dtp`,`depth` | Depth phase |
| `smu_memrepair_mbist_boot_reset_test` | `interop` | Interop / foundry cell readiness |

Toggle-tagged deferred items stay **out of enrolled PASS** forever as sole
criteria: `smu_wrapper_axi_toggle_test`, `smu_signal_path_verification_test`,
`smu_dtp_jtag2axi_signal_toggle_test`.

### Tier C — Sideband / DTP (port after fabric)

| Test | Notes |
|------|-------|
| `smu_system_timer_octs_test` | **LIVE** — `smc.toml`; J2A + `tb_timer_count`; 64b lane wstrb for PRESET@+0xC; CSR COUNT via J2A deferred (hangs) |
| `smu_i3c_mem_port_connectivity_test` | **LIVE** — FAB_SMC_031 J2A delivery UART/I2C/GPIO/I3C/AVSBus |
| `smu_dtp_smc_stap_smoke_test` | **LIVE** — `dtp.toml`; TRST + TAP_3DCR via `tb_stap_smc_tdo_oen` |
| `smu_dtp_io_stap_smoke_test` | **LIVE** — `dtp.toml`; `tb_stap_io_tck` observe during IDCODE/BYPASS |
| `smu_dtp_bsr_ijtag_scan_test` | **LIVE** — `dtp.toml`; BSR `.select` EXTEST/SAMPLE_PRELOAD |
| `smu_dtp_otp_smc_map_rw_test` | **LIVE** — `dtp.toml`; OTP J2A MAP BIRA allow-path (gate tied open) |
| `smu_dtp_otp_smc_complete_rw_test` | **LIVE** — `dtp.toml`; OTP MAP RESERVED walk + fabric/shadow + isolation (gated-deny not claimed) |
| `smu_dtp_ptap_otp_instr_scan_test` | **LIVE** — `dtp.toml`; SMC/SEP OTP CAPS + JTAG_CAPS sep_dbg_en=0 + SMC SINGLE_OP echo + SEP IR BYPASS |
| `smu_jtag_chain_enhanced_test` | **LIVE** — `dtp.toml`; IDCODE+BYPASS at 1/5/10/20 MHz TCK (VIP period; analog timing not claimed) |
| `smu_dtp_otp_smc_series_error_test` | **LIVE** — `dtp.toml`; series NO_INCR @ MAP BIRA + MAP–CTRL hole SLVERR (`0xbadcab1e`); SHIM-unmapped DECERR deferred |
| `smu_smc_dtp_jtag2axi_smoke_test` | **LIVE** — `dtp.toml`; SMC fabric J2A SCRATCH_15 + SPM + series INCR (gate tied open) |
| `smu_dtp_jtag2axi_smc_error_path_test` | **LIVE** — `dtp.toml`; unmapped local_xbar hole DECERR + `0xbadcab1e` + VERSION_LO recovery + series INCR after error |
| `smu_dtp_jtag_smc_cpu_register_test` | **LIVE** — `dtp.toml`; SCRATCH_15 two-pattern J2A + DEBUG_CONTROL stall |
| `smu_dtp_jtag2axi_smc_rw_matrix_test` | **LIVE** — `dtp.toml`; WSTRB widths 1/2/4/8 + partial 0x55/0xAA on SPM (AxSIZE-alone not claimed) |
| `smu_dtp_jtag2axi_wstrb_partial_sticky_test` | **LIVE** — `dtp.toml`; partial WSTRB merge + adjacent SPM word intact |
| `smu_dtp_jtag2axi_back_to_back_error_ok_test` | **LIVE** — `dtp.toml`; unmapped DECERR then immediate VERSION_LO SUCCESS |
| `smu_dtp_jtag2axi_abort_mid_op_test` | **LIVE** — `dtp.toml`; OTP `+0x80` BUSY abort (IR+TRST); fabric VERSION_LO recovers |
| `smu_dtp_pll_stop_clks_obs_test` | **blocked** — OSS `smu` TB has no `u_pll_wrapper` / `cgm_clk_halt_sync`; `smu_clock_stop_coordination_test` already covers `dtp_stop_clks_o` |

### Do not port (or keep hold)

| Class | Examples | Reason |
|-------|----------|--------|
| Toggle-as-PASS | `smu_wrapper_axi_toggle_test`, `smu_signal_path_verification_test`, `smu_dtp_jtag2axi_signal_toggle_test` | Local OSS policy |
| Empty / hold | `smu_axi_atomic_awatop_reject_test`, `smu_axi_crossbar_performance_test` | No `finish_ok` PASS |
| SEP exec / dual-CPU | `smu_dtp_dual_cpu_jtag2axi_test`, SEP filter/alias probes | `blocked_sep_exec` / sep_probe |
| Force-only green | Most `needs_real_lcc` until frontdoor exists | Local no-Force |
| SMC IP-level | `smc_efuse_ctrl_reg_test`, `smc_register_test`, `smc_random_default_reg_rd_test` | Belong in SMC TB, not SMU density |
| ATB hold | `smu_atb_telemetry_path_test` | Commercial hold |
| Scaffold / unsigned deferral | `smu_axi_filter_out_rule_matrix_test`, `smu_axi_priv_remap_mmode_xvisor_test` | Commercial deliberately left unmerged (no stimulus) |

---

## 4. without-SEP (60) checklist vs local oss2

Legend: **LIVE** = local runnable · **DEF** = local `deferred.toml` · **MISS** = not in local.

| Test | Local | Notes |
|------|-------|-------|
| `smu_smc_smoke_test` | LIVE | `sep0_all` |
| `smu_smc_cpu_traffic_smoke_test` | DEF | `smc`,`depth` |
| `smu_no_sep_configuration_test` | LIVE | |
| `smu_dtp_jtag_smoke_test` | LIVE | |
| `smu_dft_dtp_boot_stall_test` | LIVE | |
| `smu_dft_gpio_boot_stall_test` | LIVE | |
| `smu_dtp_dtm_local_axi_test` | DEF | `needs_real_lcc` |
| `smu_dtp_otp_debug_access_test` | DEF | `needs_real_lcc` |
| `smu_dft_lifecycle_matrix_test` | DEF | `dtp`,`depth` |
| `smu_dtp_csr_access_test` | DEF | `needs_real_lcc` |
| `smu_cross_trigger_matrix_test` | DEF | `needs_real_lcc` |
| `smu_clock_stop_coordination_test` | LIVE | |
| `smu_jtag_reset_override_test` | LIVE | |
| `smu_smc_dtp_jtag2axi_smoke_test` | LIVE | **depth** — SMC fabric J2A SCRATCH_15 + SPM + series INCR; gate tied open |
| `smu_dtp_jtag2axi_smc_error_path_test` | LIVE | **depth** — unmapped DECERR + poison + VERSION_LO recovery; series INCR after error |
| `smu_smc_dtp_jtag2axi_security_test` | DEF | `needs_real_lcc` |
| `smu_dtp_feat_ctrl_gated_jtag2axi_test` | DEF | superseded |
| `smu_dtp_xtrigger_smc_cla_test` | DEF | `needs_real_stimulus` |
| `smu_dtp_clock_stop_smc_cla_test` | DEF | depth |
| `smu_dtp_jtag_smc_cpu_register_test` | LIVE | **depth** — SCRATCH_15 two-pattern + DEBUG_CONTROL stall |
| `smu_dtp_jtag2axi_smc_rw_matrix_test` | LIVE | **depth** — WSTRB widths 1/2/4/8 + partial 0x55/0xAA on SPM (AxSIZE-alone not claimed) |
| `smu_dtp_jtag2axi_wstrb_partial_sticky_test` | LIVE | **depth** — partial WSTRB + neighbor intact |
| `smu_dtp_jtag2axi_back_to_back_error_ok_test` | LIVE | **depth** — DECERR then immediate VERSION_LO |
| `smu_dtp_jtag2axi_abort_mid_op_test` | LIVE | **depth** — OTP +0x80 BUSY abort; fabric recovers |
| `smu_axi_xbar_address_decode_test` | DEF | `fabric`,`sep1` |
| `smu_axi_xbar_connectivity_matrix_test` | DEF | `fabric`,`sep1` |
| `smu_axi_external_port_connectivity_test` | LIVE | |
| `smu_axi_crossbar_performance_test` | DEF | hold / empty |
| `smu_axi_crossbar_error_handling_test` | LIVE | |
| `smu_fabric_smc_dtp_cross_domain_test` | DEF | `needs_real_lcc` |
| `smu_axi_id_width_conversion_test` | LIVE | |
| `smu_axi_atomic_operation_test` | LIVE | |
| `smu_axi_atomic_awatop_reject_test` | MISS | commercial hold — catalog only if needed |
| `smu_smc_global_base_remap_test` | DEF | `needs_real_lcc` |
| `smu_memrepair_mbist_boot_reset_test` | DEF | interop |
| `smu_axi_alias_remap_manager_scope_test` | LIVE | **Tier A** — FAB_SMC_018 S3 J2A→SPM; S1/S2/S4/S5 deferred |
| `smu_axi_filter_allow_ns_test` | LIVE | **Tier A** — `fabric.toml`; J2A+`s_axi` S1/S2/S3; Layer-1 clean |
| `smu_axi_filter_in_instance_matrix_test` | LIVE | **Tier A** — local-alias S1–S5; J2A+`s_axi`; FIND-001 src_id fix |
| `smu_axi_filter_out_instance_matrix_test` | LIVE | **Tier A** — S1 DECODE via J2A; S2/S3 deferred (needs ext_out) |
| `smu_axi_prot_encoding_decode_test` | LIVE | **Tier A** — S9 AxPROT matrix LIVE; S1–S8 GPIO PoC deferred (`sep_in`) |
| `smu_gpio_interrupts_undriven_test` | MISS | tripwire / port-removal; low density value |
| `smu_axi_xbar_structure_test` | DEF | fabric |
| `smu_dtp_pll_stop_clks_obs_test` | MISS | **blocked** — no PLL sink on OSS `smu` TB (`dtp_stop_clks_o` is LIVE via `smu_clock_stop_coordination_test`) |
| `smu_dtp_jtag2axi_signal_toggle_test` | DEF | coverage — do not enroll as sole PASS |
| `smu_ext_axi_global_addr_smoke_test` | DEF | **Tier A** — `needs_global_aperture_stimulus` (OSS `s_axi` is LOCAL `0xC000`; GLOBAL+offset DECERR) |
| `smu_wrapper_axi_toggle_test` | DEF | coverage — do not enroll |
| `smu_system_timer_octs_test` | LIVE | **Tier C** — J2A + `tb_timer_count`; CSR COUNT deferred |
| `smu_dtp_ptap_otp_instr_scan_test` | LIVE | **depth** — SMC/SEP OTP CAPS + JTAG_CAPS sep_dbg_en=0 + SMC SINGLE_OP echo + SEP IR BYPASS |
| `smu_dtp_smc_stap_smoke_test` | LIVE | **Tier C** — TRST + TAP_3DCR via `tb_stap_smc_tdo_oen` |
| `smu_dtp_io_stap_smoke_test` | LIVE | **Tier C** — `tb_stap_io_tck` during PTAP scans |
| `smu_jtag_chain_enhanced_test` | LIVE | **depth** — IDCODE+BYPASS at 1/5/10/20 MHz TCK |
| `smu_dtp_dual_cpu_jtag2axi_test` | DEF | `blocked_sep_exec` |
| `local_fabric_reg_bar_wr_test` | LIVE | **Tier A** — FAB_SMC_032 J2A delivery to 6 fabric CFG dests |
| `smu_smc_external_axil_path_test` | DEF | **Tier A** — `needs_tb_external_terminator` + `needs_external_leaf_map` |
| `smc_cpu_traffic_sep_axi_test` | DEF | modeled |
| `smc_cpu_traffic_sep_plus_ext_axi_test` | DEF | modeled |
| `smu_rom_interop_enhanced_test` | DEF | interop |
| `smu_sep_smc_alias_remap_consistency_test` | DEF | sep_probe |
| `smu_i3c_mem_port_connectivity_test` | LIVE | **Tier C** — FAB_SMC_031 J2A peripheral delivery |
| `smu_dtp_bsr_ijtag_scan_test` | LIVE | **Tier C** — BSR `.select` during EXTEST/SAMPLE_PRELOAD |
| `smu_dtp_otp_smc_map_rw_test` | LIVE | **Tier C** — OTP J2A MAP BIRA allow-path; gated-close deferred (no Force) |
| `smu_dtp_otp_smc_complete_rw_test` | LIVE | **depth** — OTP MAP RESERVED[1,9,17] + fabric/shadow match + isolation; gated-deny not claimed |
| `smu_sep_filter_rule_matrix_test` | DEF | sep_probe |
| `smu_dtp_basic_verification_test` | DEF | depth |
| `smu_signal_path_verification_test` | DEF | coverage — do not enroll |
| `smu_dtp_otp_smc_series_error_test` | LIVE | **Tier C** — series NO_INCR @ MAP BIRA + MAP–CTRL `0xC0007C00` SLVERR/`0xbadcab1e`; SHIM `0xC000D000` DECERR deferred (TB `bank_ctrl_resp='0'`) |

---

## 5. Recommended local migration sequence

All writes land under `/proj_soc/user_dev/minshaoho/tryrun/oss2`. Commercial
sources are read-only references under `/proj_soc/user_dev/minshaoho/tryrun/nonfree2`.

### 5.1 Path map (what moves where)

| Artifact | From (nonfree2) | To (local oss2) |
|----------|-----------------|-----------------|
| Test intent / catalog name | `…/tb_uvm/yaml/testlist_smu_chiplet.yaml` | `hw/sys/smu/dv/testlists/{deferred,fabric,…}.toml` |
| Cocotb body | `…/tb_uvm/cocotb_tests/<test>.py` | `hw/sys/smu/dv/cocotb/tests/<test>.py` |
| Sequence / helpers | commercial seq / env helpers | `hw/sys/smu/dv/cocotb/seq_lib/` (+ env if needed) |
| FW images (if any) | commercial fw | `hw/sys/smu/dv/fw/tests/` via `ocah-dv-fw` flow |
| Do **not** copy | UVM env, Force/deposit, Jenkins yaml | — |

### 5.2 Per-test move checklist

1. Diff commercial intent vs local TB pins (`tb/tb_top.sv`, VIP bindings).
2. Rewrite stimulus frontdoor-only (Ocah AXI VIP / product pins); strip Force.
3. Drop in under `cocotb/tests/` + `seq_lib/`; keep SPDX headers.
4. Add name to `deferred.toml` first (inventory), then promote to leaf toml
   only after Verilator PASS with honest checkers.
5. Keep commercial re-sim log under `$TMPDIR` for A/B; do not commit logs.

### 5.3 Phase order

1. **Inventory** — Add Tier A names to
   `…/oss2/hw/sys/smu/dv/testlists/deferred.toml`
   under a `fabric` / `depth` banner (no PASS reporting).
2. **Pilot rewrite** — Implement 2–3 Tier A tests under
   `…/oss2/hw/sys/smu/dv/cocotb/{tests,seq_lib}/` using Ocah AXI VIP only; strip Force.
3. **Enroll** — After Verilator green + honest checkers, add to `fabric.toml`
   groups and optionally `sep0_p4_all` (not necessarily `phase1` density gate).
4. **Promote Tier B** — Only when `needs_real_lcc` / `sep1` blockers have a
   product-pin path (no Force exception).
5. **Tier C** — OCTS first LIVE (`smu_system_timer_octs_test`); continue STAP /
   OTP / I3C after pin readiness on `--dut smu` TB.
6. **Do not** merge commercial wrapper smoke or toggle PASS into bare
   `sep0_all` evidence (`DUT_TAG=BARE` vs `WRAPPER`).

### Local commands (oss2 destination)

```bash
cd /proj_soc/user_dev/minshaoho/tryrun/oss2
cd "$(pwd -P)"
source nonfree/setup_env.sh
export TMPDIR="${TMPDIR:?set TMPDIR to large scratch}"
mkdir -p "$TMPDIR"
module unload verilator; module load verilator/5.050 gcc/13.2.1

python3 tools/dv/run_dv.py --dut smu --items sep0_all --tool verilator --regress
python3 tools/dv/run_dv.py --dut smu --items <new_test> --tool verilator --seed 1
```

### Commercial reference re-sim (local nonfree2)

```bash
cd /proj_soc/user_dev/minshaoho/tryrun/nonfree2/hw/sys/smu/dv/tb/tb_uvm
ttem --config ../../ yaml/testlist_smu_chiplet.yaml <TEST> \
  --stack sim --no-lsf --seed=1 -c compile_smu_chiplet_no_sep
```

---

## 6. Success criteria

| Gate | Definition |
|------|------------|
| Inventory complete | All Tier A names present in local `deferred.toml` with blockers/plan tags |
| Pilot complete | ≥2 Tier A tests LIVE on local oss2, Verilator PASS, no Force, enrolled under `fabric` |
| Density preserved | Existing local `sep0_all` remains 20/20 (or documented intentional growth) |
| Policy clean | No new `allow_timeout` / Force / toggle-as-sole-PASS in enrolled set |

---

## 7. Revision

| Date | Change |
|------|--------|
| 2026-08-19 | Initial port plan from nonfree2 without-SEP (60) vs OSS live/deferred diff |
| 2026-08-19 | Retarget destination to local oss2 absolute paths; add local migration path map |
| 2026-08-20 | SMC UART Tier A depth LIVE + Layer-1 audits clean (`uart.toml`); SMU Tier A still inventory — bare SEP=0 lacks `sep_in_master` / LCC for filter CSR pilots (`needs_internal_axi_csr`) |
| 2026-08-20 | **Correction:** SEP=0 `gen_no_sep` ties `sep_feat_ctrl='1'` (enable polarity); J2A ungated after TCK 2-flop sync. Pilot `smu_axi_filter_allow_ns_test` LIVE in `fabric.toml` (J2A+`s_axi` S1/S2/S3); Layer-1 clean |
| 2026-08-20 | Pilot `smu_axi_prot_encoding_decode_test` LIVE (FAB_SMC_029 **S9** eight-way AxPROT; S1–S8 GPIO PoC deferred — needs `sep_in`). Success criteria pilot gate (≥2 Tier A LIVE) met |
| 2026-08-20 | `smu_axi_filter_in_instance_matrix_test` LIVE (FAB_SMC_023 S1–S5 local-alias); Layer-1 FIND-001 closed (4-bit SRC_ID). `smu_axi_filter_out_instance_matrix_test` LIVE (FAB_SMC_025 S1 DECODE; S2/S3 deferred SF-239); Layer-1 FIND-001 closed (no always-true deferred CHK) |
| 2026-08-20 | `local_fabric_reg_bar_wr_test` LIVE (FAB_SMC_032 J2A delivery); Layer-1 clean |
| 2026-08-20 | `smu_ext_axi_global_addr_smoke_test` attempted then deferred: OSS `s_axi` speaks LOCAL `0xC000` (connectivity precedent); `GLOBAL_BASE+offset` → DECERR → tag `needs_global_aperture_stimulus`. `smu_smc_external_axil_path_test` deferred (`needs_tb_external_terminator` + `needs_external_leaf_map`) |
| 2026-08-20 | `smu_axi_alias_remap_manager_scope_test` LIVE (FAB_SMC_018 **S3** J2A alias→SPM consumer; S1 DMA / S2 Log / S4–S5 deferred notes) |
| 2026-08-20 | **SMU Tier A inventory closed for implementable SEP=0 items:** LIVE = allow_ns, prot S9, in-matrix, out-matrix S1, local_fabric, alias-remap S3. Remaining Tier A = product/TB blockers only (global aperture, external AXIL terminator/leaf map) |
| 2026-08-20 | `smu_dtp_otp_smc_series_error_test` LIVE (`dtp.toml`; series NO_INCR @ MAP BIRA + MAP–CTRL hole SLVERR/`0xbadcab1e`). SHIM-unmapped `0xC000D000` DECERR deferred (TB `bank_ctrl_resp='0'`). `smu_dtp_pll_stop_clks_obs_test` stays MISS (no PLL wrapper). First-round executable Tier C MISS set closed. |
| 2026-08-20 | `smu_smc_dtp_jtag2axi_smoke_test` LIVE (`dtp.toml`; SCRATCH_15 + SPM + series INCR; `tb_smc_jtag2axi_security_disable` observe). Depth phase after first-round smoke stable. |
| 2026-08-20 | `smu_dtp_jtag2axi_smc_error_path_test` LIVE (`dtp.toml`; local_xbar hole between CORE3 WDT and RESET_UNIT → DECERR + `0xbadcab1e`; VERSION_LO recovery; series INCR after error). |
| 2026-08-20 | `smu_dtp_jtag_smc_cpu_register_test` LIVE (`dtp.toml`; SCRATCH_15 two-pattern + DEBUG_CONTROL stall; not SCRATCH_0). |
| 2026-08-20 | `smu_dtp_jtag2axi_smc_rw_matrix_test` LIVE (`dtp.toml`; SIZE 0..3 + WSTRB 0x55/0xAA on SPM; no TB out_mem). `smu_dtp_jtag2axi_wstrb_partial_sticky_test` LIVE (partial merge + neighbor). |
| 2026-08-20 | `smu_dtp_jtag2axi_smc_rw_matrix_test` retracts AxSIZE-alone: seed-1 SIZE=0 + WSTRB=0xFF stores the full beat (bridge applies WSTRB). S2 is WSTRB-width 1/2/4/8 with 8-byte seed/read. |
| 2026-08-20 | `smu_dtp_jtag2axi_back_to_back_error_ok_test` LIVE (DECERR then immediate VERSION_LO). `smu_dtp_jtag2axi_abort_mid_op_test` LIVE (OTP `+0x80` BUSY + IR/TRST abort; fabric recovers). |
| 2026-08-20 | Filter trio LIVE (`fabric.toml`; program / page-edge / shrink-clear). J2A-vs-SMN and OTP-vs-fabric MAP races LIVE (`dtp.toml`; abs BIRA). WDT unlock/WDOGIP0 + GPIO STRAPS LIVE (`smc.toml`). No Force. Hierarchical AXIL Force inject (csr_access / sep0_err_slv / hier_ctn) stays deferred. |
| 2026-08-20 | `smu_dtp_otp_smc_complete_rw_test` LIVE (`dtp.toml`; MAP RESERVED[1,9,17] OTP+fabric+shadow; isolation after rewrite). Index 0 (0xC0007AFC) is not 8-byte aligned — fabric 4B read returned 0. Gated-deny still needs LCC. J2A depth seven Skill-2 clean; rw_matrix retracts AxSIZE-alone. |
| 2026-08-20 | `smu_dtp_ptap_otp_instr_scan_test` LIVE (`dtp.toml`; SMC/SEP OTP CAPS + JTAG_CAPS sep_dbg_en=0 + SMC SINGLE_OP echo + SEP IR BYPASS). `smu_jtag_chain_enhanced_test` LIVE (IDCODE+BYPASS at 1/5/10/20 MHz). `smc_mailbox_sanity_test` LIVE (`smc.toml`; outbound-0 STATUS/IRQEN J2A). No Force. |
| 2026-08-20 | `smu_axi_xbar_structure_test` LIVE (`fabric.toml`; SEP=0 `gen_no_sep` IW converters present, `smu_axi_xbar` absent). Remaining SMU MISS stays LCC / SEP=1 / GLOBAL / external AXIL / PLL. |
