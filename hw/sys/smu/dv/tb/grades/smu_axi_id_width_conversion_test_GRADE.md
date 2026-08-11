---
schema: dv-quality/v1
artifact: testcase-grade
testcase: smu_axi_id_width_conversion_test
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
simulator_version: 5.050 2026-07-01 rev v5.050 (mod)
compile_target: default
model_fingerprint: 48f5d6b1d3f2
compile_inputs_sha256: null
seeds:
- 1
logs:
- path: hw/sys/smu/dv/build/kept_logs/smu_axi_id_width_conversion_test.seed1.log
  sha256: eb9469b5482f40be8a09bf52d8cc73defd2ca62ff444074bcae63d02eb13675b
test_author:
  human_id: unknown
  run_id: unknown
  model:
    provider: unknown
    family: unknown
    version: unknown
auditor:
  human_id: minshaoho
  run_id: dv_test_audit-smu_axi_id_width_conversion-L1-20260806-e8b2a91c
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

# Grade Report — smu_axi_id_width_conversion_test (NO-PLAN-ENTRY Layer 1)

**VERDICT: 0/0 PROVEN — NOT READY** (mode NO-CHECKBOX, no_contract_reason NO-PLAN-ENTRY)

| Mode | Entry gate | Checkers | Findings | Recommendation |
|---|---|---|---|---|
| `NO-CHECKBOX` | — NOT-EVALUATED | 0/0 PROVEN | none | ⛔ NOT-READY |

> SMU_ALL has an approved plan/cards surface, but this leaf has **no plan record and no
> approved checkbox card**. Layer 1 findings are the entire scope. `NOT-READY` records the
> **absence of a closure claim** (and the plan gap), not a Layer-1 structural defect.

## DELTA (re-audit vs prior grade)

| Item | Prior (`…-a04`, no kept log) | This audit (`…-e8b2a91c`, log `eb9469b5…`) |
|---|---|---|
| Verdict | 0/0 PROVEN — NOT READY | 0/0 PROVEN — NOT READY |
| FIND-001 `[NO-ALWAYS-PASS-CHECKER]` | open Blocking — `rid = beat.id else issued` tautology | **closed** — `axi_read32_resp_ids` samples live `bus.r.rid` (fail on miss / X-Z); VIP log RID matches ARID independently |
| Kept log | none | `eb9469b5…` seed=1 PASS; 3× `AXI_ID_WIDTH_OK` |
| Waivers carried | none signed | none |

## Your to-do — none

| # | Sev | Item |
|---|---|---|
| — | — | none open |

**Then:** route to `/dv_vplan_gen` so SMU_ALL either allocates this leaf (`augment`) or the owner
retires it; re-invoke `/dv_test_audit` after a card exists if Layer 2 grading is required.

## All checkers

| Checker | Grade | Proof class | Covers | Findings |
|---|---|---|---|---|
| — | — | — | — | no card checkers (MODE=NO-CHECKBOX) |

### Layer 1 structural rule set

| Rule | Result |
|---|---|
| F1 fabricated verdict / backdoor write | ✅ clean — frontdoor `s_axi` master; RID from live R-channel; no Force |
| F2 can't-fail checker | ✅ clean — live `bus.r.rid` vs issued; capture-miss and mismatch raise |
| E1 skip-to-pass | ✅ clean — no missing-handle skip |
| E2 empty phase | ✅ clean — three authoritative-map probe reads + RID compares execute |
| S1 silent fail | ✅ clean — scoreboard / AXI timeout raise; resp diagnostic-only (not a deny claim) |
| O1 checker disabled | ✅ clean |
| Phase-S obligations — L1 | ✅ clean — addresses via `smc_addr` / PeakRDL map; bounded AXI timeout; X/Z-aware RID; enrolled in `fabric.toml` / `all.toml`; wisely avoids DECERR deny claim without allow contrast |
| Phase-S obligations — L2 (needs the card) | — not evaluated |

## Evidence appendix

<details>
<summary>Code + kept-log proof path (Layer 1 only)</summary>

- Implementation: `hw/sys/smu/dv/cocotb/tests/smu_axi_id_width_conversion_test.py`
- Helpers: `seq_lib/smu_axi_helpers.py` (`make_smu_axi_master`, `axi_read32_resp_ids` /
  `_bounded`, `resp_name`), `seq_lib/smu_addr_map.py` (`SMC_CHIP_CONFIG_VERSION_LO`,
  `smc_addr`), `env/smu_scoreboard.py`
- Stimulus: three SMN reads with distinct ARIDs (`0x11`/`0x12`/`0x13`) through SEP=0 path
- Checks: `sb.expect_eq(rid, issued, evidence="AXI_ID_WIDTH_OK")`; resp logged, not asserted
- Kept log `eb9469b5482f40be8a09bf52d8cc73defd2ca62ff444074bcae63d02eb13675b` (seed 1):
  - L108/L121/L131 VIP `Read burst complete rid: 0x11/0x12/0x13` matching ARID
  - L113–L137 three `CHECK PASS` + `EVIDENCE: AXI_ID_WIDTH_OK` / `CHK-AXI_ID_WIDTH_OK`
  - L146–L152 cocotb PASS; scoreboard `3 check(s) passed with zero errors`
- Evidence map: `AXI_ID_WIDTH_OK` (`smu_evidence_map.py`)
- Enrollment: `hw/sys/smu/dv/testlists/fabric.toml`, `all.toml`
- Absent from `SMU_ALL_TESTCASE_PLAN.md` / `SMU_ALL_VPLAN_DETAIL.md` (NO-PLAN-ENTRY)
- Build: verilator 5.050, fingerprint `48f5d6b1d3f2`, run
  `20260806_070350__verilator__smu_axi_id_width_conversion_test`

</details>

## Not concluded

- Whether RID==ARID on DECERR probes proves SPEC ID-width conversion (vs local err_slv echo)
  or upper-bit truncation coverage — O2 / Skill 3 once a card exists.
- Completeness against SMU_ALL feature_list — this leaf is not in the plan denominator.
- Any closure or PROVEN checker claim — MODE=NO-CHECKBOX forbids inventing checkers from code or logs.

## Accepted waivers

| Finding | Rule | Where | Why | Approved by |
|---|---|---|---|---|
| — | — | — | none | — |
