---
schema: dv-quality/v1
artifact: testcase-grade
testcase: smc_cg_test_mode_bypass_test
ip: SMC_CLOCK_GATING
anchor: smc_cg_test_mode_bypass_test
mode: CHECKBOX
no_contract_reason: null
entry_status: ENTRY-CONDITION-FAILED
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
card_sha256: c4d8b90225e96f8c7796fabb3370409dc3db39898ca34e52d486363aef52ff49
card_revision: 1
card_path: hw/sys/smc/dv/tb/SMC_CLOCK_GATING_VPLAN_DETAIL.md
testcase_plan:
  path: hw/sys/smc/dv/tb/SMC_CLOCK_GATING_TESTCASE_PLAN.md
  plan_revision: 1
  testcase_revision: 1
  testcase_record_sha256: 3168d8b18d1afd7b31f6d5ae4780534e509da9dd543115098f4847f9df5355a0
  parent_approved: true
evidence_class: strict-e2e
closure_tier: B
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
- path: hw/sys/smc/dv/build/runs/20260806_063128__verilator__smc_cg_test_mode_bypass_test/smc_cg_test_mode_bypass_test/logs/smc_cg_test_mode_bypass_test.log
  sha256: efdec4b9acdd3a527046f834ffc264de1512112744daca8971728ce40875f0c5
test_author:
  human_id: minshaoho
  run_id: dv_test_impl-SMC_CG_TEST_MODE_BYPASS_TEST-916949e4-ce77-48fb-9e77-730455010537
  model:
    provider: cursor
    family: grok
    version: '4.5'
auditor:
  human_id: minshaoho
  run_id: dv_test_audit-SMC_CG_TEST_MODE_BYPASS_TEST-c3672edb6d2f44e7a6ebc545b2ae30f0
  model:
    provider: cursor
    family: grok
    version: '4.5'
exceptions: []
checkers: []
findings:
- id: FIND-001
  tag: '[AUTHORITATIVE-PASS]'
  severity: Blocking
  artifact_ref: hw/sys/smc/dv/build/runs/20260806_063128__verilator__smc_cg_test_mode_bypass_test/smc_cg_test_mode_bypass_test/logs/smc_cg_test_mode_bypass_test.log:309-329
  observed: >-
    Authoritative PASS missing: cocotb summary TESTS=1 PASS=0 FAIL=1 SKIP=0;
    AssertionError at smc_cg_test_mode_bypass_test_seq.py:87
    "DMA clock gated under test_en_i: edges=0 window=16"; Traceback present;
    result.json status FAIL. Root cause consistent with open issue #4413
    (prim_clkgater latched_en=i_en ignores i_te → DFT/test_en bypass dead in sim).
    No CHK-* tokens emitted before abort. Prior PROVEN on log 15806e51… is invalidated
    by this kept log.
  closure_condition: >-
    Resolve https://github.com/tenstorrent/tt-oca-hw/issues/4413 (OPEN) so
    prim_clkgater honors i_te; re-run smc_cg_test_mode_bypass_test seed=1; obtain
    authoritative PASS (TESTS PASS=1, final assert not missing CHK tokens, zero
    unexplained Traceback); then re-invoke Skill 2. Do not re-grade checkers from
    this FAIL log.
  waived_by: null
waivers: []
recommendation: NOT-READY
---

# Grade Report — smc_cg_test_mode_bypass_test (SMC_CG_TEST_MODE_BYPASS_TEST)

**VERDICT: 0/0 PROVEN — NOT READY** (mode CHECKBOX, entry ENTRY-CONDITION-FAILED)

| Mode | Entry gate | Checkers | Findings | Recommendation |
|---|---|---|---|---|
| `CHECKBOX` | ⛔ ENTRY-CONDITION-FAILED | 0/0 PROVEN | 🔴 1 Blocking | ⛔ NOT-READY |

> Card + parent approved and hash-matching, but the kept log is an authoritative FAIL
> (`edges=0` under `test_en_i`). Layer 2 checker grading is not entered (`checkers: []`).
> Prior 3/3 PROVEN + human signoff on log `15806e51…` are **invalidated**. Root cause
> citation: GitHub issue #4413 (`prim_clkgater` ignores `i_te`).

## DELTA (re-audit vs prior grade `3/3 PROVEN` on log `15806e51…`)

| Prior id | Tag / grade | Status this round | Notes |
|---|---|---|---|
| CHK-DFT-BYPASS-DMA | PROVEN | INVALIDATED — not re-graded | Entry FAIL; Layer 2 stopped (`checkers: []`) |
| CHK-DFT-BYPASS-ZEROER | PROVEN | INVALIDATED — not re-graded | Abort at DMA assert before Zeroer tokens |
| CHK-NONVAC | PROVEN | INVALIDATED — not re-graded | Fence / NONVAC never reached |
| (none) | — | OPEN FIND-001 | `[AUTHORITATIVE-PASS]` Blocking — FAIL log `efdec4b9…` |
| Human signoff Done @ 2026-08-05 | EVIDENCE-CLOSED | SUPERSEDED | Signoff on prior PASS log does not survive this FAIL re-audit |
| waivers: [] | — | unchanged | No signed waivers to carry forward; none dropped |

## Your to-do — 1 item (🔴 1 Blocking)

| # | Sev | Item | Where | Deficiency in one line |
|---|---|---|---|---|
| 1 | 🔴 Blocking | FIND-001 `[AUTHORITATIVE-PASS]` | kept log L309–329 · seq `:87` | FAIL: DMA edges=0 under test_en_i; no authoritative PASS → Layer 2 blocked |

<details>
<summary><b>1 · FIND-001 · 🔴 Blocking · <code>[AUTHORITATIVE-PASS]</code></b></summary>

**Observed** — Kept log
`…/20260806_063128__verilator__smc_cg_test_mode_bypass_test/…/smc_cg_test_mode_bypass_test.log`
(sha256 `efdec4b9…`) shows STEP S1, CSR program of CLOCK_GATE_CONTROL, then
`AssertionError: DMA clock gated under test_en_i: edges=0 window=16` at
`smc_cg_test_mode_bypass_test_seq.py:87` after `tb_test_en_i=1`. Cocotb
`TESTS=1 PASS=0 FAIL=1`; Traceback present; `result.json` `status: FAIL`. No
`CHK-DFT-BYPASS-*` / `CHK-NONVAC` tokens. Card/parent hashes still match
(`c4d8b902…` / `3168d8b1…`). Committed `prim_clkgater.sv` uses `latched_en = i_en`
(ignores `i_te`) — matches open issue
[#4413](https://github.com/tenstorrent/tt-oca-hw/issues/4413)
(`[SMC DV] prim_clkgater behavioral model ignores i_te → DFT/test_en clock-gating bypass dead in sim`,
OPEN, updatedAt 2026-08-06T06:48:56Z).

**Required change** — Fix the gater model / RTL so `i_te` forces the clock enable path
(issue #4413); do **not** weaken the test asserts. Re-run seed=1; confirm
authoritative PASS; re-invoke Skill 2. Checker grades must not be invented from this
FAIL log (LINKED-ISSUE grading only after entry PASS).

**Where** — log L309–329; seq `smc_cg_test_mode_bypass_test_seq.py:87`; RTL
`hw/common/och_prim_generic/rtl/prim_clkgater.sv` (read-only cite).
</details>

**Then:** close / fix #4413 → re-run sim → re-invoke `/dv_test_audit` on this testcase with the new kept log.

## All checkers

| Checker | Grade | Proof class | Covers | Findings |
|---|---|---|---|---|
| — | — NOT-EVALUATED | — | — | Layer 2 not entered (ENTRY-CONDITION-FAILED); card has 3 checkers but `checkers: []` this round |

### Layer 1 structural rule set

| Rule | Result |
|---|---|
| F1 fabricated verdict / backdoor write | ✅ clean — CSR via frontdoor AXI; DFT via TB pin `tb_test_en_i` only; gated clocks passively observed; no force/deposit on DUT internals |
| F2 can't-fail checker | ✅ clean — `edges == IDLE_OBSERVE` assert fired (this log: edges=0); `wait_gated_off` timeout and X/Z paths raise |
| E1 skip-to-pass | ✅ clean — FAIL path taken; no skip-to-pass |
| E2 empty phase | ✅ clean |
| S1 silent fail | ✅ clean — mismatch raises `AssertionError` (visible FAIL) |
| O1 checker disabled | ✅ clean |
| Phase-S obligations — L1 | ✅ clean — addr symbols from `smc_addr_map` / `smc_cg_obs_utils`; enrolled in `clock.toml`; tokens conditional on assert |
| Phase-S obligations — L2 (needs the card) | 🔴 Blocking — FIND-001 (`[AUTHORITATIVE-PASS]`) |

**Notes**

- Positive control for otherwise-gating: `wait_gated_off` with `tb_test_en_i=0` before bypass assert (seq S1).
- Abort before Zeroer / NONVAC proof; no vacuous PASS tokens on this log.
- Issue #4413 explains sim FAIL; it is **not** a Skill-2 waiver and was **not** graded LINKED-ISSUE (entry gate blocked Layer 2).

## Evidence appendix

<details>
<summary>Kept log + build identity + entry gate</summary>

- Log: `hw/sys/smc/dv/build/runs/20260806_063128__verilator__smc_cg_test_mode_bypass_test/smc_cg_test_mode_bypass_test/logs/smc_cg_test_mode_bypass_test.log`
  sha256 `efdec4b9acdd3a527046f834ffc264de1512112744daca8971728ce40875f0c5` (verified via `sha256sum`; matches owner hint)
- `result.json`: `status: FAIL`, seed 1, target `default`, simulator `verilator` `5.050 2026-07-01`, `target_build.fingerprint: 2c815fa08277`, positive-evidence parser `results_xml` FAIL
- Card: SMC_CG_TEST_MODE_BYPASS_TEST r1 `c4d8b90225e96f8c7796fabb3370409dc3db39898ca34e52d486363aef52ff49` (recomputed match via `manifest.py record-hash`)
- Parent plan record: r1 `3168d8b18d1afd7b31f6d5ae4780534e509da9dd543115098f4847f9df5355a0` · `plan_revision: 1` · `status: approved` (recomputed match); card `derived_from.testcase_record_sha256` matches
- Entry: ⛔ ENTRY-CONDITION-FAILED — policy §5 authoritative PASS not met (cocotb FAIL + Traceback + AssertionError); identity/freshness OK
- Cocotb summary L329: `TESTS=1 PASS=0 FAIL=1 SKIP=0`; abort at seq.py:87 before any CHK emit; test wrapper final `assert not missing` never reached
- Linked issue (cite only; not graded LINKED-ISSUE): #4413 OPEN — `prim_clkgater` `latched_en = i_en` ignores `i_te`
- Enrolled: `hw/sys/smc/dv/testlists/clock.toml` → `smc_cg_test_mode_bypass_test`
- Auditor `run_id` `dv_test_audit-SMC_CG_TEST_MODE_BYPASS_TEST-c3672edb6d2f44e7a6ebc545b2ae30f0` ≠ prior auditor `…-6ec5b8e65cd54fdeb374526fcc7ba25a` ≠ authoring `dv_test_impl-…-916949e4-…`
- Force/deposit: only `dut.tb_test_en_i.value = {0,1}`; TB `tb_top.sv:1062` `.test_en_i(tb_test_en_i)`

</details>

<details>
<summary>Token / step cites (kept log `efdec4b9…`)</summary>

| Checker | Log line | What the log shows | Impl |
|---|---|---|---|
| (setup) | 268 | `STEP S1: DMA cg enabled + idle …` | seq `:67` |
| (CSR) | 281–308 | CLOCK_GATE_CONTROL read/write at `0xc0010018` | seq `_program_cg` |
| (FAIL) | 309–322 | `DMA clock gated under test_en_i: edges=0 window=16` + Traceback | seq `:87` |
| CHK-DFT-BYPASS-DMA | — | NOT EMITTED | seq `:91` unreachable |
| CHK-DFT-BYPASS-ZEROER | — | NOT EMITTED | seq `:124` unreachable |
| CHK-NONVAC | — | NOT EMITTED | seq `:139` unreachable |
| (summary) | 327–329 | `FAIL` · `TESTS=1 PASS=0 FAIL=1` | cocotb regression |

</details>

<details>
<summary>Layer 1 notes (abbreviated)</summary>

- Structural F/E/S/O1 clean: the test fails loudly when bypass does not hold.
- Addresses/fields via `smc_addr_map` / obs_utils re-exports (generated headers).
- Layer 2 proof fence / coverage / LINKED-ISSUE checker grades: **not evaluated** this round.

</details>

## Accepted waivers

| Finding | Rule | Where | Why | Approved by |
|---|---|---|---|---|
| — | — | — | none (prior ledger empty; no unsigned entries to drop) | — |
