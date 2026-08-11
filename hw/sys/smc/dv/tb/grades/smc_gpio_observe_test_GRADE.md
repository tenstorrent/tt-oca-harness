---
schema: dv-quality/v1
artifact: testcase-grade
testcase: smc_gpio_observe_test
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
- path: hw/sys/smc/dv/build/runs/20260806_094544__verilator__smc_gpio_observe_test/smc_gpio_observe_test/logs/smc_gpio_observe_test.log
  sha256: 228801933173a7bc8952010ead725608ab671e18d5fa8e262bcf58c5e4ab80dc
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
  tag: '[NO-DUMMY-DEAD-CODE]'
  severity: Major
  artifact_ref: hw/sys/smc/dv/cocotb/env/smc_scoreboard.py:139-141
  observed: >-
    After `assert item.resolvable`, `_check_gpio` asserts
    `core2pad_any` / `core2pad_en_any` / `pad2core_en_any` `in (0, 1)`.
    The driver only sets those fields to `int(sig)` when resolvable, else `-1`,
    so once `resolvable` is True the three range asserts cannot fail on any RTL.
    They read as active level checks while the comment admits levels are not
    GPIO-diagnostic; real fail path is only resolvability. This test's entire
    scenario is one GPIO SAMPLE, so the dead range guards sit on its sole
    scoreboard proof path.
  closure_condition: >-
    Remove the tautological `in (0, 1)` asserts (keep `resolvable`), or replace
    them with an independently derived exact expectation that can fail on wrong
    levels when a future card requires pad-level proof.
  waived_by: null
- id: FIND-002
  tag: '[NO-DUMMY-DEAD-CODE]'
  severity: Minor
  artifact_ref: hw/sys/smc/dv/cocotb/seq_lib/smc_gpio_observe_test_seq.py:15-22
  observed: >-
    Sequence stores the completed SAMPLE in `self.sample` and the test module
    docstring claims "all three should read 0 after cold-reset release", but
    nothing reads `self.sample` or asserts levels. Agent/scoreboard document
    that idle OR-aggregates are not GPIO-diagnostic and typically read 1; kept
    log shows `(1, 1, 1)`. The unused field plus stale idle-0 prose resemble an
    unfinished level check.
  closure_condition: >-
    Drop unused `self.sample` and align the test docstring with agent/scoreboard
    (proof is resolvability only; idle aggregates may be 1 due to LSIO), or wire
    a fail-capable exact expectation if a future card requires level proof.
  waived_by: null
waivers: []
recommendation: NOT-READY
---

# Grade Report — smc_gpio_observe_test (standalone Layer 1)

**VERDICT: 0/0 PROVEN — NOT READY** (mode NO-CHECKBOX, no_contract_reason STANDALONE-REQUEST)

| Mode | Entry gate | Checkers | Findings | Recommendation |
|---|---|---|---|---|
| `NO-CHECKBOX` | — NOT-EVALUATED | 0/0 PROVEN | 🟠 1 Major · 🟡 1 Minor | ⛔ NOT-READY |

> No approved checkbox card or parent plan record governs this testcase
> (`STANDALONE-REQUEST` / active-regression L1 wave). Layer 1 findings are the entire
> scope of this report. `NOT-READY` records the **absence of a closure claim, not a
> defect** in the test by itself.

## DELTA (re-audit vs prior grade `0/0 NOT-READY` on log `42c97a75…`)

| Item | Prior (log `42c97a75…`, PASS) | This audit (log `22880193…`, PASS) |
|---|---|---|
| Verdict | 0/0 PROVEN — NOT READY | 0/0 PROVEN — NOT READY |
| Findings | 🟠 1 Major · 🟡 1 Minor | 🟠 1 Major · 🟡 1 Minor |
| FIND-001 `[NO-DUMMY-DEAD-CODE]` | open — tautological `in (0, 1)` after resolvable | still open — same `_check_gpio` path; scoreboard hash unchanged |
| FIND-002 `[NO-DUMMY-DEAD-CODE]` | open — unused `self.sample` + idle-0 docstring | still open — seq/test hashes unchanged; log still `(1, 1, 1)` |
| Kept log | `42c97a75041d9009efe89f88dc4e6034c44630444fbfff338bd435dc1ad8ecee` | `228801933173a7bc8952010ead725608ab671e18d5fa8e262bcf58c5e4ab80dc` |
| repository_revision | `2ecc7b22…` | `c10b6d63…` |
| Waivers carried | none signed (`waivers: []`) | none (nothing to drop; no signed entries) |

## Your to-do — 2 items (🟠 1 Major · 🟡 1 Minor)

| # | Sev | Item |
|---|---|---|
| 1 | 🟠 Major | FIND-001 `[NO-DUMMY-DEAD-CODE]` — GPIO range asserts can't fail after resolvable |
| 2 | 🟡 Minor | FIND-002 `[NO-DUMMY-DEAD-CODE]` — unused `self.sample` + stale idle-0 docstring |

<details>
<summary>1. 🟠 Major FIND-001 — drop or replace tautological GPIO range asserts</summary>

- **Where:** `hw/sys/smc/dv/cocotb/env/smc_scoreboard.py:139-141` (proof-path helper used by this observe test)
- **Observed:** `_check_gpio` asserts each aggregate `in (0, 1)` only after `assert item.resolvable`. Driver sets `0`/`1` when resolvable and `-1` otherwise, so the range guards never fire once resolvable passes; they resemble value checks the comment says are intentionally not proven.
- **Closure:** Drop the tautological range asserts, or replace with a fail-capable exact expectation when a card requires pad-level proof (today's observe only needs X-free observability).

</details>

<details>
<summary>2. 🟡 Minor FIND-002 — use or drop `self.sample`; fix idle-0 docstring</summary>

- **Where:** `hw/sys/smc/dv/cocotb/seq_lib/smc_gpio_observe_test_seq.py:15-22` (plus test module docstring)
- **Observed:** `self.sample` is assigned and never read; test docstring claims idle aggregates read `0`, while agent/scoreboard and kept log show `(1, 1, 1)` with levels intentionally unchecked.
- **Closure:** Remove the dead field and fix the docstring to match resolvability-only proof, or add a real level compare if a card requires it.

</details>

**Then:** owner may leave this as enrolled smoke under STANDALONE-REQUEST, or allocate a real IP pin + card via `/dv_vplan_gen` before any closure claim; re-invoke `/dv_test_audit smc_gpio_observe_test` after FIND-001/FIND-002 hygiene if fixed.

## All checkers

| Checker | Grade | Proof class | Covers | Findings |
|---|---|---|---|---|
| — | — | — | — | no card checkers (MODE=NO-CHECKBOX) |

### Layer 1 structural rule set

| Rule | Result |
|---|---|
| F1 fabricated verdict / backdoor write | ✅ clean — passive SAMPLE of `tb_gpio_core2pad_any` / `tb_gpio_core2pad_en_any` / `tb_gpio_pad2core_en_any`; no Force/deposit on proof path |
| F2 can't-fail checker | ✅ clean — scoreboard `assert item.resolvable` can fail on X; range guards are dead (see FIND-001) |
| E1 skip-to-pass | ✅ clean — unsupported op raises; no missing-path skip-to-pass |
| E2 empty phase | ✅ clean — body dispatches one SAMPLE item into the GPIO agent / scoreboard |
| S1 silent fail | ✅ clean — scoreboard asserts raise; `check_phase` fails if zero SAMPLE items |
| O1 checker disabled | ✅ clean — GPIO analysis path active (log sample #1) |
| Phase-S obligations — L1 | 🟠 Major — FIND-001 · 🟡 Minor — FIND-002; else X-aware `resolvable`, seed logged, enrolled in `gpio.toml`/`all.toml`, ROM/efuse preload is post-PASS bring-up trailer |
| Phase-S obligations — L2 (needs the card) | — not evaluated |

## Evidence appendix

<details>
<summary>Kept log + code proof-path notes</summary>

- Implementation: `hw/sys/smc/dv/cocotb/tests/smc_gpio_observe_test.py`
  sha256 `27fae85ce869ef0fd4b547502044655d0c851be64dcf3dd45833c3dd61ce186d`
- Sequence: `hw/sys/smc/dv/cocotb/seq_lib/smc_gpio_observe_test_seq.py`
  sha256 `b3f68ce38ef69d6c4343625990bc3ca1e65f319e1508cf3dfc6899bb1e5ef434`
- Agent / scoreboard (proof path): `smc_gpio_agent.py` → `SmcScoreboard._check_gpio`
  (agent sha256 `24ee9592dba79e75ce1230777d29aeecec355cce2b910060eab6a315923741a2`;
  scoreboard sha256 `d0508fd1e52db630eb7b85de60872460d8bf969ae4fcb67cd5a172bd85a15495`)
- Log: `hw/sys/smc/dv/build/runs/20260806_094544__verilator__smc_gpio_observe_test/smc_gpio_observe_test/logs/smc_gpio_observe_test.log`
  sha256 `228801933173a7bc8952010ead725608ab671e18d5fa8e262bcf58c5e4ab80dc`
  (verified via `manifest.py hash-file`; matches invoker hint)
- Seed: 1 · simulator: verilator 5.050 2026-07-01 · model fingerprint `2c815fa08277`
- `result.json`: `status: PASS`, `return_code: 0`, cocotb summary: `TESTS=1 PASS=1 FAIL=0 SKIP=0`
- Stimulus: 1× `SmcGpioOp.SAMPLE` after cold-reset bring-up (no CSR programming)
- Observed in log: GPIO SAMPLE #1 at 4152 ns, `resolvable=True`, `core2pad_any=1`, `core2pad_en_any=1`, `pad2core_en_any=1`; `FUNC_COV_VALUE bin=gpio_state value=(1, 1, 1)`
- Fail path (static): non-resolvable pins → AssertionError; level values intentionally not asserted (agent note: OR-reduction over LSIO-idle bus); no `CHK-*` tokens (none required without a card)
- Enrollment: `hw/sys/smc/dv/testlists/gpio.toml`, `all.toml`
- Bring-up trailer: efuse/ROM hex preload lines after cocotb PASS; not used by pin-sample proof path
- Entry gate / Layer 2 not evaluated (MODE=NO-CHECKBOX)
- Provenance: legacy (`test_author.run_id: unknown`)
- Re-audit: auditor `run_id` `cursor/grok/4.5-reaudit-20260806` (differs from prior `cursor/grok/4.5/smc_gpio_observe_test-20260806`)

</details>

<details>
<summary>Stimulus / sample cites (kept log <code>22880193…</code>)</summary>

| Step | Line (approx) | What the log shows | Impl |
|---|---|---|---|
| bring-up | 264–267 | powergood + cold release | `smc_base_test` |
| driver ready | 271 | GPIO observer ready | `smc_gpio_agent` |
| SAMPLE #1 | 279–281 | `(1,1,1)` resolvable; scoreboard #1 + cov | seq `:17–21` / `_check_gpio` |
| cocotb result | 284–290 | `PASS` / `TESTS=1 PASS=1 FAIL=0 SKIP=0` | — |

</details>

## Not concluded

- Whether a single idle GPIO OR-aggregate SAMPLE proves the SPEC properties a future card would require (O2) — Skill 3.
- Completeness against a feature_list — no inventory applies in STANDALONE-REQUEST.
- Any closure or PROVEN checker claim — MODE=NO-CHECKBOX forbids inventing checkers.

## Accepted waivers

| Finding | Rule | Where | Why | Approved by |
|---|---|---|---|---|
| — | — | — | none | — |
