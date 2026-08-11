---
schema: dv-quality/v1
artifact: testcase-grade
testcase: smc_zeroer_regclk_cg_test
ip: SMC_CLOCK_GATING
anchor: smc_zeroer_regclk_cg_test
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
card_sha256: 47e3381f135bfb76907ef06f89d4eb70bb30c6c7bb0232bb56dee36072ecbd1b
card_revision: 1
card_path: hw/sys/smc/dv/tb/SMC_CLOCK_GATING_VPLAN_DETAIL.md
testcase_plan:
  path: hw/sys/smc/dv/tb/SMC_CLOCK_GATING_TESTCASE_PLAN.md
  plan_revision: 1
  testcase_revision: 1
  testcase_record_sha256: 69210848a8214010c3e43e43a032d700ee9d0061b6bb8512de2c73b83db44b42
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
- path: hw/sys/smc/dv/build/runs/20260805_040056__verilator__smc_zeroer_regclk_cg_test/smc_zeroer_regclk_cg_test/logs/smc_zeroer_regclk_cg_test.log
  sha256: 9ae9ce78cb840329b87af06f2af9463aab869def1c155b779d3b87d3e7882a27
test_author:
  human_id: minshaoho
  run_id: dv_test_impl-SMC_ZEROER_REGCLK_CG_TEST-95afef5e-2325-4e52-878d-d6236ae7bfa7
  model:
    provider: cursor
    family: grok
    version: '4.5'
auditor:
  human_id: minshaoho
  run_id: dv_test_audit-SMC_ZEROER_REGCLK_CG_TEST-b7e506bf-b720-4295-82e9-dca594294dbf
  model:
    provider: cursor
    family: grok
    version: '4.5'
exceptions: []
checkers:
- id: CHK-ZREG-GATE-OFF-IDLE
  checks_steps: [S1]
  proves: [ZEROER-REGCLK-CG]
  covers: [ZEROER-REGCLK-CG.S1]
  proof_class: LIVE
  expect_source: 'hw/sys/smc/doc/zeroer.adoc §Clock Gating, table "Clock Gating Control", row "Register Clock" (rev 2f40548ea787240680a1c45ab75b8729e9620778)'
  grade: PROVEN
  evidence:
  - token: 'CHK-ZREG-GATE-OFF-IDLE: gate_off_within_1cyc=1 gate_off_latency=0 zero_toggles_idle=16'
    log_sha256: 9ae9ce78cb840329b87af06f2af9463aab869def1c155b779d3b87d3e7882a27
    line: 331
    seed: 1
    implementation_path: hw/sys/smc/dv/cocotb/seq_lib/smc_zeroer_regclk_cg_test_seq.py:144
  lifecycle_results: null
  coverage_results:
  - key: ZEROER-REGCLK-CG.S1
    method: DIRECTED
    required_cells: [regclk_gated_off_idle]
    achieved_cells: [regclk_gated_off_idle]
    random_knobs: []
    resolved_knobs: []
    min_seeds: 1
    actual_seeds: [1]
    required_artifact: null
    coverage_artifacts:
    - hw/sys/smc/dv/build/runs/20260805_040056__verilator__smc_zeroer_regclk_cg_test/smc_zeroer_regclk_cg_test/logs/smc_zeroer_regclk_cg_test.log#9ae9ce78cb840329b87af06f2af9463aab869def1c155b779d3b87d3e7882a27
    satisfied: true
  linked_issue: null
  finding_ids: []
  remediation: null
- id: CHK-ZREG-ACTIVITY-ENABLE
  checks_steps: [S2]
  proves: [ZEROER-REGCLK-CG]
  covers: [ZEROER-REGCLK-CG.S2]
  proof_class: LIVE
  expect_source: 'hw/sys/smc/doc/zeroer.adoc §Clock Gating, table "Clock Gating Control", row "Register Clock" (rev 2f40548ea787240680a1c45ab75b8729e9620778)'
  grade: PROVEN
  evidence:
  - token: 'CHK-ZREG-ACTIVITY-ENABLE: resume_within_1cyc=1 resume_at=1 toggles_every_cycle=1 enabled_hits=2 post_resume_cycles=2 stimulus=axi4lite_read_zeroer'
    log_sha256: 9ae9ce78cb840329b87af06f2af9463aab869def1c155b779d3b87d3e7882a27
    line: 343
    seed: 1
    implementation_path: hw/sys/smc/dv/cocotb/seq_lib/smc_zeroer_regclk_cg_test_seq.py:168
  lifecycle_results: null
  coverage_results:
  - key: ZEROER-REGCLK-CG.S2
    method: DIRECTED
    required_cells: [regclk_enabled_on_register_activity]
    achieved_cells: [regclk_enabled_on_register_activity]
    random_knobs: []
    resolved_knobs: []
    min_seeds: 1
    actual_seeds: [1]
    required_artifact: null
    coverage_artifacts:
    - hw/sys/smc/dv/build/runs/20260805_040056__verilator__smc_zeroer_regclk_cg_test/smc_zeroer_regclk_cg_test/logs/smc_zeroer_regclk_cg_test.log#9ae9ce78cb840329b87af06f2af9463aab869def1c155b779d3b87d3e7882a27
    satisfied: true
  linked_issue: null
  finding_ids: []
  remediation: null
- id: CHK-ZREG-DISABLE-CG
  checks_steps: [S3]
  proves: [ZEROER-REGCLK-CG]
  covers: [ZEROER-REGCLK-CG.S3]
  proof_class: LIVE
  expect_source: 'hw/sys/smc/doc/zeroer.adoc §Clock Gating, table "Clock Gating Control", row "Register Clock" (rev 2f40548ea787240680a1c45ab75b8729e9620778)'
  grade: PROVEN
  evidence:
  - token: 'CHK-ZREG-DISABLE-CG: toggles_every_cycle=1 edges=16 window=16'
    log_sha256: 9ae9ce78cb840329b87af06f2af9463aab869def1c155b779d3b87d3e7882a27
    line: 367
    seed: 1
    implementation_path: hw/sys/smc/dv/cocotb/seq_lib/smc_zeroer_regclk_cg_test_seq.py:199
  lifecycle_results: null
  coverage_results:
  - key: ZEROER-REGCLK-CG.S3
    method: DIRECTED
    required_cells: [regclk_enabled_disable_cg_set]
    achieved_cells: [regclk_enabled_disable_cg_set]
    random_knobs: []
    resolved_knobs: []
    min_seeds: 1
    actual_seeds: [1]
    required_artifact: null
    coverage_artifacts:
    - hw/sys/smc/dv/build/runs/20260805_040056__verilator__smc_zeroer_regclk_cg_test/smc_zeroer_regclk_cg_test/logs/smc_zeroer_regclk_cg_test.log#9ae9ce78cb840329b87af06f2af9463aab869def1c155b779d3b87d3e7882a27
    satisfied: true
  linked_issue: null
  finding_ids: []
  remediation: null
- id: CHK-ZREG-RESET-OVERRIDE
  checks_steps: [S4]
  proves: [ZEROER-REGCLK-CG]
  covers: [ZEROER-REGCLK-CG.S4]
  proof_class: LIVE
  expect_source: 'hw/sys/smc/doc/zeroer.adoc §Clock Gating, table "Clock Gating Control", row "Reset Override" (rev 2f40548ea787240680a1c45ab75b8729e9620778)'
  grade: PROVEN
  evidence:
  - token: 'CHK-ZREG-RESET-OVERRIDE: toggles_during_reset=1 edges=16 window=16'
    log_sha256: 9ae9ce78cb840329b87af06f2af9463aab869def1c155b779d3b87d3e7882a27
    line: 424
    seed: 1
    implementation_path: hw/sys/smc/dv/cocotb/seq_lib/smc_zeroer_regclk_cg_test_seq.py:232
  lifecycle_results: null
  coverage_results:
  - key: ZEROER-REGCLK-CG.S4
    method: DIRECTED
    required_cells: [regclk_enabled_during_reset]
    achieved_cells: [regclk_enabled_during_reset]
    random_knobs: []
    resolved_knobs: []
    min_seeds: 1
    actual_seeds: [1]
    required_artifact: null
    coverage_artifacts:
    - hw/sys/smc/dv/build/runs/20260805_040056__verilator__smc_zeroer_regclk_cg_test/smc_zeroer_regclk_cg_test/logs/smc_zeroer_regclk_cg_test.log#9ae9ce78cb840329b87af06f2af9463aab869def1c155b779d3b87d3e7882a27
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
  - token: 'CHK-NONVAC: idle-gate-off-observed < activity-enable-observed < disable-cg-observed < reset-override-observed < PASS'
    log_sha256: 9ae9ce78cb840329b87af06f2af9463aab869def1c155b779d3b87d3e7882a27
    line: 447
    seed: 1
    implementation_path: hw/sys/smc/dv/cocotb/seq_lib/smc_zeroer_regclk_cg_test_seq.py:255
  lifecycle_results: null
  coverage_results: []
  linked_issue: null
  finding_ids: []
  remediation: null
findings: []
waivers: []
recommendation: EVIDENCE-CLOSED-AWAITING-SIGNOFF
---

# Grade Report — smc_zeroer_regclk_cg_test (SMC_ZEROER_REGCLK_CG_TEST)

**VERDICT: 5/5 PROVEN — READY** (mode CHECKBOX, entry PASS)

| Mode | Entry gate | Checkers | Findings | Recommendation |
|---|---|---|---|---|
| `CHECKBOX` | ✅ PASS | 5/5 PROVEN | none | ✅ EVIDENCE-CLOSED-AWAITING-SIGNOFF |

> Fresh Skill 2 re-audit on rework kept log `9ae9ce78…` (run `20260805_040056`). Prior grade on
> log `4a648b13…` (**1/5 NOT-READY**) is **not** treated as authoritative. Entry PASS:
> cocotb `TESTS=1 PASS=1 FAIL=0 SKIP=0`, final `assert not missing` on all five `CHK-*` tokens,
> zero unexplained `ERROR`/`FATAL`/`Traceback`. Card r1 hash `47e3381f…` matches parent plan
> record r1 hash `69210848…` (both recomputed), parent `status: approved`. **Force/deposit check:
> clean** — CSR frontdoor AXI (SEP_IN) + TB cool-reset pin `rst_cool_ni` + passive
> `tb_zeroer_*` observation only (owner hard constraint satisfied).

## DELTA (re-audit vs prior grade `1/5 NOT-READY` on log `4a648b13…`)

| Prior id | Tag | Status this round | Notes |
|---|---|---|---|
| FIND-001 | `[ADDRESS-FROM-AUTHORITATIVE-MAP]` | CLOSED | Seq imports `CLOCK_GATE_CONTROL` / `ZEROER_CG_EN` / `CG_HYST_*` / `ZEROER_CTRL_DEST_ADDR` from `smc_addr_map` (generated `smc_addr.h` / `smc_base_config.h`); `smc_cg_obs_utils` likewise re-exports from the same map |
| FIND-002 | `[EXACT-EXPECTATION]` | CLOSED | S1 asserts `gate_off_lat <= 1` via `measure_gate_off_latency` then `edges == 0` idle window; S2 asserts `resume delta <= 1` from `tb_zeroer_bus_active` and `enabled_hits == post_resume_cycles` for the access window |
| FIND-003 | `[EXACT-EXPECTATION]` | CLOSED | S3/S4 assert `edges == IDLE_OBSERVE` (16/16); kept log shows exact match |
| FIND-004 | `[EXACT-EXPECTATION]` | CLOSED | Token fields derived from measured comparisons (`int(gate_off_lat <= 1)`, `int(delta <= 1)`, `int(edges == IDLE_OBSERVE)`), not hardcoded `1` |
| CHK-ZREG-GATE-OFF-IDLE | INSUFFICIENT-EVIDENCE → PROVEN | UPGRADED | `gate_off_latency=0` + `zero_toggles_idle=16` on new log |
| CHK-ZREG-ACTIVITY-ENABLE | INSUFFICIENT-EVIDENCE → PROVEN | UPGRADED | `resume_at=1` + `enabled_hits=2`/`post_resume_cycles=2` |
| CHK-ZREG-DISABLE-CG | INSUFFICIENT-EVIDENCE → PROVEN | UPGRADED | `edges=16 window=16` exact |
| CHK-ZREG-RESET-OVERRIDE | INSUFFICIENT-EVIDENCE → PROVEN | UPGRADED | `edges=16 window=16` during cool reset |
| CHK-NONVAC | stayed PROVEN | unchanged substance | New kept log `9ae9ce78…` |

## Your to-do — 0 items (none)

| # | Rank | Item |
|---|---|---|
| — | — | none open |

**Then:** human signoff on this grade → Skill 3 peer audit when the remaining SMC_CLOCK_GATING anchors close, or continue Skill 2 on still-open anchors.

## All checkers

| Checker | Grade | Proof class | Covers | Findings |
|---|---|---|---|---|
| CHK-ZREG-GATE-OFF-IDLE | ✅ PROVEN | LIVE | ZEROER-REGCLK-CG.S1 | — |
| CHK-ZREG-ACTIVITY-ENABLE | ✅ PROVEN | LIVE | ZEROER-REGCLK-CG.S2 | — |
| CHK-ZREG-DISABLE-CG | ✅ PROVEN | LIVE | ZEROER-REGCLK-CG.S3 | — |
| CHK-ZREG-RESET-OVERRIDE | ✅ PROVEN | LIVE | ZEROER-REGCLK-CG.S4 | — |
| CHK-NONVAC | ✅ PROVEN | INTEGRITY | — | — |

### Layer 1 structural rule set

| Rule | Result |
|---|---|
| F1 fabricated verdict / backdoor write | ✅ clean — CSR/Zeroer accesses are frontdoor AXI (SEP_IN); `rst_cool_ni` is the TB cool-reset stimulus pin; gated-clock / bus_active observation via passive `assign`s in `tb_top.sv`; **no force/deposit** |
| F2 can't-fail checker | ✅ clean — each LIVE step has a reachable `AssertionError` path (`gate_off_lat <= 1`, `edges == 0`, `delta <= 1`, `enabled_hits == post_resume`, `edges == IDLE_OBSERVE`, fence order) |
| E1 skip-to-pass | ✅ clean |
| E2 empty phase | ✅ clean — S1–S4 each program/stimulus/observe before emitting their CHK token |
| S1 silent fail | ✅ clean — mismatches/timeouts raise `AssertionError` with diagnostic state |
| O1 checker disabled | ✅ clean |
| Phase-S obligations — L1 | ✅ clean — addresses via `smc_addr_map`; timeouts fail; tokens conditional on asserts; X/Z-aware samples; enrolled in `clock.toml` |
| Phase-S obligations — L2 (needs the card) | ✅ clean — proof fence SETUP→ACTION→RESPONSE→EFFECT→NONVAC ordered; coverage cells from feature_list satisfied; no merged-evidence collision; force-free per card guardrails |

## Evidence appendix

<details>
<summary>Kept log + build identity</summary>

- Log: `hw/sys/smc/dv/build/runs/20260805_040056__verilator__smc_zeroer_regclk_cg_test/smc_zeroer_regclk_cg_test/logs/smc_zeroer_regclk_cg_test.log`
  sha256 `9ae9ce78cb840329b87af06f2af9463aab869def1c155b779d3b87d3e7882a27`
  (verified via `manifest.py hash-file`; matches invoker-supplied digest)
- `result.json`: `status: PASS`, `return_code: 0`, seed 1, target `default`, simulator `verilator`
  `5.050 2026-07-01`, `target_build.fingerprint: 2c815fa08277`, positive-evidence parser
  (`results_xml` + `log_summary`, both PASS)
- Card: SMC_ZEROER_REGCLK_CG_TEST r1 `47e3381f135bfb76907ef06f89d4eb70bb30c6c7bb0232bb56dee36072ecbd1b`
  (recomputed match against `SMC_CLOCK_GATING_VPLAN_DETAIL.md`)
- Parent plan record: r1 `69210848a8214010c3e43e43a032d700ee9d0061b6bb8512de2c73b83db44b42` ·
  `plan_revision: 1` · `status: approved` (recomputed match against
  `SMC_CLOCK_GATING_TESTCASE_PLAN.md`)
- Feature list: `ZEROER-REGCLK-CG.S1`–`S4` method `DIRECTED`, required_cells
  `[regclk_gated_off_idle]`, `[regclk_enabled_on_register_activity]`,
  `[regclk_enabled_disable_cg_set]`, `[regclk_enabled_during_reset]`,
  `coverage_artifact: null` — all four cells achieved on this directed run
- Cocotb summary L461: `TESTS=1 PASS=1 FAIL=0 SKIP=0`; final assertion gate in
  `smc_zeroer_regclk_cg_test.py:33-34` checks all five CHK tokens landed in `seq.chk_seen`; no
  unexplained `ERROR`/`FATAL`/`Traceback` (only benign cocotb `DeprecationWarning`s)
- Enrolled: `hw/sys/smc/dv/testlists/clock.toml` (`name = "smc_zeroer_regclk_cg_test"`)
- Address sourcing: seq `smc_zeroer_regclk_cg_test_seq.py:26-30` imports from `smc_addr_map`;
  independently resolved `CLOCK_GATE_CONTROL=0xc0010018`, `ZEROER_CG_EN=0x100`,
  `ZEROER_CTRL_DEST_ADDR=0xc0038200` (kept-log AXI traffic)
- Observation ports `tb_zeroer_cg_en` / `tb_zeroer_gated_reg_clk` / `tb_zeroer_busy` /
  `tb_zeroer_bus_active` are passive `assign`s in `tb_top.sv`; `rst_cool_ni` is a TB pin
- SF-004 stimulus choice (any AXI4-Lite access to Zeroer register block) is explicit on the
  approved card observation text; S2 exercises `stimulus=axi4lite_read_zeroer` with
  `tb_zeroer_bus_active` as resume T0

</details>

<details>
<summary>Token / step cites (kept log `9ae9ce78…`)</summary>

| Checker | Log line | What the log shows | Impl |
|---|---|---|---|
| (setup) | 262 | `STEP S1: disable_cg=0, no reg activity, observe reg_clk gates off` | seq `:119` |
| CHK-ZREG-GATE-OFF-IDLE | 331 | `gate_off_within_1cyc=1 gate_off_latency=0 zero_toggles_idle=16` | seq `:144-149` |
| (fence) | 334 | `FENCE idle-gate-off-observed @ 4818ns` | seq `:150` |
| (setup) | 335 | `STEP S2: issue AXI4-Lite read to Zeroer DEST_ADDR; observe reg_clk resume` | seq `:153` |
| CHK-ZREG-ACTIVITY-ENABLE | 343 | `resume_within_1cyc=1 resume_at=1 toggles_every_cycle=1 enabled_hits=2 post_resume_cycles=2 stimulus=axi4lite_read_zeroer` | seq `:168-175` |
| (fence) | 344 | `FENCE activity-enable-observed @ 4884ns` | seq `:176` |
| (setup) | 345 | `STEP S3: zeroer_cg_en=0; idle reg_clk stays enabled` | seq `:189` |
| CHK-ZREG-DISABLE-CG | 367 | `toggles_every_cycle=1 edges=16 window=16` | seq `:199-204` |
| (fence) | 368 | `FENCE disable-cg-observed @ 5358ns` | seq `:205` |
| (setup) | 369 | `STEP S4: re-enable CG, gate off, assert cool reset; reg_clk enabled` | seq `:208` |
| CHK-ZREG-RESET-OVERRIDE | 424 | `toggles_during_reset=1 edges=16 window=16` | seq `:232-237` |
| (fence) | 425 | `FENCE reset-override-observed @ 6066ns` | seq `:238` |
| CHK-NONVAC | 447 | ordered fence … `< PASS` | seq `:255-260` |
| (fence) | 448 | `FENCE PASS @ 6294ns` | seq `:261` |

</details>

<details>
<summary>Layer 1 notes</summary>

- Ordered fence idle-gate-off(4818) < activity-enable(4884) < disable-cg(5358) <
  reset-override(6066) < PASS(6294): non-empty, strictly ordered, `AssertionError`-gated via
  `assert_fence_order` (seq.py:246-254) before PASS.
- Each LIVE FAIL-ON path raises; `measure_gate_off_latency` / access-window / reset-wait /
  `wait_gated_off` timeouts raise with diagnostics.
- S1 positive control: free-run under `disable_cg` (`free == 4`) before establishing idle gating.
- `sample_bit` / gated-clock samples raise on X/Z — satisfies the card's unobservable-sample fail
  clause.
- No blind `Timer`-only sync standing in for completion: S1/S2 use measured latency from idle /
  `bus_active`; S3/S4 measure over `IDLE_OBSERVE` SMC cycles via `count_enabled_at_smc_rise`.
- Regression enrollment confirmed in `hw/sys/smc/dv/testlists/clock.toml`.
- No merged-evidence collision: each LIVE checker emits its own token; `CHK-NONVAC` is pure
  ordering (`proves: []`) and substitutes for no feature proof.
- Card guardrail frontdoor path held: AXI4-Lite programming/access + passive clock observation;
  cool-reset assertion is TB pin stimulus, not an internal force on the gated clock net.
- Prior FIND-001..004 closed by rework wave; no unsigned waivers to carry forward (`waivers: []`).

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
- **note:** Fresh Skill 2 re-audit (auditor model `cursor/grok/4.5`, run_id
  `dv_test_audit-SMC_ZEROER_REGCLK_CG_TEST-b7e506bf-b720-4295-82e9-dca594294dbf`, distinct from
  authoring `dv_test_impl-SMC_ZEROER_REGCLK_CG_TEST-95afef5e-2325-4e52-878d-d6236ae7bfa7` and
  prior auditor `…70b2f9b7…`). 5/5 PROVEN — recommendation
  EVIDENCE-CLOSED-AWAITING-SIGNOFF.
