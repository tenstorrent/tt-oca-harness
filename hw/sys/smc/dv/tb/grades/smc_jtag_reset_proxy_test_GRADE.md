---
schema: dv-quality/v1
artifact: testcase-grade
testcase: smc_jtag_reset_proxy_test
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
- path: hw/sys/smc/dv/build/runs/20260806_094552__verilator__smc_jtag_reset_proxy_test/smc_jtag_reset_proxy_test/logs/smc_jtag_reset_proxy_test.log
  sha256: 8a12ec087b0e229fa1ebe1357a7214990a682e6897cd07e9090c308b1a46ca34
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
  artifact_ref: hw/sys/smc/dv/cocotb/seq_lib/smc_jtag_reset_proxy_test_seq.py:15-16
  observed: >
    Prior full hand-copied absolute literals are gone: `CHIP_CONFIG_VERSION_LO` now
    comes from `smc_addr("SMC_TOP_SMC_MISC_WRAP_CHIP_CONFIG_BASE_ADDR")` (equals
    generated `CHIP_CONFIG_VERSION_LO_BASE_ADDR` = 0xC0002900 at this header rev).
    Residual: `SCRATCH_COLD_2 = smc_addr("…SCRATCH_COLD_BASE_ADDR") + 0x8` still
    hand-copies the index stride on the proof path while PeakRDL already exports
    `SMC_TOP_SMC_MISC_WRAP_SCRATCH_COLD_SCRATCH_BASE_ADDR(idx)` (loadable via
    `smc_indexed_addr(..., 2)` → 0xC0002808). Values match today → Major latent-rot,
    not Blocking false-identity.
  closure_condition: >
    Replace the hand-copied `+ 0x8` with
    `smc_indexed_addr("SMC_TOP_SMC_MISC_WRAP_SCRATCH_COLD_SCRATCH_BASE_ADDR", 2)`
    (and prefer `smc_addr("SMC_TOP_SMC_MISC_WRAP_CHIP_CONFIG_VERSION_LO_BASE_ADDR")`
    for the VERSION_LO symbol identity), so no parallel numeric offset remains the
    addressing source of truth on this proof path.
  waived_by: null
- id: FIND-002
  tag: '[NO-BLIND-DELAY-SYNC]'
  severity: Major
  artifact_ref: hw/sys/smc/dv/cocotb/seq_lib/smc_jtag_reset_proxy_test_seq.py:60-66
  observed: >
    After `COOL_RST_HI`, the sequence waits a fixed `ClockCycles(clk_ref_i, 200)`
    then issues the recovery `CHIP_CONFIG_VERSION_LO` read. Kept log: cool release
    @ 4632 ns → recovery AR @ 6232 ns = exactly 200×8 ns. Completion of cool-reset
    recovery is synchronized by magic cycle count, not by a predicate wait with
    fail-on-expiry before the recovery CSR sample.
  closure_condition: >
    Replace the post-`COOL_RST_HI` fixed settle on the recovery proof path with a
    bounded predicate wait (e.g. CSR/bus readiness or a documented recovery-complete
    observation) that fails on timeout with last-state diagnostics
    (`[TIMEOUT-MUST-FAIL]`), then issue the recovery read.
  waived_by: null
waivers: []
recommendation: NOT-READY
---

# Grade Report — smc_jtag_reset_proxy_test (standalone Layer 1)

**VERDICT: 0/0 PROVEN — NOT READY** (mode NO-CHECKBOX, no_contract_reason STANDALONE-REQUEST)

| Mode | Entry gate | Checkers | Findings | Recommendation |
|---|---|---|---|---|
| `NO-CHECKBOX` | — NOT-EVALUATED | 0/0 PROVEN | 🟠 2 Major | ⛔ NOT-READY |

> No approved checkbox card or parent plan record governs this testcase. Layer 1 findings
> are the entire scope of this report. `NOT-READY` records the **absence of a closure
> claim, not a defect**. Kept log is a sim **PASS** (seed 1, verilator 5.050): cool-reset
> CSR recovery plus CPU JTAG IDCODE/DTMCS pin VIP completed; Layer 2 entry is still not
> evaluated under `STANDALONE-REQUEST`.

## DELTA (re-audit vs prior grade `0/0 NOT-READY` on log `b4756972…`)

| Prior id | Tag / grade | Status this round | Notes |
|---|---|---|---|
| FIND-001 | 🟠 `[ADDRESS-FROM-AUTHORITATIVE-MAP]` | OPEN — narrowed | Absolutes now via `smc_addr`; residual hand-copied `+ 0x8` vs indexed `SCRATCH` macro |
| FIND-002 | 🟠 `[NO-BLIND-DELAY-SYNC]` | OPEN — unchanged | Same post-`COOL_RST_HI` 200-cycle settle; 4632→6232 ns cite reproduces |
| waivers: [] | — | unchanged | Prior ledger empty; no signed `approved_by` to carry; none dropped |
| Kept log | `b4756972…` | replaced | `8a12ec08…` (seed=1 PASS; model `2c815fa08277`) |
| repository_revision | `2ecc7b22…` | updated | `c10b6d63…` |

## Your to-do — 2 items (🟠 2 Major)

| # | Sev | Item |
|---|---|---|
| 1 | 🟠 Major | FIND-001 `[ADDRESS-FROM-AUTHORITATIVE-MAP]` — residual hand-copied scratch `+ 0x8` |
| 2 | 🟠 Major | FIND-002 `[NO-BLIND-DELAY-SYNC]` — fixed 200-cycle cool-recovery settle |

<details>
<summary>1. 🟠 Major — FIND-001 `[ADDRESS-FROM-AUTHORITATIVE-MAP]` at seq scratch offset</summary>

Absolute literals from the prior round are replaced by `smc_addr` for the chip-config
block base. `SCRATCH_COLD_2` still adds a hand-copied `0x8` while
`SMC_TOP_SMC_MISC_WRAP_SCRATCH_COLD_SCRATCH_BASE_ADDR(2)` exists in the generated map
(values match → latent rot, not false-identity).

**Close when:** scratch index 2 is imported via `smc_indexed_addr(..., 2)`; prefer the
`CHIP_CONFIG_VERSION_LO_BASE_ADDR` symbol for VERSION_LO identity; no parallel numeric
offset remains the addressing source of truth.

</details>

<details>
<summary>2. 🟠 Major — FIND-002 `[NO-BLIND-DELAY-SYNC]` at cool-recovery settle</summary>

Post-`COOL_RST_HI` recovery is gated by a fixed 200×`clk_ref_i` wait before the
recovery VERSION_LO read (log timing matches exactly). That delay stands in for a
recovery-complete handshake.

**Close when:** recovery CSR sampling follows a bounded predicate wait that fails on
timeout with last-state diagnostics, not a bare cycle count.

</details>

**Then:** owner remediates FIND-001/FIND-002 on the sequence, re-keeps a PASS log, and
re-invokes `/dv_test_audit`. Do not invent a card here (`STANDALONE-REQUEST`).

## All checkers

| Checker | Grade | Proof class | Covers | Findings |
|---|---|---|---|---|
| — | — | — | — | no card checkers (MODE=NO-CHECKBOX) |

### Layer 1 structural rule set

| Rule | Result |
|---|---|
| F1 fabricated verdict / backdoor write | ✅ clean — frontdoor SEP_IN SYS AXI + pin-level cool reset + CPU JTAG TAP drive; scoreboard compares DUT `rdata` to sequence `expected`; no force/deposit on proof path |
| F2 can't-fail checker | ✅ clean — scoreboard `got == exp` / `resp_ok`, AXI timeout raise, `assert accesses == 6`, IDCODE mismatch / TDO resolvable / DTMCS version asserts are reachable FAIL-ON paths |
| E1 skip-to-pass | ✅ clean — no missing-handle skip-to-pass; JTAG helper raises on mismatch |
| E2 empty phase | ✅ clean — six real SYS AXI scoreboard checks + cool reset pin ops + JTAG IDCODE/DTMCS captures executed |
| S1 silent fail | ✅ clean — AXI mismatch/timeout/`resp_ok` raise; JTAG `SmcJtagTapError` / assert on mismatch; no swallow-to-pass |
| O1 checker disabled | ✅ clean — SYS AXI scoreboard and protocol VIP path active |
| Phase-S obligations — L1 | 🟠 Major — FIND-001 `[ADDRESS-FROM-AUTHORITATIVE-MAP]`, FIND-002 `[NO-BLIND-DELAY-SYNC]`; AXI timeouts fail; enrolled in `batch_c.toml` / `all.toml`; no unconditional CHK token; JTAG expected from TB strap composition constant |
| Phase-S obligations — L2 (needs the card) | — not evaluated |

## Evidence appendix

<details>
<summary>Kept log + code proof-path notes</summary>

- Log: `hw/sys/smc/dv/build/runs/20260806_094552__verilator__smc_jtag_reset_proxy_test/smc_jtag_reset_proxy_test/logs/smc_jtag_reset_proxy_test.log`
  sha256 `8a12ec087b0e229fa1ebe1357a7214990a682e6897cd07e9090c308b1a46ca34`
  (verified via `manifest.py hash-file`; matches invoker hint)
- Seed: 1 · simulator: verilator 5.050 2026-07-01 · model fingerprint `2c815fa08277`
- `result.json`: `status: PASS`, `exit_code: 0`, cocotb summary L356:
  `TESTS=1 PASS=1 FAIL=0 SKIP=0`
- Final assertion gate: seq `assert self.accesses == 6` reached after six scoreboard
  SYS AXI checks; protocol VIP records `csr_accesses=6`
- Cool reset: `COOL_RST_LO` @ 4476 ns → `COOL_RST_HI` @ 4632 ns → recovery VERSION_LO
  read start @ 6232 ns (`rdata=0x100a0 exp=0x100a0` @ 6336 ns)
- Scratch path: write `0x1a7a0002` / readback match pre-cool; post-cool restore write `0`
  / read `0` (does not sample scratch immediately after cool to prove clear — O2/intent,
  not graded here; cold scratch is not a cool-clear oracle)
- JTAG pin VIP: IDCODE `0x10CA0555` MATCH (L341–L342); DTMCS version `0x1` MATCH
  (L343–L344) via `check_cpu_jtag_pin_vip`
- Test: `hw/sys/smc/dv/cocotb/tests/smc_jtag_reset_proxy_test.py` starts
  `smc_jtag_reset_proxy_test_seq` on `sys_axi_agent.sequencer`, cool reset via
  `reset_agent`, then `check_cpu_jtag_pin_vip`, then protocol VIP record
- Addressing: `smc_jtag_reset_proxy_test_seq.py:15-16` via `smc_addr` + residual `+ 0x8`;
  generated truth in `hw/sys/smc/regs/gen/c/smc_addr.h` (indexed scratch macro matches)
- Driver FAIL-ON: `smc_sys_axi_agent.py` raises on unexpected AXI timeout
- Scoreboard value check: `smc_scoreboard.py:188-194` asserts `rdata` vs `expected`
  when set (VERSION_LO and scratch readbacks use non-null expecteds)
- Enrollment: `hw/sys/smc/dv/testlists/batch_c.toml`, `all.toml`
- Bring-up trailer (post-PASS flush): efuse hex + ROM `$readmemh` — time-0 image load;
  not used as CSR/JTAG golden substitution on this proof path
- No unexplained `ERROR`/`FATAL`/`Traceback` in the kept log
- Provenance: legacy (`test_author.run_id: unknown`); auditor
  `run_id: cursor/grok/4.5-reaudit-20260806`

</details>

## Not concluded

- Whether cool-reset + CPU JTAG pin VIP prove the SPEC JTAG-reset properties (O2) —
  Skill 3; this sequence is explicitly a CSR/cool-reset proxy until a public JTAG VIP
  exists.
- Completeness against a feature_list — no inventory applies in STANDALONE-REQUEST.
- Any closure or PROVEN checker claim — MODE=NO-CHECKBOX forbids inventing checkers.

## Accepted waivers

| Finding | Rule | Where | Why | Approved by |
|---|---|---|---|---|
| — | — | — | none | — |
