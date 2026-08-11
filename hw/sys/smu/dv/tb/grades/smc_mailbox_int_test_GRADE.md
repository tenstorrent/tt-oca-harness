---
schema: dv-quality/v1
artifact: testcase-grade
testcase: smc_mailbox_int_test
ip: SMU_ALL
anchor: smc_mailbox_int_test
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
card_sha256: b52e48d7d64f14e7927b312abab235923c74daf21d5a0b1692411a704ccbe0bc
card_revision: 18
card_path: hw/sys/smu/dv/tb/SMU_ALL_VPLAN_DETAIL.md
testcase_plan:
  path: hw/sys/smu/dv/tb/SMU_ALL_TESTCASE_PLAN.md
  plan_revision: 18
  testcase_revision: 3
  testcase_record_sha256: 9708455a65d08e9b61262724548aec548e35cceee130bb05bc841288641fff94
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
- path: hw/sys/smu/dv/build/kept_logs/smc_mailbox_int_test.seed1.log
  sha256: a0f50c9c906171c082a3810006942306ae34b618f910524552a2b1844624efbd
test_author:
  human_id: minshaoho
  run_id: dv_test_impl-SMU_ALL_004-r8-20260804T063848
  model:
    provider: cursor
    family: grok
    version: '4.5'
auditor:
  human_id: minshaoho
  run_id: dv_test_audit-SMU_ALL_004-r18-58c8569adafc
  model:
    provider: cursor
    family: grok
    version: '4.5'
exceptions: []
checkers:
- id: CHK-SMC-MBX-IRQ-EXT-S2
  checks_steps:
  - S2
  proves:
  - SMC-MBX-IRQ-EXT
  covers:
  - SMC-MBX-IRQ-EXT.S2
  proof_class: DECODE
  expect_source: pinned SPEC citations on SMC-MBX-IRQ-EXT.S2 in SMU_ALL_SPEC_FEATURE_LIST.md
  grade: PROVEN
  evidence:
  - token: 'CHK-SMC-MBX-IRQ-EXT-S2: PASS (width=32 NUM_MAILBOXES=32 port=ext_mailbox_interrupts baseline=0x0 observed=0x0 checked=0x0)'
    log_sha256: a0f50c9c906171c082a3810006942306ae34b618f910524552a2b1844624efbd
    line: 31
    seed: 1
    implementation_path: hw/sys/smu/dv/cocotb/seq_lib/smc_mailbox_int_test_seq.py:256
  lifecycle_results:
    set:
      token: 'LIFECYCLE CHK-SMC-MBX-IRQ-EXT-S2 set: assert observation for SMC-MBX-IRQ-EXT.S2 (port=ext_mailbox_interrupts baseline_w=32 baseline_val=0x0)'
      line: 27
    observed:
      token: 'LIFECYCLE CHK-SMC-MBX-IRQ-EXT-S2 observed: consumer samples asserted condition for SMC-MBX-IRQ-EXT.S2 (width=32 val=0x0 NUM_MAILBOXES=32)'
      line: 28
    cleared:
      token: 'LIFECYCLE CHK-SMC-MBX-IRQ-EXT-S2 cleared: clear/ack for SMC-MBX-IRQ-EXT.S2 (idle_val=0x0 matches baseline; no force)'
      line: 29
    checked_cleared:
      token: 'LIFECYCLE CHK-SMC-MBX-IRQ-EXT-S2 checked_cleared: readback cleared for SMC-MBX-IRQ-EXT.S2 (width=32 val=0x0)'
      line: 30
    complete: true
  coverage_results:
  - key: SMC-MBX-IRQ-EXT.S2
    method: DIRECTED
    required_cells:
    - width=32
    achieved_cells:
    - width=32
    random_knobs: []
    resolved_knobs: []
    min_seeds: 1
    actual_seeds:
    - 1
    required_artifact: null
    coverage_artifacts:
    - hw/sys/smu/dv/build/kept_logs/smc_mailbox_int_test.seed1.log#a0f50c9c906171c082a3810006942306ae34b618f910524552a2b1844624efbd
    satisfied: true
  linked_issue: null
  finding_ids: []
  remediation: null
- id: CHK-NONVAC
  checks_steps:
  - S1
  - S2
  - S3
  proves: []
  covers: []
  proof_class: INTEGRITY
  expect_source: approved card ordering contract
  grade: PROVEN
  evidence:
  - token: 'CHK-NONVAC: Ordered fence S1<S2<S3<PASS all hold'
    log_sha256: a0f50c9c906171c082a3810006942306ae34b618f910524552a2b1844624efbd
    line: 43
    seed: 1
    implementation_path: hw/sys/smu/dv/cocotb/seq_lib/smc_mailbox_int_test_seq.py:323
  lifecycle_results: null
  coverage_results: []
  linked_issue: null
  finding_ids: []
  remediation: null
- id: CHK-TIMEOUT-PATHS
  checks_steps:
  - S3
  proves: []
  covers: []
  proof_class: INTEGRITY
  expect_source: approved card timeout contract
  grade: PROVEN
  evidence:
  - token: 'CHK-TIMEOUT-PATHS: Finite bound on S3; expiry fails with last-state diagnostics (paths=2 expect=2 bound=2000)'
    log_sha256: a0f50c9c906171c082a3810006942306ae34b618f910524552a2b1844624efbd
    line: 38
    seed: 1
    implementation_path: hw/sys/smu/dv/cocotb/seq_lib/smc_mailbox_int_test_seq.py:289
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
content_sha256: c55aedc2b80aa53242a4b37d65aabe092c8700c29ae821d0df1ce761c1e09a06
---

# Grade Report — smc_mailbox_int_test (SMU_ALL_004)

**VERDICT: 3/3 PROVEN — READY** (mode CHECKBOX, entry PASS)

| Mode | Entry gate | Checkers | Findings | Recommendation |
|---|---|---|---|---|
| `CHECKBOX` | ✅ PASS | 3/3 PROVEN | none | ✅ EVIDENCE-CLOSED-AWAITING-SIGNOFF |

> Entry PASS on kept log `a0f50c9c…` (run `20260804_063848`, byte-identical). Parent plan r18 hash `9708455a…` matches card r8→r18 `derived_from`; OWNS scope is SMC-MBX-IRQ-EXT.S2 only (CHANNELS/EXT.S1 out of contract). All three checkers PROVEN with no open findings.

## DELTA (re-audit vs prior grade)

| Item | Prior (`dv_test_audit-SMU_ALL_004-r8-c4e91a72-8b3d-4f6a-9e21-5d0a7c8b4f13`, card r8) | This audit (`dv_test_audit-SMU_ALL_004-r18-58c8569adafc`, card r18) |
|---|---|---|
| Verdict | 3/3 PROVEN — READY | 3/3 PROVEN — READY |
| Card hash | `f670f76181726330279f56dc04dc653ae5a882cc3531164ebf572168d950d862` (STALE vs plan r18) | `b52e48d7d64f14e7927b312abab235923c74daf21d5a0b1692411a704ccbe0bc` (current) |
| Plan revision | 8 | 18 |
| Checkers / OWNS | unchanged | unchanged — all 3 tokens re-verified on same kept log |
| Kept log | `a0f50c9c906171c082a3810006942306ae34b618f910524552a2b1844624efbd` | `a0f50c9c906171c082a3810006942306ae34b618f910524552a2b1844624efbd` (unchanged) |
| Findings | none open | none open |
| Waivers carried | none signed | none |
| Signoff | prior `2026-08-05T17:16:48+08:00` | renewed `2026-08-05T18:14:08+08:00` (standing order) |

## Your to-do — none

**SIGNOFF RECORDED** — see ## Human signoff below.

**Then:** `/dv_peer_audit` on SMU_ALL when all seven r18 grades are filed.

## All checkers

| Checker | Grade | Proof class | Covers |
|---|---|---|---|
| CHK-SMC-MBX-IRQ-EXT-S2 | ✅ PROVEN | DECODE | SMC-MBX-IRQ-EXT.S2 |
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

- Log: `hw/sys/smu/dv/build/kept_logs/smc_mailbox_int_test.seed1.log` sha256 `a0f50c9c906171c082a3810006942306ae34b618f910524552a2b1844624efbd` (byte-identical to run `20260804_063848__verilator__smc_mailbox_int_test` sim log)
- Seed: 1 · simulator: verilator 5.050 · target: `default` · model_fingerprint: `48f5d6b1d3f2`
- Card: SMU_ALL_004 r18 `b52e48d7d64f14e7927b312abab235923c74daf21d5a0b1692411a704ccbe0bc` (recomputed match; `current: true` / `approved`)
- Parent plan record: r3 `9708455a65d08e9b61262724548aec548e35cceee130bb05bc841288641fff94` · `plan_revision: 8` · `parent_approved: true` (recomputed match)
- Feature list: `SMC-MBX-IRQ-EXT.S2` method DIRECTED · required_cells `[width=32]` · `coverage_artifact: null`
- Cocotb summary L61: `TESTS=1 PASS=1 FAIL=0 SKIP=0`; scoreboard final gate L52 (`3 check(s) passed with zero errors`); no unexplained ERROR/FATAL/Traceback
- Enrolled: `hw/sys/smu/dv/testlists/smc.toml` + `all.toml` → `smc_mailbox_int_test`
- Contract scope: OWNS SMC-MBX-IRQ-EXT.S2 (+ CHK-NONVAC, CHK-TIMEOUT-PATHS); CHANNELS/EXT.S1 owned by SMU_ALL_008 — not demanded here
</details>

<details>
<summary>PROVEN token cites</summary>

| Checker | Line | Token (abbrev) | Impl |
|---|---|---|---|
| CHK-SMC-MBX-IRQ-EXT-S2 | 31 | `CHK-SMC-MBX-IRQ-EXT-S2: PASS (width=32 NUM_MAILBOXES=32 …)` + lifecycle L27–30 | `smc_mailbox_int_test_seq.py:256` |
| CHK-TIMEOUT-PATHS | 38 | `CHK-TIMEOUT-PATHS: … (paths=2 expect=2 bound=2000)` + TIMEOUT-PATH L36–37 | `:289` |
| CHK-NONVAC | 43 | `CHK-NONVAC: Ordered fence S1<S2<S3<PASS all hold` | `:323` |
</details>

<details>
<summary>Layer 1 / Layer 2 notes (no open F/E/S)</summary>

- Ordered fence S1 SETUP (primary release + baseline) → S2 ACTION/RESPONSE/EFFECT (passive `ext_mailbox_interrupts` width DECODE) → S3 timeout inventory → PASS: non-empty, ordered, AssertionError-gated.
- Expected width `NUM_MAILBOXES=32` is SPEC-cited (`SMU_SPEC.md` SMC mailboxes = 32), independent of the DUT sample; observed width comes from `signal.n_bits` / `len(signal)` with X/Z rejected.
- FAIL-ON paths: missing port, width ≠ 32, idle drift vs baseline (force/deposit tell), lifecycle order/missing leg, timeout expiry with last-state, NONVAC order/positive-delta mismatch, scoreboard `expect_eq` mismatch.
- Lifecycle legs `set → observed → cleared → checked_cleared` all present and ordered for CHK-SMC-MBX-IRQ-EXT-S2; coverage cell `width=32` logged at L26 and achieved.
- Timeout paths: `s1_primary_release` and `s2_width_sample` each log `bound=2000` + last-state; expiry raises `AssertionError`.
- `+skip_fuse_sense` / ROM backdoor appear only in the sim trailer (bring-up); not on the EXT.S2 DECODE proof path. No force/deposit on `ext_mailbox_interrupts`.
- No merged-evidence collision: feature token is independent of integrity tokens; CHANNELS/EXT.S1 not claimed.
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
