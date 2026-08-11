---
schema: dv-quality/v1
artifact: testcase-grade
testcase: smu_dtp_bsr_extest_loopback_test
ip: SMU_ENROLLED_RESIDUAL
anchor: null
mode: NO-CHECKBOX
no_contract_reason: NO-PLAN-ENTRY
entry_status: NOT-EVALUATED
repository_revision: 2ecc7b227e3926b253c65b5aac21239eec24ba5f
spec: []
card_sha256: null
card_revision: null
card_path: null
testcase_plan:
  path: hw/sys/smu/dv/tb/SMU_ALL_TESTCASE_PLAN.md
  plan_revision: null
  testcase_revision: null
  testcase_record_sha256: null
  parent_approved: null
evidence_class: null
closure_tier: null
quality_policy:
  path: hw/sys/smu/dv/tb/SMU_ALL_QUALITY_POLICY.md
  revision: 936b77700909a93bb122f9fb124a3ffb6f5dac5f508c623c5950285a5cefb79a
build_config: default
simulator: verilator
simulator_version: 5.050 2026-07-01
compile_target: default
model_fingerprint: 48f5d6b1d3f2
compile_inputs_sha256: null
seeds:
- 1
logs:
- path: hw/sys/smu/dv/build/kept_logs/smu_dtp_bsr_extest_loopback_test.seed1.log
  sha256: b2ee62db2d2f0876f7945e00082fe882c4b1b495890175662342dfc24141305f
test_author:
  human_id: unknown
  run_id: unknown
  model:
    provider: unknown
    family: unknown
    version: unknown
auditor:
  human_id: minshaoho
  run_id: dv_test_audit-smu_dtp_bsr_extest_loopback-L1-20260806-c15
  model:
    provider: cursor
    family: grok
    version: '4.5'
exceptions: []
checkers: []
findings: []
waivers: []
recommendation: NOT-READY
---

# Grade Report — smu_dtp_bsr_extest_loopback_test (NO-PLAN-ENTRY Layer 1)

**VERDICT: 0/0 PROVEN — NOT READY** (mode NO-CHECKBOX, no_contract_reason NO-PLAN-ENTRY)

| Mode | Entry gate | Checkers | Findings | Recommendation |
|---|---|---|---|---|
| `NO-CHECKBOX` | — NOT-EVALUATED | 0/0 PROVEN | none | ⛔ NOT-READY |

> SMU_ALL has an approved plan/cards surface, but this leaf has **no plan record and no
> approved checkbox card**. Layer 1 findings are the entire scope. `NOT-READY` records the
> **absence of a closure claim** (and the plan gap), not a Layer-1 structural defect.
> TB BSR loopback is a declared stub (`STUB:DECLARED`); absence of a card declaration is
> already carried by MODE=NO-CHECKBOX and is not double-counted as a finding. LIVE pad-BSR
> proof remains out of scope for this leaf.

## DELTA (re-audit vs prior grade)

| Item | Prior (`b03`, STANDALONE-REQUEST) | This audit (`c15`, log `b2ee62db…`) |
|---|---|---|
| Verdict | 0/0 PROVEN — NOT READY | 0/0 PROVEN — NOT READY |
| `no_contract_reason` | STANDALONE-REQUEST | NO-PLAN-ENTRY |
| Findings | 🟠 1 Major FIND-001 `[BEHAVIORAL-STUB-DECLARED]` | none |
| FIND-001 | open — TB scan loopback undeclared on card | closed — docstring `STUB:DECLARED BSR_TB_SCAN_LOOPBACK` + runtime log L22; evidence_map notes declared stub / pad BSR out of scope; no-card declaration not re-filed under NO-CHECKBOX |
| Kept log | absent in prior report | `b2ee62db2d2f0876f7945e00082fe882c4b1b495890175662342dfc24141305f` seed=1 |
| Waivers carried | none signed | none |

## Your to-do — 0 items (none)

| # | Sev | Item |
|---|---|---|
| — | — | none open |

**Then:** route to `/dv_vplan_gen` so SMU_ALL either allocates this leaf (`augment`, with stub
declared on the card) or the owner retires it; re-invoke `/dv_test_audit` after a card exists
if Layer 2 grading is required. Do not treat `BSR_EXTEST_TDO_MATCH` as LIVE pad-BSR proof.

## All checkers

| Checker | Grade | Proof class | Covers | Findings |
|---|---|---|---|---|
| — | — | — | — | no card checkers (MODE=NO-CHECKBOX) |

### Layer 1 structural rule set

| Rule | Result |
|---|---|
| F1 fabricated verdict / backdoor write | ✅ clean — JTAG IR/DR frontdoor; no TB success writeback |
| F2 can't-fail checker | ✅ clean — nonzero-only patterns; X/Z→0 VIP hazard rejected; DUT decode + captured DR compared |
| E1 skip-to-pass | ✅ clean |
| E2 empty phase | ✅ clean — IR=EXTEST, decode sample, multi-pattern DR shift |
| S1 silent fail | ✅ clean — `_sample` raises on X/Z; `expect_eq` raises on mismatch |
| O1 checker disabled | ✅ clean |
| Phase-S obligations — L1 | ✅ clean — X-aware `_sample`; stub declared; evidence after compares; enrolled in `dtp.toml` / `all.toml` |
| Phase-S obligations — L2 (needs the card) | — not evaluated |

## Evidence appendix

<details>
<summary>Code + kept log (Layer 1 only; no card checkers)</summary>

- Test: `hw/sys/smu/dv/cocotb/tests/smu_dtp_bsr_extest_loopback_test.py`
- TB stub: `hw/sys/smu/dv/tb/tb_top.sv:412-414`
  `jtag_bsr_host_scan_in_i <- jtag_bsr_host_scan_out_o` (compact `DTP_BSR_MODEL_LEN=8`)
- Declaration: docstring `STUB:DECLARED BSR_TB_SCAN_LOOPBACK`; runtime log L22
- Kept log: `hw/sys/smu/dv/build/kept_logs/smu_dtp_bsr_extest_loopback_test.seed1.log`
  sha256 `b2ee62db2d2f0876f7945e00082fe882c4b1b495890175662342dfc24141305f`
- Seed: 1 · simulator: verilator 5.050 · run
  `20260806_081246__verilator__smu_dtp_bsr_extest_loopback_test`
- Evidence: L23–27 BSR_EXTEST_DECODE; L28–57 BSR_EXTEST_TDO_MATCH ×6 patterns;
  L59 FEATURE PROVEN CHK-BSR-EXTEST; L71–73 cocotb PASS
- Final gate: `prove_mapped_features` + scoreboard `check_phase` (7 checks, zero errors);
  no unexplained ERROR/FATAL/Traceback
- Enrollment: `hw/sys/smu/dv/testlists/dtp.toml`, `all.toml`; absent from
  `SMU_ALL_TESTCASE_PLAN.md` / `SMU_ALL_VPLAN_DETAIL.md`

</details>

## Not concluded

- Whether EXTEST BSR loopback is the milestone-required property (O2) — Skill 3.
- Completeness against SMU_ALL feature_list — this leaf is not in the plan denominator.
- Any LIVE pad-BSR / SEP STAP closure claim — stubbed path; MODE=NO-CHECKBOX forbids inventing checkers.

## Accepted waivers

| Finding | Rule | Where | Why | Approved by |
|---|---|---|---|---|
| — | — | — | none | — |
