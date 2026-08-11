---
schema: dv-quality/v1
artifact: testcase-grade
testcase: smc_i2c_p1_rdwr_protocol_test
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
- path: hw/sys/smc/dv/build/runs/20260806_094618__verilator__smc_i2c_p1_rdwr_protocol_test/smc_i2c_p1_rdwr_protocol_test/logs/smc_i2c_p1_rdwr_protocol_test.log
  sha256: 7ea9b82af4eec7e96e3aa82caf2a7ff98108b96201666021bc5bf2fe57dbcfa4
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
  tag: '[NO-BLIND-DELAY-SYNC]'
  severity: Major
  artifact_ref: hw/sys/smc/dv/cocotb/seq_lib/smc_i2c_master_target_test_seq.py:115-129
  observed: >-
    Shared sequence on this alias's proof path: after `_wait_hostidle`
    (STATUS HOSTIDLE handshake), `_dut_i2c0_host_write_proof` and
    `_dut_i2c0_smbus_pec_write_proof` still `await Timer(50, units="us")`
    before VIP EEPROM mem compare (seq :199, :242). OVRD pad `_check_line`
    samples only after `ClockCycles(..., 100)` with no event/timeout FAIL-ON
    for pad settle (:115-129). Kept PASS log reaches all three host proofs
    (L578 host write, L651 PEC, L703 ARA) and the OVRD matrix (L422–L454).
  closure_condition: >-
    Sample VIP mem / pads immediately after the HOSTIDLE (or other named)
    handshake, or replace the fixed delay with a bounded event wait that fails
    on expiry with last-state diagnostics; do not use bare Timer/ClockCycles as
    the sync before the FAIL-ON compare.
  waived_by: null
- id: FIND-002
  tag: '[X-AWARE-CHECK]'
  severity: Major
  artifact_ref: hw/sys/smc/dv/cocotb/seq_lib/smc_i2c_master_target_test_seq.py:115-129
  observed: >-
    OVRD pad proof `_check_line` converts `dut.tb_i2c0_scl.value` /
    `tb_i2c0_sda.value` (and dut_low mirrors) with bare `int(...)` then asserts
    equality to expected 0/1, with no resolve-and-assert-known / X/Z gate before
    the FAIL-ON compare. On cocotb/Verilator an unresolved pad can raise or
    resolve arbitrarily, so a pass on X-optimism is not cycle-valid proof. Path
    executed this seed (L422/L430/L454 OVRD matrix).
  closure_condition: >-
    Resolve-and-assert-known (or equivalent) before numeric compare on
    tb_i2c0_scl / tb_i2c0_sda samples used as FAIL-ON evidence.
  waived_by: null
waivers: []
recommendation: NOT-READY
---

# Grade Report — smc_i2c_p1_rdwr_protocol_test (standalone Layer 1 re-audit)

**VERDICT: 0/0 PROVEN — NOT READY** (mode NO-CHECKBOX, no_contract_reason STANDALONE-REQUEST)

| Mode | Entry gate | Checkers | Findings | Recommendation |
|---|---|---|---|---|
| `NO-CHECKBOX` | — NOT-EVALUATED | 0/0 PROVEN | 🟠 2 Major | ⛔ NOT-READY |

> No approved checkbox card or parent plan record governs this testcase
> (`STANDALONE-REQUEST`). Layer 1 findings are the entire scope of this report.
> `NOT-READY` records the **absence of a closure claim, not a defect** in the
> test by itself. Kept log is a sim **PASS** (seed 1):
> `TESTS=1 PASS=1 FAIL=0 SKIP=0`, `result.json status: PASS`, zero unexplained
> `ERROR`/`FATAL`/`Traceback` — Layer 2 entry is still not evaluated without a card.

## Delta from prior round (`smc_i2c_p1_rdwr_protocol_test_GRADE.md`, kept log `7ea9b82a…`)

| Item | Prior round | This round |
|---|---|---|
| Kept log | PASS seed1 `7ea9b82a…` (`20260806_094618`) | **Same** PASS seed1 `7ea9b82a…` (sha256 verified) |
| FIND-001 `[NO-BLIND-DELAY-SYNC]` | Open (Major) — Timer(50us) / ClockCycles(100) | **Open** — unchanged on proof path |
| FIND-002 `[X-AWARE-CHECK]` | Open (Major) — bare `int(pad.value)` in `_check_line` | **Open** — unchanged |
| Blocking / address-map | Closed in prior (map via `smc_addr_map`) | **Still clean** — log `0xc0005000`/`5200`/`5400`/`5e00` |
| Recommendation | ⛔ NOT-READY | ⛔ NOT-READY |
| Waivers carried forward | `waivers: []` | `waivers: []` — prior ledger empty (`approved_by` none); nothing to carry |

**Fresh L1 re-check (this run_id):** same two Major hygiene findings; no new Blocking/Major/Minor; no closures. Alias still does not fabricate VIP `observed_bytes`.

## Your to-do — 2 items (🟠 2 Major)

| # | Kind | Id | Severity / grade | Where |
|---|---|---|---|---|
| 1 | finding | FIND-001 | 🟠 Major | `smc_i2c_master_target_test_seq.py:115-129` (+ `:199`, `:242`) |
| 2 | finding | FIND-002 | 🟠 Major | `smc_i2c_master_target_test_seq.py:115-129` |

<details>
<summary>1. FIND-001 — 🟠 Major <code>[NO-BLIND-DELAY-SYNC]</code> — fixed 50 µs / 100 cycles before sample</summary>

- **Where:** `hw/sys/smc/dv/cocotb/seq_lib/smc_i2c_master_target_test_seq.py:115-129` (`_check_line`); also host/PEC proofs `:199`, `:242`
- **Observed:** Host-write and PEC proofs wait `Timer(50, "us")` after HOSTIDLE before VIP mem compare; OVRD pad checks sample only after 100 `ClockCycles`. Executed this PASS seed (L578/L651 host/PEC after Timer deprecation warn; L422–L454 OVRD).
- **Closure:** Sync on handshake / bounded event with FAIL-ON timeout; do not use bare delay before the compare.

</details>

<details>
<summary>2. FIND-002 — 🟠 Major <code>[X-AWARE-CHECK]</code> — pad samples without known/X gate</summary>

- **Where:** `hw/sys/smc/dv/cocotb/seq_lib/smc_i2c_master_target_test_seq.py:115-129`
- **Observed:** `_check_line` uses bare `int(tb_i2c0_scl/sda.value)` before FAIL-ON equality; no X/Z resolve-and-assert-known. Executed this seed (OVRD matrix).
- **Closure:** Assert known before numeric pad compares used as proof.

</details>

**Then:** owner fixes FIND-001/002 hygiene on the shared OVRD + host path (same seq as `smc_i2c_master_target_test`), re-keeps a PASS log for this alias, and re-invokes `/dv_test_audit smc_i2c_p1_rdwr_protocol_test`. Do not invent a card here (`STANDALONE-REQUEST`).

## All checkers

| Checker | Grade | Proof class | Covers | Findings |
|---|---|---|---|---|
| — | — | — | — | no card checkers (MODE=NO-CHECKBOX) |

### Layer 1 structural rule set

| Rule | Result |
|---|---|
| F1 fabricated verdict / backdoor write | ✅ clean — alias does not invent VIP `observed_bytes`; in-seq asserts measure VIP mem / ARA RDATA / pads; no force/deposit on proof path (ROM/efuse `$readmemh` is bring-up trailer) |
| F2 can't-fail checker | ✅ clean — in-seq `assert got == bytes([...])` / ARA RDATA / CSR scoreboard `resp_ok` are reachable FAIL-ON |
| E1 skip-to-pass | ✅ clean — missing EEPROM VIP raises AssertionError; import failure does not mark pass |
| E2 empty phase | ✅ clean — body issues real CSR R/W, OVRD pad matrix, DUT host write + PEC + ARA |
| S1 silent fail | ✅ clean — axi_monitor + scoreboard + seq `assert` raise on mismatch |
| O1 checker disabled | ✅ clean — SYS AXI scoreboard and protocol VIP scoreboard active (L727 protocol VIP check #1) |
| Phase-S obligations — L1 | 🟠 Major — FIND-001 `[NO-BLIND-DELAY-SYNC]`, FIND-002 `[X-AWARE-CHECK]`; else `_wait_hostidle` / ARA poll raise on timeout; addresses from `smc_addr_map`; seed logged; enrolled in `vplan_triplets.toml`; force-free pad/VIP path |
| Phase-S obligations — L2 (needs the card) | — not evaluated |

## Evidence appendix

<details>
<summary>Kept log + code proof-path notes</summary>

- Implementation: `hw/sys/smc/dv/cocotb/tests/smc_i2c_p1_rdwr_protocol_test.py`
  sha256 `38d9fdab3c1ee6513c0d867a69361268edfee765311e903bb802560d458273ac`
- Sequence (discovered): `hw/sys/smc/dv/cocotb/seq_lib/smc_i2c_master_target_test_seq.py`
  sha256 `b51292e53837152229b7261d7ffb3ba08a1eb61f9a8479340b3ff7c9273d933a`
- Authoritative map: `hw/sys/smc/regs/gen/c/smc_addr.h` via `seq_lib/smc_addr_map.py`
- Log: `hw/sys/smc/dv/build/runs/20260806_094618__verilator__smc_i2c_p1_rdwr_protocol_test/smc_i2c_p1_rdwr_protocol_test/logs/smc_i2c_p1_rdwr_protocol_test.log`
  sha256 `7ea9b82af4eec7e96e3aa82caf2a7ff98108b96201666021bc5bf2fe57dbcfa4`
  (verified via `sha256sum`; matches invoker hint)
- Seed: 1 · simulator: verilator 5.050 2026-07-01 · model fingerprint `2c815fa08277`
- `result.json`: `status: PASS`, `exit_code: 0`, cocotb summary L735–L737:
  `TESTS=1 PASS=1 FAIL=0 SKIP=0`
- Stimulus observed: CLOCK_GATE ungating → I2C wrap enable @ `0xc0005e00` → OVRD pad
  matrix → DUT host write `0xAB@0x10` → SMBus PEC `a594` → ARA RDATA `0xA0`
- In-seq FAIL-ON proof present for host mem / PEC / ARA; alias VIP record has no
  fabricated byte golden (unlike sibling `smc_i2c_master_target_test`)
- Enrollment: `hw/sys/smc/dv/testlists/vplan_triplets.toml`
- Entry gate / Layer 2 not evaluated (MODE=NO-CHECKBOX)
- Provenance: legacy (`test_author.run_id: unknown`)
- Auditor: `minshaoho` / `cursor/grok/4.5-reaudit-20260806`

</details>

<details>
<summary>Stimulus / sample cites (kept log <code>7ea9b82a…</code>)</summary>

| Step | Line (approx) | What the log shows | Impl |
|---|---|---|---|
| seed | 13 | Python random seeded with 1 | cocotb |
| I2C0_INTR_STATE | 297 | `0xc0005000` OKAY (real I2C window) | seq `smc_indexed_addr` idx0 |
| I2C1/I2C2 INTR | 311/318 | `0xc0005200` / `0xc0005400` OKAY | seq idx1/idx2 |
| OVRD matrix | 422–454 | release/scl_low/sda_low/both/restore pads | seq `_check_line` |
| host write | 578 | `slave.mem[0x10]=ab` VIP starts/acks/stops=1 | seq `:169-218` |
| SMBus PEC | 651 | `slave.mem[0x20]=a594` | seq `:220-255` |
| SMBus ARA | 703 | `RDATA=0xA0` expected `0xA0` | seq `:257-315` |
| complete | 725–737 | U4-2 OK · protocol VIP check #1 · PASS | test + scoreboard |

</details>

## Not concluded

- Whether the intended U4-2 / SMBus host proofs match SPEC properties a future card would require (O2) — Skill 3.
- Completeness against a feature_list — no inventory applies in STANDALONE-REQUEST.
- Any closure or PROVEN checker claim — MODE=NO-CHECKBOX forbids inventing checkers from this PASS log.

## Accepted waivers

| Finding | Rule | Where | Why | Approved by |
|---|---|---|---|---|
| — | — | — | none | — |
