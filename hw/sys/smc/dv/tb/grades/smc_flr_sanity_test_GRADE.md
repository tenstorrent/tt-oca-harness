---
schema: dv-quality/v1
artifact: testcase-grade
testcase: smc_flr_sanity_test
ip: SMC_ACTIVE_REGRESSION
anchor: null
mode: NO-CHECKBOX
no_contract_reason: STANDALONE-REQUEST
entry_status: NOT-EVALUATED
repository_revision: c10b6d63e0b3377f8e2fa38c138e2ea72cae92c7
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
build_config: default
simulator: verilator
simulator_version: 5.050 2026-07-01
compile_target: default
model_fingerprint: 2c815fa08277
compile_inputs_sha256: null
seeds:
- 1
logs:
- path: hw/sys/smc/dv/build/runs/20260806_094554__verilator__smc_flr_sanity_test/smc_flr_sanity_test/logs/smc_flr_sanity_test.log
  sha256: a6b0cb99fe8f12690f581442da3e268d1d1cf60161c697614a861b8743b56948
test_author:
  human_id: unknown
  run_id: unknown
  model:
    provider: unknown
    family: unknown
    version: unknown
auditor:
  human_id: minshaoho
  run_id: cursor/grok/4.5-reaudit-20260806
  model:
    provider: cursor
    family: grok
    version: '4.5'
exceptions: []
checkers: []
findings:
- id: FIND-001
  tag: '[CHECKER-NONVACUITY]'
  severity: Blocking
  artifact_ref: hw/sys/smc/dv/cocotb/seq_lib/smc_flr_sanity_test_seq.py:67-98
  observed: >
    Cool-reset is the FLR-like stimulus (`COOL_RST_LO`/`HI`), but no FAIL-ON check
    observes a cool effect. Pre-cool `SCRATCH_COLD_WARM_0` is written `0xF1A0_0001` and
    never re-read after the pulse to prove warm-domain clear; post-cool proof only
    re-reads RO `CHIP_CONFIG_VERSION_LO` (same constant as baseline), then write/read
    scratch `0` (succeeds whether cool ran), and a single post-delay `SAMPLE` requiring
    already-true released levels (`powergood_stable==1`, primary resets==1). Kept log:
    cool assert @ 16878 ns, release @ 17032 ns, SAMPLE all-1s @ 23432 ns with no
    mid-cool RAW/SAMPLE compare. A DUT that ignores `rst_cool_ni` still yields the same
    post-stable SAMPLE and CSR path, so cocotb PASS does not prove cool/FLR recovery.
  closure_condition: >
    After cool assert (or before recovery completes), assert at least one observable
    cool effect that fails if cool is ignored (e.g. mid-cool reset/status sample, or
    post-cool readback that `SCRATCH_COLD_WARM_0` cleared from the pre-cool pattern),
    then keep the post-recovery SAMPLE / SEP_IN AXI recovery compares.
  waived_by: null
- id: FIND-002
  tag: '[NO-BLIND-DELAY-SYNC]'
  severity: Major
  artifact_ref: hw/sys/smc/dv/cocotb/seq_lib/smc_flr_sanity_test_seq.py:78-81
  observed: >
    After `COOL_RST_HI`, recovery completion is `ClockCycles(dut.clk_ref_i, 800)` then
    `SAMPLE`. Kept log: cool release @ 17032 ns → SAMPLE @ 23432 ns = exactly 800×8 ns
    ref cycles. There is no bounded predicate wait on recovery outputs that fails on
    expiry with last-state diagnostics; the fixed delay stands in for post-cool settle
    before the stability asserts.
  closure_condition: >
    Replace the fixed 800-cycle settle with a bounded wait on the recovery signals
    (released / stable levels) that raises on timeout with last-state diagnostics, then
    SAMPLE / scoreboard-compare.
  waived_by: null
waivers: []
recommendation: NOT-READY
---

# Grade Report — smc_flr_sanity_test (standalone Layer 1)

**VERDICT: 0/0 PROVEN — NOT READY** (mode NO-CHECKBOX, no_contract_reason STANDALONE-REQUEST)

| Mode | Entry gate | Checkers | Findings | Recommendation |
|---|---|---|---|---|
| `NO-CHECKBOX` | — NOT-EVALUATED | 0/0 PROVEN | 🔴 1 Blocking · 🟠 1 Major | ⛔ NOT-READY |

> No approved checkbox card or parent plan record governs this testcase. Layer 1 findings
> are the entire scope of this report. `NOT-READY` records the **absence of a closure
> claim, not a defect**. Kept log is a sim PASS (seed 1); Layer 2 was not entered.

## DELTA (re-audit vs prior grade `0/0 NOT-READY` on log `82ca662f…`)

| Item | Prior (log `82ca662f…`) | This audit (log `a6b0cb99…`) |
|---|---|---|
| Verdict | 0/0 PROVEN — NOT READY | 0/0 PROVEN — NOT READY |
| Findings | 🔴 1 Blocking · 🟠 2 Major | 🔴 1 Blocking · 🟠 1 Major |
| Prior FIND-001 `[CHECKER-NONVACUITY]` | open — cool effect never FAIL-ON | still open — renumbered FIND-001 |
| Prior FIND-002 `[ADDRESS-FROM-AUTHORITATIVE-MAP]` | open — hand-copied `0xC000_2900` / `0xC000_2880` | **closed** — seq now uses `smc_addr(...)` from `smc_addr_map` / `smc_addr.h` |
| Prior FIND-003 `[NO-BLIND-DELAY-SYNC]` | open — fixed 800-cycle post-cool settle | still open — renumbered FIND-002; HI→SAMPLE still 800×8 ns |
| Kept log | `82ca662f55c50cb33b93c42096ad1ba1b57e7b2fd6556625975dca102ae880bd` PASS seed=1 | `a6b0cb99fe8f12690f581442da3e268d1d1cf60161c697614a861b8743b56948` PASS seed=1 |
| Waivers carried | none signed (`waivers: []`; nothing to drop) | none |

## Your to-do — 2 items (🔴 1 Blocking · 🟠 1 Major)

| # | Sev | Item |
|---|---|---|
| 1 | 🔴 Blocking | FIND-001 `[CHECKER-NONVACUITY]` — cool effect never FAIL-ON |
| 2 | 🟠 Major | FIND-002 `[NO-BLIND-DELAY-SYNC]` — fixed 800-cycle post-cool settle |

<details>
<summary>1. 🔴 Blocking — FIND-001 `[CHECKER-NONVACUITY]` at cool/FLR proof path</summary>

Cool pulse is driven, but post-cool checks only re-prove released reset levels and a
generic SEP_IN AXI path (RO version + scratch write/read `0`). The pre-cool scratch
pattern is never used as a cool-effect oracle, and no mid-cool sample is FAIL-ON compared.
A no-effect DUT still PASSes.

**Close when:** assert at least one cool-specific effect (mid-cool status and/or
post-cool scratch clear from the pre-cool pattern), then keep recovery SAMPLE / AXI
compares.

</details>

<details>
<summary>2. 🟠 Major — FIND-002 `[NO-BLIND-DELAY-SYNC]` at post-cool settle</summary>

`ClockCycles(..., 800)` after `COOL_RST_HI` gates the stability SAMPLE (log gap = 800 ref
cycles). No bounded handshake wait with fail-on-expiry.

**Close when:** recovery proof uses a predicate wait with fail-on-expiry and last-state
diagnostics, not a blind cycle count.

</details>

**Then:** owner remediates FIND-001/002 in the sequence (and any scoreboard expect for
mid-cool if used), re-keeps a PASS log, and re-invokes `/dv_test_audit`. Do not invent a
card here (`STANDALONE-REQUEST`).

## All checkers

| Checker | Grade | Proof class | Covers | Findings |
|---|---|---|---|---|
| — | — | — | — | no card checkers (MODE=NO-CHECKBOX) |

### Layer 1 structural rule set

| Rule | Result |
|---|---|
| F1 fabricated verdict / backdoor write | ✅ clean — pin drive via `SmcResetDriver` on top-level `rst_cool_ni`; samples top-level status outputs; SYS AXI frontdoor; no force/deposit on proof path |
| F2 can't-fail checker | ✅ clean — post-stable `SAMPLE` and SYS AXI `expected` compares can fail on stuck recovery / wrong rdata; cool-stimulus vacuity filed under Phase-S, not F2 |
| E1 skip-to-pass | ✅ clean — missing `dispatch_reset` would raise; no HDL-path skip-to-pass |
| E2 empty phase | ✅ clean — baseline CSR, cool pulse, SAMPLE, recovery CSR, access-count gate all execute |
| S1 silent fail | ✅ clean — scoreboard SYS AXI / SAMPLE asserts raise; sequence sample and `accesses==6` gates raise `AssertionError` |
| O1 checker disabled | ✅ clean — scoreboard reset and SYS AXI checks remain enabled |
| Phase-S obligations — L1 | 🔴 Blocking — FIND-001 · 🟠 Major — FIND-002; X-aware `is_resolvable`; addresses via `smc_addr`; enrolled in `batch_d.toml` / `all.toml` / `vplan_triplets.toml` |
| Phase-S obligations — L2 (needs the card) | — not evaluated |

## Evidence appendix

<details>
<summary>Kept log + code proof-path notes</summary>

- Log: `hw/sys/smc/dv/build/runs/20260806_094554__verilator__smc_flr_sanity_test/smc_flr_sanity_test/logs/smc_flr_sanity_test.log`
  sha256 `a6b0cb99fe8f12690f581442da3e268d1d1cf60161c697614a861b8743b56948`
  (verified via `sha256sum`; matches invoker hint)
- Seed: 1 · simulator: verilator 5.050 2026-07-01 · model fingerprint `2c815fa08277`
- `result.json`: `status: PASS`, `return_code: 0`, cocotb summary:
  `TESTS=1 PASS=1 FAIL=0 SKIP=0`
- Test: `hw/sys/smc/dv/cocotb/tests/smc_flr_sanity_test.py` starts
  `smc_flr_sanity_test_seq` on `sys_axi_agent.sequencer` with `dispatch_reset` →
  `reset_agent` via `_OneShot`
- Seq proof path: `smc_flr_sanity_test_seq.py` → `SmcSysAxiAgent` /
  `SmcResetAgent` / `SmcScoreboard._check_sys_axi` + `_check_reset`
- SYS AXI cites: VERSION_LO baseline `0x100a0` @ 16662 ns; scratch write/read
  `0xf1a00001` @ 16770/16878 ns; VERSION_LO recovery @ 23538 ns; scratch restore `0`
  @ 23646/23754 ns (scoreboard checks #1–#6)
- Cool cites: `rst_cool_ni=0` @ 16878 ns; `=1` @ 17032 ns; SAMPLE all-1s @ 23432 ns
- Blind recover cite: HI→SAMPLE gap = 800 ref cycles × 8 ns
- Address map cite: `smc_addr("SMC_TOP_SMC_MISC_WRAP_CHIP_CONFIG_BASE_ADDR")` →
  `0xC0002900`; `smc_addr("SMC_TOP_SMC_MISC_WRAP_SCRATCH_COLD_WARM_BASE_ADDR")` →
  `0xC0002880` (matches log frontdoor addresses)
- Enrollment: `hw/sys/smc/dv/testlists/batch_d.toml`, `all.toml`, `vplan_triplets.toml`
- Bring-up trailer: efuse hex + ROM `$readmemh` — time-0 image load; not used as golden
  for these checks (policy §6 standing preload exception; off this proof path)
- No unexplained `ERROR`/`FATAL`/`Traceback`; only cocotb deprecation warnings
- Provenance: legacy (`test_author.run_id: unknown`); auditor
  `cursor/grok/4.5-reaudit-20260806`

</details>

## Not concluded

- Whether the FLR/cool path checks the SPEC properties a future card would require (O2) —
  Skill 3.
- Completeness against a feature_list — no inventory applies in STANDALONE-REQUEST.
- Any closure or PROVEN checker claim — MODE=NO-CHECKBOX forbids inventing checkers from
  the passing log.

## Accepted waivers

| Finding | Rule | Where | Why | Approved by |
|---|---|---|---|---|
| — | — | — | none | — |
