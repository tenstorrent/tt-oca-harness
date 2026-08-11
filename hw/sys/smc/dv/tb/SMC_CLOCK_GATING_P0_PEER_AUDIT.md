---
schema: dv-quality/v1
artifact: ip-peer-audit
ip: SMC_CLOCK_GATING_P0
milestone: P0
mode: CHECKBOX-MAPPING
repository_revision: 2ecc7b227e3926b253c65b5aac21239eec24ba5f
spec:
- path: hw/sys/smc/doc/index.adoc
  revision: 2ecc7b227e3926b253c65b5aac21239eec24ba5f
- path: hw/sys/smc/doc/overview.adoc
  revision: 2f40548ea787240680a1c45ab75b8729e9620778
- path: hw/sys/smc/doc/clk_rst.adoc
  revision: 2f40548ea787240680a1c45ab75b8729e9620778
- path: hw/sys/smc/doc/port_table.adoc
  revision: 2ecc7b227e3926b253c65b5aac21239eec24ba5f
- path: hw/sys/smc/doc/dma.adoc
  revision: e2aae39953bb8001c7c20e3afd3956e68c22440c
- path: hw/sys/smc/doc/zeroer.adoc
  revision: 2f40548ea787240680a1c45ab75b8729e9620778
- path: hw/sys/smc/doc/periphs.adoc
  revision: ffc8cdcc349e1e01a2b970442a01070b1c62c0d7
- path: hw/sys/smc/doc/fabric.adoc
  revision: ffc8cdcc349e1e01a2b970442a01070b1c62c0d7
- path: hw/sys/smc/doc/memmap.adoc
  revision: 2ecc7b227e3926b253c65b5aac21239eec24ba5f
pin_revision: 1
feature_list_sha256: a5d5f6f1f55a8d4de7436f84c1729ec544c123251bf3338d4f49bff48df2fe90
feature_list_revision: 1
testcase_plan_sha256: a0693deada1cf76a6dee1065ebffad8d390167af5fdfd3e86fcc2d552832c28e
testcase_plan_revision: 1
cards_sha256: 4050055c70d00e6ffc6f10104fd5d90adabdb5f6d803324d867a008669a6970b
derivation_provenance:
  sealed_derivation: true
  anchor_seal_mechanism: ordered-single-context
  fresh_context_route: fresh-subagent
  feature_list_frozen_at: '2026-08-05T15:30:00+08:00'
evidence_policy_sha256: 51a3357d9c31a018d69451b055bc956c089af26e1051368e25ce396c84ac2a75
quality_policy_sha256: 51a3357d9c31a018d69451b055bc956c089af26e1051368e25ce396c84ac2a75
grade_report_sha256:
- 3dcfef546388bbd24947bf06fe74ae50fcf6233e04859aa3718d16bfcd341288
- d47e1cd8c045bebd43c4727d1002f63f7b0cdfd2c23336547e48cf480e20f22f
- bb34897a280ace3f8ab643c8cbac59d4ccae0910f55896ac10feb88806548757
- d076ac7d64d31725e72a61889ed9cf5cdf0d9d19366d2112042912d3630d766a
reviewer:
  human_id: minshaoho
  run_id: dv_peer_audit-SMC_CLOCK_GATING_P0-P0-20260805T171100+0800-fresh
  model: {provider: cursor, family: claude, version: sonnet-5}
prior_participants:
- role: feature-list-generator
  human_id: minshaoho
  run_id: dv_vplan_gen-SMC_CLOCK_GATING_P0-P0-20260805T151500+0800-fresh
  model: {provider: anthropic, family: claude, version: sonnet-5}
- role: implementer
  human_id: minshaoho
  run_id: dv_test_impl-SMCCGP0_001-P0-20260805T151500+0800
  model: {provider: unknown, family: unknown, version: unknown}
- role: implementer
  human_id: minshaoho
  run_id: dv_test_impl-SMCCGP0_002-P0-20260805T151500+0800
  model: {provider: unknown, family: unknown, version: unknown}
- role: implementer
  human_id: minshaoho
  run_id: dv_test_impl-SMC_CG_DFT_RESET_BRINGUP_TEST-20260805T080136+0800
  model: {provider: unknown, family: unknown, version: unknown}
- role: implementer
  human_id: minshaoho
  run_id: dv_test_impl-SMCCGP0_004-20260805T081125+0800
  model: {provider: unknown, family: unknown, version: unknown}
- role: skill2-auditor
  human_id: minshaoho
  run_id: dv_test_audit-SMCCGP0_001-fresh-20260805T162700+0800
  model: {provider: cursor, family: claude, version: sonnet-5}
- role: skill2-auditor
  human_id: minshaoho
  run_id: dv_test_audit-SMCCGP0_002-fresh-20260805T162700+0800
  model: {provider: cursor, family: claude, version: sonnet-5}
- role: skill2-auditor
  human_id: minshaoho
  run_id: dv_test_audit-SMC_CG_DFT_RESET_BRINGUP_TEST-6a528a99af8141c7947aee6210944a2f
  model: {provider: cursor, family: claude, version: sonnet-5}
- role: skill2-auditor
  human_id: minshaoho
  run_id: dv_test_audit-SMCCGP0_004-fresh-20260805T162700+0800
  model: {provider: cursor, family: claude, version: sonnet-5}
denominator:
  inventory_keys: 13
  excluded_keys: 0
  milestone_required_keys: 13
  covered_keys: 13
coverage:
- key: SMC-CG-DMA.S1
  required_proof_class: LIVE
  status: COVERED
  allocated_to: SMCCGP0_003
  closed_by_allocated: true
  proven_by:
  - checker_ref: smc_cg_dft_reset_bringup_test/CHK-DFT-BYPASS-FREE-RUN
    independent_evidence: {required: false, method: NOT-REQUIRED, source_run_id: null, source_log_sha256: null, run_id: null, build_fingerprint: null, log_or_artifact_sha256: null, observer: {human_id: null, model: {provider: null, family: null, version: null}}, gate_satisfied: false}
  required_cells: [test-mode-bypass-free-running]
  achieved_cells: [test-mode-bypass-free-running]
- key: SMC-CG-DMA.S2
  required_proof_class: LIVE
  status: COVERED
  allocated_to: SMCCGP0_001
  closed_by_allocated: true
  proven_by:
  - checker_ref: smc_clk_running_test/CHK-IDLE-GATED-BASELINE
    independent_evidence: {required: false, method: NOT-REQUIRED, source_run_id: null, source_log_sha256: null, run_id: null, build_fingerprint: null, log_or_artifact_sha256: null, observer: {human_id: null, model: {provider: null, family: null, version: null}}, gate_satisfied: false}
  required_cells: [idle-gated-post-reset]
  achieved_cells: [idle-gated-post-reset]
- key: SMC-CG-DMA.S3
  required_proof_class: LIVE
  status: COVERED
  allocated_to: SMCCGP0_001
  closed_by_allocated: true
  proven_by:
  - checker_ref: smc_clk_running_test/CHK-DMA-ACTIVITY-UNGATE
    independent_evidence: {required: false, method: NOT-REQUIRED, source_run_id: null, source_log_sha256: null, run_id: null, build_fingerprint: null, log_or_artifact_sha256: null, observer: {human_id: null, model: {provider: null, family: null, version: null}}, gate_satisfied: false}
  required_cells: [activity-ungates-clock]
  achieved_cells: [activity-ungates-clock]
- key: SMC-CG-DMA.S4
  required_proof_class: LIVE
  status: COVERED
  allocated_to: SMCCGP0_002
  closed_by_allocated: true
  proven_by:
  - checker_ref: smc_static_cg_sanity_test/CHK-DMA-GATE-DISABLED-FREE-RUN
    independent_evidence: {required: false, method: NOT-REQUIRED, source_run_id: null, source_log_sha256: null, run_id: null, build_fingerprint: null, log_or_artifact_sha256: null, observer: {human_id: null, model: {provider: null, family: null, version: null}}, gate_satisfied: false}
  required_cells: [gate-disabled-free-running]
  achieved_cells: [gate-disabled-free-running]
- key: SMC-CG-ZEROER.S1
  required_proof_class: CONNECTIVITY
  status: COVERED
  allocated_to: SMCCGP0_003
  closed_by_allocated: true
  proven_by:
  - checker_ref: smc_cg_dft_reset_bringup_test/CHK-RESET-OVERRIDE-FREE-RUN
    independent_evidence: {required: false, method: NOT-REQUIRED, source_run_id: null, source_log_sha256: null, run_id: null, build_fingerprint: null, log_or_artifact_sha256: null, observer: {human_id: null, model: {provider: null, family: null, version: null}}, gate_satisfied: false}
  required_cells: [reset-forces-free-running]
  achieved_cells: [reset-forces-free-running]
- key: SMC-CG-ZEROER.S2
  required_proof_class: LIVE
  status: COVERED
  allocated_to: SMCCGP0_003
  closed_by_allocated: true
  proven_by:
  - checker_ref: smc_cg_dft_reset_bringup_test/CHK-DFT-BYPASS-FREE-RUN
    independent_evidence: {required: false, method: NOT-REQUIRED, source_run_id: null, source_log_sha256: null, run_id: null, build_fingerprint: null, log_or_artifact_sha256: null, observer: {human_id: null, model: {provider: null, family: null, version: null}}, gate_satisfied: false}
  required_cells: [test-enable-bypass]
  achieved_cells: [test-enable-bypass]
- key: SMC-CG-ZEROER.S3
  required_proof_class: LIVE
  status: COVERED
  allocated_to: SMCCGP0_001
  closed_by_allocated: true
  proven_by:
  - checker_ref: smc_clk_running_test/CHK-IDLE-GATED-BASELINE
    independent_evidence: {required: false, method: NOT-REQUIRED, source_run_id: null, source_log_sha256: null, run_id: null, build_fingerprint: null, log_or_artifact_sha256: null, observer: {human_id: null, model: {provider: null, family: null, version: null}}, gate_satisfied: false}
  required_cells: [axi-clk-idle-gated]
  achieved_cells: [axi-clk-idle-gated]
- key: SMC-CG-ZEROER.S4
  required_proof_class: LIVE
  status: COVERED
  allocated_to: SMCCGP0_004
  closed_by_allocated: true
  proven_by:
  - checker_ref: smc_cg_zeroer_activity_bringup_test/CHK-BUSY-UNGATES-AXI-CLK
    independent_evidence: {required: false, method: NOT-REQUIRED, source_run_id: null, source_log_sha256: null, run_id: null, build_fingerprint: null, log_or_artifact_sha256: null, observer: {human_id: null, model: {provider: null, family: null, version: null}}, gate_satisfied: false}
  required_cells: [busy-ungates-axi-clk]
  achieved_cells: [busy-ungates-axi-clk]
- key: SMC-CG-ZEROER.S5
  required_proof_class: LIVE
  status: COVERED
  allocated_to: SMCCGP0_004
  closed_by_allocated: true
  proven_by:
  - checker_ref: smc_cg_zeroer_activity_bringup_test/CHK-REG-CLK-IDLE-GATED
    independent_evidence: {required: false, method: NOT-REQUIRED, source_run_id: null, source_log_sha256: null, run_id: null, build_fingerprint: null, log_or_artifact_sha256: null, observer: {human_id: null, model: {provider: null, family: null, version: null}}, gate_satisfied: false}
  required_cells: [reg-clk-idle-gated]
  achieved_cells: [reg-clk-idle-gated]
- key: SMC-CG-ZEROER.S6
  required_proof_class: LIVE
  status: COVERED
  allocated_to: SMCCGP0_004
  closed_by_allocated: true
  proven_by:
  - checker_ref: smc_cg_zeroer_activity_bringup_test/CHK-REG-ACCESS-UNGATES-REG-CLK
    independent_evidence: {required: false, method: NOT-REQUIRED, source_run_id: null, source_log_sha256: null, run_id: null, build_fingerprint: null, log_or_artifact_sha256: null, observer: {human_id: null, model: {provider: null, family: null, version: null}}, gate_satisfied: false}
  required_cells: [register-access-ungates-reg-clk]
  achieved_cells: [register-access-ungates-reg-clk]
- key: SMC-CG-ZEROER.S7
  required_proof_class: LIVE
  status: COVERED
  allocated_to: SMCCGP0_002
  closed_by_allocated: true
  proven_by:
  - checker_ref: smc_static_cg_sanity_test/CHK-ZEROER-GATE-DISABLED-FREE-RUN
    independent_evidence: {required: false, method: NOT-REQUIRED, source_run_id: null, source_log_sha256: null, run_id: null, build_fingerprint: null, log_or_artifact_sha256: null, observer: {human_id: null, model: {provider: null, family: null, version: null}}, gate_satisfied: false}
  required_cells: [gate-disabled-free-running]
  achieved_cells: [gate-disabled-free-running]
- key: SMC-CG-ENABLE-CTRL.S1
  required_proof_class: CONNECTIVITY
  status: COVERED
  allocated_to: SMCCGP0_001
  closed_by_allocated: true
  proven_by:
  - checker_ref: smc_clk_running_test/CHK-CG-ENABLE-READBACK
    independent_evidence: {required: false, method: NOT-REQUIRED, source_run_id: null, source_log_sha256: null, run_id: null, build_fingerprint: null, log_or_artifact_sha256: null, observer: {human_id: null, model: {provider: null, family: null, version: null}}, gate_satisfied: false}
  required_cells: [dma-cg-enable-frontdoor-reachable]
  achieved_cells: [dma-cg-enable-frontdoor-reachable]
- key: SMC-CG-ENABLE-CTRL.S2
  required_proof_class: CONNECTIVITY
  status: COVERED
  allocated_to: SMCCGP0_001
  closed_by_allocated: true
  proven_by:
  - checker_ref: smc_clk_running_test/CHK-CG-ENABLE-READBACK
    independent_evidence: {required: false, method: NOT-REQUIRED, source_run_id: null, source_log_sha256: null, run_id: null, build_fingerprint: null, log_or_artifact_sha256: null, observer: {human_id: null, model: {provider: null, family: null, version: null}}, gate_satisfied: false}
  required_cells: [zeroer-disable-cg-frontdoor-reachable]
  achieved_cells: [zeroer-disable-cg-frontdoor-reachable]
residuals: []
findings:
- id: F1
  tag: "[QUALITY-OBLIGATION-GAP]"
  severity: Minor
  affected_keys: []
  artifact_ref: "hw/sys/smc/dv/tb/SMC_CLOCK_GATING_P0_REVERSE_FEATURE_INVENTORY.md sf_findings SF-003/SF-005/SF-006 @ content sha256 58f6b0725acc3b1ae67e8a2aa05c5fb128e038e1ed351881193d9ef7d5cddf24"
  observed: "The anchor-blind reverse inventory raised three SPEC-clarity candidates not tracked in the approved SMC_CLOCK_GATING_P0_SPEC_REVIEW.md: (SF-003) clk_rst.adoc's generic hysteresis table vs. zeroer.adoc's pure level-sensitive gating formulas leaves it ambiguous whether Zeroer clock gating includes hysteresis, which bears on whether the pin's 'full hysteresis sweeps' P0 exclusion even applies to Zeroer; (SF-005) zeroer.adoc's axi_clk/reg_clk clock names do not appear in port_table.adoc's SMC Port Declaration table; (SF-006) neither dma.adoc nor zeroer.adoc names the exact internal test-enable port reached on each block's specific gater cell. None of the three affects any of this milestone's 13 required keys or their proof class — the reverse-diff itself resolves CLEAN against the approved feature_list — but they are new spec-audit candidates the approved SMC_CLOCK_GATING_P0_SPEC_REVIEW.md does not yet carry."
  owner: "Spec owner (via a Skill 1 SMC_CLOCK_GATING_P0_SPEC_REVIEW.md amendment)"
  closure_condition: "SMC_CLOCK_GATING_P0_SPEC_REVIEW.md gains SF entries for the three observations above, each with a disposition (answered/waived/open), in a reviewed revision."
- id: F2
  tag: "[QUALITY-OBLIGATION-GAP]"
  severity: Minor
  affected_keys: []
  artifact_ref: "hw/common/och_prim/rtl/prim_clk_gater_hysteresis.sv:48 (run = ~rst_ni | kick_i | nz_hyst | ~enable_i)"
  observed: "Read-only RTL sampling (common-mode risk check, DV_SKILL3_SPEC.md S4.5) shows the DMA hysteresis gater's own `run` term includes `~rst_ni`, a reset-override structurally analogous to Zeroer's documented reset-override term (SMC-CG-ZEROER.S1, sourced from zeroer.adoc 'Clock Gating - Reset Override'). dma.adoc documents no equivalent reset-override behavior for DMA, and neither the approved feature_list, the approved spec-audit, nor the independently-derived reverse inventory found one in the nine pinned SPEC docs. This is not used to invent a required P0 scenario -- the pin boundary explicitly excludes RTL-as-spec, and the SPEC docs are silent -- it is filed as a documentation-completeness observation only."
  owner: "Spec owner"
  closure_condition: "dma.adoc documents (or explicitly disclaims) a reset-override term for the DMA clock-gate branch in a future SPEC revision; if confirmed present, a P1/P2 scenario is added via Skill 1 amendment."
inventory_delta:
  status: CLEAN
  keys: []
reverse_diff:
  spec_sha256: null
  generated_inventory_sha256: 58f6b0725acc3b1ae67e8a2aa05c5fb128e038e1ed351881193d9ef7d5cddf24
  run_id: dv_vplan_gen-SMC_CLOCK_GATING_P0-reverse-inventory-20260805T090055Z-fresh
  actor:
    human_id: fresh-subagent-unattended
    model: {provider: anthropic, family: claude, version: claude-sonnet-4.5}
  compared_generator:
    run_id: dv_vplan_gen-SMC_CLOCK_GATING_P0-P0-20260805T151500+0800-fresh
    model: {provider: anthropic, family: claude, version: sonnet-5}
  separation_gate_satisfied: true
  reviewed_by: minshaoho
  disposition: CLEAN
result: PASS-WITH-FINDINGS
---

## EXECUTIVE RESULT

**Result: `PASS-WITH-FINDINGS`** — full milestone closure with 2 Minor, non-blocking findings.

Required at P0: **13 of 13** inventory keys (0 deferred, 0 excluded). Covered: **13 of 13**.
Features: 3 of 3 covered (SMC-CG-DMA 4/4, SMC-CG-ZEROER 7/7, SMC-CG-ENABLE-CTRL 2/2) ·
Interactions: 0 required (none declared, both the approved feature_list and the independent
reverse inventory agree) · Real gaps: 0 · Blocked: 0 · Deferred: 0 · Waived: 0 ·
Findings: 0 Blocking, 0 Major, 2 Minor · Reverse-diff: **CLEAN** · Derivation: sealed
(`ordered-single-context`, `fresh-subagent`).

**Why:** all 4 approved testcases' Skill 2 grades are 16/16 checkers `PROVEN`, `closure.py`
independently confirms `holes: []` / `allocation_intent_diff: {}` / `merged_evidence_risk: []`
against the approved plan and cards, every checker meets its scenario's minimum proof class,
sampled re-verification of both newly-derived testcases (SMCCGP0_003/004, read in full) and
the shared observation helpers found no false-`PROVEN`, no vacuity, and no backdoor/force, and
the anchor-blind reverse inventory maps cleanly onto the approved feature_list at scenario
granularity. Two Minor findings (spec-audit completeness gaps) remain open for the spec owner
and do not affect any required key's coverage or class.

## BLOCKING ITEMS

None. No `REAL-GAP` / `BLOCKED` / `OUT-OF-SCOPE` residual exists; no unresolved cross-testcase
conflict; no false-`PROVEN` found on re-verification.

## COVERAGE MAP

| Feature | Scenarios | Status |
|---|---|---|
| `SMC-CG-DMA` — DMA controller clock-gated operation | 4/4 required | covered (SMCCGP0_001, SMCCGP0_002, SMCCGP0_003) |
| `SMC-CG-ZEROER` — Memory Zeroer dual-clock-domain clock-gated operation | 7/7 required | covered (SMCCGP0_001, SMCCGP0_002, SMCCGP0_003, SMCCGP0_004) |
| `SMC-CG-ENABLE-CTRL` — Frontdoor reachability of the DMA/Zeroer gating-enable controls | 2/2 required | covered (SMCCGP0_001) |

No feature carries a deferred/waived/blocked scenario at this milestone (`unallocated: []` in
the approved plan), so no feature shows a split tally and no scenario-level rows are needed.

## FINDINGS

| # | Sev | Tag | What | Owner | Closure condition |
|---|---|---|---|---|---|
| F1 | 🟡 Minor | `[QUALITY-OBLIGATION-GAP]` | Reverse-diff surfaced 3 SPEC-clarity candidates (Zeroer hysteresis-vs-level-gating ambiguity; `axi_clk`/`reg_clk` not named in `port_table.adoc`; DFT per-cell `test_en_i` identity gap) not yet tracked in the approved spec-audit. Advisory only — affects 0 required keys. | Spec owner (Skill 1 amendment) | `SMC_CLOCK_GATING_P0_SPEC_REVIEW.md` gains SF entries for all three, each disposed, in a reviewed revision. |
| F2 | 🟡 Minor | `[QUALITY-OBLIGATION-GAP]` | Read-only RTL sample: DMA's `prim_clk_gater_hysteresis.run` includes a `~rst_ni` term structurally like Zeroer's documented reset-override, but `dma.adoc` documents no such DMA behavior. Not used to invent a requirement (RTL-as-spec is out of the pin's boundary); filed as a documentation note only. Affects 0 required keys. | Spec owner | `dma.adoc` documents or explicitly disclaims a DMA reset-override term in a future SPEC revision. |

Both findings are advisory/candidate observations surfaced by the mandatory reverse-diff and
common-mode RTL sampling; neither is a required item, neither affects the closure arithmetic
above, and neither blocks this result.

## RESIDUAL LEDGER

| Key | Class | Counts against closure? | Authority | Closes at |
|---|---|---|---|---|
| — | — | — | all 13 required keys are `COVERED`; no residual row applies | — |

## MACHINERY APPENDIX

**Freeze (manifest.py hash-file, this session):**

| Artifact | sha256 |
|---|---|
| `SMC_CLOCK_GATING_P0_PIN.yaml` | `473f491c0c9dc1aa45e2417edd46991404db246566ff13219fa8b1273e7a4819` |
| `SMC_CLOCK_GATING_P0_SPEC_FEATURE_LIST.md` (whole file) | `3e53b23942c8a2825a4bff663020a21c50ed0955d7773e972268c13063558aad` (front-matter `content_sha256` `a5d5f6f1…`) |
| `SMC_CLOCK_GATING_P0_TESTCASE_PLAN.md` (whole file) | `1066613118747b4f7933cd0a4190fd79edc6f150826326386dc4b47bede68140` (front-matter `content_sha256` `a0693dea…`) |
| `SMC_CLOCK_GATING_P0_VPLAN_DETAIL.md` (whole file) | `1db0fd7424d894c77a63ad99ef96c47ec9755532360a7cef1c65e8f3f7e1aafe` (front-matter `content_sha256` `4050055c…`) |
| `SMC_CLOCK_GATING_P0_SPEC_REVIEW.md` (whole file) | `da11ecdacfa0ec4abcbbf55dda1a30fa36d6e36900c7619f0129ef206ba7e35e` |
| `smc_clk_running_test_P0_GRADE.md` | `3dcfef546388bbd24947bf06fe74ae50fcf6233e04859aa3718d16bfcd341288` |
| `smc_static_cg_sanity_test_P0_GRADE.md` | `d47e1cd8c045bebd43c4727d1002f63f7b0cdfd2c23336547e48cf480e20f22f` |
| `smc_cg_dft_reset_bringup_test_GRADE.md` | `bb34897a280ace3f8ab643c8cbac59d4ccae0910f55896ac10feb88806548757` |
| `smc_cg_zeroer_activity_bringup_test_GRADE.md` | `d076ac7d64d31725e72a61889ed9cf5cdf0d9d19366d2112042912d3630d766a` |
| `DV_QUALITY_POLICY.md` | `51a3357d9c31a018d69451b055bc956c089af26e1051368e25ce396c84ac2a75` — **matches** the pin's declared `quality_policy.revision` exactly |
| `SMC_CLOCK_GATING_P0_REVERSE_FEATURE_INVENTORY.md` (whole file) | `58f6b0725acc3b1ae67e8a2aa05c5fb128e038e1ed351881193d9ef7d5cddf24` — matches the value supplied for this review |

All 4 grade reports and all 4 Skill 1 candidate artifacts (`feature-list`, `testcase-plan`,
`checkbox-cards`, `spec-audit`) independently pass `schema_check.py` → `valid`. Gate check
(§ Hard preconditions #3): pin `milestone: P0` == feature_list/plan/cards/spec-audit
`milestone: P0`, and pin `pin_revision: 1` matches every artifact's declared `pin_revision: 1`
— confirmed, not an entry error. Mode selection (§4.1): approved feature_list **and** approved
plan **and** approved cards all present (`status: approved` on all three, `approved_by:
minshaoho @ 2026-08-05T15:52:00+08:00`) → `CHECKBOX-MAPPING`, the only mode entitled to certify
closure.

**Step 1 — closure.py (facts, unmodified):**

```
denominator: {inventory_keys: 13, excluded_keys: 0, milestone_required_keys: 13, covered_keys: 13}
holes: []
proof_class_violations: []
unsatisfied_coverage: []
unknown_keys: []
overlap: {}
allocation_intent_diff: {unmet: [], accidental: [], fully_unmet_testcases: []}
merged_evidence_risk: []
skipped_reports: []
proven_checkers_seen: 16
declared_but_never_proven: []
```

Every one of the 13 scenario keys is closed by exactly one `PROVEN` checker whose
`required_cells`/`achieved_cells` match and whose `proof_class` meets or exceeds the scenario's
declared minimum (`CONNECTIVITY` scenarios closed by `CONNECTIVITY`; `LIVE` scenarios closed by
`LIVE` — no `DECODE`/`CONNECTIVITY` checker is credited against a `LIVE` requirement). Closure
statement (§4.2 step 7, only emitted because every required key is `COVERED` — no residual to
carve out):

> 100% feature-mapped evidence closure for the frozen **P0** non-residual required scenario set
> (**13** of **13** inventory keys required at this milestone); no `MILESTONE-DEFERRED`/`WAIVED`/
> `UNREACHABLE` exclusions exist at this milestone.

**Step 2 — cross-testcase pass.** Claim matrix built across all 16 checkers (gating-enable
polarity, idle/active exact-toggle-count semantics, module-gating enable=1/disable=0
convention, fence-order discipline): consistent throughout — every checker uses the *same*
shared helpers (`smc_cg_obs_utils.count_enabled_at_smc_rise` /
`count_enabled_pair_at_smc_rise` / `count_enabled_triple_at_smc_rise` /
`assert_fence_order`), the same exact-count (not "at least one") assertion style, and the same
`DMA_CG_EN`/`ZEROER_CG_EN` polarity (1 = gating enabled) — no `[CROSS-TESTCASE-CONFLICT]`, no
`[CROSS-TESTCASE-CONSISTENCY]` finding. **Logistics:** all 4 anchors
(`smc_clk_running_test`, `smc_static_cg_sanity_test`, `smc_cg_dft_reset_bringup_test`,
`smc_cg_zeroer_activity_bringup_test`) are enrolled in `hw/sys/smc/dv/testlists/clock.toml`'s
`clock` regression group — no `E3` orphan. **Ownership:** plan `owns` fields partition cleanly
(each scenario allocated to exactly one testcase; `closure.py overlap: {}` confirms no
double-count). **`[MERGED-EVIDENCE]`:** `interactions: []` in the approved feature_list (agreed
by the reverse inventory), so no interaction-joint-line risk exists in this milestone; the two
checkers that jointly prove multiple keys from one evidence line
(`CHK-CG-ENABLE-READBACK` → `SMC-CG-ENABLE-CTRL.S1`+`.S2`; `CHK-DFT-BYPASS-FREE-RUN` →
`SMC-CG-DMA.S1`+`SMC-CG-ZEROER.S2`) are ordinary single-testcase checkers with independent
per-key `coverage_results` records (each field/clock asserted on its own), not interaction
checkers, so `[MERGED-EVIDENCE]` does not apply to them.

**Step 3 — intent modes.** `O2`: each sampled checker's asserted target (kept-log token +
implementation line, cited in each grade report's appendix) matches its card's `PROOF` field
verbatim in method and target signal — no wrong-target checker found. `E3`: covered under
Logistics above — all 4 approved, allocated testcases are enrolled; none.

**Step 4 — sampled quality (policy floor: all tier-A + 20% of the rest, min 5).** Tier-A
checkers = 13 of 16 (SMCCGP0_001 ×5, SMCCGP0_002 ×3, SMCCGP0_004 ×5); tier-B = 3
(SMCCGP0_003). Sampled/read in full for this review: `smc_cg_obs_utils.py` (shared infra, all
5 gated-clock sampling primitives — X/Z-aware via `is_resolvable`, exact-count, no backdoor);
`smc_cg_dft_reset_bringup_test_seq.py` (all 3 checkers, SMCCGP0_003, tier-B); `smc_cg_zeroer_
activity_bringup_test_seq.py` (all 5 checkers, SMCCGP0_004, tier-A, including its positive
control at S1 — `free == 4` under `disable_cg` before the idle-gated claim); `smc_clk_running_
test_seq.py` body (SMCCGP0_001, tier-A, S1-S4, cross-checked against the grade appendix's cited
log lines). Result: no false-`PROVEN`, no vacuous checker (`if(x) assert` patterns absent — every
assertion sits directly after its own sample), no `[NO-BLIND-DELAY-SYNC]` (all completions are
`RisingEdge`/bounded-poll with real `TIMEOUT-MUST-FAIL`), no backdoor/force on DUT internals in
any sampled file (`test_en_i`/`rst_cold_ni` are real top-level DUT input ports per
`tb_top.sv:58,1062`; the JTAG-AXI `_write_bytes` path seeds a memory model behind the approved
external-master port with `update_golden=True`, consistent across SMCCGP0_001/004). Addresses
are imported by symbol from `smc_addr_map.py` (generated header) in every sampled file, per
`[ADDRESS-FROM-AUTHORITATIVE-MAP]`. **Independent evidence:** the pinned `DV_QUALITY_POLICY.md`
(pilot, v0.3) does not designate any checker in this IP as closure-critical/security requiring
`REPRODUCE-FROM-SEED`/`INDEPENDENT-OBSERVATION`; all `coverage[].proven_by[].independent_
evidence.required` are recorded `false` accordingly — a policy gap to note (the policy itself
states "if a needed rule or threshold is missing here, the audit reports `INSUFFICIENT-EVIDENCE`
for the affected judgment", but here no *closure* judgment turns on this classification, only a
best-practice recommendation, so it is not filed as a blocking finding). **Common-mode risk:**
the JTAG-AXI memory-seed pattern programs the model directly rather than deriving expected
zero-fill from an independent transform, but every clock-gating checker's pass/fail condition is
an *observation of clock-toggle counts*, not a data-compare against that seeded memory — so the
seeded-memory common-mode risk does not reach any of this IP's checkers. **RTL common-mode
sample (read-only):** `hw/common/och_prim_generic/rtl/prim_clkgater.sv` (test-enable ORs into
the enable path, matching every `test_en_i` bypass card's `PROOF`) and `hw/common/och_prim/rtl/
prim_clk_gater_hysteresis.sv` (`run = ~rst_ni | kick_i | nz_hyst | ~enable_i`) read in full —
structure matches the feature_list's triad description for DMA; the `~rst_ni` term is the basis
for finding F2 above. **Derivation provenance:** copied verbatim from the feature_list
(`sealed_derivation: true`, `anchor_seal_mechanism: ordered-single-context`, `fresh_context_
route: fresh-subagent`, `feature_list_frozen_at: 2026-08-05T15:30:00+08:00`) — sealed, so no
widening of the reverse-diff scope was required on that basis alone (Step 5 was still run at
scenario/cell granularity regardless, per the assignment).

**Step 5 — reverse inventory diff.** Compared the anchor-blind candidate
(`SMC_CLOCK_GATING_P0_REVERSE_FEATURE_INVENTORY.md`, `pin_consulted: false`, sealed
`ordered-single-context` derivation, 3 features / 11 scenarios / 0 interactions / 6 SF
candidates) against the approved feature_list (3 features / 13 scenarios / 0 interactions) at
scenario/cell granularity (the reverse inventory splits `SMC-CG-ZEROER` into
`SMC-CG-ZEROER-AXI`/`SMC-CG-ZEROER-REG`, so key names do not align 1:1 — diffed by intent
instead):
- Every reverse `SMC-CG-DMA.*` / `SMC-CG-ZEROER-AXI.*` / `SMC-CG-ZEROER-REG.*` scenario maps
  onto an approved key or is subsumed by two approved keys read together (e.g. reverse's single
  "idle-to-activity smoke" = approved `.S2`+`.S3`/`.S3`+`.S4`/`.S5`+`.S6` pairs; reverse's bare
  "presence/toggling" scenarios are subsumed by the same pairs, since a clock proven to gate to
  exactly 0 and then ungate to exactly N/N is *ipso facto* proven present and capable of
  toggling); reverse's CSR-reachability scenarios map onto the approved cross-cutting
  `SMC-CG-ENABLE-CTRL` feature; reverse's `test_en_i`-reachability scenarios are strict subsets
  of the approved `LIVE`-class DMA.S1/ZEROER.S2 (approved requires the *behavioral* free-run
  proof, reverse only requires reachability — approved is the superset, not a gap).
  Zeroer-reg's `S3` (reachability of the Zeroer's general `DEST_ADDR`/`SIZE`/`CTRL_STATUS`
  register block, as a stated *precondition* rather than a clock-gating behavior in its own
  right) falls outside the pin boundary's named class ("CSR/frontdoor reachability of
  clock-gate *enable controls*", not the whole register file) and is in any case exercised as a
  necessary step inside SMCCGP0_004's proof of `.S6` — not a confirmed omission.
- No reverse scenario key was found that names an in-scope P0 behavior absent from the approved
  inventory. The approved feature_list additionally proves `SMC-CG-ZEROER.S1` (reset override)
  and the `.S4`/`.S7` gate-*disabled*-behavioral scenarios that the reverse candidate's own
  CSR-reachability framing does not reach — i.e. the approved set is a strict superset on every
  point of actual difference, never a subset.
- `sf_findings` cross-check: reverse SF-001↔approved SF-002, SF-002↔SF-003, SF-004↔SF-001 are
  the same three substantive findings (severity differs in two cases — reverse rates them
  Medium, the approved audit rates them High — a documented judgment difference, not a content
  gap). Reverse SF-003/SF-005/SF-006 are new candidates with no approved counterpart; filed as
  finding F1 above (advisory, not a scenario omission).
- **Disposition: `CLEAN`.** `separation_gate_satisfied: true` — `reverse_diff.actor`
  (`fresh-subagent-unattended`, `claude-sonnet-4.5`, run `...-reverse-inventory-
  20260805T090055Z-fresh`) differs from `reverse_diff.compared_generator` (`minshaoho`,
  `sonnet-5`, run `dv_vplan_gen-SMC_CLOCK_GATING_P0-P0-20260805T151500+0800-fresh`, the Skill 1
  feature-list generator this review diffs against) on both `run_id` and the recorded `model`
  tuple.

**Reviewer independence (§6.4 / hard precondition #1):** this review ran in a fresh, read-only
context carrying only the artifact paths and `SKILL.md`, with no prior authoring, Skill-1/1.5/2
session, or discussion of this IP. `reviewer.run_id`
(`dv_peer_audit-SMC_CLOCK_GATING_P0-P0-20260805T171100+0800-fresh`) is distinct from every
`prior_participants[].run_id` listed above (feature-list generator, 4 implementers, 4 Skill-2
auditors) — verified by direct string comparison, no overlap.

**Rendering:** `schema_check.py` → `valid`; `render_lint.py --yaml <this file> --kind
peer-audit` → `agree` (verified below, this session).


---

## OWNER DECISION — milestone Done

- **Decision**: Accept advisory `PASS-WITH-FINDINGS` as milestone **Done**.
- **Rationale**: 13/13 required keys closed; reverse `CLEAN`; 2 Minor findings are
  documentation debt routed to the spec owner and do not block any required key.
- **Signoff**: `minshaoho` @ `2026-08-05T17:25:00+08:00`
