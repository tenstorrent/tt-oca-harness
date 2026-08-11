<!-- SPDX-License-Identifier: Apache-2.0 -->
# SMC_CLOCK_GATING — Skill 1 Steps and Results

- **IP**: `SMC_CLOCK_GATING`
- **Milestone**: `P1` (pin field; boundary prose still mentions P0–P2 closure semantics)
- **Skill**: `dv_vplan_gen` (Skill 1)
- **Board**: `hw/sys/smc/dv/tb/audit_status_smc_clock_gating.md`
- **Last updated**: 2026-08-07

## 1. Goal

Turn the pinned SPEC into an approvable verification contract: feature_list → testcase plan → per-anchor checkbox cards → spec audit, and produce the three role-scoped review packets.

## 2. Inputs (Pin)

| Item | Value |
|---|---|
| Pin | `hw/sys/smc/dv/tb/SMC_CLOCK_GATING_PIN.yaml` |
| `pin_revision` | 1 |
| `confirmed_by` / `confirmed_at` | `minshaoho` / `2026-08-05T12:00:00+08:00` |
| `anchor_mode` | `augment` |
| Seed anchors | `smc_clk_multi_window_test`, `smc_clk_running_test`, `smc_i2c_cg_sanity_test`, `smc_pll_cgm_awm_config_test`, `smc_static_cg_sanity_test` |
| Policy | `/home/minshaoho/.claude/skills/dv_common/DV_QUALITY_POLICY.md` |

Pinned SPEC (9 files):

- `hw/sys/smc/doc/{index,overview,clk_rst,port_table,dma,zeroer,periphs,fabric,memmap}.adoc`

## 3. Execution steps

1. **Pin confirmation** — owner fills `confirmed_by` / `confirmed_at`, boundary, anchors, `anchor_mode=augment`.
2. **Fresh Skill 1 child session** — `dv_vplan_gen`; `generated_by.run_id` ≈ `dv_vplan_gen-smc_clock_gating-fresh_subagent-20260805T080404+0800` (claude-sonnet).
3. **Feature list freeze** — `feature_list_frozen_at: 2026-08-05T08:20:00+08:00`.
4. **All human gates signed** — `approved_by: minshaoho` @ `2026-08-05T09:20:00+08:00`:
   - feature_list / testcase plan / VPLAN cards / SPEC·FEATURE·TESTCASE·CARD reviews all `status: approved`.
5. **SF disposition** — SF-001/005 waived; SF-002/003/004/006 answered (including SF-004: Zeroer `register_activity` = any AXI4-Lite access).
6. **Artifacts written** under `hw/sys/smc/dv/tb/`, and `audit_status_smc_clock_gating.md` maintained.

## 4. Artifacts

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

Approval chain (after Skill 1, before Skill 1.5):

1. **designer** — feature semantics (`FEATURE_REVIEW`) and SPEC questions (`SPEC_REVIEW` / SF).
2. **dv** — testcase set + OWNS + gap accept (`TESTCASE_REVIEW`), then card mechanics (`CARD_REVIEW`).

Only after both sides sign is the card `status: approved`, and Skill 1.5 may start.

## 5. Example: how Skill 1.5 creates a test

Using the approved card `SMC_DMA_CG_ACTIVITY_TEST` (anchor `smc_dma_cg_activity_test`) as an example of how Skill 1.5 (`dv_test_impl`) turns one card into a runnable test.

### 5.1 Entry conditions (all required)

- Card and parent testcase record are both `status: approved` (Skill 1 human gates passed).
- Every `SF-*` blocker on the card is `answered` / `waived`; no `TBD-`.
- Env + `top_tb` chosen (this example: `cocotb` + `hw/sys/smc/dv/tb/tb_top.sv`).
- Hard constraint: no DUT force/deposit on the proof path; do not weaken checkers.

### 5.2 Create flow (example)

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

### 5.3 Typical outputs for this example

| Item | Notes |
|---|---|
| Sequence | `hw/sys/smc/dv/cocotb/seq_lib/smc_dma_cg_activity_test_seq.py` |
| Test wrapper | `hw/sys/smc/dv/cocotb/tests/smc_dma_cg_activity_test.py` |
| Testlist | enroll `smc_dma_cg_activity_test` in `hw/sys/smc/dv/testlists/clock.toml` |
| Kept log | `hw/sys/smc/dv/build/runs/<run_dir>/…` + sha256 |
| Evidence | one `CHK-<NAME>: …` line per checker (including `CHK-NONVAC`) |

Skill 1.5 **does not grade and does not write PROVEN**; its strongest claim is: "the run finished and these tokens appeared in the kept log." Formal grading is Skill 2.

### 5.4 When DV review / approve is required

| When | Who | Approves what | If skipped |
|---|---|---|---|
| After Skill 1 | **dv** (after designer feature/SPEC signoff) | `TESTCASE_REVIEW`: testcase set, OWNS split, accept each OUT-OF-MILESTONE / gap | Skill 1.5 entry gate refuses |
| After Skill 1 | **dv** | `CARD_REVIEW`: steps, checkers, fail_on, whether observation points are implementable | Must not write code against an unapproved card |
| After Skill 1.5 tokens OK | **dv** (optional; often folded into Skill 2) | Implementation fidelity to the card; env/testlist wiring | May proceed to Skill 2; contract doubts go back to Skill 1 first |
| After Skill 2 grade | **dv** owner signoff | grade = `EVIDENCE-CLOSED` closes the card | Stays `AWAITING-SIGNOFF` / `NOT-READY` |
| Impl finds card unobservable / SPEC wrong | **dv** must not rewrite the contract alone | Escalate Skill 1 amend → **designer + dv** re-approve the changed parts | Forbidden to weaken checkers or change expectations in 1.5 |

In one line: **DV approve gates "may this card be written" and "may this card's evidence close"**; Skill 1.5 only turns an already-approved card into a kept log with tokens.
