---
schema: dv-quality/v1
artifact: testcase-grade
testcase: smc_i2c_master_target_test
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
- path: hw/sys/smc/dv/build/runs/20260806_094550__verilator__smc_i2c_master_target_test/smc_i2c_master_target_test/logs/smc_i2c_master_target_test.log
  sha256: 555909247213a7e5f94286a1bc26ff576fb4ae647408478a44aac1b376fac512
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
  tag: '[NO-FABRICATED-VERDICT]'
  severity: Blocking
  artifact_ref: hw/sys/smc/dv/cocotb/tests/smc_i2c_master_target_test.py:28-42
  observed: >-
    After the SMBus gate assert, the test sets observed_bytes = expected_bytes
    whenever dut_host_write_ok and dut_smbus_ara_ok are true
    (`obs = exp if (...) else b""`), then passes both into record_protocol_vip.
    SmcScoreboard._check_protocol_vip asserts observed_bytes == expected_bytes,
    so the VIP byte golden compare cannot fail once the boolean flags are set —
    the "observed" payload is invented, not sampled from slave mem / RDATA.
    Kept log L726–L727 shows golden=aba0 obs=aba0 on the scoreboard line.
  closure_condition: >-
    Build observed_bytes from independently measured DUT/VIP results (e.g. EEPROM
    mem byte + ARA RDATA already checked in-seq) without copying exp; keep the
    scoreboard compare as a real FAIL-ON path.
  waived_by: null
- id: FIND-002
  tag: '[NO-BLIND-DELAY-SYNC]'
  severity: Major
  artifact_ref: hw/sys/smc/dv/cocotb/seq_lib/smc_i2c_master_target_test_seq.py:115-129
  observed: >-
    After _wait_hostidle returns (STATUS HOSTIDLE handshake), both
    _dut_i2c0_host_write_proof and _dut_i2c0_smbus_pec_write_proof still
    `await Timer(50, units="us")` before reading VIP EEPROM mem
    (seq :199, :242). That fixed delay is not a completion handshake and is not
    itself the checked quantity. OVRD pad `_check_line` likewise samples only
    after `ClockCycles(..., 100)` with no event/timeout FAIL-ON for pad settle
    (:115-129). Kept PASS log reaches all three host proofs (L578 host write,
    L651 PEC, L703 ARA).
  closure_condition: >-
    Sample VIP mem / pads immediately after the HOSTIDLE (or other named)
    handshake, or replace the fixed delay with a bounded event wait that fails
    on expiry with last-state diagnostics; do not use bare Timer/ClockCycles as
    the sync before the FAIL-ON compare.
  waived_by: null
- id: FIND-003
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

# Grade Report — smc_i2c_master_target_test (standalone Layer 1 re-audit)

**VERDICT: 0/0 PROVEN — NOT READY** (mode NO-CHECKBOX, no_contract_reason STANDALONE-REQUEST)

| Mode | Entry gate | Checkers | Findings | Recommendation |
|---|---|---|---|---|
| `NO-CHECKBOX` | — NOT-EVALUATED | 0/0 PROVEN | 🔴 1 Blocking · 🟠 2 Major | ⛔ NOT-READY |

> No approved checkbox card or parent plan record governs this testcase
> (`STANDALONE-REQUEST` / active-regression L1 wave). Layer 1 findings are the entire
> scope of this report. `NOT-READY` records the **absence of a closure claim, not a
> defect** in the test by itself. Kept log is a sim **PASS** (seed 1):
> `TESTS=1 PASS=1 FAIL=0 SKIP=0`, `result.json status: PASS`, zero unexplained
> `ERROR`/`FATAL`/`Traceback` — Layer 2 entry is still not evaluated without a card.

## Delta from prior round (`smc_i2c_master_target_test_GRADE.md`, kept log `6ed3d38a…`)

| Item | Prior round | This round |
|---|---|---|
| Kept log | FAIL seed1 `6ed3d38a…` (DECERR @ `0xc0009400`) | PASS seed1 `55590924…` (`20260806_094550`) |
| Prior `FIND-001` `[ADDRESS-FROM-AUTHORITATIVE-MAP]` | Open (Blocking) — hand `0xC000_9xxx` I2C literals | **Closed** — seq now imports `smc_addr` / `smc_indexed_addr`; log traffic hits `0xc0005000` / `5200` / `5400` / `5e00` |
| Prior `FIND-002` `[NO-FABRICATED-VERDICT]` | Open (Blocking) — `obs = exp if flags` | **Open** as FIND-001 — same `smc_i2c_master_target_test.py:28-42`; log L726–727 `golden=aba0 obs=aba0` |
| Prior `FIND-003` `[NO-BLIND-DELAY-SYNC]` | Open (Major) — Timer(50us) / ClockCycles(100) | **Open** as FIND-002 — same sync pattern still on proof path |
| `FIND-003` `[X-AWARE-CHECK]` | — (not filed) | **New** Major — bare `int(pad.value)` in `_check_line` |
| Recommendation | ⛔ NOT-READY | ⛔ NOT-READY |
| Waivers carried forward | — | `waivers: []` — prior ledger empty (`approved_by` none); nothing to carry |

**Root cause of the address fix (verified in `seq_lib/smc_i2c_master_target_test_seq.py`):**
proof-path I2C / wrap / CLOCK_GATE addresses are resolved via `smc_addr_map`
(`smc_addr` / `smc_indexed_addr` from PeakRDL `smc_addr.h`), replacing the prior
`0xC000_9xxx` literals. Kept PASS log shows host write / PEC / ARA completing on the
real I2C0 window.

## Your to-do — 3 items (🔴 1 Blocking · 🟠 2 Major)

| # | Kind | Id | Severity / grade | Where |
|---|---|---|---|---|
| 1 | finding | FIND-001 | 🔴 Blocking | `smc_i2c_master_target_test.py:28-42` |
| 2 | finding | FIND-002 | 🟠 Major | `smc_i2c_master_target_test_seq.py:115-129` (+ `:199`, `:242`) |
| 3 | finding | FIND-003 | 🟠 Major | `smc_i2c_master_target_test_seq.py:115-129` |

<details>
<summary>1. FIND-001 — 🔴 Blocking <code>[NO-FABRICATED-VERDICT]</code> — VIP <code>observed_bytes</code> copied from <code>exp</code></summary>

- **Where:** `hw/sys/smc/dv/cocotb/tests/smc_i2c_master_target_test.py:28-42`
- **Observed:** `obs = exp if (dut_host_write_ok and dut_smbus_ara_ok) else b""` feeds `record_protocol_vip`; scoreboard then asserts `obs == exp`, so the byte compare cannot fail once flags are true. Log L726–727: `golden=aba0 obs=aba0`.
- **Closure:** Pass measured bytes (slave mem / ARA RDATA) as `observed_bytes`, never a copy of `exp`.

</details>

<details>
<summary>2. FIND-002 — 🟠 Major <code>[NO-BLIND-DELAY-SYNC]</code> — fixed 50 µs / 100 cycles before sample</summary>

- **Where:** `hw/sys/smc/dv/cocotb/seq_lib/smc_i2c_master_target_test_seq.py:115-129` (`_check_line`); also host/PEC proofs `:199`, `:242`
- **Observed:** Host-write and PEC proofs wait `Timer(50, "us")` after HOSTIDLE before VIP mem compare; OVRD pad checks sample only after 100 `ClockCycles`.
- **Closure:** Sync on handshake / bounded event with FAIL-ON timeout; do not use bare delay before the compare.

</details>

<details>
<summary>3. FIND-003 — 🟠 Major <code>[X-AWARE-CHECK]</code> — pad samples without known/X gate</summary>

- **Where:** `hw/sys/smc/dv/cocotb/seq_lib/smc_i2c_master_target_test_seq.py:115-129`
- **Observed:** `_check_line` uses bare `int(tb_i2c0_scl/sda.value)` before FAIL-ON equality; no X/Z resolve-and-assert-known. Executed this seed (OVRD matrix).
- **Closure:** Assert known before numeric pad compares used as proof.

</details>

**Then:** owner fixes FIND-001 (fabricated VIP bytes) first, then FIND-002/003 hygiene on the OVRD + host path, re-keeps a PASS log, and re-invokes `/dv_test_audit smc_i2c_master_target_test`. Do not invent a card here (`STANDALONE-REQUEST`).

## All checkers

| Checker | Grade | Proof class | Covers | Findings |
|---|---|---|---|---|
| — | — | — | — | no card checkers (MODE=NO-CHECKBOX) |

### Layer 1 structural rule set

| Rule | Result |
|---|---|
| F1 fabricated verdict / backdoor write | 🔴 Blocking — FIND-001; no force/deposit on proof path (frontdoor SYS AXI + pad OVRD + VIP slave) |
| F2 can't-fail checker | ✅ clean — in-seq `assert got == bytes([...])` / ARA RDATA / CSR scoreboard `resp_ok` are reachable FAIL-ON (VIP byte golden is FIND-001, not a separate tautology) |
| E1 skip-to-pass | ✅ clean — missing EEPROM VIP raises AssertionError; import failure does not mark pass |
| E2 empty phase | ✅ clean — body issues real CSR R/W, OVRD pad matrix, DUT host write + PEC + ARA |
| S1 silent fail | ✅ clean — axi_monitor + scoreboard + seq/test `assert` raise on mismatch |
| O1 checker disabled | ✅ clean — SYS AXI scoreboard and protocol VIP scoreboard active (L727 protocol VIP check #1) |
| Phase-S obligations — L1 | 🔴 Blocking — FIND-001 `[NO-FABRICATED-VERDICT]`; 🟠 Major — FIND-002 `[NO-BLIND-DELAY-SYNC]`, FIND-003 `[X-AWARE-CHECK]`; else `_wait_hostidle` / ARA poll raise on timeout; addresses from `smc_addr_map`; seed logged; enrolled in `i2c.toml` / `all.toml` / `batch_c.toml`; force-free pad/VIP path; ROM/efuse `$readmemh` is bring-up trailer not I2C golden |
| Phase-S obligations — L2 (needs the card) | — not evaluated |

## Evidence appendix

<details>
<summary>Kept log + code proof-path notes</summary>

- Implementation: `hw/sys/smc/dv/cocotb/tests/smc_i2c_master_target_test.py`
  sha256 `3fd49f4747b120330f43bc5a023db2a2bdb030c03230d4c03710f6202db6bfca`
- Sequence: `hw/sys/smc/dv/cocotb/seq_lib/smc_i2c_master_target_test_seq.py`
  sha256 `b51292e53837152229b7261d7ffb3ba08a1eb61f9a8479340b3ff7c9273d933a`
- Authoritative map: `hw/sys/smc/regs/gen/c/smc_addr.h` via `seq_lib/smc_addr_map.py`
- Log: `hw/sys/smc/dv/build/runs/20260806_094550__verilator__smc_i2c_master_target_test/smc_i2c_master_target_test/logs/smc_i2c_master_target_test.log`
  sha256 `555909247213a7e5f94286a1bc26ff576fb4ae647408478a44aac1b376fac512`
  (verified via `manifest.py hash-file`; matches invoker hint)
- Seed: 1 · simulator: verilator 5.050 2026-07-01 · model fingerprint `2c815fa08277`
- `result.json`: `status: PASS`, `exit_code: 0`, cocotb summary L735–L737:
  `TESTS=1 PASS=1 FAIL=0 SKIP=0`
- Stimulus observed: CLOCK_GATE ungating → I2C wrap enable @ `0xc0005e00` → OVRD pad
  matrix → DUT host write `0xAB@0x10` → SMBus PEC `a594` → ARA RDATA `0xA0`
- In-seq FAIL-ON proof present for host mem / PEC / ARA; VIP `observed_bytes` still
  fabricated (FIND-001)
- Enrollment: `hw/sys/smc/dv/testlists/i2c.toml`, `all.toml`, `batch_c.toml`
- Entry gate / Layer 2 not evaluated (MODE=NO-CHECKBOX)
- Provenance: legacy (`test_author.run_id: unknown`)
- Auditor `run_id`: `cursor/grok/4.5-reaudit-20260806` (differs from prior `cursor/grok/4.5`)

</details>

<details>
<summary>Stimulus / PASS cites (kept log <code>55590924…</code>)</summary>

| Step | Line (approx) | What the log shows | Impl |
|---|---|---|---|
| bring-up | 266+ | clocks + powergood | `smc_base_test` |
| I2C0_INTR precheck | 296–299 | `0xc0005000 -> 0` OKAY | `I2C_READABLE_REGS` via addr_map |
| I2C1 / I2C2 INTR | 310–320 | `0xc0005200` / `5400` OKAY | same |
| wrap enable | 344–354 | write/read `0xc0005e00` data `0x11` | `I2C0_WRAP_CTRL` |
| OVRD release / scl_low | 422 / 430 | pad samples match expected | `_check_line` |
| host write | 578 | `slave.mem[0x10]=ab` expected `0xAB` | `_dut_i2c0_host_write_proof` |
| PEC write | 651 | `slave.mem[0x20]=a594` | `_dut_i2c0_smbus_pec_write_proof` |
| ARA | 703 | `RDATA=0xA0 expected 0xA0` | `_dut_i2c0_smbus_ara_read_proof` |
| U4-2 complete | 725 | host write + PEC + ARA OK | seq body |
| VIP scoreboard | 726–727 | `golden=aba0 obs=aba0` (fabricated obs) | test `:28-42` |
| cocotb result | 735–737 | `PASS` / `TESTS=1 PASS=1 FAIL=0 SKIP=0` | — |

</details>

## Not concluded

- Whether a U4-2 host/SMBus path matches SPEC I2C properties (O2) — Skill 3.
- Completeness against a feature_list — no inventory applies in STANDALONE-REQUEST.
- Any closure or PROVEN checker claim — MODE=NO-CHECKBOX forbids inventing checkers.

## Accepted waivers

| Finding | Rule | Where | Why | Approved by |
|---|---|---|---|---|
| — | — | — | none | — |
