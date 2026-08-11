# SMU_ENROLLED_RESIDUAL — DV 品質流程狀態圖

- **IP**: `SMU_ENROLLED_RESIDUAL`（SMU enrolled tests outside SMU_ALL P2 OWNS）
- **Milestone**: residual Skill 2 Layer-1 sweep（NO-CHECKBOX；無核准卡片）
- **Pin**: n/a（standalone Layer-1 audits）
- **最後更新**: 2026-08-06
- **目前狀態**: Major-batch Layer-1 **all clean**（18/18）；`NOT-READY` 僅因無 plan/card
- **Board**: `hw/sys/smu/dv/tb/audit_status_smu_enrolled_residual.md`

## 範圍（18）
無 SMU_ALL 核准卡 → `MODE=NO-CHECKBOX`（僅 Layer 1）。

| # | Test | Group | Grade | Layer-1 findings |
|---|---|---|---|---|
| 1 | smc_reset_ctrl_test | smc | [x] filed | none |
| 2 | smc_security_demote_pm_test | smc | [x] filed | none |
| 3 | smu_axi_atomic_operation_test | fabric | [x] re-filed | none（`NOT-READY` = NO-PLAN-ENTRY） |
| 4 | smu_axi_id_width_conversion_test | fabric | [x] re-filed | none（`NOT-READY` = NO-PLAN-ENTRY） |
| 5 | smu_boot_stall_jtag_cold_reset_matrix_test | dtp | [x] re-filed | none（`NOT-READY` = NO-PLAN-ENTRY） |
| 6 | smu_boot_stall_vs_ic_reset_priority_test | dtp | [x] re-filed | none（`NOT-READY` = NO-PLAN-ENTRY） |
| 7 | smu_dft_dtp_boot_stall_test | dtp | [x] re-filed | none（`NOT-READY` = NO-PLAN-ENTRY） |
| 8 | smu_dft_gpio_boot_stall_test | dtp | [x] re-filed | none（`NOT-READY` = NO-PLAN-ENTRY） |
| 9 | smu_dtp_bsr_extest_loopback_test | dtp | [x] re-filed | none（`NOT-READY` = NO-PLAN-ENTRY；STUB:DECLARED） |
| 10 | smu_ext_boot_seq_gate_test | smc | [x] re-filed | none（`NOT-READY` = NO-PLAN-ENTRY） |
| 11 | smu_ic_reset_dual_domain_illegal_test | dtp | [x] re-filed | none（`NOT-READY` = NO-PLAN-ENTRY） |
| 12 | smu_ic_reset_smc_multi_domain_test | dtp | [x] re-filed | none（`NOT-READY` = NO-PLAN-ENTRY） |
| 13 | smu_ic_reset_ss_domain_matrix_test | dtp | [x] re-filed | none（`NOT-READY` = NO-PLAN-ENTRY） |
| 14 | smu_jtag_reset_override_test | dtp | [x] re-filed | none（`NOT-READY` = NO-PLAN-ENTRY） |
| 15 | smu_no_sep_configuration_test | smc | [x] re-filed | none（`NOT-READY` = STANDALONE-REQUEST） |
| 16 | smu_wrapper_elaboration_no_sep_test | wrapper | [x] re-filed | none（`NOT-READY` = NO-APPROVED-CARD） |
| 17 | smu_xtrig_ctm_illegal_phase_test | dtp | [x] re-filed | none（`NOT-READY` = STANDALONE-REQUEST；r2） |
| 18 | smu_xtrig_ctm_remap_test | dtp | [x] re-filed | none（`NOT-READY` = STANDALONE-REQUEST） |

## Major-batch closure（10/10 Layer-1 clean）
| Test | Auditor | Layer-1 |
|---|---|---|
| smu_boot_stall_jtag_cold_reset_matrix_test | [stall C](663744d1-a322-4d3b-9210-b2ac9bd6c18e) | clean（fuzzy FIND-001 closed） |
| smu_boot_stall_vs_ic_reset_priority_test | [stall C](663744d1-a322-4d3b-9210-b2ac9bd6c18e) | clean |
| smu_dft_dtp_boot_stall_test | [stall C](663744d1-a322-4d3b-9210-b2ac9bd6c18e) | clean |
| smu_dft_gpio_boot_stall_test | [batch A](e8abc4e5-1c00-4653-b741-daa225a6fcc9) | clean |
| smu_dtp_bsr_extest_loopback_test | [batch A](e8abc4e5-1c00-4653-b741-daa225a6fcc9) | clean（STUB:DECLARED） |
| smu_ic_reset_dual_domain_illegal_test | [IC-reset D](7486c172-e7f5-4078-950f-12d0c1b5133a) | clean |
| smu_ic_reset_smc_multi_domain_test | [IC-reset D](7486c172-e7f5-4078-950f-12d0c1b5133a) | clean（fuzzy + X-aware closed） |
| smu_ic_reset_ss_domain_matrix_test | [IC-reset D](7486c172-e7f5-4078-950f-12d0c1b5133a) | clean |
| smu_jtag_reset_override_test | [batch B](3ce5291a-3da3-4286-ac4c-72bf3143b894) | clean |
| smu_wrapper_elaboration_no_sep_test | [batch B](3ce5291a-3da3-4286-ac4c-72bf3143b894) | clean |

Scoreboard fix: `SmuScoreboard._resolve_token` no longer fuzzy-matches expect keywords onto idle/bring-up checks.

## Progress
```
   [x] Skill 2 Layer-1 residual sweep (18/18 grades)
   [x] Blocking-batch remediation + re-audit (6/6 clean)
   [x] Major-batch remediation + re-sim + re-audit (10/10 clean)  ◀━━ 現在在這裡
   [ ] /dv_vplan_gen allocate residuals → Layer-2 closure / Skill 3
```

## 下一 session 指令
```
/dv_vplan_gen allocate residual enrolled tests (augment) for Layer-2
  OR leave as NO-CHECKBOX inventory (owner chooses)
Board: hw/sys/smu/dv/tb/audit_status_smu_enrolled_residual.md
Grades: hw/sys/smu/dv/tb/grades/
```
