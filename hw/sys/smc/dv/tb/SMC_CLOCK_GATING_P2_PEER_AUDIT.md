---
schema: dv-quality/v1
artifact: ip-peer-audit
ip: SMC_CLOCK_GATING_P2
milestone: P2
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
feature_list_sha256: 98edfcafc4474d142fa0a6ad9ef0f619826ceeedaf5eea953d0b7399bd56df9b
feature_list_revision: 1
testcase_plan_sha256: 8ec020019d780b5f0e6c25e870c49b7d2c06d0a2e6a0074dd1e0dd678869ddd8
testcase_plan_revision: 1
cards_sha256: 6a10cab30c73449a6968b1803148bf19d5de8f91f2dcfea40f2d4886f0afa69b
derivation_provenance:
  sealed_derivation: true
  anchor_seal_mechanism: fresh-subagent
  fresh_context_route: fresh-subagent
  feature_list_frozen_at: '2026-08-05T15:09:00+08:00'
evidence_policy_sha256: 51a3357d9c31a018d69451b055bc956c089af26e1051368e25ce396c84ac2a75
quality_policy_sha256: 51a3357d9c31a018d69451b055bc956c089af26e1051368e25ce396c84ac2a75
grade_report_sha256:
- 2dd12b71a218aed20e7490702b1fc43d34a311609ad2aa1a3e2570180cdfbdc4   # smc_dma_cg_activity_test_P2_GRADE.md (file sha256)
- cd81c3ee3629943554610f819432e6c4a76b4146c6bd6b58a7aaced67cb1d824   # smc_zeroer_axiclk_cg_test_P2_GRADE.md (file sha256)
- 7e97f9a1e60a3c4362e185a858619374bce270267e0f41095af69f8913faa4fa   # smc_zeroer_regclk_cg_test_P2_GRADE.md (file sha256)
reviewer:
  human_id: fresh-subagent-unattended
  run_id: dv_peer_audit-SMC_CLOCK_GATING_P2-9e41b7d2-20260805T182000+0800
  model: {provider: cursor, family: claude, version: sonnet-5}
prior_participants:
- role: feature-list-generator
  human_id: minshaoho
  run_id: dv_vplan_gen-SMC_CLOCK_GATING_P2-step1-2026-08-05T15:09:00+08:00
  model: {provider: cursor, family: claude, version: sonnet-5}
- role: spec-audit-generator
  human_id: minshaoho
  run_id: dv_vplan_gen-SMC_CLOCK_GATING_P2-step1-2026-08-05T15:09:00+08:00
  model: {provider: cursor, family: claude, version: sonnet-5}
- role: testcase-plan-generator
  human_id: minshaoho
  run_id: dv_vplan_gen-SMC_CLOCK_GATING_P2-step3-2026-08-05T15:40:00+08:00
  model: {provider: cursor, family: claude, version: sonnet-5}
- role: cards-generator
  human_id: minshaoho
  run_id: dv_vplan_gen-SMC_CLOCK_GATING_P2-amend-SMC_CG_P2_002-2026-08-05T17:25:00+08:00
  model: {provider: cursor, family: claude, version: sonnet-5}
- role: test-author
  human_id: minshaoho
  run_id: dv_test_impl-SMC_CG_P2_001-coverage-fix-2026-08-05T09:20:45Z
  model: {provider: cursor, family: claude, version: sonnet-5}
- role: test-author
  human_id: minshaoho
  run_id: 'unknown (Skill 1.5 implementation of the P2 back-to-back race extension; no run_id recorded in-repo for this revision)'
  model: {provider: unknown, family: unknown, version: unknown}
- role: test-author
  human_id: minshaoho
  run_id: dv_test_impl-SMC_CG_P2_003-2026-08-05T09:17:48Z
  model: {provider: cursor, family: claude, version: sonnet-5}
- role: skill2-auditor
  human_id: minshaoho
  run_id: dv_test_audit-SMC_CG_P2_001-fresh-8f2d16c3-2026-08-05T17:21:00+08:00
  model: {provider: cursor, family: claude, version: sonnet-5}
- role: skill2-auditor
  human_id: minshaoho
  run_id: dv_test_audit-SMC_CG_P2_002-47744281-1e84-4dbb-bda6-dddc90c31d9c
  model: {provider: cursor, family: claude, version: sonnet-5}
- role: skill2-auditor
  human_id: minshaoho
  run_id: dv_test_audit-SMC_CG_P2_003-fresh-3a7c92e1-2026-08-05T17:21:00+08:00
  model: {provider: cursor, family: claude, version: sonnet-5}
denominator:
  inventory_keys: 4
  excluded_keys: 0
  milestone_required_keys: 4
  covered_keys: 4
coverage:
- key: SMC-CG-DMA-HYST.S1
  required_proof_class: LIVE
  status: COVERED
  allocated_to: SMC_DMA_CG_ACTIVITY_TEST
  closed_by_allocated: true
  proven_by:
  - checker_ref: smc_dma_cg_activity_test/CHK-DMA-HYST-SWEEP/2dd12b71a218aed20e7490702b1fc43d34a311609ad2aa1a3e2570180cdfbdc4
    independent_evidence:
      required: true          # closure_tier A
      method: NONE-AVAILABLE
      source_run_id: dv_test_audit-SMC_CG_P2_001-fresh-8f2d16c3-2026-08-05T17:21:00+08:00
      source_log_sha256: 3bc69b7a595712d77ce226742cb67103bd5f0b6a34e34c68e8cc551bd3134919
      run_id: null
      build_fingerprint: null
      log_or_artifact_sha256: null
      observer:
        human_id: null
        model: {provider: null, family: null, version: null}
      gate_satisfied: false
  required_cells: [hyst-gap=0, hyst-gap=1, hyst-gap=32-mid, hyst-gap=63-max, hyst-gap=64-just-over-max]
  achieved_cells: [hyst-gap=0, hyst-gap=1, hyst-gap=32-mid, hyst-gap=63-max, hyst-gap=64-just-over-max]
- key: SMC-CG-DMA-HYST.S2
  required_proof_class: LIVE
  status: COVERED
  allocated_to: SMC_DMA_CG_ACTIVITY_TEST
  closed_by_allocated: true
  proven_by:
  - checker_ref: smc_dma_cg_activity_test/CHK-DMA-HYST-RACE/2dd12b71a218aed20e7490702b1fc43d34a311609ad2aa1a3e2570180cdfbdc4
    independent_evidence:
      required: true          # closure_tier A
      method: NONE-AVAILABLE
      source_run_id: dv_test_audit-SMC_CG_P2_001-fresh-8f2d16c3-2026-08-05T17:21:00+08:00
      source_log_sha256: 3bc69b7a595712d77ce226742cb67103bd5f0b6a34e34c68e8cc551bd3134919
      run_id: null
      build_fingerprint: null
      log_or_artifact_sha256: null
      observer:
        human_id: null
        model: {provider: null, family: null, version: null}
      gate_satisfied: false
  required_cells: [activity-reassert-early-in-countdown, activity-reassert-at-last-cycle-of-countdown, activity-clear-immediately-after-reassert, back-to-back-reassert-reassert]
  achieved_cells: [activity-reassert-early-in-countdown, activity-reassert-at-last-cycle-of-countdown, activity-clear-immediately-after-reassert, back-to-back-reassert-reassert]
- key: SMC-CG-ZEROER-AXICLK.S1
  required_proof_class: LIVE
  status: COVERED
  allocated_to: SMC_ZEROER_AXICLK_CG_TEST
  closed_by_allocated: true
  proven_by:
  - checker_ref: smc_zeroer_axiclk_cg_test/CHK-ZEROER-AXICLK-NOGLITCH/cd81c3ee3629943554610f819432e6c4a76b4146c6bd6b58a7aaced67cb1d824
    independent_evidence:
      required: true          # closure_tier A
      method: NONE-AVAILABLE
      source_run_id: dv_test_audit-SMC_CG_P2_002-47744281-1e84-4dbb-bda6-dddc90c31d9c
      source_log_sha256: 5d8c44ab9eeb46dd701ddf35452be8158a81e178a278eaf841a541ea6497e377
      run_id: null
      build_fingerprint: null
      log_or_artifact_sha256: null
      observer:
        human_id: null
        model: {provider: null, family: null, version: null}
      gate_satisfied: false
  - checker_ref: smc_zeroer_axiclk_cg_test/CHK-ZEROER-AXICLK-COMPLETION/cd81c3ee3629943554610f819432e6c4a76b4146c6bd6b58a7aaced67cb1d824
    independent_evidence:
      required: true          # closure_tier A
      method: NONE-AVAILABLE
      source_run_id: dv_test_audit-SMC_CG_P2_002-47744281-1e84-4dbb-bda6-dddc90c31d9c
      source_log_sha256: 5d8c44ab9eeb46dd701ddf35452be8158a81e178a278eaf841a541ea6497e377
      run_id: null
      build_fingerprint: null
      log_or_artifact_sha256: null
      observer:
        human_id: null
        model: {provider: null, family: null, version: null}
      gate_satisfied: false
  required_cells: [new-trigger-1-cycle-before-busy-deassert, new-trigger-same-cycle-as-busy-deassert, new-trigger-1-cycle-after-busy-deassert]
  achieved_cells: [new-trigger-1-cycle-before-busy-deassert, new-trigger-same-cycle-as-busy-deassert, new-trigger-1-cycle-after-busy-deassert]
- key: SMC-CG-ZEROER-REGCLK.S1
  required_proof_class: LIVE
  status: COVERED
  allocated_to: SMC_ZEROER_REGCLK_CG_TEST
  closed_by_allocated: true
  proven_by:
  - checker_ref: smc_zeroer_regclk_cg_test/CHK-ZEROER-REGCLK-UNGATE/7e97f9a1e60a3c4362e185a858619374bce270267e0f41095af69f8913faa4fa
    independent_evidence:
      required: true          # closure_tier A
      method: NONE-AVAILABLE
      source_run_id: dv_test_audit-SMC_CG_P2_003-fresh-3a7c92e1-2026-08-05T17:21:00+08:00
      source_log_sha256: f6d7df5fd00b9f40a4e5cc728f7ed4afbb2a364d6b4718c25ea58513c539d111
      run_id: null
      build_fingerprint: null
      log_or_artifact_sha256: null
      observer:
        human_id: null
        model: {provider: null, family: null, version: null}
      gate_satisfied: false
  - checker_ref: smc_zeroer_regclk_cg_test/CHK-ZEROER-REGCLK-ACCESS-COMPLETE/7e97f9a1e60a3c4362e185a858619374bce270267e0f41095af69f8913faa4fa
    independent_evidence:
      required: true          # closure_tier A
      method: NONE-AVAILABLE
      source_run_id: dv_test_audit-SMC_CG_P2_003-fresh-3a7c92e1-2026-08-05T17:21:00+08:00
      source_log_sha256: f6d7df5fd00b9f40a4e5cc728f7ed4afbb2a364d6b4718c25ea58513c539d111
      run_id: null
      build_fingerprint: null
      log_or_artifact_sha256: null
      observer:
        human_id: null
        model: {provider: null, family: null, version: null}
      gate_satisfied: false
  required_cells: [access-immediately-after-reg_clk-gates, access-long-after-reg_clk-gates, back-to-back-accesses-across-gate-boundary]
  achieved_cells: [access-immediately-after-reg_clk-gates, access-long-after-reg_clk-gates, back-to-back-accesses-across-gate-boundary]
residuals: []
findings:
- id: F1
  tag: '[BUILD-MODEL-IDENTITY]'
  severity: Blocking
  affected_keys: [SMC-CG-DMA-HYST.S1, SMC-CG-DMA-HYST.S2, SMC-CG-ZEROER-AXICLK.S1, SMC-CG-ZEROER-REGCLK.S1]
  artifact_ref: hw/common/och_prim_generic/rtl/prim_clkgater.sv:20 (uncommitted working-tree change) and
    hw/sys/smc/dv/tb/tb_top.sv (uncommitted) vs every P2 grade report's repository_revision 2ecc7b227e3926b253c65b5aac21239eec24ba5f
  observed: 'Carried forward unresolved from the P1 gate (that review''s F1) and independently
    reconfirmed in this session: `git status --porcelain` at HEAD `2ecc7b227e39...` shows
    `prim_clkgater.sv` and `tb_top.sv` modified in the working tree, and all 6 P2-relevant cocotb
    sources (`smc_dma_cg_activity_test_seq.py`, `smc_zeroer_axiclk_cg_test_seq.py`,
    `smc_zeroer_regclk_cg_test_seq.py` and their 3 `tests/*.py` wrappers) are untracked. The diff
    itself reads `latched_en = i_en | i_te;` where the committed revision reads `latched_en = i_en;`
    -- the DFT test-enable bypass for the very `prim_clkgater` cell all three P2 anchors instantiate.
    All 3 P2 grade reports declare `repository_revision: 2ecc7b227e39...` (a commit that does not
    contain any of this) and `compile_inputs_sha256: null`; the axiclk grade additionally records
    `model_fingerprint: null` and its own evidence appendix states "No `result.json` present in this
    run directory". So no recorded hash in any of the 3 P2 grade reports pins the code that actually
    elaborated and ran, and a change to shared common RTL -- outside DV''s scope to approve -- remains
    uncommitted one milestone later.'
  owner: SMC design owner (shared common RTL) + DV owner
  closure_condition: The `prim_clkgater` change is reviewed and either committed or reverted by the
    design owner; `tb_top.sv` and the 6 P2 cocotb sources are committed; each of the 3 P2 grade
    reports re-records a `repository_revision` and a non-null `compile_inputs_sha256`/`model_fingerprint`
    that contain the reviewed state, and the 3 runs are repeated at that identity.
- id: F2
  tag: '[REPRESENTATIVE-EVIDENCE]'
  severity: Blocking
  affected_keys: [SMC-CG-DMA-HYST.S1, SMC-CG-DMA-HYST.S2, SMC-CG-ZEROER-AXICLK.S1, SMC-CG-ZEROER-REGCLK.S1]
  artifact_ref: 'hw/sys/smc/dv/tb/grades/smc_dma_cg_activity_test_P2_GRADE.md, smc_zeroer_axiclk_cg_test_P2_GRADE.md,
    smc_zeroer_regclk_cg_test_P2_GRADE.md (all declare seeds [1], one logs entry each)'
  observed: 'The same-log common-mode gate is unsatisfied for all 12 `closure_tier: A` checkers across
    the 3 P2 reports (policy §4 designates tier A "required for milestone closure", so
    `independent_evidence.required` is `true`). Objectively: every P2 grade report declares exactly
    one log and `seeds: [1]`; no `REPRODUCE-FROM-SEED` artifact (a distinct run id + distinct log hash
    + build fingerprint) and no `INDEPENDENT-OBSERVATION` artifact (observer provenance + hashed
    independent artifact) exists anywhere for any of the 3 anchors. `gate_satisfied` is therefore
    derived `false`, not asserted, for every one of the 12 checkers -- so per Step 4 of the skill
    ("Without it the checker is excluded from closure and the result is INSUFFICIENT-EVIDENCE") none
    of these checkers may certify closure on their own single-log evidence alone.'
  owner: DV owner
  closure_condition: Each of the 12 tier-A checkers gains either a reproduce-from-seed re-run of the
    reviewed build with a distinct run id, a distinct log hash and a non-null build fingerprint, or an
    independent observation artifact with policy-conformant observer provenance; `gate_satisfied` then
    derives true from the recorded fields.
- id: F3
  tag: '[EVIDENCE-TOKEN-CONDITIONAL]'
  severity: Major
  affected_keys: [SMC-CG-DMA-HYST.S2, SMC-CG-ZEROER-REGCLK.S1]
  artifact_ref: hw/sys/smc/dv/cocotb/seq_lib/smc_dma_cg_activity_test_seq.py:570-578,735;
    smc_zeroer_regclk_cg_test_seq.py:316-334
  observed: 'Two tier-A proof tokens carry fields that are not measurements. `CHK-DMA-HYST-RACE`
    prints `zero_glitches=1` as a hard-coded literal (seq.py:735) rather than a count derived from
    `_assert_no_glitch` (570-578), which does perform a real per-cycle scan and does raise
    `AssertionError` on a genuine glitch -- so the check itself is live, but the printed field can
    never read anything but `1`, live or not. `CHK-ZEROER-REGCLK-ACCESS-COMPLETE`''s three `match=`
    fields (seq.py:322-334) are computed as `int(written == readback)` from values already gated by
    an executed `assert rb == val` earlier in the same cell (seq.py:228,256,291) -- a token that only
    ever reaches this line already true, so the field is a restatement of a condition already
    asserted, not an independent report-out. Neither weakens the underlying pass/fail gate (both have
    a real, reachable `AssertionError` fail path upstream), but a milestone reviewer reading only the
    kept-log token cannot distinguish "measured and true" from "unconditionally prints true".'
  owner: DV owner
  closure_condition: '`zero_glitches` prints the measured glitch count from the scan (`0` when clean),
    and each `match` field is computed independently of the preceding assert (e.g. from a fresh
    re-read) rather than recomputing the identical already-asserted comparison.'
- id: F4
  tag: '[FEATURE-INVENTORY-COMPLETE]'
  severity: Major
  affected_keys: [SMC-CG-ZEROER-AXICLK.S1]
  artifact_ref: hw/sys/smc/dv/tb/SMC_CLOCK_GATING_P2_SPEC_FEATURE_LIST.md:117-119 (SMC-CG-ZEROER-AXICLK
    triad, producer description) vs :142-147 (S1 required_cells) vs hw/sys/smc/dv/cocotb/seq_lib/smc_zeroer_axiclk_cg_test_seq.py
  observed: 'The approved feature_list''s own triad text for `SMC-CG-ZEROER-AXICLK` states the producer
    is "`zeroer_busy_o`, asserted from trigger through the state machine''s ST_ISSUE_ADDR/ST_ISSUE_DATA
    phases **until all write responses are received**" (citing zeroer.adoc §State Machine and
    §Outstanding Transaction Management, which documents a 32-bit in-flight-write counter with
    flow-control back-pressure). None of `.S1`''s three approved `required_cells` (all keyed to
    *trigger timing* relative to the busy-to-idle edge) exercises whether `zeroer_busy_o` itself stays
    correctly asserted while a write **response** is still outstanding -- as distinct from the address/data
    issue phases the sequence''s `_p2_measure_busy_hold`/`_p2_trigger_op` calibrate against. An
    independent anchor-blind reverse-derivation of the pinned SPEC (delegated per Step 5, see appendix)
    independently surfaced the identical gap as its own `ZEROER-CG-AXI-RACE.S2` ("outstanding-response-pending
    race", INTEGRITY class). This is not scored as a missing required key -- the approved inventory
    correctly requires only `SMC-CG-ZEROER-AXICLK.S1`, and `CHK-ZEROER-AXICLK-NOGLITCH` genuinely
    proves the gating *transport* never glitches while `zeroer_busy_o` is high, whatever that signal''s
    own generation logic does -- but the approved feature''s own stated producer claim ("until all
    write responses are received") is not exercised by any required cell, and no `SF-*` finding in the
    approved spec audit asks or answers whether it needs to be.'
  owner: Skill 1 owner
  closure_condition: At the next feature_list revision, either add a required cell/scenario that
    exercises busy-vs-outstanding-response fidelity (e.g. a trigger racing a *delayed* write response
    rather than only the address/data-issue completion), or record an explicit finding narrowing the
    triad''s producer description to what is actually tested.
- id: F5
  tag: '[QUALITY-OBLIGATION-GAP]'
  severity: Major
  affected_keys: []
  artifact_ref: /home/minshaoho/.claude/skills/dv_common/DV_QUALITY_POLICY.md:2,6,356,362 (titles
    "pilot" / "SMU-scope SEP" / "Frontdoor / stimulus policy (SMU_SEP)" / "Authoritative PASS
    definition (pilot, SMU_SEP cocotb)")
  observed: 'Unchanged since the P1 gate flagged the identical gap (that review''s F15): the only
    quality_policy pinned for this IP (`SMC_CLOCK_GATING_P2_PIN.yaml:29-31`, content hash confirmed
    `51a3357d...` matching the reviewer''s local copy exactly) is still titled and scoped for
    `SMU_SEP`, not SMC, and still designates no required gating simulator/version for this milestone.
    Both this and the P1 gate ran on `verilator 5.050`, so no tool-mismatch has actually occurred, but
    that is coincidence, not a pinned requirement -- nothing in the policy would catch a future P2-class
    run on a different simulator.'
  owner: Policy owner + pin owner
  closure_condition: An SMC-scoped authoritative evidence policy (required tool/version, accepted
    build-model identity, completion/error semantics) is pinned in place of, or alongside, the
    SMU_SEP-titled one, as recommended at the P1 gate and still outstanding.
- id: F6
  tag: '[ARTIFACT-RENDER-STALE]'
  severity: Minor
  affected_keys: []
  artifact_ref: hw/sys/smc/dv/tb/SMC_CLOCK_GATING_P2_SPEC_REVIEW.md:253-307 (rendered body) vs
    :77,112,141,174,210,243 (front-matter `findings[].status`)
  observed: 'The rendered "Questions awaiting your answer" section lists all 6 findings (SF-001
    through SF-006) as `STATUS: open`, while the front matter -- the schema-normative record --
    marks SF-001 `waived` and SF-002/003/004/006 `answered`, each with a substantive `resolution`
    block from the same `approved_by`/`approved_at` stamp as the document''s own top-level
    `status: approved`. Mechanically confirmed non-blocking: `schema_check.py
    SMC_CLOCK_GATING_P2_VPLAN_DETAIL.md --spec-audit SMC_CLOCK_GATING_P2_SPEC_REVIEW.md --plan
    SMC_CLOCK_GATING_P2_TESTCASE_PLAN.md` returns `{"status": "valid", "problems": []}` -- no
    `BLOCKED-BY-FINDING`-class problem is raised, so no card is actually blocked by this stale
    render. Already independently caught and correctly triaged as documentation-hygiene (not a grading
    issue) by the `smc_zeroer_regclk_cg_test_P2_GRADE.md` auditor; recorded here as well because
    `render_lint.py`''s YAML-vs-body agreement check does not currently cover the `spec-audit`
    artifact kind, so nothing else in the pipeline catches it.'
  owner: Skill 1 owner (next SMC_CLOCK_GATING_P2_SPEC_REVIEW.md revision)
  closure_condition: The rendered body is regenerated from the front matter so `STATUS:` lines agree
    with `findings[].status`, or `render_lint.py` is extended to cover the `spec-audit` kind.
- id: F7
  tag: '[TRACEABILITY]'
  severity: Minor
  affected_keys: []
  artifact_ref: hw/sys/smc/dv/tb/SMC_CLOCK_GATING_P2_TESTCASE_REVIEW.md:57-58 vs
    hw/sys/smc/dv/tb/SMC_CLOCK_GATING_P2_TESTCASE_PLAN.md content_sha256
  observed: 'The testcase-review appendix cites the plan at "`content_sha256
    33a2949f9b2995cfb3c59b4c165586f70b5e796f017dee8721d35292caf1912f`", but the plan''s actual,
    schema-declared and independently recomputed `content_sha256` is `8ec020019d780b5f0e6c25e870c49b7d2c06d0a2e6a0074dd1e0dd678869ddd8`
    -- the two do not match. The plan itself is internally consistent (its own declared hash matches
    recomputation exactly, confirmed via `manifest.py hashes`), so this is a stale citation left in
    the human accept/reject packet''s appendix from an earlier plan draft, not a live plan-identity
    problem.'
  owner: Skill 1 owner
  closure_condition: The testcase-review appendix''s cited plan `content_sha256` is refreshed to match
    the plan actually reviewed/approved.
- id: F8
  tag: '[EVIDENCE-PROVENANCE-GAP]'
  severity: Minor
  affected_keys: []
  artifact_ref: this report''s own `reverse_diff.actor` block (Step 5 input)
  observed: 'The reverse inventory diff mandated by Step 5 was handed to this reviewer as a verbatim
    text block from a "separate fresh agent that had access ONLY to the 9 pinned SPEC docs", per the
    delegating instruction -- but no `run_id`, `human_id` beyond "a separate fresh agent", or model
    identity for that generating agent was supplied. This reviewer recorded `actor.human_id:
    fresh-subagent-unattended` and `actor.run_id: null` / `actor.model: unknown` rather than
    inventing plausible-sounding provenance, and derived `separation_gate_satisfied: true` only on the
    weaker basis that the delegating instruction itself asserts context separation from the feature-list
    generator (`minshaoho`), not on a verifiable distinct run id.'
  owner: DV owner (session orchestrator)
  closure_condition: Future Step 5 delegations record the generating agent''s `run_id` and model tuple
    alongside the reverse-diff text so `separation_gate_satisfied` can be mechanically derived rather
    than accepted on the delegator''s assertion.
inventory_delta:
  status: CLEAN
  keys: []
reverse_diff:
  spec_sha256: 0f0d0eae9bdb6ba4a2cba6267eae00d87a1b6422c999988f47da98fb301aeab0
  generated_inventory_sha256: 5560aef371c0a18782b1188eb6c28205a7c6ada0fc79217277fe421f51e30819
  run_id: null
  actor:
    human_id: fresh-subagent-unattended
    model: {provider: unknown, family: unknown, version: unknown}
  compared_generator:
    run_id: dv_vplan_gen-SMC_CLOCK_GATING_P2-step1-2026-08-05T15:09:00+08:00
    model: {provider: cursor, family: claude, version: sonnet-5}
  separation_gate_satisfied: true
  reviewed_by: fresh-subagent-unattended
  disposition: CLEAN
result: INSUFFICIENT-EVIDENCE
---

# IP Peer Audit — SMC_CLOCK_GATING_P2, P2 gate (MODE=CHECKBOX-MAPPING)

## Result: **INSUFFICIENT-EVIDENCE** — 4 of 4 required keys COVERED, 0 real gaps, but no closure
certificate is available

Required at P2: **4 of 4** inventory keys (0 excluded/deferred) · Covered: **4 of 4**
Features: 3 of 3 covered · Interactions: 0 of 0 (none required) · Real gaps: **0** · Blocked: 0 ·
Deferred: 0 · Waived: 0
Findings: **2 🔴 Blocking, 3 🟠 Major, 3 🟡 Minor** · Reverse-diff: **CLEAN** · Derivation: **sealed**
(`fresh-subagent`)
Why: every required scenario has a genuine, non-fabricated `LIVE` proof — all 12 tier-`A` checkers'
kept-log tokens were re-verified byte-for-byte against their declared log lines and their `seq.py`
implementation, and none is a false-`PROVEN`. But none of those 12 checkers carries the
`REPRODUCE-FROM-SEED`/`INDEPENDENT-OBSERVATION` evidence policy §4 requires for `closure_tier: A`
(single-seed, single-log, unchanged since the P1 gate's own F4), and the shared clock-gater RTL and
all 6 P2 cocotb sources remain uncommitted one milestone after the P1 gate first flagged it — so no
recorded hash in any of the 3 P2 grade reports pins the code that actually ran. Per the skill's own
verdict rules, a required checker without the evidence policy demands is `INSUFFICIENT-EVIDENCE`,
not `FAIL`, because no false-PROVEN and no real gap were found.

---

## Blocking items (must resolve before closure)

**1. SAME-LOG COMMON-MODE GATE — 12 `closure_tier: A` checkers, all 4 required keys · finding F2**
Policy §4 designates tier `A` as "required for milestone closure", so `independent_evidence.required`
is `true` for all 12 checkers across the 3 P2 grade reports. No qualifying evidence exists: every
report declares exactly one log and `seeds: [1]`; there is no `REPRODUCE-FROM-SEED` re-run (a distinct
run id + distinct log hash + build fingerprint) and no `INDEPENDENT-OBSERVATION` artifact anywhere for
any of the 3 anchors. `gate_satisfied` derives `false` for all 12.
Owner: **DV owner** · Closes when: each tier-A checker gains a reproduce-from-seed re-run with a
distinct run id, a distinct log hash and a non-null build fingerprint, or an independent observation
artifact with policy-conformant observer provenance.

**2. BUILD-MODEL IDENTITY — uncommitted RTL/TB, all P2 cocotb sources untracked · finding F1**
`hw/common/och_prim_generic/rtl/prim_clkgater.sv:20` still reads `latched_en = i_en | i_te;` in the
working tree (committed revision: `latched_en = i_en;`); `tb_top.sv` is still modified; all 6 P2
cocotb sources are still untracked — identical to the P1 gate's F1, unresolved one milestone later.
All 3 P2 grade reports cite `repository_revision: 2ecc7b227e39…` (a commit without any of this) with
`compile_inputs_sha256: null`, and the axiclk grade additionally has `model_fingerprint: null` and no
`result.json`. No recorded hash pins the code that actually ran.
Owner: **SMC design owner** (shared common RTL) **+ DV owner** · Closes when: the RTL change is
reviewed and committed or reverted, `tb_top.sv` and the 6 cocotb sources are committed, and the 3 P2
runs are repeated with a `repository_revision` and non-null `compile_inputs_sha256`/`model_fingerprint`
that contain the reviewed state.

---

## Coverage map

| Feature | Scenarios | Status |
|---|---|---|
| `SMC-CG-DMA-HYST` — DMA hysteresis breadth + reassertion race | 2/2 required | covered (`smc_dma_cg_activity_test`) — see F3 (token conditionality, non-blocking) |
| `SMC-CG-ZEROER-AXICLK` — Zeroer axi_clk back-to-back race | 1/1 required | covered (`smc_zeroer_axiclk_cg_test`) — see F4 (untested producer-triad dimension, non-blocking) |
| `SMC-CG-ZEROER-REGCLK` — Zeroer reg_clk pending-access race | 1/1 required | covered (`smc_zeroer_regclk_cg_test`) — see F3 (token conditionality, non-blocking) |

No interaction keys are required (`interactions: []` in the approved feature_list — `zeroer.adoc`
§Clock Domains states the register clock is "independent of AXI activity", and none of the 9 pinned
docs ties the DMA hysteresis gate to either Zeroer domain).

**No closure statement is emitted.** All 4 required keys are `COVERED` by a genuine `LIVE` checker and
0 keys are real gaps — but 12 of 12 crediting checkers are `closure_tier: A` and none satisfies the
independent-evidence gate policy §4 requires for that tier (F2), and the elaborated model those
checkers ran against is not reconstructible from a committed revision (F1). Feature-mapped coverage
and the policy's own evidence-quality bar are two different bars; this milestone clears the first and
not the second.

**Denominator arithmetic** (§4.2 step 0, reconstructible): `inventory_keys 4` − `excluded_keys 0` =
`milestone_required_keys 4`; `covered_keys 4`. There are no exclusions to name an authority for — the
pin's boundary is narrow enough (three named P1-deferred races) that the anchor-blind feature_list
derivation produced exactly 4 required keys with none unallocated (`unallocated: []` in the approved
plan, confirmed by `closure.py`: `holes: []`, `unsatisfied_coverage: []`, `unknown_keys: []`).

---

## Findings

### 🔴 Blocking

| # | Tag | What | Owner |
|---|---|---|---|
| F1 | `[BUILD-MODEL-IDENTITY]` | `prim_clkgater.sv`/`tb_top.sv` uncommitted, all 6 P2 cocotb sources untracked, `compile_inputs_sha256: null` in all 3 grades — unresolved carryover from the P1 gate | design + DV owner |
| F2 | `[REPRESENTATIVE-EVIDENCE]` | 12 tier-A checkers have single-seed single-log evidence only; no reproduce-from-seed or independent-observation artifact exists | DV owner |

### 🟠 Major

| # | Tag | What | Owner |
|---|---|---|---|
| F3 | `[EVIDENCE-TOKEN-CONDITIONAL]` | `CHK-DMA-HYST-RACE`'s `zero_glitches=1` is a hard-coded literal; `CHK-ZEROER-REGCLK-ACCESS-COMPLETE`'s `match=1` fields restate an already-asserted comparison | DV owner |
| F4 | `[FEATURE-INVENTORY-COMPLETE]` | The approved feature's own triad claims `zeroer_busy_o` stays asserted "until all write responses are received"; no required cell of `SMC-CG-ZEROER-AXICLK.S1` exercises that specific dimension (independently confirmed by the Step 5 reverse-diff's `ZEROER-CG-AXI-RACE.S2`) | Skill 1 owner |
| F5 | `[QUALITY-OBLIGATION-GAP]` | The pinned quality policy is still titled/scoped for `SMU_SEP`, not SMC; no designated gating tool for this milestone — unresolved carryover from the P1 gate | policy + pin owner |

### 🟡 Minor

| # | Tag | What | Owner |
|---|---|---|---|
| F6 | `[ARTIFACT-RENDER-STALE]` | `SMC_CLOCK_GATING_P2_SPEC_REVIEW.md`'s rendered body shows all 6 findings `STATUS: open` while front matter (normative) marks 5 `answered`/`waived`; `schema_check.py` confirms no live blocker | Skill 1 owner |
| F7 | `[TRACEABILITY]` | `SMC_CLOCK_GATING_P2_TESTCASE_REVIEW.md` appendix cites a stale plan `content_sha256` that does not match the approved plan's actual (and internally-consistent) hash | Skill 1 owner |
| F8 | `[EVIDENCE-PROVENANCE-GAP]` | The Step 5 reverse-diff generating agent's `run_id`/model identity was not supplied to this reviewer; recorded as `null`/`unknown` rather than fabricated | DV owner (orchestrator) |

### Verified clean (recorded because "checked and clean" is the information)

- **Evidence integrity.** All 3 kept logs exist and their sha256 matches each grade's declaration
  exactly (`3bc69b7a…`, `5d8c44ab…`, `f6d7df5f…`, all recomputed via `manifest.py hash-file`). All
  **12/12** PROVEN checkers' tokens were re-verified byte-for-byte at their declared log line (0 wrong
  line, 0 absent, 0 mismatched content — e.g. `CHK-DMA-HYST-SWEEP` at line 1387, `CHK-ZEROER-AXICLK-COMPLETION`
  at line 690, `CHK-ZEROER-REGCLK-ACCESS-COMPLETE` at line 526, spot-checked directly against the raw log
  files). **No fabricated or misplaced evidence token was found.**
- **No cross-testcase conflict.** The 3 P2 anchors gate 3 disjoint target signals (`tb_dma_gated_clk`,
  `tb_zeroer_gated_axi_clk`, `tb_zeroer_gated_reg_clk`); no target carries two disagreeing claims.
  `[CROSS-TESTCASE-CONFLICT]`: clean.
- **Force-free.** All 3 grade reports' own Layer-1 audits (independently spot-checked against the
  cited line ranges) confirm zero `force`/`deposit`/`uvm_hdl_*`/`.value =` writes to any DUT-internal
  net on the P2 code paths; all stimulus is frontdoor CSR read/write via generated `smc_addr_map`
  symbols, all observation is pre-existing passive `tb_top.sv` taps. `[NO-BACKDOOR-WRITE]`: clean.
- **Proof classes.** Every required scenario is `LIVE` and every crediting checker (`CHK-DMA-HYST-SWEEP`,
  `CHK-DMA-HYST-RACE`, `CHK-ZEROER-AXICLK-NOGLITCH`, `CHK-ZEROER-AXICLK-COMPLETION`,
  `CHK-ZEROER-REGCLK-UNGATE`, `CHK-ZEROER-REGCLK-ACCESS-COMPLETE`) is `LIVE`; the 6 `CHK-NONVAC`/
  `CHK-TIMEOUT-PATHS` checkers are `INTEGRITY` with `proves: []`/`covers: []` and earn no scenario
  credit anywhere. `achieved_cells` equals `required_cells` for all 4 keys. `[PROOF-CLASS-HONESTY]`: clean.
- **Allocation intent.** `closure.py`'s `allocation_intent_diff` reports `unmet: []`, `accidental: []`,
  `fully_unmet_testcases: []` — every plan allocation is met by the testcase it was allocated to, no
  key is double-credited. `[ALLOCATION-INTENT-DIFF]`: clean.
- **Enrollment.** All 3 required anchors (`smc_dma_cg_activity_test`, `smc_zeroer_axiclk_cg_test`,
  `smc_zeroer_regclk_cg_test`) appear in `hw/sys/smc/dv/testlists/clock.toml`, which `all.toml`
  includes; none appears in `deferred.toml`. No `E3` orphan.
- **Card/grade matching.** Exactly one `current: true` card record per anchor (`SMC_CG_P2_002` has a
  superseded revision-1 record, `current: false`, correctly excluded); all 3 grade reports cite the
  correct current `record_sha256`, each recomputed and matched via `manifest.py record-hash`. No
  superseded approval was used as authoritative.
- **Spec blockers.** `SMC_CG_P2_002`/`SMC_CG_P2_003`'s plan-recorded `blockers: [SF-005]`/`[SF-004]`
  are both `status: answered` in the approved `SMC_CLOCK_GATING_P2_SPEC_REVIEW.md` front matter (the
  normative record), independently confirmed via `schema_check.py --spec-audit` → `{"status": "valid",
  "problems": []}` (no `BLOCKED-BY-FINDING`). Neither card is actually blocked.
- **Timeouts fail closed.** Every bounded wait sampled (`_p2_timed_access`, `_run_pulse`,
  `wait_gated_off`) raises `AssertionError` with last-state diagnostics on expiry; no `except: pass`,
  no `skip`, no `xfail` found in any of the 3 sequences.
- **Addresses.** All register accesses sampled resolve through generated `smc_addr_map.py` symbols
  (re-exporting PeakRDL-generated `smc_addr.h`/`smc_base_config.h`); no hand-copied address literal on
  any P2 proof path.
- **Exceptions.** `exceptions: []` in all 3 P2 grade reports; no backdoor requiring one.

---

## Residual ledger

No non-`COVERED` key exists in this milestone's required set — all 4 required keys are `COVERED` by a
genuine `LIVE` checker (`closure.py`: `holes: []`). The residual ledger is therefore empty by
construction; there is no `REAL-GAP`, `BLOCKED`, `MILESTONE-DEFERRED`, `WAIVED`, or `UNREACHABLE` row
to record. This is not the same as saying the milestone is closure-certified — see F1/F2 above and the
"No closure statement is emitted" note in the coverage map: the residual ledger tracks *scenario*
coverage holes, and there are none, but the *evidence-quality* bar the same skill imposes on
`closure_tier: A` checkers is a separate, unsatisfied condition.

**`smc_clk_multi_window_test` (pinned `anchor_mode: augment` anchor, unallocated in this plan) is not
a problem.** The approved feature_list's `interactions: []` is empty by an explicit, cited SPEC
reading (`zeroer.adoc` §Clock Domains: the register clock is "independent of AXI activity" — a
statement against a cross-domain requirement, not for one), and the approved plan states this
reasoning out loud rather than silently omitting the anchor ("Pinned anchor not allocated in this
plan" section, `SMC_CLOCK_GATING_P2_TESTCASE_PLAN.md:183-190`). Separately, `SF-001`'s waived
resolution explicitly names this anchor: "`smc_clk_multi_window_test` remains unallocated for this
withdrawn area" (the `axi_cg_snoop`/fabric-capacity area, which admits no feature at all from the
pinned SPEC). Both citations independently agree the anchor genuinely owns nothing at this pin's
boundary — this reviewer concurs.

---

## Questions routed to the designer

1. **`prim_clkgater` (carried from P1):** is `latched_en = i_en | i_te` the approved DFT bypass for
   shared common RTL? It has now run un-reviewed across two milestone gates.
2. **`axi_cg_snoop` (SF-001, waived for P2):** does an OutstandingTx-tracking mechanism exist at all?
   If so, a future re-pin with an authoritative SPEC section is needed before any feature can be
   derived for it.
3. **Zeroer outstanding-response drain (new, F4):** does `zeroer_busy_o` need to be proven to stay
   asserted specifically while a write *response* (not just the address/data issue phase) is
   outstanding, per the feature_list's own triad claim — and if so, should that become an explicit
   required cell at the next revision?

---

## Review limitations

- **Sampling.** Policy §7 floor is all tier-`A` PROVENs + 20% of the rest (min 5). This review
  re-verified **all 12/12** PROVEN checkers (token / declared line / log-file hash) and read the
  implementation of all 3 P2 sequences (`smc_dma_cg_activity_test_seq.py`,
  `smc_zeroer_axiclk_cg_test_seq.py`, `smc_zeroer_regclk_cg_test_seq.py`) for the checkers'
  derivation logic, well past the policy floor.
- **No simulation was run.** This review is read-only and advisory; F2 records the absence of
  independent reproduction rather than supplying it. No test, RTL, contract, or tracker was modified.
- **Sealed derivation.** The feature_list declares `sealed_derivation: true` /
  `anchor_seal_mechanism: fresh-subagent`, better than the P1 gate's `ordered-single-context`. The
  Step 5 reverse diff was still run per the skill's unconditional mandate; see appendix.
- **Policy gaps.** F5 records a judgment the pinned policy does not resolve (no SMC-scoped
  authoritative evidence policy, no designated gating tool) — fed back to the policy owner rather than
  decided here, as it was at the P1 gate.
- **Advisory only.** This report holds no signoff or tracker authority and makes no `Done` decision.
  `hw/sys/smc/dv/tb/audit_status_smc_clock_gating_p2.md` is intentionally not touched by this review —
  updating it is the orchestrator's/owner's call.

---
*Machinery appendix: full YAML coverage records, reverse-diff provenance, grade-report hashes and
sampled-evidence detail — for tooling and re-audit.*

## Machinery appendix

### Frozen input set (all hashes recomputed in this session)

| Artifact | Identity | Verified |
|---|---|---|
| Pin | `SMC_CLOCK_GATING_P2_PIN.yaml`, `pin_revision: 1`, file `fcf62b5c…` | `milestone: P2` equals the plan's and the spec-audit's — gate confirmed |
| Feature list | `artifact_revision 1`, `content_sha256 98edfcaf…` | declared == recomputed (`manifest.py hashes`), all 3 feature records match |
| Testcase plan | `plan_revision 1`, `content_sha256 8ec02001…`, `status: approved` | declared == recomputed; all 3 testcase records match; `derived_from` → feature_list rev 1 / `98edfcaf…` ✓ |
| Cards | `content_sha256 6a10cab3…` | declared == recomputed; 4 records (`SMC_CG_P2_002` has 1 superseded + 1 current), 3 anchors, 1 `current: true` each |
| Spec audit | `content_sha256 5feed47c…`, `status: approved` | 6 findings (SF-001…SF-006), front matter: 1 `waived` + 4 `answered` + 1 `answered`, **none open** despite the stale render (F6) |
| Grade reports | 3 files, file hashes in `grade_report_sha256`; all `mode: CHECKBOX`, all `EVIDENCE-CLOSED-AWAITING-SIGNOFF`, all human-signed | `schema_check.py` → `valid` for all 3 |
| Quality policy | `51a3357d9c31a018d69451b055bc956c089af26e1051368e25ce396c84ac2a75` | pinned path readable this session; content hash matches |
| Pinned SPEC | 9 `.adoc` sources; combined `spec_sha256 0f0d0eae…` | method: SHA-256 over canonical JSON of `[{path, file-sha256}]` sorted by path |

### Independence

Reviewer `fresh-subagent-unattended` / `dv_peer_audit-SMC_CLOCK_GATING_P2-9e41b7d2-20260805T182000+0800`
/ cursor·claude·sonnet-5, dispatched in a fresh read-only context per the delegating instruction, with
no authoring, generation, self-audit, or prior-discussion history for `SMC_CLOCK_GATING_P2` before this
review. The `run_id` does not collide with any `prior_participants` entry listed above, nor with any
`run_id`/`human_id`/`auditor` identity recorded in the P1 gate's own `SMC_CLOCK_GATING_PEER_AUDIT.md`
(`dv_peer_audit-SMC_CLOCK_GATING-P1-5aa9c629a618-fresh-opus5-rereview`,
`dv_peer_audit-SMC_CLOCK_GATING-P1-20260805T141900+0800-fresh-grok45-final`, reviewing human
`brucehsu`/`dv-peer-fresh-smc-cg-final`) — this review is for a distinct `ip:`/milestone
(`SMC_CLOCK_GATING_P2` / P2) in any case. Every P2 input artifact (feature_list, plan, cards,
spec-audit, all 3 grades) was generated/authored/audited by `minshaoho` on `cursor·claude·sonnet-5`;
this reviewer is a different human identity in a fresh context. Model separation is optional per
policy §6 and is recorded, not enforced — the underlying model family is the same
(`cursor·claude·sonnet-5`) as most prior participants.

### Reverse inventory diff (Step 5 — delegated, not re-derived here)

Source: a verbatim text block handed to this reviewer by the delegating instruction, attributed to "a
separate fresh agent that had access ONLY to the 9 pinned SPEC docs (no feature_list, no plan, no
cards, no anchors)". Recorded identity: `generated_inventory_sha256 5560aef3…` (SHA-256 of the exact
text block, since it was not delivered as a repo file). No `run_id` or model tuple for the generating
agent was supplied (see finding F8); `separation_gate_satisfied: true` is derived on the weaker basis
that the generating agent's `human_id` (`fresh-subagent-unattended`, per the delegating instruction's
own description) differs from the feature-list generator's (`minshaoho`), not from a verified distinct
`run_id`.

**Per-item disposition** (5 features / 3 SF-* gaps / 3 cross-feature notes derived by the reverse-diff
agent, diffed against the 4 approved required keys):

| Reverse-diff item | Proof class | Disposition | Authority |
|---|---|---|---|
| `DMA-CG-HYST-SWEEP.S1/S2/S3` | LIVE | **(clean match)** → `SMC-CG-DMA-HYST.S1` | Approved feature_list required_cells `hyst-gap={0,1,32-mid,63-max,64-just-over-max}` cover the full swept range including both named boundaries |
| `DMA-CG-HYST-SWEEP.S4` (cg_enable_i override) | CONNECTIVITY | (a) P1-closed | `SMC_CLOCK_GATING_SPEC_FEATURE_LIST.md` `DMA-CG-CTRL.S4`, PROVEN by `smc_dma_cg_activity_test/CHK-DMA-GATING-DISABLED` (P1 grade, `ip: SMC_CLOCK_GATING`) |
| `DMA-CG-HYST-SWEEP.S5` (test_en_i bypass) | CONNECTIVITY | (a) P1-closed | `CG-DFT-TEST-BYPASS.S1`, PROVEN by `smc_cg_test_mode_bypass_test/CHK-DFT-BYPASS-DMA` (P1 grade) |
| `DMA-CG-HYST-SWEEP.S6` (programmability→HW effect, DECODE) | DECODE | (c) SF-answered | `SF-002` — CG_HYSTERESIS_W confirmed a synthesis-time RTL parameter, not a runtime register; no CSR-level DECODE claim exists to test |
| `DMA-CG-HYST-RACE.S1/S2` | LIVE | **(clean match)** → `SMC-CG-DMA-HYST.S2` | Approved required_cells cover early reassertion, back-to-back reassertion, and clear-after-reassert |
| `DMA-CG-HYST-RACE.S3` (exact-edge race, reassert on the cycle countdown hits 0) | LIVE | (d) out of P2 boundary — P3 corner | Pin boundary: "OUT for P2: P3 pure corner/stress randomization beyond named races"; the reverse-diff agent's own note states the SPEC does not claim glitch-free behavior for this exact case |
| `ZEROER-CG-AXI-RACE.S1` (back-to-back trigger) | LIVE | **(clean match)** → `SMC-CG-ZEROER-AXICLK.S1` | Approved required_cells cover trigger 1-before/same-cycle/1-after busy deassert |
| `ZEROER-CG-AXI-RACE.S2` (outstanding-response-pending race) | INTEGRITY | (d) untested producer-triad dimension, not a missing key | See finding **F4** — INTEGRITY class earns no scenario credit under policy in any case, and the approved key's own transport proof (`CHK-ZEROER-AXICLK-NOGLITCH`) already covers the gating-transport side; raised as F4, not as an omission |
| `ZEROER-CG-REG-RACE.S1` (pending access not clipped) | INTEGRITY | **(clean match)** → `SMC-CG-ZEROER-REGCLK.S1` | Approved required_cells `access-immediately-after-reg_clk-gates` / `access-long-after-reg_clk-gates` are the two boundary-timing extremes of "not clipped mid-flight" |
| `ZEROER-CG-REG-RACE.S2` (back-to-back, zero idle gap) | LIVE | **(clean match)** → `SMC-CG-ZEROER-REGCLK.S1` | Approved required_cell `back-to-back-accesses-across-gate-boundary` |
| `ZEROER-CG-ISOLATION.S1` (contested same-cycle transition) | CONNECTIVITY | (a)-adjacent — general principle P1-closed, exact-cycle corner out of P2 boundary | `INT-ZEROER-CG-INDEP` (P1 grade `smc_zeroer_cg_indep_test/CHK-ZINDEP-DECOUPLE`) proves cross-domain independence generally; the same-cycle-toggle edge case is a P3-style corner per the pin's boundary exclusion |
| `ZEROER-CG-ISOLATION.S2` (override precedence) | CONNECTIVITY | (a) P1-closed | `ZEROER-AXICLK-CG.S3/S4` + `ZEROER-REGCLK-CG.S3/S4` (P1 grades), PROVEN by `CHK-ZAXI-DISABLE-CG`/`CHK-ZAXI-RESET-OVERRIDE`/`CHK-ZREG-DISABLE-CG`/`CHK-ZREG-RESET-OVERRIDE` |
| `DMA-FAB-OSTX-CAP.S1/S2/S3` (`axi_cg_snoop` grounding attempt) | LIVE/INTEGRITY/CONNECTIVITY | (c) SF-answered | `SF-001`, `status: waived` — "the producer (a snoop counter), transport (comparison against fabric capacity), and consumer (a gating decision) legs of this behavior are all absent from the pinned SPEC"; the reverse-diff agent's own §2 gaps 1-3 (`axi_cg_snoop` undefined, "ID-bucket sizing" undefined, Zeroer absent from the fabric traffic-manager table) independently confirm the same triad-fails finding |

**Disposition: `CLEAN`.** Every reverse-diff item either maps cleanly onto one of the 4 approved
required keys, is a P1-closed cell the pin's own boundary text authorizes excluding ("re-proving P1
nominal formula cells already CLOSED... except where a P2 race requires joint observation" — none of
the P1-closed items above is a P2 race requiring joint observation), is explicitly answered/waived by
a named `SF-*` finding in the approved spec audit, or is an untested dimension of an already-required
key raised as its own finding (F4) rather than forced into a false "already covered". No reverse-diff
item independently demands a new required key the approved feature_list omitted.

### Sampled-evidence detail

Re-verification covered 12/12 PROVEN checkers across 3 reports: kept-log existence and sha256 (3/3
exact — `3bc69b7a…`/`5d8c44ab…`/`f6d7df5f…`, recomputed via `manifest.py hash-file`),
token-at-declared-line (12/12 exact, spot-checked directly against raw log content at lines 1387/1439
(dma), 689/690 (axiclk), 525/526 (regclk) — 0 wrong-line, 0 absent, 0 mismatched), `implementation_path`
resolution (12/12, read against the 3 `seq_lib/*.py` sources), entry-PASS gates (3/3 `TESTS=1 PASS=1
FAIL=0 SKIP=0`), and error-record scans (0 `ERROR`/`FATAL`/`Traceback` reported by any of the 3 grade
reports' own Layer-1 audits, independently spot-checked). Build identity: `verilator 5.050 2026-07-01`
across all 3, `compile_target default`; `model_fingerprint 2c815fa08277` present for 2 of 3 (dma,
regclk) and `null` for the third (axiclk, whose own evidence appendix states no `result.json` exists
for that run directory); `compile_inputs_sha256: null` in all 3 (F1).

**No false-PROVEN was found in the evidence layer** — `_assert_no_glitch` (dma seq.py:570-578) and the
`assert rb == val` / `assert meas["delta"] <= P2_UNGATE_BOUND_SMC` pairs (regclk seq.py:228-229 etc.)
were read directly and do perform real, reachable comparisons before every token is emitted — so the
§4.5 full-re-verification escalation was not triggered. The two Major/Blocking findings that touch
evidence quality (F2, F3) are independence and token-hygiene defects on top of real checks, not
fabricated evidence; F1 is a build-identity defect, not a false-PROVEN.


---

## OWNER DECISION — milestone Done

- **Decision**: Accept Skill 3 result `INSUFFICIENT-EVIDENCE` as milestone **Done** after
  owner review of Blocking findings F1/F2.
- **F1 `[BUILD-MODEL-IDENTITY]`**: Owner-reviewed. The uncommitted `prim_clkgater.sv`
  (DFT `i_te` OR into enable) and `tb_top.sv` lifts are intentional DV/bring-up changes
  exercised by the signed P0/P1/P2 CG grades; identity residual tracked for a later commit
  hygiene pass, not reopened as a P2 scenario gap (4/4 required keys COVERED, reverse CLEAN).
- **F2 `[REPRESENTATIVE-EVIDENCE]`**: Owner-reviewed. Single-seed verilator evidence is
  accepted for this milestone's directed race/sweep cells; multi-seed representative
  evidence deferred as process debt, not a missing required key.
- **Rationale**: 4/4 required scenario keys COVERED; reverse disposition CLEAN; no
  REAL-GAP / false-PROVEN; blockers are process/identity hygiene, not unproven CG races.
- **Signoff**: `minshaoho` @ `2026-08-05T21:40:00+08:00`
