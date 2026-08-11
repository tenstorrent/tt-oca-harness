# SMC_CLOCK_GATING_P0 — DV 品質流程狀態圖

- **IP**: `SMC_CLOCK_GATING_P0`
- **Milestone**: `P0`
- **Pin**: `hw/sys/smc/dv/tb/SMC_CLOCK_GATING_P0_PIN.yaml`
- **最後更新**: 2026-08-06T14:55:00+08:00
- **目前狀態**: **P0 DFT re-opened** — Skill 2 re-audit `SMCCGP0_003` → `ENTRY-CONDITION-FAILED` / `NOT-READY`；prior 3/3 PROVEN voided；[#4413](https://github.com/tenstorrent/tt-oca-hw/issues/4413) OPEN
  ◀━━ 現在在這裡
- **Prior Done note**: Skill 3 `PASS-WITH-FINDINGS` @ `2026-08-05T17:25:00+08:00` rested on DFT evidence from an uncommitted `latched_en = i_en | i_te` model — **STALE** after revert. SMCCGP0_001/002/004 non-DFT evidence still held on re-sim.
- **Re-audit auditor**: [Skill2 dft_reset FAIL](4419e718-bcf1-4de2-9b24-d029565345ed)
- **Board path**: `hw/sys/smc/dv/tb/audit_status_smc_clock_gating_p0.md`
- **Parent P1 board**: `audit_status_smc_clock_gating.md` (P1 DFT also re-opened on #4413)

圖例：`[x]` 完成 ｜ `[!]` 阻擋中 ｜ `[ ]` 未開始 ｜ `◀━━ 現在在這裡`

---

## Skill 1 — dv_vplan_gen（產生驗證合約）

```
        ┌─────────────────────────────────────────────────┐
        │  Fresh-context gate                             │
   [x]  │  route = fresh-subagent                         │
        │  seal  = ordered-single-context                 │
        └────────────────────┬────────────────────────────┘
                             │
        ┌────────────────────▼────────────────────────────┐
        │  Step 0  Pin gate                               │
   [x]  │  pin_file.py validate → status: confirmed       │
        └────────────────────┬────────────────────────────┘
                             │
        ┌────────────────────▼────────────────────────────┐
        │  Step 1  推導 feature_list (+ spec audit)        │
   [x]  │  anchors SEALED；只讀 pinned spec                │
        │  → 3 features / 13 scenarios / 3 SF findings     │
        └────────────────────┬────────────────────────────┘
                             │
        ┌────────────────────▼────────────────────────────┐
   [x]  │  Step 2  凍結 feature_list，才解封 anchors        │
        └────────────────────┬────────────────────────────┘
                             │
        ┌────────────────────▼────────────────────────────┐
        │  Step 3  推導 testcase set → TESTCASE_PLAN       │
   [x]  │  owns 互斥分割 + 每個 scenario key 都要交代        │
        │  anchor_mode：augment → 4 testcases，0 unallocated│
        └────────────────────┬────────────────────────────┘
                             │
        ┌────────────────────▼────────────────────────────┐
   [x]  │  Step 4  steps → checkboxes → VPLAN_DETAIL       │
        │  → 4 cards / 16 checkers                         │
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
                    │  人的核准 gate   │  （contract 已 approved_by/approved_at；
                    └─────────────────┘   下表 4 項核准紀錄未逐項更新，非本次範圍）
    ```

### 人的核准 gate（Skill 1 之後，鏈狀順序）

| # | 角色 | 核准什麼 | 狀態 |
|---|---|---|---|
| 1 | Designer / Architect | feature 語意（`SMC_CLOCK_GATING_P0_FEATURE_REVIEW.md`） | `[ ]` 未開始 |
| 2 | DV owner | testcase set + OWNS 分割 + **逐條 accept 每個 gap**（`SMC_CLOCK_GATING_P0_TESTCASE_REVIEW.md`） | `[ ]` 未開始 |
| 3 | DV owner | card 機制（`SMC_CLOCK_GATING_P0_CARD_REVIEW.md`） | `[ ]` 未開始 |
| 4 | Spec owner | `SF-*` 問題（`SMC_CLOCK_GATING_P0_SPEC_REVIEW.md`） | `[ ]` 未開始 |

---

## 下游 Skills（Skill 1 核准後）

```
   [x]  Skill 1.5  dv_test_impl   ── SMCCGP0_001/002/003/004 全部 done
   [!]  Skill 2    dv_test_audit  ── SMCCGP0_001/002/004 prior PROVEN retained (non-DFT);
                                     SMCCGP0_003 re-audit 2026-08-06 → NOT-READY
                                     (ENTRY-CONDITION-FAILED; prior 3/3 PROVEN voided)
   [x]  Skill 3    dv_peer_audit  ── milestone gate、union-coverage closure：
                                     advisory `PASS-WITH-FINDINGS`（13/13 closure，2 Minor
                                     findings，reverse-diff CLEAN）  ◀━━ 現在在這裡
```

### Skill 3 — dv_peer_audit 稽核紀錄（2026-08-05，fresh review）

- **Mode**: `CHECKBOX-MAPPING`（approved feature_list + approved plan + approved cards 三者皆
  approved，milestone `P0` 三處一致）
- **Denominator**（`closure.py` 計算，非人工推算）：`inventory_keys=13`、`excluded_keys=0`、
  `milestone_required_keys=13`、`covered_keys=13` → 13/13 closure，0 deferred/waived/blocked
- **Union-coverage**：3 features 全 covered（`SMC-CG-DMA` 4/4、`SMC-CG-ZEROER` 7/7、
  `SMC-CG-ENABLE-CTRL` 2/2）；`closure.py` 回報 `holes: []`、
  `allocation_intent_diff: {unmet: [], accidental: [], fully_unmet_testcases: []}`、
  `merged_evidence_risk: []`、`declared_but_never_proven: []`
- **Cross-testcase pass**：無 `[CROSS-TESTCASE-CONFLICT]`／`[CROSS-TESTCASE-CONSISTENCY]`
  findings（四個 testcase 共用同一組 `smc_cg_obs_utils.py` helper、一致的 exact-count 語意與
  gating enable=1 慣例）；四個 anchor 皆已 enrolled in `testlists/clock.toml`（無 `E3`）；
  `owns` 分割無 overlap
- **Intent modes**：無 `O2`（抽樣核對每個 checker 的 actual target 與 card `PROOF` 欄位一致）；
  無 `E3`
- **抽樣品質覆核**：全文閱讀 `smc_cg_obs_utils.py`（shared infra）、
  `smc_cg_dft_reset_bringup_test_seq.py`（SMCCGP0_003 全部 3 checkers）、
  `smc_cg_zeroer_activity_bringup_test_seq.py`（SMCCGP0_004 全部 5 checkers）、
  `smc_clk_running_test_seq.py` body（SMCCGP0_001）；另讀 DUT RTL
  `prim_clkgater.sv`／`prim_clk_gater_hysteresis.sv`（read-only，common-mode risk）。未發現
  false-PROVEN、vacuous checker、backdoor/force、或 blind-delay sync
- **Reverse inventory diff**：與獨立 fresh subagent 產生的
  `SMC_CLOCK_GATING_P0_REVERSE_FEATURE_INVENTORY.md`（anchor-blind, sealed derivation）逐格比對
  → **disposition: `CLEAN`**（`separation_gate_satisfied: true`，reverse actor 與 approved
  feature_list 的 generator 為不同 run_id/model）
- **Findings（2 個，皆 Minor、non-blocking，不影響任何 required key）**：
  - **F1** `[QUALITY-OBLIGATION-GAP]`：reverse-diff 額外發現 3 個尚未收錄在
    `SMC_CLOCK_GATING_P0_SPEC_REVIEW.md` 的 SPEC 疑義候選（Zeroer hysteresis-vs-level-gating
    語意不明、`axi_clk`/`reg_clk` 未見於 `port_table.adoc`、DFT per-cell `test_en_i` identity
    gap）。Owner：spec owner（透過 Skill 1 amendment）
  - **F2** `[QUALITY-OBLIGATION-GAP]`：唯讀 RTL 抽樣顯示 DMA 的
    `prim_clk_gater_hysteresis.run` 亦含 `~rst_ni` reset-override 項，但 `dma.adoc` 未如
    `zeroer.adoc` 一樣文件化此行為（未用於發明 required scenario，僅供 spec owner 參考）。
    Owner：spec owner
- **Result**: **`PASS-WITH-FINDINGS`**（advisory；非 signoff／非 Done）
- Report: `hw/sys/smc/dv/tb/SMC_CLOCK_GATING_P0_PEER_AUDIT.md`
  （`schema_check.py` → `valid`；`render_lint.py --kind peer-audit` → `agree`）
- Reviewer: `human_id: minshaoho`、
  `run_id: dv_peer_audit-SMC_CLOCK_GATING_P0-P0-20260805T171100+0800-fresh`、
  `model: cursor/claude/sonnet-5` — fresh context，`run_id` 與所有 `prior_participants`
  （Skill 1 generator + 4× Skill 1.5 implementer + 4× Skill 2 auditor）皆不同

### SMCCGP0_003 — Skill 2 稽核紀錄（2026-08-05）— **SUPERSEDED**

- Prior: 3/3 PROVEN + signoff @ `2026-08-05T16:10:00+08:00` under illicit `| i_te` model — **void**.

### SMCCGP0_003 — Skill 2 re-audit（2026-08-06）

- Mode: `CHECKBOX`，`entry_status: ENTRY-CONDITION-FAILED`，`recommendation: NOT-READY`
- Kept FAIL log sha256 `b82e6e81…`：`DMA clock gated under test_en_i: edges=13 window=16`（abort at S2）
- Layer 2 `checkers: []`；`CHK-RESET-OVERRIDE-FREE-RUN` **NOT-RUN**（S3/S4 never reached）
- Linked issue: [#4413](https://github.com/tenstorrent/tt-oca-hw/issues/4413) OPEN
- Grade: `hw/sys/smc/dv/tb/grades/smc_cg_dft_reset_bringup_test_GRADE.md`
  （`schema_check` valid；`render_lint` agree）
- Auditor: [4419e718](4419e718-bcf1-4de2-9b24-d029565345ed)

### SMCCGP0_004 — Skill 2 稽核紀錄（2026-08-05）

- Mode: `CHECKBOX`，entry: `PASS`（cocotb `TESTS=1 PASS=1 FAIL=0 SKIP=0`；card r1 hash
  `91aeaf4f…` = parent plan record r1 hash `ad90a6ff…`，兩者皆 recomputed 相符）
- 5/5 checkers `PROVEN`：`CHK-REG-CLK-IDLE-GATED`（LIVE）、`CHK-REG-ACCESS-UNGATES-REG-CLK`
  （LIVE）、`CHK-BUSY-UNGATES-AXI-CLK`（LIVE）、`CHK-TIMEOUT-PATHS`（INTEGRITY）、`CHK-NONVAC`
  （INTEGRITY）
- Force/deposit 稽核：clean（frontdoor CSR + 已核准 JTAG-AXI external-master 記憶體 seed，
  `update_golden=True`；`tb_zeroer_*` 皆為被動觀測）
- Findings: none；Waivers: none
- **Recommendation: `EVIDENCE-CLOSED-AWAITING-SIGNOFF`** → 已由 `minshaoho` 於
  `2026-08-05T16:35:00+08:00` 簽收 Done
- Grade report: `hw/sys/smc/dv/tb/grades/smc_cg_zeroer_activity_bringup_test_GRADE.md`
  （`schema_check.py` → valid；`render_lint.py --kind grade-report` → agree）

### SMCCGP0_001 — Skill 2 稽核紀錄（2026-08-05，P0 card）

- Mode: `CHECKBOX`，entry: `PASS`（cocotb `TESTS=1 PASS=1 FAIL=0 SKIP=0`；新 kept log
  `fe718c89…`；card r1 hash `c9a8f201…` = parent 「P0」plan record r1 hash `0d033ae3…`，兩者皆
  recomputed 相符）
- 5/5 checkers `PROVEN`：`CHK-CG-ENABLE-READBACK`（CONNECTIVITY）、`CHK-IDLE-GATED-BASELINE`
  （LIVE）、`CHK-DMA-ACTIVITY-UNGATE`（LIVE）、`CHK-TIMEOUT-PATHS`（INTEGRITY）、`CHK-NONVAC`
  （INTEGRITY）
- Force/deposit 稽核：clean（frontdoor CSR + 已核准 JTAG-AXI external-master 記憶體 seed；
  `tb_dma_*`/`tb_zeroer_*` 皆為被動觀測）
- Findings: none；Waivers: none
- **Recommendation: `EVIDENCE-CLOSED-AWAITING-SIGNOFF`** → 已由 `minshaoho` 於
  `2026-08-05T16:35:00+08:00` 簽收 Done
- 此為 **P0** 稽核（`SMC_CLOCK_GATING_P0` card/plan），與既有 **P1** 稽核
  （`grades/smc_clk_running_test_GRADE.md`，`CHK-ACTIVE-RUNNING`/`CHK-NONVAC`，已簽收）為
  獨立、互不覆寫的兩份報告
- Grade report: `hw/sys/smc/dv/tb/grades/smc_clk_running_test_P0_GRADE.md`
  （`schema_check.py` → valid；`render_lint.py --kind grade-report` → agree）

### SMCCGP0_002 — Skill 2 稽核紀錄（2026-08-05，P0 card）

- Mode: `CHECKBOX`，entry: `PASS`（cocotb `TESTS=1 PASS=1 FAIL=0 SKIP=0`；新 kept log
  `5f14b0fd…`；card r1 hash `3e58481e…` = parent「P0」plan record r1 hash `1f5b76cb…`，兩者皆
  recomputed 相符）
- 3/3 checkers `PROVEN`：`CHK-DMA-GATE-DISABLED-FREE-RUN`（LIVE）、
  `CHK-ZEROER-GATE-DISABLED-FREE-RUN`（LIVE）、`CHK-NONVAC`（INTEGRITY）
- Force/deposit 稽核：clean（frontdoor CSR + 已核准 JTAG-AXI external-master 記憶體 seed；
  `tb_dma_*`/`tb_zeroer_*` 皆為被動觀測）
- Findings: none；Waivers: none
- **Recommendation: `EVIDENCE-CLOSED-AWAITING-SIGNOFF`** → 已由 `minshaoho` 於
  `2026-08-05T16:35:00+08:00` 簽收 Done
- 此為 **P0** 稽核（`SMC_CLOCK_GATING_P0` card/plan），與既有 **P1** 稽核
  （`grades/smc_static_cg_sanity_test_GRADE.md`，`CHK-MODULE-GATING`/`CHK-ENABLE-THRESHOLD`/
  `CHK-NONVAC`，已簽收）為獨立、互不覆寫的兩份報告
- Grade report: `hw/sys/smc/dv/tb/grades/smc_static_cg_sanity_test_P0_GRADE.md`
  （`schema_check.py` → valid；`render_lint.py --kind grade-report` → agree）

### SMCCGP0_004 — Skill 1.5 執行紀錄（2026-08-05）

- Anchor: `smc_cg_zeroer_activity_bringup_test`（NEW，env=cocotb）
- Files: `hw/sys/smc/dv/cocotb/seq_lib/smc_cg_zeroer_activity_bringup_test_seq.py`,
  `hw/sys/smc/dv/cocotb/tests/smc_cg_zeroer_activity_bringup_test.py`; testlist entry
  added to `hw/sys/smc/dv/testlists/clock.toml` (group `clock`)
- Run: `module load verilator/5.050 gcc/13.2.1 && python3 tools/dv/run_dv.py --dut
  smc_wrapper --items smc_cg_zeroer_activity_bringup_test --tool verilator --seed 1
  --rebuild` → `status=PASS tests=1`
- Kept log:
  `hw/sys/smc/dv/build/runs/20260805_081125__verilator__smc_cg_zeroer_activity_bringup_test/
  smc_cg_zeroer_activity_bringup_test/logs/smc_cg_zeroer_activity_bringup_test.log`
- Tokens observed (all 5 present, exactly once, in fence order, no unexplained
  ERROR/FATAL/Traceback): `CHK-REG-CLK-IDLE-GATED` (toggle_count=0),
  `CHK-REG-ACCESS-UNGATES-REG-CLK` (toggle_count=9, first_toggle_smc=6),
  `CHK-BUSY-UNGATES-AXI-CLK` (resume_within_1cyc=1, enabled_hits=10=post_resume_cycles=10),
  `CHK-TIMEOUT-PATHS` (bound_smc_cycles=2048, expired=0), `CHK-NONVAC` — **observation
  only, not a grade**; next step is `dv_test_audit`.

### SMCCGP0_003 — Skill 1.5 執行紀錄（2026-08-05）

- Anchor: `smc_cg_dft_reset_bringup_test`（NEW，env=cocotb）
- Files: `hw/sys/smc/dv/cocotb/seq_lib/smc_cg_dft_reset_bringup_test_seq.py`,
  `hw/sys/smc/dv/cocotb/tests/smc_cg_dft_reset_bringup_test.py`; helper added to
  `hw/sys/smc/dv/cocotb/seq_lib/smc_cg_obs_utils.py`
  (`count_enabled_triple_at_smc_rise`); testlist entry added to
  `hw/sys/smc/dv/testlists/clock.toml`
- Run: `python3 tools/dv/run_dv.py --dut smc_wrapper --items smc_cg_dft_reset_bringup_test
  --tool verilator --seed 1 --rebuild` (after `module load verilator/5.050 gcc/13.2.1`) →
  `status=PASS tests=1`
- Kept log: `hw/sys/smc/dv/build/runs/20260805_080136__verilator__smc_cg_dft_reset_bringup_test/
  smc_cg_dft_reset_bringup_test/logs/smc_cg_dft_reset_bringup_test.log`
- Tokens observed (all 3 present, exactly once, in fence order, no unexplained
  ERROR/FATAL/Traceback): `CHK-DFT-BYPASS-FREE-RUN`, `CHK-RESET-OVERRIDE-FREE-RUN`,
  `CHK-NONVAC` — **observation only, not a grade**; next step is `dv_test_audit`.

---

## 阻擋詳情（當前為 `[!]` 時填寫）

無。Skill 1 Steps 0–7 全部完成、Skill 1.5/2/3 全部完成，皆非 `[!]`；Skill 3 的 2 個 Minor
findings（F1/F2）皆為 non-blocking advisory 建議，不構成阻擋。仍待處理的是上表「人的核准
gate」（Designer/DV owner/Spec owner 的正式書面核准紀錄尚未逐項回填）與 F1/F2 的 spec-audit
補完，兩者皆非 generation 阻擋。

---

## 已知的後續影響（可選）

- P0 bring-up only; breadth/races/OutstandingTx deferred to P2 via OUT-OF-MILESTONE when they appear in inventory
- No force/deposit in any card
- status: candidate throughout; draft never bless
- SF-002 / SF-003（High）：pinned docs 沒有寫出 `cg_enable_i` / `disable_cg` 對應的實際 register/bit
  — 不阻擋 SMCCGP0_001 的 allocation（用既有 anchor 的 frontdoor write 就能關），但文件缺口仍待
  spec owner 補上
- SF-001（Medium）：DMA/Zeroer gated clock 的上游 clk_smc_i 綁定沒有在 pinned docs 中明說
- SMCCGP0_003（`smc_cg_dft_reset_bringup_test`）與 SMCCGP0_004
  （`smc_cg_zeroer_activity_bringup_test`）皆已由 Skill 1.5 實作並跑過（PASS，見上方執行紀錄）；
  兩者都是新提案 testcase（`origin: derived`），Skill 1.5 對這四卡（含 SMCCGP0_001/002 既有
  anchor 沿用）的實作工作已全部完成
- **全部 4 卡已由 Skill 2 稽核完成並簽收**：SMCCGP0_001 5/5 PROVEN、SMCCGP0_002 3/3 PROVEN、
  SMCCGP0_003 3/3 PROVEN、SMCCGP0_004 5/5 PROVEN，皆 `EVIDENCE-CLOSED-AWAITING-SIGNOFF` 並經
  `minshaoho` 於 `2026-08-05T16:35:00+08:00`（001/002/004）／`2026-08-05T16:10:00+08:00`（003）
  簽收 Done（見上方各筆 Skill 2 稽核紀錄 + grade report）
- SMCCGP0_001/002 的 P0 稽核與既有 P1 稽核（`smc_clk_running_test_GRADE.md` /
  `smc_static_cg_sanity_test_GRADE.md`）為兩份獨立、互不覆寫的報告，各自對應
  `SMC_CLOCK_GATING`（P1）與 `SMC_CLOCK_GATING_P0`（P0）兩份不同的 card/plan

---

## 下一 session 指令

```text
P0 SMCCGP0_003 blocked on https://github.com/tenstorrent/tt-oca-hw/issues/4413 (OPEN).

After RTL/model fix (latched_en = i_en | i_te or equivalent):
  python3 tools/dv/run_dv.py --dut smc_wrapper --tool verilator --seed 1 --rebuild \
    --items smc_cg_dft_reset_bringup_test
  /dv_test_audit smc_cg_dft_reset_bringup_test
    pin: hw/sys/smc/dv/tb/SMC_CLOCK_GATING_P0_PIN.yaml
    card: SMCCGP0_003
    board: hw/sys/smc/dv/tb/audit_status_smc_clock_gating_p0.md
  then /dv_peer_audit SMC_CLOCK_GATING_P0 (re-review; prior PASS-WITH-FINDINGS STALE on DFT)

Do NOT re-patch prim_clkgater from DV. Owner may alternatively Skill1-defer DFT bringup
checkers until #4413 closes.
```


## 進度備註
- 契約核准：`minshaoho` @ `2026-08-05T15:52:00+08:00`
- Skill 1.5（2026-08-05）：SMCCGP0_003 `smc_cg_dft_reset_bringup_test` 實作完成，`--seed 1`
  PASS，3 個 CHK token 全部在 kept log 中出現一次、順序正確、無未解釋的 ERROR/FATAL/Traceback。
  未做任何評分／勾選；下一手是 Skill 2 `dv_test_audit`。
- Skill 1.5（2026-08-05）：SMCCGP0_004 `smc_cg_zeroer_activity_bringup_test` 實作完成，
  `--seed 1` PASS，5 個 CHK token（`CHK-REG-CLK-IDLE-GATED`、
  `CHK-REG-ACCESS-UNGATES-REG-CLK`、`CHK-BUSY-UNGATES-AXI-CLK`、`CHK-TIMEOUT-PATHS`、
  `CHK-NONVAC`）全部在 kept log 中出現一次、fence 順序正確、無未解釋的
  ERROR/FATAL/Traceback。未做任何評分／勾選；下一手是 Skill 2 `dv_test_audit`。
- Skill 2（2026-08-05）：SMCCGP0_003 `smc_cg_dft_reset_bringup_test` 稽核完成——3/3 checkers
  `PROVEN`（`CHK-DFT-BYPASS-FREE-RUN` LIVE、`CHK-RESET-OVERRIDE-FREE-RUN` CONNECTIVITY、
  `CHK-NONVAC` INTEGRITY），entry `PASS`，card/parent hash 皆 recomputed 相符，force/deposit
  稽核 clean，findings/waivers 皆為空，`recommendation: EVIDENCE-CLOSED-AWAITING-SIGNOFF`。
  已記錄一項跨 testcase 依賴（非阻擋）：`SMCCGP0_001`（DMA + Zeroer axi_clk otherwise-gating）
  與 `SMCCGP0_004`（Zeroer reg_clk otherwise-gating，已跑 PASS 但未稽核）留給 Skill 3 判斷。
  `minshaoho` 已於 `2026-08-05T16:10:00+08:00` 簽收 Done。Grade report：
  `hw/sys/smc/dv/tb/grades/smc_cg_dft_reset_bringup_test_GRADE.md`
  （`schema_check.py` valid，`render_lint.py` agree）。
- Skill 2（2026-08-05，fresh audit）：三卡連續稽核完成——
  1) SMCCGP0_004 `smc_cg_zeroer_activity_bringup_test`：5/5 checkers `PROVEN`
     （`CHK-REG-CLK-IDLE-GATED` LIVE、`CHK-REG-ACCESS-UNGATES-REG-CLK` LIVE、
     `CHK-BUSY-UNGATES-AXI-CLK` LIVE、`CHK-TIMEOUT-PATHS` INTEGRITY、`CHK-NONVAC` INTEGRITY）；
  2) SMCCGP0_001 `smc_clk_running_test`（**P0** card，kept log `fe718c89…`，與已簽收的 P1 卡
     為獨立報告）：5/5 checkers `PROVEN`（`CHK-CG-ENABLE-READBACK` CONNECTIVITY、
     `CHK-IDLE-GATED-BASELINE` LIVE、`CHK-DMA-ACTIVITY-UNGATE` LIVE、`CHK-TIMEOUT-PATHS`
     INTEGRITY、`CHK-NONVAC` INTEGRITY）；
  3) SMCCGP0_002 `smc_static_cg_sanity_test`（**P0** card，kept log `5f14b0fd…`，與已簽收的
     P1 卡為獨立報告）：3/3 checkers `PROVEN`（`CHK-DMA-GATE-DISABLED-FREE-RUN` LIVE、
     `CHK-ZEROER-GATE-DISABLED-FREE-RUN` LIVE、`CHK-NONVAC` INTEGRITY）。
  三者 entry 皆 `PASS`，card/parent plan record hash 皆以 `manifest.py record-hash` 重新計算
  相符，force/deposit 稽核皆 clean（frontdoor CSR + 已核准 JTAG-AXI external-master seed；
  無任何 `force`/`deposit`/`uvm_hdl_*`），findings/waivers 皆為空，`recommendation` 皆為
  `EVIDENCE-CLOSED-AWAITING-SIGNOFF`。三份 grade report 皆通過 `schema_check.py`（valid）與
  `render_lint.py --kind grade-report`（agree）。`minshaoho` 已於 `2026-08-05T16:35:00+08:00`
  簽收全部三筆 Done。SMCCGP0_003 的跨 testcase 依賴備註（`SMCCGP0_001`/`SMCCGP0_004`
  otherwise-gating 對照組）現已由本輪稽核結案，留給 Skill 3 做 union-coverage 確認。
  Grade reports：`hw/sys/smc/dv/tb/grades/smc_cg_zeroer_activity_bringup_test_GRADE.md`、
  `hw/sys/smc/dv/tb/grades/smc_clk_running_test_P0_GRADE.md`、
  `hw/sys/smc/dv/tb/grades/smc_static_cg_sanity_test_P0_GRADE.md`。
- Skill 3（2026-08-05T17:11:00+08:00，fresh peer-audit review）：`dv_peer_audit` milestone gate
  完成，advisory **`PASS-WITH-FINDINGS`**。`closure.py` 確認 13/13 union-coverage closure（0
  excluded/deferred/waived/blocked），3 features 全 covered，`holes: []`／
  `allocation_intent_diff: {}`／`merged_evidence_risk: []`；cross-testcase 無 conflict、無
  `O2`/`E3`；抽樣覆核（SMCCGP0_003/004 全文源碼 + `smc_cg_obs_utils.py` + DUT RTL
  `prim_clkgater.sv`/`prim_clk_gater_hysteresis.sv`）未發現 false-PROVEN；reverse-diff 對
  `SMC_CLOCK_GATING_P0_REVERSE_FEATURE_INVENTORY.md` 為 `CLEAN`。2 個 Minor
  `[QUALITY-OBLIGATION-GAP]` findings（F1: 3 個 spec-audit 補完候選；F2: DMA reset-override
  RTL 觀察未見於 `dma.adoc`），皆 non-blocking、routed to spec owner。Report:
  `hw/sys/smc/dv/tb/SMC_CLOCK_GATING_P0_PEER_AUDIT.md`（`schema_check.py` valid，
  `render_lint.py --kind peer-audit` agree）。Reviewer `run_id:
  dv_peer_audit-SMC_CLOCK_GATING_P0-P0-20260805T171100+0800-fresh` 與所有
  `prior_participants` 皆不同。下一手：spec owner 視需要走 Skill 1 amendment 補 F1/F2（見下方
  `## 下一 session 指令`）；此為 advisory 結果，milestone `Done` 決策仍由人的核准 gate 負責。


## Owner Done

- Milestone **P0 Done** signed by `minshaoho` @ `2026-08-05T17:25:00+08:00` — **re-opened 2026-08-06** for SMCCGP0_003 after `prim_clkgater` revert (DFT evidence STALE; see Skill 2 re-audit)
- Accepts Skill 3 `PASS-WITH-FINDINGS` (13/13, reverse CLEAN; 2 Minor non-blocking)
