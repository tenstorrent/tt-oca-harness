---
schema: dv-quality/v1
artifact: testcase-grade
testcase: smc_multi_reset_csr_persistence_test
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
- path: hw/sys/smc/dv/build/runs/20260806_094613__verilator__smc_multi_reset_csr_persistence_test/smc_multi_reset_csr_persistence_test/logs/smc_multi_reset_csr_persistence_test.log
  sha256: f7f5e981f25e92e31ba97888b2f11806408b77c7b5dc772be10af63022e4fac5
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
  artifact_ref: hw/sys/smc/dv/cocotb/seq_lib/smc_multi_reset_csr_persistence_test_seq.py:35-50
  observed: >
    Cool is the only reset pulse under test (`COOL_RST_LO`/`HI` via
    `SmcResetDriver` on top-level `rst_cool_ni`), but no FAIL-ON check observes a
    cool effect. Pre-cool `SCRATCH_COLD_WARM_1` is written `0xCAFE_0020` and
    post-cool proof re-reads the same pattern (persistence) plus RO
    `CHIP_CONFIG_VERSION_LO` (same constant as baseline). Kept log: cool assert @
    16878 ns, release @ 17032 ns, post-cool VERSION_LO/scratch compares @
    23538/23646 ns with no mid-cool RAW/SAMPLE and no register that must clear on
    cool. A DUT that ignores `rst_cool_ni` still leaves the scratch pattern and RO
    version intact, so cocotb PASS does not prove cool ran — only that the
    programmed value was still readable after a timed wait. Severity follows
    policy §3 default (proof does not hold → Blocking); tag is Phase-S L1
    checker non-vacuity.
  closure_condition: >
    Couple the persistence oracle with at least one cool-effect FAIL-ON (e.g.
    mid-cool status sample that fails if cool is ignored, or a warm-cleared
    companion register whose clear is required before asserting scratch
    persistence), then keep the post-cool SEP_IN AXI persistence / restore
    compares.
  waived_by: null
- id: FIND-002
  tag: '[ADDRESS-FROM-AUTHORITATIVE-MAP]'
  severity: Major
  artifact_ref: hw/sys/smc/dv/cocotb/seq_lib/smc_multi_reset_csr_persistence_test_seq.py:14-15
  observed: >
    Prior full hand-copied absolute literals are gone: addresses now resolve via
    `smc_addr`. Residual: `CHIP_CONFIG_VERSION_LO` uses block base
    `SMC_TOP_SMC_MISC_WRAP_CHIP_CONFIG_BASE_ADDR` rather than register symbol
    `SMC_TOP_SMC_MISC_WRAP_CHIP_CONFIG_VERSION_LO_BASE_ADDR` (same numeric value
    today = 0xC0002900). `SCRATCH_COLD_WARM_1` is
    `smc_addr("…SCRATCH_COLD_WARM_BASE_ADDR") + 0x4` with a hand-copied stride
    instead of
    `smc_indexed_addr("SMC_TOP_SMC_MISC_WRAP_SCRATCH_COLD_WARM_SCRATCH_BASE_ADDR", 1)`
    → 0xC0002884. Values match generated `smc_addr.h` → Major latent-rot, not
    Blocking false-identity (policy §3 conditional adjustment).
  closure_condition: >
    Source both proof-path addresses from register-level generated symbols:
    `smc_addr("SMC_TOP_SMC_MISC_WRAP_CHIP_CONFIG_VERSION_LO_BASE_ADDR")` and
    `smc_indexed_addr("SMC_TOP_SMC_MISC_WRAP_SCRATCH_COLD_WARM_SCRATCH_BASE_ADDR", 1)`.
    Drop block-base + hand-offset arithmetic as the addressing source of truth.
  waived_by: null
- id: FIND-003
  tag: '[NO-BLIND-DELAY-SYNC]'
  severity: Major
  artifact_ref: hw/sys/smc/dv/cocotb/seq_lib/smc_multi_reset_csr_persistence_test_seq.py:40-47
  observed: >
    After `COOL_RST_HI`, recovery completion is `ClockCycles(dut.clk_ref_i, 800)`
    then the post-cool CSR reads. Kept log: cool release @ 17032 ns → VERSION_LO
    recovery read start @ 23432 ns = exactly 800×8 ns ref cycles. There is no
    bounded predicate wait on recovery outputs that fails on expiry with
    last-state diagnostics; the fixed delay stands in for post-cool settle before
    the persistence asserts. (The mid-cool `ClockCycles(..., 20)` is stimulus
    pulse width, not the recovery completion sync under this finding.)
  closure_condition: >
    Replace the fixed 800-cycle settle with a bounded wait on the recovery
    signals (released / stable levels) that raises on timeout with last-state
    diagnostics (`[TIMEOUT-MUST-FAIL]`), then issue the post-cool CSR compares.
  waived_by: null
waivers: []
recommendation: NOT-READY
---

# Grade Report — smc_multi_reset_csr_persistence_test (standalone Layer 1)

**VERDICT: 0/0 PROVEN — NOT READY** (mode NO-CHECKBOX, no_contract_reason STANDALONE-REQUEST)

| Mode | Entry gate | Checkers | Findings | Recommendation |
|---|---|---|---|---|
| `NO-CHECKBOX` | — NOT-EVALUATED | 0/0 PROVEN | 🔴 1 Blocking · 🟠 2 Major | ⛔ NOT-READY |

> No approved checkbox card or parent plan record governs this testcase. Layer 1 findings
> are the entire scope of this report. `NOT-READY` records the **absence of a closure
> claim, not a defect**. Kept log is a sim PASS (seed 1); Layer 2 was not entered.

## DELTA (re-audit vs prior grade `0/0 NOT-READY` on log `f7f5e981…`)

| Prior id | Tag / grade | Status this round | Notes |
|---|---|---|---|
| FIND-001 | 🔴 `[CHECKER-NONVACUITY]` | OPEN — unchanged | Cool pulse still has no FAIL-ON effect oracle; persistence-only proof |
| FIND-002 | 🟠 `[ADDRESS-FROM-AUTHORITATIVE-MAP]` | OPEN — unchanged | Residual block-base VERSION_LO + hand `+ 0x4` vs indexed `SCRATCH_COLD_WARM` macro |
| FIND-003 | 🟠 `[NO-BLIND-DELAY-SYNC]` | OPEN — unchanged | Same post-`COOL_RST_HI` 800-cycle settle; 17032→23432 ns cite reproduces |
| waivers: [] | — | unchanged | Prior ledger empty; no signed `approved_by` to carry; none dropped |
| Kept log | `f7f5e981…` | same | seed=1 PASS; model `2c815fa08277`; sha256 re-verified |
| repository_revision | `c10b6d63…` | same | fresh L1 re-audit, same pinned rev |

## Your to-do — 3 items (🔴 1 Blocking · 🟠 2 Major)

| # | Sev | Item |
|---|---|---|
| 1 | 🔴 Blocking | FIND-001 `[CHECKER-NONVACUITY]` — cool effect never FAIL-ON |
| 2 | 🟠 Major | FIND-002 `[ADDRESS-FROM-AUTHORITATIVE-MAP]` — residual block-base / hand `+0x4` |
| 3 | 🟠 Major | FIND-003 `[NO-BLIND-DELAY-SYNC]` — fixed 800-cycle post-cool settle |

<details>
<summary>1. 🔴 Blocking — FIND-001 `[CHECKER-NONVACUITY]` at cool persistence proof path</summary>

Cool pulse is driven, but post-cool checks only re-prove RO version and that the
pre-cool scratch pattern is still present. Persistence alone is satisfied if cool is
a NOP. No mid-cool sample or cool-cleared companion oracle is FAIL-ON compared.

**Close when:** assert at least one cool-specific effect that fails if cool is ignored,
then keep the persistence / restore SEP_IN AXI compares.

</details>

<details>
<summary>2. 🟠 Major — FIND-002 `[ADDRESS-FROM-AUTHORITATIVE-MAP]` at seq address constants</summary>

Absolute literals from the prior round are replaced by `smc_addr` for block bases.
`CHIP_CONFIG_VERSION_LO` still uses `CHIP_CONFIG_BASE_ADDR`, and
`SCRATCH_COLD_WARM_1` keeps hand `+ 0x4` rather than
`smc_indexed_addr("…SCRATCH_COLD_WARM_SCRATCH_BASE_ADDR", 1)`. Numerics match today
(`0xc0002900` / `0xc0002884`) — Major latent-rot, not Blocking false-identity.

**Close when:** import register-level symbols via `smc_addr(VERSION_LO_…)` and
`smc_indexed_addr(SCRATCH_COLD_WARM_SCRATCH_…, 1)` on the proof path.

</details>

<details>
<summary>3. 🟠 Major — FIND-003 `[NO-BLIND-DELAY-SYNC]` at post-cool settle</summary>

`ClockCycles(..., 800)` after `COOL_RST_HI` gates the post-cool CSR reads (log gap =
800 ref cycles). No bounded handshake wait with fail-on-expiry.

**Close when:** recovery proof uses a predicate wait with fail-on-expiry and last-state
diagnostics, not a blind cycle count.

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
| F1 fabricated verdict / backdoor write | ✅ clean — pin drive via `SmcResetDriver` on top-level `rst_cool_ni`; SYS AXI frontdoor CSR path; no force/deposit on proof path |
| F2 can't-fail checker | ✅ clean — SYS AXI `expected` compares can fail on wrong rdata; cool-stimulus vacuity filed under Phase-S, not F2 |
| E1 skip-to-pass | ✅ clean — missing `dispatch_reset` would raise; no HDL-path skip-to-pass |
| E2 empty phase | ✅ clean — baseline CSR, cool pulse, recovery CSR, restore, `accesses==7` gate all execute |
| S1 silent fail | ✅ clean — scoreboard SYS AXI asserts raise on resp/value mismatch; sequence `accesses==7` raises `AssertionError` |
| O1 checker disabled | ✅ clean — scoreboard SYS AXI checks remain enabled |
| Phase-S obligations — L1 | 🔴 Blocking — FIND-001 · 🟠 Major — FIND-002, FIND-003; fuse-sense wait fail-on-expiry; enrolled in `batch_d.toml` / `all.toml` / `vplan_triplets.toml` |
| Phase-S obligations — L2 (needs the card) | — not evaluated |

## Evidence appendix

<details>
<summary>Kept log + code proof-path notes</summary>

- Log: `hw/sys/smc/dv/build/runs/20260806_094613__verilator__smc_multi_reset_csr_persistence_test/smc_multi_reset_csr_persistence_test/logs/smc_multi_reset_csr_persistence_test.log`
  sha256 `f7f5e981f25e92e31ba97888b2f11806408b77c7b5dc772be10af63022e4fac5`
  (re-verified this round via `sha256sum`; matches invoker hint)
- Seed: 1 · simulator: verilator 5.050 · model fingerprint `2c815fa08277`
- `result.json`: `status: PASS`, `return_code: 0`, cocotb summary:
  `TESTS=1 PASS=1 FAIL=0 SKIP=0`
- Test: `hw/sys/smc/dv/cocotb/tests/smc_multi_reset_csr_persistence_test.py` starts
  `smc_multi_reset_csr_persistence_test_seq` on `sys_axi_agent.sequencer` with
  `dispatch_reset` → `reset_agent` via `_OneShot`
- Seq proof path: `smc_multi_reset_csr_persistence_test_seq.py` → `SmcSysAxiAgent` /
  `SmcResetAgent` / `SmcScoreboard._check_sys_axi`
- SYS AXI cites: VERSION_LO baseline `0x100a0` @ 16662 ns; scratch write/read
  `0xcafe0020` @ 16770/16878 ns; VERSION_LO recovery @ 23538 ns; scratch persist
  `0xcafe0020` @ 23646 ns; restore `0` @ 23754/23862 ns (scoreboard checks #1–#7)
- Cool cites: `rst_cool_ni=0` @ 16878 ns; `=1` @ 17032 ns
- Blind recover cite: HI→post-cool read start gap = 800 ref cycles × 8 ns
- Address map cite: `smc_addr` + hand `+0x4`; numerics match `smc_addr.h`
  (`0xC0002884` = SCRATCH_COLD_WARM idx 1, `0xC0002900` = VERSION_LO) — residual
  register-level symbol gap is FIND-002
- Enrollment: `hw/sys/smc/dv/testlists/batch_d.toml`, `all.toml`, `vplan_triplets.toml`
- Bring-up trailer: efuse hex + ROM `$readmemh` — time-0 image load; not used as golden
  for these checks (policy §6 standing preload exception; off this proof path)
- No unexplained `ERROR`/`FATAL`/`Traceback`; only cocotb deprecation warnings
- Provenance: legacy (`test_author.run_id: unknown`); auditor
  `run_id: cursor/grok/4.5-reaudit-20260806`

</details>

## Not concluded

- Whether the multi-reset CSR persistence path checks the SPEC properties a future card
  would require (O2) — Skill 3.
- Completeness against a feature_list — no inventory applies in STANDALONE-REQUEST.
- Any closure or PROVEN checker claim — MODE=NO-CHECKBOX forbids inventing checkers from
  the passing log.

## Accepted waivers

| Finding | Rule | Where | Why | Approved by |
|---|---|---|---|---|
| — | — | — | none | — |
