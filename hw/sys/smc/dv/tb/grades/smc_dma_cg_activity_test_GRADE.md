---
schema: dv-quality/v1
artifact: testcase-grade
testcase: smc_dma_cg_activity_test
ip: SMC_CLOCK_GATING
anchor: smc_dma_cg_activity_test
mode: CHECKBOX
no_contract_reason: null
entry_status: PASS
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
card_sha256: b1f928140c5123ae1298877e726f91b309ba15c3b287fb236f723b3582d51653
card_revision: 2
card_path: hw/sys/smc/dv/tb/SMC_CLOCK_GATING_VPLAN_DETAIL.md
testcase_plan:
  path: hw/sys/smc/dv/tb/SMC_CLOCK_GATING_TESTCASE_PLAN.md
  plan_revision: 1
  testcase_revision: 1
  testcase_record_sha256: 392d53ae853d76a3fdfbc7f31a4099290100b25a06fbbd51f47fbd7a09a12469
  parent_approved: true
evidence_class: strict-e2e
closure_tier: A
quality_policy:
  path: /home/minshaoho/.claude/skills/dv_common/DV_QUALITY_POLICY.md
  revision: 51a3357d9c31a018d69451b055bc956c089af26e1051368e25ce396c84ac2a75
build_config: default
simulator: verilator
simulator_version: 5.050 2026-07-01
compile_target: default
model_fingerprint: 2c815fa08277
compile_inputs_sha256: null
seeds: [1]
logs:
- path: hw/sys/smc/dv/build/runs/20260805_032809__verilator__smc_dma_cg_activity_test/smc_dma_cg_activity_test/logs/smc_dma_cg_activity_test.log
  sha256: c448f12feaa5d2a7098e95531fd1ecfb5ca937adc2ba894f21ea97c06b0a1ab1
test_author:
  human_id: minshaoho
  run_id: dv_test_impl-SMC_DMA_CG_ACTIVITY_TEST-cfed1faa-1b63-498e-81d5-885bfc9fe47b
  model:
    provider: cursor
    family: grok
    version: '4.5'
auditor:
  human_id: minshaoho
  run_id: dv_test_audit-SMC_DMA_CG_ACTIVITY_TEST-8d57b4e6-2d89-4119-af45-91ca33dc3245
  model:
    provider: cursor
    family: grok
    version: '4.5'
exceptions: []
checkers:
- id: CHK-DMA-GATE-OFF
  checks_steps: [S1]
  proves: [DMA-CG-CTRL]
  covers: [DMA-CG-CTRL.S1]
  proof_class: LIVE
  expect_source: 'hw/sys/smc/doc/dma.adoc §Performance Optimization and Power Management, table "Clock Gating Configuration", rows "Clock Gating Implementation"/"Hysteresis Width" (rev e2aae39953bb8001c7c20e3afd3956e68c22440c)'
  grade: PROVEN
  evidence:
  - token: 'CHK-DMA-GATE-OFF: last_toggle_within_hyst=16 zero_toggles_idle=16 quiet_at=32'
    log_sha256: c448f12feaa5d2a7098e95531fd1ecfb5ca937adc2ba894f21ea97c06b0a1ab1
    line: 932
    seed: 1
    implementation_path: hw/sys/smc/dv/cocotb/seq_lib/smc_dma_cg_activity_test_seq.py:381
  lifecycle_results: null
  coverage_results:
  - key: DMA-CG-CTRL.S1
    method: DIRECTED
    required_cells: [dma_clock_gated_off_after_idle]
    achieved_cells: [dma_clock_gated_off_after_idle]
    random_knobs: []
    resolved_knobs: []
    min_seeds: 1
    actual_seeds: [1]
    required_artifact: null
    coverage_artifacts:
    - hw/sys/smc/dv/build/runs/20260805_032809__verilator__smc_dma_cg_activity_test/smc_dma_cg_activity_test/logs/smc_dma_cg_activity_test.log#c448f12feaa5d2a7098e95531fd1ecfb5ca937adc2ba894f21ea97c06b0a1ab1
    satisfied: true
  linked_issue: null
  finding_ids: []
  remediation: null
- id: CHK-DMA-WAKEUP-FRONTEND
  checks_steps: [S2]
  proves: [DMA-CG-CTRL]
  covers: [DMA-CG-CTRL.S2]
  proof_class: LIVE
  expect_source: 'hw/sys/smc/doc/dma.adoc §Performance Optimization and Power Management, table "Clock Gating Configuration", row "Activity Detection" (rev e2aae39953bb8001c7c20e3afd3956e68c22440c)'
  grade: PROVEN
  evidence:
  - token: 'CHK-DMA-WAKEUP-FRONTEND: resume_within_1cyc=1 resume_cyc=0 start_id=2'
    log_sha256: c448f12feaa5d2a7098e95531fd1ecfb5ca937adc2ba894f21ea97c06b0a1ab1
    line: 1046
    seed: 1
    implementation_path: hw/sys/smc/dv/cocotb/seq_lib/smc_dma_cg_activity_test_seq.py:430
  lifecycle_results: null
  coverage_results:
  - key: DMA-CG-CTRL.S2
    method: DIRECTED
    required_cells: [dma_clock_enabled_on_frontend_wakeup]
    achieved_cells: [dma_clock_enabled_on_frontend_wakeup]
    random_knobs: []
    resolved_knobs: []
    min_seeds: 1
    actual_seeds: [1]
    required_artifact: null
    coverage_artifacts:
    - hw/sys/smc/dv/build/runs/20260805_032809__verilator__smc_dma_cg_activity_test/smc_dma_cg_activity_test/logs/smc_dma_cg_activity_test.log#c448f12feaa5d2a7098e95531fd1ecfb5ca937adc2ba894f21ea97c06b0a1ab1
    satisfied: true
  linked_issue: null
  finding_ids: []
  remediation: null
- id: CHK-DMA-WAKEUP-BACKEND
  checks_steps: [S3]
  proves: [DMA-CG-CTRL]
  covers: [DMA-CG-CTRL.S3]
  proof_class: LIVE
  expect_source: 'hw/sys/smc/doc/dma.adoc §Performance Optimization and Power Management, table "Clock Gating Configuration", row "Activity Detection" (rev e2aae39953bb8001c7c20e3afd3956e68c22440c)'
  grade: PROVEN
  evidence:
  - token: 'CHK-DMA-WAKEUP-BACKEND: during a backend-only window (backend_busy=1 && frontend_busy=0), the shared DMA clock toggles every cycle for the entire observed window (edges=8 window=8 edges_before_be=4 be_at=4)'
    log_sha256: c448f12feaa5d2a7098e95531fd1ecfb5ca937adc2ba894f21ea97c06b0a1ab1
    line: 1174
    seed: 1
    implementation_path: hw/sys/smc/dv/cocotb/seq_lib/smc_dma_cg_activity_test_seq.py:455
  lifecycle_results: null
  coverage_results:
  - key: DMA-CG-CTRL.S3
    method: DIRECTED
    required_cells: [dma_clock_enabled_on_backend_busy]
    achieved_cells: [dma_clock_enabled_on_backend_busy]
    random_knobs: []
    resolved_knobs: []
    min_seeds: 1
    actual_seeds: [1]
    required_artifact: null
    coverage_artifacts:
    - hw/sys/smc/dv/build/runs/20260805_032809__verilator__smc_dma_cg_activity_test/smc_dma_cg_activity_test/logs/smc_dma_cg_activity_test.log#c448f12feaa5d2a7098e95531fd1ecfb5ca937adc2ba894f21ea97c06b0a1ab1
    satisfied: true
  linked_issue: null
  finding_ids: []
  remediation: null
- id: CHK-DMA-GATING-DISABLED
  checks_steps: [S4]
  proves: [DMA-CG-CTRL]
  covers: [DMA-CG-CTRL.S4]
  proof_class: LIVE
  expect_source: 'hw/sys/smc/doc/dma.adoc §Performance Optimization and Power Management, table "Clock Gating Configuration", row "Gating Control" (rev e2aae39953bb8001c7c20e3afd3956e68c22440c)'
  grade: PROVEN
  evidence:
  - token: 'CHK-DMA-GATING-DISABLED: toggles_every_cycle=1 edges=16 window=16'
    log_sha256: c448f12feaa5d2a7098e95531fd1ecfb5ca937adc2ba894f21ea97c06b0a1ab1
    line: 1212
    seed: 1
    implementation_path: hw/sys/smc/dv/cocotb/seq_lib/smc_dma_cg_activity_test_seq.py:476
  lifecycle_results: null
  coverage_results:
  - key: DMA-CG-CTRL.S4
    method: DIRECTED
    required_cells: [dma_cg_disabled_clock_always_on]
    achieved_cells: [dma_cg_disabled_clock_always_on]
    random_knobs: []
    resolved_knobs: []
    min_seeds: 1
    actual_seeds: [1]
    required_artifact: null
    coverage_artifacts:
    - hw/sys/smc/dv/build/runs/20260805_032809__verilator__smc_dma_cg_activity_test/smc_dma_cg_activity_test/logs/smc_dma_cg_activity_test.log#c448f12feaa5d2a7098e95531fd1ecfb5ca937adc2ba894f21ea97c06b0a1ab1
    satisfied: true
  linked_issue: null
  finding_ids: []
  remediation: null
- id: CHK-NONVAC
  checks_steps: [S1, S2, S3, S4]
  proves: []
  covers: []
  proof_class: INTEGRITY
  expect_source: approved card ordering contract
  grade: PROVEN
  evidence:
  - token: 'CHK-NONVAC: gate-off-observed < frontend-wakeup-observed < backend-only-keep-enabled-observed < gating-disabled-observed < PASS'
    log_sha256: c448f12feaa5d2a7098e95531fd1ecfb5ca937adc2ba894f21ea97c06b0a1ab1
    line: 1214
    seed: 1
    implementation_path: hw/sys/smc/dv/cocotb/seq_lib/smc_dma_cg_activity_test_seq.py:492
  lifecycle_results: null
  coverage_results: []
  linked_issue: null
  finding_ids: []
  remediation: null
findings: []
waivers: []
recommendation: EVIDENCE-CLOSED-AWAITING-SIGNOFF
---

# Grade Report — smc_dma_cg_activity_test (SMC_DMA_CG_ACTIVITY_TEST)

**VERDICT: 5/5 PROVEN — READY** (mode CHECKBOX, entry PASS)

| Mode | Entry gate | Checkers | Findings | Recommendation |
|---|---|---|---|---|
| `CHECKBOX` | ✅ PASS | 5/5 PROVEN | none | ✅ EVIDENCE-CLOSED-AWAITING-SIGNOFF |

> Fresh Skill 2 audit against **card revision 2** (`b1f92814…`) keep-enabled S3. Prior r1
> vacuous gated-off→resume FIND-001 is closed by contract amend + matching impl; not reused
> as authoritative for this round.

## DELTA (re-audit vs prior grade `4/5 NOT-READY` on card r1 / log `e3240af0…`)

| Prior id | Tag | Status this round | Notes |
|---|---|---|---|
| FIND-001 (r1 rework) | `[NO-ALWAYS-PASS-CHECKER]` | CLOSED by card r2 | Card S3 is now backend-only **keep-enabled** (not gated-off→resume). Impl measures every-cycle toggles for `edges=8 window=8` with `frontend_busy=0` / `backend_busy=1` after free-running wake (`edges_before_be=4`) — log L1174 |
| CHK-DMA-WAKEUP-BACKEND | INSUFFICIENT-EVIDENCE → PROVEN | UPGRADED | Proof fence matches r2 text; token + fence term `backend-only-keep-enabled-observed` |
| CHK-DMA-GATE-OFF / FRONTEND / GATING-DISABLED / NONVAC | stayed PROVEN | unchanged substance | New kept log `c448f12f…`; NONVAC fence terms updated to r2 names |

## Your to-do — 0 items (none)

| # | Rank | Item |
|---|---|---|
| — | — | none open |

**Then:** human signoff on this grade → Skill 3 peer audit when the remaining SMC_CLOCK_GATING anchors close, or continue Skill 2 on still-open anchors (`smc_cg_test_mode_bypass_test` after 1.5 rebuild).

## All checkers

| Checker | Grade | Proof class | Covers | Findings |
|---|---|---|---|---|
| CHK-DMA-GATE-OFF | ✅ PROVEN | LIVE | DMA-CG-CTRL.S1 | — |
| CHK-DMA-WAKEUP-FRONTEND | ✅ PROVEN | LIVE | DMA-CG-CTRL.S2 | — |
| CHK-DMA-WAKEUP-BACKEND | ✅ PROVEN | LIVE | DMA-CG-CTRL.S3 | — |
| CHK-DMA-GATING-DISABLED | ✅ PROVEN | LIVE | DMA-CG-CTRL.S4 | — |
| CHK-NONVAC | ✅ PROVEN | INTEGRITY | — | — |

### Layer 1 structural rule set

| Rule | Result |
|---|---|
| F1 fabricated verdict / backdoor write | ✅ clean |
| F2 can't-fail checker | ✅ clean |
| E1 skip-to-pass | ✅ clean |
| E2 empty phase | ✅ clean |
| S1 silent fail | ✅ clean |
| O1 checker disabled | ✅ clean |
| Phase-S obligations — L1 | ✅ clean |
| Phase-S obligations — L2 (needs the card) | ✅ clean |

## Evidence appendix

<details>
<summary>Kept log + build identity</summary>

- Log: `hw/sys/smc/dv/build/runs/20260805_032809__verilator__smc_dma_cg_activity_test/smc_dma_cg_activity_test/logs/smc_dma_cg_activity_test.log`
  sha256 `c448f12feaa5d2a7098e95531fd1ecfb5ca937adc2ba894f21ea97c06b0a1ab1` (verified match to owner hint)
- `result.json`: `status: PASS`, `return_code: 0`, seed 1, target `default`, simulator `verilator`,
  `target_build.fingerprint: 2c815fa08277`, positive-evidence parsers PASS
- Card: SMC_DMA_CG_ACTIVITY_TEST **revision 2** `current: true` `approved`
  `record_sha256 b1f928140c5123ae1298877e726f91b309ba15c3b287fb236f723b3582d51653`
  (recomputed match; superseded r1 `789b6359…` / `current: false` not used)
- Parent plan record: r1 `392d53ae853d76a3fdfbc7f31a4099290100b25a06fbbd51f47fbd7a09a12469` ·
  `plan_revision: 1` · `status: approved` (recomputed match; card `derived_from` agrees)
- Cocotb summary L1228: `TESTS=1 PASS=1 FAIL=0 SKIP=0`; final assertion gate in
  `smc_dma_cg_activity_test.py` requires all five `CHK-*` tokens in `seq.chk_seen`; no
  unexplained `ERROR`/`FATAL`/`Traceback` (only benign cocotb `DeprecationWarning`s)
- Enrolled: `hw/sys/smc/dv/testlists/clock.toml` → `smc_dma_cg_activity_test`
- Address map: `seq_lib/smc_addr_map.py` loads generated `smc_addr.h` / `dma_ctrl_addr.h` /
  field masks; seq imports those symbols
- Observation: `tb_dma_cg_en` / `tb_dma_gated_clk` / `tb_dma_busy` / `tb_dma_frontend_busy` /
  `tb_dma_backend_busy` are passive `assign`s in `tb_top.sv` (card r2 observation /
  owner-authorized LIVE); no force/deposit on the proof path

</details>

<details>
<summary>Token / step cites (kept log `c448f12f…`)</summary>

| Checker | Log line | What the log shows | Impl |
|---|---|---|---|
| CHK-DMA-GATE-OFF | 932 | `last_toggle_within_hyst=16 zero_toggles_idle=16 quiet_at=32` | seq `:381-385` |
| (fence) | 935 | `FENCE gate-off-observed @ 8766ns` | seq `:386` |
| CHK-DMA-WAKEUP-FRONTEND | 1046 | `resume_within_1cyc=1 resume_cyc=0 start_id=2` | seq `:430-434` |
| (fence) | 1047 | `FENCE frontend-wakeup-observed @ 10074ns` | seq `:435` |
| CHK-DMA-WAKEUP-BACKEND | 1174 | backend-only keep-enabled `edges=8 window=8 edges_before_be=4 be_at=4` | seq `:455-462` |
| (fence) | 1175 | `FENCE backend-only-keep-enabled-observed @ 11514ns` | seq `:463` |
| CHK-DMA-GATING-DISABLED | 1212 | `toggles_every_cycle=1 edges=16 window=16` | seq `:476-480` |
| (fence) | 1213 | `FENCE gating-disabled-observed @ 12216ns` | seq `:481` |
| CHK-NONVAC | 1214 | r2 fence order including `backend-only-keep-enabled-observed` | seq `:492-496` |
| (fence) | 1215 | `FENCE PASS @ 12216ns` | seq `:497` |

</details>

<details>
<summary>Layer 1 / Layer 2 notes</summary>

- Ordered fence (ns): gate-off(8766) < frontend-wakeup(10074) < backend-only-keep-enabled(11514)
  < gating-disabled(12216) < PASS(12216); asserted before CHK-NONVAC emit.
- S3 proof fence (card r2): SETUP free-running after activity wake (`edges_before_be>=4` /
  `free_running`) → ACTION backend-only (`be=1 && fe=0`) → EFFECT every-cycle gated rising for
  the full window (`edges==window`) → NONVAC fence term. Prior r1 gated-off→resume claim is
  explicitly out of contract.
- FAIL-ON paths: timeout waiting gate-off / backend-only; missing gated rise in window;
  `frontend_busy` assert during claimed backend-only; `backend_busy` drop; resume >1 cyc after
  frontend wakeup; insufficient edges while cg disabled; X/Z via `_sample_bit`.
- No merged-evidence collision: each LIVE checker has its own token; CHK-NONVAC is ordering only.
- Coverage: feature_list `DMA-CG-CTRL.S1–S4` are DIRECTED with `coverage_artifact: null`;
  required cells achieved via the directed kept-log tokens above.

</details>

## Accepted waivers

| Finding | Rule | Where | Why | Approved by |
|---|---|---|---|---|
| — | — | — | none | — |

## Human signoff

- **signed_off_by:** minshaoho
- **signed_off_at:** 2026-08-05T14:28:00+08:00
- **decision:** Done — evidence accepted by owner signoff.
- **decision:** (pending)
- **note:** Fresh Skill 2 audit (auditor `cursor/grok/4.5`,
  `run_id` `dv_test_audit-SMC_DMA_CG_ACTIVITY_TEST-8d57b4e6-2d89-4119-af45-91ca33dc3245`,
  distinct from authoring `dv_test_impl-SMC_DMA_CG_ACTIVITY_TEST-cfed1faa-1b63-498e-81d5-885bfc9fe47b`).
  Card r2 keep-enabled S3 graded independently; prior r1 4/5 NOT-READY grade not treated as
  authoritative. 5/5 PROVEN — recommendation EVIDENCE-CLOSED-AWAITING-SIGNOFF.
