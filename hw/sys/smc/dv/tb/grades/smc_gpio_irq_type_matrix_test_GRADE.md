---
schema: dv-quality/v1
artifact: testcase-grade
testcase: smc_gpio_irq_type_matrix_test
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
- path: hw/sys/smc/dv/build/runs/20260806_094544__verilator__smc_gpio_irq_type_matrix_test/smc_gpio_irq_type_matrix_test/logs/smc_gpio_irq_type_matrix_test.log
  sha256: db347a7a961395dd36e20ba18342ece06f5f9934844063417e50b36e09d4c27d
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
  tag: '[ADDRESS-FROM-AUTHORITATIVE-MAP]'
  severity: Major
  artifact_ref: hw/sys/smc/dv/cocotb/seq_lib/smc_gpio_irq_type_matrix_test_seq.py:26-34
  observed: >-
    GPIO0 `DATA_CTRL` address is now imported via
    `smc_indexed_addr("SMC_TOP_GPIO_INTF_DATA_CTRL_BASE_ADDR", 0)` and the kept
    log writes `0xc0003000` (matches PeakRDL). Field encodes on the proof path
    remain hand-shifted literals (`_RX_ENABLE = 2 << 4`, `_IF_ENABLE = 1 << 16`,
    `_IRQ_ENABLE = 1 << 18`, `_TYPE_* = n << 20`) instead of symbols from
    generated `hw/ip/gpio/regs/gen/c/gpio_intf.h`
    (`GPIO_INTF__DATA_CTRL__ENABLE_RX_TX_*` /
    `INTERFACE_ENABLE_*` / `INTERRUPT_ENABLE_*` / `INTERRUPT_TYPE_*`). Numeric
    values currently match the header (CFG `0x50020` / `0x150020`), so identity
    is correct today, but RDL regen can silently rot the polarity matrix.
  closure_condition: >-
    Import DATA_CTRL field masks/bit positions from generated `gpio_intf.h`
    (or an `smc_addr_map` helper that loads those symbols) and build
    `CFG_ACTIVE_HIGH` / `CFG_ACTIVE_LOW` from them; re-keep a PASS log.
  waived_by: null
- id: FIND-002
  tag: '[NO-BLIND-DELAY-SYNC]'
  severity: Major
  artifact_ref: hw/sys/smc/dv/cocotb/seq_lib/smc_gpio_irq_type_matrix_test_seq.py:36-50
  observed: >-
    Every IRQ sample after pad drive uses fixed `_SETTLE = 24` `ClockCycles`
    then asserts `tb_gpio_irq_any`, with no bounded predicate wait that fails on
    expiry. The settle stands in for IRQ assertion/deassertion completion; under
    a slower path the same delay would sample too early and pass/fail by luck.
  closure_condition: >-
    Replace settle-then-sample with a bounded wait for the expected
    `tb_gpio_irq_any` level (and the complementary deassert) that raises on
    timeout with last-state diagnostics; keep a fixed delay only if that latency
    itself is the SPEC quantity under test.
  waived_by: null
waivers: []
recommendation: NOT-READY
---

# Grade Report — smc_gpio_irq_type_matrix_test (standalone Layer 1)

**VERDICT: 0/0 PROVEN — NOT READY** (mode NO-CHECKBOX, no_contract_reason STANDALONE-REQUEST)

| Mode | Entry gate | Checkers | Findings | Recommendation |
|---|---|---|---|---|
| `NO-CHECKBOX` | — NOT-EVALUATED | 0/0 PROVEN | 🟠 2 Major | ⛔ NOT-READY |

> No approved checkbox card or parent plan record governs this testcase
> (`STANDALONE-REQUEST` / active-regression L1 wave). Layer 1 findings are the entire
> scope of this report. `NOT-READY` records the **absence of a closure claim, not a
> defect** in the test by itself. Kept log is a sim **PASS** (seed 1): both polarity
> CSR writes land on GPIO0 `DATA_CTRL` and the matrix success log fires — Layer 2
> entry is still not evaluated in this mode.

## DELTA (re-audit vs prior grade `0/0 NOT-READY` on log `30ada6e3…`)

| Item | Prior (log `30ada6e3…`, FAIL) | This audit (log `db347a7a…`, PASS) |
|---|---|---|
| Verdict | 0/0 PROVEN — NOT READY | 0/0 PROVEN — NOT READY |
| Findings | 🔴 1 Blocking · 🟠 1 Major | 🟠 2 Major |
| Prior FIND-001 address | open Blocking — `0xC0004000` = AVSBus, not GPIO0 | **closed** — `smc_indexed_addr(...)` → `0xc0003000`; log L280–L299 writes OKAY |
| Field encodes | bundled under prior Blocking FIND-001 | **open** as FIND-001 Major — still hand-shifted vs `gpio_intf.h` |
| Prior FIND-002 settle | open Major `[NO-BLIND-DELAY-SYNC]` | **still open** as FIND-002 Major — `_SETTLE = 24` unchanged |
| Kept log | FAIL `active-high: pad high did not assert IRQ` | PASS seed=1; success log L302; `assert accesses == 2` reached |
| Waivers carried | none signed (`waivers: []`; nothing to drop) | none |

## Your to-do — 2 items (🟠 2 Major)

| # | Sev | Item |
|---|---|---|
| 1 | 🟠 Major | FIND-001 `[ADDRESS-FROM-AUTHORITATIVE-MAP]` — hand-shifted DATA_CTRL field encodes |
| 2 | 🟠 Major | FIND-002 `[NO-BLIND-DELAY-SYNC]` — fixed 24-cycle settle before IRQ sample |

<details>
<summary>1. 🟠 Major — FIND-001 <code>[ADDRESS-FROM-AUTHORITATIVE-MAP]</code> at field encode literals</summary>

- **Where:** `hw/sys/smc/dv/cocotb/seq_lib/smc_gpio_irq_type_matrix_test_seq.py:26-34`
- **Observed:** Address identity is fixed. Field bit packs
  (`_RX_ENABLE` / `_IF_ENABLE` / `_IRQ_ENABLE` / `_TYPE_*`) are still hand-shifted;
  they currently equal `gpio_intf.h` masks/positions (CFG `0x50020` /
  `0x150020`) but are not imported from the generated map.
- **Closure:** Build CFGs from `GPIO_INTF__DATA_CTRL__*` symbols in
  `hw/ip/gpio/regs/gen/c/gpio_intf.h` (or an `smc_addr_map` loader); re-keep PASS log.

</details>

<details>
<summary>2. 🟠 Major — FIND-002 <code>[NO-BLIND-DELAY-SYNC]</code> at <code>_drive</code> settle</summary>

- **Where:** `hw/sys/smc/dv/cocotb/seq_lib/smc_gpio_irq_type_matrix_test_seq.py:36-50`
- **Observed:** `_SETTLE = 24` `ClockCycles` then IRQ sample — completion sync by
  magic cycle count, not a TIMEOUT-failing predicate wait.
- **Closure:** Bounded wait for expected `tb_gpio_irq_any` level with fail-on-expiry
  and last-state diagnostics.

</details>

**Then:** owner imports field symbols (FIND-001) and replaces the blind settle
(FIND-002), re-keeps a PASS log, and re-invokes
`/dv_test_audit smc_gpio_irq_type_matrix_test`. Do not invent a card here
(`STANDALONE-REQUEST`).

## All checkers

| Checker | Grade | Proof class | Covers | Findings |
|---|---|---|---|---|
| — | — | — | — | no card checkers (MODE=NO-CHECKBOX) |

### Layer 1 structural rule set

| Rule | Result |
|---|---|
| F1 fabricated verdict / backdoor write | ✅ clean — frontdoor SEP_IN AXI CSR write + top-level `tb_gpio_ext_drive_*` pad inject; samples `tb_gpio_irq_any`; no force/deposit of IRQ success |
| F2 can't-fail checker | ✅ clean — polarity / clear asserts raise; prior kept FAIL proved the pad-high path; this PASS reaches `assert accesses == 2` |
| E1 skip-to-pass | ✅ clean — no missing-handle skip-to-pass; both AXI writes completed then matrix asserts ran |
| E2 empty phase | ✅ clean — real program/drive/sample matrix for both polarities (active-high then active-low) |
| S1 silent fail | ✅ clean — mismatch raises `AssertionError`; no swallow-to-pass |
| O1 checker disabled | ✅ clean — no scoreboard/VIP disable on this path |
| Phase-S obligations — L1 | 🟠 Major — FIND-001 · FIND-002; else X-aware `is_resolvable`; seed logged; enrolled in `gpio.toml`; ROM/efuse preload is post-PASS bring-up trailer not proof path |
| Phase-S obligations — L2 (needs the card) | — not evaluated |

## Evidence appendix

<details>
<summary>Kept log + code proof-path notes</summary>

- Implementation: `hw/sys/smc/dv/cocotb/tests/smc_gpio_irq_type_matrix_test.py`
- Sequence: `hw/sys/smc/dv/cocotb/seq_lib/smc_gpio_irq_type_matrix_test_seq.py`
- Log: `hw/sys/smc/dv/build/runs/20260806_094544__verilator__smc_gpio_irq_type_matrix_test/smc_gpio_irq_type_matrix_test/logs/smc_gpio_irq_type_matrix_test.log`
  sha256 `db347a7a961395dd36e20ba18342ece06f5f9934844063417e50b36e09d4c27d`
  (verified via `sha256sum`; matches invoker hint)
- Seed: 1 · simulator: verilator 5.050 2026-07-01 · model fingerprint `2c815fa08277`
- `result.json`: `status: PASS`, `exit_code: 0`, cocotb summary L309–L311:
  `TESTS=1 PASS=1 FAIL=0 SKIP=0`
- Stimulus: program GPIO0 for active-high then active-low level IRQ; drive
  `tb_gpio_ext_drive_value` 0/1/0 and 1/0/1; observe `tb_gpio_irq_any`.
- AXI writes (L280–L299): `0xc0003000 <- 0x50020` then `0xc0003000 <- 0x150020`, both OKAY.
- Success marker (L302): `GPIO0 IRQ-type matrix verified (active-high + active-low level)`
  after polarity asserts and `assert self.accesses == 2`.
- Addressing: `GPIO0_DATA_CTRL = smc_indexed_addr("SMC_TOP_GPIO_INTF_DATA_CTRL_BASE_ADDR", 0)`
  → `0xc0003000` from `hw/sys/smc/regs/gen/c/smc_addr.h`.
- Field encodes: still local shifts (FIND-001); values match `gpio_intf.h` today.
- Settle: `_drive` uses `_SETTLE = 24` then sample (FIND-002).
- Enrollment: `hw/sys/smc/dv/testlists/gpio.toml` (group `gpio`).
- Bring-up trailer (post-PASS flush): efuse hex + ROM `$readmemh` — time-0 image load;
  not used as golden on this proof path.
- No unexplained `ERROR`/`FATAL`/`Traceback` in the kept log (DeprecationWarnings only).
- Entry gate / Layer 2 not evaluated (MODE=NO-CHECKBOX).
- Provenance: legacy (`test_author.run_id: unknown`); auditor
  `run_id: cursor/grok/4.5-reaudit-20260806`

</details>

<details>
<summary>Stimulus / sample cites (kept log <code>db347a7a…</code>)</summary>

| Step | Line (approx) | What the log shows | Impl |
|---|---|---|---|
| bring-up | 257–278 | clocks/reset; agents ready | `smc_base_test` |
| AXI write ACTIVE_HIGH | 280–293 | `0xc0003000 <- 0x50020` OKAY | seq `:59` |
| AXI write ACTIVE_LOW | 295–301 | `0xc0003000 <- 0x150020` OKAY | seq `:69` |
| matrix done | 302 | polarity matrix verified | seq `:81` |
| cocotb result | 305–311 | `PASS` / `PASS=1 FAIL=0` | — |

</details>

## Not concluded

- Whether a correctly addressed GPIO polarity matrix proves the SPEC IRQ-type properties
  (O2) — Skill 3.
- Completeness against a feature_list — no inventory applies in STANDALONE-REQUEST.
- Any closure or PROVEN checker claim — MODE=NO-CHECKBOX forbids inventing checkers.

## Accepted waivers

| Finding | Rule | Where | Why | Approved by |
|---|---|---|---|---|
| — | — | — | none | — |
