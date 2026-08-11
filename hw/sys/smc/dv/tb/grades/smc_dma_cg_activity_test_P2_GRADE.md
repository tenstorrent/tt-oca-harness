---
schema: dv-quality/v1
artifact: testcase-grade
testcase: smc_dma_cg_activity_test
ip: SMC_CLOCK_GATING_P2
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
card_sha256: f30a819ece07cac193724665274c74e6512a18c0771b7fde11375464acf5489a
card_revision: 1
card_path: hw/sys/smc/dv/tb/SMC_CLOCK_GATING_P2_VPLAN_DETAIL.md
testcase_plan:
  path: hw/sys/smc/dv/tb/SMC_CLOCK_GATING_P2_TESTCASE_PLAN.md
  plan_revision: 1
  testcase_revision: 1
  testcase_record_sha256: 98e628cd4183ce05c02517f1828a9ed5ee18b3a0849be5c14b4c2d8a71dbd316
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
- path: hw/sys/smc/dv/build/runs/20260805_092045__verilator__smc_dma_cg_activity_test/smc_dma_cg_activity_test/logs/smc_dma_cg_activity_test.log
  sha256: 3bc69b7a595712d77ce226742cb67103bd5f0b6a34e34c68e8cc551bd3134919
test_author:
  human_id: minshaoho
  run_id: dv_test_impl-SMC_CG_P2_001-coverage-fix-2026-08-05T09:20:45Z
  model:
    provider: cursor
    family: claude
    version: sonnet-5
auditor:
  human_id: minshaoho
  run_id: dv_test_audit-SMC_CG_P2_001-fresh-8f2d16c3-2026-08-05T17:21:00+08:00
  model:
    provider: cursor
    family: claude
    version: sonnet-5
exceptions: []
checkers:
- id: CHK-DMA-HYST-SWEEP
  checks_steps: [S2]
  proves: [SMC-CG-DMA-HYST]
  covers: [SMC-CG-DMA-HYST.S1]
  proof_class: LIVE
  expect_source: 'hw/sys/smc/doc/dma.adoc §Configuration Parameters (CG_HYSTERESIS_W) and §Performance Optimization and Power Management (Clock Gating Configuration) @ e2aae39953bb8001c7c20e3afd3956e68c22440c'
  grade: PROVEN
  evidence:
  - token: 'CHK-DMA-HYST-SWEEP: gap0(hyst_field=0,deassert_cyc=0) gap1(hyst_field=1,deassert_cyc=1) gap32(hyst_field=32,deassert_cyc=32) gap63(hyst_field=63,deassert_cyc=63) gap64(hyst_field=0,deassert_cyc=0) coverage_artifact=functional-coverage-report.json cells=hyst-gap=0,hyst-gap=1,hyst-gap=32,hyst-gap=63,hyst-gap=64'
    log_sha256: 3bc69b7a595712d77ce226742cb67103bd5f0b6a34e34c68e8cc551bd3134919
    line: 1387
    seed: 1
    implementation_path: hw/sys/smc/dv/cocotb/seq_lib/smc_dma_cg_activity_test_seq.py:641
  lifecycle_results: null
  coverage_results:
  - key: SMC-CG-DMA-HYST.S1
    method: RANDOMIZED
    required_cells: [hyst-gap=0, hyst-gap=1, hyst-gap=32-mid, hyst-gap=63-max, hyst-gap=64-just-over-max]
    achieved_cells: [hyst-gap=0, hyst-gap=1, hyst-gap=32-mid, hyst-gap=63-max, hyst-gap=64-just-over-max]
    random_knobs: ['inter-activity gap length in clk_smc_i cycles, swept 0 through 64']
    resolved_knobs: [gap=0, gap=1, gap=32, gap=63, gap=64]
    min_seeds: 1
    actual_seeds: [1]
    required_artifact: functional_coverage_report
    coverage_artifacts:
    - hw/sys/smc/dv/build/runs/20260805_092045__verilator__smc_dma_cg_activity_test/smc_dma_cg_activity_test/logs/functional-coverage-report.json#f7c4ebc10ea30bf30f596103522c5b3d159bddfcdc92636ed506241c74079c1c
    satisfied: true
  linked_issue: null
  finding_ids: []
  remediation: null
- id: CHK-DMA-HYST-RACE
  checks_steps: [S3]
  proves: [SMC-CG-DMA-HYST]
  covers: [SMC-CG-DMA-HYST.S2]
  proof_class: LIVE
  expect_source: 'hw/sys/smc/doc/dma.adoc §Performance Optimization and Power Management (Activity Detection); hw/sys/smc/doc/clk_rst.adoc §Clock and Reset-Based Power Management Integration (Hysteresis Control) @ 2f40548ea787240680a1c45ab75b8729e9620778'
  grade: PROVEN
  evidence:
  - token: 'CHK-DMA-HYST-RACE: zero_glitches=1 hyst=40 early_offset=11 b2b_gap=8 late_offset=35 final_countdown_restarted_full=40'
    log_sha256: 3bc69b7a595712d77ce226742cb67103bd5f0b6a34e34c68e8cc551bd3134919
    line: 1439
    seed: 1
    implementation_path: hw/sys/smc/dv/cocotb/seq_lib/smc_dma_cg_activity_test_seq.py:663
  lifecycle_results: null
  coverage_results:
  - key: SMC-CG-DMA-HYST.S2
    method: DIRECTED
    required_cells: [activity-reassert-early-in-countdown, activity-reassert-at-last-cycle-of-countdown, activity-clear-immediately-after-reassert, back-to-back-reassert-reassert]
    achieved_cells: [activity-reassert-early-in-countdown, activity-reassert-at-last-cycle-of-countdown, activity-clear-immediately-after-reassert, back-to-back-reassert-reassert]
    random_knobs: []
    resolved_knobs: []
    min_seeds: 1
    actual_seeds: [1]
    required_artifact: null
    coverage_artifacts:
    - hw/sys/smc/dv/build/runs/20260805_092045__verilator__smc_dma_cg_activity_test/smc_dma_cg_activity_test/logs/smc_dma_cg_activity_test.log#3bc69b7a595712d77ce226742cb67103bd5f0b6a34e34c68e8cc551bd3134919
    satisfied: true
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
  - token: 'CHK-NONVAC: SETUP < ACTIVITY-BASELINE < SWEEP-COMPLETE(5-cells) < RACE-REASSERT-EARLY < RACE-REASSERT-LAST < PASS'
    log_sha256: 3bc69b7a595712d77ce226742cb67103bd5f0b6a34e34c68e8cc551bd3134919
    line: 1444
    seed: 1
    implementation_path: hw/sys/smc/dv/cocotb/seq_lib/smc_dma_cg_activity_test_seq.py:701
  lifecycle_results: null
  coverage_results: []
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
  - token: 'CHK-TIMEOUT-PATHS: sweep_bound_smc_cycles=130 settle_bound_smc_cycles=200 race_pulse_bound_smc_cycles=200 race_final_bound_smc_cycles=60 expired=0 last_gater_busy=0 dma_cg_en=1'
    log_sha256: 3bc69b7a595712d77ce226742cb67103bd5f0b6a34e34c68e8cc551bd3134919
    line: 1443
    seed: 1
    implementation_path: hw/sys/smc/dv/cocotb/seq_lib/smc_dma_cg_activity_test_seq.py:676
  lifecycle_results: null
  coverage_results: []
  linked_issue: null
  finding_ids: []
  remediation: null
findings: []
waivers: []
recommendation: EVIDENCE-CLOSED-AWAITING-SIGNOFF
---

# Grade Report — smc_dma_cg_activity_test (SMC_CG_P2_001, IP SMC_CLOCK_GATING_P2)

**VERDICT: 4/4 PROVEN — EVIDENCE-CLOSED-AWAITING-SIGNOFF** (mode CHECKBOX, entry PASS)

| Mode | Entry gate | Checkers | Findings | Recommendation |
|---|---|---|---|---|
| `CHECKBOX` | ✅ PASS | 4/4 PROVEN | none | ✅ EVIDENCE-CLOSED-AWAITING-SIGNOFF |

**SIGNOFF RECORDED** — see [Human signoff](#human-signoff) below.

> Fresh Skill 2 re-audit of the **P2** card `SMC_CG_P2_001` on the new kept log `3bc69b7a…`
> (run `20260805_092045`), superseding the prior round's kept log `dcc3f062…`
> (run `20260805_084816`). This anchor also carries a **separate, already-closed P1 grade**
> (`grades/smc_dma_cg_activity_test_GRADE.md`) — that file governs the unrelated P1 checkers
> (`CHK-DMA-GATE-OFF`, `CHK-DMA-WAKEUP-FRONTEND`, `CHK-DMA-WAKEUP-BACKEND`,
> `CHK-DMA-GATING-DISABLED`, P1's own `CHK-NONVAC`) and was **not read as authoritative for
> this round, not overwritten, and not touched**. This report grades only the 4 checkers on
> the P2 card. Card r1 hash `f30a819e…` (recomputed via `manifest.py record-hash`) matches;
> parent plan record r1 hash `98e628cd…` (recomputed) matches the card's
> `derived_from.testcase_record_sha256`; parent `status: approved`, `current: true`. Entry
> PASS: `result.json status: PASS`, cocotb `TESTS=1 PASS=1 FAIL=0 SKIP=0`, zero unexplained
> `ERROR`/`FATAL`/`Traceback`. Force/deposit check: clean (unchanged from prior round — no
> stimulus/observation code was touched by the fix).

## Delta from prior round (`smc_dma_cg_activity_test_P2_GRADE.md`, kept log `dcc3f062…`)

| Item | Prior round | This round |
|---|---|---|
| `CHK-DMA-HYST-SWEEP` | ⚠️ INSUFFICIENT-EVIDENCE (`coverage_results.satisfied: false` — no `functional_coverage_report`-class artifact produced) | ✅ PROVEN — `functional-coverage-report.json` now emitted beside the kept log (`P2_COVERAGE_ARTIFACT` log line 1386) and inline in `coverage/`; `satisfied: true`; `required_cells` == `cells_hit` == `{hyst-gap=0,1,32,63,64}` |
| `FIND-001` `[COVERAGE-ARTIFACT-UNRESOLVED]` | Open (UNMAPPED-IN-POLICY) | **Closed** — the named artifact class now exists and is diffed against `required_cells` (see coverage appendix below); no residual finding |
| `CHK-DMA-HYST-RACE` / `CHK-NONVAC` / `CHK-TIMEOUT-PATHS` | ✅ PROVEN | ✅ PROVEN (unchanged evidence tokens, same line numbers, same values — only the log's sha256 changed because of the new run/timestamp and the added `P2_COVERAGE_ARTIFACT` line) |
| Recommendation | ⛔ NOT-READY | ✅ EVIDENCE-CLOSED-AWAITING-SIGNOFF |
| Waivers carried forward | — | `waivers: []` — prior grade's ledger was already empty (`| — | — | — | none | — |`); nothing to carry |

**Root cause of the fix (verified in `seq_lib/smc_dma_cg_activity_test_seq.py`):** a new
`_emit_p2_hyst_sweep_coverage_report(cells_hit)` helper is called at the end of the P2 sweep
step (after all 5 `hyst-gap` cells are measured) and writes
`artifact_type: functional-coverage-report`, `feature_key: SMC-CG-DMA-HYST.S1`,
`method: RANDOMIZED`, `required_cells`, `cells_hit`, and a computed `satisfied` boolean to
`functional-coverage-report.json` in both the run's `logs/` and `coverage/` output
directories (mirroring the existing `_emit_functional_coverage_report` pattern in
`smc_zeroer_dma_timeout_test_seq.py` that the prior round's `FIND-001` remediation pointed
at). The write path is confirmed present in the run directory and the artifact's own
`cells_hit` matches the log's `CHK-DMA-HYST-SWEEP` line byte-for-byte.

## All checkers

| Checker | Grade | Proof class | Covers | Findings |
|---|---|---|---|---|
| CHK-DMA-HYST-SWEEP | ✅ PROVEN | LIVE | SMC-CG-DMA-HYST.S1 | — |
| CHK-DMA-HYST-RACE | ✅ PROVEN | LIVE | SMC-CG-DMA-HYST.S2 | — |
| CHK-NONVAC | ✅ PROVEN | INTEGRITY | — | — |
| CHK-TIMEOUT-PATHS | ✅ PROVEN | INTEGRITY | — | — |

### Layer 1 structural rule set

| Rule | Result |
|---|---|
| F1 fabricated verdict / backdoor write | ✅ clean — all P2 stimulus is frontdoor CSR read/write via generated `smc_addr_map` symbols; observation ports are pre-existing passive `tb_top.sv` assigns; no `force`/`deposit`/`uvm_hdl_*` anywhere in `smc_dma_cg_activity_test_seq.py` / `smc_dma_cg_activity_test.py` |
| F2 can't-fail checker | ✅ clean — every P2 checker has a reachable `AssertionError` fail path (exact deassert-cycle mismatch, glitch detection, final-countdown mismatch, fence-order mismatch, timeout expiry) |
| E1 skip-to-pass | ✅ clean — `assert hasattr(dut, port)` on all required TB ports; no HDL-path skip-to-pass |
| E2 empty phase | ✅ clean — P2-S1..S4 each program, observe, and assert with real state transitions |
| S1 silent fail | ✅ clean — every mismatch/timeout raises `AssertionError` with diagnostic state (no `log.info`/`warning`-only handling) |
| O1 checker disabled | ✅ clean |
| Phase-S obligations — L1 | ✅ clean — X/Z guarded via `_sample_bit`; no blind-delay-sync (edge-driven sampling throughout, `Timer(1, ...)` calls are same-edge-alignment bridges only, never the checked quantity); addresses sourced from generated `smc_addr_map` symbols, never hand literals; regression enrolled (`hw/sys/smc/dv/testlists/clock.toml`) |
| Phase-S obligations — L2 (needs the card) | ✅ clean — coverage-artifact contract for `SMC-CG-DMA-HYST.S1` now closed (`satisfied: true`); proof fence, static sensitivity, no merged evidence between `CHK-DMA-HYST-SWEEP`/`CHK-DMA-HYST-RACE`/`CHK-NONVAC`/`CHK-TIMEOUT-PATHS` all clean |

## Evidence appendix

<details>
<summary>Kept log + build identity + entry-gate recomputation</summary>

- Log: `hw/sys/smc/dv/build/runs/20260805_092045__verilator__smc_dma_cg_activity_test/smc_dma_cg_activity_test/logs/smc_dma_cg_activity_test.log`
  sha256 `3bc69b7a595712d77ce226742cb67103bd5f0b6a34e34c68e8cc551bd3134919` (verified via
  `manifest.py hash-file`)
- Coverage artifact: `.../logs/functional-coverage-report.json` (identical copy also in
  `.../coverage/functional-coverage-report.json`) sha256
  `f7c4ebc10ea30bf30f596103522c5b3d159bddfcdc92636ed506241c74079c1c` — content:
  `feature_key: SMC-CG-DMA-HYST.S1`, `method: RANDOMIZED`, `required_cells` ==
  `cells_hit` == `[hyst-gap=0, hyst-gap=1, hyst-gap=32, hyst-gap=63, hyst-gap=64]`,
  `satisfied: true`
- `result.json`: `status: PASS`, `return_code: 0`, seed 1, target `default`, simulator
  `verilator` `5.050 2026-07-01`, `target_build.fingerprint: 2c815fa08277`,
  `build_cache.rebuild: false`, positive-evidence parser (`results_xml` + `log_summary`, both
  PASS)
- Card `SMC_CG_P2_001` r1 `f30a819ece07cac193724665274c74e6512a18c0771b7fde11375464acf5489a` —
  recomputed via `manifest.py record-hash SMC_CLOCK_GATING_P2_VPLAN_DETAIL.md --id
  SMC_CG_P2_001 --array cards` → `match: true`
- Parent plan record `SMC_CG_P2_001` r1 `98e628cd4183ce05c02517f1828a9ed5ee18b3a0849be5c14b4c2d8a71dbd316`
  matches card's `derived_from.testcase_record_sha256` verbatim; `plan_revision: 1` /
  `testcase_revision: 1` both match; parent `status: approved`, `current: true` → no
  `ENTRY-STALE` / `ENTRY-PARENT-UNAPPROVED`
- Canonical testcase name `smc_dma_cg_activity_test` consistent across card `anchor`, plan
  `anchor`, `testlists/clock.toml` `name`/`module`, `tests/smc_dma_cg_activity_test.py` class
  name, and the cocotb log's `running smc_dma_cg_activity_test.smc_dma_cg_activity_test` line
  → no `ENTRY-IDENTITY-MISMATCH`
- Cocotb summary L1458: `TESTS=1 PASS=1 FAIL=0 SKIP=0`; final assertion gate in
  `smc_dma_cg_activity_test.py:44-45` checks all nine required `CHK-*` tokens (5 P1 + 4 P2)
  landed in `seq.chk_seen`; zero unexplained `ERROR`/`FATAL`/`Traceback` (only benign
  cocotb/library `DeprecationWarning`s and unrelated bring-up `[INFO]` lines)
- Enrolled: `hw/sys/smc/dv/testlists/clock.toml` → `smc_dma_cg_activity_test` (tags
  `clock`/`pyuvm`/`dma_cg`, also listed in the `smoke` `tests=[...]` group)
- Force/deposit audit: no `force`/`deposit`/`uvm_hdl_*` in `smc_dma_cg_activity_test_seq.py`
  or `smc_dma_cg_activity_test.py`; code comment at seq.py:373-381 explicitly documents the
  frontdoor-only activity-pulse technique used instead of a backdoor
- Address map: seq imports `CLOCK_GATE_CONTROL`/`DMA_CG_EN`/`CG_HYST_SHIFT`/`CG_HYST_MASK`
  etc. from `seq_lib/smc_addr_map.py` (generated header re-export); `_program_cg_field`
  writes/reads the hysteresis field exclusively through the generated shift/mask, including
  the intentional gap=64 truncation path (`CG_HYSTERESIS_W` is 6-bit; 64 truncates to field
  value 0 on real hardware, not a TB special case)

</details>

<details>
<summary>Token / step cites (kept log `3bc69b7a…`)</summary>

| Checker | Log line | What the log shows | Impl |
|---|---|---|---|
| (setup) | 1217 (STEP P2-S1) | SETUP: re-enable DMA CG, confirm idle baseline | seq.py:597-609 |
| (setup) | 1245 (STEP P2-S2) | ACTION/RESPONSE/EFFECT for S1: sweep hysteresis over `{0,1,32,63,64}` | seq.py:611-615 |
| (coverage) | 1386 | `P2_COVERAGE_ARTIFACT: functional-coverage-report.json path=… cells=hyst-gap=0,hyst-gap=1,hyst-gap=32,hyst-gap=63,hyst-gap=64` — new in this round | seq.py:641-649 |
| CHK-DMA-HYST-SWEEP | 1387 | `gap0(hyst_field=0,deassert_cyc=0) gap1(hyst_field=1,deassert_cyc=1) gap32(hyst_field=32,deassert_cyc=32) gap63(hyst_field=63,deassert_cyc=63) gap64(hyst_field=0,deassert_cyc=0) coverage_artifact=functional-coverage-report.json cells=hyst-gap=0,hyst-gap=1,hyst-gap=32,hyst-gap=63,hyst-gap=64` — all 5 required cells, each `deassert_cyc == hyst_field` exactly (gap=64 truncates to field 0, which is `<=63` per the card's own declared rule for the over-max cell), now with the coverage-artifact reference inline | seq.py:641-649 |
| (fence) | 1388 | `FENCE SWEEP-COMPLETE(5-cells) @ 16872ns` | seq.py:650 |
| (setup) | 1389 (STEP P2-S3) | ACTION/RESPONSE/EFFECT for S2: activity-reassert race (early / back-to-back / last-cycle) | seq.py:651-655 |
| CHK-DMA-HYST-RACE | 1439 | `zero_glitches=1 hyst=40 early_offset=11 b2b_gap=8 late_offset=35 final_countdown_restarted_full=40` | seq.py:663-670 |
| (fence) | 1440-1441 | `FENCE RACE-REASSERT-EARLY @ …` / `FENCE RACE-REASSERT-LAST @ 18120ns` | seq.py:671-672 |
| (setup) | 1442 (STEP P2-S4) | TIMEOUT: every bounded wait above has a finite bound + fail-on-expiry + last-state diagnostic | seq.py:674-675 |
| CHK-TIMEOUT-PATHS | 1443 | `sweep_bound_smc_cycles=130 settle_bound_smc_cycles=200 race_pulse_bound_smc_cycles=200 race_final_bound_smc_cycles=60 expired=0 last_gater_busy=0 dma_cg_en=1` | seq.py:676-688 |
| CHK-NONVAC (P2) | 1444 | `SETUP < ACTIVITY-BASELINE < SWEEP-COMPLETE(5-cells) < RACE-REASSERT-EARLY < RACE-REASSERT-LAST < PASS` | seq.py:690-706 |
| (fence) | 1445 | `FENCE PASS @ 18120ns` | seq.py:707 |

**Token-hygiene observation (not a finding):** `CHK-NONVAC:` is emitted twice in this kept
log — once by the unrelated, already-closed P1 flow at line 1214 (`gate-off-observed < … <
PASS`) and once by this P2 card's own checker at line 1444 (`SETUP < ACTIVITY-BASELINE < … <
PASS`). Fully independent content, line numbers, and fence-term lists — not a
`[MERGED-EVIDENCE]` violation, but a naive `grep 'CHK-NONVAC:'` returns both, so a
reader/tool must disambiguate by content or line number, not by name alone.

</details>

<details>
<summary>Layer 1 / Layer 2 notes</summary>

- Ordered fence (ns) for the P2 flow: SETUP(12216) < ACTIVITY-BASELINE(12522) <
  SWEEP-COMPLETE(5-cells)(16872) < RACE-REASSERT-EARLY(18120) < RACE-REASSERT-LAST(18120) <
  PASS(18120); `assert fence_terms == expected_p2_pre_pass` (seq.py:698-700) gates the P2
  `CHK-NONVAC` token before it is trusted.
- `CHK-DMA-HYST-SWEEP` proof fence: SETUP (idle+gated baseline via `_p2_settle_idle`) → ACTION
  (`_program_cg_field` writes each swept gap through the generated mask/shift, with a
  readback assertion) → RESPONSE/EFFECT (`_scan_activity_and_gate` samples every
  `clk_smc_i` period; `_find_last_deassert` + `_count_consecutive_edges` derive the observed
  deassert cycle) → static compare against `actual_hyst` (the programmed, readback-verified
  register value — never the DUT's own clock-enable trace, satisfying
  `CHK-NO-TAUTOLOGY`/`[INDEPENDENT-EXPECTED-MODEL]`). All 5 required cells
  (`hyst-gap={0,1,32-mid,63-max,64-just-over-max}`) are hit with an exact-match assertion
  (`==` for gap≤63, `<=63` for the truncating gap=64 cell). **Coverage-result gate now
  closed**: `_emit_p2_hyst_sweep_coverage_report` writes `functional-coverage-report.json`
  (both `logs/` and `coverage/`) with `required_cells == cells_hit` and `satisfied: true`,
  matching what the kept log's `CHK-DMA-HYST-SWEEP` line reports byte-for-byte. Per schema
  (`schema_check.py` `check_grade`: a `PROVEN` checker's every `covers` entry must have
  `coverage_results.satisfied == true`), this checker is now eligible for `PROVEN`.
- `CHK-DMA-HYST-RACE` proof fence: SETUP (`_p2_settle_idle` to a fresh gated baseline at
  `race_hyst=40`) → ACTION (`_race_trial`: early reassert, back-to-back reassert, last-cycle
  reassert, each a frontdoor CSR-read activity pulse) → RESPONSE/EFFECT
  (`_assert_no_glitch` between every pair of trial boundaries; `_count_consecutive_edges` on
  the final uninterrupted countdown) → static compare `final_countdown == race_hyst` (the
  programmed hysteresis value, readback-verified — independent of the DUT's own trace).
  Coverage: `coverage_artifact: null` (DIRECTED) → satisfied by the kept log per this repo's
  established convention.
- `CHK-NONVAC` / `CHK-TIMEOUT-PATHS`: `proves: []` / `covers: []`, so no coverage_results
  apply; both are ordering/structural (`INTEGRITY`) claims verified directly against the code
  (fence-order assert; four independently-bounded waits each with a real `AssertionError` +
  last-state diagnostic on expiry, per-bound values matching the source constants exactly:
  `P2_SWEEP_MAX_CYCLES=130`, `P2_SETTLE_TIMEOUT_SMC=200`, `P2_RACE_PULSE_BOUND=200`,
  `race_hyst(40)+P2_RACE_FINAL_MARGIN(20)=60`).
- No merged-evidence collision among the 4 P2 checkers: each emits its own token from its own
  step, with `CHK-NONVAC`/`CHK-TIMEOUT-PATHS` carrying `proves: []` (ordering/structural
  only).
- No blind `Timer`-only wait stands in for a measured event on the P2 proof path: every
  sample is `RisingEdge`-driven per `clk_smc_i`/`tb_dma_gated_clk` period; the only bare
  `Timer(1, ...)` calls are same-edge-alignment bridges to avoid a concurrent-coroutine race
  on one edge, never the checked quantity itself.
- X-awareness: `_sample_bit` raises `AssertionError` on an unresolvable (X/Z) value before any
  compare uses it.
- Regression enrollment confirmed in `hw/sys/smc/dv/testlists/clock.toml`.
- P1/P2 additivity: the P1 flow's 5 evidence tokens (lines 932-1214, byte-for-byte identical
  content to the closed P1 grade's cites, only shifted in wall-clock timestamp) confirm the
  P2 extension — and this round's coverage-artifact fix — did not alter the P1 proof path
  (out of scope for this report; the P1 grade file was not read as authoritative for this P2
  round and was not touched).

</details>

## Accepted waivers

| Finding | Rule | Where | Why | Approved by |
|---|---|---|---|---|
| — | — | — | none — 0 findings this round; prior round's ledger was already empty, nothing to carry forward | — |

## Human signoff

- **who:** minshaoho
- **when:** 2026-08-05T17:21:00+08:00
- **decision:** Done — evidence accepted by owner signoff. 4/4 PROVEN, recommendation
  `EVIDENCE-CLOSED-AWAITING-SIGNOFF`. `FIND-001` from the prior round is closed (coverage
  artifact now produced and satisfied). This P2 grade is independent of, and does not alter,
  the separately-closed P1 grade for the same anchor.
- **note:** Per user instruction, signoff recorded automatically since all four checkers
  graded PROVEN with zero open findings.
