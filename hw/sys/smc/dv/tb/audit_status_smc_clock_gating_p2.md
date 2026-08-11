# SMC_CLOCK_GATING_P2 — DV 品質流程狀態圖

- **IP**: `SMC_CLOCK_GATING_P2`
- **Milestone**: `P2`
- **Pin**: `hw/sys/smc/dv/tb/SMC_CLOCK_GATING_P2_PIN.yaml` (confirmed by minshaoho @
  2026-08-05T14:58:00+08:00, pin_revision 1)
- **最後更新**: 2026-08-05
- **目前狀態**: **P2 Done** — Skill 3 `INSUFFICIENT-EVIDENCE` owner-accepted by `minshaoho` @ `2026-08-05T21:40:00+08:00`（4/4 COVERED、reverse CLEAN；F1/F2 經 review 接受為 process debt）
  三個 P2 testcase 全部 4/4 PROVEN 已簽署，`closure.py` 回報 4/4 required key 皆 COVERED、0 個
  real gap、reverse-diff **CLEAN**——但獨立 fresh peer-audit reviewer 發現 **2 個 🔴 Blocking**
  finding 擋下 closure certificate：**F1 `[BUILD-MODEL-IDENTITY]`**（`prim_clkgater.sv` 與
  `tb_top.sv` 仍未 commit，其中 `prim_clkgater.sv` 的未 commit diff 把 `latched_en = i_en` 改成
  `latched_en = i_en | i_te`——即共用 RTL 的 DFT test-enable bypass，本 session 用 `git diff`
  獨立覆核屬實；3 份 P2 grade 記載的 `repository_revision` 皆不含此變更，`compile_inputs_sha256`
  全 null，此為延續自 P1 gate 自己 F1 的同一未解殘留，跨了一個 milestone 仍未解）；**F2
  `[REPRESENTATIVE-EVIDENCE]`**（12 個 `closure_tier: A` checker 全部只有單一 seed/單一 log，
  沒有任何 `REPRODUCE-FROM-SEED` 或 `INDEPENDENT-OBSERVATION` 證據，`gate_satisfied` 依規則衍生為
  `false`）。另有 3 個 🟠 Major（F3 兩個 checker token 欄位非真量測、F4 `SMC-CG-ZEROER-AXICLK.S1`
  的 approved feature triad 聲稱涵蓋「outstanding write response 排空」但目前 required_cells 未
  測到此維度、F5 quality policy 仍是 SMU_SEP 範疇非 SMC）+ 3 個 🟡 Minor。依 owner standing
  order：非 PASS/PASS-WITH-FINDINGS，**未** 蓋章 Done，回報 blocker 給 owner。Report:
  `hw/sys/smc/dv/tb/SMC_CLOCK_GATING_P2_PEER_AUDIT.md`（`schema_check.py` valid，
  `render_lint.py --kind peer-audit` agree）。**下一手：見下方「下一 session 指令」**
- **Parent P1 board**: `audit_status_smc_clock_gating.md` (P1 Done)
- **Board path**: `dv/smc/tb/audit_status_smc_clock_gating_p2.md`

圖例：`[x]` 完成 ｜ `[!]` 阻擋中 ｜ `[ ]` 未開始 ｜ `◀━━ 現在在這裡`

---

## Skill 1 — dv_vplan_gen（產生驗證合約）

```
        ┌─────────────────────────────────────────────────┐
        │  Fresh-context gate                             │
   [x]  │  route = fresh-subagent (top-level workflow)     │
        │  seal  = fresh-subagent (Step 1 derivation)      │
        └────────────────────┬────────────────────────────┘
                             │
        ┌────────────────────▼────────────────────────────┐
        │  Step 0  Pin gate                               │
   [x]  │  pin_file.py validate → status: confirmed        │
        └────────────────────┬────────────────────────────┘
                             │
        ┌────────────────────▼────────────────────────────┐
        │  Step 1  推導 feature_list (+ spec audit)        │
   [x]  │  anchors SEALED；只讀 9 個 pinned spec 檔案       │
        │  → 3 features / 4 scenarios / 0 interactions；   │
        │    6 SF findings (SF-001 Critical: axi_cg_snoop  │
        │    無法從 SPEC 導出 feature)                      │
        └────────────────────┬────────────────────────────┘
                             │
        ┌────────────────────▼────────────────────────────┐
   [x]  │  Step 2  凍結 feature_list，才解封 anchors        │
        │  frozen_at: 2026-08-05T15:09:00+08:00            │
        └────────────────────┬────────────────────────────┘
                             │
        ┌────────────────────▼────────────────────────────┐
        │  Step 3  推導 testcase set → TESTCASE_PLAN       │
   [x]  │  anchor_mode: augment；3 testcases，全部 origin:  │
        │  given（extend 既有 anchor）；0 NEW；unallocated  │
        │  = []（已在 packet 中明講原因）                    │
        └────────────────────┬────────────────────────────┘
                             │
        ┌────────────────────▼────────────────────────────┐
   [x]  │  Step 4  steps → checkboxes → VPLAN_DETAIL       │
        │  3 cards，每卡 3-4 steps / 4 checkers（budget 內） │
        └────────────────────┬────────────────────────────┘
                             │
        ┌────────────────────▼────────────────────────────┐
   [x]  │  Step 5  manifest stamp + schema_check（全部 valid）│
        └────────────────────┬────────────────────────────┘
                             │
        ┌────────────────────▼────────────────────────────┐
   [x]  │  Step 6  三份 review packet + render_lint = agree │
        └────────────────────┬────────────────────────────┘
                             │
        ┌────────────────────▼────────────────────────────┐
   [x]  │  Step 7  收尾報告：把每個 gap 明講出來             │
        └────────────────────┬────────────────────────────┘
                             │
                             ▼
                    ┌─────────────────┐
                    │  人的核准 gate   │  ◀━━ 現在在這裡
                    └─────────────────┘
```

### 人的核准 gate（Skill 1 之後，鏈狀順序）

| # | 角色 | 核准什麼 | 狀態 |
|---|---|---|---|
| 1 | Designer / Architect | feature 語意（`SMC_CLOCK_GATING_P2_FEATURE_REVIEW.md`） | `[ ]` 未開始 |
| 2 | DV owner | testcase set + OWNS 分割 + **逐條 accept 每個 gap**（`SMC_CLOCK_GATING_P2_TESTCASE_REVIEW.md`；本輪 unallocated=0，但 pinned anchor `smc_clk_multi_window_test` 未被分配，需 DV owner 確認） | `[ ]` 未開始 |
| 3 | DV owner | card 機制（`SMC_CLOCK_GATING_P2_CARD_REVIEW.md`；2 張卡帶 blocker SF-004/SF-005） | `[ ]` 未開始 |
| 4 | Spec owner | `SF-001`..`SF-006`（`SMC_CLOCK_GATING_P2_SPEC_REVIEW.md`；SF-001/004/005 為 Critical） | `[ ]` 未開始 |

---

## 下游 Skills（Skill 1 核准後）

```
   [x]  Skill 1.5  dv_test_impl   ── SMC_CG_P2_001 (smc_dma_cg_activity_test)
                                     已 extend + PASS (verilator seed=1); coverage-artifact
                                     缺口已補上並重跑 (run 20260805_092045)
   [x]                             SMC_CG_P2_002 (smc_zeroer_axiclk_cg_test)
                                     rev1 曾 extend + RUN → FAIL against rev1 contract (now
                                     superseded); owner amend (ii) 完成 → card rev2 approved;
                                     已針對 rev2 重新實作 `_p2_race_cell` (mid-busy vs inter-busy
                                     gap 拆分) 並重跑 → PASS (verilator seed=1, run 20260805_093933)
   [x]                             SMC_CG_P2_003 (smc_zeroer_regclk_cg_test)
                                     已 extend + PASS (verilator seed=1)
                     │
   [x]  Skill 2    dv_test_audit  ── SMC_CG_P2_001: RE-AUDIT 4/4 PROVEN —
                                     EVIDENCE-CLOSED-AWAITING-SIGNOFF（已簽署）
   [x]                             SMC_CG_P2_003: 4/4 PROVEN —
                                     EVIDENCE-CLOSED-AWAITING-SIGNOFF（已簽署）
   [x]                             SMC_CG_P2_002: rev2 首次稽核 4/4 PROVEN —
                                     EVIDENCE-CLOSED-AWAITING-SIGNOFF（已簽署）
                     │
   [x]  Skill 3    dv_peer_audit  ── INSUFFICIENT-EVIDENCE → owner **Done**
                                     4/4 required key COVERED、reverse-diff CLEAN，但 2 個
                                     Blocking finding（F1 build-model identity、F2 獨立性證據
                                     缺口）擋下 closure ◀━━ 現在在這裡，等 owner 清除 blocker
```

### Skill 2 稽核紀錄 — SMC_CG_P2_001（smc_dma_cg_activity_test）— RE-AUDIT（第二輪，已簽署）

- **Grade report**: `hw/sys/smc/dv/tb/grades/smc_dma_cg_activity_test_P2_GRADE.md`（原地覆寫第一輪
  NOT READY 結果；與既有已結案的 P1 grade `smc_dma_cg_activity_test_GRADE.md` 分開，未讀取該檔作為
  本輪權威依據、未覆寫、未動）
- **Verdict**: `4/4 PROVEN — EVIDENCE-CLOSED-AWAITING-SIGNOFF`（`schema_check.py` → `valid`；
  `render_lint.py --kind grade-report` → `agree`）
- **Entry gate**: PASS — card r1 `f30a819e…` 與 testcase plan 父紀錄 r1 `98e628cd…`（兩者皆用
  `manifest.py record-hash` 重新計算比對相符）；新 kept log（run `20260805_092045`）sha256
  `3bc69b7a…`；cocotb `TESTS=1 PASS=1 FAIL=0 SKIP=0`，零未解釋 ERROR/FATAL/Traceback；
  force/deposit 檢查乾淨
- **Delta from round 1**（kept log `dcc3f062…` → `3bc69b7a…`）：owner 在
  `smc_dma_cg_activity_test_seq.py` 新增 `_emit_p2_hyst_sweep_coverage_report()`，於 P2 hyst sweep
  結束後把 `required_cells`/`cells_hit`/`satisfied` 寫入
  `functional-coverage-report.json`（`logs/` 與 `coverage/` 皆有一份，sha256 `f7c4ebc1…`，
  `satisfied: true`），並在 kept log 新增一行 `P2_COVERAGE_ARTIFACT` 佐證路徑與 cells。
  `CHK-DMA-HYST-SWEEP` 由 `INSUFFICIENT-EVIDENCE` 轉為 `PROVEN`；`FIND-001`
  `[COVERAGE-ARTIFACT-UNRESOLVED]` 關閉，本輪 `findings: []`。其餘 3 個 checker
  （`CHK-DMA-HYST-RACE`、`CHK-NONVAC`、`CHK-TIMEOUT-PATHS`）token 內容/行號/實作路徑與第一輪完全
  相同，僅因新 run 而 log sha256 改變。
- **PROVEN (4/4)**: `CHK-DMA-HYST-SWEEP`、`CHK-DMA-HYST-RACE`、`CHK-NONVAC`（P2 版）、
  `CHK-TIMEOUT-PATHS`
- **Waiver carryforward**: 第一輪 grade 的 `waivers: []` 本就是空帳本，本輪無任何 waiver 可延續
- **Human signoff**: `minshaoho` @ `2026-08-05T17:21:00+08:00`（4/4 PROVEN、0 findings，依使用者
  standing order 自動記錄簽署）

### Skill 2 稽核紀錄 — SMC_CG_P2_003（smc_zeroer_regclk_cg_test）— 首次稽核（已簽署）

- **Grade report**: `hw/sys/smc/dv/tb/grades/smc_zeroer_regclk_cg_test_P2_GRADE.md`（新檔，與既有
  已結案的 P1 grade `smc_zeroer_regclk_cg_test_GRADE.md`——`ip: SMC_CLOCK_GATING`、card
  `SMC_CLOCK_GATING_VPLAN_DETAIL.md`——完全分開，未讀取該檔作為本輪權威依據、未覆寫、未動）
- **Verdict**: `4/4 PROVEN — EVIDENCE-CLOSED-AWAITING-SIGNOFF`（`schema_check.py` → `valid`；
  `render_lint.py --kind grade-report` → `agree`）
- **Entry gate**: PASS — card r1 `93666c6c…` 與 testcase plan 父紀錄 r1 `49c886a7…`（兩者皆用
  `manifest.py record-hash` 重新計算比對相符）；kept log sha256 `f6d7df5f…`；cocotb
  `TESTS=1 PASS=1 FAIL=0 SKIP=0`，零未解釋 ERROR/FATAL/Traceback；force/deposit 檢查乾淨
- **Blocker `SF-004` 解除確認**：front matter `findings[SF-004].status: answered`，附有具體
  `resolution.note`（與整份文件 `status: approved` 同一 `approved_by`/`approved_at` 戳記）；並用
  `schema_check.py SMC_CLOCK_GATING_P2_VPLAN_DETAIL.md --spec-audit
  SMC_CLOCK_GATING_P2_SPEC_REVIEW.md --plan SMC_CLOCK_GATING_P2_TESTCASE_PLAN.md` 機械交叉檢查 →
  `{"status": "valid", "problems": []}`，未觸發 blocked-by-finding 問題。**文件衛生觀察（非
  finding）**：`SMC_CLOCK_GATING_P2_SPEC_REVIEW.md` 檔尾的 render 區塊「Questions awaiting your
  answer:」仍把 SF-002/003/004/006 全部列為 `STATUS: open`，與 front matter 的 `status: answered`
  不一致，看起來是 owner 答覆後未重新產生該渲染區塊；已在 grade report 中記錄，留給下一次修訂
  `SPEC_REVIEW.md` 的人處理，不影響本 testcase 的評分。
- **PROVEN (4/4)**: `CHK-ZEROER-REGCLK-UNGATE`、`CHK-ZEROER-REGCLK-ACCESS-COMPLETE`、`CHK-NONVAC`
  （P2 版）、`CHK-TIMEOUT-PATHS`
- **Waiver carryforward**: 本輪之前不存在 `smc_zeroer_regclk_cg_test_P2_GRADE.md`，故無任何
  waiver 可延續；`waivers: []` 為全新空帳本
- **Human signoff**: `minshaoho` @ `2026-08-05T17:21:00+08:00`（4/4 PROVEN、0 findings，依使用者
  standing order 自動記錄簽署）

### Skill 2 稽核紀錄 — SMC_CG_P2_002（smc_zeroer_axiclk_cg_test）— rev2 首次稽核（已簽署）

- **Grade report**: `hw/sys/smc/dv/tb/grades/smc_zeroer_axiclk_cg_test_P2_GRADE.md`（新檔，與既有
  已結案的 P1 grade `smc_zeroer_axiclk_cg_test_GRADE.md`——`ip: SMC_CLOCK_GATING`、card
  `SMC_CLOCK_GATING_VPLAN_DETAIL.md` revision 1——完全分開，未讀取該檔作為本輪權威依據、未覆寫、
  未動）
- **Verdict**: `4/4 PROVEN — READY`（`recommendation: EVIDENCE-CLOSED-AWAITING-SIGNOFF`）
- **Entry gate**: PASS — card `SMC_CG_P2_002` **revision 2** `record_sha256 7716914f…`（用
  `manifest.py` `record_hash` 重新計算比對相符，`current: true`、`status: approved`）與 testcase
  plan 父紀錄 `SMC_CG_P2_002` revision 1 `record_sha256 53791893…`（重新計算比對相符，
  `derived_from.testcase_record_sha256` 逐字相符，父紀錄 `current: true`/`status: approved`）；
  kept log sha256 `5d8c44ab9eeb46dd701ddf35452be8158a81e178a278eaf841a541ea6497e377`
  （`sha256sum` 重新計算，與 owner 提供值完全相符；rev1 的 FAIL log `20260805_091625` 依指示
  視為 STALE，未讀取、未作為本輪證據）；cocotb `TESTS=1 PASS=1 FAIL=0 SKIP=0`，全 716 行 kept log
  掃描零未解釋 ERROR/FATAL/Traceback；force/deposit 檢查乾淨（P2 code path 僅 frontdoor CSR +
  passive 觀察）。
- **PROVEN (4/4)**: `CHK-ZEROER-AXICLK-NOGLITCH`（3 個必測 cell `mid_busy_glitches=0`，
  inter-busy gap 25/26/27 cycles 依 rev2 契約合法記錄、不計分）、`CHK-ZEROER-AXICLK-COMPLETION`
  （same-cycle/1-after `completed=1` 計分；1-before evidence-only 依 SF-005 carve-out 不下判定）、
  `CHK-NONVAC`（P2 版，fence 順序逐字相符卡片 `proof`）、`CHK-TIMEOUT-PATHS`（三個宣告 bound 皆有
  fail-on-expiry path 與 last-state 診斷，`expired=0`）
- **Waiver carryforward**: 本輪之前不存在 `smc_zeroer_axiclk_cg_test_P2_GRADE.md`，故無任何
  waiver 可延續；`waivers: []` 為全新空帳本
- **Human signoff**: `minshaoho` @ `2026-08-05T18:04:00+08:00`（4/4 PROVEN、0 findings，依 owner
  standing order「if all PROVEN, signoff minshaoho」自動記錄簽署）
- **里程碑狀態**：`SMC_CG_P2_001`/`SMC_CG_P2_002`/`SMC_CG_P2_003` 三個 P2 testcase 現在**全部**
  4/4 PROVEN 並已簽署——Skill 3 milestone gate 的前置條件已滿足。

### Skill 3 milestone gate 紀錄 — SMC_CLOCK_GATING_P2 / P2（INSUFFICIENT-EVIDENCE，未 Done）

- **Report**: `hw/sys/smc/dv/tb/SMC_CLOCK_GATING_P2_PEER_AUDIT.md`（`schema_check.py` → `valid`；
  `render_lint.py --yaml ... --kind peer-audit` → `agree`，兩者皆由本 session 獨立重跑覆核）
- **Reviewer**: fresh subagent，`run_id
  dv_peer_audit-SMC_CLOCK_GATING_P2-9e41b7d2-20260805T182000+0800`，對本 IP 無任何 authoring/
  Skill-2-audit/discussion 的 carryover（本 session 執行 Skill 2 對 `SMC_CG_P2_002` 的稽核，因此
  由獨立 fresh subagent 執行 Skill 3 判斷，滿足 skill 的 fresh-context 硬性前提，而非由本 session
  自己判斷）
- **Mode**: `CHECKBOX-MAPPING`（feature_list + plan + cards 皆 approved）
- **Denominator**: `inventory_keys 4 − excluded_keys 0 = milestone_required_keys 4`；
  `covered_keys 4`（`closure.py`：`holes: []`、`unsatisfied_coverage: []`、`unknown_keys: []`、
  `allocation_intent_diff` 全空、`merged_evidence_risk: []`）
- **Reverse-diff（Step 5，強制）**: 由另一個獨立 fresh subagent（僅讀 9 份 pinned SPEC，未見
  feature_list/plan/cards/anchor 名稱）derive 5 個 candidate feature、17 個 candidate scenario；
  peer-audit reviewer 逐項 disposition 後判定 **`CLEAN`**——全部落在(a) 已於 P1 關閉、(b) 本 pin
  boundary 明文排除的 P3 corner、(c) 已被 `SF-*` 回答/waived 的項目，或(d) 已獨立轉為 finding F4
  的「已涵蓋 key 但特定維度未測」，**沒有任何一項需要新增必測 key**
- **Result**: **`INSUFFICIENT-EVIDENCE`**（非 `PASS`/`PASS-WITH-FINDINGS`/`FAIL`）——4/4 必測 key
  皆有真實 `LIVE` proof、0 個 real gap，但 12/12 credit checker 皆屬 `closure_tier: A` 且皆不滿足
  policy 對該 tier 要求的獨立性證據 gate（同 log/同 seed），加上共用 RTL 未 commit 導致
  build-model identity 無法重建；依 skill 判定規則，「必要 checker 缺獨立性證據」對應
  `INSUFFICIENT-EVIDENCE`，非 `FAIL`（因為沒有 real gap、沒有 false-PROVEN）
- **🔴 Blocking findings（2 個，擋下 closure）**：
  - **F1 `[BUILD-MODEL-IDENTITY]`**：`hw/common/och_prim_generic/rtl/prim_clkgater.sv` 與
    `hw/sys/smc/dv/tb/tb_top.sv` 仍在 working tree 未 commit（本 session 用 `git status`/
    `git diff` 獨立覆核屬實）——`prim_clkgater.sv` 的未 commit diff 把
    `latched_en = i_en` 改成 `latched_en = i_en | i_te`（DFT test-enable 直接 OR 進共用
    clock-gater cell 的 enable path），這是**共用 RTL**、超出 DV 可自行核准的範圍；3 份 P2 grade
    記載的 `repository_revision` 皆不含此變更，`compile_inputs_sha256` 全 null（axiclk 那份連
    `model_fingerprint`/`result.json` 都缺），故沒有任何一份 grade 能鎖定「實際跑的到底是哪個
    elaborated model」。**與 P1 gate 自己的 F1 完全同一問題，跨了一個 milestone 仍未解決。**
    Owner: SMC design owner（共用 RTL）+ DV owner。Closure 條件：design owner 覆核並 commit 或
    revert 該 RTL 變更；`tb_top.sv` 與 6 個 P2 cocotb 原始檔一併 commit；3 份 P2 grade 用該
    reviewed 狀態重新記錄 `repository_revision` + 非 null `compile_inputs_sha256`/
    `model_fingerprint` 並重跑。
  - **F2 `[REPRESENTATIVE-EVIDENCE]`**：3 份 P2 grade 報告的 12 個 `closure_tier: A` checker
    全部只有 `seeds: [1]`、單一 log，沒有任何 `REPRODUCE-FROM-SEED`（獨立 run_id + 獨立 log hash +
    build fingerprint）或 `INDEPENDENT-OBSERVATION`（獨立 observer + hashed artifact）證據，故
    `gate_satisfied` 依規則衍生為 `false`。Owner: DV owner。Closure 條件：12 個 tier-A checker
    各自補上 reproduce-from-seed 重跑或 independent-observation 證據。
- **🟠 Major（3 個，非阻擋）**：F3 `CHK-DMA-HYST-RACE` 的 `zero_glitches=1` 為硬編字面值、
  `CHK-ZEROER-REGCLK-ACCESS-COMPLETE` 的 `match=` 欄位只是重述已 assert 過的條件（皆未削弱底層
  fail-on gate，僅 token 欄位本身不是獨立量測）；F4 approved feature_list 對
  `SMC-CG-ZEROER-AXICLK` 的 triad 聲稱涵蓋「直到所有 write response 收到」但目前 required_cells
  只測 trigger timing，未測 outstanding-response 排空維度（reverse-diff 獨立發現同一缺口）；F5
  quality policy 仍是 `SMU_SEP` 範疇，非 SMC 專用（延續自 P1 gate 的同一觀察）。
- **🟡 Minor（3 個）**：F6 `SPEC_REVIEW.md` render 區塊過期（與 Skill 2 `SMC_CG_P2_003` 稽核已獨立
  發現的同一問題）；F7 `TESTCASE_REVIEW.md` 附錄引用的 plan hash 過期；F8 reverse-diff 產生者的
  `run_id`/model 身份未提供，reviewer 誠實記為 `null`/`unknown` 而非捏造。
- **Verified clean**：evidence 完整性（12/12 token 逐行覆核無誤植/無造假）、無 cross-testcase
  conflict、force-free、proof-class 誠實、allocation-intent 無 unmet/accidental、regression
  enrollment 齊全、card/grade 對應正確（`SMC_CG_P2_002` 舊 revision 正確排除）、SF-004/SF-005
  blocker 確認已解除、timeout 皆 fail-closed、位址皆走 authoritative map。
- **`smc_clk_multi_window_test`**：reviewer 獨立確認非問題（plan + `SF-001` 皆已明文記載此
  anchor 在本 pin 邊界內不擁有任何 scenario）。
- **Owner 決策（依 standing order）**：Result 非 `PASS`/`PASS-WITH-FINDINGS`，**未蓋章 Done**。
  已回報 2 個 Blocking blocker 給 owner（見上），milestone 尚未 closure-certified。

### Skill 1.5 實作紀錄 — SMC_CG_P2_001（smc_dma_cg_activity_test）

- **Card**: `SMC_CG_P2_001` rev 1 · `record_sha256 f30a819ece07cac193724665274c74e6512a18c0771b7fde11375464acf5489a`
  （`SMC_CLOCK_GATING_P2_VPLAN_DETAIL.md`，approved by minshaoho @2026-08-05T15:52:00+08:00）
- **手法**: extend 既有 `smc_dma_cg_activity_test_seq.py`（additive `_p2_extension()`，P1 的 4 個
  checker + `CHK-NONVAC` 字面 token 原樣保留未動，讓已結案的 P1 grade 繼續有效）
- **新增**: P2-S1 SETUP/baseline、P2-S2 hyst 全範圍 sweep `{0,1,32,63,64}`（用生成的
  `CG_HYST_SHIFT`/`CG_HYST_MASK` 對 6-bit 欄位寫值，64 走真實硬體截斷 0 的路徑，非 TB 特判）、
  P2-S3 activity-reassert race（early/back-to-back/last-cycle-before-expiry，全程逐 cycle 監看
  `tb_dma_gated_clk` 零 glitch）、P2-S4 timeout-path 證據
- **Files**:
  - `hw/sys/smc/dv/cocotb/seq_lib/smc_dma_cg_activity_test_seq.py`（provenance header 加上 P2 卡片區塊；新增 `_p2_extension` 與量測 helper）
  - `hw/sys/smc/dv/cocotb/tests/smc_dma_cg_activity_test.py`（provenance header 同步；`required` token 清單 additive 加入 4 個 P2 token）
- **Run**: `module load verilator/5.050 gcc/13.2.1 && python3 tools/dv/run_dv.py --dut smc_wrapper --items smc_dma_cg_activity_test --tool verilator --seed 1`
- **Result**: `PASS` · `TESTS=1 PASS=1 FAIL=0 SKIP=0` · exit_code 0 · 無 ERROR/FATAL/Traceback
  - Kept log: `hw/sys/smc/dv/build/runs/20260805_084816__verilator__smc_dma_cg_activity_test/smc_dma_cg_activity_test/logs/smc_dma_cg_activity_test.log`
    （`sha256 dcc3f062d0fee9f017858a6147a0d230188c131e472c5200f8853664de50d2d6`）
- **Token checklist**（kept log 內逐行可 grep）：
  - `[x]` `CHK-DMA-GATE-OFF`（P1，原樣未動，L932）
  - `[x]` `CHK-DMA-WAKEUP-FRONTEND`（P1，原樣未動，L1046）
  - `[x]` `CHK-DMA-WAKEUP-BACKEND`（P1，原樣未動，L1174）
  - `[x]` `CHK-DMA-GATING-DISABLED`（P1，原樣未動，L1212）
  - `[x]` `CHK-NONVAC`（P1 版本，原樣未動，L1214）
  - `[x]` `CHK-DMA-HYST-SWEEP`（P2 新增，L1386：`gap0..gap64` 全 5 格皆與程式化 hyst 值精確相符）
  - `[x]` `CHK-DMA-HYST-RACE`（P2 新增，L1438：`zero_glitches=1` `final_countdown_restarted_full=40`）
  - `[x]` `CHK-TIMEOUT-PATHS`（P2 新增，L1442：`expired=0`，四個 bounded-wait 的 bound 皆已標出）
  - `[x]` `CHK-NONVAC`（P2 版本，L1443：`SETUP < ACTIVITY-BASELINE < SWEEP-COMPLETE(5-cells) <
    RACE-REASSERT-EARLY < RACE-REASSERT-LAST < PASS`）
- **Guardrails 遵守**: 全程 frontdoor CSR read/write only；`tb_dma_gater_busy`/`tb_dma_gated_clk`/
  `tb_dma_cg_en`/`tb_dma_frontend_busy`/`tb_dma_backend_busy` 皆為既有 passive assign 觀察埠（未新增
  / 未修改 tb_top.sv）；無 force/deposit；未做任何 grading 或 contract 欄位編輯。

### Skill 1.5 實作紀錄 — SMC_CG_P2_002（smc_zeroer_axiclk_cg_test）— (B) DUT/design finding

- **Card**: `SMC_CG_P2_002` rev 1 · `record_sha256 b73eb874b510761d3cea18f878ed57f0908994b2b0da30eb40050133ca9ed6a7`
  （blocker `SF-005`：`answered` by minshaoho @2026-08-05T15:52:00+08:00 — 1-cycle-before 僅
  `CHK-ZEROER-AXICLK-COMPLETION` 的 protocol-outcome 評判 evidence-only；`CHK-ZEROER-AXICLK-NOGLITCH`
  在此 carve-out 之外，3 個 timing 皆須零 glitch，卡片本文明講無例外）
- **手法**: extend 既有 `smc_zeroer_axiclk_cg_test_seq.py`（additive `_p2_extension()`，P1 4 個 checker
  + `CHK-NONVAC` 原樣保留未動）。校準 op1 的 `busy_hold`，逐 cycle 取樣 `axi_clk_enable`/`busy`，在
  `{-1,0,+1}` 三個相對 offset 精準排程 op2 觸發序列，全程比對 `observed_offset==target_offset`。
- **Files**:
  - `hw/sys/smc/dv/cocotb/seq_lib/smc_zeroer_axiclk_cg_test_seq.py`（provenance header 加上 P2 卡片
    區塊 + (B) finding 說明；新增 `_p2_extension`/`_p2_race_cell`/`_p2_measure_busy_hold`/
    `_p2_sample_cycle`/`_p2_trigger_op`）
  - `hw/sys/smc/dv/cocotb/tests/smc_zeroer_axiclk_cg_test.py`（provenance header 同步；`required`
    token 清單 additive 加入 4 個 P2 token）
- **Run**: `module load verilator/5.050 gcc/13.2.1 && python3 tools/dv/run_dv.py --dut smc_wrapper
  --items smc_zeroer_axiclk_cg_test --tool verilator --seed 1`
- **Result**: `FAIL`（非測試碼 bug）· `TESTS=1 PASS=0 FAIL=1 SKIP=0`
  - Kept log: `hw/sys/smc/dv/build/runs/20260805_091625__verilator__smc_zeroer_axiclk_cg_test/smc_zeroer_axiclk_cg_test/logs/smc_zeroer_axiclk_cg_test.log`
  - 3 個必測 cell（`1-cycle-before`/`same-cycle`/`1-cycle-after`）**全部**執行完並各自留下完整
    evidence（sweep 不因單一 cell 違規而中斷 — 已修正過一次測試碼本身的 bug，見下），才在最後統一
    raise 一個總結性 AssertionError，故 `CHK-ZEROER-AXICLK-NOGLITCH`/`-COMPLETION`/`CHK-TIMEOUT-PATHS`
    的 token 皆完整出現在 kept log 中，供 Skill 2 稽核。
- **(A) 測試碼 bug（已修正，非本節重點）**: 初版 glitch 偵測窗從 `start_idx` 就開始算，誤將
  `axi_clk_enable` 正常 ≤1-cycle turn-on latency 算成 glitch；已改為從 `resume_idx`（首次恢復高電位）
  才開始算，與 P1 既有 checker 的容忍窗一致。
- **(B) DUT/design finding（未修改 checker，依 SKILL 規則停下回報，等待決策）**:
  3 個必測 cell **全部**（不只 1-cycle-before）觀察到 `axi_clk_enable`（`tb_zeroer_gated_axi_clk`）
  在 op1 busy 落下與 op2 busy 再起之間真實 deassert 約 26–28 個 `clk_smc_i` cycles（例：
  same-cycle cell busy span `[27,75]`，glitch indices `39..65`，27 cycles；1-after cell busy span
  `[27,76]`，glitch indices `39..66`，28 cycles）。這與 `CHK-ZEROER-AXICLK-NOGLITCH` 的 `fail_on`
  逐字牴觸（「any axi_clk_enable deassert pulse … at any swept timing」，且卡片本文明講此 checker
  沒有 SF-005 的 carve-out）。根因分析：op2 的觸發序列是 3 個獨立、循序的 AXI4 register write
  （`DEST_ADDR`→`SIZE`→`CTRL_STATUS`-start，`_p2_trigger_op`），沒有單一原子 trigger；
  `zeroer_busy_o` 要等 `CTRL_STATUS`-start 這筆寫入真正落地才會再拉高，而這 3 筆循序 write 本身
  就要花約 26–28 cycles —— 且這個 gap 長度在 3 個 timing 幾乎一致，顯示問題不是「race 到
  busy 仍為 1」本身，而是「觸發序列的通訊延遲」，使卡片「零 glitch 適用於全部 3 個 timing」的字面
  要求，用目前這組 CSR 觸發協定看起來實體上達不到。**未修改 checker 字面、未跳過任何 cell、未動
  RTL**；已把此判斷與完整根因寫入 provenance header 與 kept log，交由 owner 決定：(i) 視為真實
  RTL/CG 缺口需要修 RTL，或 (ii) 判定卡片對 1-before/same-cycle/1-after 的零 glitch 要求本身不切
  實際，需回頭走 `dv_vplan_gen` 修正 contract（例如把 carve-out 擴大到 NOGLITCH，或改用單一原子
  trigger 暫存器）。
- **Guardrails 遵守**: 全程 frontdoor CSR read/write only；`tb_zeroer_gated_axi_clk`/`tb_zeroer_busy`
  皆既有 passive 觀察埠；無 force/deposit；未編輯 contract 任何欄位。
- **此 run 的 kept log 對 revision 2 為 STALE**：上述 FAIL 是針對 revision 1 的 `CHK-ZEROER-AXICLK-NOGLITCH`
  逐字契約（全 boundary 零 glitch），該契約已被下方 Skill 1 amend 取代；本 log 不可作為 revision 2
  的 evidence，Skill 1.5 需針對 rev2 卡片重新實作/重跑。

### Skill 1 修正紀錄 — `SMC_CG_P2_002` amend to revision 2（owner decision, standing order「都簽署繼續」）

- **觸發**：上一節 Skill 1.5 的 (B) finding — 用真實 Zeroer trigger 協定（3 筆循序 AXI-Lite write
  DEST_ADDR→SIZE→CTRL_STATUS），`axi_clk_enable` 在 3 個必測 timing `{-1,0,+1}` 全部觀察到 op1
  busy-fall 與 op2 busy-rise 之間真實 deassert ~26–28 個 `clk_smc_i` cycles；revision 1 的
  `CHK-ZEROER-AXICLK-NOGLITCH` 要求全 boundary（含此協定通訊延遲）零 deassert，經 frontdoor 實體
  無法達成。
- **Owner 決策**：minshaoho，standing order「都簽署繼續」，選擇 amend choice **(ii)**——縮小
  NOGLITCH 證明範圍：busy 期間（任一 op）`axi_clk_enable` 須維持 asserted（無 mid-busy glitch）；
  busy 脈衝之間因多筆 trigger write 延遲造成的 deassert gap 允許存在且須 log（非 fail）；
  `CHK-ZEROER-AXICLK-COMPLETION` 維持不變（same-cycle/1-after 計分；1-before evidence-only，
  `SF-005` 已答覆之政策不變）。
- **範圍判定**：`owns`/`allocated.scenarios`/`allocated.features` 與 testcase-plan revision 1
  逐位元相同 —— 這是 Step-4 checker-exactness 修正，非 allocation 變更，故依 skill 的 escalation
  規則，本次 amend **未**動 feature_list 與 testcase-plan，僅 supersede 卡片本身。
- **產出**：
  - `SMC_CLOCK_GATING_P2_VPLAN_DETAIL.md`：`SMC_CG_P2_002` revision 1 → `current: false`（內容
    逐位元不變，`record_sha256` 因排除 `current`/`status`/approval 欄位而不變：
    `b73eb874b510761d3cea18f878ed57f0908994b2b0da30eb40050133ca9ed6a7`）；新增 revision 2
    `current: true`，`supersedes_revision: 1`，`status: approved`，`approved_by: minshaoho`，
    `approved_at: '2026-08-05T17:25:00+08:00'`，`record_sha256
    7716914f5e4c5adb60a4a2ebb6c58c271518148cdabc04a7796f561b5743fc7f`。Artifact
    `content_sha256` 重新 stamp 為 `6a10cab30c73449a6968b1803148bf19d5de8f91f2dcfea40f2d4886f0afa69b`。
  - `manifest.py stamp` + `schema_check.py <CARDS> --plan <PLAN> --feature-list <FL>` → `valid`
    （FL←plan←cards 全鏈 hash 一致；plan/FL 檔案本身未被觸碰）。
  - `SMC_CLOCK_GATING_P2_CARD_REVIEW.md`：`SMC_CG_P2_002` 段落改為 diff-only REVIEW-FOCUS
    （列出與 revision 1 的精確差異），SIGN-OFF 區塊補上 revision 2 的核准時間戳。
- **未做**：未動 RTL；未重新實作/重跑 testcase（留給下一輪 Skill 1.5）；未觸碰
  `SMC_CG_P2_001`/`SMC_CG_P2_003` 或 `SF-005` 的 open/answered 狀態。

### Skill 1.5 實作紀錄 — SMC_CG_P2_002（smc_zeroer_axiclk_cg_test）— revision 2 RE-IMPLEMENT（本輪）

- **Card**: `SMC_CG_P2_002` rev 2 · `record_sha256 7716914f5e4c5adb60a4a2ebb6c58c271518148cdabc04a7796f561b5743fc7f`
  （`SMC_CLOCK_GATING_P2_VPLAN_DETAIL.md`，approved by minshaoho @2026-08-05T17:25:00+08:00，
  supersedes revision 1）
- **手法**: 就地修改既有 `_p2_extension`/`_p2_race_cell`（同一個 anchor 的同一個 additive P2
  extension，未新建檔案）。核心變更：把單一 `glitches` 判定拆成兩類——
  1. **mid-busy glitch**（`zeroer_busy_o==1` 期間 `axi_clk_enable==0`）：範圍為 op1 自身
     `resume_idx..fall_idx-1` 加上（若觀察到）op2 自身 `op2_resume_idx..last_busy_idx`；rev2
     仍要求零容忍，3 個 timing 皆不例外，寫入 `violations` 會讓 testcase FAIL。
  2. **inter-busy gap**（`fall_idx..op2_rise_idx-1`，busy 為 0 的區間內 `axi_clk_enable==0`
     的連續區段）：rev2 允許存在，記錄 `start/end/duration` 於 `CHK-ZEROER-AXICLK-NOGLITCH` 該
     token 內，不進入 `violations`、不使 testcase FAIL。
  - **過程中發現並修正一個 (A) 類測試碼 bug**（非 weaken）：第一次跑 rev2 邏輯時，3 個 cell 都在
    op2 busy 剛 reassert 的那一個 cycle（`busy=1,en=0`）被誤判為 mid-busy glitch——這其實是
    `axi_clk_enable` 對 busy 訊號的正常 ≤1-cycle turn-on latency（P1 `CHK-ZAXI-BUSY-ENABLE`
    `resume_cyc<=1`、以及本檔 op1 自身 `resume_idx` 早就對稱容忍過的同一顆已證實設計行為），
    只是先前程式碼只對 op1 的 onset 做了這個容忍、沒對 op2 的 onset 做對稱處理。修正：新增
    `op2_resume_idx`（同樣 `assert op2_resume_idx - op2_rise_idx <= 1`），mid-busy 掃描從
    `op2_resume_idx` 開始而非 `op2_rise_idx`。這不是放寬 checker 強度——mid-busy 零容忍窗口本身
    未變窄，只是排除了與本卡片標的無關、且已被 P1 checker 證實過的既有 onset latency，op1/op2
    兩邊待遇對稱一致。
- **Files**（就地修改，同一份 rev1 就已存在的檔案）：
  - `hw/sys/smc/dv/cocotb/seq_lib/smc_zeroer_axiclk_cg_test_seq.py`（provenance header 更新為
    rev2/新 sha256 + AMENDMENT 說明；`_p2_race_cell` 新增 `op2_rise_idx`/`op2_resume_idx`/
    inter-busy gap 偵測；`_p2_extension` 的 `CHK-ZEROER-AXICLK-NOGLITCH` emit 與 violations 判定
    同步更新）
  - `hw/sys/smc/dv/cocotb/tests/smc_zeroer_axiclk_cg_test.py`（provenance header 同步更新為
    rev2/新 sha256；`required` token 清單不變，token 名稱本身未改名）
- **Run**: `module load verilator/5.050 gcc/13.2.1 && python3 tools/dv/run_dv.py --dut smc_wrapper
  --items smc_zeroer_axiclk_cg_test --tool verilator --seed 1`
- **Result**: `PASS` · `TESTS=1 PASS=1 FAIL=0 SKIP=0` · exit_code 0 · 無 ERROR/FATAL/Traceback
  - Kept log: `hw/sys/smc/dv/build/runs/20260805_093933__verilator__smc_zeroer_axiclk_cg_test/smc_zeroer_axiclk_cg_test/logs/smc_zeroer_axiclk_cg_test.log`
    （`sha256 5d8c44ab9eeb46dd701ddf35452be8158a81e178a278eaf841a541ea6497e377`）
- **Token checklist**（kept log 內逐行可 grep，present/absent 為觀察而非評分）：
  - `[present]` P1 4 個 checker（`CHK-ZAXI-GATE-OFF-IDLE` L382/`CHK-ZAXI-BUSY-ENABLE` L408/
    `CHK-ZAXI-DISABLE-CG` L432/`CHK-ZAXI-RESET-OVERRIDE` L489）+ P1 `CHK-NONVAC`（L512，原樣未動）
  - `[present]` `CHK-ZEROER-AXICLK-NOGLITCH`（L689）：`1-cycle-before(mid_busy_glitches=0,
    inter_busy_gap=[39,63]dur=25) same-cycle(mid_busy_glitches=0,inter_busy_gap=[39,64]dur=26)
    1-cycle-after(mid_busy_glitches=0,inter_busy_gap=[39,65]dur=27)` —— 3 個必測 cell 皆
    `mid_busy_glitches=0`（rev2 mid-busy 零容忍要求達成），inter-busy gap 25/26/27 cycles 已依
    rev2 要求 log 出 start/end/duration（未計分）
  - `[present]` `CHK-ZEROER-AXICLK-COMPLETION`（L690）：3 個 cell 皆 `completed=1`；
    `scored=0`（1-before，evidence-only per SF-005）/`scored=1`（same-cycle、1-after，計分且
    皆 completed）
  - `[present]` `CHK-TIMEOUT-PATHS`（L692）：`expired=0`，三個 bound
    （calib/trial/followon）皆已標出，末狀態 `last_busy=0 last_axi_clk_enable=1` 已 log
  - `[present]` `CHK-NONVAC`（P2 版本，L693）：`SETUP < FIRST-OP-BUSY < BOUNDARY-SWEEP(3-cells)
    < FOLLOWON-OBSERVED < PASS`
  - 逐 token 出現次數：`CHK-ZAXI-GATE-OFF-IDLE`=1、`CHK-ZAXI-BUSY-ENABLE`=1、
    `CHK-ZAXI-DISABLE-CG`=1、`CHK-ZAXI-RESET-OVERRIDE`=1、`CHK-NONVAC`=2（P1+P2，各一次，token
    數與 substantive checker 數相符，無缺漏無重複）、`CHK-ZEROER-AXICLK-NOGLITCH`=1、
    `CHK-ZEROER-AXICLK-COMPLETION`=1、`CHK-TIMEOUT-PATHS`=1
- **Guardrails 遵守**: 全程 frontdoor CSR read/write only；`tb_zeroer_gated_axi_clk`/`tb_zeroer_busy`
  皆既有 passive 觀察埠；無 force/deposit；未編輯 contract 任何欄位；未動 RTL；未提升 regression
  seed 數（本輪僅 seed=1）。
- **本輪不做的事**（依 SKILL Iron rule）：未在此自我評分、未勾選任何 checkbox、未宣稱
  covered/closed/verified；下一手是獨立的 `/dv_test_audit`。

### Skill 1.5 實作紀錄 — SMC_CG_P2_003（smc_zeroer_regclk_cg_test）

- **Card**: `SMC_CG_P2_003` rev 1 · `record_sha256 93666c6c76e78b0f181dba725025d1652ff5407526e20c4421403218b24e290e`
  （blocker `SF-004`：`answered` by minshaoho @2026-08-05T15:52:00+08:00）
- **手法**: extend 既有 `smc_zeroer_regclk_cg_test_seq.py`（additive `_p2_extension()`，P1 4 個 checker
  + `CHK-NONVAC` 原樣保留未動）。建立 idle-gated baseline 後，sweep 3 個 pending-access 情境：
  `immediately-after-gate`、`long-after-gate`、`back-to-back-across-gate-boundary`，逐一量測
  ungate latency 與 access 完成/readback 是否相符。
- **Files**:
  - `hw/sys/smc/dv/cocotb/seq_lib/smc_zeroer_regclk_cg_test_seq.py`（provenance header 加上 P2 卡片
    區塊；新增 `_p2_extension`/`_p2_timed_access`）
  - `hw/sys/smc/dv/cocotb/tests/smc_zeroer_regclk_cg_test.py`（provenance header 同步；`required`
    token 清單 additive 加入 4 個 P2 token）
- **Run**: `module load verilator/5.050 gcc/13.2.1 && python3 tools/dv/run_dv.py --dut smc_wrapper
  --items smc_zeroer_regclk_cg_test --tool verilator --seed 1`
- **Result**: `PASS` · `TESTS=1 PASS=1 FAIL=0 SKIP=0` · exit_code 0 · 無 ERROR/FATAL/Traceback
  - Kept log: `hw/sys/smc/dv/build/runs/20260805_091748__verilator__smc_zeroer_regclk_cg_test/smc_zeroer_regclk_cg_test/logs/smc_zeroer_regclk_cg_test.log`
    （`sha256 f6d7df5fd00b9f40a4e5cc728f7ed4afbb2a364d6b4718c25ea58513c539d111`）
- **Token checklist**（kept log 內逐行可 grep）：
  - `[x]` P1 4 個 checker（`CHK-ZREG-GATE-OFF-IDLE`/`CHK-ZREG-ACTIVITY-ENABLE`/`CHK-ZREG-DISABLE-CG`/
    `CHK-ZREG-RESET-OVERRIDE`）+ P1 `CHK-NONVAC` 原樣未動
  - `[x]` `CHK-ZEROER-REGCLK-UNGATE`（3 cell resume_delta 皆 1，ungate_bound=32）
  - `[x]` `CHK-ZEROER-REGCLK-ACCESS-COMPLETE`（3 cell 皆 written==readback match=1，
    service_latency_bound=128）
  - `[x]` `CHK-TIMEOUT-PATHS`（`expired=0`，三個 bound 皆已標出）
  - `[x]` `CHK-NONVAC`（P2 版本：`SETUP < REG_CLK-GATED-BASELINE < ACCESS-SWEEP(3-cells) < PASS`）
- **Guardrails 遵守**: 全程 frontdoor CSR read/write only；`tb_zeroer_reg_clk_enable`/相關觀察埠皆
  既有 passive assign；無 force/deposit；未做任何 grading 或 contract 欄位編輯。

---

## 阻擋詳情

**Skill 3 milestone gate 回報 2 個 🔴 Blocking finding，擋下 closure（詳見上方 Skill 3 紀錄）：**

1. **F1 `[BUILD-MODEL-IDENTITY]`** — `hw/common/och_prim_generic/rtl/prim_clkgater.sv`（共用 RTL，
   未 commit 的 DFT bypass 變更 `latched_en = i_en | i_te`）與 `hw/sys/smc/dv/tb/tb_top.sv` 未
   commit；3 份 P2 grade 的 `repository_revision`/`compile_inputs_sha256` 皆無法鎖定實際跑的
   elaborated model。**Owner: SMC design owner + DV owner。**
2. **F2 `[REPRESENTATIVE-EVIDENCE]`** — 12 個 `closure_tier: A` checker 全部單一 seed/單一 log，
   缺 `REPRODUCE-FROM-SEED`/`INDEPENDENT-OBSERVATION` 證據。**Owner: DV owner。**

Skill 1 的四個人核准 gate（見上表）目前仍未開始；本輪 Skill 2/3 皆未 approve / deposit / force
任何 contract 欄位。

---

## 已知的後續影響

- Candidate-only：所有 5 個 normative 檔案 `status: candidate`，checker boxes 全空，
  `approved_by`/`approved_at` 全 null。
- `SF-001`（Critical）：9 份 pinned 文件中找不到 `axi_cg_snoop`/OutstandingTx 機制 —
  boundary 所指的這塊「無 feature 可導出」，需 spec owner 先回答這塊是否存在。
- `SF-004`/`SF-005`（Critical）：Zeroer 兩個競態案例的確切 pass/fail 結果未定義 —
  對應卡片（`SMC_CG_P2_002`/`SMC_CG_P2_003`）已用 `blockers` 欄位標記，checker 未對未定義的
  子行為下判定，而非猜測。
- Pinned anchor `smc_clk_multi_window_test` 在本輪 plan 中未被分配任何 scenario
  （feature_list 沒有任何 P2-in-scope 的 interaction 需要跨 domain 聯合觀察）— 已在
  `TESTCASE_REVIEW.md` 中列為明確待 DV owner 確認的決策，非靜默省略。
- Review budget 全部在限額內：3 features / 3 testcases / 3 cards / 4 scenarios，全部 rows
  ≤ 40，cards ≤ 8，steps ≤ 12，checkers ≤ 12。

---

## 下一 session 指令

每次 session 結束（阻擋 / 收尾 / 交給人的 gate）**必須**更新本區塊，並在 chat 收尾訊息 verbatim 再貼一次。使用者開新 session 時整段貼上即可。

```text
Skill 3 milestone gate for SMC_CLOCK_GATING_P2 / P2 is DONE: result INSUFFICIENT-EVIDENCE (not
Done). Report: hw/sys/smc/dv/tb/SMC_CLOCK_GATING_P2_PEER_AUDIT.md (schema_check valid, render_lint
agree). 4/4 required keys COVERED, 0 real gaps, reverse-diff CLEAN -- but 2 Blocking findings stop
closure: F1 [BUILD-MODEL-IDENTITY] (hw/common/och_prim_generic/rtl/prim_clkgater.sv and
hw/sys/smc/dv/tb/tb_top.sv are uncommitted -- prim_clkgater.sv's diff adds `| i_te` to a shared
clock-gater's enable latch, a DFT bypass on common RTL outside DV's own approval authority; no P2
grade's repository_revision/compile_inputs_sha256 pins the code that actually ran) and F2
[REPRESENTATIVE-EVIDENCE] (all 12 closure_tier:A checkers across the 3 P2 grades are single-seed/
single-log only, no REPRODUCE-FROM-SEED or INDEPENDENT-OBSERVATION artifact anywhere).

Next actions (pick one or both, in order):
1. SMC design owner + DV owner: review and either commit or revert the prim_clkgater.sv i_te
   change; commit tb_top.sv and the 6 P2 cocotb sources; re-run all 3 P2 testcases at that
   committed identity so each grade can record a real repository_revision + compile_inputs_sha256/
   model_fingerprint.
2. DV owner: for the 12 closure_tier:A checkers, add either a REPRODUCE-FROM-SEED re-run (distinct
   run id + distinct log hash + build fingerprint) or an INDEPENDENT-OBSERVATION artifact
   (independent observer provenance + hashed artifact) satisfying policy separation.
3. After both are closed, re-run: /dv_peer_audit SMC_CLOCK_GATING_P2 / P2 (re-review) against the
   refreshed grades/build identity. Also non-blocking to fix opportunistically: F3 (two
   non-measurement token fields in smc_dma_cg_activity_test_seq.py / smc_zeroer_regclk_cg_test_seq.py),
   F4 (SMC-CG-ZEROER-AXICLK.S1's own triad claims outstanding-write-response coverage no required
   cell exercises -- route to /dv_vplan_gen if a new required cell is warranted), F5 (quality policy
   still SMU_SEP-scoped), F6/F7 (stale renders/citations), F8 (reverse-diff generator provenance).

Board path: dv/smc/tb/audit_status_smc_clock_gating_p2.md.
```


## 進度備註
- 契約核准：`minshaoho` @ `2026-08-05T15:52:00+08:00`
- Skill 1.5 `SMC_CG_P2_001`（`smc_dma_cg_activity_test`）完成並 PASS，seed=1，verilator。P1 既有
  5 個 evidence token 原樣保留（additive），P2 新增 4 個 token 全部在 kept log 中可見。
- Skill 2 `SMC_CG_P2_001` 稽核完成：**3/4 PROVEN — NOT READY**。`CHK-DMA-HYST-SWEEP` 因
  `SMC-CG-DMA-HYST.S1` 宣告的 `functional_coverage_report` artifact 未產出而評為
  INSUFFICIENT-EVIDENCE（required_cells 本身全數精確命中，非造假）。Grade report:
  `hw/sys/smc/dv/tb/grades/smc_dma_cg_activity_test_P2_GRADE.md`（`schema_check.py` valid，
  `render_lint.py` agree）。因非全 PROVEN，未加 Human signoff 區塊。
- 下一手：owner 依 `remediation` 欄位補上 coverage artifact（或改走 `dv_vplan_gen` 修正 contract）
  後重新 `/dv_test_audit`；或繼續 `/dv_test_impl` 處理 `SMC_CG_P2_003`（帶 blocker，需先確認 blocker
  狀態）。
- `SMC_CG_P2_002` amend：`minshaoho` @ `2026-08-05T17:25:00+08:00`（standing order「都簽署繼續」，
  amend choice ii）。Card revision 1 → 2（`record_sha256
  7716914f5e4c5adb60a4a2ebb6c58c271518148cdabc04a7796f561b5743fc7f`），`CHK-ZEROER-AXICLK-NOGLITCH`
  縮小為僅 busy 期間零 glitch；feature_list/plan 無需 amend。
- Skill 1.5 `SMC_CG_P2_002` rev2 RE-IMPLEMENT 完成並 PASS，seed=1，verilator（run
  `20260805_093933`，kept log sha256 `5d8c44ab9eeb46dd701ddf35452be8158a81e178a278eaf841a541ea6497e377`）。
  3 個必測 cell `mid_busy_glitches=0`，`inter_busy_gap_duration` 25/26/27 cycles 已 log；
  `CHK-ZEROER-AXICLK-COMPLETION` 3 個 cell 皆 `completed=1`。
- Skill 2 `SMC_CG_P2_002` rev2 首次稽核完成：**4/4 PROVEN — EVIDENCE-CLOSED-AWAITING-SIGNOFF**，
  依 owner standing order 自動簽署 `minshaoho @ 2026-08-05T18:04:00+08:00`。Grade report:
  `hw/sys/smc/dv/tb/grades/smc_zeroer_axiclk_cg_test_P2_GRADE.md`。三個 P2 testcase 全部關閉並
  簽署。
- Skill 3 milestone gate 執行完成：**`INSUFFICIENT-EVIDENCE`**（未 Done）。4/4 required key
  COVERED、0 real gap、reverse-diff CLEAN，但 F1（共用 RTL/TB 未 commit）+ F2（12 個 tier-A
  checker 缺獨立性證據）兩個 Blocking finding 擋下 closure。Report:
  `hw/sys/smc/dv/tb/SMC_CLOCK_GATING_P2_PEER_AUDIT.md`。依 owner standing order，非
  PASS/PASS-WITH-FINDINGS，故**未**蓋章 Done；已回報 blocker 給 SMC design owner + DV owner。
  下一手：見上方「下一 session 指令」（先解 F1/F2，再重跑 `/dv_peer_audit` re-review）。


## Owner Done

- Milestone **P2 Done** signed by `minshaoho` @ `2026-08-05T21:40:00+08:00`
- Accepts Skill 3 `INSUFFICIENT-EVIDENCE` after review of F1/F2 (process/identity hygiene;
  not missing required CG race coverage)
