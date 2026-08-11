---
schema: dv-quality/v1
artifact: testcase-grade
testcase: smu_axi_atomic_operation_test
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
- path: hw/sys/smu/dv/build/kept_logs/smu_axi_atomic_operation_test.seed1.log
  sha256: f20f87991dc44117f409c1c55cbccb41ee068a4d905f02d7b56ca9efe8c17966
test_author:
  human_id: unknown
  run_id: unknown
  model:
    provider: unknown
    family: unknown
    version: unknown
auditor:
  human_id: minshaoho
  run_id: dv_test_audit-smu_axi_atomic_operation-L1-20260806-3fd7f96d55a6
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

# Grade Report — smu_axi_atomic_operation_test (NO-PLAN-ENTRY Layer 1)

**VERDICT: 0/0 PROVEN — NOT READY** (mode NO-CHECKBOX, no_contract_reason NO-PLAN-ENTRY)

| Mode | Entry gate | Checkers | Findings | Recommendation |
|---|---|---|---|---|
| `NO-CHECKBOX` | — NOT-EVALUATED | 0/0 PROVEN | none | ⛔ NOT-READY |

> SMU_ALL has an approved plan/cards surface, but this leaf has **no plan record and no
> approved checkbox card**. Layer 1 findings are the entire scope. `NOT-READY` records the
> **absence of a closure claim** (and the plan gap), not a Layer-1 structural defect.

## DELTA (re-audit vs prior grade)

| Item | Prior (`a03`, no kept log) | This audit (`3fd7f96d55a6`, log `f20f8799…`) |
|---|---|---|
| Verdict | 0/0 PROVEN — NOT READY | 0/0 PROVEN — NOT READY |
| Findings | 🔴 2 Blocking | none |
| FIND-001 `[NO-ALWAYS-PASS-CHECKER]` | open — `axi_read32_resp_ids` fell back to issued ARID | closed — helper samples live `bus_r.rid` (no issued fallback); log RID=`0x2a` vs ARID=`0x2a` |
| FIND-002 `[NEGATIVE-NEEDS-POSITIVE-CONTROL]` | open — DECERR/poison deny asserts without allow contrast | closed — leaf dropped deny/poison asserts; resp/data diagnostic-only |
| Kept log | absent | `f20f87991dc44117f409c1c55cbccb41ee068a4d905f02d7b56ca9efe8c17966` seed=1 |
| Waivers carried | none signed | none |

## Your to-do — 0 items (none)

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
| F1 fabricated verdict / backdoor write | ✅ clean — frontdoor `s_axi` master; no Force |
| F2 can't-fail checker | ✅ clean — live R-channel RID vs issued ARID via `axi_read32_resp_ids`; mismatch / capture-miss raise |
| E1 skip-to-pass | ✅ clean — ATOP reject deferred with alternate non-ATOP path executed (not skip-to-pass) |
| E2 empty phase | ✅ clean — SMN read + RID compare present (ATOP reject itself still deferred — O2/intent) |
| S1 silent fail | ✅ clean — scoreboard / AXI timeout raise; resp/data diagnostic-only |
| O1 checker disabled | ✅ clean |
| Phase-S obligations — L1 | ✅ clean — address via `SMC_CHIP_CONFIG_VERSION_LO`→`smc_addr.h`; bounded AXI timeout; X/Z-aware RID sample; enrolled in `fabric.toml` / `all.toml` |
| Phase-S obligations — L2 (needs the card) | — not evaluated |

## Evidence appendix

<details>
<summary>Code + kept log (Layer 1 only; no card checkers)</summary>

- Implementation: `hw/sys/smu/dv/cocotb/tests/smu_axi_atomic_operation_test.py`
- Helpers: `seq_lib/smu_axi_helpers.py` (`make_smu_axi_master`, `axi_read32_resp_ids_bounded` →
  `axi_read32_resp_ids` live `bus_r.rid` capture), `seq_lib/smu_addr_map.py`
  (`SMC_CHIP_CONFIG_VERSION_LO`), `env/smu_scoreboard.py`
- Stimulus: non-ATOP SMN read `arid=0x2A` to CHIP_CONFIG.VERSION_LO (ATOP pin tied 0; ATOP
  reject deferred per docstring)
- Checks: RID==ARID only (`sb.expect_eq` → `AXI_NON_ATOP_OK`); resp/data logged as non-claim
- Kept log: `hw/sys/smu/dv/build/kept_logs/smu_axi_atomic_operation_test.seed1.log`
  sha256 `f20f87991dc44117f409c1c55cbccb41ee068a4d905f02d7b56ca9efe8c17966`
- Seed: 1 · simulator: verilator 5.050 · model_fingerprint: `48f5d6b1d3f2`
  (run `20260806_070344__verilator__smu_axi_atomic_operation_test`)
- Log cites: L105–109 ARID/`rid: 0x2a` / `rresp: 3` / data `1e ab dc ba`; L113–117 CHECK PASS
  RID match + `EVIDENCE:AXI_NON_ATOP_OK` / `CHK-AXI_NON_ATOP_OK`; L118 diagnostic
  `resp=DECERR data=0xbadcab1e (not a deny claim)`; L126–132 cocotb PASS / `TESTS=1 PASS=1`
- Final gate: `prove_mapped_features` + scoreboard `check_phase` (1 check, zero errors,
  `CHK-NONVAC`); no unexplained ERROR/FATAL/Traceback
- Enrollment: `hw/sys/smu/dv/testlists/fabric.toml`, `all.toml`
- Absent from `SMU_ALL_TESTCASE_PLAN.md` / `SMU_ALL_VPLAN_DETAIL.md` (NO-PLAN-ENTRY);
  related ATOP scenarios `SMU-XBAR-ATOP-REJECT.S1/S2` are OUT-OF-MILESTONE deferred in the plan
- Bring-up trailer `+skip_fuse_sense` / ROM backdoor present; not on the SMN RID proof path

</details>

## Not concluded

- Whether this leaf proves ATOP reject / atomic-ops SPEC properties (name vs deferred stimulus)
  — O2 / Skill 3.
- Completeness against SMU_ALL feature_list — this leaf is not in the plan denominator.
- Any closure or PROVEN checker claim — MODE=NO-CHECKBOX forbids inventing checkers from code or logs.

## Accepted waivers

| Finding | Rule | Where | Why | Approved by |
|---|---|---|---|---|
| — | — | — | none | — |
