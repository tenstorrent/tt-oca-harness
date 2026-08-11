---
schema: dv-quality/v1
artifact: testcase-grade
testcase: smc_zeroer_axiclk_cg_test
ip: SMC_CLOCK_GATING
anchor: smc_zeroer_axiclk_cg_test
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
card_sha256: 67c81eca9fc764cc694026df6a7da34a406f4c5528305cc17e43d9d6b9a045db
card_revision: 1
card_path: hw/sys/smc/dv/tb/SMC_CLOCK_GATING_VPLAN_DETAIL.md
testcase_plan:
  path: hw/sys/smc/dv/tb/SMC_CLOCK_GATING_TESTCASE_PLAN.md
  plan_revision: 1
  testcase_revision: 1
  testcase_record_sha256: 5b2f4fe439dc4b09edbcad1945ca1abc3a2e3aa354c37a9000e8c4dd6f7b0ed3
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
- path: hw/sys/smc/dv/build/runs/20260805_040006__verilator__smc_zeroer_axiclk_cg_test/smc_zeroer_axiclk_cg_test/logs/smc_zeroer_axiclk_cg_test.log
  sha256: d32840f62eaba3585678e27560c396fdfaafd797a0d227b9dd1722aeba25222e
test_author:
  human_id: minshaoho
  run_id: dv_test_impl-SMC_ZEROER_AXICLK_CG_TEST-95afef5e-2325-4e52-878d-d6236ae7bfa7
  model:
    provider: cursor
    family: grok
    version: '4.5'
auditor:
  human_id: minshaoho
  run_id: dv_test_audit-SMC_ZEROER_AXICLK_CG_TEST-a3f529c4-02ac-43fb-a1d8-907e6147b65a
  model:
    provider: cursor
    family: grok
    version: '4.5'
exceptions: []
checkers:
- id: CHK-ZAXI-GATE-OFF-IDLE
  checks_steps: [S1]
  proves: [ZEROER-AXICLK-CG]
  covers: [ZEROER-AXICLK-CG.S1]
  proof_class: LIVE
  expect_source: 'hw/sys/smc/doc/zeroer.adoc §Clock Gating, table "Clock Gating Control", row "AXI Clock" (rev 2f40548ea787240680a1c45ab75b8729e9620778)'
  grade: PROVEN
  evidence:
  - token: 'CHK-ZAXI-GATE-OFF-IDLE: gate_off_within_1cyc=1 gate_off_latency=0 zero_toggles_idle=16'
    log_sha256: d32840f62eaba3585678e27560c396fdfaafd797a0d227b9dd1722aeba25222e
    line: 382
    seed: 1
    implementation_path: hw/sys/smc/dv/cocotb/seq_lib/smc_zeroer_axiclk_cg_test_seq.py:229
  lifecycle_results: null
  coverage_results:
  - key: ZEROER-AXICLK-CG.S1
    method: DIRECTED
    required_cells: [axiclk_gated_off_idle]
    achieved_cells: [axiclk_gated_off_idle]
    random_knobs: []
    resolved_knobs: []
    min_seeds: 1
    actual_seeds: [1]
    required_artifact: null
    coverage_artifacts:
    - hw/sys/smc/dv/build/runs/20260805_040006__verilator__smc_zeroer_axiclk_cg_test/smc_zeroer_axiclk_cg_test/logs/smc_zeroer_axiclk_cg_test.log#d32840f62eaba3585678e27560c396fdfaafd797a0d227b9dd1722aeba25222e
    satisfied: true
  linked_issue: null
  finding_ids: []
  remediation: null
- id: CHK-ZAXI-BUSY-ENABLE
  checks_steps: [S2]
  proves: [ZEROER-AXICLK-CG]
  covers: [ZEROER-AXICLK-CG.S2]
  proof_class: LIVE
  expect_source: 'hw/sys/smc/doc/zeroer.adoc §Clock Gating, table "Clock Gating Control", row "AXI Clock" (rev 2f40548ea787240680a1c45ab75b8729e9620778)'
  grade: PROVEN
  evidence:
  - token: 'CHK-ZAXI-BUSY-ENABLE: resume_within_1cyc=1 resume_cyc=1 toggles_every_cycle=1 enabled_hits=10 post_resume_cycles=10'
    log_sha256: d32840f62eaba3585678e27560c396fdfaafd797a0d227b9dd1722aeba25222e
    line: 408
    seed: 1
    implementation_path: hw/sys/smc/dv/cocotb/seq_lib/smc_zeroer_axiclk_cg_test_seq.py:257
  lifecycle_results: null
  coverage_results:
  - key: ZEROER-AXICLK-CG.S2
    method: DIRECTED
    required_cells: [axiclk_enabled_on_busy]
    achieved_cells: [axiclk_enabled_on_busy]
    random_knobs: []
    resolved_knobs: []
    min_seeds: 1
    actual_seeds: [1]
    required_artifact: null
    coverage_artifacts:
    - hw/sys/smc/dv/build/runs/20260805_040006__verilator__smc_zeroer_axiclk_cg_test/smc_zeroer_axiclk_cg_test/logs/smc_zeroer_axiclk_cg_test.log#d32840f62eaba3585678e27560c396fdfaafd797a0d227b9dd1722aeba25222e
    satisfied: true
  linked_issue: null
  finding_ids: []
  remediation: null
- id: CHK-ZAXI-DISABLE-CG
  checks_steps: [S3]
  proves: [ZEROER-AXICLK-CG]
  covers: [ZEROER-AXICLK-CG.S3]
  proof_class: LIVE
  expect_source: 'hw/sys/smc/doc/zeroer.adoc §Clock Gating, table "Clock Gating Control", row "AXI Clock" (rev 2f40548ea787240680a1c45ab75b8729e9620778)'
  grade: PROVEN
  evidence:
  - token: 'CHK-ZAXI-DISABLE-CG: toggles_every_cycle=1 edges=16 window=16'
    log_sha256: d32840f62eaba3585678e27560c396fdfaafd797a0d227b9dd1722aeba25222e
    line: 432
    seed: 1
    implementation_path: hw/sys/smc/dv/cocotb/seq_lib/smc_zeroer_axiclk_cg_test_seq.py:288
  lifecycle_results: null
  coverage_results:
  - key: ZEROER-AXICLK-CG.S3
    method: DIRECTED
    required_cells: [axiclk_enabled_disable_cg_set]
    achieved_cells: [axiclk_enabled_disable_cg_set]
    random_knobs: []
    resolved_knobs: []
    min_seeds: 1
    actual_seeds: [1]
    required_artifact: null
    coverage_artifacts:
    - hw/sys/smc/dv/build/runs/20260805_040006__verilator__smc_zeroer_axiclk_cg_test/smc_zeroer_axiclk_cg_test/logs/smc_zeroer_axiclk_cg_test.log#d32840f62eaba3585678e27560c396fdfaafd797a0d227b9dd1722aeba25222e
    satisfied: true
  linked_issue: null
  finding_ids: []
  remediation: null
- id: CHK-ZAXI-RESET-OVERRIDE
  checks_steps: [S4]
  proves: [ZEROER-AXICLK-CG]
  covers: [ZEROER-AXICLK-CG.S4]
  proof_class: LIVE
  expect_source: 'hw/sys/smc/doc/zeroer.adoc §Clock Gating, table "Clock Gating Control", row "Reset Override" (rev 2f40548ea787240680a1c45ab75b8729e9620778)'
  grade: PROVEN
  evidence:
  - token: 'CHK-ZAXI-RESET-OVERRIDE: toggles_during_reset=1 edges=16 window=16'
    log_sha256: d32840f62eaba3585678e27560c396fdfaafd797a0d227b9dd1722aeba25222e
    line: 489
    seed: 1
    implementation_path: hw/sys/smc/dv/cocotb/seq_lib/smc_zeroer_axiclk_cg_test_seq.py:324
  lifecycle_results: null
  coverage_results:
  - key: ZEROER-AXICLK-CG.S4
    method: DIRECTED
    required_cells: [axiclk_enabled_during_reset]
    achieved_cells: [axiclk_enabled_during_reset]
    random_knobs: []
    resolved_knobs: []
    min_seeds: 1
    actual_seeds: [1]
    required_artifact: null
    coverage_artifacts:
    - hw/sys/smc/dv/build/runs/20260805_040006__verilator__smc_zeroer_axiclk_cg_test/smc_zeroer_axiclk_cg_test/logs/smc_zeroer_axiclk_cg_test.log#d32840f62eaba3585678e27560c396fdfaafd797a0d227b9dd1722aeba25222e
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
  - token: 'CHK-NONVAC: idle-gate-off-observed < busy-enable-observed < disable-cg-observed < reset-override-observed < PASS'
    log_sha256: d32840f62eaba3585678e27560c396fdfaafd797a0d227b9dd1722aeba25222e
    line: 512
    seed: 1
    implementation_path: hw/sys/smc/dv/cocotb/seq_lib/smc_zeroer_axiclk_cg_test_seq.py:348
  lifecycle_results: null
  coverage_results: []
  linked_issue: null
  finding_ids: []
  remediation: null
findings: []
waivers: []
recommendation: EVIDENCE-CLOSED-AWAITING-SIGNOFF
---

# Grade Report — smc_zeroer_axiclk_cg_test (SMC_ZEROER_AXICLK_CG_TEST)

**VERDICT: 5/5 PROVEN — READY** (mode CHECKBOX, entry PASS)

| Mode | Entry gate | Checkers | Findings | Recommendation |
|---|---|---|---|---|
| `CHECKBOX` | ✅ PASS | 5/5 PROVEN | none | ✅ EVIDENCE-CLOSED-AWAITING-SIGNOFF |

> Fresh Skill 2 re-audit on rework kept log `d32840f6…` (run `20260805_040006`). Prior grade on
> log `0f4ab012…` (**1/5 NOT-READY**) is **not** treated as authoritative. Entry PASS:
> cocotb `TESTS=1 PASS=1 FAIL=0 SKIP=0`, final `assert not missing` on all five `chk_seen`
> tokens, zero unexplained `ERROR`/`FATAL`/`Traceback`. Card r1 hash `67c81eca…` matches
> parent plan record r1 hash `5b2f4fe4…` (both recomputed), parent `status: approved`.
> **Force/deposit check: clean** — CSR/Zeroer frontdoor + JTAG memory seed + cool-reset pin
> + passive `tb_zeroer_*` observation only (owner hard constraint satisfied).

## DELTA (re-audit vs prior grade `1/5 NOT-READY` on log `0f4ab012…`)

| Prior id | Tag | Status this round | Notes |
|---|---|---|---|
| FIND-001 | `[ADDRESS-FROM-AUTHORITATIVE-MAP]` | CLOSED | Seq + `smc_cg_obs_utils` import CSR/Zeroer/fabric addresses and CG field masks from `seq_lib/smc_addr_map.py` (generated `smc_addr.h` / `smc_base_config.h`) |
| FIND-002 | `[EXACT-EXPECTATION]` | CLOSED | `_measure_busy_window_toggles` asserts `enabled_hits == post_resume_cycles` for the full post-resume busy window; this log `enabled_hits=10 post_resume_cycles=10` |
| FIND-003 | `[EXACT-EXPECTATION]` | CLOSED | S3/S4 assert `edges == IDLE_OBSERVE` via `count_enabled_at_smc_rise`; this log `edges=16 window=16` twice |
| FIND-004 | `[EXACT-EXPECTATION]` | CLOSED | `measure_gate_off_latency` + `assert gate_off_lat <= 1`; this log `gate_off_latency=0` |
| FIND-005 | `[EXACT-EXPECTATION]` | CLOSED | Token booleans derived from measured comparisons (`within_1` / `resume_ok` / `every_ok` / `toggles_*`) |
| CHK-ZAXI-GATE-OFF-IDLE | INSUFFICIENT-EVIDENCE → PROVEN | UPGRADED | Latency + zero-toggle idle window |
| CHK-ZAXI-BUSY-ENABLE | INSUFFICIENT-EVIDENCE → PROVEN | UPGRADED | Resume ≤1cyc + every-cycle busy window |
| CHK-ZAXI-DISABLE-CG | INSUFFICIENT-EVIDENCE → PROVEN | UPGRADED | Exact 16/16 under disable_cg |
| CHK-ZAXI-RESET-OVERRIDE | INSUFFICIENT-EVIDENCE → PROVEN | UPGRADED | Exact 16/16 during cool reset |
| CHK-NONVAC | stayed PROVEN | unchanged substance | New kept log `d32840f6…` |

## Your to-do — 0 items (none)

| # | Rank | Item |
|---|---|---|
| — | — | none open |

**Then:** human signoff on this grade → Skill 3 peer audit when the remaining SMC_CLOCK_GATING anchors close, or continue Skill 2 on still-open anchors.

## All checkers

| Checker | Grade | Proof class | Covers | Findings |
|---|---|---|---|---|
| CHK-ZAXI-GATE-OFF-IDLE | ✅ PROVEN | LIVE | ZEROER-AXICLK-CG.S1 | — |
| CHK-ZAXI-BUSY-ENABLE | ✅ PROVEN | LIVE | ZEROER-AXICLK-CG.S2 | — |
| CHK-ZAXI-DISABLE-CG | ✅ PROVEN | LIVE | ZEROER-AXICLK-CG.S3 | — |
| CHK-ZAXI-RESET-OVERRIDE | ✅ PROVEN | LIVE | ZEROER-AXICLK-CG.S4 | — |
| CHK-NONVAC | ✅ PROVEN | INTEGRITY | — | — |

### Layer 1 structural rule set

| Rule | Result |
|---|---|
| F1 fabricated verdict / backdoor write | ✅ clean — CSR/data via frontdoor AXI; cool-reset via top-level `rst_cool_ni` pin; TB observation ports are passive `assign`s; no force/deposit on gated clock / busy / disable_cg |
| F2 can't-fail checker | ✅ clean — every LIVE checker has a reachable `AssertionError` fail path (gate-off latency, exact edge counts, resume delta, busy-window equality, reset wait timeout, X/Z) |
| E1 skip-to-pass | ✅ clean — missing TB ports `assert hasattr` fail; no HDL-path skip-to-pass |
| E2 empty phase | ✅ clean — S1–S4 each program, observe, and assert |
| S1 silent fail | ✅ clean — every mismatch/timeout raises `AssertionError` with diagnostic state |
| O1 checker disabled | ✅ clean |
| Phase-S obligations — L1 | ✅ clean |
| Phase-S obligations — L2 (needs the card) | ✅ clean |

## Evidence appendix

<details>
<summary>Kept log + build identity</summary>

- Log: `hw/sys/smc/dv/build/runs/20260805_040006__verilator__smc_zeroer_axiclk_cg_test/smc_zeroer_axiclk_cg_test/logs/smc_zeroer_axiclk_cg_test.log`
  sha256 `d32840f62eaba3585678e27560c396fdfaafd797a0d227b9dd1722aeba25222e` (verified via
  `manifest.py hash-file`; matches owner hint)
- `result.json`: `status: PASS`, `return_code: 0`, seed 1, target `default`, simulator
  `verilator` `5.050 2026-07-01`, `target_build.fingerprint: 2c815fa08277`, rebuild=false,
  positive-evidence parser (`results_xml` + `log_summary`, both PASS)
- Card: SMC_ZEROER_AXICLK_CG_TEST r1
  `67c81eca9fc764cc694026df6a7da34a406f4c5528305cc17e43d9d6b9a045db` (recomputed match against
  `SMC_CLOCK_GATING_VPLAN_DETAIL.md`)
- Parent plan record: r1
  `5b2f4fe439dc4b09edbcad1945ca1abc3a2e3aa354c37a9000e8c4dd6f7b0ed3` · `plan_revision: 1` ·
  `status: approved` (recomputed match against `SMC_CLOCK_GATING_TESTCASE_PLAN.md`)
- Cocotb summary L526: `TESTS=1 PASS=1 FAIL=0 SKIP=0`; final assertion gate in
  `smc_zeroer_axiclk_cg_test.py` checks all five `CHK-*` tokens landed in `seq.chk_seen`; no
  unexplained `ERROR`/`FATAL`/`Traceback` (only benign cocotb/library `DeprecationWarning`s)
- Enrolled: `hw/sys/smc/dv/testlists/clock.toml` → `smc_zeroer_axiclk_cg_test`
- Force/deposit audit (owner hard constraint): no `force`/`deposit`/`uvm_hdl_*` in
  `smc_zeroer_axiclk_cg_test.py`, `smc_zeroer_axiclk_cg_test_seq.py`, or `smc_cg_obs_utils.py`
- Address map: `seq_lib/smc_addr_map.py` + re-exports in `smc_cg_obs_utils.py`; seq imports
  `_addr.CLOCK_GATE_CONTROL` / `ZEROER_CG_EN` / `CG_HYST_*` / fabric filters / `ZEROER_CTRL_*`
- Observation ports `tb_zeroer_cg_en` / `tb_zeroer_gated_axi_clk` / `tb_zeroer_busy` /
  `tb_output_axi_write_count` / `rst_cool_ni` / `rst_primary_smc_clk_no` asserted present via
  `hasattr` before use; `sample_bit` / gated samples raise on X/Z
- `tb_zeroer_gated_axi_clk` is a passive hierarchical assign of zeroer `axi_clk`
  (`tb_top.sv:1132-1133`); cool-reset drives top-level `rst_cool_ni` and waits for
  `rst_primary_smc_clk_no` — frontdoor reset path

</details>

<details>
<summary>Token / step cites (kept log `d32840f6…`)</summary>

| Checker | Log line | What the log shows | Impl |
|---|---|---|---|
| (setup) | 333 | `STEP S1: disable_cg=0 (zeroer_cg_en=1), idle, observe axi_clk gates off` | seq `:202` |
| CHK-ZAXI-GATE-OFF-IDLE | 382 | `gate_off_within_1cyc=1 gate_off_latency=0 zero_toggles_idle=16` (derived boolean + measured latency) | seq `:229` |
| (fence) | 385 | `FENCE idle-gate-off-observed @ 5484ns` | seq `:235` |
| (setup) | 386 | `STEP S2: trigger zeroer; axi_clk resumes for busy window` | seq `:238` |
| CHK-ZAXI-BUSY-ENABLE | 408 | `resume_within_1cyc=1 resume_cyc=1 toggles_every_cycle=1 enabled_hits=10 post_resume_cycles=10` | seq `:257` |
| (fence) | 409 | `FENCE busy-enable-observed @ 5724ns` | seq `:264` |
| (setup) | 410 | `STEP S3: zeroer_cg_en=0 (disable_cg=1); idle axi_clk stays enabled` | seq `:277` |
| CHK-ZAXI-DISABLE-CG | 432 | `toggles_every_cycle=1 edges=16 window=16` | seq `:288` |
| (fence) | 433 | `FENCE disable-cg-observed @ 6198ns` | seq `:294` |
| (setup) | 434 | `STEP S4: re-enable CG, gate off, assert cool reset; axi_clk enabled` | seq `:297` |
| CHK-ZAXI-RESET-OVERRIDE | 489 | `toggles_during_reset=1 edges=16 window=16` | seq `:324` |
| (fence) | 490 | `FENCE reset-override-observed @ 6906ns` | seq `:330` |
| CHK-NONVAC | 512 | ordered fence terms before PASS | seq `:348` |
| (fence) | 513 | `FENCE PASS @ 7134ns` | seq `:354` |

</details>

<details>
<summary>Layer 1 / Layer 2 notes</summary>

- Ordered fence (ns): idle-gate-off-observed(5484) < busy-enable-observed(5724) <
  disable-cg-observed(6198) < reset-override-observed(6906) < PASS(7134);
  `assert_fence_order` (seq.py:339-347) gates NONVAC before the token is trusted; VIP details
  echo the same timestamps.
- CHK-ZAXI-GATE-OFF-IDLE proof fence: SETUP free-run positive control (`disable_cg` off →
  `edges==4`) then program `zeroer_cg_en=1` with busy=0 → ACTION `measure_gate_off_latency`
  → RESPONSE/EFFECT `gate_off_lat <= 1` and `edges == 0` over IDLE_OBSERVE → NONVAC fence.
- CHK-ZAXI-BUSY-ENABLE proof fence: SETUP axi_clk gated off → ACTION frontdoor Zeroer start →
  RESPONSE resume within 1 smc cycle of `tb_zeroer_busy` → EFFECT every-cycle enable samples
  for the entire post-resume busy window (`enabled_hits == post_resume_cycles`, non-empty).
- CHK-ZAXI-DISABLE-CG / CHK-ZAXI-RESET-OVERRIDE: exact `edges == IDLE_OBSERVE` via
  `count_enabled_at_smc_rise`; S1 already proved the same clock can gate (positive control for
  the continuously-enabled claims).
- FAIL-ON paths: gate-off latency timeout / `>1`; idle residual toggles; busy never asserts /
  never resumes / empty post-resume window / missing enable sample; disable/reset missing cycle;
  cool-reset primary timeout; X/Z samples; fence order; missing CHK tokens at test wrapper.
- Coverage: feature_list `ZEROER-AXICLK-CG.S1–S4` DIRECTED required cells all hit
  (`coverage_artifact: null`). Adequacy is required_cells, not seed count. S5
  (`axiclk_no_glitch_back_to_back_ops`) is not allocated to this card.
- No merged-evidence collision: each LIVE checker emits its own token from its own step;
  `CHK-NONVAC` is ordering only (`proves: []`).
- No blind `Timer`-only wait stands in for a measured event on the proof path: gate-off /
  busy resume / enable counts are RisingEdge-driven; fixed `ClockCycles(..., 4)` / `32`
  delays are settle bridges, not the checked quantity.
- Regression enrollment confirmed in `hw/sys/smc/dv/testlists/clock.toml`.

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
  `run_id` `dv_test_audit-SMC_ZEROER_AXICLK_CG_TEST-a3f529c4-02ac-43fb-a1d8-907e6147b65a`,
  distinct from authoring
  `dv_test_impl-SMC_ZEROER_AXICLK_CG_TEST-95afef5e-2325-4e52-878d-d6236ae7bfa7` and prior
  auditor `…-a559a49b-…`). Rework log graded independently; prior 1/5 NOT-READY grade not
  treated as authoritative. 5/5 PROVEN — recommendation EVIDENCE-CLOSED-AWAITING-SIGNOFF.
  Force/deposit check clean.
