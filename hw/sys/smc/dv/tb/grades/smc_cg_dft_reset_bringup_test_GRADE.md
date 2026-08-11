---
schema: dv-quality/v1
artifact: testcase-grade
testcase: smc_cg_dft_reset_bringup_test
ip: SMC_CLOCK_GATING_P0
anchor: smc_cg_dft_reset_bringup_test
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
card_sha256: 14b3775169e65fc707b9fdcd7c6dec6f9d817c002225fc23bbe4eaeefa702640
card_revision: 1
card_path: hw/sys/smc/dv/tb/SMC_CLOCK_GATING_P0_VPLAN_DETAIL.md
testcase_plan:
  path: hw/sys/smc/dv/tb/SMC_CLOCK_GATING_P0_TESTCASE_PLAN.md
  plan_revision: 1
  testcase_revision: 1
  testcase_record_sha256: 1c1053289e15ccfa6dd29d0e1711bcfd540f51ab071234d456097e9669600b2b
  parent_approved: true
evidence_class: frontdoor-func
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
- path: hw/sys/smc/dv/build/runs/20260806_063132__verilator__smc_cg_dft_reset_bringup_test/smc_cg_dft_reset_bringup_test/logs/smc_cg_dft_reset_bringup_test.log
  sha256: b82e6e818f4f73598f2141ad4e367fdee5e47eb94125ab01d1f572620d6f72b1
test_author:
  human_id: minshaoho
  run_id: dv_test_impl-SMC_CG_DFT_RESET_BRINGUP_TEST-20260805T080136+0800
  model:
    provider: unknown
    family: unknown
    version: unknown
auditor:
  human_id: minshaoho
  run_id: dv_test_audit-SMC_CG_DFT_RESET_BRINGUP_TEST-4c46174a5fa84cdf938003086ff2a732
  model:
    provider: cursor
    family: grok
    version: 4.5
exceptions: []
checkers: []
findings:
- id: FIND-001
  tag: '[ENTRY-CONDITION-FAILED]'
  severity: Blocking
  artifact_ref: hw/sys/smc/dv/build/runs/20260806_063132__verilator__smc_cg_dft_reset_bringup_test/smc_cg_dft_reset_bringup_test/logs/smc_cg_dft_reset_bringup_test.log:310-330
  observed: >-
    Authoritative PASS (policy §5) fails on kept log sha256
    b82e6e818f4f73598f2141ad4e367fdee5e47eb94125ab01d1f572620d6f72b1 (seed 1):
    cocotb summary TESTS=1 PASS=0 FAIL=1 SKIP=0; result.json status FAIL;
    AssertionError at S2 DFT bypass
    (`smc_cg_dft_reset_bringup_test_seq.py:125`)
    "DMA clock gated under test_en_i: edges=13 window=16"; Traceback present and
    explained by that assert; final assertion gate
    (`smc_cg_dft_reset_bringup_test.py:26-28`) never executed; no CHK-* tokens
    emitted. Consistent with committed `prim_clkgater.sv` (`latched_en = i_en`,
    `i_te` ignored) — GitHub issue #4413 OPEN
    (https://github.com/tenstorrent/tt-oca-hw/issues/4413,
    updatedAt 2026-08-06T06:48:56Z). Layer 2 not entered; checkers remain [].
  closure_condition: >-
    Resolve #4413 so `test_en_i`/`i_te` actually forces free-running gated clocks
    under enabled CG; keep a new PASS log meeting policy §5 (cocotb PASS + final
    CHK gate executed + no unexplained ERROR/FATAL/Traceback); re-invoke Skill 2
    on that log. Do not paper over by weakening the S2 exact-edge assert.
  waived_by: null
waivers: []
recommendation: NOT-READY
---

# Grade Report — smc_cg_dft_reset_bringup_test (SMC_CLOCK_GATING_P0 / SMCCGP0_003)

**VERDICT: 0/0 PROVEN — NOT READY** (mode CHECKBOX, entry ENTRY-CONDITION-FAILED)

| Mode | Entry gate | Checkers | Findings | Recommendation |
|---|---|---|---|---|
| `CHECKBOX` | ⛔ ENTRY-CONDITION-FAILED | 0/0 PROVEN | 🔴 Blocking 1 | ⛔ NOT-READY |

> Fresh Skill 2 re-audit (auditor `run_id`
> `dv_test_audit-SMC_CG_DFT_RESET_BRINGUP_TEST-4c46174a5fa84cdf938003086ff2a732`,
> ≠ authoring `dv_test_impl-SMC_CG_DFT_RESET_BRINGUP_TEST-20260805T080136+0800` and ≠ prior
> auditor `…6a528a99…`). Card SMCCGP0_003 r1 `14b37751…` and parent plan record r1
> `1c105328…` both `current: true` / `status: approved` (recomputed `manifest.py
> record-hash` match). Entry fails policy §5: kept FAIL log `b82e6e81…` —
> `AssertionError: DMA clock gated under test_en_i: edges=13 window=16` at S2 before any
> `CHK-*` token or the test wrapper's final gate. Linked RTL defect: #4413 OPEN
> (`prim_clkgater` ignores `i_te`). Layer 2 stopped (`checkers: []`); S3/S4 /
> `CHK-RESET-OVERRIDE-FREE-RUN` never reached (NOT-RUN at scenario level, not graded).

## DELTA (vs prior grade)

| Field | Prior (2026-08-05) | This audit |
|---|---|---|
| Kept log | `…20260805_080136…` sha256 `544db348…` | `…20260806_063132…` sha256 `b82e6e81…` |
| Entry | ✅ PASS | ⛔ ENTRY-CONDITION-FAILED |
| Checkers | 3/3 PROVEN | 0/0 (`checkers: []` — Layer 2 not entered) |
| Recommendation | ✅ EVIDENCE-CLOSED-AWAITING-SIGNOFF | ⛔ NOT-READY |
| Human signoff | Done @ 2026-08-05T16:10:00+08:00 | **voided** by this FAIL re-audit |
| Root cause cited | — | #4413 OPEN (`latched_en = i_en`) |

Prior PROVEN grades (CHK-DFT-BYPASS-FREE-RUN / CHK-RESET-OVERRIDE-FREE-RUN / CHK-NONVAC)
do not carry forward: entry PASS is a hard gate, and this kept log never emitted those tokens.

## Your to-do — 1 item (🔴 1 Blocking)

| # | Rank | Item |
|---|---|---|
| 1 | 🔴 Blocking | FIND-001 — `[ENTRY-CONDITION-FAILED]` DFT bypass assert (edges=13/16); #4413 |

<details>
<summary>1. FIND-001 — ENTRY-CONDITION-FAILED at S2 DFT bypass (#4413)</summary>

- **Where:** kept log L310–323 /
  `smc_cg_dft_reset_bringup_test_seq.py:125` assert
  `dma_edges == IDLE_OBSERVE` after `test_en_i=1` + gating enabled
- **Observed:** `edges=13 window=16`; test FAIL; no `CHK-DFT-BYPASS-FREE-RUN`,
  `CHK-RESET-OVERRIDE-FREE-RUN`, or `CHK-NONVAC` tokens; S3/S4 never executed
- **Cause (outside this test):** committed
  `hw/common/och_prim_generic/rtl/prim_clkgater.sv` sets `latched_en = i_en`
  (ignores `i_te`) — tracked by
  https://github.com/tenstorrent/tt-oca-hw/issues/4413 (OPEN, #4413,
  updatedAt 2026-08-06T06:48:56Z)
- **Closure:** fix/land RTL so `i_te` participates in the latch enable; re-run this
  testcase; keep a policy-§5 PASS log; re-invoke `/dv_test_audit` on
  `smc_cg_dft_reset_bringup_test`. Do **not** edit the test to accept partial edges.

</details>

**Then:** owner/RTL lands #4413 → re-run `smc_cg_dft_reset_bringup_test` → fresh Skill 2
re-audit on the new kept log (prior 3/3 PROVEN + owner signoff do not apply until entry
PASS returns).

## All checkers

| Checker | Grade | Proof class | Covers | Findings |
|---|---|---|---|---|
| — | — not graded (entry failed) | — | — | FIND-001 |

Layer 2 was not entered. Card checkers that would have been graded on PASS:
`CHK-DFT-BYPASS-FREE-RUN`, `CHK-RESET-OVERRIDE-FREE-RUN`, `CHK-NONVAC`. Scenario note:
`CHK-RESET-OVERRIDE-FREE-RUN` (S4) is **NOT-RUN** in this kept log (abort at S2); that is
narrative only — not a Layer 2 grade record.

### Layer 1 structural rule set

| Rule | Result |
|---|---|
| F1 fabricated verdict / backdoor write | ✅ clean — CSR frontdoor (`SmcCsrSeq`/`SmcSysAxiItem`); `tb_test_en_i` / `rst_cold_ni` are real top-level DUT inputs; gated clocks / `rst_primary_smc_clk_n` are passive reads; no `force`/`deposit`/`uvm_hdl_*` on DUT internals in seq, test, or proof-path helpers |
| F2 can't-fail checker | ✅ clean — S2 exact `edges == IDLE_OBSERVE` **did fail** on this RTL (`edges=13`); remaining asserts/`TIMEOUT`/`is_resolvable` raise on mismatch (static review of unreached S3/S4 paths) |
| E1 skip-to-pass | ✅ clean — missing TB ports `assert hasattr` fail before use; FAIL does not skip to PASS |
| E2 empty phase | ✅ clean — S1 programs/drives; S2 observes and asserts (reached); S3/S4 present in code with program/observe/assert (not reached this run) |
| S1 silent fail | ✅ clean — mismatch raises `AssertionError` with diagnostic state; bounded reset wait has `TIMEOUT-MUST-FAIL` |
| O1 checker disabled | ✅ clean |
| Phase-S obligations — L1 | ✅ clean — addresses via `smc_addr_map` symbols; X/Z-aware sampling in `smc_cg_obs_utils`; tokens only via `emit_chk` after asserts; enrolled in `testlists/clock.toml` |
| Phase-S obligations — L2 (needs the card) | — not evaluated — entry ENTRY-CONDITION-FAILED; Layer 2 stopped |

## Evidence appendix

<details>
<summary>Kept log + build identity</summary>

- Log: `hw/sys/smc/dv/build/runs/20260806_063132__verilator__smc_cg_dft_reset_bringup_test/smc_cg_dft_reset_bringup_test/logs/smc_cg_dft_reset_bringup_test.log`
  sha256 `b82e6e818f4f73598f2141ad4e367fdee5e47eb94125ab01d1f572620d6f72b1` (verified
  `sha256sum`; matches invoker hint)
- `result.json`: `status: FAIL`, `exit_code: 1`, seed 1, target `default`, simulator
  `verilator` `5.050 2026-07-01`, `target_build.fingerprint: 2c815fa08277`,
  `rebuild: false`, positive-evidence parser reports FAIL (`1 testcase failure/error
  node(s)`); `git.commit` / repo HEAD `2ecc7b227e3926b253c65b5aac21239eec24ba5f`
- Card: SMCCGP0_003 r1 `14b3775169e65fc707b9fdcd7c6dec6f9d817c002225fc23bbe4eaeefa702640`
  (`current: true`, `status: approved`, `manifest.py record-hash` match)
- Parent plan: SMCCGP0_003 r1
  `1c1053289e15ccfa6dd29d0e1711bcfd540f51ab071234d456097e9669600b2b` ·
  `plan_revision: 1` · `status: approved` · `current: true` (hash match)
- Cocotb summary L328–330: test **FAIL**, `TESTS=1 PASS=0 FAIL=1 SKIP=0`
- Fail site L310–323: `AssertionError: DMA clock gated under test_en_i: edges=13 window=16`
  at `smc_cg_dft_reset_bringup_test_seq.py:125` (S2); Traceback is the explained assert —
  counts toward entry FAIL, not a separate unexplained-error finding
- No `CHK-DFT-BYPASS-FREE-RUN` / `CHK-RESET-OVERRIDE-FREE-RUN` / `CHK-NONVAC` / `FENCE`
  lines in this kept log
- Linked issue: https://github.com/tenstorrent/tt-oca-hw/issues/4413 — state OPEN,
  number 4413, updatedAt 2026-08-06T06:48:56Z
- RTL (read-only confirm, not modified): `prim_clkgater.sv` `latched_en = i_en`
  (no `i_te` in latch)
- Enrolled: `hw/sys/smc/dv/testlists/clock.toml`
- Force/deposit audit: clean on proof path (same frontdoor + pin-drive pattern as prior
  audit; failure is behavioral, not backdoor)

</details>

<details>
<summary>Token / step cites (kept log `b82e6e81…`)</summary>

| Checker / step | Log line | What the log shows | Impl |
|---|---|---|---|
| (setup) | 268 | `STEP S1: assert test_en_i; frontdoor CLOCK_GATE_CONTROL …` | seq `:102-109` |
| (setup) | 309 | `STEP S2: sample … with test_en_i asserted` | seq `:112-124` |
| CHK-DFT-BYPASS-FREE-RUN | — | **not emitted** — assert fails first | seq `:125-146` |
| (fail) | 310–323 | `DMA clock gated under test_en_i: edges=13 window=16` + Traceback | seq `:125` |
| S3 / S4 / CHK-RESET-OVERRIDE-FREE-RUN | — | **NOT-RUN** (abort at S2) | seq `:149-193` |
| CHK-NONVAC | — | **NOT-RUN** | seq `:203-211` |
| (summary) | 328–330 | test FAIL · `PASS=0 FAIL=1` | cocotb |

</details>

<details>
<summary>Layer 1 notes (proof-path helpers)</summary>

- `smc_cg_obs_utils.count_enabled_triple_at_smc_rise` X/Z-checks each sample and returns
  per-SMC-rise enable hits; S2 compares to `IDLE_OBSERVE=16` — real FAIL-ON (observed).
- `emit_chk` only after asserts; this run never reached emit for any card checker.
- Addresses: `smc_addr_map` symbols (`CLOCK_GATE_CONTROL`, `DMA_CG_EN`, `ZEROER_CG_EN`,
  hyst masks) — no hand-copied proof-path literals in the seq.
- Layer 1 finds no fabricated-pass / can't-fail / skip-to-pass structure; the test is
  correctly detecting the DFT-bypass defect exposed by #4413.

</details>

## Accepted waivers

| Finding | Rule | Where | Why | Approved by |
|---|---|---|---|---|
| — | — | — | none | — |
