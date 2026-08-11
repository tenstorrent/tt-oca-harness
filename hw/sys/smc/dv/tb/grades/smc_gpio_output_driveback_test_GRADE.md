---
schema: dv-quality/v1
artifact: testcase-grade
testcase: smc_gpio_output_driveback_test
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
- path: hw/sys/smc/dv/build/runs/20260806_094544__verilator__smc_gpio_output_driveback_test/smc_gpio_output_driveback_test/logs/smc_gpio_output_driveback_test.log
  sha256: c5d808be425330a6fbc1fa29b74ea330a9f1505f6de9a99d0c24066ea57f8c70
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
  artifact_ref: hw/sys/smc/dv/cocotb/seq_lib/smc_gpio_output_driveback_test_seq.py:32-37
  observed: >
    Register address is now sourced via
    `smc_indexed_addr("SMC_TOP_GPIO_INTF_DATA_CTRL_BASE_ADDR", 0)` and the kept
    log programs `0xc0003000` (correct GPIO wrap0 DATA_CTRL). Proof-path field
    encoding remains hand-copied: `_CORE2PAD = 1 << 0`, `_TX_ENABLE = 1 << 4`,
    `_IF_ENABLE = 1 << 16` composing `OUT_DRIVE_HIGH/LOW`. Generated
    `hw/ip/gpio/regs/gen/c/gpio_intf.h` already exports
    `GPIO_INTF__DATA_CTRL__{CORE2PAD,ENABLE_RX_TX,INTERFACE_ENABLE}_{bm,bp}`
    matching those values — latent rot only (Major), not false identity.
  closure_condition: >
    Import DATA_CTRL field masks/positions from `gpio_intf.h` (extend
    `smc_addr_map` or parse locally) and build write data from those symbols
    (e.g. INTERFACE_ENABLE_bm | (TX_code << ENABLE_RX_TX_bp) | CORE2PAD_bm).
    Re-keep a PASS log showing the same pad delta with symbol-sourced data.
  waived_by: null
- id: FIND-002
  tag: '[X-AWARE-CHECK]'
  severity: Major
  artifact_ref: hw/sys/smc/dv/cocotb/seq_lib/smc_gpio_output_driveback_test_seq.py:48-61
  observed: >
    `_resolve_int` maps any X/Z bit to 0 before pad checks. Non-zero asserts
    (newly_en, value-high, enable-still-set) fail under X, but equality-to-zero
    gates at `:105–107` (value low) and `:112–114` (enable release) pass when
    the checked bit is X. On VCS undriven/X pads this is X-optimism on the
    drive-low / disable legs; Verilator zero-init masks it on this kept PASS.
  closure_condition: >
    For each checked pad bit, require a known 0/1 (reject X/Z) before comparing,
    or use an X-aware equality that fails on unknown; keep the delta/high fails
    that already trip when X resolves to 0.
  waived_by: null
- id: FIND-003
  tag: '[NO-BLIND-DELAY-SYNC]'
  severity: Major
  artifact_ref: hw/sys/smc/dv/cocotb/seq_lib/smc_gpio_output_driveback_test_seq.py:84-114
  observed: >
    After each handshake-complete AXI CSR write, the sequence waits a fixed
    `ClockCycles(dut.clk_smc_i, 8)` then samples `tb_core2pad_*` and asserts.
    Pad-enable/value update has no event wait with fail-on-expiry; completion
    is synchronized by magic cycle count. Kept log: write complete @4284 ns →
    next write start @4332 ns (= 8 × 6 ns smc clocks) with asserts in between.
  closure_condition: >
    Replace fixed post-write settles on the proof path with bounded predicate
    waits (e.g. poll until `newly_en != 0` / value/enable match) that raise on
    timeout with last-state diagnostics (`[TIMEOUT-MUST-FAIL]`).
  waived_by: null
waivers: []
recommendation: NOT-READY
---

# Grade Report — smc_gpio_output_driveback_test (standalone Layer 1)

**VERDICT: 0/0 PROVEN — NOT READY** (mode NO-CHECKBOX, no_contract_reason STANDALONE-REQUEST)

| Mode | Entry gate | Checkers | Findings | Recommendation |
|---|---|---|---|---|
| `NO-CHECKBOX` | — NOT-EVALUATED | 0/0 PROVEN | 🟠 3 Major | ⛔ NOT-READY |

> No approved checkbox card or parent plan record governs this testcase
> (`STANDALONE-REQUEST` / active-regression L1 wave). Layer 1 findings are the entire
> scope of this report. `NOT-READY` records the **absence of a closure claim, not a
> defect**. Kept log is a sim **PASS** (seed 1); Layer 2 was not entered.

## DELTA (re-audit vs prior grade `0/0 NOT-READY` on log `f332595d…`)

| Prior id | Tag / grade | Status this round | Notes |
|---|---|---|---|
| FIND-001 | 🔴 `[ADDRESS-FROM-AUTHORITATIVE-MAP]` | CLOSED (false identity) | Seq now uses `smc_indexed_addr(...DATA_CTRL..., 0)`; log writes `0xc0003000` / `0x10011` OKAY; pad[0] driveback verified |
| — | residual field encoding | OPEN — refiled FIND-001 🟠 | Hand-copied `_CORE2PAD` / `_TX_ENABLE` / `_IF_ENABLE` remain (Major latent rot) |
| — | — | NEW FIND-002 🟠 `[X-AWARE-CHECK]` | Full PASS path reaches `== 0` asserts; X→0 resolve is optimistic there |
| — | — | NEW FIND-003 🟠 `[NO-BLIND-DELAY-SYNC]` | Fixed 8-cycle settle before each pad sample |
| waivers: [] | — | unchanged | Prior ledger empty; no signed `approved_by` to carry; none dropped |
| Kept log | `f332595d…` (FAIL) | replaced | `c5d808be…` (seed=1 PASS; model `2c815fa08277`) |
| repository_revision | `2ecc7b22…` | updated | `c10b6d63…` |

## Your to-do — 3 items (🟠 3 Major)

| # | Sev | Item |
|---|---|---|
| 1 | 🟠 Major | FIND-001 `[ADDRESS-FROM-AUTHORITATIVE-MAP]` — DATA_CTRL field bits still hand-copied |
| 2 | 🟠 Major | FIND-002 `[X-AWARE-CHECK]` — `== 0` pad checks pass when bit is X |
| 3 | 🟠 Major | FIND-003 `[NO-BLIND-DELAY-SYNC]` — fixed 8-cycle settle before pad sample |

<details>
<summary>1. 🟠 Major — FIND-001 <code>[ADDRESS-FROM-AUTHORITATIVE-MAP]</code> — field encoding not from generated map</summary>

- **Where:** `hw/sys/smc/dv/cocotb/seq_lib/smc_gpio_output_driveback_test_seq.py:32-37`
- **Observed:** Address path is fixed (`smc_indexed_addr` → `0xc0003000` in kept log). Write data still uses parallel shift literals instead of `gpio_intf.h` `GPIO_INTF__DATA_CTRL__*_bm/_bp` (values currently match — latent rot).
- **Closure:** Source field masks/positions from the generated header; rebuild `OUT_DRIVE_*` from those symbols; re-keep PASS log.

</details>

<details>
<summary>2. 🟠 Major — FIND-002 <code>[X-AWARE-CHECK]</code> — X→0 makes low/release asserts optimistic</summary>

- **Where:** `hw/sys/smc/dv/cocotb/seq_lib/smc_gpio_output_driveback_test_seq.py:48-61` (used at `:105–114`)
- **Observed:** `_resolve_int` forces X/Z→0. Value-low and enable-release `== 0` asserts then pass on unknown bits; Verilator zero-init hides this on the kept PASS.
- **Closure:** Require known 0/1 on the checked pad bit (fail on X/Z) before equality-to-zero compares.

</details>

<details>
<summary>3. 🟠 Major — FIND-003 <code>[NO-BLIND-DELAY-SYNC]</code> — post-write fixed settle</summary>

- **Where:** `hw/sys/smc/dv/cocotb/seq_lib/smc_gpio_output_driveback_test_seq.py:84-114`
- **Observed:** After AXI write completion, `ClockCycles(..., 8)` then sample/assert pad vectors; no bounded predicate wait for enable/value update (log gap 4284→4332 ns = 8 smc cycles).
- **Closure:** Poll for the expected pad delta/value/release with timeout-must-fail + last-state diagnostics.

</details>

**Then:** owner remediates FIND-001/002/003 in the sequence, re-keeps a PASS log, and
re-invokes `/dv_test_audit`. Do not invent a card here (`STANDALONE-REQUEST`).

## All checkers

| Checker | Grade | Proof class | Covers | Findings |
|---|---|---|---|---|
| — | — | — | — | no card checkers (MODE=NO-CHECKBOX) |

### Layer 1 structural rule set

| Rule | Result |
|---|---|
| F1 fabricated verdict / backdoor write | ✅ clean — frontdoor SEP_IN AXI CSR write + passive TB mirrors `tb_core2pad_*`; no force/deposit on proof path |
| F2 can't-fail checker | ✅ clean — `newly_en`/value/release asserts are reachable fail paths (prior FAIL on wrong address proved sensitivity) |
| E1 skip-to-pass | ✅ clean — no missing-handle skip-to-pass; three AXI writes + pad asserts ran to PASS |
| E2 empty phase | ✅ clean — real CSR program + pad-bus delta / value / release checks |
| S1 silent fail | ✅ clean — mismatch raises `AssertionError`; scoreboard SYS AXI checks enabled |
| O1 checker disabled | ✅ clean — scoreboard SYS AXI checks #1–#3 active; sequence asserts not gated off |
| Phase-S obligations — L1 | 🟠 Major — FIND-001 / FIND-002 / FIND-003; else address via `smc_addr_map`, seed logged, enrolled in `gpio.toml`, force-free pad mirrors, `accesses == 3` activity gate, no unconditional CHK token |
| Phase-S obligations — L2 (needs the card) | — not evaluated |

## Evidence appendix

<details>
<summary>Kept log + code proof-path notes</summary>

- Log: `hw/sys/smc/dv/build/runs/20260806_094544__verilator__smc_gpio_output_driveback_test/smc_gpio_output_driveback_test/logs/smc_gpio_output_driveback_test.log`
  sha256 `c5d808be425330a6fbc1fa29b74ea330a9f1505f6de9a99d0c24066ea57f8c70`
  (verified via `sha256sum`; matches invoker hint)
- Seed: 1 · simulator: verilator 5.050 2026-07-01 · model fingerprint `2c815fa08277`
- Cocotb summary L316–L318: `smc_gpio_output_driveback_test ... PASS` /
  `TESTS=1 PASS=1 FAIL=0 SKIP=0`
- Zero unexplained `ERROR`/`FATAL`/`Traceback` (DeprecationWarning only)
- Test: `hw/sys/smc/dv/cocotb/tests/smc_gpio_output_driveback_test.py` starts
  `smc_gpio_output_driveback_test_seq` on `sys_axi_agent.sequencer`
- Seq: baseline `tb_core2pad_en_o` → TX high / low / disable → single-bit enable
  delta + value track + release (`:69–120`); address `:30`
- Kept-log stimulus cites:
  - L280–L293: AXI write `0xc0003000 <- 0x10011` OKAY; scoreboard #1
  - L295–L300: `0xc0003000 <- 0x10010` OKAY; scoreboard #2
  - L302–L307: `0xc0003000 <- 0x0` OKAY; scoreboard #3
  - L309: `GPIO wrap0 output driveback verified on pad[0]`
- Authoritative map: `SMC_TOP_GPIO_INTF_DATA_CTRL_BASE_ADDR(0) = 0xC0003000` (resolved)
- Enrollment: `hw/sys/smc/dv/testlists/gpio.toml` (group `gpio`)
- Bring-up trailer: efuse hex + ROM `$readmemh` — time-0 image load; not used as GPIO golden
- Entry gate / Layer 2 not evaluated (`MODE=NO-CHECKBOX`; `entry_status: NOT-EVALUATED`)
- Provenance: legacy (`test_author.run_id: unknown`)

</details>

<details>
<summary>Stimulus / pass cites (kept log <code>c5d808be…</code>)</summary>

| Step | Line (approx) | What the log shows | Impl |
|---|---|---|---|
| bring-up | 267–278 | clocks + cold reset; agents ready | `smc_base_test` |
| AXI write high | 280–293 | `0xc0003000 <- 0x10011` OKAY; SB #1 | seq `:83` |
| AXI write low | 295–300 | `0xc0003000 <- 0x10010` OKAY; SB #2 | seq `:100` |
| AXI write disable | 302–307 | `0xc0003000 <- 0x0` OKAY; SB #3 | seq `:110` |
| verified | 309 | pad[0] driveback verified | seq `:117–120` |
| cocotb result | 312–318 | `PASS` / `PASS=1 FAIL=0` | — |

</details>

## Not concluded

- Whether pad driveback after correct GPIO DATA_CTRL programming proves the SPEC
  properties a future card would require (O2) — Skill 3.
- Completeness against a feature_list — no inventory applies in STANDALONE-REQUEST.
- Any closure or PROVEN checker claim — MODE=NO-CHECKBOX forbids inventing checkers.

## Accepted waivers

| Finding | Rule | Where | Why | Approved by |
|---|---|---|---|---|
| — | — | — | none | — |
