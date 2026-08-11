<!-- SPDX-License-Identifier: Apache-2.0 -->
# SMC_CLOCK_GATING — Skill 3 實作步驟與結果

- **IP**: `SMC_CLOCK_GATING`
- **Milestone**: `P1`
- **Skill**: `dv_peer_audit` (Skill 3)
- **Board**: `hw/sys/smc/dv/tb/audit_status_smc_clock_gating.md`
- **狀態**: **P1 re-opened by independent re-review** — advisory **`FAIL`**（2 required REAL-GAP）。
  先前 advisory `PASS` + owner signoff `minshaoho` @ `2026-08-05T14:28:00+08:00` 仍在紀錄中，但已被本次
  fresh-context re-review 取代；board 是否改動由 owner 決定（Skill 3 無 signoff 權限）
- **最後更新**: 2026-08-05
- **Report**: `hw/sys/smc/dv/tb/SMC_CLOCK_GATING_PEER_AUDIT.md`
- **Reverse inventory**: `hw/sys/smc/dv/tb/SMC_CLOCK_GATING_REVERSE_FEATURE_INVENTORY.md`
- **Reverse inventory agent**: [Reverse inventory SMC CG](12817b98-d1fd-49bb-93f0-ac94f37ca022)
- **Skill 3 FAIL agent**: [Skill3 re-review reverse inv](acef077d-92a4-4ff4-8ca6-5856cfaed726)
- **Skill 3 final agent**: [Relaunch Skill3 final review](8e56f4a0-dfe9-4a4c-ab22-fee895088f9f)

## 1. 進入條件（閘門）

Skill 3 為 milestone / IP peer audit，應在以下就緒後啟動：

1. Skill 1 契約已 approved（已完成 — 見 `smc_cg_skill1.md`；含 INT-ZEROER amend）。
2. 計畫內 in-milestone cards 皆有 runnable test + kept log（Skill 1.5）。
3. 每張卡皆有 Skill 2 grade；目標為可接受的 closure（PROVEN / 已簽核 deferral），無未關閉 Blocking。
4. Owner 已決：
   - DMA FIND-001…005 rework + re-audit
   - `SMC_CG_TEST_MODE_BYPASS_TEST` 在 `prim_clkgater` `i_te` 修復後 PASS + audit
   - FIND-001 amend → `smc_zeroer_cg_indep_test` impl + Skill 2
5. Board 箭頭移至 Skill 3。

**進入時狀態（本 final re-review）**：8/8 Skill 2 grades 皆為 `EVIDENCE-CLOSED-AWAITING-SIGNOFF`；force/deposit owner constraint 已在各 grade 記為 clean；FL r2 approved with `INT-ZEROER-CG-INDEP`。

## 2. 執行步驟（本 run — final re-review after amend）

1. Fresh Skill 3 subagent（model `cursor-grok-4.5`；`run_id` ≠ 所有 prior participants，含先前 peer audits / reverse inventory / amend / indep impl+audit）。
2. Freeze hashes：pin / feature_list r2 / plan / cards / grades×8 / quality policy / testlist `clock.toml` / pinned SPEC paths / reverse inventory。
3. Mode 判定：`CHECKBOX-MAPPING`（approved FL + approved plan + approved cards；pin/plan milestone 皆為 P1）。
4. `closure.py` union-coverage：denominator **19 of 23**（4 signed `OUT-OF-MILESTONE` → `MILESTONE-DEFERRED` 排除）；**covered 19/19**；allocation intent / proof-class / cells 皆 clean；`INT-ZEROER-CG-INDEP` ← `CHK-ZINDEP-DECOUPLE`。
5. Cross-testcase / O2 / E3：無衝突；8 anchors 皆在 `hw/sys/smc/dv/testlists/clock.toml`；抽樣 PROVEN re-verify（17 tier-A + 10 tier-B；27/27 token 命中）；序列 force/deposit 掃描 clean。
6. Reverse inventory **diff**（不重推導）：candidate vs sealed FL r2 → packaging CLEAN；**INT-ZEROER-CG-INDEP → CLEAN**（cells match）。
7. 更新 `SMC_CLOCK_GATING_PEER_AUDIT.md`（含 **DELTA** vs prior FAIL）；`schema_check` → `valid`；`render_lint --kind peer-audit` → `agree`。
8. 更新 board + 本檔。

## 3. 結果

| 項目 | 結果 |
|---|---|
| Peer-audit run_id | `dv_peer_audit-SMC_CLOCK_GATING-P1-20260805T141900+0800-fresh-grok45-final` |
| Model | cursor / grok / 4.5 |
| Mode | `CHECKBOX-MAPPING` |
| Union coverage | **19/19** required keys PROVEN（inventory 23；excluded 4 → P2） |
| Reverse-diff disposition | **CLEAN** |
| Blocking gaps | 0 REAL-GAP / 0 BLOCKED |
| Advisory verdict | **`PASS`** |
| Report path | `hw/sys/smc/dv/tb/SMC_CLOCK_GATING_PEER_AUDIT.md` |
| schema_check / render_lint | `valid` / `agree` |

### DELTA vs prior Skill 3 (`…130700+0800…` / `FAIL` / CONFIRMED-OMISSION)

| Item | Prior | Now |
|---|---|---|
| FL | r1 · `interactions: []` | **r2 · INT-ZEROER-CG-INDEP** |
| Grades | 7 | **8** (+ indep 2/2 PROVEN) |
| Union coverage | 18/18 of 22 | **19/19 of 23** |
| Reverse disposition | CONFIRMED-OMISSION | **CLEAN** |
| FIND-001 | Blocking | **cleared** |
| Result | FAIL | **PASS** |

### 凍結 hashes（摘要）

| Artifact | content / file sha256 |
|---|---|
| feature_list (content_sha256) | `a22b78b40765efe57912f03934312f6b07a8582c351fa97c4ff0169d49bcca20` |
| testcase plan (content_sha256) | `23856412227c96ff9b0ac8e23dc49901183c598bad8b9e5e3d9a49914686edcd` |
| cards (content_sha256) | `c097f008eb7eb94183188970bf1c95c21977bc6c721f0b9bc65d735324834f69` |
| quality policy | `51a3357d9c31a018d69451b055bc956c089af26e1051368e25ce396c84ac2a75` |
| pin file (raw) | `d6800e9969c71c359b003b166f3004c7cde592843f2fadbd0653f9167c02b2f3` |
| reverse inventory (content_sha256) | `535b4a2d146baf5f1c822ecc0588516d0016b92fe18725e5d626558c711eef92` |
| reverse inventory (raw file) | `66bb946be0bd01be55378d109202ed8554e03714733f106e05fe6edbffee2a7d` |
| combined SPEC (concat) | `1dc1b2229d99fe54e4cd98d661b827d41cb40e213cfef1d9c5ac6d60d6cc9d26` |
| grade smc_zeroer_cg_indep_test | `e19a9e288bd1b764b9fa3c96cce9513d03a403e69384653ad57e769309ccf220` |

## 4. OUT-OF-MILESTONE 已知（不計 P1 closure）

來自 Skill 1 plan（已簽核；Skill 3 計為 `MILESTONE-DEFERRED`，不計 gap）：

- DMA-CG-CTRL.S5 / S6（hyst sweep / race）→ P2
- ZEROER-AXICLK-CG.S5 / ZEROER-REGCLK-CG.S5（race）→ P2

## 5. 下一動作

```text
# P1 Skill 3 advisory PASS — optional human signoff.
# When starting P2 (deferred races / hysteresis breadth):
/dv_vplan_gen \
  --pin hw/sys/smc/dv/tb/SMC_CLOCK_GATING_PIN.yaml \
  --milestone P2 \
  --planning-dir hw/sys/smc/dv/tb \
  --board hw/sys/smc/dv/tb/audit_status_smc_clock_gating.md
```

### 5.1 Reverse inventory candidate — 已產出並已 diff (2026-08-05)

Fresh, anchor-blind Skill 1 subagent (model `cursor / claude / sonnet-5`; run_id
`dv_vplan_gen-SMC_CLOCK_GATING-reverse-inventory-20260805T121100+0800-fresh-claude-sonnet5`)
produced the reverse feature inventory without ever opening
`SMC_CLOCK_GATING_PIN.yaml`, any `SMC_CLOCK_GATING_*.md` artifact, grade, peer-audit
report, or testlist. Inputs were the 9 pinned `hw/sys/smc/doc/` SPEC sources plus the
boundary text only.

| Item | Value |
|---|---|
| Output path | `hw/sys/smc/dv/tb/SMC_CLOCK_GATING_REVERSE_FEATURE_INVENTORY.md` |
| Status | `candidate` (no approvals, no allocations, no ticked boxes) |
| Features / scenarios / interactions | 6 / 18 / 1 |
| SF-* findings | 5 (`SF-001`..`SF-005`; 1 High, 2 Medium, 2 Low) |
| Skill 3 disposition (prior FAIL) | CONFIRMED-OMISSION on `INT-ZEROER-CG-INDEP` |
| Skill 3 disposition (this PASS) | **CLEAN** — FL r2 contains matching interaction + cells |

## 6. 獨立 re-review（2026-08-05，第三次 Skill 3 run）— advisory `FAIL`

由**不同 human + 不同 model** 在全新 read-only context 執行，未繼承任何前次 Skill 3 結論。

| 項目 | 結果 |
|---|---|
| Peer-audit run_id | `dv_peer_audit-SMC_CLOCK_GATING-P1-5aa9c629a618-fresh-opus5-rereview` |
| Reviewer / Model | `brucehsu` / anthropic · claude · opus-5（前次為 `minshaoho` 體系 / cursor · grok · 4.5） |
| Mode | `CHECKBOX-MAPPING`（pin `milestone: P1` == plan `milestone: P1`，閘門確認） |
| Denominator | inventory **23** − excluded **4** = required **19**；**covered 17** |
| REAL-GAP | **2** — `SMC-CG-ARCH-PARAMS.S3`、`CG-DFT-TEST-BYPASS.S2` |
| Findings | **5 🔴 Blocking · 12 🟠 Major · 2 🟡 Minor** |
| Reverse-diff disposition | **CLEAN**（key 層級 clean；已加做 cell 層級 diff，8 個 advisory P2 candidate cells） |
| Advisory verdict | **`FAIL`** |
| schema_check / render_lint | `valid` / `agree` |

### 6.1 為什麼與前次 `PASS` 不同

前次 run 的 coverage 算術（19/19）在 key 層級是對的；差異全部來自**前次未做或未通過的三類檢查**：

1. **契約 vs 實作 diff（intent mode `O2`）** — `SMC-CG-ARCH-PARAMS.S3`（enable-threshold，intent 明寫
   *"independent of the hysteresis count"*）實際上是用 `CLOCK_GATE_CONTROL.CG_HYSTERESIS` 這個**同一個欄位**
   量同一個 re-gate delay；`smc_static_cg_sanity_test_seq.py:22` 自己寫著
   `# SF-002: Enable Threshold == Hysteresis Control (same programmable field).`，且其值 {8,63} 是
   `.S1` {8,31,63} 的子集。一個量測被記到兩個 required key → `.S3` 判為 **REAL-GAP**，並 route 回 Skill 1
   （**不得**改測試）。
2. **前置條件（negative 需 positive control）** — `CG-DFT-TEST-BYPASS.S2` 從未在同一 run 內證明兩條
   Zeroer clock「本來會被 gate」；該檔的 `_program_cg` 是全 slate 唯一**沒有 CSR readback** 的版本，
   且從未檢查 `tb_zeroer_cg_en == 1` → **REAL-GAP**。（DMA leg 有 positive control，因此不對稱是客觀事實。）
3. **independent-evidence gate 是 derive 出來的，不是自宣告** — 17 個 `closure_tier: A` checker 只有
   單一 seed／單一 log；`build/runs/` 下 153 筆 `seed` 全為 `1`；多個 run dir 是同 seed 重跑且較早者為
   `FAIL`/`ERROR`。前次 report 卻在 `required: false` / `method: NOT-REQUIRED` / 全部 provenance 為 `null`
   的情況下寫 `gate_satisfied: true`。

另外兩項只有讀 working tree 才會看到：

- **F1 build-model identity** — `hw/common/och_prim_generic/rtl/prim_clkgater.sv:20` 已改為
  `latched_en = i_en | i_te;`（本檔 §1 item 4 已記錄為 owner 決定，並非偷改），但 8 份 grade 全部記
  `repository_revision: 2ecc7b227e39`（不含此修改）、`compile_inputs_sha256: null`、`exceptions: []`；
  `tb_top.sv` modified、13 個 cocotb 檔 untracked。→ 證據無法從任何可審的 revision 重建，且 shared common
  RTL 的正確性需 design owner 核可。
- **F5 always-pass proof line** — `CHK-TIMEOUT-PATHS` 全欄位皆為常數、沒有任何比較，卻列入兩支測試的
  required-token final gate。

### 6.2 驗證為 clean 的部分（前次結論在這些面向成立）

證據完整性 8/8 log hash 相符、**27/27** token 在宣告行號逐字命中、19/19 coverage artifact hash 相符、
0 個 `ERROR`/`FATAL`/`Traceback`；**未發現任何偽造或錯位的 evidence token**，故 §4.5 的
behaviour-class 全面 re-verify 升級路徑未觸發。cross-testcase claim matrix 無衝突；force-free clean
（唯二 DUT write 是 `rst_cool_ni` / `tb_test_en_i`，皆為 TB top-level input pin）；proof class 全為 `LIVE`
且無 over-credit；`[MERGED-EVIDENCE]` clean（interaction 拿自己的 credit，兩個 feature 各有單獨證明）；
8 anchors 皆已 enroll；card↔grade 的 `record_sha256` 全部對上，含 DMA card revision 2。

### 6.3 四個 OUT-OF-MILESTONE deferral 仍然有效

`DMA-CG-CTRL.S5/S6`、`ZEROER-AXICLK-CG.S5`、`ZEROER-REGCLK-CG.S5` 皆為 approved plan 的
`OUT-OF-MILESTONE` / `downstream_class: out-of-scope` 且有 `accepted_by`，映射為 `MILESTONE-DEFERRED`
（**不是** closure-blocking 的 `OUT-OF-SCOPE`），不計入 gap，`closes_at_milestone: P2`。

**但 P2 需連帶承接（F17）**：`DMA-CG-CTRL.S5` 唯一還沒被碰到的 cell 是 `dma_hysteresis_0`，而測試原始碼
記載 `hyst=0` "never runs under cg_enable"、`hyst=1` "loses the frontend→backend handoff"。此 row 因此
不是單純的 breadth deferral，而可能藏著一個設計問題。

### 6.4 交回 designer 的問題

1. `prim_clkgater` 的 `i_en | i_te` 是否為 shared common RTL 正確的 DFT bypass，可否 commit？
2. SF-002：是否存在獨立的 enable-threshold 欄位，或 `CG_HYSTERESIS` 是唯一的可程式延遲？
3. `CG_HYSTERESIS = 0` / `= 1` 的 DMA 行為是否符合預期？
4. `clk_periph` 是否會被 clock-gate？（pin boundary 說在 scope，但沒有任何 approved artifact 回答；
   approved `SF-003` 只答了 `clk_ref_i` / `clk_telemetry_i`，而 anchor-blind reverse derivation 有點到
   `clk_periph`。）

### 6.5 下一動作（取代 §5）

```text
# P1 尚未 closure。先處理 5 項 Blocking：
#   F3 → Skill 1 amend（S3 併入 S1 或改寫為獨立欄位）；勿改測試
#   F2 → smc_cg_test_mode_bypass_test_seq 補 Zeroer positive control + CSR readback，再跑 Skill 2
#   F1 → prim_clkgater 變更由 design owner 決定 commit/revert；tb + cocotb 原始碼 commit；
#         8 支測試在可審 revision 重跑，grade 記錄非 null 的 compile_inputs_sha256
#   F4 → 17 個 tier-A checker 補 reproduce-from-seed 或 independent observation
#   F5 → 移除 CHK-TIMEOUT-PATHS（或改為有實際比較後才 emit）
# 完成後重跑 Skill 2（受影響卡）→ 再跑 Skill 3 re-review。
```

---

*此檔為流程紀錄。Peer-audit advisory 正式結論以 `SMC_CLOCK_GATING_PEER_AUDIT.md` 為準。*
