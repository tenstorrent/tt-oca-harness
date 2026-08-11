# SMU_SEP — DV 品質流程狀態圖

- **IP**: `SMU_SEP`
- **Milestone**: `P2`
- **Pin**: `hw/sys/smu/dv/tb/SMU_SEP_PIN.yaml`
- **最後更新**: 2026-08-07
- **目前狀態**: **Skill 1 完成（candidate）→ 等人核准 gate #1（feature 語意）**
- **Board path**: `hw/sys/smu/dv/tb/audit_status_smu_sep.md`

圖例：`[x]` 完成 ｜ `[!]` 阻擋中 ｜ `[ ]` 未開始 ｜ `◀━━ 現在在這裡`

---

## 背景（與 SMU_ALL 的關係）

| Board | 狀態 | 與本板關係 |
|---|---|---|
| `SMU_ALL` P2 | 既有 milestone | 曾關閉一小段 SEP 邊界；本板 inventorizes 完整 SEP@SMU 表面，不默認那些 closure |
| **`SMU_SEP`（本板）** | Skill 1 Steps 0–7 done（candidate） | 專責 SEP@SMU 契約 → 人 gate → 實作 → audit → peer |

Helper 路徑：`/proj_soc/user_dev/minshaoho/tryrun/oca_smu/.claude/skills/dv_common/`

---

## Skill 1 — dv_vplan_gen（產生驗證合約）

```
        ┌─────────────────────────────────────────────────┐
        │  Fresh-context gate                             │
   [x]  │  route = fresh-subagent                         │
        │  seal  = ordered-single-context                 │
        │  sealed_derivation = false（validate 傾印 anchors）│
        └────────────────────┬────────────────────────────┘
                             │
        ┌────────────────────▼────────────────────────────┐
   [x]  │  Step 0  Pin gate → confirmed                   │
        └────────────────────┬────────────────────────────┘
                             │
        ┌────────────────────▼────────────────────────────┐
   [x]  │  Step 1  feature_list + spec audit（28 feat / 74 scen / 3 int）│
        └────────────────────┬────────────────────────────┘
                             │
        ┌────────────────────▼────────────────────────────┐
   [x]  │  Step 2  凍結 FL；解封 anchors（40 pinned）       │
        └────────────────────┬────────────────────────────┘
                             │
        ┌────────────────────▼────────────────────────────┐
   [x]  │  Step 3  TESTCASE_PLAN（16 given / 0 derived；16 unalloc）│
        └────────────────────┬────────────────────────────┘
                             │
        ┌────────────────────▼────────────────────────────┐
   [x]  │  Step 4  VPLAN_DETAIL（16 cards）                │
        └────────────────────┬────────────────────────────┘
                             │
        ┌────────────────────▼────────────────────────────┐
   [x]  │  Step 5  stamp + schema_check → all valid       │
        └────────────────────┬────────────────────────────┘
                             │
        ┌────────────────────▼────────────────────────────┐
   [x]  │  Step 6  packets + render_lint → all agree      │
        └────────────────────┬────────────────────────────┘
                             │
        ┌────────────────────▼────────────────────────────┐
   [x]  │  Step 7  收尾報告                                │
        └────────────────────┬────────────────────────────┘
                             ▼
                    ┌─────────────────┐
                    │  人的核准 gate   │  ◀━━ 現在在這裡
                    └─────────────────┘
```

### 人的核准 gate（Skill 1 之後，鏈狀順序）

| # | 角色 | 核准什麼 | 狀態 |
|---|---|---|---|
| 1 | Designer / Architect | feature 語意（`SMU_SEP_FEATURE_REVIEW.md`） | `[ ]` 未開始 ◀━━ |
| 2 | DV owner | testcase set + OWNS + **逐條 accept gap**（`SMU_SEP_TESTCASE_REVIEW.md`） | `[ ]` 未開始 |
| 3 | DV owner | card 機制（`SMU_SEP_CARD_REVIEW.md`） | `[ ]` 未開始 |
| 4 | Spec owner | `SF-*` 問題（`SMU_SEP_SPEC_REVIEW.md`） | `[ ]` 未開始 |

---

## 下游 Skills（Skill 1 核准後）

```
   [ ]  Skill 1.5  dv_test_impl   ── 一張核准卡 → 可跑 test + kept log
                     │
   [ ]  Skill 2    dv_test_audit  ── 逐卡 PROVEN / NOT-READY（fresh subagent）
                     │
   [ ]  Skill 3    dv_peer_audit  ── 全卡 CLOSED 後 union-coverage + reverse inventory
```

---

## Skill 1 產出摘要（candidate）

| Artifact | schema_check / render_lint |
|---|---|
| `SMU_SEP_SPEC_FEATURE_LIST.md` | valid |
| `SMU_SEP_TESTCASE_PLAN.md` | valid |
| `SMU_SEP_VPLAN_DETAIL.md` | valid |
| `SMU_SEP_SPEC_REVIEW.md` | valid |
| `SMU_SEP_FEATURE_REVIEW.md` | agree |
| `SMU_SEP_TESTCASE_REVIEW.md` | agree |
| `SMU_SEP_CARD_REVIEW.md` | agree |

- Features: **28** · Scenarios: **74** · Interactions: **3**
- Testcases: **16** all `origin: given` (pinned reuse) · `origin: derived`: **0**
- Unallocated: **16** — OUT-OF-MILESTONE×13 · BLOCKED-BY-SPEC-FINDING×3（SF-001, SF-005×2）
- Critical/High SF: **SF-001, SF-003, SF-005, SF-006**（另 Medium SF-002/SF-007, Low SF-004）
- Pin 40 anchors；review budget 限制本 rev 只掛 16 張卡；其餘 pinned 名留待 P3/packet-split

---

## 阻擋詳情（當前為 `[!]` 時填寫）

| # | 項目 | 現況 | 解除條件 | 狀態 |
|---|---|---|---|---|
| — | （無 Skill 1 技術阻擋） | Steps 0–7 完成 | 人 gate 核准 | — |

---

## 下一 session 指令

```
/dv_vplan_gen Continue SMU_SEP Skill 1 human gates.
  Pin: hw/sys/smu/dv/tb/SMU_SEP_PIN.yaml
  Board: hw/sys/smu/dv/tb/audit_status_smu_sep.md
  Helpers: /proj_soc/user_dev/minshaoho/tryrun/oca_smu/.claude/skills/dv_common/
  Resume: human gate #1 — designer/architect approve feature semantics in
          SMU_SEP_FEATURE_REVIEW.md (then DV owner TESTCASE_REVIEW gaps,
          then CARD_REVIEW; spec owner answers SF-* in SMU_SEP_SPEC_REVIEW.md).
  Paste into a NEW session. Neutral inputs only: pin path + follow
  dv_vplan_gen SKILL.md. Do not invent approvals. After all four gates,
  hand off to /dv_test_impl for the first approved card (prefer SEP_SMU_001 /
  smu_sep_smoke_test). Board path: hw/sys/smu/dv/tb/audit_status_smu_sep.md.
```
