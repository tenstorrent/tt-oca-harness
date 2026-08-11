---
schema: dv-quality/v1
artifact: testcase-grade
testcase: smc_i2c_error_fifo_depth_test
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
- path: hw/sys/smc/dv/build/runs/20260806_094618__verilator__smc_i2c_error_fifo_depth_test/smc_i2c_error_fifo_depth_test/logs/smc_i2c_error_fifo_depth_test.log
  sha256: 528f7b62b2cf5ec4ab3fe0006dd81410976493e38183074804c39ec226d578bc
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
  observed: >
    Shared sequence `_check_line` waits a fixed `ClockCycles(dut.clk_smc_i, 100)`
    then samples SCL/SDA with no pad/OVRD completion event
    (`smc_i2c_master_target_test_seq.py:115-129`). After `_wait_hostidle`
    returns, `_dut_i2c0_host_write_proof` and `_dut_i2c0_smbus_pec_write_proof`
    still `await Timer(50, units="us")` before reading VIP EEPROM mem (`:199`,
    `:242`). Those settles stand in for a handshake and are not themselves the
    checked quantity. Kept PASS log reaches the full OVRD matrix plus host/PEC/ARA
    (L422–L454 OVRD; L578 host write; L651 PEC; L703 ARA).
  closure_condition: >
    Replace fixed cycle/time settles with event/handshake waits that FAIL-ON
    timeout (e.g. wait for OVRD-driven pad state or sample VIP mem immediately
    after HOSTIDLE / a bounded `[TIMEOUT-MUST-FAIL]` poll); keep any delay only
    when the latency itself is the checked quantity.
  waived_by: null
- id: FIND-002
  tag: '[X-AWARE-CHECK]'
  severity: Major
  artifact_ref: hw/sys/smc/dv/cocotb/seq_lib/smc_i2c_master_target_test_seq.py:115-129
  observed: >
    OVRD pad proof `_check_line` converts `dut.tb_i2c0_scl.value` /
    `tb_i2c0_sda.value` (and dut_low mirrors) with bare `int(...)` then asserts
    equality to expected 0/1, with no resolve-and-assert-known / X/Z gate before
    the FAIL-ON compare. On cocotb/Verilator an unresolved pad can raise or
    resolve arbitrarily, so a pass on X-optimism is not cycle-valid proof. Path
    executed this seed (L422/L430/L438/L446/L454 OVRD matrix).
  closure_condition: >
    Resolve-and-assert-known (or equivalent) before numeric compare on
    tb_i2c0_scl / tb_i2c0_sda samples used as FAIL-ON evidence.
  waived_by: null
waivers: []
recommendation: NOT-READY
---

# Grade Report — smc_i2c_error_fifo_depth_test (standalone Layer 1 re-audit)

**VERDICT: 0/0 PROVEN — NOT READY** (mode NO-CHECKBOX, no_contract_reason STANDALONE-REQUEST)

| Mode | Entry gate | Checkers | Findings | Recommendation |
|---|---|---|---|---|
| `NO-CHECKBOX` | — NOT-EVALUATED | 0/0 PROVEN | 🟠 2 Major | ⛔ NOT-READY |

> No approved checkbox card or parent plan record governs this testcase
> (`STANDALONE-REQUEST` / active-regression L1 wave). Layer 1 findings are the entire
> scope of this report. `NOT-READY` records the **absence of a closure claim, not a
> defect** in the test by itself. Kept log is a sim **PASS** (seed 1):
> `TESTS=1 PASS=1 FAIL=0 SKIP=0`, `result.json status: PASS`, zero unexplained
> `ERROR`/`FATAL`/`Traceback` — Layer 2 entry is still not evaluated without a card.

## DELTA (re-audit vs prior grade `0/0 NOT-READY` on log `b94ae1d8…`)

| Item | Prior (log `b94ae1d8…`, FAIL) | This audit (log `528f7b62…`, PASS) |
|---|---|---|---|
| Verdict | 0/0 PROVEN — NOT READY | 0/0 PROVEN — NOT READY |
| Findings | 🔴 1 Blocking · 🟠 1 Major | 🟠 2 Major |
| Prior FIND-001 wrong I2C literals / TELEMETRY window | open Blocking `[ADDRESS-FROM-AUTHORITATIVE-MAP]` | **resolved** — sequence imports PeakRDL via `smc_addr_map` / `smc_indexed_addr`; log hits `0xc0005000` / `5200` / `5400` / `5e00` (I2C wrap), not `0xc0009xxx` |
| Prior FIND-002 fixed ClockCycles/Timer settle | open Major `[NO-BLIND-DELAY-SYNC]` | **still open** as FIND-001 Major — `_check_line` + host/PEC `Timer(50us)` unchanged |
| New FIND-002 bare `int(pad.value)` | — | open Major `[X-AWARE-CHECK]` — `_check_line` pad samples without known/X gate |
| VIP / sim result | FAIL at I2C2 DECERR on hand-copied `0xc0009400`; OVRD/host never reached | PASS — OVRD matrix + DUT host write + PEC + ARA complete; `csr_accesses=59` |
| Kept log | `b94ae1d8087e757d2c7430dc61a1948584db33e8ed564729baec9a2cabdd3221` | `528f7b62b2cf5ec4ab3fe0006dd81410976493e38183074804c39ec226d578bc` |
| Repo rev | `2ecc7b227e3926b253c65b5aac21239eec24ba5f` | `c10b6d63e0b3377f8e2fa38c138e2ea72cae92c7` |
| Auditor run_id | `cursor/grok/4.5` | `cursor/grok/4.5-reaudit-20260806` |
| Waivers carried | none signed (`waivers: []`) | none (nothing to drop; no signed entries) |

## Your to-do — 2 items (🟠 2 Major)

| # | Kind | Id | Severity / grade | Where |
|---|---|---|---|---|
| 1 | finding | FIND-001 | 🟠 Major | `smc_i2c_master_target_test_seq.py:115-129` (+ `:199`, `:242`) |
| 2 | finding | FIND-002 | 🟠 Major | `smc_i2c_master_target_test_seq.py:115-129` |

<details>
<summary>1. FIND-001 — 🟠 Major <code>[NO-BLIND-DELAY-SYNC]</code> — fixed settle before pad / VIP sample</summary>

- **Where:** `hw/sys/smc/dv/cocotb/seq_lib/smc_i2c_master_target_test_seq.py:115-129` (`ClockCycles(..., 100)`); also `:199` / `:242` `Timer(50, "us")`
- **Observed:** OVRD pin checks and post-host-write VIP mem reads sync with fixed delays, not a completion handshake with FAIL-ON timeout. Reached this seed (PASS path).
- **Closure:** Event/handshake + bounded timeout that fails; do not treat bare settle as proof sync.

</details>

<details>
<summary>2. FIND-002 — 🟠 Major <code>[X-AWARE-CHECK]</code> — pad samples without known/X gate</summary>

- **Where:** `hw/sys/smc/dv/cocotb/seq_lib/smc_i2c_master_target_test_seq.py:115-129`
- **Observed:** `_check_line` uses bare `int(tb_i2c0_scl/sda.value)` before FAIL-ON equality; no X/Z resolve-and-assert-known. Executed this seed (OVRD matrix).
- **Closure:** Assert known before numeric pad compares used as proof.

</details>

**Then:** owner remediates FIND-001/FIND-002 sync and X-aware hygiene on the shared `smc_i2c_master_target_test_seq` OVRD + host path, re-keeps a PASS log for `smc_i2c_error_fifo_depth_test`, and re-invokes `/dv_test_audit smc_i2c_error_fifo_depth_test`. Do not invent a card here (`STANDALONE-REQUEST`).

## All checkers

| Checker | Grade | Proof class | Covers | Findings |
|---|---|---|---|---|
| — | — | — | — | no card checkers (MODE=NO-CHECKBOX) |

### Layer 1 structural rule set

| Rule | Result |
|---|---|
| F1 fabricated verdict / backdoor write | ✅ clean — frontdoor SEP_IN SYS AXI via `SmcSysAxiItem`; pad samples are passive reads; test `record_protocol_vip` passes `csr_accesses`/`details` only (no invented observed/expected bytes); no Force/deposit on proof path; ROM/efuse hex is post-PASS bring-up trailer |
| F2 can't-fail checker | ✅ clean — scoreboard `assert item.resp_ok` and seq pad/host/PEC/ARA asserts are reachable FAIL-ON; this run passed through real compares |
| E1 skip-to-pass | ✅ clean — missing EEPROM VIP raises `AssertionError`; bind warning does not mark pass |
| E2 empty phase | ✅ clean — CSR sweep + OVRD matrix + DUT host write + SMBus PEC/ARA all executed (59 CSR accesses) |
| S1 silent fail | ✅ clean — scoreboard/seq `assert` raise on mismatch; success log only after asserts |
| O1 checker disabled | ✅ clean — SYS AXI scoreboard checks #1–#59 + protocol VIP check #1 active; axi_monitor 0 errors |
| Phase-S obligations — L1 | 🟠 Major — FIND-001 `[NO-BLIND-DELAY-SYNC]`, FIND-002 `[X-AWARE-CHECK]`; else addresses from `smc_addr_map`, `_wait_hostidle` / ARA poll / LSIO wait raise on timeout, seed logged, enrolled in `vplan_triplets.toml` (pulled by `all.toml`), force-free, no unconditional CHK token |
| Phase-S obligations — L2 (needs the card) | — not evaluated |

## Evidence appendix

<details>
<summary>Kept log + code proof-path notes</summary>

- Implementation: `hw/sys/smc/dv/cocotb/tests/smc_i2c_error_fifo_depth_test.py`
  sha256 `272170cd8e8f46dd50d6229470cac182a4cf12839ae1195158f6abc2777e9ebe`
- Sequence (discovered): `hw/sys/smc/dv/cocotb/seq_lib/smc_i2c_master_target_test_seq.py`
  sha256 `b51292e53837152229b7261d7ffb3ba08a1eb61f9a8479340b3ff7c9273d933a`
  (shared with `smc_i2c_master_target_test` / `smc_i2c_p1_rdwr_protocol_test`; OVRD + DUT host write + SMBus PEC/ARA — not an error/FIFO-depth stimulus)
- Scoreboard (proof path): `hw/sys/smc/dv/cocotb/env/smc_scoreboard.py` `_check_sys_axi` / `_check_protocol_vip`
- Authoritative map: `hw/sys/smc/regs/gen/c/smc_addr.h` via `seq_lib/smc_addr_map.py`
- Log: `hw/sys/smc/dv/build/runs/20260806_094618__verilator__smc_i2c_error_fifo_depth_test/smc_i2c_error_fifo_depth_test/logs/smc_i2c_error_fifo_depth_test.log`
  sha256 `528f7b62b2cf5ec4ab3fe0006dd81410976493e38183074804c39ec226d578bc`
  (verified via `manifest.py hash-file`; matches invoker hint)
- Seed: 1 · simulator: verilator 5.050 2026-07-01 · model fingerprint `2c815fa08277`
- Repo rev: `c10b6d63e0b3377f8e2fa38c138e2ea72cae92c7`
- `result.json`: `status: PASS`, `exit_code: 0`, cocotb summary L731–L737:
  `TESTS=1 PASS=1 FAIL=0 SKIP=0`
- Stimulus observed: CLOCK_GATE → I2C0/1/2 INTR @ `0xc0005000`/`5200`/`5400` → wrap enable
  @ `0xc0005e00` → OVRD pad matrix → DUT host write `0xAB@0x10` → SMBus PEC `a594` →
  ARA RDATA `0xA0` → CG restore
- Enrollment: `hw/sys/smc/dv/testlists/vplan_triplets.toml` (included by `all.toml`)
- Bring-up trailer (post-PASS flush): efuse/ROM hex preload — not used as I2C golden
- Entry gate / Layer 2 not evaluated (MODE=NO-CHECKBOX)
- Provenance: legacy (`test_author.run_id: unknown`); auditor `run_id: cursor/grok/4.5-reaudit-20260806`

</details>

<details>
<summary>Stimulus / PASS cites (kept log <code>528f7b62…</code>)</summary>

| Step | Line (approx) | What the log shows | Impl |
|---|---|---|---|
| CLOCK_GATE | 281–294 | OKAY read `0xc0010018` data `0x1f000000` | seq CLOCK_GATE via addr_map |
| I2C0_INTR_STATE | 296–301 | OKAY `0xc0005000` data 0 | `I2C_READABLE_REGS` |
| I2C1 / I2C2 INTR | 310–322 | OKAY `0xc0005200` / `5400` | same |
| wrap enable | 344–354 | write/read `0xc0005e00` data `0x11` | `I2C0_WRAP_CTRL` |
| LSIO ready | 414 | `I2C0_WRAP_ENABLE ready: bus_scl=1 scl_i=1` | `wait_i2c0_lsio_ready` |
| OVRD release / scl/sda/both | 422 / 430 / 438 / 446 / 454 | pad samples match expected | `_check_line` |
| host write | 578 | `slave.mem[0x10]=ab` expected `0xAB` | `_dut_i2c0_host_write_proof` |
| PEC write | 651 | `slave.mem[0x20]=a594` | `_dut_i2c0_smbus_pec_write_proof` |
| ARA | 703 | `RDATA=0xA0 expected 0xA0` | `_dut_i2c0_smbus_ara_read_proof` |
| U4-2 complete | 725 | host write + PEC + ARA OK | seq body |
| VIP scoreboard | 726–727 | `csr_accesses=59` details pin OVRD (no byte golden) | test `:18-27` |
| cocotb result | 731–737 | `PASS` / `TESTS=1 PASS=1 FAIL=0 SKIP=0` | — |

</details>

## Not concluded

- Whether this testcase (name: error/FIFO depth; body: shared master-target OVRD+host+SMBus seq) proves any SPEC error/FIFO property (O2) — Skill 3.
- Completeness against a feature_list — no inventory applies in STANDALONE-REQUEST.
- Any closure or PROVEN checker claim — MODE=NO-CHECKBOX forbids inventing checkers.

## Accepted waivers

| Finding | Rule | Where | Why | Approved by |
|---|---|---|---|---|
| — | — | — | none | — |
