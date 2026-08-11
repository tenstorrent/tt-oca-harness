---
schema: dv-quality/v1
artifact: testcase-grade
testcase: smu_no_sep_configuration_test
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
simulator: verilator
simulator_version: 5.050 2026-07-01
compile_target: null
model_fingerprint: null
compile_inputs_sha256: null
seeds:
- 1
logs:
- path: hw/sys/smu/dv/build/kept_logs/smu_no_sep_configuration_test.seed1.log
  sha256: adf9f3edea88a965fa7c1e361acba84c936ead314b44a764cba2e8439cd4bd38
test_author:
  human_id: unknown
  run_id: unknown
  model:
    provider: unknown
    family: unknown
    version: unknown
auditor:
  human_id: minshaoho
  run_id: dv_test_audit-smu_no_sep_configuration-L1-20260806-d17
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

# Grade Report — smu_no_sep_configuration_test (standalone Layer 1)

**VERDICT: 0/0 PROVEN — NOT READY** (mode NO-CHECKBOX, no_contract_reason STANDALONE-REQUEST)

| Mode | Entry gate | Checkers | Findings | Recommendation |
|---|---|---|---|---|
| `NO-CHECKBOX` | — NOT-EVALUATED | 0/0 PROVEN | none | ⛔ NOT-READY |

> No approved checkbox card or parent plan record governs this residual enrolled test
> (header DV-CARD SMU_005 cites a missing `SMU_VPLAN_DETAIL.md`; not used as a contract).
> Layer 1 findings are the entire scope of this report. `NOT-READY` records the **absence of
> a closure claim**, not a defect in the test by itself.

## DELTA (re-audit vs prior grade)

| Item | Prior (`dv_test_audit-smu_no_sep_configuration-L1-20260806-c03`) | This audit (`dv_test_audit-smu_no_sep_configuration-L1-20260806-d17`) |
|---|---|---|
| Verdict | 0/0 PROVEN — NOT READY | 0/0 PROVEN — NOT READY |
| Findings | 🔴 1 Blocking FIND-001 `[NO-ALWAYS-PASS-CHECKER]` (`expect_eq(True, True)` NONVAC) | none open — FIND-001 closed |
| CHK-NONVAC | tautological `True`/`True` scoreboard expect | `expect_eq(pairs_ok, 2)` after measured S1&lt;S2&lt;PASS fence (seq `:116–135`, log L36–39) |
| Kept log | none supplied | `adf9f3edea…` seed1 (run `20260806_070527`) PASS |
| Waivers carried | none signed | none |

## Your to-do — none

**Then:** residual Layer 1 is clean; no Skill-2 closure claim applies under STANDALONE-REQUEST. Owner may allocate this leaf via `/dv_vplan_gen` if SMU_ALL (or a residual contract) should own SEP=0 `lc_state` composition, or leave it as enrolled smoke outside the milestone denominator.

## All checkers

| Checker | Grade | Proof class | Covers | Findings |
|---|---|---|---|---|
| — | — | — | — | no card checkers (MODE=NO-CHECKBOX) |

### Layer 1 structural rule set

| Rule | Result |
|---|---|
| F1 fabricated verdict / backdoor write | ✅ clean — top-level `lc_state_o` / SEP aperture samples; no Force on proof path |
| F2 can't-fail checker | ✅ clean — prior True/True NONVAC removed; LC / aperture / pairs_ok / timeout-path count can fail |
| E1 skip-to-pass | ✅ clean — aperture and LC mismatches raise |
| E2 empty phase | ✅ clean — S1 aperture tie-off + S2 16-cycle LC stable sample + S3 timeout inventory |
| S1 silent fail | ✅ clean — AssertionError / `expect_eq` on LC, timeout-path count, and NONVAC fence |
| O1 checker disabled | ✅ clean |
| Phase-S obligations — L1 | ✅ clean — X-aware `_sample`; seed logged; enrolled in `smc.toml` / `all.toml`; CHK-* tokens gated after checks |
| Phase-S obligations — L2 (needs the card) | — not evaluated |

## Evidence appendix

<details>
<summary>Kept log + code proof-path notes</summary>

- Implementation: `hw/sys/smu/dv/cocotb/tests/smu_no_sep_configuration_test.py`
- Sequence: `hw/sys/smu/dv/cocotb/seq_lib/smu_no_sep_configuration_test_seq.py`
- Log: `hw/sys/smu/dv/build/kept_logs/smu_no_sep_configuration_test.seed1.log` sha256
  `adf9f3edea88a965fa7c1e361acba84c936ead314b44a764cba2e8439cd4bd38` (matches claimed;
  run `20260806_070527__verilator__smu_no_sep_configuration_test`)
- Seed: 1 · simulator: verilator 5.050 · cocotb summary L54: `TESTS=1 PASS=1 FAIL=0 SKIP=0`
- Stimulus: SEP=0 bring-up only (direct SMN→SMC path deferred by design comment)
- Observations: `sep_global_base_o`/`sep_region_size_o` == 0; `lc_state_o == 0xf0` for 16 cycles
- Evidence tokens (log L26–39 / scoreboard summary L46): `CHK-SEP0-LC`, `CHK-TIMEOUT-PATHS`,
  `CHK-NONVAC` (scoreboard `check_phase` re-logs CHK-NONVAC once more — shared helper hygiene)
- Enrollment: `hw/sys/smu/dv/testlists/smc.toml`, `all.toml`
- Bring-up trailer `+skip_fuse_sense` / ROM backdoor present; not on the SEP=0 pin-sample proof path
- Header cites legacy SMU_005 card metadata; residual board has no approved card → NO-CHECKBOX
- Entry gate / Layer 2 not evaluated (MODE=NO-CHECKBOX)

</details>

<details>
<summary>Token / step cites (kept log `adf9f3edea…`)</summary>

| Step / token | Line | What the log shows | Impl |
|---|---|---|---|
| S1 | 23 | SEP aperture PRELOAD / tie-off step | seq `:51–60` |
| S2 / CHK-SEP0-LC | 24–28 | `lc_state_o == 0xf0` stable samples=16; CHECK PASS 16 | seq `:62–84` |
| S3 / CHK-TIMEOUT-PATHS | 29–34 | `TIMEOUT-PATH s2_lc_stable bound=16 ok last=0xf0`; paths=1 | seq `:86–111` |
| CHK-NONVAC | 36–39 | ordered fence `S1<S2<PASS` pairs_ok=2 expect=2; CHECK PASS 2 | seq `:116–135` |

</details>

## Not concluded

- Whether SEP=0 `lc_state_o==0xf0` alone proves the SPEC composition properties a future card
  would require (O2; direct SMC path deferred) — Skill 3.
- Completeness against a feature_list — no inventory applies in STANDALONE-REQUEST.
- Any closure or PROVEN checker claim — MODE=NO-CHECKBOX forbids inventing checkers.

## Accepted waivers

| Finding | Rule | Where | Why | Approved by |
|---|---|---|---|---|
| — | — | — | none | — |
