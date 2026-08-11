<!-- SPDX-License-Identifier: Apache-2.0 -->
# SMC_CLOCK_GATING — Skill 1 實作步驟與結果

- **IP**: `SMC_CLOCK_GATING`
- **Milestone**: `P1`（pin field；boundary prose 仍提及 P0–P2 關閉語意）
- **Skill**: `dv_vplan_gen` (Skill 1)
- **Board**: `hw/sys/smc/dv/tb/audit_status_smc_clock_gating.md`
- **最後更新**: 2026-08-07

## 1. 目標

把 pinned SPEC 轉成可核准的驗證契約：feature_list → testcase plan → per-anchor checkbox cards → spec audit，並產出三角色 review packets。

## 2. 輸入（Pin）

| 項目 | 值 |
|---|---|
| Pin | `hw/sys/smc/dv/tb/SMC_CLOCK_GATING_PIN.yaml` |
| `pin_revision` | 1 |
| `confirmed_by` / `confirmed_at` | `minshaoho` / `2026-08-05T12:00:00+08:00` |
| `anchor_mode` | `augment` |
| Seed anchors | `smc_clk_multi_window_test`, `smc_clk_running_test`, `smc_i2c_cg_sanity_test`, `smc_pll_cgm_awm_config_test`, `smc_static_cg_sanity_test` |
| Policy | `/home/minshaoho/.claude/skills/dv_common/DV_QUALITY_POLICY.md` |

Pinned SPEC（9 份）:

- `hw/sys/smc/doc/{index,overview,clk_rst,port_table,dma,zeroer,periphs,fabric,memmap}.adoc`

## 3. 執行步驟

1. **Pin 確認** — owner 填妥 `confirmed_by` / `confirmed_at`、boundary、anchors、`anchor_mode=augment`。
2. **Fresh Skill 1 子 session** — `dv_vplan_gen`；`generated_by.run_id` ≈ `dv_vplan_gen-smc_clock_gating-fresh_subagent-20260805T080404+0800`（claude-sonnet）。
3. **Feature list 凍結** — `feature_list_frozen_at: 2026-08-05T08:20:00+08:00`。
4. **Human gates 全數簽核** — `approved_by: minshaoho` @ `2026-08-05T09:20:00+08:00`：
   - feature_list / testcase plan / VPLAN cards / SPEC·FEATURE·TESTCASE·CARD reviews 皆 `status: approved`。
5. **SF 處置** — SF-001/005 waived；SF-002/003/004/006 answered（含 SF-004：Zeroer `register_activity` = 任何 AXI4-Lite access）。
6. **產出寫入** `hw/sys/smc/dv/tb/`，並維護 `audit_status_smc_clock_gating.md`。

## 4. 產出物

| Artifact | Path | Reviewer |
|---|---|---|
| Feature list | `SMC_CLOCK_GATING_SPEC_FEATURE_LIST.md` | designer |
| Testcase plan | `SMC_CLOCK_GATING_TESTCASE_PLAN.md` | dv |
| Checkbox cards (VPLAN) | `SMC_CLOCK_GATING_VPLAN_DETAIL.md` | dv |
| Spec review | `SMC_CLOCK_GATING_SPEC_REVIEW.md` | designer |
| Feature review | `SMC_CLOCK_GATING_FEATURE_REVIEW.md` | designer |
| Testcase review | `SMC_CLOCK_GATING_TESTCASE_REVIEW.md` | dv |
| Card review | `SMC_CLOCK_GATING_CARD_REVIEW.md` | dv |
| Status board | `audit_status_smc_clock_gating.md` | dv |

核准鏈（Skill 1 之後、進 Skill 1.5 之前）：

1. **designer** — feature 語意（`FEATURE_REVIEW`）與 SPEC 問題（`SPEC_REVIEW` / SF）。
2. **dv** — testcase set + OWNS + gap accept（`TESTCASE_REVIEW`），再核准 card 機制（`CARD_REVIEW`）。

兩邊都簽完，card 才是 `status: approved`，Skill 1.5 才可開工。

## 5. 舉例：Skill 1.5 如何 create test

以下以核准卡 `SMC_DMA_CG_ACTIVITY_TEST`（anchor `smc_dma_cg_activity_test`）為例，說明 Skill 1.5（`dv_test_impl`）如何把一張 card 變成可跑的 test。

### 5.1 進入條件（缺一不可）

- Card 與 parent testcase record 皆 `status: approved`（Skill 1 human gates 已過）。
- Card 上的 `SF-*` blockers 皆 `answered` / `waived`；無 `TBD-`。
- 選定 env + `top_tb`（本例：`cocotb` + `hw/sys/smc/dv/tb/tb_top.sv`）。
- Hard constraint：proof path 禁止 DUT force/deposit；不得削弱 checker。

### 5.2 Create 流程（舉例）

```
Approved card
      |
      v
Entry gates OK?
      | yes
      v
Env: cocotb + tb_top
      |
      v
Map card steps / checkers → seq phases + CHK tokens
      |
      v
Write seq + test + testlist entry
      |
      v
run_dv.py (one seed) --> kept log
      |
      v
All CHK-* tokens present in log?  --yes--> handoff Skill 2
                                 --no --> rework 1.5 (or escalate Skill 1)
```

```bash
# Example command
module load verilator/5.050 gcc/13.2.1
python3 tools/dv/run_dv.py \
  --dut smc_wrapper \
  --items smc_dma_cg_activity_test \
  --tool verilator \
  --seed 1
```

### 5.3 本例典型產出

| 項目 | 說明 |
|---|---|
| Sequence | `hw/sys/smc/dv/cocotb/seq_lib/smc_dma_cg_activity_test_seq.py` |
| Test wrapper | `hw/sys/smc/dv/cocotb/tests/smc_dma_cg_activity_test.py` |
| Testlist | `hw/sys/smc/dv/testlists/clock.toml` 掛入 `smc_dma_cg_activity_test` |
| Kept log | `hw/sys/smc/dv/build/runs/<run_dir>/…` + sha256 |
| Evidence | 每個 checker 印一次 `CHK-<NAME>: …`（含 `CHK-NONVAC`） |

Skill 1.5 **不評分、不寫 PROVEN**；最強聲明只是：「run 完成且 kept log 出現這些 tokens」。正式 grade 交給 Skill 2。

### 5.4 什麼時候需要 DV review / approve

| 時機 | 誰 | 核准什麼 | 不過會怎樣 |
|---|---|---|---|
| Skill 1 結束後 | **dv**（在 designer feature/SPEC 簽完之後） | `TESTCASE_REVIEW`：testcase set、OWNS 分割、逐條 accept OUT-OF-MILESTONE / gap | Skill 1.5 entry gate 拒絕 |
| Skill 1 結束後 | **dv** | `CARD_REVIEW`：步驟、checker、fail_on、觀測點是否可實作 | 不可對未核准 card 寫 code |
| Skill 1.5 跑完 tokens OK | **dv**（選用，常併入 Skill 2） | 實作是否忠於 card、env/testlist 是否正確 | 可進 Skill 2；但契約疑慮應先回 Skill 1 |
| Skill 2 grade 後 | **dv** owner signoff | grade = `EVIDENCE-CLOSED` 才算單卡關閉 | 停留 `AWAITING-SIGNOFF` / `NOT-READY` |
| 實作發現 card 不可觀測 / SPEC 錯 | **dv** 不可自行改契約 | 退回 Skill 1 amend → **designer + dv** 再 approve 變更部分 | 禁止在 1.5 削弱 checker 或改 expectation |

一句話：**DV approve 發生在「能不能寫這張卡」與「這張卡的證據能不能算關閉」**；Skill 1.5 本身只負責把已核准卡實作成有 token 的 kept log。
