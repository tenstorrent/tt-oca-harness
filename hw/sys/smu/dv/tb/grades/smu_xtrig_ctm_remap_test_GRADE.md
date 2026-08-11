---
schema: dv-quality/v1
artifact: testcase-grade
testcase: smu_xtrig_ctm_remap_test
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
  path: /home/minshaoho/.claude/skills/dv_common/DV_QUALITY_POLICY.md
  revision: 51a3357d9c31a018d69451b055bc956c089af26e1051368e25ce396c84ac2a75
build_config: null
simulator: null
simulator_version: null
compile_target: null
model_fingerprint: null
compile_inputs_sha256: null
seeds: [1]
logs:
  - path: hw/sys/smu/dv/build/kept_logs/smu_xtrig_ctm_remap_test.seed1.log
    sha256: afd47963659aa7321ce02f09f295d233e62ebb8806b34c8e6aea9b03c7344d65
test_author:
  human_id: unknown
  run_id: unknown
  model:
    provider: unknown
    family: unknown
    version: unknown
auditor:
  human_id: minshaoho
  run_id: dv_test_audit-smu_xtrig_ctm_remap-L1-20260806-d19
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

# Grade Report — smu_xtrig_ctm_remap_test (standalone Layer 1)

**VERDICT: 0/0 PROVEN — NOT READY** (mode NO-CHECKBOX, no_contract_reason STANDALONE-REQUEST)

| Mode | Entry gate | Checkers | Findings | Recommendation |
|---|---|---|---|---|
| `NO-CHECKBOX` | — NOT-EVALUATED | 0/0 PROVEN | none | ⛔ NOT-READY |

> No approved checkbox card or parent plan record governs this residual enrolled test. Layer 1
> findings are the entire scope of this report. `NOT-READY` records the **absence of a closure
> claim**, not a defect in the test by itself.

## DELTA (re-audit vs prior grade)

| Item | Prior (`dv_test_audit-smu_xtrig_ctm_remap-L1-20260806-c06`) | This audit (`dv_test_audit-smu_xtrig_ctm_remap-L1-20260806-d19`) |
|---|---|---|
| Verdict | 0/0 PROVEN — NOT READY | 0/0 PROVEN — NOT READY |
| Mode / reason | NO-CHECKBOX / STANDALONE-REQUEST | unchanged |
| Kept log | none supplied | `afd47963659aa7321ce02f09f295d233e62ebb8806b34c8e6aea9b03c7344d65` seed=1 |
| Findings | 🔴 1 Blocking FIND-001 `[NEGATIVE-NEEDS-POSITIVE-CONTROL]` | none open — FIND-001 closed |
| Waivers carried | none signed | none |
| Code delta | idle-negative `dst_ack`/`src_req` expects still present (prior lines ~64–110) | those expects removed; docstring marks four-phase idle-negatives out of scope until positive control is enrolled |

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
| F1 fabricated verdict / backdoor write | ✅ clean — product pins only; hierarchical DTP observe; no Force |
| F2 can't-fail checker | ✅ clean — DEST_PATS/SRC_ACK_PATS remap and [1:0] hardwire expects can fail independently |
| E1 skip-to-pass | ✅ clean |
| E2 empty phase | ✅ clean — dest-pattern + src-ack sweeps with RisingEdge settles |
| S1 silent fail | ✅ clean — `sb.expect_eq` raises; X/Z `_bits` raises |
| O1 checker disabled | ✅ clean |
| Phase-S obligations — L1 | ✅ clean — X-aware samples; event settles; scoreboard refuses zero checks; `XT_CTM_REMAP` conditional; enrolled in `dtp.toml` / `all.toml`; prior idle-negative claim dropped |
| Phase-S obligations — L2 (needs the card) | — not evaluated |

## Evidence appendix

<details>
<summary>Code + kept log (Layer 1 only)</summary>

- Implementation: `hw/sys/smu/dv/cocotb/tests/smu_xtrig_ctm_remap_test.py`
- Helpers: `tests/smu_base_test.py` (bring-up, `prove_mapped_features`), `env/smu_scoreboard.py` (`expect_eq`)
- Stimulus: product pins `xtrig_ctm_dst_req` / `xtrig_ctm_src_ack` with DEST_PATS / SRC_ACK_PATS
- Observations: hierarchical `u_dut.dtp_xtrig_ctm_dst_req` / `dtp_xtrig_ctm_src_ack` via X-aware `_bits`
- Evidence map: `XT_CTM_REMAP` → `CHK-XT-CTM-REMAP` (`smu_evidence_map.py`)
- Explicitly out of scope: Force-based four-phase; idle-negative `dst_ack` / `src_req` until positive control enrolled
- Enrollment: `hw/sys/smu/dv/testlists/dtp.toml`, `all.toml`
- Kept log: `hw/sys/smu/dv/build/kept_logs/smu_xtrig_ctm_remap_test.seed1.log` sha256 `afd47963659aa7321ce02f09f295d233e62ebb8806b34c8e6aea9b03c7344d65`
- Run: `20260806_070415__verilator__smu_xtrig_ctm_remap_test`, Verilator 5.050, seed 1
- Log: cocotb PASS; 15 scoreboard checks; `FEATURE PROVEN CHK-XT-CTM-REMAP -> XT_CTM_REMAP`; `EVIDENCE: CHK-NONVAC`; no unexplained ERROR/FATAL/Traceback
- Authoritative PASS / Layer 2 not evaluated (MODE=NO-CHECKBOX)

</details>

## Not concluded

- Whether product-pin remap without four-phase proves the full SPEC CTM remap/handshake
  surface (O2) — Skill 3.
- Completeness against a feature_list — no inventory applies in STANDALONE-REQUEST.
- Any closure or PROVEN checker claim — MODE=NO-CHECKBOX forbids inventing checkers.

## Accepted waivers

| Finding | Rule | Where | Why | Approved by |
|---|---|---|---|---|
| — | — | — | none | — |
