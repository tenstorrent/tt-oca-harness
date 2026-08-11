<!-- SPDX-License-Identifier: Apache-2.0 -->
# SMC_CLOCK_GATING — Skill 1.5 / Skill 2 實作步驟與結果

- **IP**: `SMC_CLOCK_GATING`
- **Milestone**: `P1`
- **Skills**: `dv_test_impl` (1.5) → `dv_test_audit` (2)
- **Board**: `hw/sys/smc/dv/tb/audit_status_smc_clock_gating.md`
- **Grades dir**: `hw/sys/smc/dv/tb/grades/`
- **最後更新**: 2026-08-05

## 1. Skill 1.5 — 實作波次

### 1.1 共用 TB / helper 變更

| 項目 | 說明 |
|---|---|
| `tb_top.sv` lifts | `tb_dma_cg_en`, `tb_dma_gated_clk`, `tb_dma_{,frontend_,backend_}busy`, `tb_dma_gater_busy`, `tb_zeroer_{cg_en,gated_axi_clk,gated_reg_clk,busy}`, `tb_test_en_i` |
| Helper | `hw/sys/smc/dv/cocotb/env/smc_cg_obs_utils.py`（及/或 `seq_lib/smc_cg_obs_utils.py`） |
| Testlist | `clock.toml` 掛入新 anchors；`smc_static_cg_sanity_test` 自 `deferred.toml` 移除 |
| Sim model fix (owner 2026-08-05) | `hw/common/och_prim_generic/rtl/prim_clkgater.sv`：`latched_en = i_en \| i_te`（修正忽略 `i_te`） |

### 1.2 各卡實作結果

| Card | Impl 結果 | Kept log (run_dir under `hw/sys/smc/dv/build/runs/`) | Notes |
|---|---|---|---|
| `SMC_DMA_CG_ACTIVITY_TEST` | PASS tokens（**card r2**） | `20260805_032809__verilator__smc_dma_cg_activity_test` · sha256 `c448f12f…` | S3 keep-enabled；Skill 2 **5/5 EVIDENCE-CLOSED**（§2.2c） |
| `SMC_CLK_RUNNING_TEST` | PASS tokens（rework FIND-001..003） | `20260805_035801__verilator__smc_clk_running_test` · sha256 `807b1266…` | addr_map + exact 16/16 + derived tokens；Skill 2 **2/2 EVIDENCE-CLOSED**（§2.6b） |
| `SMC_CLK_MULTI_WINDOW_TEST` | PASS tokens（rework FIND-001 addr_map） | `20260805_035610__verilator__smc_clk_multi_window_test` · sha256 `557f7d0f…` | cells hyst 8/31/63；Skill 2 **2/2 EVIDENCE-CLOSED**（§2.3b） |
| `SMC_STATIC_CG_SANITY_TEST` | PASS tokens（rework FIND-001..003） | `20260805_035854__verilator__smc_static_cg_sanity_test` · sha256 `3d21022c…` | addr_map + exact 16/16 + derived tokens；Skill 2 **3/3 EVIDENCE-CLOSED**（§2.7b） |
| `SMC_ZEROER_AXICLK_CG_TEST` | PASS tokens（rework FIND-001..005） | `20260805_040006__verilator__smc_zeroer_axiclk_cg_test` · sha256 `d32840f6…` | gate_off_lat + busy post-resume every-cycle + exact 16 |
| `SMC_ZEROER_REGCLK_CG_TEST` | PASS tokens（rework FIND-001..004） | `20260805_040056__verilator__smc_zeroer_regclk_cg_test` · sha256 `9ae9ce78…` | `tb_zeroer_bus_active` lift；hyst=0；1cyc + access window |
| `SMC_CG_TEST_MODE_BYPASS_TEST` | PASS tokens（rework FIND-001..003） | `20260805_035029__verilator__smc_cg_test_mode_bypass_test` · sha256 `15806e51…` | addr_map + `edges==16` via `count_enabled_at_smc_rise` + derived tokens；Skill 2 re-audit **3/3 EVIDENCE-CLOSED**（§2.5b） |
| `SMC_ZEROER_CG_INDEP_TEST` | PASS tokens（Skill 1.5） | `20260805_055443__verilator__smc_zeroer_cg_indep_test` · sha256 `1c39f29a…` | INT-ZEROER-CG-INDEP both cells；Skill 2 **2/2 EVIDENCE-CLOSED**（§2.9） |

Impl 子 session：[Impl remaining 6 CG cards](0d6ea0d3-ff19-4d61-864e-fa7bac66f03e)（5 PASS + 1 BLOCKED）；DMA 初版由 parent/impl session；DMA rework：[Rework DMA CG FIND-001..005](3b4c3b1e-79fc-40a3-9d01-3928e7023c46)；INT-ZEROER impl：[Impl zeroer CG indep test](7731943f-dcb5-4dae-a13c-7e3ea0301648)。

### 1.3 BLOCKED (B) 根因與處置

**根因**：`prim_clkgater` 宣告 `i_te` 但未使用；上層已接 `test_en_i`→`i_te`，sim 無法 OR test enable。

**Owner 決策 (2026-08-05)**：修 sim model（非 waive）。已改：

```systemverilog
latched_en = i_en | i_te;
```

**DONE 2026-08-05**：`--rebuild` 後 `smc_cg_test_mode_bypass_test` PASS；CHK-DFT-* / CHK-NONVAC 皆出現於 kept log（不削弱 fail_on；無 DUT-internal force）。

## 2. Skill 2 — 稽核波次

規則：fresh context；`auditor.run_id ≠ authoring run_id`；不同 model。

### 2.1 Grade 總表

| Anchor | Grade file | Verdict | PROVEN | Status |
|---|---|---|---|---|
| `smc_dma_cg_activity_test` | `grades/smc_dma_cg_activity_test_GRADE.md` | **EVIDENCE-CLOSED-AWAITING-SIGNOFF** | 5/5 | card r2 keep-enabled；fresh grok audit（§2.2c） |
| `smc_clk_running_test` | `grades/smc_clk_running_test_GRADE.md` | **EVIDENCE-CLOSED-AWAITING-SIGNOFF** | 2/2 | grok-4.5 re-audit rework log；prior FIND-001..003 CLOSED；force/deposit clean（§2.6b） |
| `smc_clk_multi_window_test` | `grades/smc_clk_multi_window_test_GRADE.md` | **EVIDENCE-CLOSED-AWAITING-SIGNOFF** | 2/2 | grok-4.5 re-audit rework log；prior FIND-001 CLOSED；force/deposit clean（§2.3b） |
| `smc_static_cg_sanity_test` | `grades/smc_static_cg_sanity_test_GRADE.md` | **EVIDENCE-CLOSED-AWAITING-SIGNOFF** | 3/3 | grok-4.5 re-audit rework log；prior FIND-001..003 CLOSED；force/deposit clean（§2.7b） |
| `smc_zeroer_axiclk_cg_test` | `grades/smc_zeroer_axiclk_cg_test_GRADE.md` | **EVIDENCE-CLOSED-AWAITING-SIGNOFF** | 5/5 | grok-4.5 re-audit rework log；prior FIND-001..005 CLOSED；force/deposit clean（§2.8） |
| `smc_zeroer_regclk_cg_test` | `grades/smc_zeroer_regclk_cg_test_GRADE.md` | **EVIDENCE-CLOSED-AWAITING-SIGNOFF** | 5/5 | grok-4.5 re-audit rework log；prior FIND-001..004 CLOSED；force/deposit clean（§2.4b） |
| `smc_cg_test_mode_bypass_test` | `grades/smc_cg_test_mode_bypass_test_GRADE.md` | **EVIDENCE-CLOSED-AWAITING-SIGNOFF** | 3/3 | grok-4.5 re-audit rework log；prior FIND-001..003 CLOSED；force/deposit clean（§2.5b） |
| `smc_zeroer_cg_indep_test` | `grades/smc_zeroer_cg_indep_test_GRADE.md` | **EVIDENCE-CLOSED-AWAITING-SIGNOFF** | 2/2 | fresh grok-4.5 audit；force/deposit clean（§2.9） |

### 2.2 `smc_dma_cg_activity_test` 初版稽核（詳細）

- **Auditor**: [Audit DMA CG test](1d7a8a24-a6a4-4420-8e18-8207345eba87)
- **run_id**: `dv_test_audit-SMC_DMA_CG_ACTIVITY_TEST-1b206f12-158a-4a4a-ba53-1d7124b0dd76`
- **Model**: anthropic/claude/sonnet-5
- **MODE**: CHECKBOX；entry PASS 認證 Layer 2
- **Overall**: **1/5 PROVEN · NOT-READY**

| Checker | Grade |
|---|---|
| CHK-DMA-GATE-OFF | INSUFFICIENT-EVIDENCE |
| CHK-DMA-WAKEUP-FRONTEND | INSUFFICIENT-EVIDENCE |
| CHK-DMA-WAKEUP-BACKEND | INSUFFICIENT-EVIDENCE |
| CHK-DMA-GATING-DISABLED | INSUFFICIENT-EVIDENCE |
| CHK-NONVAC | PROVEN |

| Finding | Sev | 摘要 |
|---|---|---|
| FIND-001 | Blocking | Backend wakeup token 硬編碼 `resume_cyc=0`，非實測 |
| FIND-002 | Major | S3 未隔離 backend-only（frontend_busy 未 assert=0） |
| FIND-003 | Major | Register 位址手抄 hex，未自 generated header import |
| FIND-004 | Minor | `_await_gated_rising` dead code |
| FIND-005 | Minor | GATE-OFF token 印常數而非 measured toggle |

**Owner 決策**：授權 `/dv_test_impl` rework 關閉 FIND-001…005（已完成；見 §2.2b）。

### 2.2b `smc_dma_cg_activity_test` re-audit（rework log）

- **run_id**: `dv_test_audit-SMC_DMA_CG_ACTIVITY_TEST-10faace5-21b0-45c4-a54a-c3a41b7c6914`
- **Model**: cursor/grok/4.5（≠ authoring `dv_test_impl-SMC_DMA_CG_ACTIVITY_TEST-3b4c3b1e-79fc-40a3-9d01-3928e7023c46`）
- **Kept log**: `20260805_030401__verilator__smc_dma_cg_activity_test` · sha256 `e3240af0…`（verified）
- **MODE**: CHECKBOX；entry PASS
- **Overall**: **4/5 PROVEN · NOT-READY**

| Checker | Grade |
|---|---|
| CHK-DMA-GATE-OFF | PROVEN |
| CHK-DMA-WAKEUP-FRONTEND | PROVEN |
| CHK-DMA-WAKEUP-BACKEND | INSUFFICIENT-EVIDENCE |
| CHK-DMA-GATING-DISABLED | PROVEN |
| CHK-NONVAC | PROVEN |

| Prior FIND | Status |
|---|---|
| FIND-001…005（初版） | **全部 CLOSED**（addr map / measured tokens / fe=0 / `_await_gated_rising` wired） |

| New FIND | Sev | 摘要 |
|---|---|---|
| FIND-001 | Blocking | S3 在 clock 已 free-run 後才量 `resume_cyc`；`resume_within_1cyc` 對 card 的 gated-off→backend resume 主張為 vacuous |

**下一步（已嘗試）**：Skill 1.5 非 vacuous S3 SETUP（gated-off 證明 → arm-before-start → 禁 early_rise）→
kept log `20260805_031312` sha256 `d0c1b224…` **FAIL (B)**：`resume@smc=8` 早於 `backend-only@smc=10`。
CHK 未弱化；token 未發出。需 **Skill 1 修 card**（「keeps」vs gated-off→backend resume）後才能再 1.5 / audit。

### 2.2c `smc_dma_cg_activity_test` card r2 re-impl + Skill 2 re-audit

- **Card**: revision 2 · `record_sha256 b1f928140c5123ae1298877e726f91b309ba15c3b287fb236f723b3582d51653`
- **Kept log**: `20260805_032809__verilator__smc_dma_cg_activity_test` · sha256 `c448f12feaa5d2a7098e95531fd1ecfb5ca937adc2ba894f21ea97c06b0a1ab1`
- **S3 proof shape**: free-running after activity wake → `backend_busy=1 && frontend_busy=0` →
  every-cycle toggles for entire window (`edges=8 window=8`); fence term
  `backend-only-keep-enabled-observed`. LIVE via `tb_dma_gated_clk` /
  `tb_dma_frontend_busy` / `tb_dma_backend_busy` (no force/deposit).
- **Tokens**: 5/5 once（GATE-OFF / WAKEUP-FRONTEND / WAKEUP-BACKEND / GATING-DISABLED / NONVAC）
- **Skill 2 (fresh)**: `run_id` `dv_test_audit-SMC_DMA_CG_ACTIVITY_TEST-8d57b4e6-2d89-4119-af45-91ca33dc3245`
  · model cursor/grok/4.5 · ≠ authoring `dv_test_impl-SMC_DMA_CG_ACTIVITY_TEST-cfed1faa-1b63-498e-81d5-885bfc9fe47b`
- **MODE**: CHECKBOX；entry PASS；**5/5 PROVEN · EVIDENCE-CLOSED-AWAITING-SIGNOFF**
- **DELTA vs §2.2b**: prior r1 FIND-001 (vacuous gated-off→resume) **CLOSED by card r2** keep-enabled
  contract + matching impl; CHK-DMA-WAKEUP-BACKEND upgraded INSUFFICIENT-EVIDENCE → PROVEN.
  §2.2b grade not treated as authoritative for r2.

### 2.3 `smc_clk_multi_window_test` 初版稽核（superseded）

- **run_id**: `dv_test_audit-SMC_CLK_MULTI_WINDOW_TEST-d8bfa6e7-4100-4217-992b-e26754984b96`
- **Model**: cursor/grok/4.5（≠ authoring `dv_test_impl-SMC_CLK_MULTI_WINDOW_TEST-0d6ea0d3`）
- **Kept log**: `20260805_015203__verilator__smc_clk_multi_window_test` · sha256 `a7fcb1a3…`
- **MODE**: CHECKBOX；entry PASS
- **Overall**: **1/2 PROVEN · NOT-READY**（superseded by §2.3b）

| Checker | Grade |
|---|---|
| CHK-HYST-WINDOW | INSUFFICIENT-EVIDENCE |
| CHK-NONVAC | PROVEN |

| Finding | Sev | 摘要 |
|---|---|---|
| FIND-001 | Major | `smc_cg_obs_utils.py` 手抄 CSR/DMA 位址（latent-rot；值正確） |

### 2.3b `smc_clk_multi_window_test` re-audit（rework log）

- **run_id**: `dv_test_audit-SMC_CLK_MULTI_WINDOW_TEST-df05f6072436480d82eb71249e3a5c17`
- **Model**: cursor/grok/4.5（≠ authoring `dv_test_impl-SMC_CLK_MULTI_WINDOW_TEST-95afef5e-2325-4e52-878d-d6236ae7bfa7`）
- **Kept log**: `20260805_035610__verilator__smc_clk_multi_window_test` · sha256 `557f7d0f739f7fb0d81f68137db11e4b8b414b20eddc896e41cb7c42e809349c`（verified）
- **MODE**: CHECKBOX；entry PASS
- **Overall**: **2/2 PROVEN · EVIDENCE-CLOSED-AWAITING-SIGNOFF**
- **Force/deposit**: **clean**（僅 CSR frontdoor + JTAG memory write + passive `tb_dma_*` obs）
- **DELTA**: prior FIND-001 **CLOSED**（`smc_cg_obs_utils` → `smc_addr_map`）；CHK-HYST-WINDOW UPGRADED → PROVEN
- schema_check `valid` · render_lint `agree`

| Checker | Grade |
|---|---|
| CHK-HYST-WINDOW | PROVEN |
| CHK-NONVAC | PROVEN |

### 2.4 `smc_zeroer_regclk_cg_test` 初版稽核（superseded）

- **Auditor**: [Grok audit Zeroer regclk CG](03345617-ff49-4a00-b79b-b1ce0f9bb870)
- **run_id**: `dv_test_audit-SMC_ZEROER_REGCLK_CG_TEST-70b2f9b7-f242-4232-becd-208f1b1cbd00`
- **Model**: cursor/grok/4.5
- **Kept log**: `20260805_022637__verilator__smc_zeroer_regclk_cg_test` · sha256 `4a648b13…`
- **MODE**: CHECKBOX；entry PASS
- **Overall**: **1/5 PROVEN · NOT-READY**（superseded by §2.4b）
- LIVE checkers 皆 INSUFFICIENT-EVIDENCE（FIND-001…004：addr / 1cyc / every-cycle / token literals）

### 2.4b `smc_zeroer_regclk_cg_test` re-audit（rework log）

- **run_id**: `dv_test_audit-SMC_ZEROER_REGCLK_CG_TEST-b7e506bf-b720-4295-82e9-dca594294dbf`
- **Model**: cursor/grok/4.5（≠ authoring `dv_test_impl-SMC_ZEROER_REGCLK_CG_TEST-95afef5e-2325-4e52-878d-d6236ae7bfa7`；≠ prior auditor `…70b2f9b7…`）
- **Kept log**: `20260805_040056__verilator__smc_zeroer_regclk_cg_test` · sha256 `9ae9ce78cb840329b87af06f2af9463aab869def1c155b779d3b87d3e7882a27`（verified）
- **MODE**: CHECKBOX；entry PASS
- **Overall**: **5/5 PROVEN · EVIDENCE-CLOSED-AWAITING-SIGNOFF**
- **Force/deposit**: **clean**（僅 CSR frontdoor + TB `rst_cool_ni` pin + passive `tb_zeroer_*` obs）
- **DELTA**: prior FIND-001..004 **全部 CLOSED**（`smc_addr_map` + measured 1cyc/access-window + exact `==16` + derived tokens）；四個 LIVE checkers UPGRADED → PROVEN
- schema_check `valid` · render_lint `agree`

| Checker | Grade |
|---|---|
| CHK-ZREG-GATE-OFF-IDLE | PROVEN |
| CHK-ZREG-ACTIVITY-ENABLE | PROVEN |
| CHK-ZREG-DISABLE-CG | PROVEN |
| CHK-ZREG-RESET-OVERRIDE | PROVEN |
| CHK-NONVAC | PROVEN |

### 2.5 `smc_cg_test_mode_bypass_test` 初版稽核（superseded）

- **run_id**: `dv_test_audit-SMC_CG_TEST_MODE_BYPASS_TEST-fb8894e9c1014087b46cc7b35dafc9b0`
- **Model**: cursor/grok/4.5（≠ authoring `dv_test_impl-SMC_CG_TEST_MODE_BYPASS_TEST-4a52330c-5a48-4316-b82d-d43fb13ddce1`）
- **Kept log**: `20260805_033431__verilator__smc_cg_test_mode_bypass_test` · sha256 `91c3600d…`（verified）
- **MODE**: CHECKBOX；entry PASS
- **Overall**: **1/3 PROVEN · NOT-READY**（superseded by §2.5b）
- **Force/deposit**: **clean**（僅 `tb_test_en_i` pin + CSR frontdoor + passive obs）

| Checker | Grade |
|---|---|
| CHK-DFT-BYPASS-DMA | INSUFFICIENT-EVIDENCE |
| CHK-DFT-BYPASS-ZEROER | FAILED |
| CHK-NONVAC | PROVEN |

| Finding | Sev | 摘要 |
|---|---|---|
| FIND-001 | Major | `smc_cg_obs_utils.py` 手抄 CSR 位址（latent-rot；值正確） |
| FIND-002 | Major | `edges >= IDLE-1`；kept log `reg_edges=15` 仍 PASS |
| FIND-003 | Minor | token 硬編碼 `toggles_every_cycle=1` |

### 2.5b `smc_cg_test_mode_bypass_test` re-audit（rework log）

- **run_id**: `dv_test_audit-SMC_CG_TEST_MODE_BYPASS_TEST-6ec5b8e65cd54fdeb374526fcc7ba25a`
- **Model**: cursor/grok/4.5（≠ authoring `dv_test_impl-SMC_CG_TEST_MODE_BYPASS_TEST-916949e4-ce77-48fb-9e77-730455010537`）
- **Kept log**: `20260805_035029__verilator__smc_cg_test_mode_bypass_test` · sha256 `15806e51…`（verified）
- **MODE**: CHECKBOX；entry PASS
- **Overall**: **3/3 PROVEN · EVIDENCE-CLOSED-AWAITING-SIGNOFF**
- **Force/deposit**: **clean**（僅 `tb_test_en_i` pin + CSR frontdoor + passive obs）
- **DELTA**: prior FIND-001..003 **全部 CLOSED**；DMA/Zeroer LIVE checkers UPGRADED → PROVEN
- schema_check `valid` · render_lint `agree`

| Checker | Grade |
|---|---|
| CHK-DFT-BYPASS-DMA | PROVEN |
| CHK-DFT-BYPASS-ZEROER | PROVEN |
| CHK-NONVAC | PROVEN |

### 2.6 `smc_clk_running_test` 初版稽核（superseded）

- **run_id**: `dv_test_audit-SMC_CLK_RUNNING_TEST-7e4a2c19-6b8d-4f31-9a05-3d8f61b2e4c7`
- **Model**: anthropic/claude/sonnet-5
- **Kept log**: `20260805_014647__verilator__smc_clk_running_test` · sha256 `cc496fb7…`
- **MODE**: CHECKBOX；entry PASS
- **Overall**: **1/2 PROVEN · NOT-READY**（superseded by §2.6b）

| Checker | Grade |
|---|---|
| CHK-ACTIVE-RUNNING | INSUFFICIENT-EVIDENCE |
| CHK-NONVAC | PROVEN |

| Finding | Sev | 摘要 |
|---|---|---|
| FIND-001 | Major | `smc_cg_obs_utils.py` 手抄 CSR/DMA 位址（latent-rot；值正確） |
| FIND-002 | Major | `edges >= ACTIVE_WINDOW-1`；kept log `dma_edges=15` 仍 PASS |
| FIND-003 | Minor | token 硬編碼 `toggles_every_cycle=1` / `axi_clk_gated=1` |

### 2.6b `smc_clk_running_test` re-audit（rework log）

- **run_id**: `dv_test_audit-SMC_CLK_RUNNING_TEST-75e9d256c2bd40a8837f1aa4258bb201`
- **Model**: cursor/grok/4.5（≠ authoring `dv_test_impl-SMC_CLK_RUNNING_TEST-95afef5e-2325-4e52-878d-d6236ae7bfa7`）
- **Kept log**: `20260805_035801__verilator__smc_clk_running_test` · sha256 `807b1266708bd851f04e28c5cb0a6075dd88f11bb3fc27265225321a45d5f945`（verified）
- **MODE**: CHECKBOX；entry PASS
- **Overall**: **2/2 PROVEN · EVIDENCE-CLOSED-AWAITING-SIGNOFF**
- **Force/deposit**: **clean**（僅 CSR frontdoor + JTAG memory write + passive `tb_dma_*` / `tb_zeroer_*` obs）
- **DELTA**: prior FIND-001..003 **全部 CLOSED**（`smc_addr_map` + exact `==16` + derived tokens）；CHK-ACTIVE-RUNNING UPGRADED → PROVEN
- schema_check `valid` · render_lint `agree`

| Checker | Grade |
|---|---|
| CHK-ACTIVE-RUNNING | PROVEN |
| CHK-NONVAC | PROVEN |

### 2.7 `smc_static_cg_sanity_test` 初版稽核（superseded）

- **run_id**: `dv_test_audit-SMC_STATIC_CG_SANITY_TEST-f0040264-a114-4598-93a6-4d0d6d666f40`
- **Model**: cursor/grok/4.5（≠ authoring `dv_test_impl-SMC_STATIC_CG_SANITY_TEST-0d6ea0d3-ff19-4d61-864e-fa7bac66f03e`）
- **Kept log**: `20260805_021959__verilator__smc_static_cg_sanity_test` · sha256 `9a982374…`
- **MODE**: CHECKBOX；entry PASS
- **Overall**: **1/3 PROVEN · NOT-READY**（superseded by §2.7b）

| Checker | Grade |
|---|---|
| CHK-MODULE-GATING | INSUFFICIENT-EVIDENCE |
| CHK-ENABLE-THRESHOLD | INSUFFICIENT-EVIDENCE |
| CHK-NONVAC | PROVEN |

| Finding | Sev | 摘要 |
|---|---|---|
| FIND-001 | Major | `smc_cg_obs_utils.py` 手抄 CSR/DMA 位址（latent-rot；值正確） |
| FIND-002 | Major | `edges >= IDLE-1`；kept log `zeroer_ungated_edges=15` 仍 PASS |
| FIND-003 | Minor | token 硬編碼 `continuous_idle_toggles=1` / `independent=1` |

### 2.7b `smc_static_cg_sanity_test` re-audit（rework log）

- **run_id**: `dv_test_audit-SMC_STATIC_CG_SANITY_TEST-493b545b-2608-47f6-8c06-eb04fad4ad0e`
- **Model**: cursor/grok/4.5（≠ authoring `dv_test_impl-SMC_STATIC_CG_SANITY_TEST-95afef5e-2325-4e52-878d-d6236ae7bfa7`）
- **Kept log**: `20260805_035854__verilator__smc_static_cg_sanity_test` · sha256 `3d21022c1749bc3d0ae9252fad6f8b0059c53198d93050e0f4ba55a240c1d806`（verified）
- **MODE**: CHECKBOX；entry PASS
- **Overall**: **3/3 PROVEN · EVIDENCE-CLOSED-AWAITING-SIGNOFF**
- **Force/deposit**: **clean**（僅 CSR frontdoor + JTAG memory write + passive `tb_dma_*` / `tb_zeroer_*` obs）
- **DELTA**: prior FIND-001..003 **全部 CLOSED**（`smc_addr_map` + exact `==16` + derived tokens）；CHK-MODULE-GATING / CHK-ENABLE-THRESHOLD UPGRADED → PROVEN
- schema_check `valid` · render_lint `agree`

| Checker | Grade |
|---|---|
| CHK-MODULE-GATING | PROVEN |
| CHK-ENABLE-THRESHOLD | PROVEN |
| CHK-NONVAC | PROVEN |

## 3. 後續步驟（本檔持續更新）

1. ~~DMA card r2 Skill 2~~ → **5/5 EVIDENCE-CLOSED-AWAITING-SIGNOFF**（§2.2c；[Grok audit DMA card r2](e138d551-b274-46dc-ac5f-1a2eff977408)）。
2. ~~Skill 1.5 bypass after `prim_clkgater` fix~~ → PASS tokens；~~Skill 2~~ → **1/3 NOT-READY**（§2.5）。
3. ~~Skill 1.5 bypass FIND-001..003 rework~~ → PASS tokens `20260805_035029` `15806e51…`。
4. ~~`/dv_test_audit` re-audit bypass~~ → **3/3 EVIDENCE-CLOSED-AWAITING-SIGNOFF**（§2.5b）。
5. ~~Skill 1.5 rework wave ×5~~ → PASS tokens（[Rework wave 5](95afef5e-2325-4e52-878d-d6236ae7bfa7)；no force；no (B)）。
6. ~~`/dv_test_audit` re-audit multi_window~~ → **2/2 EVIDENCE-CLOSED-AWAITING-SIGNOFF**（§2.3b；log `20260805_035610` `557f7d0f…`）。
7. ~~`/dv_test_audit` re-audit clk_running~~ → **2/2 EVIDENCE-CLOSED-AWAITING-SIGNOFF**（§2.6b；log `20260805_035801` `807b1266…`）。
8. ~~`/dv_test_audit` re-audit static_cg~~ → **3/3 EVIDENCE-CLOSED-AWAITING-SIGNOFF**（§2.7b；log `20260805_035854` `3d21022c…`）。
9. ~~`/dv_test_audit` re-audit z-reg~~ → **5/5 EVIDENCE-CLOSED-AWAITING-SIGNOFF**（§2.4b；log `20260805_040056` `9ae9ce78…`）。
10. ~~`/dv_test_audit` re-audit z-axi~~ → **5/5 EVIDENCE-CLOSED-AWAITING-SIGNOFF**（§2.8；log `20260805_040006` `d32840f6…`）。
11. ~~`/dv_test_audit` `smc_zeroer_cg_indep_test`~~ → **2/2 EVIDENCE-CLOSED-AWAITING-SIGNOFF**（§2.9；log `20260805_055443` `1c39f29a…`）。
12. **Now**: 全卡 EVIDENCE-CLOSED（含 INT-ZEROER）→ `/dv_peer_audit` re-review（見 `smc_cg_skill3.md`）。

### 1.4 Rework wave ×5 摘要（Skill 1.5，2026-08-05）

| FIND 類 | 處置（不削弱 checker） |
|---|---|
| ADDRESS-FROM-AUTHORITATIVE-MAP | `smc_cg_obs_utils` / seqs → `smc_addr_map` |
| `>= IDLE/ACTIVE-1` | `count_enabled_at_smc_rise` / pair → exact `== N` |
| hardcoded token `=1` | derived booleans from measured counts |
| gate-off / resume 1cyc | measured latency；z-reg 用 `tb_zeroer_bus_active` T0 |
| busy/access every-cycle | post-resume window exact enable hits |

Helper 新增：`count_enabled_pair_at_smc_rise`、`measure_gate_off_latency`。TB：`tb_zeroer_bus_active`（passive assign）。

## 4. Session / 代理索引

| Role | Agent link | 結果 |
|---|---|---|
| Impl ×6 | [Impl remaining 6 CG cards](0d6ea0d3-ff19-4d61-864e-fa7bac66f03e) | 5 PASS tokens；bypass BLOCKED(B) |
| Audit DMA 初版 | [Audit DMA CG test](1d7a8a24-a6a4-4420-8e18-8207345eba87) | NOT-READY 1/5 |
| Rework DMA | [Rework DMA CG FIND-001..005](3b4c3b1e-79fc-40a3-9d01-3928e7023c46) | kept log `20260805_030401` |
| Re-audit DMA | grok-4.5 `10faace5-21b0-45c4-a54a-c3a41b7c6914` | NOT-READY 4/5；prior FIND closed；new S3 FIND-001 |
| DMA S3 SETUP | [Fix DMA S3 SETUP vacuous](eb8fb41c-409b-4a4e-9c5e-b1a6f57b4c00) | **(B) BLOCKED** log `20260805_031312` `d0c1b224…` |
| DMA r2 impl | [Impl DMA card r2 S3 keep](cfed1faa-1b63-498e-81d5-885bfc9fe47b) | PASS tokens log `20260805_032809` `c448f12f…` |
| DMA r2 audit | [Grok audit DMA card r2](e138d551-b274-46dc-ac5f-1a2eff977408) | **5/5 EVIDENCE-CLOSED** |
| Bypass impl | [Impl CG test mode bypass](4a52330c-5a48-4316-b82d-d43fb13ddce1) | PASS tokens (`--rebuild`) |
| Bypass audit | grok-4.5 `fb8894e9c1014087b46cc7b35dafc9b0` | NOT-READY 1/3；force/deposit clean |
| Bypass rework | [Rework bypass FIND-001..003](916949e4-ce77-48fb-9e77-730455010537) | PASS tokens `15806e51…`；exact 16/16 |
| Bypass re-audit | [Re-audit bypass after rework](faca001a-75ce-4712-a1ab-428b32e08594) | **3/3 EVIDENCE-CLOSED** |
| Rework wave ×5 | [Rework wave 5 NOT-READY CG](95afef5e-2325-4e52-878d-d6236ae7bfa7) | **DONE** — 5/5 PASS tokens；no (B) |
| Multi-win re-audit | [Audit multi-window rework log](aae2af38-16e7-47bf-b93f-b44f7356dc94) | **2/2 EVIDENCE-CLOSED** |
| Clk-running re-audit | grok-4.5 `75e9d256c2bd40a8837f1aa4258bb201` | **2/2 EVIDENCE-CLOSED** |
| Static CG re-audit | grok-4.5 `493b545b-2608-47f6-8c06-eb04fad4ad0e` | **3/3 EVIDENCE-CLOSED** |
| Audit z-reg 初版 | [Grok audit Zeroer regclk CG](03345617-ff49-4a00-b79b-b1ce0f9bb870) | NOT-READY 1/5（superseded） |
| Z-reg re-audit | grok-4.5 `b7e506bf-b720-4295-82e9-dca594294dbf` | **5/5 EVIDENCE-CLOSED** |
| Z-axi re-audit | grok-4.5 `a3f529c4-02ac-43fb-a1d8-907e6147b65a` | **5/5 EVIDENCE-CLOSED** |
| INT-ZEROER impl | [Impl zeroer CG indep test](7731943f-dcb5-4dae-a13c-7e3ea0301648) | PASS tokens `1c39f29a…` |
| INT-ZEROER Skill 2 | [Relaunch Skill2 indep audit](6999b2cf-a8d0-4a3f-84fb-1f1cea692cfb) | **2/2 EVIDENCE-CLOSED** |

### 2.8 `smc_zeroer_axiclk_cg_test` re-audit（rework log）

- **run_id**: `dv_test_audit-SMC_ZEROER_AXICLK_CG_TEST-a3f529c4-02ac-43fb-a1d8-907e6147b65a`
- **Model**: cursor/grok/4.5（≠ authoring `dv_test_impl-SMC_ZEROER_AXICLK_CG_TEST-95afef5e-2325-4e52-878d-d6236ae7bfa7`；≠ prior auditor `…-a559a49b-…`）
- **Kept log**: `20260805_040006__verilator__smc_zeroer_axiclk_cg_test` · sha256 `d32840f62eaba3585678e27560c396fdfaafd797a0d227b9dd1722aeba25222e`（verified）
- **MODE**: CHECKBOX；entry PASS
- **Overall**: **5/5 PROVEN · EVIDENCE-CLOSED-AWAITING-SIGNOFF**
- **Force/deposit**: **clean**（僅 CSR/Zeroer frontdoor + JTAG memory seed + `rst_cool_ni` pin + passive `tb_zeroer_*` obs）
- **DELTA**: prior FIND-001..005 **全部 CLOSED**（`smc_addr_map` + gate_off_latency≤1 + busy every-cycle + exact 16/16 + derived tokens）；all four LIVE checkers UPGRADED → PROVEN
- schema_check `valid` · render_lint `agree`

| Checker | Grade |
|---|---|
| CHK-ZAXI-GATE-OFF-IDLE | PROVEN |
| CHK-ZAXI-BUSY-ENABLE | PROVEN |
| CHK-ZAXI-DISABLE-CG | PROVEN |
| CHK-ZAXI-RESET-OVERRIDE | PROVEN |
| CHK-NONVAC | PROVEN |

### 2.9 `smc_zeroer_cg_indep_test` Skill 2 audit（fresh）

- **run_id**: `dv_test_audit-SMC_ZEROER_CG_INDEP_TEST-24e034821e5542e98d84f70c280bbd56`
- **Model**: cursor/grok/4.5（≠ authoring `dv_test_impl-SMC_ZEROER_CG_INDEP_TEST-7731943f-dcb5-4dae-a13c-7e3ea0301648`）
- **Card**: revision 1 · `record_sha256 46ad998bc85c45be9ff0180d25267976c65047f0d983dec945caf0e9eebee833`
- **Parent plan**: r1 · `af246ccaaec1265a4b108f970b90726c58b7506ea70db7292939077909a69da0`（recomputed match）
- **Kept log**: `20260805_055443__verilator__smc_zeroer_cg_indep_test` · sha256 `1c39f29a1c81d83950d23ab4e38423bf62b9dfeceb8b1fd19b0cba178fc8f56a`（verified）
- **MODE**: CHECKBOX；entry PASS
- **Overall**: **2/2 PROVEN · EVIDENCE-CLOSED-AWAITING-SIGNOFF**
- **Force/deposit**: **clean**（CSR/Zeroer frontdoor + JTAG fabric seed + passive `tb_zeroer_*` obs）
- **Coverage**: `INT-ZEROER-CG-INDEP` DIRECTED cells `axi-active-reg-idle-decoupled` + `reg-active-axi-idle-decoupled` both hit（S1 window=39；S2 post_resume=2）
- schema_check `valid` · render_lint `agree`

| Checker | Grade |
|---|---|
| CHK-ZINDEP-DECOUPLE | PROVEN |
| CHK-NONVAC | PROVEN |

---

*此檔為流程紀錄。正式 grade 以 `tb/grades/*_GRADE.md` 為準；勿把「PASS tokens OK」當成 PROVEN。*
