---
schema: dv-quality/v1
artifact: testcase-grade
testcase: smc_zeroer_cg_indep_test
ip: SMC_CLOCK_GATING
anchor: smc_zeroer_cg_indep_test
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
card_sha256: 46ad998bc85c45be9ff0180d25267976c65047f0d983dec945caf0e9eebee833
card_revision: 1
card_path: hw/sys/smc/dv/tb/SMC_CLOCK_GATING_VPLAN_DETAIL.md
testcase_plan:
  path: hw/sys/smc/dv/tb/SMC_CLOCK_GATING_TESTCASE_PLAN.md
  plan_revision: 1
  testcase_revision: 1
  testcase_record_sha256: af246ccaaec1265a4b108f970b90726c58b7506ea70db7292939077909a69da0
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
- path: hw/sys/smc/dv/build/runs/20260805_055443__verilator__smc_zeroer_cg_indep_test/smc_zeroer_cg_indep_test/logs/smc_zeroer_cg_indep_test.log
  sha256: 1c39f29a1c81d83950d23ab4e38423bf62b9dfeceb8b1fd19b0cba178fc8f56a
test_author:
  human_id: minshaoho
  run_id: dv_test_impl-SMC_ZEROER_CG_INDEP_TEST-7731943f-dcb5-4dae-a13c-7e3ea0301648
  model:
    provider: cursor
    family: grok
    version: '4.5'
auditor:
  human_id: minshaoho
  run_id: dv_test_audit-SMC_ZEROER_CG_INDEP_TEST-24e034821e5542e98d84f70c280bbd56
  model:
    provider: cursor
    family: grok
    version: '4.5'
exceptions: []
checkers:
- id: CHK-ZINDEP-DECOUPLE
  checks_steps: [S1, S2]
  proves: [ZEROER-AXICLK-CG, ZEROER-REGCLK-CG]
  covers: [INT-ZEROER-CG-INDEP]
  proof_class: LIVE
  expect_source: 'hw/sys/smc/doc/zeroer.adoc §Clock Domains row "Register Clock … independent of AXI activity"; §Clock Gating formulas axi_clk_enable = disable_cg | zeroer_busy_o | ~rst_ni and reg_clk_enable = disable_cg | register_activity | ~rst_ni (rev 2f40548ea787240680a1c45ab75b8729e9620778)'
  grade: PROVEN
  evidence:
  - token: 'CHK-ZINDEP-DECOUPLE: (S1 axi-active-reg-idle-decoupled) with disable_cg=0 and out of reset, during the axi-active / register-idle window axi_clk toggles every cycle and reg_clk is gated off for the whole window (s1_ok=1 window=39 axi_hits=39 reg_hits=0); (S2 reg-active-axi-idle-decoupled) during the register-active / axi-idle window reg_clk toggles every cycle and axi_clk is gated off for the whole window (s2_ok=1 post_resume_cycles=2 reg_hits=2 axi_hits_all=0)'
    log_sha256: 1c39f29a1c81d83950d23ab4e38423bf62b9dfeceb8b1fd19b0cba178fc8f56a
    line: 394
    seed: 1
    implementation_path: hw/sys/smc/dv/cocotb/seq_lib/smc_zeroer_cg_indep_test_seq.py:399
  lifecycle_results: null
  coverage_results:
  - key: INT-ZEROER-CG-INDEP
    method: DIRECTED
    required_cells: [axi-active-reg-idle-decoupled, reg-active-axi-idle-decoupled]
    achieved_cells: [axi-active-reg-idle-decoupled, reg-active-axi-idle-decoupled]
    random_knobs: []
    resolved_knobs: []
    min_seeds: 1
    actual_seeds: [1]
    required_artifact: null
    coverage_artifacts:
    - hw/sys/smc/dv/build/runs/20260805_055443__verilator__smc_zeroer_cg_indep_test/smc_zeroer_cg_indep_test/logs/smc_zeroer_cg_indep_test.log#1c39f29a1c81d83950d23ab4e38423bf62b9dfeceb8b1fd19b0cba178fc8f56a
    satisfied: true
  linked_issue: null
  finding_ids: []
  remediation: null
- id: CHK-NONVAC
  checks_steps: [S1, S2]
  proves: []
  covers: []
  proof_class: INTEGRITY
  expect_source: approved card ordering contract
  grade: PROVEN
  evidence:
  - token: 'CHK-NONVAC: axi-active-reg-idle-decoupled-observed < reg-active-axi-idle-decoupled-observed < PASS'
    log_sha256: 1c39f29a1c81d83950d23ab4e38423bf62b9dfeceb8b1fd19b0cba178fc8f56a
    line: 395
    seed: 1
    implementation_path: hw/sys/smc/dv/cocotb/seq_lib/smc_zeroer_cg_indep_test_seq.py:419
  lifecycle_results: null
  coverage_results: []
  linked_issue: null
  finding_ids: []
  remediation: null
findings: []
waivers: []
recommendation: EVIDENCE-CLOSED-AWAITING-SIGNOFF
---

# Grade Report — smc_zeroer_cg_indep_test (SMC_ZEROER_CG_INDEP_TEST)

**VERDICT: 2/2 PROVEN — READY** (mode CHECKBOX, entry PASS)

| Mode | Entry gate | Checkers | Findings | Recommendation |
|---|---|---|---|---|
| `CHECKBOX` | ✅ PASS | 2/2 PROVEN | none | ✅ EVIDENCE-CLOSED-AWAITING-SIGNOFF |

> Fresh Skill 2 audit (auditor `run_id` ≠ authoring). Kept log sha256 `1c39f29a…` verified
> via `manifest.py hash-file` (matches invoker digest). Entry PASS: cocotb
> `TESTS=1 PASS=1 FAIL=0 SKIP=0`, final `assert not missing` on both `CHK-*` tokens, zero
> unexplained `ERROR`/`FATAL`/`Traceback`. Card r1 `46ad998b…` matches parent plan record r1
> `af246cca…` (both recomputed), parent `status: approved`. **Force/deposit check: clean** —
> CSR/Zeroer frontdoor AXI + JTAG fabric seed + passive `tb_zeroer_*` observation only (owner
> hard constraint satisfied).

## Your to-do — 0 items (none)

| # | Rank | Item |
|---|---|---|
| — | — | none open |

**Then:** human signoff on this grade → `/dv_peer_audit` re-review for SMC_CLOCK_GATING P1
(INT-ZEROER-CG-INDEP now evidence-closed).

## All checkers

| Checker | Grade | Proof class | Covers | Findings |
|---|---|---|---|---|
| CHK-ZINDEP-DECOUPLE | ✅ PROVEN | LIVE | INT-ZEROER-CG-INDEP | — |
| CHK-NONVAC | ✅ PROVEN | INTEGRITY | — | — |

### Layer 1 structural rule set

| Rule | Result |
|---|---|
| F1 fabricated verdict / backdoor write | ✅ clean — CSR/Zeroer accesses are frontdoor AXI (SEP_IN); fabric seed via JTAG AXI VIP; gated-clock / busy / bus_active observation via passive `assign`s in `tb_top.sv`; **no force/deposit** |
| F2 can't-fail checker | ✅ clean — S1 has reachable `AssertionError` on empty window / `axi_hits != window` / `reg_hits != 0` / missing busy or register-idle; S2 on missing `bus_active`, busy-during-access, resume delta, `reg_hits != post_resume`, `axi_hits_all != 0`; X/Z samples raise |
| E1 skip-to-pass | ✅ clean |
| E2 empty phase | ✅ clean — S1 and S2 each program/stimulus/observe before emitting `CHK-ZINDEP-DECOUPLE` |
| S1 silent fail | ✅ clean — mismatches/timeouts raise `AssertionError` with diagnostic state |
| O1 checker disabled | ✅ clean |
| Phase-S obligations — L1 | ✅ clean — CSR addresses via `smc_addr_map`; timeouts fail; tokens emitted only after asserts; X/Z-aware samples; enrolled in `clock.toml` |
| Phase-S obligations — L2 (needs the card) | ✅ clean — proof fence SETUP→ACTION→RESPONSE→EFFECT→NONVAC ordered; feature_list cells for `INT-ZEROER-CG-INDEP` satisfied; interaction `[MERGED-EVIDENCE]` carve-out recorded (single-feature LIVE remains on axi/reg cards); force-free per card guardrails |

## Evidence appendix

<details>
<summary>Kept log + build identity</summary>

- Log: `hw/sys/smc/dv/build/runs/20260805_055443__verilator__smc_zeroer_cg_indep_test/smc_zeroer_cg_indep_test/logs/smc_zeroer_cg_indep_test.log`
  sha256 `1c39f29a1c81d83950d23ab4e38423bf62b9dfeceb8b1fd19b0cba178fc8f56a`
  (verified via `manifest.py hash-file`; matches invoker-supplied digest)
- `result.json`: `status: PASS`, `return_code: 0`, seed 1, target `default`, simulator `verilator`
  `5.050 2026-07-01`, `target_build.fingerprint: 2c815fa08277`, positive-evidence parser
  (`results_xml` + `log_summary`, both PASS)
- Card: SMC_ZEROER_CG_INDEP_TEST r1 `46ad998bc85c45be9ff0180d25267976c65047f0d983dec945caf0e9eebee833`
  (recomputed match against `SMC_CLOCK_GATING_VPLAN_DETAIL.md`)
- Parent plan record: r1 `af246ccaaec1265a4b108f970b90726c58b7506ea70db7292939077909a69da0` ·
  `plan_revision: 1` · `status: approved` (recomputed match against
  `SMC_CLOCK_GATING_TESTCASE_PLAN.md`)
- Feature list interaction `INT-ZEROER-CG-INDEP`: method `DIRECTED`, required_cells
  `[axi-active-reg-idle-decoupled, reg-active-axi-idle-decoupled]`,
  `coverage_artifact: null` — both cells achieved on this directed run (S1 window=39
  axi_hits=39 reg_hits=0; S2 post_resume_cycles=2 reg_hits=2 axi_hits_all=0)
- Cocotb summary: `TESTS=1 PASS=1 FAIL=0 SKIP=0`; final assertion gate in
  `smc_zeroer_cg_indep_test.py:30-31` checks both CHK tokens landed in `seq.chk_seen`; no
  unexplained `ERROR`/`FATAL`/`Traceback` (only benign cocotb `DeprecationWarning`s)
- Enrolled: `hw/sys/smc/dv/testlists/clock.toml` (`name = "smc_zeroer_cg_indep_test"`)
- Address sourcing: seq imports CSR symbols from `smc_addr_map` (generated `smc_addr.h` /
  `smc_base_config.h`); independently resolved `CLOCK_GATE_CONTROL=0xc0010018`,
  `ZEROER_CG_EN=0x100`, `ZEROER_CTRL_DEST_ADDR=0xc0038200`
- Observation ports `tb_zeroer_cg_en` / `tb_zeroer_gated_{axi,reg}_clk` / `tb_zeroer_busy` /
  `tb_zeroer_bus_active` are passive `assign`s in `tb_top.sv`
- `[MERGED-EVIDENCE]` note: this interaction checker jointly proves ZEROER-AXICLK-CG ×
  ZEROER-REGCLK-CG under asymmetric cells; single-feature LIVE proofs remain on
  `SMC_ZEROER_AXICLK_CG_TEST` / `SMC_ZEROER_REGCLK_CG_TEST` (cross-testcase dependency for
  Skill 3)

</details>

<details>
<summary>Token / step cites (kept log `1c39f29a…`)</summary>

| Checker | Log line | What the log shows | Impl |
|---|---|---|---|
| (setup) | 360 | `STEP S1: disable_cg=0: axi-active (busy) + register-idle → axi_clk every cycle, reg_clk gated off` | seq `:333-337` |
| (fence) | 384 | `FENCE axi-active-reg-idle-decoupled-observed @ 5502ns` | seq `:354` |
| (setup) | 385 | `STEP S2: disable_cg=0: register-active (AXI4-Lite) + axi-idle → reg_clk every cycle, axi_clk gated off` | seq `:376-380` |
| (fence) | 393 | `FENCE reg-active-axi-idle-decoupled-observed @ 5760ns` | seq `:397` |
| CHK-ZINDEP-DECOUPLE | 394 | `s1_ok=1 window=39 axi_hits=39 reg_hits=0` · `s2_ok=1 post_resume_cycles=2 reg_hits=2 axi_hits_all=0` | seq `:399-410` |
| CHK-NONVAC | 395 | ordered fence … `< PASS` | seq `:419-424` |
| (fence) | 396 | `FENCE PASS @ 5760ns` | seq `:425` |

</details>

<details>
<summary>Layer 1 notes</summary>

- Ordered fence axi-active-reg-idle(5502) < reg-active-axi-idle(5760) < PASS(5760): non-empty,
  strictly ordered; `assert_fence_order` (obs_utils) gates the first two terms before
  `CHK-NONVAC` emit; `mark_fence(PASS)` follows.
- Each LIVE FAIL-ON path raises; S1/S2 dual-clock monitors timeout with diagnostics; X/Z on
  either gated clock raises before compare.
- S1 arms only after `busy && !bus_active && !reg_on`, then requires every subsequent busy cycle
  in the window keep `axi_on` and `reg` gated (`window=39` on this seed — non-vacuous).
- S2 asserts axi-idle (`busy` never during `bus_active`) and every-cycle reg enable from resume
  through access clear (`reg_hits == post_resume_cycles`), with `axi_hits_all == 0`.
- No blind `Timer`-only sync standing in for completion: 1 ps `Timer` is delta-cycle sample
  hygiene after `ReadOnly`; completion uses busy/`bus_active` handshakes with bounded timeout.
- Regression enrollment confirmed in `hw/sys/smc/dv/testlists/clock.toml`.
- Card guardrail frontdoor path held: Zeroer start + AXI4-Lite register read + passive clock
  observation; no internal write/force/deposit on busy, register_activity, disable_cg, rst_ni,
  or either gated clock net.
- No prior grade file; `waivers: []` (nothing to carry forward).

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
- **note:** Fresh Skill 2 audit (auditor model `cursor/grok/4.5`, run_id
  `dv_test_audit-SMC_ZEROER_CG_INDEP_TEST-24e034821e5542e98d84f70c280bbd56`, distinct from
  authoring `dv_test_impl-SMC_ZEROER_CG_INDEP_TEST-7731943f-dcb5-4dae-a13c-7e3ea0301648`).
  2/2 PROVEN — recommendation EVIDENCE-CLOSED-AWAITING-SIGNOFF.
