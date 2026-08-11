---
schema: dv-quality/v1
artifact: testcase-grade
testcase: smc_static_cg_sanity_test
ip: SMC_CLOCK_GATING
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
card_sha256: dd59e7b200aba458784d03f8e04dfcd55377243446a0b2a61397f8a9ec99afc5
card_revision: 1
card_path: hw/sys/smc/dv/tb/SMC_CLOCK_GATING_VPLAN_DETAIL.md
testcase_plan:
  path: hw/sys/smc/dv/tb/SMC_CLOCK_GATING_TESTCASE_PLAN.md
  plan_revision: 1
  testcase_revision: 1
  testcase_record_sha256: bd3ff0d4488f120d7b6b9e08981e7d9570a8aaa947582e08951b40df609f6ff8
  parent_approved: true
evidence_class: frontdoor-func
closure_tier: B
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
- path: hw/sys/smc/dv/build/runs/20260805_035854__verilator__smc_static_cg_sanity_test/smc_static_cg_sanity_test/logs/smc_static_cg_sanity_test.log
  sha256: 3d21022c1749bc3d0ae9252fad6f8b0059c53198d93050e0f4ba55a240c1d806
test_author:
  human_id: minshaoho
  run_id: dv_test_impl-SMC_STATIC_CG_SANITY_TEST-95afef5e-2325-4e52-878d-d6236ae7bfa7
  model:
    provider: cursor
    family: grok
    version: '4.5'
auditor:
  human_id: minshaoho
  run_id: dv_test_audit-SMC_STATIC_CG_SANITY_TEST-493b545b-2608-47f6-8c06-eb04fad4ad0e
  model:
    provider: cursor
    family: grok
    version: '4.5'
exceptions: []
checkers:
- id: CHK-MODULE-GATING
  checks_steps: [S1, S2]
  proves: [SMC-CG-ARCH-PARAMS]
  covers: [SMC-CG-ARCH-PARAMS.S4]
  proof_class: LIVE
  expect_source: 'hw/sys/smc/doc/clk_rst.adoc §Clock and Reset-Based Power Management Integration, row "Module Gating" (rev 2f40548ea787240680a1c45ab75b8729e9620778)'
  grade: PROVEN
  evidence:
  - token: 'CHK-MODULE-GATING: disabled_module=DMA continuous_idle_toggles=1 dma_edges_s1=16 independent=1 dma_gated_edges=0 zeroer_ungated_edges=16 window=16'
    log_sha256: 3d21022c1749bc3d0ae9252fad6f8b0059c53198d93050e0f4ba55a240c1d806
    line: 392
    seed: 1
    implementation_path: hw/sys/smc/dv/cocotb/seq_lib/smc_static_cg_sanity_test_seq.py:314
  lifecycle_results: null
  coverage_results:
  - key: SMC-CG-ARCH-PARAMS.S4
    method: DIRECTED
    required_cells: [module_gating_enabled, module_gating_disabled]
    achieved_cells: [module_gating_disabled, module_gating_enabled]
    random_knobs: []
    resolved_knobs: []
    min_seeds: 1
    actual_seeds: [1]
    required_artifact: null
    coverage_artifacts:
    - hw/sys/smc/dv/build/runs/20260805_035854__verilator__smc_static_cg_sanity_test/smc_static_cg_sanity_test/logs/smc_static_cg_sanity_test.log#3d21022c1749bc3d0ae9252fad6f8b0059c53198d93050e0f4ba55a240c1d806
    satisfied: true
  linked_issue: null
  finding_ids: []
  remediation: null
- id: CHK-ENABLE-THRESHOLD
  checks_steps: [S3, S4]
  proves: [SMC-CG-ARCH-PARAMS]
  covers: [SMC-CG-ARCH-PARAMS.S3]
  proof_class: LIVE
  expect_source: 'hw/sys/smc/doc/clk_rst.adoc §Clock and Reset-Based Power Management Integration, row "Enable Threshold" (rev 2f40548ea787240680a1c45ab75b8729e9620778)'
  grade: PROVEN
  evidence:
  - token: 'CHK-ENABLE-THRESHOLD: min/max within_1cyc min=8/8 max=63/63 cells=enable_threshold_delay_min,enable_threshold_delay_max'
    log_sha256: 3d21022c1749bc3d0ae9252fad6f8b0059c53198d93050e0f4ba55a240c1d806
    line: 684
    seed: 1
    implementation_path: hw/sys/smc/dv/cocotb/seq_lib/smc_static_cg_sanity_test_seq.py:333
  lifecycle_results: null
  coverage_results:
  - key: SMC-CG-ARCH-PARAMS.S3
    method: RANDOMIZED
    required_cells: [enable_threshold_delay_min, enable_threshold_delay_max]
    achieved_cells: [enable_threshold_delay_min, enable_threshold_delay_max]
    random_knobs: [programmed_enable_threshold]
    resolved_knobs: ['programmed_enable_threshold=8', 'programmed_enable_threshold=63']
    min_seeds: 1
    actual_seeds: [1]
    required_artifact: null
    coverage_artifacts:
    - hw/sys/smc/dv/build/runs/20260805_035854__verilator__smc_static_cg_sanity_test/smc_static_cg_sanity_test/logs/smc_static_cg_sanity_test.log#3d21022c1749bc3d0ae9252fad6f8b0059c53198d93050e0f4ba55a240c1d806
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
  - token: 'CHK-NONVAC: module-gating-observed < enable-threshold-min-measured < enable-threshold-max-measured < PASS'
    log_sha256: 3d21022c1749bc3d0ae9252fad6f8b0059c53198d93050e0f4ba55a240c1d806
    line: 686
    seed: 1
    implementation_path: hw/sys/smc/dv/cocotb/seq_lib/smc_static_cg_sanity_test_seq.py:354
  lifecycle_results: null
  coverage_results: []
  linked_issue: null
  finding_ids: []
  remediation: null
findings: []
waivers: []
recommendation: EVIDENCE-CLOSED-AWAITING-SIGNOFF
---

# Grade Report — smc_static_cg_sanity_test (SMC_STATIC_CG_SANITY_TEST)

**VERDICT: 3/3 PROVEN — READY** (mode CHECKBOX, entry PASS)

| Mode | Entry gate | Checkers | Findings | Recommendation |
|---|---|---|---|---|
| `CHECKBOX` | ✅ PASS | 3/3 PROVEN | none | ✅ EVIDENCE-CLOSED-AWAITING-SIGNOFF |

> Fresh Skill 2 re-audit on rework kept log `3d21022c…` (run `20260805_035854`). Prior grade on
> log `9a982374…` (**1/3 NOT-READY**) is **not** treated as authoritative. Entry PASS:
> cocotb `TESTS=1 PASS=1 FAIL=0 SKIP=0`, final `assert not missing` on all four `chk_seen`
> tokens (three card checkers + `CHK-TIMEOUT-PATHS`), zero unexplained `ERROR`/`FATAL`/
> `Traceback`. Card r1 hash `dd59e7b2…` matches parent plan record r1 hash `bd3ff0d4…` (both
> recomputed), parent `status: approved`. **Force/deposit check: clean** — CSR frontdoor +
> JTAG-AXI memory seed + passive `tb_*` observation only (owner hard constraint satisfied).

## DELTA (re-audit vs prior grade `1/3 NOT-READY` on log `9a982374…`)

| Prior id | Tag | Status this round | Notes |
|---|---|---|---|
| FIND-001 | `[ADDRESS-FROM-AUTHORITATIVE-MAP]` | CLOSED | Seq + `smc_cg_obs_utils` import `CLOCK_GATE_CONTROL` / `DMA_CG_EN` / `ZEROER_CG_EN` / `CG_HYST_*` / all `DMA_CTRL_*` / fabric filter addresses from `seq_lib/smc_addr_map.py` (generated `smc_addr.h` / `smc_base_config.h` / `dma_ctrl_addr.h`) |
| FIND-002 | `[EXACT-EXPECTATION]` | CLOSED | Disabled-module asserts tightened to `== IDLE_OBSERVE` via `count_enabled_at_smc_rise` / `count_enabled_pair_at_smc_rise`; this log shows `dma_edges_s1=16` and `zeroer_ungated_edges=16` (prior boundary miss `15/16` gone) |
| FIND-003 | `[EXACT-EXPECTATION]` | CLOSED | Token booleans derived from measured comparisons (`continuous` / `independent`), not hardcoded `1` |
| CHK-MODULE-GATING | INSUFFICIENT-EVIDENCE → PROVEN | UPGRADED | Addr map + exact every-cycle enable samples + independent opposite-enable window |
| CHK-ENABLE-THRESHOLD | INSUFFICIENT-EVIDENCE → PROVEN | UPGRADED | Addr map closed; measured delays `min=8/8 max=63/63` + both required cells intact |
| CHK-NONVAC | stayed PROVEN | unchanged substance | New kept log `3d21022c…` |

## Your to-do — 0 items (none)

| # | Rank | Item |
|---|---|---|
| — | — | none open |

**Then:** human signoff on this grade → Skill 3 peer audit when the remaining SMC_CLOCK_GATING anchors close, or continue Skill 2 on still-open anchors.

## All checkers

| Checker | Grade | Proof class | Covers | Findings |
|---|---|---|---|---|
| CHK-MODULE-GATING | ✅ PROVEN | LIVE | SMC-CG-ARCH-PARAMS.S4 | — |
| CHK-ENABLE-THRESHOLD | ✅ PROVEN | LIVE | SMC-CG-ARCH-PARAMS.S3 | — |
| CHK-NONVAC | ✅ PROVEN | INTEGRITY | — | — |

### Layer 1 structural rule set

| Rule | Result |
|---|---|
| F1 fabricated verdict / backdoor write | ✅ clean — every CSR/data access is frontdoor AXI (SEP_IN CSR, JTAG memory seed); TB observation ports (`tb_dma_gated_clk`, `tb_zeroer_gated_axi_clk`, etc.) are passive reads; **no force/deposit on DUT internals** |
| F2 can't-fail checker | ✅ clean — `dma_n == 0`, `dma_edges_s1 == IDLE_OBSERVE`, `z_n == IDLE_OBSERVE`, `abs(delay - hyst) <= 1`, fence-order assert, and X/Z via `is_resolvable` all raise |
| E1 skip-to-pass | ✅ clean — missing TB ports `assert hasattr` fail; no HDL-path skip-to-pass |
| E2 empty phase | ✅ clean — S1–S4 each program, observe, and assert |
| S1 silent fail | ✅ clean — every mismatch/timeout raises `AssertionError` with diagnostic state |
| O1 checker disabled | ✅ clean |
| Phase-S obligations — L1 | ✅ clean |
| Phase-S obligations — L2 (needs the card) | ✅ clean |

## Evidence appendix

<details>
<summary>Kept log + build identity</summary>

- Log: `hw/sys/smc/dv/build/runs/20260805_035854__verilator__smc_static_cg_sanity_test/smc_static_cg_sanity_test/logs/smc_static_cg_sanity_test.log`
  sha256 `3d21022c1749bc3d0ae9252fad6f8b0059c53198d93050e0f4ba55a240c1d806` (verified via
  `sha256sum`; matches owner hint)
- `result.json`: `status: PASS`, `return_code: 0`, seed 1, target `default`, simulator
  `verilator` `5.050 2026-07-01`, `target_build.fingerprint: 2c815fa08277`, rebuild=false,
  positive-evidence parser (`results_xml` + `log_summary`, both PASS)
- Card: SMC_STATIC_CG_SANITY_TEST r1
  `dd59e7b200aba458784d03f8e04dfcd55377243446a0b2a61397f8a9ec99afc5` (recomputed match against
  `SMC_CLOCK_GATING_VPLAN_DETAIL.md`)
- Parent plan record: r1
  `bd3ff0d4488f120d7b6b9e08981e7d9570a8aaa947582e08951b40df609f6ff8` · `plan_revision: 1` ·
  `status: approved` (recomputed match against `SMC_CLOCK_GATING_TESTCASE_PLAN.md`)
- Cocotb summary L700: `TESTS=1 PASS=1 FAIL=0 SKIP=0`; final assertion gate in
  `smc_static_cg_sanity_test.py` checks `CHK-MODULE-GATING` / `CHK-ENABLE-THRESHOLD` /
  `CHK-NONVAC` / `CHK-TIMEOUT-PATHS` tokens landed in `seq.chk_seen`; no unexplained
  `ERROR`/`FATAL`/`Traceback` (only benign cocotb/library `DeprecationWarning`s)
- Enrolled: `hw/sys/smc/dv/testlists/clock.toml` (`name = "smc_static_cg_sanity_test"`).
  Note: the same name remains listed under `deferred.toml` `deferred_tb_policy` (process debt);
  live enrollment in `clock.toml` is what this audit relies on for `[REGRESSION-ENROLLED]`
- Force/deposit audit (owner hard constraint): no `force`/`deposit`/`uvm_hdl_*` in
  `smc_static_cg_sanity_test.py`, `smc_static_cg_sanity_test_seq.py`, or `smc_cg_obs_utils.py`
- Address map: `seq_lib/smc_addr_map.py` + re-exports in `smc_cg_obs_utils.py`; seq imports
  `_addr.CLOCK_GATE_CONTROL` / field masks / `DMA_CTRL_*` by symbol
- Observation ports `tb_dma_cg_en`/`tb_dma_gated_clk`/`tb_dma_gater_busy`/`tb_zeroer_cg_en`/
  `tb_zeroer_gated_axi_clk`/`tb_zeroer_busy` confirmed present via `assert hasattr(dut, port)`
  (seq.py:253-261) before use
- SF-002 disposition (SPEC_REVIEW): Enable Threshold == Hysteresis Control for P1 — programming
  `CG_HYST` for S3/S4 is consistent with the approved finding disposition, not a Skill 2 defect

</details>

<details>
<summary>Token / step cites (kept log `3d21022c…`)</summary>

| Checker | Log line | What the log shows | Impl |
|---|---|---|---|
| (setup) | 342 | `STEP S1: dma_cg_en=0; idle DMA clock continuously enabled` | seq `:270` |
| (setup) | 370 | `STEP S2: dma_cg_en=1 zeroer_cg_en=0; observe independent per-module gating` | seq `:282` |
| CHK-MODULE-GATING | 392 | `… continuous_idle_toggles=1 dma_edges_s1=16 independent=1 dma_gated_edges=0 zeroer_ungated_edges=16 window=16` (booleans derived; exact 16/16) | seq `:314` |
| (fence) | 395 | `FENCE module-gating-observed @ 5724ns` | seq `:322` |
| (setup) | 396 | `STEP S3: enable-threshold/hyst=8; measure re-gate delay` | seq `:325` |
| (fence) | 541 | `FENCE enable-threshold-min-measured @ 7542ns` | seq `:326` |
| (setup) | 542 | `STEP S4: enable-threshold/hyst=63; measure re-gate delay` | seq `:328` |
| (fence) | 683 | `FENCE enable-threshold-max-measured @ 10362ns` | seq `:329` |
| CHK-ENABLE-THRESHOLD | 684 | `min/max within_1cyc min=8/8 max=63/63 cells=enable_threshold_delay_min,enable_threshold_delay_max` | seq `:333` |
| (extra, not on card) | 685 | `CHK-TIMEOUT-PATHS: … fail_on_expiry=1` (bounded waits raise on expiry; not a card checker) | seq `:340` |
| CHK-NONVAC | 686 | `CHK-NONVAC: module-gating-observed < enable-threshold-min-measured < enable-threshold-max-measured < PASS` | seq `:354` |
| (fence) | 687 | `FENCE PASS @ 10362ns` | seq `:360` |

</details>

<details>
<summary>Layer 1 / Layer 2 notes</summary>

- Ordered fence (ns): module-gating-observed(5724) < enable-threshold-min-measured(7542) <
  enable-threshold-max-measured(10362) < PASS(10362); `assert_fence_order` (seq.py:346-353)
  gates NONVAC before the token is trusted.
- CHK-MODULE-GATING proof fence: SETUP program DMA cg disabled (S1) / opposite enables (S2) →
  ACTION idle observe → RESPONSE/EFFECT `count_enabled_at_smc_rise` / pair sample with exact
  `== IDLE_OBSERVE` and `dma_n == 0` → NONVAC fence term. Independent states proven in one
  concurrent window.
- CHK-ENABLE-THRESHOLD proof fence: SETUP program hyst=min/max with DMA gating enabled → ACTION
  DMA transfer → RESPONSE meter `tb_dma_gater_busy` fall vs last `tb_dma_gated_clk` edge →
  EFFECT `abs(delay - hyst) <= 1` (card within-one-period bar). No blind `Timer`-only stand-in.
- FAIL-ON paths: missing enabled sample; gated-off while disabled; modules tracking each other;
  threshold mismatch >1 cycle; gate-off / DMA-done / threshold quiet timeouts; X/Z samples;
  fence order; missing CHK tokens at test wrapper.
- Coverage: feature_list `SMC-CG-ARCH-PARAMS.S4` DIRECTED cells both hit; `S3` RANDOMIZED
  required cells `enable_threshold_delay_min/max` both hit with resolved knobs 8 and 63
  (`coverage_artifact: null`). Adequacy is required_cells, not seed count.
- No merged-evidence collision: `CHK-MODULE-GATING`, `CHK-ENABLE-THRESHOLD`, and `CHK-NONVAC`
  emit independent tokens; `CHK-NONVAC` is ordering only (`proves: []`). Extra
  `CHK-TIMEOUT-PATHS` is not graded (not on the approved card).
- The JTAG-AXI `_write_bytes` calls seed the TB memory model behind the DMA fabric
  (`update_golden = True`) — frontdoor AXI through the approved JTAG external-master port, not
  a DUT backdoor.
- F1/F2/E1/E2/S1/O1 structural rules: no fabricated verdict, no always-pass checker, no
  skip-to-pass, no empty phase, no silent fail, no disabled checker.

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
- **note:** Fresh Skill 2 re-audit (auditor `cursor/grok/4.5`,
  `run_id` `dv_test_audit-SMC_STATIC_CG_SANITY_TEST-493b545b-2608-47f6-8c06-eb04fad4ad0e`,
  distinct from authoring
  `dv_test_impl-SMC_STATIC_CG_SANITY_TEST-95afef5e-2325-4e52-878d-d6236ae7bfa7`).
  Rework log graded independently; prior 1/3 NOT-READY grade not treated as authoritative.
  3/3 PROVEN — recommendation EVIDENCE-CLOSED-AWAITING-SIGNOFF. Force/deposit check clean.
