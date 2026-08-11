---
schema: dv-quality/v1
artifact: testcase-grade
testcase: smu_xtrig_ctm_illegal_phase_test
ip: SMU_ENROLLED_RESIDUAL
anchor: null
mode: NO-CHECKBOX
no_contract_reason: STANDALONE-REQUEST
entry_status: NOT-EVALUATED
repository_revision: 2ecc7b227e3926b253c65b5aac21239eec24ba5f
spec: []
card_sha256: null
card_revision: null
card_path: null
testcase_plan:
  path: null
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
model_fingerprint: null
compile_inputs_sha256: null
seeds:
- 1
logs:
- path: hw/sys/smu/dv/build/kept_logs/smu_xtrig_ctm_illegal_phase_test.seed1.log
  sha256: 605acf1aa46ad38308016cdcecaeca2fc2e1d72b70255650ccd208f961f43e08
test_author:
  human_id: unknown
  run_id: unknown
  model:
    provider: unknown
    family: unknown
    version: unknown
auditor:
  human_id: minshaoho
  run_id: dv_test_audit-smu_xtrig_ctm_illegal_phase-L1-20260806-e82a1
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

# Grade Report — smu_xtrig_ctm_illegal_phase_test (standalone Layer 1)

**VERDICT: 0/0 PROVEN — NOT READY** (mode NO-CHECKBOX, no_contract_reason STANDALONE-REQUEST)

| Mode | Entry gate | Checkers | Findings | Recommendation |
|---|---|---|---|---|
| `NO-CHECKBOX` | — NOT-EVALUATED | 0/0 PROVEN | none | ⛔ NOT-READY |

> No approved checkbox card or parent plan record governs this residual enrolled test. Layer 1
> findings are the entire scope of this report. `NOT-READY` records the **absence of a closure
> claim**, not a defect in the test by itself.

## DELTA (re-audit vs prior grade)

| Item | Prior (`…-cc4475`, log `79b58f0c…`) | This audit (`…-e82a1`, log `605acf1a…`) |
|---|---|---|
| Verdict | 0/0 PROVEN — NOT READY | 0/0 PROVEN — NOT READY |
| FIND-001 `[NO-FABRICATED-VERDICT]` | open Blocking — FEATURE PROVEN / FCOV `smc_bits_clean` without SMC measure | closed — evidence-map expect rewritten to DTP[9:2] abort/double-req; `smc_bits_clean` removed from leaf `TEST_FCOV_HITS` |
| FIND-002 `[EVIDENCE-TOKEN-CONDITIONAL]` | open Major — `XT_ILLEGAL_PHASE` after DTP-only equals vs "illegal order ignored" | closed — mapped expect now matches the three DTP[9:2] `expect_eq` checks |
| Kept log | `79b58f0c…` (pre-remediation expect / FCOV) | `605acf1a…` seed=1 · cocotb PASS · 3 checks · FCOV `illegal_phase` only |
| Waivers carried | none signed | none |

## Your to-do — 0 items (none)

| # | Sev | Item |
|---|---|---|
| — | — | none open |

**Then:** re-invoke `/dv_test_audit` only if the leaf changes; Layer 2 grading needs an approved card (not invented here).

## All checkers

| Checker | Grade | Proof class | Covers | Findings |
|---|---|---|---|---|
| — | — | — | — | no card checkers (MODE=NO-CHECKBOX) |

### Layer 1 structural rule set

| Rule | Result |
|---|---|
| F1 fabricated verdict / backdoor write | ✅ clean — product pins only; mapped expect matches measured DTP follow-through; no Force |
| F2 can't-fail checker | ✅ clean — DTP[9:2] pattern expects can fail independently |
| E1 skip-to-pass | ✅ clean |
| E2 empty phase | ✅ clean — abort + double-req sequences with settles and compares |
| S1 silent fail | ✅ clean — `sb.expect_eq` raises; `_bits` raises on X/Z |
| O1 checker disabled | ✅ clean |
| Phase-S obligations — L1 | ✅ clean — X-aware `_bits`; RisingEdge settles; token expect aligned; enrolled in `dtp.toml` / `all.toml` |
| Phase-S obligations — L2 (needs the card) | — not evaluated |

## Evidence appendix

<details>
<summary>Kept log + code proof-path notes</summary>

- Log: `hw/sys/smu/dv/build/kept_logs/smu_xtrig_ctm_illegal_phase_test.seed1.log` sha256 `605acf1aa46ad38308016cdcecaeca2fc2e1d72b70255650ccd208f961f43e08`
- Seed: 1 · simulator: verilator 5.050 · cocotb summary L52: `TESTS=1 PASS=1 FAIL=0 SKIP=0`
- Implementation: `hw/sys/smu/dv/cocotb/tests/smu_xtrig_ctm_illegal_phase_test.py`
- Stimulus: pin-only `xtrig_ctm_dst_req` assert/clear and mid-req pattern switch (no Force)
- Observations: hierarchical `u_dut.dtp_xtrig_ctm_dst_req[9:2]` via X-aware `_bits`
- Checks (log L22–36): abort PAT_A → clear → double-req PAT_B; three `CHECK PASS` + `EVIDENCE: XT_ILLEGAL_PHASE`
- FEATURE PROVEN (log L38): `CHK-XT-ILLEGAL -> XT_ILLEGAL_PHASE (DTP[9:2] follows abort/double-req pin patterns)` — matches measured equals
- FCOV (log L39, L45–46): auto-hit 1 bin · `xtrig_cg.ctm.illegal_phase = 1` only (`smc_bits_clean` absent)
- Evidence map: `XT_ILLEGAL_PHASE` expect `"DTP[9:2] follows abort/double-req pin patterns"`
- Explicitly out of scope (docstring): idle-negative ack/SMC; Force four-phase / ack-before-req
- Enrollment: `hw/sys/smu/dv/testlists/dtp.toml`, `all.toml`
- No unexplained ERROR/FATAL/Traceback; bring-up trailer `+skip_fuse_sense` / ROM backdoor not on CTM proof path

</details>

## Not concluded

- Whether pin-only abort/double-req DTP follow-through proves the SPEC CTM illegal-phase
  properties (O2) — Skill 3.
- Completeness against a feature_list — no inventory applies in STANDALONE-REQUEST.
- Any closure or PROVEN checker claim — MODE=NO-CHECKBOX forbids inventing checkers.

## Accepted waivers

| Finding | Rule | Where | Why | Approved by |
|---|---|---|---|---|
| — | — | — | none | — |
