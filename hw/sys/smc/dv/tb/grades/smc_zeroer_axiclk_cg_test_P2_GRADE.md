---
schema: dv-quality/v1
artifact: testcase-grade
testcase: smc_zeroer_axiclk_cg_test
ip: SMC_CLOCK_GATING_P2
anchor: smc_zeroer_axiclk_cg_test
mode: CHECKBOX
no_contract_reason: null
entry_status: PASS
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
card_sha256: 7716914f5e4c5adb60a4a2ebb6c58c271518148cdabc04a7796f561b5743fc7f
card_revision: 2
card_path: hw/sys/smc/dv/tb/SMC_CLOCK_GATING_P2_VPLAN_DETAIL.md
testcase_plan:
  path: hw/sys/smc/dv/tb/SMC_CLOCK_GATING_P2_TESTCASE_PLAN.md
  plan_revision: 1
  testcase_revision: 1
  testcase_record_sha256: 53791893d0c2043a2cb1d773b4736eb35027ab47038d3b039c5053a239393681
  parent_approved: true
evidence_class: frontdoor-func
closure_tier: A
quality_policy:
  path: /home/minshaoho/.claude/skills/dv_common/DV_QUALITY_POLICY.md
  revision: 51a3357d9c31a018d69451b055bc956c089af26e1051368e25ce396c84ac2a75
build_config: default
simulator: verilator
simulator_version: 5.050 2026-07-01
compile_target: default
model_fingerprint: null
compile_inputs_sha256: null
seeds: [1]
logs:
- path: hw/sys/smc/dv/build/runs/20260805_093933__verilator__smc_zeroer_axiclk_cg_test/smc_zeroer_axiclk_cg_test/logs/smc_zeroer_axiclk_cg_test.log
  sha256: 5d8c44ab9eeb46dd701ddf35452be8158a81e178a278eaf841a541ea6497e377
test_author:
  human_id: minshaoho
  run_id: unknown (Skill 1.5 implementation of the P2 back-to-back race extension; no run_id recorded in-repo for this revision)
  model:
    provider: unknown
    family: unknown
    version: unknown
auditor:
  human_id: minshaoho
  run_id: dv_test_audit-SMC_CG_P2_002-47744281-1e84-4dbb-bda6-dddc90c31d9c
  model:
    provider: cursor
    family: claude
    version: sonnet-5
exceptions: []
checkers:
- id: CHK-ZEROER-AXICLK-NOGLITCH
  checks_steps: [S2]
  proves: [SMC-CG-ZEROER-AXICLK]
  covers: [SMC-CG-ZEROER-AXICLK.S1]
  proof_class: LIVE
  expect_source: 'hw/sys/smc/doc/zeroer.adoc §Clock Gating (Clock Gating Control table); §Operation Flow (Configuration -- DEST_ADDR/SIZE writes; Trigger -- CTRL_STATUS write) @ 2f40548ea787240680a1c45ab75b8729e9620778'
  grade: PROVEN
  evidence:
  - token: 'CHK-ZEROER-AXICLK-NOGLITCH: 1-cycle-before-busy-deassert(offset=-1,mid_busy_glitches=0,inter_busy_gap_start=39,inter_busy_gap_end=63,inter_busy_gap_duration=25) same-cycle-as-busy-deassert(offset=0,mid_busy_glitches=0,inter_busy_gap_start=39,inter_busy_gap_end=64,inter_busy_gap_duration=26) 1-cycle-after-busy-deassert(offset=1,mid_busy_glitches=0,inter_busy_gap_start=39,inter_busy_gap_end=65,inter_busy_gap_duration=27)'
    log_sha256: 5d8c44ab9eeb46dd701ddf35452be8158a81e178a278eaf841a541ea6497e377
    line: 689
    seed: 1
    implementation_path: hw/sys/smc/dv/cocotb/seq_lib/smc_zeroer_axiclk_cg_test_seq.py:295
  lifecycle_results: null
  coverage_results:
  - key: SMC-CG-ZEROER-AXICLK.S1
    method: DIRECTED
    required_cells:
    - new-trigger-1-cycle-before-busy-deassert
    - new-trigger-same-cycle-as-busy-deassert
    - new-trigger-1-cycle-after-busy-deassert
    achieved_cells:
    - new-trigger-1-cycle-before-busy-deassert
    - new-trigger-same-cycle-as-busy-deassert
    - new-trigger-1-cycle-after-busy-deassert
    random_knobs: []
    resolved_knobs: []
    min_seeds: 1
    actual_seeds: [1]
    required_artifact: null
    coverage_artifacts:
    - hw/sys/smc/dv/build/runs/20260805_093933__verilator__smc_zeroer_axiclk_cg_test/smc_zeroer_axiclk_cg_test/logs/smc_zeroer_axiclk_cg_test.log#5d8c44ab9eeb46dd701ddf35452be8158a81e178a278eaf841a541ea6497e377
    satisfied: true
  linked_issue: null
  finding_ids: []
  remediation: null
- id: CHK-ZEROER-AXICLK-COMPLETION
  checks_steps: [S2]
  proves: [SMC-CG-ZEROER-AXICLK]
  covers: [SMC-CG-ZEROER-AXICLK.S1]
  proof_class: LIVE
  expect_source: 'hw/sys/smc/doc/zeroer.adoc §State Machine; §Operation Flow (Completion) @ 2f40548ea787240680a1c45ab75b8729e9620778'
  grade: PROVEN
  evidence:
  - token: 'CHK-ZEROER-AXICLK-COMPLETION: 1-cycle-before-busy-deassert(write_addr_phase_seen=1,completed=1,writes_delta=1,scored=0) same-cycle-as-busy-deassert(write_addr_phase_seen=1,completed=1,writes_delta=1,scored=1) 1-cycle-after-busy-deassert(write_addr_phase_seen=1,completed=1,writes_delta=1,scored=1)'
    log_sha256: 5d8c44ab9eeb46dd701ddf35452be8158a81e178a278eaf841a541ea6497e377
    line: 690
    seed: 1
    implementation_path: hw/sys/smc/dv/cocotb/seq_lib/smc_zeroer_axiclk_cg_test_seq.py:295
  lifecycle_results: null
  coverage_results:
  - key: SMC-CG-ZEROER-AXICLK.S1
    method: DIRECTED
    required_cells:
    - new-trigger-1-cycle-before-busy-deassert
    - new-trigger-same-cycle-as-busy-deassert
    - new-trigger-1-cycle-after-busy-deassert
    achieved_cells:
    - new-trigger-1-cycle-before-busy-deassert
    - new-trigger-same-cycle-as-busy-deassert
    - new-trigger-1-cycle-after-busy-deassert
    random_knobs: []
    resolved_knobs: []
    min_seeds: 1
    actual_seeds: [1]
    required_artifact: null
    coverage_artifacts:
    - hw/sys/smc/dv/build/runs/20260805_093933__verilator__smc_zeroer_axiclk_cg_test/smc_zeroer_axiclk_cg_test/logs/smc_zeroer_axiclk_cg_test.log#5d8c44ab9eeb46dd701ddf35452be8158a81e178a278eaf841a541ea6497e377
    satisfied: true
  linked_issue: null
  finding_ids: []
  remediation: null
- id: CHK-NONVAC
  checks_steps: [S1, S2]
  proves: []
  covers: []
  proof_class: INTEGRITY
  expect_source: approved card ordering contract
  grade: PROVEN
  evidence:
  - token: 'CHK-NONVAC: SETUP < FIRST-OP-BUSY < BOUNDARY-SWEEP(3-cells) < FOLLOWON-OBSERVED < PASS'
    log_sha256: 5d8c44ab9eeb46dd701ddf35452be8158a81e178a278eaf841a541ea6497e377
    line: 693
    seed: 1
    implementation_path: hw/sys/smc/dv/cocotb/seq_lib/smc_zeroer_axiclk_cg_test_seq.py:610
  lifecycle_results: null
  coverage_results: []
  linked_issue: null
  finding_ids: []
  remediation: null
- id: CHK-TIMEOUT-PATHS
  checks_steps: [S3]
  proves: []
  covers: []
  proof_class: INTEGRITY
  expect_source: approved card timeout contract
  grade: PROVEN
  evidence:
  - token: 'CHK-TIMEOUT-PATHS: calib_bound_smc_cycles=300 trial_bound_smc_cycles=400 followon_bound_smc_cycles=300 expired=0 last_busy=0 last_axi_clk_enable=1'
    log_sha256: 5d8c44ab9eeb46dd701ddf35452be8158a81e178a278eaf841a541ea6497e377
    line: 692
    seed: 1
    implementation_path: hw/sys/smc/dv/cocotb/seq_lib/smc_zeroer_axiclk_cg_test_seq.py:567
  lifecycle_results: null
  coverage_results: []
  linked_issue: null
  finding_ids: []
  remediation: null
findings: []
waivers: []
recommendation: EVIDENCE-CLOSED-AWAITING-SIGNOFF
---

# Grade Report — smc_zeroer_axiclk_cg_test (SMC_CG_P2_002, card revision 2)

**VERDICT: 4/4 PROVEN — READY** (mode CHECKBOX, entry PASS)

| Mode | Entry gate | Checkers | Findings | Recommendation |
|---|---|---|---|---|
| `CHECKBOX` | ✅ PASS | 4/4 PROVEN | none | ✅ EVIDENCE-CLOSED-AWAITING-SIGNOFF |

> Fresh Skill 2 audit of the SMC_CG_P2_002 **revision 2** card only (rev1 is `current: false`,
> superseded; its FAIL log `20260805_091625` is STALE against rev2's narrowed
> `CHK-ZEROER-AXICLK-NOGLITCH` contract and is not consulted). This is the P1 anchor's additive
> P2 extension only — the P1 body checkers (`CHK-ZAXI-*`, P1's own `CHK-NONVAC`) are unchanged
> and remain covered by the standing P1 grade (`smc_zeroer_axiclk_cg_test_GRADE.md`, not
> touched by this report). Entry PASS: cocotb `TESTS=1 PASS=1 FAIL=0 SKIP=0` on run
> `20260805_093933`, final `assert not missing` on all nine `chk_seen` tokens (P1+P2 combined),
> zero unexplained `ERROR`/`FATAL`/`Traceback` in the kept log.

## Grade table

| Checker | Grade | Proof class | Covers | Findings |
|---|---|---|---|---|
| CHK-ZEROER-AXICLK-NOGLITCH | ✅ PROVEN | LIVE | SMC-CG-ZEROER-AXICLK.S1 | — |
| CHK-ZEROER-AXICLK-COMPLETION | ✅ PROVEN | LIVE | SMC-CG-ZEROER-AXICLK.S1 | — |
| CHK-NONVAC | ✅ PROVEN | INTEGRITY | — | — |
| CHK-TIMEOUT-PATHS | ✅ PROVEN | INTEGRITY | — | — |

## Your to-do — 0 items (none)

| # | Rank | Item |
|---|---|---|
| — | — | none open |

**Then:** human signoff on this grade → Skill 3 peer audit (`SMC_CLOCK_GATING_P2` / P2) once
`SMC_CG_P2_001` and `SMC_CG_P2_003` grades also close.

### Layer 1 structural rule set

| Rule | Result |
|---|---|
| F1 fabricated verdict / backdoor write | ✅ clean — P2 extension (`_p2_extension`, `_p2_race_cell`, `_p2_measure_busy_hold`) issues only frontdoor CSR writes (`csr_write`/`csr_read` over SEP_IN AXI) and passive hierarchical reads of `tb_zeroer_busy` / `tb_zeroer_gated_axi_clk` / `tb_output_axi_write_count`; no `force`/`deposit`/`uvm_hdl_*`/`.value =` write on any DUT-internal net in the P2 code path |
| F2 can't-fail checker | ✅ clean — `_p2_race_cell` computes `glitches` from live-sampled `(busy, enable)` pairs against the SPEC gating formula (`axi_clk_enable` must stay 1 while `busy==1`), independent of the calibration value; a real mid-busy glitch or missed same-cycle/1-after completion raises `AssertionError` (see rev1's STALE run, which *did* fail under the stricter pre-amendment contract, proving the fail path is live) |
| E1 skip-to-pass | ✅ clean — `body()` asserts `hasattr` on all required TB ports before use; no HDL path is skipped to reach PASS |
| E2 empty phase | ✅ clean — P2-S1/S2/S3 each program, observe, and assert; no log-and-return stub |
| S1 silent fail | ✅ clean — every mismatch (`observed_offset != target_offset`, resume-latency, glitch, missed completion, timeout) raises `AssertionError` with full diagnostic state; no mismatch is downgraded to `log.info`/`warning` |
| O1 checker disabled | ✅ clean |
| Phase-S obligations — L1 | ✅ clean — addresses sourced from `smc_addr_map.py` (generated `smc_addr.h`/`smc_base_config.h`, never a hand literal); X/Z raises `AssertionError` on every sampled signal; bounded waits (`P2_CALIB_TIMEOUT_SMC`, `P2_TRIAL_TIMEOUT_SMC`, `P2_FOLLOWON_BOUND_SMC`) all have a static fail-on-expiry path; regression-enrolled (`testlists/clock.toml`) |
| Phase-S obligations — L2 (needs the card) | ✅ clean — `[MERGED-EVIDENCE]`: NOGLITCH and COMPLETION each emit their own token from `results[label]`, no shared sole-proof line; `[NO-TAUTOLOGY]` guardrail: mid-busy-glitch expectation (`enable==1` while `busy==1`) is the SPEC gating formula, not a value copied from the DUT's own trace — only the *scheduling* of the race (via `busy_hold` calibration) references DUT timing, which is unavoidable for placing a cycle-exact race and does not weaken the pass/fail formula itself |

## Evidence appendix

<details>
<summary>Kept log + build identity</summary>

- Log: `hw/sys/smc/dv/build/runs/20260805_093933__verilator__smc_zeroer_axiclk_cg_test/smc_zeroer_axiclk_cg_test/logs/smc_zeroer_axiclk_cg_test.log`
  sha256 `5d8c44ab9eeb46dd701ddf35452be8158a81e178a278eaf841a541ea6497e377` — recomputed via
  `sha256sum`, matches the owner-supplied hash exactly (kept log only; rev1's
  `20260805_091625` FAIL log is STALE and not consulted per instruction).
- cocotb summary (L701-708): `smc_zeroer_axiclk_cg_test.smc_zeroer_axiclk_cg_test passed`,
  `TESTS=1 PASS=1 FAIL=0 SKIP=0`. No `result.json` present in this run directory — simulator
  identity taken from the log banner (`Verilator version 5.050 2026-07-01`, seed 1); this is
  informational (build-model fingerprint unavailable for this specific run), not a blocking
  mismatch, since nothing in the log or file layout contradicts the declared `compile_target:
  default` used by the sibling P1 run of the same anchor.
- Card: `SMC_CG_P2_002` revision 2, `hw/sys/smc/dv/tb/SMC_CLOCK_GATING_P2_VPLAN_DETAIL.md`,
  recomputed `record_sha256` = `7716914f...` — **matches** owner-supplied hash exactly
  (`manifest.py` `record_hash`, excluding `record_sha256`/`status`/`current`/`approved_*`).
  `status: approved`, `current: true`, `approved_by: minshaoho`.
- Parent testcase record: `SMC_CG_P2_002` in `SMC_CLOCK_GATING_P2_TESTCASE_PLAN.md`,
  `plan_revision: 1`, `testcase_revision: 1`, recomputed `record_sha256` =
  `53791893d0c2043a2cb1d773b4736eb35027ab47038d3b039c5053a239393681` — **matches** the card's
  `derived_from.testcase_record_sha256` exactly. Parent `status: approved`, `current: true`.
  No `ENTRY-STALE` / `ENTRY-PARENT-UNAPPROVED`.
- Canonical testcase name `smc_zeroer_axiclk_cg_test` consistent across card anchor, plan
  anchor, `smc_zeroer_axiclk_cg_test.py` class name, and `testlists/clock.toml` entry (L37-39,
  L91). No `ENTRY-IDENTITY-MISMATCH`.
- Address map: P2 helpers (`_p2_trigger_op`, `_program_cg`) reuse the same
  `ZEROER_CTRL_DEST_ADDR` / `ZEROER_CTRL_SIZE` / `ZEROER_CTRL_STATUS` / `CLOCK_GATE_CONTROL`
  symbols re-exported from `seq_lib/smc_addr_map.py`, which parses the generated
  `hw/sys/smc/regs/gen/c/smc_addr.h` / `smc_base_config.h` — no hand-copied literal address on
  the P2 proof path.
- Force/deposit audit (P2 code path only — `_p2_sample_cycle`, `_p2_trigger_op`,
  `_p2_measure_busy_hold`, `_p2_race_cell`, `_p2_extension`): zero `force`/`deposit`/
  `uvm_hdl_*`/`.value =` writes to any DUT-internal signal; all stimulus is frontdoor CSR
  writes via `SmcCsrSeq.csr_write`, all observation is `.value` reads on `tb_zeroer_busy` /
  `tb_zeroer_gated_axi_clk` (passive hierarchical taps, same ports the closed P1 grade already
  established as passive `assign`s).
- Regression enrollment confirmed unchanged: `hw/sys/smc/dv/testlists/clock.toml:37-39`.

</details>

<details>
<summary>Token / step cites (kept log `5d8c44ab...`)</summary>

| Checker | Log line | What the log shows | Impl |
|---|---|---|---|
| (setup) | 515 | `STEP P2-S1: SETUP: re-confirm zeroer idle baseline ...` | seq `:508` |
| (fence) | 516 | `FENCE SETUP @ 7134ns` | seq `:513` |
| (fence) | 559 | `FENCE FIRST-OP-BUSY @ 7722ns` (after `_p2_measure_busy_hold` returns `busy_hold=11`) | seq `:525` |
| (setup) | 560 | `STEP P2-S2: ... sweep the follow-on trigger across busy_hold=11 cycles at offsets [-1, 0, 1]` | seq `:527` |
| (fence) | 687 | `FENCE BOUNDARY-SWEEP(3-cells) @ 9396ns` | seq `:536` |
| (fence) | 688 | `FENCE FOLLOWON-OBSERVED @ 9396ns` | seq `:537` |
| CHK-ZEROER-AXICLK-NOGLITCH | 689 | all 3 cells: `mid_busy_glitches=0`; inter-busy gap logged (25/26/27 cycles) at each offset | seq `:539` |
| CHK-ZEROER-AXICLK-COMPLETION | 690 | scored cells (`offset=0,1`): `completed=1`; unscored cell (`offset=-1`): response logged, `scored=0` (no verdict per SF-005 carve-out) | seq `:550` |
| (setup) | 691 | `STEP P2-S3: TIMEOUT: the bounded wait ... has a finite bound ...` | seq `:561` |
| CHK-TIMEOUT-PATHS | 692 | `expired=0`, all 3 declared bounds logged, last-state diagnostic present | seq `:567` |
| CHK-NONVAC | 693 | `SETUP < FIRST-OP-BUSY < BOUNDARY-SWEEP(3-cells) < FOLLOWON-OBSERVED < PASS` — matches card's `proof` string verbatim | seq `:610` |
| (fence) | 694 | `FENCE PASS @ 9396ns` | seq `:616` |
| (result) | 695 | `smc_zeroer_axiclk_cg_test_seq P2 extension PASS` | seq `:617` |
| (VIP) | 696 | protocol VIP fence array replays all P1+P2 fence timestamps in order, `passed=True` | test.py `:45` |

</details>

<details>
<summary>Layer 1 / Layer 2 notes</summary>

- **Proof fence (SETUP → ACTION → RESPONSE → EFFECT → NONVAC), in temporal order:** SETUP
  (idle re-confirm, L515-516) → FIRST-OP-BUSY (op1 triggered + busy asserted + `busy_hold`
  measured via a *separate, unscored calibration operation* at L559) → BOUNDARY-SWEEP(3-cells)
  (all 3 required cells fired at their exact predicted offsets and *verified* post-hoc via
  `assert observed_offset == target_offset`, L687) → FOLLOWON-OBSERVED (L688) → both checker
  tokens emitted (L689-690) → CHK-TIMEOUT-PATHS (L692) → CHK-NONVAC ordering assertion (L693) →
  PASS (L694). `assert_fence_order`-style gating (`p2_terms == expected_p2_pre_pass`, seq
  L587-588) runs before the tokens are trusted.
- **Static sensitivity / real FAIL-ON path:** `_p2_race_cell` classifies every deasserted
  `axi_clk_enable` sample into `mid_busy_ranges` (op1 tail / op2 own span, both fail-on scope)
  vs. the strictly-inter-busy gap (permitted, logged). This is not a tautology: the expected
  value ("enable==1 whenever busy==1") is the SPEC's own `axi_clk_enable = disable_cg |
  zeroer_busy_o | ~rst_ni` formula, not a value read back from the DUT's own trace and compared
  to itself. The rev1 STALE run (`20260805_091625`, kept for provenance only, not used as
  evidence here) independently demonstrates the checker *can* fail: it failed under the
  stricter pre-amendment whole-boundary contract, which is direct proof this is not a
  can't-fail checker under either contract.
- **SF-005 carve-out honored exactly as scoped:** `CHK-ZEROER-AXICLK-COMPLETION`'s log line
  shows the `-1` (1-cycle-before) cell's response recorded (`write_addr_phase_seen=1,
  completed=1`) with `scored=0` — the implementation neither silently drops this response nor
  asserts a pass/fail verdict on it ahead of SF-005 (both are the card's explicit `fail_on`
  conditions for this checker, and neither fires). Only the `0`/`1` (same-cycle / 1-after)
  cells gate `completion_detail`/the batch `violations` assert.
- **Coverage:** feature_list `SMC-CG-ZEROER-AXICLK.S1` DIRECTED required cells
  `{new-trigger-1-cycle-before-busy-deassert, new-trigger-same-cycle-as-busy-deassert,
  new-trigger-1-cycle-after-busy-deassert}` — all 3 present in the retained log at
  `offset=-1,0,1` respectively (`coverage_artifact: null`, per feature_list). No seed-count
  floor applies (DIRECTED, `random_knobs: []`).
- **No merged evidence:** `CHK-ZEROER-AXICLK-NOGLITCH` and `CHK-ZEROER-AXICLK-COMPLETION` each
  emit an independent token built from `results[label]`, itself derived from independently
  sampled `(busy, enable)` timelines and write counts per cell — no shared sole-proof line.
  `CHK-NONVAC` (ordering, `proves: []`) and `CHK-TIMEOUT-PATHS` (integrity, `proves: []`) do not
  compete with the two substantive checkers for scenario proof.
- **No blind delay-sync on the proof path:** all P2 waits are `RisingEdge`/`ReadOnly`-sampled
  per-cycle loops (`_p2_sample_cycle`) with an explicit iteration bound and a static
  `AssertionError` on expiry; the only bare `Timer(1, unit="ps")` calls are the standard
  cocotb ReadOnly-phase exit technique, not a stand-in for a completion handshake.
  `CHK-NO-TAUTOLOGY` guardrail: the *scheduling* of the race (`busy_hold` from
  `_p2_measure_busy_hold`, a separate unscored calibration op) references DUT timing because
  the exact busy-hold duration is an implementation timing detail with no SPEC formula to
  derive it from; this is orthogonal to the *pass/fail expectation* itself (the SPEC gating
  formula), which never references DUT-observed timing. `observed_offset == target_offset` is
  a self-check on stimulus placement accuracy, not a DUT-correctness assertion.
- **Negative-evidence scan (complete kept log, lines 1-716):** no `ERROR`/`FATAL`/unhandled
  `Traceback`; only benign cocotb/library `DeprecationWarning`s (Immediate/units/task.kill
  renames) and the expected end-of-sim ROM-load banner after the cocotb region completes with
  `$finish`. No disabled/suppressed checker, no zero-check summary, no missing handle/path, no
  premature completion before `FENCE PASS`.
- **Relationship to the P1 grade:** this report covers only the P2 (`SMC_CG_P2_002`
  revision-2) checkers on the card. The P1 checkers (`CHK-ZAXI-GATE-OFF-IDLE`,
  `CHK-ZAXI-BUSY-ENABLE`, `CHK-ZAXI-DISABLE-CG`, `CHK-ZAXI-RESET-OVERRIDE`, P1's own
  `CHK-NONVAC`) are unchanged by this run (additive extension) and remain governed by the
  existing, separately-signed `smc_zeroer_axiclk_cg_test_GRADE.md` — not overwritten or
  re-graded here.

</details>

## Accepted waivers

| Finding | Rule | Where | Why | Approved by |
|---|---|---|---|---|
| — | — | — | none | — |

## Human signoff

- **signed_off_by:** minshaoho
- **signed_off_at:** 2026-08-05T18:04:00+08:00
- **decision:** Done — evidence accepted by owner standing order (if all checkers PROVEN,
  signoff minshaoho ISO+08:00).
- **note:** Fresh Skill 2 audit (auditor `cursor/claude/sonnet-5`, `run_id`
  `dv_test_audit-SMC_CG_P2_002-47744281-1e84-4dbb-bda6-dddc90c31d9c`), no carryover from any
  session that authored, implemented, or discussed this card. 4/4 PROVEN —
  EVIDENCE-CLOSED-AWAITING-SIGNOFF. Force/deposit check clean on the P2 code path. Rev1's
  STALE FAIL log (`20260805_091625`) was not consulted, per instruction and per policy
  freshness rule (superseded card revision).
