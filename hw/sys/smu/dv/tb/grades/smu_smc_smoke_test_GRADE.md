---
schema: dv-quality/v1
artifact: testcase-grade
testcase: smu_smc_smoke_test
ip: SMU_ALL
anchor: smu_smc_smoke_test
mode: CHECKBOX
no_contract_reason: null
entry_status: PASS
repository_revision: e02d5a97ba46d97eb4469041e115efca949f0184
spec:
- path: hw/sys/smu/doc/SMU_SPEC.md
  revision: 88ddf2482d1e542c0801722975e1f4171907b4fcb68cb511574a88ea9efe88c9
- path: hw/sys/smu/doc/port_table.adoc
  revision: 2f40548ea787240680a1c45ab75b8729e9620778
- path: hw/sys/smc/doc/index.adoc
  revision: 1e98bd45a59ae32ca1bb4715a963b721e26aaf3b
- path: hw/sys/smc/doc/overview.adoc
  revision: 2f40548ea787240680a1c45ab75b8729e9620778
- path: hw/sys/smc/doc/fabric.adoc
  revision: ffc8cdcc349e1e01a2b970442a01070b1c62c0d7
- path: hw/sys/smc/doc/port_table.adoc
  revision: 2f40548ea787240680a1c45ab75b8729e9620778
- path: hw/sys/smc/doc/cpu.adoc
  revision: 2f40548ea787240680a1c45ab75b8729e9620778
- path: hw/sys/smc/doc/clk_rst.adoc
  revision: 2f40548ea787240680a1c45ab75b8729e9620778
- path: hw/sys/smc/doc/interrupts.adoc
  revision: 2f40548ea787240680a1c45ab75b8729e9620778
- path: hw/sys/smc/doc/memmap.adoc
  revision: 2f40548ea787240680a1c45ab75b8729e9620778
- path: hw/sys/smc/doc/periphs.adoc
  revision: ffc8cdcc349e1e01a2b970442a01070b1c62c0d7
- path: hw/sys/smc/doc/dma.adoc
  revision: e2aae39953bb8001c7c20e3afd3956e68c22440c
- path: hw/sys/smc/doc/rom.adoc
  revision: df9e3efe4c8a68f95acb339d0aaf9c9f3f90ab4d
- path: hw/sys/sep/doc/index.adoc
  revision: 2f40548ea787240680a1c45ab75b8729e9620778
- path: hw/sys/sep/doc/introduction.adoc
  revision: 2f40548ea787240680a1c45ab75b8729e9620778
- path: hw/sys/sep/doc/overview.adoc
  revision: 2f40548ea787240680a1c45ab75b8729e9620778
- path: hw/sys/sep/doc/fabric.adoc
  revision: 2f40548ea787240680a1c45ab75b8729e9620778
- path: hw/sys/sep/doc/cpu.adoc
  revision: 2f40548ea787240680a1c45ab75b8729e9620778
- path: hw/sys/sep/doc/crypto.adoc
  revision: 2f40548ea787240680a1c45ab75b8729e9620778
- path: hw/sys/sep/doc/periphs.adoc
  revision: 2f40548ea787240680a1c45ab75b8729e9620778
- path: hw/sys/sep/doc/memory_map.adoc
  revision: 2f40548ea787240680a1c45ab75b8729e9620778
- path: hw/sys/sep/doc/port_table.adoc
  revision: 2f40548ea787240680a1c45ab75b8729e9620778
- path: hw/sys/sep/doc/lifecycle_controller.adoc
  revision: 2f40548ea787240680a1c45ab75b8729e9620778
- path: hw/sys/sep/doc/security_disable.adoc
  revision: 2f40548ea787240680a1c45ab75b8729e9620778
- path: hw/sys/sep/doc/test_mode.adoc
  revision: 2f40548ea787240680a1c45ab75b8729e9620778
- path: hw/sys/sep/doc/token_processing.adoc
  revision: 2f40548ea787240680a1c45ab75b8729e9620778
- path: hw/sys/dtp/doc/index.adoc
  revision: ffc8cdcc349e1e01a2b970442a01070b1c62c0d7
- path: hw/sys/dtp/doc/overview.adoc
  revision: 2f40548ea787240680a1c45ab75b8729e9620778
- path: hw/sys/dtp/doc/jtag.adoc
  revision: 2f40548ea787240680a1c45ab75b8729e9620778
- path: hw/sys/dtp/doc/clock_stop.adoc
  revision: 2f40548ea787240680a1c45ab75b8729e9620778
- path: hw/sys/dtp/doc/port_table.adoc
  revision: 2f40548ea787240680a1c45ab75b8729e9620778
card_sha256: 22defe13f9b110094dfd9fddf430e179cc1f95d383723f78c89facf98d8812df
card_revision: 18
card_path: hw/sys/smu/dv/tb/SMU_ALL_VPLAN_DETAIL.md
testcase_plan:
  path: hw/sys/smu/dv/tb/SMU_ALL_TESTCASE_PLAN.md
  plan_revision: 18
  testcase_revision: 3
  testcase_record_sha256: 5e984fcfcb941c7eccfa5a9a0f2c78adc1006e1becc960317d9d802fe682b024
  parent_approved: true
evidence_class: frontdoor-func
closure_tier: B
quality_policy:
  path: hw/sys/smu/dv/tb/SMU_ALL_QUALITY_POLICY.md
  revision: 936b77700909a93bb122f9fb124a3ffb6f5dac5f508c623c5950285a5cefb79a
build_config: default
simulator: verilator
simulator_version: 5.050 2026-07-01 rev v5.050 (mod)
compile_target: default
model_fingerprint: 48f5d6b1d3f2
compile_inputs_sha256: null
seeds:
- 1
logs:
- path: hw/sys/smu/dv/build/kept_logs/smu_smc_smoke_test.seed1.log
  sha256: b575348c09fe1b2170415ff48e83f6f69f1992bbb288be1ecac86fb4316318d5
test_author:
  human_id: minshaoho
  run_id: dv_test_impl-SMU_ALL_003-remediate-8c79fce8
  model:
    provider: cursor
    family: grok
    version: '4.5'
auditor:
  human_id: minshaoho
  run_id: dv_test_audit-SMU_ALL_003-r18-250948484e4b
  model:
    provider: cursor
    family: grok
    version: '4.5'
exceptions: []
checkers:
- id: CHK-SMC-FAB-DUAL-NET-S2
  checks_steps:
  - S2
  proves:
  - SMC-FAB-DUAL-NET
  covers:
  - SMC-FAB-DUAL-NET.S2
  proof_class: CONNECTIVITY
  expect_source: pinned SPEC citations on SMC-FAB-DUAL-NET.S2 in SMU_ALL_SPEC_FEATURE_LIST.md
  grade: PROVEN
  evidence:
  - token: 'CHK-SMC-FAB-DUAL-NET-S2: PASS (net=AXI4-Lite dest=local_peripheral=gpio_req_o(pack=111) dest=config_register=smc_base_config_req_o(pack=147) cfg_rst=1 per_rst=1)'
    log_sha256: b575348c09fe1b2170415ff48e83f6f69f1992bbb288be1ecac86fb4316318d5
    line: 35
    seed: 1
    implementation_path: hw/sys/smu/dv/cocotb/seq_lib/smu_smc_smoke_test_seq.py:396
  lifecycle_results: null
  coverage_results:
  - key: SMC-FAB-DUAL-NET.S2
    method: DIRECTED
    required_cells:
    - dest=local_peripheral
    - dest=config_register
    achieved_cells:
    - dest=local_peripheral
    - dest=config_register
    random_knobs: []
    resolved_knobs: []
    min_seeds: 1
    actual_seeds:
    - 1
    required_artifact: null
    coverage_artifacts:
    - hw/sys/smu/dv/build/kept_logs/smu_smc_smoke_test.seed1.log#b575348c09fe1b2170415ff48e83f6f69f1992bbb288be1ecac86fb4316318d5
    satisfied: true
  linked_issue: null
  finding_ids: []
  remediation: null
- id: CHK-SMC-FAB-DUAL-NET-S3
  checks_steps:
  - S3
  proves:
  - SMC-FAB-DUAL-NET
  covers:
  - SMC-FAB-DUAL-NET.S3
  proof_class: CONNECTIVITY
  expect_source: pinned SPEC citations on SMC-FAB-DUAL-NET.S3 in SMU_ALL_SPEC_FEATURE_LIST.md
  grade: PROVEN
  evidence:
  - token: 'CHK-SMC-FAB-DUAL-NET-S3: PASS (net=AXI4,data=64 (input_axi_req_i packed=254 formula←SPEC addr=32/id=6/user=12) net=AXI4-Lite,data=64 (axil_smc_base_config_req_o packed=147 formula←SPEC addr=32))'
    log_sha256: b575348c09fe1b2170415ff48e83f6f69f1992bbb288be1ecac86fb4316318d5
    line: 47
    seed: 1
    implementation_path: hw/sys/smu/dv/cocotb/seq_lib/smu_smc_smoke_test_seq.py:493
  lifecycle_results: null
  coverage_results:
  - key: SMC-FAB-DUAL-NET.S3
    method: DIRECTED
    required_cells:
    - net=AXI4,data=64
    - net=AXI4-Lite,data=64
    achieved_cells:
    - net=AXI4,data=64
    - net=AXI4-Lite,data=64
    random_knobs: []
    resolved_knobs: []
    min_seeds: 1
    actual_seeds:
    - 1
    required_artifact: null
    coverage_artifacts:
    - hw/sys/smu/dv/build/kept_logs/smu_smc_smoke_test.seed1.log#b575348c09fe1b2170415ff48e83f6f69f1992bbb288be1ecac86fb4316318d5
    satisfied: true
  linked_issue: null
  finding_ids: []
  remediation: null
- id: CHK-NONVAC
  checks_steps:
  - S1
  - S2
  - S3
  - S4
  proves: []
  covers: []
  proof_class: INTEGRITY
  expect_source: approved card ordering contract
  grade: PROVEN
  evidence:
  - token: 'CHK-NONVAC: ordered fence S1<S2<S3<S4<PASS all present'
    log_sha256: b575348c09fe1b2170415ff48e83f6f69f1992bbb288be1ecac86fb4316318d5
    line: 62
    seed: 1
    implementation_path: hw/sys/smu/dv/cocotb/seq_lib/smu_smc_smoke_test_seq.py:568
  lifecycle_results: null
  coverage_results: []
  linked_issue: null
  finding_ids: []
  remediation: null
- id: CHK-TIMEOUT-PATHS
  checks_steps:
  - S4
  proves: []
  covers: []
  proof_class: INTEGRITY
  expect_source: approved card timeout contract
  grade: PROVEN
  evidence:
  - token: 'CHK-TIMEOUT-PATHS: every bounded wait names finite bound, fail-on-expiry path, and last-state diagnostic (paths=2 expect=2 bound=2000)'
    log_sha256: b575348c09fe1b2170415ff48e83f6f69f1992bbb288be1ecac86fb4316318d5
    line: 57
    seed: 1
    implementation_path: hw/sys/smu/dv/cocotb/seq_lib/smu_smc_smoke_test_seq.py:538
  lifecycle_results: null
  coverage_results: []
  linked_issue: null
  finding_ids: []
  remediation: null
findings: []
waivers: []
recommendation: EVIDENCE-CLOSED-AWAITING-SIGNOFF
signed_off_by: minshaoho
signed_off_at: '2026-08-05T18:14:08+08:00'
content_sha256: 6adf161def8140f3efe8c9c9c7384e7b3b9b3b50174a462b78b572ac31f289c3
---

# Grade Report — smu_smc_smoke_test (SMU_ALL_003)

**VERDICT: 4/4 PROVEN — READY** (mode CHECKBOX, entry PASS)

| Mode | Entry gate | Checkers | Findings | Recommendation |
|---|---|---|---|---|
| `CHECKBOX` | ✅ PASS | 4/4 PROVEN | none | ✅ EVIDENCE-CLOSED-AWAITING-SIGNOFF |

> Remediation re-audit on kept log `b575348c…` (run `20260804_054142`). Card r6 / plan r3 hashes match. Prior FIND-001..004 closed: dest-side CONNECTIVITY packing identity, SPEC-width invert for data=64 (no RTL totals as golden), non-tautological scoreboard compares. All four checkers PROVEN at declared CONNECTIVITY / INTEGRITY class.

## DELTA (re-audit vs prior grade)

| Item | Prior (`dv_test_audit-SMU_ALL_003-86824f58-0443-490f-900d-287bc07acc02`, card r6) | This audit (`dv_test_audit-SMU_ALL_003-r18-250948484e4b`, card r18) |
|---|---|---|
| Verdict | 4/4 PROVEN — READY | 4/4 PROVEN — READY |
| Card hash | `b3f504a0350089e1b8867785d30aa618dd4c31a9fc7dcef2192f8ff42ada6380` (STALE vs plan r18) | `22defe13f9b110094dfd9fddf430e179cc1f95d383723f78c89facf98d8812df` (current) |
| Plan revision | 6 | 18 |
| Checkers / OWNS | unchanged | unchanged — all 4 tokens re-verified on same kept log |
| Kept log | `b575348c09fe1b2170415ff48e83f6f69f1992bbb288be1ecac86fb4316318d5` | `b575348c09fe1b2170415ff48e83f6f69f1992bbb288be1ecac86fb4316318d5` (unchanged) |
| Findings | none open | none open |
| Waivers carried | none signed | none |
| Signoff | prior `2026-08-05T17:16:48+08:00` | renewed `2026-08-05T18:14:08+08:00` (standing order) |


## Your to-do — none

**Then:** `/dv_peer_audit` on SMU_ALL when all seven r18 grades are filed.

## All checkers

| Checker | Grade | Proof class | Covers |
|---|---|---|---|
| CHK-SMC-FAB-DUAL-NET-S2 | ✅ PROVEN | CONNECTIVITY | SMC-FAB-DUAL-NET.S2 |
| CHK-SMC-FAB-DUAL-NET-S3 | ✅ PROVEN | CONNECTIVITY | SMC-FAB-DUAL-NET.S3 |
| CHK-NONVAC | ✅ PROVEN | INTEGRITY | — |
| CHK-TIMEOUT-PATHS | ✅ PROVEN | INTEGRITY | — |

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

- Log: `hw/sys/smu/dv/build/kept_logs/smu_smc_smoke_test.seed1.log` sha256 `b575348c09fe1b2170415ff48e83f6f69f1992bbb288be1ecac86fb4316318d5` (byte-identical to claimed; run `20260804_054142__verilator__smu_smc_smoke_test`)
- Seed: 1 · simulator: verilator 5.050 · target: `default` · model_fingerprint: `48f5d6b1d3f2`
- Card: SMU_ALL_003 r18 `22defe13f9b110094dfd9fddf430e179cc1f95d383723f78c89facf98d8812df` (current:true recomputed match)
- Parent plan record: r3 `5e984fcfcb941c7eccfa5a9a0f2c78adc1006e1becc960317d9d802fe682b024` · `plan_revision: 6` · `parent_approved: true` (current:true recomputed match; card `derived_from.testcase_record_sha256` agrees)
- Feature list: `SMC-FAB-DUAL-NET.S2` required_cells `[dest=local_peripheral, dest=config_register]`; `SMC-FAB-DUAL-NET.S3` `[net=AXI4,data=64, net=AXI4-Lite,data=64]`; `coverage_artifact: null`; both `requires: CONNECTIVITY`
- Cocotb summary L83: `TESTS=1 PASS=1 FAIL=0 SKIP=0`; scoreboard final gate + FEATURE PROVEN lines L66–69 / EVIDENCE_SUMMARY L74 executed; no unexplained ERROR/FATAL/Traceback
- Enrolled: `hw/sys/smu/dv/testlists/smc.toml` (+ `all.toml` / wrapper shared name) → `smu_smc_smoke_test`
- Bring-up trailer shows `+skip_fuse_sense` / ROM backdoor; not on the dual-net hierarchical observe path; checkers claim CONNECTIVITY not LIVE

</details>

<details>
<summary>Token / step cites (kept log `b575348c…`)</summary>

| Checker | Line | What the log shows | Impl |
|---|---|---|---|
| (setup) | 29–30 | `STEP S1` + dual-net hierarchy baseline | seq `:272` |
| CHK-SMC-FAB-DUAL-NET-S2 | 31–44 | DEST cells + `PASS (… gpio_req_o pack=111 … smc_base_config_req_o pack=147 …)` + numeric CHECK PASS | seq `:396` |
| CHK-SMC-FAB-DUAL-NET-S3 | 45–53 | COVERAGE `data=64` + `PASS (… data=64 … formula←SPEC …)` + data-bus width CHECK PASS 64 | seq `:493` |
| CHK-TIMEOUT-PATHS | 54–60 | TIMEOUT-PATH ×2 + `paths=2 expect=2 bound=2000` | seq `:538` |
| CHK-NONVAC | 61–65 | ordered fence S1&lt;S2&lt;S3&lt;S4&lt;PASS + positive-delta CHECK PASS 4 | seq `:568` |

</details>

<details>
<summary>Layer 1 / proof-fence notes</summary>

- Ordered fence S1 SETUP → S2 dest-attachment observe → S3 data-width derive → S4 timeout inventory → PASS: non-empty, AssertionError-gated.
- S2 FAIL-ON: missing dest ports, X/Z, rst/settle timeout, pack ≠ SPEC Lite expect, dest_cells≠2; scoreboard compares pack widths and cell count (not True/True).
- S3 FAIL-ON: unobservable packed buses, non-invertible packing, derived data≠64, Lite64 collapsed to 32-bit pack; scoreboard compares derived data widths to SPEC 64.
- Timeout paths use `BOUND_CYCLES=2000` with expiry → AssertionError + last-state; inventory expects exactly 2 paths.
- NONVAC timestamp order S1&lt;S2&lt;S3&lt;S4&lt;PASS can fail on missing/out-of-order terms; scoreboard compares positive-delta count to 4.
- No force/deposit on the proof path; no merged-evidence collision between S2 and S3 tokens (distinct dest vs net cells).
- Card/plan authorize hierarchical CONNECTIVITY (not LIVE); FL required_cells walked on the remediated body.

</details>

<details>
<summary>Prior finding closure verification</summary>

- FIND-001: S2 observes Traffic-Subordinates destinations `gpio_req_o` (local_peripheral) and `smc_base_config_req_o` (config_register) with AXI4-Lite packing identity; log L33–35; FL cells achieved.
- FIND-002: no RTL `254`/`147` goldens; invert uses SPEC addr/id/user (+ AMBA/pulp packing reference); compare target is SPEC data=64 (seq `:443–505`, log L47–51). Skeptical re-check: independent enough for PROVEN — see DELTA note.
- FIND-003: all `sb.expect_eq` calls use numeric observed/expected pairs (seq `:397–414`, `:494–505`, `:539–544`, `:569–574`); log shows non-tautological CHECK PASS lines.
- FIND-004: evidence and scoreboard assert `data=64` derived widths, not packed-total masquerade (log L47–51).

</details>

## Accepted waivers

| Finding | Rule | Where | Why | Approved by |
|---|---|---|---|---|
| — | — | — | none | — |

## Human signoff

- **signed_off_by:** minshaoho
- **signed_off_at:** 2026-08-05T18:14:08+08:00
- **decision:** accept evidence-closed grade (Done)
- **note:** Re-audit for plan/card artifact_revision 18 mechanical hash bump; OWNS/checkers unchanged; same kept log; standing-order signoff renewed.
