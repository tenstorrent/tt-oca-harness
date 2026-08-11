---
schema: dv-quality/v1
artifact: testcase-grade
testcase: smc_static_cg_sanity_test
ip: SMC_CLOCK_GATING_P0
anchor: smc_static_cg_sanity_test
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
card_sha256: 3e58481e3b0cf7321a51f26a98560768603af989a54bb69cf5e776f5b9e6d34b
card_revision: 1
card_path: hw/sys/smc/dv/tb/SMC_CLOCK_GATING_P0_VPLAN_DETAIL.md
testcase_plan:
  path: hw/sys/smc/dv/tb/SMC_CLOCK_GATING_P0_TESTCASE_PLAN.md
  plan_revision: 1
  testcase_revision: 1
  testcase_record_sha256: 1f5b76cb4385fb6652f42dce64b040c578e5722f373560b5a6143f493b19060c
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
- path: hw/sys/smc/dv/build/runs/20260805_082459__verilator__smc_static_cg_sanity_test/smc_static_cg_sanity_test/logs/smc_static_cg_sanity_test.log
  sha256: 5f14b0fdb8b0e8a51eeb17cb9eb5a4622dc17d8e9c9e8ed0c41beefd907f0403
test_author:
  human_id: minshaoho
  run_id: dv_test_impl-SMCCGP0_002-P0-20260805T151500+0800
  model:
    provider: unknown
    family: unknown
    version: unknown
auditor:
  human_id: minshaoho
  run_id: dv_test_audit-SMCCGP0_002-fresh-20260805T162700+0800
  model:
    provider: cursor
    family: claude
    version: sonnet-5
exceptions: []
checkers:
- id: CHK-DMA-GATE-DISABLED-FREE-RUN
  checks_steps: [S2]
  proves: [SMC-CG-DMA]
  covers: [SMC-CG-DMA.S4]
  proof_class: LIVE
  expect_source: 'hw/sys/smc/doc/dma.adoc "Clock Gating Configuration - Gating Control"'
  grade: PROVEN
  evidence:
  - token: 'CHK-DMA-GATE-DISABLED-FREE-RUN: toggles_every_cycle=1 dma_edges=16 window=16 dma_cg_en=0 activity=0'
    log_sha256: 5f14b0fdb8b0e8a51eeb17cb9eb5a4622dc17d8e9c9e8ed0c41beefd907f0403
    line: 371
    seed: 1
    implementation_path: hw/sys/smc/dv/cocotb/seq_lib/smc_static_cg_sanity_test_seq.py:286
  lifecycle_results: null
  coverage_results:
  - key: SMC-CG-DMA.S4
    method: DIRECTED
    required_cells: [gate-disabled-free-running]
    achieved_cells: [gate-disabled-free-running]
    random_knobs: []
    resolved_knobs: []
    min_seeds: 1
    actual_seeds: [1]
    required_artifact: null
    coverage_artifacts:
    - hw/sys/smc/dv/build/runs/20260805_082459__verilator__smc_static_cg_sanity_test/smc_static_cg_sanity_test/logs/smc_static_cg_sanity_test.log#5f14b0fdb8b0e8a51eeb17cb9eb5a4622dc17d8e9c9e8ed0c41beefd907f0403
    satisfied: true
  linked_issue: null
  finding_ids: []
  remediation: null
- id: CHK-ZEROER-GATE-DISABLED-FREE-RUN
  checks_steps: [S4]
  proves: [SMC-CG-ZEROER]
  covers: [SMC-CG-ZEROER.S7]
  proof_class: LIVE
  expect_source: 'hw/sys/smc/doc/zeroer.adoc "Clock Gating"'
  grade: PROVEN
  evidence:
  - token: 'CHK-ZEROER-GATE-DISABLED-FREE-RUN: toggles_every_cycle=1 zeroer_axi_edges=16 zeroer_reg_edges=16 window=16 zeroer_cg_en=0'
    log_sha256: 5f14b0fdb8b0e8a51eeb17cb9eb5a4622dc17d8e9c9e8ed0c41beefd907f0403
    line: 398
    seed: 1
    implementation_path: hw/sys/smc/dv/cocotb/seq_lib/smc_static_cg_sanity_test_seq.py:334
  lifecycle_results: null
  coverage_results:
  - key: SMC-CG-ZEROER.S7
    method: DIRECTED
    required_cells: [gate-disabled-free-running]
    achieved_cells: [gate-disabled-free-running]
    random_knobs: []
    resolved_knobs: []
    min_seeds: 1
    actual_seeds: [1]
    required_artifact: null
    coverage_artifacts:
    - hw/sys/smc/dv/build/runs/20260805_082459__verilator__smc_static_cg_sanity_test/smc_static_cg_sanity_test/logs/smc_static_cg_sanity_test.log#5f14b0fdb8b0e8a51eeb17cb9eb5a4622dc17d8e9c9e8ed0c41beefd907f0403
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
  - token: 'CHK-NONVAC: dma-gate-disabled-free-run < zeroer-gate-disabled-free-run < PASS'
    log_sha256: 5f14b0fdb8b0e8a51eeb17cb9eb5a4622dc17d8e9c9e8ed0c41beefd907f0403
    line: 692
    seed: 1
    implementation_path: hw/sys/smc/dv/cocotb/seq_lib/smc_static_cg_sanity_test_seq.py:392
  lifecycle_results: null
  coverage_results: []
  linked_issue: null
  finding_ids: []
  remediation: null
findings: []
waivers: []
recommendation: EVIDENCE-CLOSED-AWAITING-SIGNOFF
---

# Grade Report — smc_static_cg_sanity_test (SMC_CLOCK_GATING_P0 / SMCCGP0_002)

**VERDICT: 3/3 PROVEN — READY** (mode CHECKBOX, entry PASS)

| Mode | Entry gate | Checkers | Findings | Recommendation |
|---|---|---|---|---|
| `CHECKBOX` | ✅ PASS | 3/3 PROVEN | none | ✅ EVIDENCE-CLOSED-AWAITING-SIGNOFF |

> First **P0** Skill 2 audit of SMCCGP0_002 on this reallocated anchor (fresh context, no prior
> authoring/audit/discussion of this test or IP in this session). Distinct from the
> already-closed P1 grade at `grades/smc_static_cg_sanity_test_GRADE.md`
> (`SMC_CLOCK_GATING` IP, checkers `CHK-MODULE-GATING`/`CHK-ENABLE-THRESHOLD`/`CHK-NONVAC`) —
> **not overwritten**; this report grades the P0 card's own three checkers
> (`CHK-DMA-GATE-DISABLED-FREE-RUN`/`CHK-ZEROER-GATE-DISABLED-FREE-RUN`/`CHK-NONVAC`) against the
> `SMC_CLOCK_GATING_P0` card/plan pair on a fresh kept log. Entry PASS: cocotb
> `TESTS=1 PASS=1 FAIL=0 SKIP=0` (`result.json` structured `status: PASS`, positive-evidence
> parser, `return_code: 0`), the testcase's own final assertion gate executed
> (`smc_static_cg_sanity_test.py:35-36` `assert not missing` on all six `chk_seen` tokens, three
> P0 + three legacy-P1 tokens retained for the closed P1 grade), zero unexplained
> `ERROR`/`FATAL`/`Traceback` in the kept log. Card r1 hash `3e58481e…` matches the parent P0
> plan record r1 hash `1f5b76cb…` (both recomputed via `manifest.py record-hash`), parent
> `status: approved`, `current: true`. **Force/deposit check: clean** — CSR frontdoor + JTAG-AXI
> memory seed (approved external-master frontdoor) + passive `tb_dma_*`/`tb_zeroer_*`
> observation only (owner hard constraint satisfied).

## Your to-do — 0 items (none)

| # | Rank | Item |
|---|---|---|
| — | — | none open |

**Then:** human signoff on this grade (stamped below) → Skill 3 peer audit once all four P0
cards close (SMCCGP0_001/002/003/004 all `EVIDENCE-CLOSED-AWAITING-SIGNOFF` and signed off).

## All checkers

| Checker | Grade | Proof class | Covers | Findings |
|---|---|---|---|---|
| CHK-DMA-GATE-DISABLED-FREE-RUN | ✅ PROVEN | LIVE | SMC-CG-DMA.S4 | — |
| CHK-ZEROER-GATE-DISABLED-FREE-RUN | ✅ PROVEN | LIVE | SMC-CG-ZEROER.S7 | — |
| CHK-NONVAC | ✅ PROVEN | INTEGRITY | — | — |

### Layer 1 structural rule set

| Rule | Result |
|---|---|
| F1 fabricated verdict / backdoor write | ✅ clean — every CSR access is frontdoor AXI (`SmcCsrSeq`); JTAG-AXI `_write_bytes` seeds the DMA memory model behind the approved external-master port (`update_golden=True`); `tb_dma_*`/`tb_zeroer_*` observation ports are passive; **no `force`/`deposit`/`uvm_hdl_*` on DUT internals** |
| F2 can't-fail checker | ✅ clean — `dma_edges_s1==IDLE_OBSERVE` (DMA free-run), `dma_n==0`/`zaxi_n==IDLE_OBSERVE`/`zreg_n==IDLE_OBSERVE` (Zeroer free-run + concurrent DMA-gated cross-check), and `assert_fence_order` all raise `AssertionError` on real RTL deviation; each free-run assertion requires the *exact* window count (16/16), not merely "some" toggling, so a stuck-gated tap fails it |
| E1 skip-to-pass | ✅ clean — missing TB ports `assert hasattr` fail before use |
| E2 empty phase | ✅ clean — S1–S4 each program, observe, and assert |
| S1 silent fail | ✅ clean — every mismatch/timeout raises `AssertionError` with diagnostic state |
| O1 checker disabled | ✅ clean |
| Phase-S obligations — L1 | ✅ clean — addresses via `smc_addr_map` (generated header); X/Z-aware sampling (`count_enabled_at_smc_rise`, `count_enabled_triple_at_smc_rise`); tokens emitted only after their asserts; enrolled in `testlists/clock.toml` (`smc_static_cg_sanity_test`, `clock` regression) |
| Phase-S obligations — L2 (needs the card) | ✅ clean — proof fence SETUP→ACTION→RESPONSE→EFFECT→NONVAC ordered per checker; coverage cells from feature_list satisfied, matching the plan's allocated scenarios exactly; no merged-evidence collision within this card's checker set; force-free per card guardrails |

## Evidence appendix

<details>
<summary>Kept log + build identity</summary>

- Log: `hw/sys/smc/dv/build/runs/20260805_082459__verilator__smc_static_cg_sanity_test/smc_static_cg_sanity_test/logs/smc_static_cg_sanity_test.log`
  sha256 `5f14b0fdb8b0e8a51eeb17cb9eb5a4622dc17d8e9c9e8ed0c41beefd907f0403` (verified via
  `sha256sum`; matches invoker hint) — a **new** kept log distinct from the P1 grade's log
  `3d21022c…`
- `result.json`: `status: PASS`, `return_code: 0`, seed 1, target `default`, simulator
  `verilator` `5.050 2026-07-01`, `target_build.fingerprint: 2c815fa08277`, `rebuild: false`,
  positive-evidence parser (`results_xml` + `log_summary`, both PASS)
- Card: SMCCGP0_002 r1 `3e58481e3b0cf7321a51f26a98560768603af989a54bb69cf5e776f5b9e6d34b`
  (recomputed match via `manifest.py record-hash ... --array cards`, `current: true`,
  `status: approved`)
- Parent plan record: SMCCGP0_002 r1
  `1f5b76cb4385fb6652f42dce64b040c578e5722f373560b5a6143f493b19060c` · `plan_revision: 1` ·
  `status: approved` · `current: true` (recomputed match via `manifest.py record-hash
  ... --array testcases`)
- Cocotb summary L695/L700/L706: protocol VIP `passed=True`,
  `smc_static_cg_sanity_test.smc_static_cg_sanity_test passed`, `TESTS=1 PASS=1 FAIL=0 SKIP=0`;
  final assertion gate in `smc_static_cg_sanity_test.py:35-36` checks all six `chk_seen` tokens
  (the two P0 checkers plus `CHK-NONVAC`, and the legacy P1 `CHK-MODULE-GATING`/
  `CHK-ENABLE-THRESHOLD`/`CHK-TIMEOUT-PATHS` retained for the already-closed P1 grade's
  compatibility, not themselves graded here); no unexplained `ERROR`/`FATAL`/`Traceback`
- Enrolled: `hw/sys/smc/dv/testlists/clock.toml` (`name = "smc_static_cg_sanity_test"`, line
  29-30; listed in the `clock` regression, line 90)
- Force/deposit audit (owner hard constraint): only frontdoor CSR writes
  (`CLOCK_GATE_CONTROL`, DMA descriptor registers) and JTAG-AXI `_write_bytes`
  (`update_golden=True`, approved external-master seed). No `force`/`deposit`/`uvm_hdl_*` on
  DUT internals in test, seq, `_one_shot.py`, `smc_csr_seq_utils.py`, or `smc_cg_obs_utils.py`.
- Address map: `smc_addr_map.py` (generated PeakRDL C headers); seq imports
  `_addr.CLOCK_GATE_CONTROL` / `DMA_CG_EN` / `ZEROER_CG_EN` / `CG_HYST_*` / `DMA_CTRL_*` by
  symbol, no hand-copied literals.
- Observation ports `tb_dma_cg_en`/`tb_dma_gated_clk`/`tb_dma_gater_busy`/`tb_zeroer_cg_en`/
  `tb_zeroer_gated_axi_clk`/`tb_zeroer_gated_reg_clk`/`tb_zeroer_busy` confirmed present via
  `assert hasattr(dut, port)` (seq.py:253-263) before use.

</details>

<details>
<summary>Token / step cites (kept log `5f14b0fd…`)</summary>

| Checker | Log line | What the log shows | Impl |
|---|---|---|---|
| (setup) | 342 | `STEP S1: CLOCK_GATE_CONTROL DMA_CG_EN=0 ZEROER_CG_EN=1; no DMA activity` | seq `:272-276` |
| (setup) | 370 | `STEP S2: sample dma_gated_clk free-run with cg disabled` | seq `:279` |
| CHK-DMA-GATE-DISABLED-FREE-RUN | 371 | `toggles_every_cycle=1 dma_edges=16 window=16 dma_cg_en=0 activity=0` | seq `:286` |
| (fence) | 374 | `FENCE dma-gate-disabled-free-run @ 5298ns` | seq `:293` |
| (setup) | 375 | `STEP S3: CLOCK_GATE_CONTROL ZEROER_CG_EN=0 DMA_CG_EN=1; no Zeroer activity` | seq `:296-300` |
| (setup) | 397 | `STEP S4: sample zeroer axi_clk + reg_clk free-run with disable_cg / cg off` | seq `:311` |
| CHK-ZEROER-GATE-DISABLED-FREE-RUN | 398 | `toggles_every_cycle=1 zeroer_axi_edges=16 zeroer_reg_edges=16 window=16 zeroer_cg_en=0` | seq `:334` |
| (fence) | 399 | `FENCE zeroer-gate-disabled-free-run @ 5724ns` | seq `:341` |
| CHK-NONVAC | 692 | `dma-gate-disabled-free-run < zeroer-gate-disabled-free-run < PASS` | seq `:392` |
| (fence) | 693 | `FENCE PASS @ 10362ns` | seq `:398` |

</details>

<details>
<summary>Layer 1 / Layer 2 notes</summary>

- Ordered fence (relevant P0 terms, ns): `dma-gate-disabled-free-run`(5298) <
  `zeroer-gate-disabled-free-run`(5724) < ... < `PASS`(10362); `assert_fence_order`
  (`smc_cg_obs_utils.py:267-269`) checks the full 5-term list (P0's two terms plus three legacy
  P1 terms for the enable-threshold measurement) as one equality — the P0 terms are confirmed in
  the correct relative order as part of that real, list-ordered assertion.
- `CHK-DMA-GATE-DISABLED-FREE-RUN` proof fence: SETUP frontdoor-write `DMA_CG_EN=0` (readback
  cross-checked in `_program_cg`) → ACTION `IDLE_OBSERVE=16`-cycle sample with no DMA descriptor
  programmed → RESPONSE/EFFECT exact `dma_edges_s1==16` (every SMC rise, not "at least one") →
  NONVAC. This is a directly falsifiable positive claim (a stuck-gated tap would sample `0`, not
  `16`), so no separate positive-control checker is needed within this card.
- `CHK-ZEROER-GATE-DISABLED-FREE-RUN` proof fence: SETUP frontdoor-write `ZEROER_CG_EN=0` →
  ACTION concurrent triple-sample (`count_enabled_triple_at_smc_rise`) over the same window →
  RESPONSE/EFFECT exact `zaxi_n==16` and `zreg_n==16` on both Zeroer clocks, with the concurrent
  `dma_n==0` cross-check confirming DMA is independently still gated in the same window → NONVAC.
- `FAIL-ON` paths present and real: any gated interval on the DMA clock while `DMA_CG_EN=0`; any
  gated interval on either Zeroer clock while `ZEROER_CG_EN=0`; DMA unexpectedly free while
  `ZEROER_CG_EN=0` window is sampled; X/Z on any of the three clocks; fence order mismatch;
  missing `CHK-*` tokens at the test wrapper.
- No merged-evidence collision: `CHK-DMA-GATE-DISABLED-FREE-RUN`,
  `CHK-ZEROER-GATE-DISABLED-FREE-RUN`, and `CHK-NONVAC` each emit an independent token for a
  distinct feature/scenario (`SMC-CG-DMA.S4`, `SMC-CG-ZEROER.S7`); `CHK-NONVAC` is ordering-only
  (`proves: []`). The legacy `CHK-MODULE-GATING`/`CHK-ENABLE-THRESHOLD` tokens (lines 400, 690)
  belong to the **closed, separately-graded** P1 card and are not part of this P0 grade's
  checker set.
- Coverage: feature_list `SMC-CG-DMA.S4` and `SMC-CG-ZEROER.S7`, both `method: DIRECTED`,
  `coverage_artifact: null`; required cell `gate-disabled-free-running` (same cell name, two
  independent feature-scoped scenario records) hit for both DMA and Zeroer in this kept log,
  matching `SMCCGP0_002`'s allocated scenarios exactly.
- SF-002 disposition (spec audit): Enable Threshold == Hysteresis Control for P1 is out of the
  P0 pin boundary; the P0 checkers here only exercise the enable/disable (module-gating)
  boundary, consistent with the P0 card's `owns` scope — not a Skill 2 defect.
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
- **decision:** Done — evidence accepted by owner signoff. 3/3 PROVEN, recommendation
  `EVIDENCE-CLOSED-AWAITING-SIGNOFF`. This P0 grade is independent of, and does not alter, the
  already-closed P1 grade at `grades/smc_static_cg_sanity_test_GRADE.md`.
- **note:** Fresh Skill 2 audit (auditor `cursor/claude/sonnet-5`, `run_id`
  `dv_test_audit-SMCCGP0_002-fresh-20260805T162700+0800`). Force/deposit check clean (frontdoor
  CSR + approved JTAG-AXI external-master seed only). No blocking findings.
