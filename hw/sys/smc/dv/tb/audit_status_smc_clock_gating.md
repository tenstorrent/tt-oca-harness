# SMC_CLOCK_GATING — DV 品質流程狀態圖

- **IP**: `SMC_CLOCK_GATING`
- **Milestone**: `P1`
- **Pin**: `hw/sys/smc/dv/tb/SMC_CLOCK_GATING_PIN.yaml`
- **最後更新**: 2026-08-06T14:55:00+08:00
- **目前狀態**: **P1 DFT re-opened** — Skill 2 re-audit of `smc_cg_test_mode_bypass_test` → `ENTRY-CONDITION-FAILED` / `NOT-READY`；prior PROVEN voided；[#4413](https://github.com/tenstorrent/tt-oca-hw/issues/4413) OPEN
- **Board path**: `hw/sys/smc/dv/tb/audit_status_smc_clock_gating.md`
- **Process docs**: `hw/sys/smc/dv/docs/smc_cg_skill_flow.md`（總覽）· `smc_cg_skill{1,2,3}.md`
- **Peer-audit report**: `hw/sys/smc/dv/tb/SMC_CLOCK_GATING_PEER_AUDIT.md`（pre-revert；DFT portion superseded）
- **RTL issue**: https://github.com/tenstorrent/tt-oca-hw/issues/4413 (`prim_clkgater` ignores `i_te`)
- **Re-audit auditor**: [Skill2 bypass FAIL](86a3adf0-9d49-447e-af36-7321757aee18)

## Progress

```
   [x] Skill 1 approved (+ INT-ZEROER amend approved)
   [x] Skill 1.5 all 8 cards
   [!] Skill 2 re-audit smc_cg_test_mode_bypass_test
       → 0/0 PROVEN — NOT READY (ENTRY-CONDITION-FAILED)  ◀━━
       grade: grades/smc_cg_test_mode_bypass_test_GRADE.md
       log sha256: efdec4b9… (FAIL edges=0 under test_en_i)
   [x] Skill 3 prior PASS (advisory) — DFT claim no longer backed
   [ ] P1 Done (blocked on #4413 fix + re-sim + Skill 2 re-closure,
       or owner waiver/deferral of CG-DFT-TEST-BYPASS)
```

### Skill 2 re-audit — `SMC_CG_TEST_MODE_BYPASS_TEST` (2026-08-06)

- Kept FAIL log after `prim_clkgater` revert to `latched_en = i_en`
- Prior 3/3 PROVEN + signoff (log `15806e51…`, illicit `| i_te` model) **invalidated**
- Layer 2 not entered (`checkers: []`); Layer 1 + entry findings cite #4413
- Non-DFT P1 tests re-simmed PASS after revert (clk_running / static / dma / zeroer*)

## Owner constraints
- Model: **cursor-grok-4.5**
- **禁止 force/deposit**

## Skill 3 summary (signed)

| Item | Value |
|---|---|
| Mode | `CHECKBOX-MAPPING` |
| Result | **`PASS`** (advisory) → owner **Done** |
| Coverage | **19/19** required · inventory 23 · deferred 4 → P2 |
| Reverse disposition | **CLEAN** |
| Signoff | minshaoho @ 2026-08-05T14:28:00+08:00 |
| Final reviewer | [Relaunch Skill3 final review](8e56f4a0-dfe9-4a4c-ab22-fee895088f9f) |

## Sibling milestones

| Milestone | Pin | Board | Status |
|---|---|---|---|
| P0 | `SMC_CLOCK_GATING_P0_PIN.yaml` | `audit_status_smc_clock_gating_p0.md` | **Re-open Skill 2** (`smc_cg_dft_reset_bringup_test` FAIL) |
| P2 | `SMC_CLOCK_GATING_P2_PIN.yaml` | `audit_status_smc_clock_gating_p2.md` | **Done** (non-DFT; PASS after revert re-sim) |

## 下一 session 指令

```text
Owner disposition for P1 DFT hole (CG-DFT-TEST-BYPASS):
  A) Wait for https://github.com/tenstorrent/tt-oca-hw/issues/4413 fix
     → rebuild + re-sim smc_cg_test_mode_bypass_test
     → /dv_test_audit smc_cg_test_mode_bypass_test (fresh)
     → then /dv_peer_audit SMC_CLOCK_GATING P1 if DFT was in Skill3 denom
  B) Or Skill1 deferral / requirement-waiver of CG-DFT-TEST-BYPASS until model fix
     (do NOT treat FAIL as PROVEN; do NOT re-patch prim_clkgater from DV)

P0 sibling: same #4413 blocks SMCCGP0_003 — see audit_status_smc_clock_gating_p0.md
```
