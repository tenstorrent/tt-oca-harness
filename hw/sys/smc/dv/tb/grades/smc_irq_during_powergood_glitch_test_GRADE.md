---
schema: dv-quality/v1
artifact: testcase-grade
testcase: smc_irq_during_powergood_glitch_test
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
- path: hw/sys/smc/dv/build/runs/20260806_094547__verilator__smc_irq_during_powergood_glitch_test/smc_irq_during_powergood_glitch_test/logs/smc_irq_during_powergood_glitch_test.log
  sha256: 68a7cf56a14654518451c25f7de98465b8b3dd50ab075235b60f4db373a17e1b
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
  artifact_ref: hw/sys/smc/dv/cocotb/seq_lib/smc_irq_during_powergood_glitch_test_seq.py:42-63
  observed: >
    Docstring claims no spurious IRQ due to the powergood glitch / recovery, but the
    sequence only issues SmcIrqOp.SAMPLE before POWERGOOD_LO and after a fixed recover
    wait. Between those points (kept log: SAMPLE #1 @4152ns → POWERGOOD_LO @4152ns →
    POWERGOOD_HI @4216ns → SAMPLE #2 @9016ns) there is no IRQ SAMPLE / RAW poll and
    scoreboard `_check_irq` never runs. A DUT that pulses sync/gpio/uart IRQ during the
    glitch window and returns to idle by the post-recover SAMPLE still yields two
    idle-zero items and cocotb PASS. Endpoint idle-zero alone cannot FAIL-ON the claimed
    mid-window property.
  closure_condition: >
    During the POWERGOOD_LO→recover window, continuously sample or poll the IRQ
    aggregates (or issue checked SAMPLE/RAW items) and FAIL if any observed non-idle
    value appears; keep the post-recovery idle-zero SAMPLE assert.
  waived_by: null
- id: FIND-002
  tag: '[NO-BLIND-DELAY-SYNC]'
  severity: Major
  artifact_ref: hw/sys/smc/dv/cocotb/seq_lib/smc_irq_during_powergood_glitch_test_seq.py:55-63
  observed: >
    After POWERGOOD_HI, recovery completion is `ClockCycles(dut.clk_ref_i,
    RECOVER_REF_CYCLES)` with RECOVER_REF_CYCLES=600, then the recovered IRQ SAMPLE.
    Kept log timing matches exactly (HI @4216ns → SAMPLE #2 @9016ns = 600×8ns). AXI
    agents log reset de-assert at 6540ns mid-delay, but the sequence does not wait on
    powergood_stable / primary-reset release (or any bounded handshake that fails on
    timeout with last-state diagnostics); the fixed delay stands in for recovery
    completion before the proof SAMPLE.
  closure_condition: >
    Replace the fixed recover-tail ClockCycles with a bounded wait on recovery signals
    that raises on expiry with last-state diagnostics, then issue the recovered IRQ
    SAMPLE / scoreboard compare.
  waived_by: null
- id: FIND-003
  tag: '[NO-DUMMY-DEAD-CODE]'
  severity: Minor
  artifact_ref: hw/sys/smc/dv/cocotb/seq_lib/smc_irq_during_powergood_glitch_test_seq.py:39-63
  observed: >
    Sequence stores `self.baseline_irq` and `self.recovered_irq` after the two SAMPLE
    dispatches, but nothing reads those attributes or compares baseline vs recovered.
    The live fail path is only scoreboard per-sample `resolvable` plus idle-zero on the
    three IRQ aggregates. The stored items therefore look like an unfinished
    cross-sample / glitch-delta compare that never runs.
  closure_condition: >
    Either assert a real baseline-vs-recovered (or mid-window) compare on the stored
    items, or drop the unused attributes and keep only the scoreboard path.
  waived_by: null
waivers: []
recommendation: NOT-READY
---

# Grade Report — smc_irq_during_powergood_glitch_test (standalone Layer 1)

**VERDICT: 0/0 PROVEN — NOT READY** (mode NO-CHECKBOX, no_contract_reason STANDALONE-REQUEST)

| Mode | Entry gate | Checkers | Findings | Recommendation |
|---|---|---|---|---|
| `NO-CHECKBOX` | — NOT-EVALUATED | 0/0 PROVEN | 🔴 1 Blocking · 🟠 1 Major · 🟡 1 Minor | ⛔ NOT-READY |

> No approved checkbox card or parent plan record governs this testcase. Layer 1 findings are
> the entire scope of this report. `NOT-READY` records the **absence of a closure claim, not a
> defect** in the test by itself.

## DELTA (re-audit vs prior grade `0/0 NOT-READY` on log `7470f560…`)

| Item | Prior (log `7470f560…`, PASS) | This audit (log `68a7cf56…`, PASS) |
|---|---|---|
| Verdict | 0/0 PROVEN — NOT READY | 0/0 PROVEN — NOT READY |
| Findings | 🔴 1 Blocking · 🟠 1 Major · 🟡 1 Minor | 🔴 1 Blocking · 🟠 1 Major · 🟡 1 Minor |
| FIND-001 `[CHECKER-NONVACUITY]` | open — no mid-window IRQ FAIL-ON | still open — seq sha256 unchanged; SAMPLE only at endpoints |
| FIND-002 `[NO-BLIND-DELAY-SYNC]` | open — fixed 600-cycle recover wait | still open — HI@4216ns → SAMPLE#2@9016ns = 600×8ns |
| FIND-003 `[NO-DUMMY-DEAD-CODE]` | open — unused baseline/recovered stores | still open — attributes still write-only |
| Kept log | `7470f560afa8e8b0569109c0b76f4bd04901801ec1b6779267b22cfadd80662a` | `68a7cf56a14654518451c25f7de98465b8b3dd50ab075235b60f4db373a17e1b` |
| Repo rev | `2ecc7b227e3926b253c65b5aac21239eec24ba5f` | `c10b6d63e0b3377f8e2fa38c138e2ea72cae92c7` |
| Waivers carried | none signed (`waivers: []`) | none (nothing to drop; no signed entries) |

## Your to-do — 3 items (🔴 1 Blocking · 🟠 1 Major · 🟡 1 Minor)

| # | Kind | Id | Severity / grade | Where |
|---|---|---|---|---|
| 1 | finding | FIND-001 | 🔴 Blocking | `smc_irq_during_powergood_glitch_test_seq.py:42-63` |
| 2 | finding | FIND-002 | 🟠 Major | `smc_irq_during_powergood_glitch_test_seq.py:55-63` |
| 3 | finding | FIND-003 | 🟡 Minor | `smc_irq_during_powergood_glitch_test_seq.py:39-63` |

<details>
<summary>1. FIND-001 — 🔴 Blocking <code>[CHECKER-NONVACUITY]</code> — glitch-window IRQ never FAIL-ON</summary>

- **Where:** `hw/sys/smc/dv/cocotb/seq_lib/smc_irq_during_powergood_glitch_test_seq.py:42-63`
- **Observed:** Between `POWERGOOD_LO` and the post-recover SAMPLE, no IRQ SAMPLE/poll runs; scoreboard `_check_irq` is only fed at the two endpoints (log: SAMPLE #1 @4152ns idle-zero; SAMPLE #2 @9016ns idle-zero). A mid-window pulse that returns to idle still yields cocotb PASS.
- **Closure:** Poll/sample IRQ aggregates during the glitch→recover window and FAIL on any non-idle value; keep the post-recovery idle-zero SAMPLE.

</details>

<details>
<summary>2. FIND-002 — 🟠 Major <code>[NO-BLIND-DELAY-SYNC]</code> — fixed 600-cycle recover wait</summary>

- **Where:** `hw/sys/smc/dv/cocotb/seq_lib/smc_irq_during_powergood_glitch_test_seq.py:55-63`
- **Observed:** `RECOVER_REF_CYCLES=600` after `POWERGOOD_HI` is the only recovery sync before the proof SAMPLE (HI @4216ns → SAMPLE #2 @9016ns). No bounded handshake wait with timeout diagnostics.
- **Closure:** Replace the fixed recover-tail `ClockCycles` with a bounded wait on recovery outputs that raises on expiry with last-state diagnostics, then SAMPLE IRQ.

</details>

<details>
<summary>3. FIND-003 — 🟡 Minor <code>[NO-DUMMY-DEAD-CODE]</code> — unused baseline_irq / recovered_irq</summary>

- **Where:** `hw/sys/smc/dv/cocotb/seq_lib/smc_irq_during_powergood_glitch_test_seq.py:39-63`
- **Observed:** `self.baseline_irq` / `self.recovered_irq` are stored after SAMPLE but never read or compared; live fail path is only scoreboard per-sample resolvable + idle-zero.
- **Closure:** Assert a real baseline-vs-recovered (or mid-window) compare, or drop the unused attributes.

</details>

**Then:** owner remediates FIND-001/002/003 and re-invokes `/dv_test_audit` on this leaf; Layer 2 needs an approved card (not invented here).

## All checkers

| Checker | Grade | Proof class | Covers | Findings |
|---|---|---|---|---|
| — | — | — | — | no card checkers (MODE=NO-CHECKBOX) |

### Layer 1 structural rule set

| Rule | Result |
|---|---|
| F1 fabricated verdict / backdoor write | ✅ clean — top-level `powergood_i` drive; DUT pin samples of `tb_sync_irq` / `tb_gpio_irq_any` / `tb_uart_irq_any`; no Force/deposit on proof path |
| F2 can't-fail checker | ✅ clean — scoreboard `assert item.resolvable` and idle-zero asserts can fail on X or stuck-asserted IRQ at SAMPLE points |
| E1 skip-to-pass | ✅ clean — unsupported ops raise; no missing-path skip-to-pass |
| E2 empty phase | ✅ clean — POWERGOOD_LO/HI + two IRQ SAMPLE dispatches present |
| S1 silent fail | ✅ clean — scoreboard uses `assert`; `check_phase` requires nonzero SAMPLE activity |
| O1 checker disabled | ✅ clean — IRQ analysis path active (log SAMPLE #1–#2) |
| Phase-S obligations — L1 | 🔴 Blocking — FIND-001 · 🟠 Major — FIND-002 · 🟡 Minor — FIND-003; X-aware `resolvable`; enrolled in `irq.toml` / `combined.toml` / `all.toml`; glitch-hold `GLITCH_REF_CYCLES=8` is stimulus width |
| Phase-S obligations — L2 (needs the card) | — not evaluated |

## Evidence appendix

<details>
<summary>Kept log + code proof-path notes</summary>

- Implementation: `hw/sys/smc/dv/cocotb/tests/smc_irq_during_powergood_glitch_test.py`
  sha256 `e34faab78f33a959fcf08d3d965cb2fd62743bc1e9f00a8eb5f372c4d3733b1d`
- Sequence: `hw/sys/smc/dv/cocotb/seq_lib/smc_irq_during_powergood_glitch_test_seq.py`
  sha256 `bf0c86bf3db3e3ca6d5de263edc8a3973ebf29b38bbd63fbee3a3c017956845f`
- Agent / scoreboard (proof path): `smc_irq_agent.py` / `smc_reset_agent.py` → `SmcScoreboard._check_irq` / `_check_reset`
- Log: `hw/sys/smc/dv/build/runs/20260806_094547__verilator__smc_irq_during_powergood_glitch_test/smc_irq_during_powergood_glitch_test/logs/smc_irq_during_powergood_glitch_test.log`
  sha256 `68a7cf56a14654518451c25f7de98465b8b3dd50ab075235b60f4db373a17e1b` (matches claimed)
- Seed: 1 · simulator: verilator 5.050 2026-07-01 · model fingerprint `2c815fa08277`
- `result.json`: `status: PASS`, `return_code: 0`, cocotb summary: `TESTS=1 PASS=1 FAIL=0 SKIP=0`
- Stimulus: IRQ SAMPLE → `POWERGOOD_LO` → 8 ref cycles → `POWERGOOD_HI` → 600 ref cycles → IRQ SAMPLE
- Observed in log: SAMPLE #1 @4152ns idle-zero; POWERGOOD_LO @4152ns; POWERGOOD_HI @4216ns; AXI reset de-assert @6540ns; SAMPLE #2 @9016ns idle-zero; no mid-window IRQ SAMPLE
- Fail path (static): non-resolvable pins or any idle IRQ aggregate != 0 at SAMPLE → AssertionError; no mid-window FAIL-ON
- Enrollment: `hw/sys/smc/dv/testlists/irq.toml`, `combined.toml`, `all.toml`
- Bring-up trailer: efuse/ROM hex preload lines after cocotb PASS; not used by pin-sample proof path
- Entry gate / Layer 2 not evaluated (MODE=NO-CHECKBOX)
- Provenance: legacy (`test_author.run_id: unknown`)

</details>

<details>
<summary>Stimulus / sample cites (kept log <code>68a7cf56…</code>)</summary>

| Step | Line (approx) | What the log shows | Impl |
|---|---|---|---|
| bring-up | 265–266 | powergood + cold release | `smc_base_test` |
| IRQ SAMPLE #1 | 279–281 | idle-zero, scoreboard #1 | seq baseline SAMPLE / `_check_irq` |
| POWERGOOD_LO | 282–283 | `powergood_i=0` | reset agent |
| POWERGOOD_HI | 315–316 | `powergood_i=1` after 8 ref cycles | reset agent + `GLITCH_REF_CYCLES` |
| AXI reset release | ~327 | reset de-assert @6540ns (mid recover delay) | TB AXI VIP |
| IRQ SAMPLE #2 | 338–340 | idle-zero after 600 ref cycles | seq recovered SAMPLE / `_check_irq` |
| cocotb result | 343–349 | `PASS` / `TESTS=1 PASS=1 FAIL=0 SKIP=0` | — |

</details>

## Not concluded

- Whether this leaf proves the SPEC IRQ-during-powergood-glitch properties a future card would require (O2) — Skill 3.
- Completeness against a feature_list — no inventory applies in STANDALONE-REQUEST.
- Any closure or PROVEN checker claim — MODE=NO-CHECKBOX forbids inventing checkers.

## Accepted waivers

| Finding | Rule | Where | Why | Approved by |
|---|---|---|---|---|
| — | — | — | none | — |
