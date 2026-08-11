---
schema: dv-quality/v1
artifact: testcase-grade
testcase: smc_clk_running_test
ip: SMC_CLOCK_GATING_P0
anchor: smc_clk_running_test
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
card_sha256: c9a8f2011802914da1e11a25c66a37abbfcfed17058830392c07cfd14228c33c
card_revision: 1
card_path: hw/sys/smc/dv/tb/SMC_CLOCK_GATING_P0_VPLAN_DETAIL.md
testcase_plan:
  path: hw/sys/smc/dv/tb/SMC_CLOCK_GATING_P0_TESTCASE_PLAN.md
  plan_revision: 1
  testcase_revision: 1
  testcase_record_sha256: 0d033ae30973d5d21f601d2782614dbdaad3d7fa560ff3cd922534e826ce3ca9
  parent_approved: true
evidence_class: frontdoor-func
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
- path: hw/sys/smc/dv/build/runs/20260805_082337__verilator__smc_clk_running_test/smc_clk_running_test/logs/smc_clk_running_test.log
  sha256: fe718c899e420aa43b23013ba5a2d37d1fd2c184d5c242062325cb38e0a785e7
test_author:
  human_id: minshaoho
  run_id: dv_test_impl-SMCCGP0_001-P0-20260805T151500+0800
  model:
    provider: unknown
    family: unknown
    version: unknown
auditor:
  human_id: minshaoho
  run_id: dv_test_audit-SMCCGP0_001-fresh-20260805T162700+0800
  model:
    provider: cursor
    family: claude
    version: sonnet-5
exceptions: []
checkers:
- id: CHK-CG-ENABLE-READBACK
  checks_steps: [S1]
  proves: [SMC-CG-ENABLE-CTRL]
  covers: [SMC-CG-ENABLE-CTRL.S1, SMC-CG-ENABLE-CTRL.S2]
  proof_class: CONNECTIVITY
  expect_source: 'hw/sys/smc/doc/clk_rst.adoc "Clock and Reset-Based Power Management Integration"'
  grade: PROVEN
  evidence:
  - token: 'CHK-CG-ENABLE-READBACK: DMA_CG_EN=1 ZEROER_CG_EN=1 readback_dma=1 readback_zeroer=1 match=1'
    log_sha256: fe718c899e420aa43b23013ba5a2d37d1fd2c184d5c242062325cb38e0a785e7
    line: 370
    seed: 1
    implementation_path: hw/sys/smc/dv/cocotb/seq_lib/smc_clk_running_test_seq.py:234
  lifecycle_results: null
  coverage_results:
  - key: SMC-CG-ENABLE-CTRL.S1
    method: DIRECTED
    required_cells: [dma-cg-enable-frontdoor-reachable]
    achieved_cells: [dma-cg-enable-frontdoor-reachable]
    random_knobs: []
    resolved_knobs: []
    min_seeds: 1
    actual_seeds: [1]
    required_artifact: null
    coverage_artifacts:
    - hw/sys/smc/dv/build/runs/20260805_082337__verilator__smc_clk_running_test/smc_clk_running_test/logs/smc_clk_running_test.log#fe718c899e420aa43b23013ba5a2d37d1fd2c184d5c242062325cb38e0a785e7
    satisfied: true
  - key: SMC-CG-ENABLE-CTRL.S2
    method: DIRECTED
    required_cells: [zeroer-disable-cg-frontdoor-reachable]
    achieved_cells: [zeroer-disable-cg-frontdoor-reachable]
    random_knobs: []
    resolved_knobs: []
    min_seeds: 1
    actual_seeds: [1]
    required_artifact: null
    coverage_artifacts:
    - hw/sys/smc/dv/build/runs/20260805_082337__verilator__smc_clk_running_test/smc_clk_running_test/logs/smc_clk_running_test.log#fe718c899e420aa43b23013ba5a2d37d1fd2c184d5c242062325cb38e0a785e7
    satisfied: true
  linked_issue: null
  finding_ids: []
  remediation: null
- id: CHK-IDLE-GATED-BASELINE
  checks_steps: [S2]
  proves: [SMC-CG-DMA, SMC-CG-ZEROER]
  covers: [SMC-CG-DMA.S2, SMC-CG-ZEROER.S3]
  proof_class: LIVE
  expect_source: 'hw/sys/smc/doc/dma.adoc "Clock Gating Configuration - Activity Detection"; hw/sys/smc/doc/zeroer.adoc "Clock Gating - AXI Clock"'
  grade: PROVEN
  evidence:
  - token: 'CHK-IDLE-GATED-BASELINE: dma_toggle_count=0 zeroer_axi_toggle_count=0 window=16'
    log_sha256: fe718c899e420aa43b23013ba5a2d37d1fd2c184d5c242062325cb38e0a785e7
    line: 375
    seed: 1
    implementation_path: hw/sys/smc/dv/cocotb/seq_lib/smc_clk_running_test_seq.py:271
  lifecycle_results: null
  coverage_results:
  - key: SMC-CG-DMA.S2
    method: DIRECTED
    required_cells: [idle-gated-post-reset]
    achieved_cells: [idle-gated-post-reset]
    random_knobs: []
    resolved_knobs: []
    min_seeds: 1
    actual_seeds: [1]
    required_artifact: null
    coverage_artifacts:
    - hw/sys/smc/dv/build/runs/20260805_082337__verilator__smc_clk_running_test/smc_clk_running_test/logs/smc_clk_running_test.log#fe718c899e420aa43b23013ba5a2d37d1fd2c184d5c242062325cb38e0a785e7
    satisfied: true
  - key: SMC-CG-ZEROER.S3
    method: DIRECTED
    required_cells: [axi-clk-idle-gated]
    achieved_cells: [axi-clk-idle-gated]
    random_knobs: []
    resolved_knobs: []
    min_seeds: 1
    actual_seeds: [1]
    required_artifact: null
    coverage_artifacts:
    - hw/sys/smc/dv/build/runs/20260805_082337__verilator__smc_clk_running_test/smc_clk_running_test/logs/smc_clk_running_test.log#fe718c899e420aa43b23013ba5a2d37d1fd2c184d5c242062325cb38e0a785e7
    satisfied: true
  linked_issue: null
  finding_ids: []
  remediation: null
- id: CHK-DMA-ACTIVITY-UNGATE
  checks_steps: [S3]
  proves: [SMC-CG-DMA]
  covers: [SMC-CG-DMA.S3]
  proof_class: LIVE
  expect_source: 'hw/sys/smc/doc/dma.adoc "Clock Gating Configuration - Activity Detection"'
  grade: PROVEN
  evidence:
  - token: 'CHK-DMA-ACTIVITY-UNGATE: toggles_every_cycle=1 dma_edges=16 window=16 zeroer_axi_edges=0'
    log_sha256: fe718c899e420aa43b23013ba5a2d37d1fd2c184d5c242062325cb38e0a785e7
    line: 483
    seed: 1
    implementation_path: hw/sys/smc/dv/cocotb/seq_lib/smc_clk_running_test_seq.py:315
  lifecycle_results: null
  coverage_results:
  - key: SMC-CG-DMA.S3
    method: DIRECTED
    required_cells: [activity-ungates-clock]
    achieved_cells: [activity-ungates-clock]
    random_knobs: []
    resolved_knobs: []
    min_seeds: 1
    actual_seeds: [1]
    required_artifact: null
    coverage_artifacts:
    - hw/sys/smc/dv/build/runs/20260805_082337__verilator__smc_clk_running_test/smc_clk_running_test/logs/smc_clk_running_test.log#fe718c899e420aa43b23013ba5a2d37d1fd2c184d5c242062325cb38e0a785e7
    satisfied: true
  linked_issue: null
  finding_ids: []
  remediation: null
- id: CHK-TIMEOUT-PATHS
  checks_steps: [S4]
  proves: []
  covers: []
  proof_class: INTEGRITY
  expect_source: approved card timeout contract
  grade: PROVEN
  evidence:
  - token: 'CHK-TIMEOUT-PATHS: bound_smc_cycles=2048 expired=0 done_after_smc=2 fail_on_expiry=1'
    log_sha256: fe718c899e420aa43b23013ba5a2d37d1fd2c184d5c242062325cb38e0a785e7
    line: 508
    seed: 1
    implementation_path: hw/sys/smc/dv/cocotb/seq_lib/smc_clk_running_test_seq.py:336
  lifecycle_results: null
  coverage_results: []
  linked_issue: null
  finding_ids: []
  remediation: null
- id: CHK-NONVAC
  checks_steps: [S1, S2, S3]
  proves: []
  covers: []
  proof_class: INTEGRITY
  expect_source: approved card ordering contract
  grade: PROVEN
  evidence:
  - token: 'CHK-NONVAC: cg-enable-readback < idle-gated-baseline < dma-activity-ungate < PASS'
    log_sha256: fe718c899e420aa43b23013ba5a2d37d1fd2c184d5c242062325cb38e0a785e7
    line: 509
    seed: 1
    implementation_path: hw/sys/smc/dv/cocotb/seq_lib/smc_clk_running_test_seq.py:352
  lifecycle_results: null
  coverage_results: []
  linked_issue: null
  finding_ids: []
  remediation: null
findings: []
waivers: []
recommendation: EVIDENCE-CLOSED-AWAITING-SIGNOFF
---

# Grade Report — smc_clk_running_test (SMC_CLOCK_GATING_P0 / SMCCGP0_001)

**VERDICT: 5/5 PROVEN — READY** (mode CHECKBOX, entry PASS)

| Mode | Entry gate | Checkers | Findings | Recommendation |
|---|---|---|---|---|
| `CHECKBOX` | ✅ PASS | 5/5 PROVEN | none | ✅ EVIDENCE-CLOSED-AWAITING-SIGNOFF |

> First **P0** Skill 2 audit of SMCCGP0_001 on this reallocated anchor (fresh context, no prior
> authoring/audit/discussion of this test or IP in this session). This is a distinct grade from
> the already-closed P1 grade at `grades/smc_clk_running_test_GRADE.md` (`SMC_CLOCK_GATING`
> IP, different card/plan pair, checkers `CHK-ACTIVE-RUNNING`/`CHK-NONVAC`) — **not
> overwritten**; this report grades the P0 card's own five checkers
> (`CHK-CG-ENABLE-READBACK`/`CHK-IDLE-GATED-BASELINE`/`CHK-DMA-ACTIVITY-UNGATE`/
> `CHK-TIMEOUT-PATHS`/`CHK-NONVAC`) against the `SMC_CLOCK_GATING_P0` card/plan pair on a fresh
> kept log. Entry PASS: cocotb `TESTS=1 PASS=1 FAIL=0 SKIP=0` (`result.json` structured
> `status: PASS`, positive-evidence parser, `return_code: 0`), the testcase's own final
> assertion gate executed (`smc_clk_running_test.py:35-36` `assert not missing` on all six
> `chk_seen` tokens, five P0 + one legacy-P1 token retained for the closed P1 grade), zero
> unexplained `ERROR`/`FATAL`/`Traceback` in the kept log. Card r1 hash `c9a8f201…` matches the
> parent P0 plan record r1 hash `0d033ae3…` (both recomputed via `manifest.py record-hash`),
> parent `status: approved`, `current: true`. **Force/deposit check: clean** — CSR frontdoor +
> JTAG-AXI memory seed (approved external-master frontdoor) + passive `tb_dma_*`/`tb_zeroer_*`
> observation only (owner hard constraint satisfied).

## Your to-do — 0 items (none)

| # | Rank | Item |
|---|---|---|
| — | — | none open |

**Then:** human signoff on this grade (stamped below) → Skill 2 audit of SMCCGP0_002
(`smc_static_cg_sanity_test`, P0 reallocation) → Skill 3 peer audit once all four P0 cards
close.

## All checkers

| Checker | Grade | Proof class | Covers | Findings |
|---|---|---|---|---|
| CHK-CG-ENABLE-READBACK | ✅ PROVEN | CONNECTIVITY | SMC-CG-ENABLE-CTRL.S1, SMC-CG-ENABLE-CTRL.S2 | — |
| CHK-IDLE-GATED-BASELINE | ✅ PROVEN | LIVE | SMC-CG-DMA.S2, SMC-CG-ZEROER.S3 | — |
| CHK-DMA-ACTIVITY-UNGATE | ✅ PROVEN | LIVE | SMC-CG-DMA.S3 | — |
| CHK-TIMEOUT-PATHS | ✅ PROVEN | INTEGRITY | — | — |
| CHK-NONVAC | ✅ PROVEN | INTEGRITY | — | — |

### Layer 1 structural rule set

| Rule | Result |
|---|---|
| F1 fabricated verdict / backdoor write | ✅ clean — CSR access is frontdoor AXI (`SmcCsrSeq`); DMA descriptor programming and start are frontdoor CSR writes/reads; JTAG-AXI `_write_bytes` seeds the DMA memory model behind the approved external-master port (`update_golden=True`); `tb_dma_*`/`tb_zeroer_*` observation ports are passive; **no `force`/`deposit`/`uvm_hdl_*` on DUT internals** |
| F2 can't-fail checker | ✅ clean — `(rb & DMA_CG_EN)/(rb & ZEROER_CG_EN)` exact readback match, `dma_idle==0`/`zaxi_idle==0` (idle), `dma_edges==ACTIVE_WINDOW`/`zaxi_edges==0` (activity), `tb_zeroer_busy==0`, DMA-done TIMEOUT, and `assert_fence_order` all raise `AssertionError` on real RTL deviation |
| E1 skip-to-pass | ✅ clean — missing TB ports `assert hasattr` fail before use |
| E2 empty phase | ✅ clean — S1–S4 each program/drive, observe, and assert |
| S1 silent fail | ✅ clean — every mismatch/timeout raises `AssertionError` with diagnostic state (`_wait_dma_done` TIMEOUT logs bound/last-done/busy/fe/be) |
| O1 checker disabled | ✅ clean |
| Phase-S obligations — L1 | ✅ clean — addresses via `smc_addr_map` (generated header); X/Z-aware sampling (`count_enabled_pair_at_smc_rise`, `sample_bit`); bounded `RisingEdge`-polled waits with real `TIMEOUT-MUST-FAIL` (`_wait_dma_busy`, `_wait_dma_done`); tokens emitted only after their asserts; enrolled in `testlists/clock.toml` (`smc_clk_running_test`, `clock` regression) |
| Phase-S obligations — L2 (needs the card) | ✅ clean — proof fence SETUP→ACTION→RESPONSE→EFFECT→NONVAC ordered per checker; coverage cells from feature_list satisfied, matching the plan's allocated scenarios exactly; no merged-evidence collision within this card's checker set; force-free per card guardrails |

## Evidence appendix

<details>
<summary>Kept log + build identity</summary>

- Log: `hw/sys/smc/dv/build/runs/20260805_082337__verilator__smc_clk_running_test/smc_clk_running_test/logs/smc_clk_running_test.log`
  sha256 `fe718c899e420aa43b23013ba5a2d37d1fd2c184d5c242062325cb38e0a785e7` (verified via
  `sha256sum`; matches invoker hint) — a **new** kept log distinct from the P1 grade's log
  `807b1266…`
- `result.json`: `status: PASS`, `return_code: 0`, seed 1, target `default`, simulator
  `verilator` `5.050 2026-07-01`, `target_build.fingerprint: 2c815fa08277`, `rebuild: false`,
  positive-evidence parser (`results_xml` + `log_summary`, both PASS)
- Card: SMCCGP0_001 r1 `c9a8f2011802914da1e11a25c66a37abbfcfed17058830392c07cfd14228c33c`
  (recomputed match via `manifest.py record-hash ... --array cards`, `current: true`,
  `status: approved`)
- Parent plan record: SMCCGP0_001 r1
  `0d033ae30973d5d21f601d2782614dbdaad3d7fa560ff3cd922534e826ce3ca9` · `plan_revision: 1` ·
  `status: approved` · `current: true` (recomputed match via `manifest.py record-hash
  ... --array testcases`)
- Cocotb summary L512/L517/L523: protocol VIP `passed=True`, `smc_clk_running_test.
  smc_clk_running_test passed`, `TESTS=1 PASS=1 FAIL=0 SKIP=0`; final assertion gate in
  `smc_clk_running_test.py:35-36` checks all six `chk_seen` tokens (five P0 checkers plus the
  legacy P1 `CHK-ACTIVE-RUNNING` retained for the already-closed P1 grade's compatibility, not
  itself graded here); no unexplained `ERROR`/`FATAL`/`Traceback`
- Enrolled: `hw/sys/smc/dv/testlists/clock.toml` (`name = "smc_clk_running_test"`, line 5-6;
  listed in the `clock` regression, line 87)
- Force/deposit audit (owner hard constraint): only frontdoor CSR writes (`CLOCK_GATE_CONTROL`,
  DMA descriptor registers) and JTAG-AXI `_write_bytes` (`update_golden=True`, approved
  external-master seed). No `force`/`deposit`/`uvm_hdl_*` on DUT internals.
- Address map: `smc_addr_map.py` (generated PeakRDL C headers); seq imports
  `_addr.CLOCK_GATE_CONTROL` / `DMA_CG_EN` / `ZEROER_CG_EN` / `CG_HYST_*` / all `DMA_CTRL_*` by
  symbol, no hand-copied literals.
- Observation ports `tb_dma_cg_en`/`tb_dma_gated_clk`/`tb_dma_busy`/`tb_zeroer_cg_en`/
  `tb_zeroer_gated_axi_clk`/`tb_zeroer_busy` confirmed present via `assert hasattr(dut, port)`
  (seq.py:205-213) before use.

</details>

<details>
<summary>Token / step cites (kept log `fe718c89…`)</summary>

| Checker | Log line | What the log shows | Impl |
|---|---|---|---|
| (setup) | 342 | `STEP S1: frontdoor-write CLOCK_GATE_CONTROL DMA_CG_EN=1 ZEROER_CG_EN=1; readback` | seq `:225-227` |
| CHK-CG-ENABLE-READBACK | 370 | `DMA_CG_EN=1 ZEROER_CG_EN=1 readback_dma=1 readback_zeroer=1 match=1` | seq `:234` |
| (fence) | 373 | `FENCE cg-enable-readback @ 5130ns` | seq `:240` |
| (setup) | 374 | `STEP S2: gating enabled, no DMA descriptor; sample dma + zeroer axi idle-gated` | seq `:243-245` |
| CHK-IDLE-GATED-BASELINE | 375 | `dma_toggle_count=0 zeroer_axi_toggle_count=0 window=16` | seq `:271` |
| (fence) | 376 | `FENCE idle-gated-baseline @ 5514ns` | seq `:278` |
| (setup) | 377 | `STEP S3: program/trigger one DMA transfer; sample dma ungate + zeroer idle` | seq `:281-283` |
| CHK-DMA-ACTIVITY-UNGATE | 483 | `toggles_every_cycle=1 dma_edges=16 window=16 zeroer_axi_edges=0` | seq `:315` |
| (fence) | 485 | `FENCE dma-activity-ungate @ 6894ns` | seq `:331` |
| (setup) | 486 | `STEP S4: bounded wait for DMA transfer completion` | seq `:334` |
| CHK-TIMEOUT-PATHS | 508 | `bound_smc_cycles=2048 expired=0 done_after_smc=2 fail_on_expiry=1` | seq `:336` |
| CHK-NONVAC | 509 | `cg-enable-readback < idle-gated-baseline < dma-activity-ungate < PASS` | seq `:352` |
| (fence) | 510 | `FENCE PASS @ 7140ns` | seq `:358` |

</details>

<details>
<summary>Layer 1 / Layer 2 notes</summary>

- Ordered fence (ns): `cg-enable-readback`(5130) < `idle-gated-baseline`(5514) <
  `dma-activity-ungate`(6894) < `PASS`(7140); `assert_fence_order` (`smc_cg_obs_utils.py:267-269`)
  gates the `CHK-NONVAC` emit — real, list-ordered, non-empty.
- `CHK-CG-ENABLE-READBACK` proof fence: SETUP frontdoor-write `CLOCK_GATE_CONTROL` with both
  enable bits set → ACTION readback → RESPONSE/EFFECT `assert (rb & DMA_CG_EN)==...` /
  `assert (rb & ZEROER_CG_EN)==...` in `_program_cg` (real, raises before the token is emitted)
  and top-level pin cross-check (`tb_dma_cg_en`/`tb_zeroer_cg_en` sampled ==1) → NONVAC fence
  term. Covers both `SMC-CG-ENABLE-CTRL` scenarios (DMA + Zeroer reachability) from one write —
  legitimate joint proof of the same CSR's two fields, not a merged-evidence collision (both
  cells are the direct readback of their own bit, independently asserted).
- `CHK-IDLE-GATED-BASELINE` proof fence: SETUP gating enabled, no DMA descriptor programmed →
  ACTION `wait_gated_off` settles both taps → RESPONSE/EFFECT `count_enabled_pair_at_smc_rise`
  returns exact `0/0` on `tb_dma_gated_clk` / `tb_zeroer_gated_axi_clk` over the idle window →
  NONVAC.
- `CHK-DMA-ACTIVITY-UNGATE` proof fence: SETUP program + start one DMA descriptor, wait for
  `tb_dma_busy`/frontend/backend busy → ACTION concurrent sample over `ACTIVE_WINDOW` →
  RESPONSE/EFFECT exact `dma_edges==16` (every SMC rise, not "at least one") while
  `zaxi_edges==0` (Zeroer stays idle-gated throughout) → NONVAC.
- `FAIL-ON` paths present and real: readback mismatch or X on either enable field; any idle
  toggle on either clock; missing DMA-active toggle or a toggle gap; Zeroer toggling during DMA
  activity; DMA-busy-not-observed TIMEOUT; DMA-completion TIMEOUT (2048 SMC cycles) with
  last-state diagnostics (`done`/`busy`/`fe`/`be`); fence order mismatch; missing `CHK-*` tokens.
- No merged-evidence collision: each of the five P0 checkers emits its own token; `CHK-NONVAC`
  and `CHK-TIMEOUT-PATHS` are ordering/timeout-only (`proves: []`) and substitute for no feature
  proof. The legacy `CHK-ACTIVE-RUNNING` token (line 484) reuses the same S3 measurement for the
  **closed, separately-graded** P1 card and is not part of this P0 grade's checker set.
- Coverage: feature_list `SMC-CG-ENABLE-CTRL.S1`/`.S2`, `SMC-CG-DMA.S2`/`.S3`,
  `SMC-CG-ZEROER.S3`, all `method: DIRECTED`, `coverage_artifact: null`; required cells
  `dma-cg-enable-frontdoor-reachable` / `zeroer-disable-cg-frontdoor-reachable` /
  `idle-gated-post-reset` / `activity-ungates-clock` / `axi-clk-idle-gated` all hit, matching
  `SMCCGP0_001`'s allocated scenarios exactly (`SMC-CG-DMA.S2`, `SMC-CG-DMA.S3`,
  `SMC-CG-ZEROER.S3`, `SMC-CG-ENABLE-CTRL.S1`, `SMC-CG-ENABLE-CTRL.S2`).
- SF-002/SF-003 (spec audit, unresolved CSR identity for the gating-enable register in the
  pinned docs) do not block this checker: the testcase plan's own disposition is that
  `SMCCGP0_001` closes `SMC-CG-ENABLE-CTRL.S1`/`.S2` "through the register the existing anchor's
  own frontdoor writes target" — a Skill 1 documentation gap, not a Skill 2 evidence gap.
- No fabricated verdict, no always-pass checker, no skip-to-pass, no empty phase, no silent
  fail, no disabled checker.

</details>

## Accepted waivers

| Finding | Rule | Where | Why | Approved by |
|---|---|---|---|---|
| — | — | — | none | — |

## Human signoff

- **signed_off_by:** minshaoho
- **signed_off_at:** 2026-08-05T16:35:00+08:00
- **decision:** Done — evidence accepted by owner signoff. 5/5 PROVEN, recommendation
  `EVIDENCE-CLOSED-AWAITING-SIGNOFF`. This P0 grade is independent of, and does not alter, the
  already-closed P1 grade at `grades/smc_clk_running_test_GRADE.md`.
- **note:** Fresh Skill 2 audit (auditor `cursor/claude/sonnet-5`, `run_id`
  `dv_test_audit-SMCCGP0_001-fresh-20260805T162700+0800`). Force/deposit check clean (frontdoor
  CSR + approved JTAG-AXI external-master seed only). No blocking findings.
