---
schema: dv-quality/v1
artifact: testcase-grade
testcase: smc_smbus_pmbus_test
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
- path: hw/sys/smc/dv/build/runs/20260806_094553__verilator__smc_smbus_pmbus_test/smc_smbus_pmbus_test/logs/smc_smbus_pmbus_test.log
  sha256: 4783c661f03380c887931f2615153a0b3e0f5752efb04332a8cfefd202906aee
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
  tag: '[NO-ALWAYS-PASS-CHECKER]'
  severity: Blocking
  artifact_ref: hw/sys/smc/dv/cocotb/seq_lib/smc_smbus_pmbus_test_seq.py:100-120
  observed: >
    SMBus PEC "bus proof" calls `master.smbus_write_with_pec`, which returns the
    VIP-computed `pec`, then asserts `SmcI2cEepromSlave.read_mem` equals that same
    `pec` and payload byte. Golden is the TB variable that programmed the VIP slave;
    a wrong CRC-8 that is still appended and stored still passes. Kept log L437–L438:
    `PEC=0x6D` and `slave memory at 0x10 = a56d (expected 0xA5 0x6D)` — expected is
    the VIP return, not an independent SPEC/calculator vector.
  closure_condition: >
    Assert PEC against an independent SPEC/calculator golden (fixed vector table or
    non-VIP CRC-8/0x07 reference), not against the value just written by the same
    VIP; keep slave-memory layout as a separate transport check.
  waived_by: null
- id: FIND-002
  tag: '[MUST-FAIL-ON-MISMATCH]'
  severity: Blocking
  artifact_ref: hw/sys/smc/dv/cocotb/seq_lib/smc_smbus_pmbus_test_seq.py:122-129
  observed: >
    ARA phase calls `master.smbus_query_ara()`, logs the result byte and prose
    "0xFF = no target alerting, expected in bring-up", then returns with no
    `assert`/`raise`. Kept log L439 shows `result byte = 0xFF`; any ARA byte would
    leave the sequence green.
  closure_condition: >
    Assert the exact expected ARA byte (bring-up: `0xFF`) or the alerting-slave
    address when a positive-control alerter is present; convert mismatch to test
    failure with last-state diagnostics.
  waived_by: null
- id: FIND-003
  tag: '[INDEPENDENT-EXPECTED-MODEL]'
  severity: Blocking
  artifact_ref: hw/sys/smc/dv/cocotb/seq_lib/smc_smbus_pmbus_test_seq.py:57-90
  observed: >
    PMBus Linear11/Linear16 "proof" is VIP `pmbus_encode_*` then `pmbus_decode_*`
    round-trip against the same input floats (relative error < 2%). No SPEC-derived
    fixed encoding vectors; encode and decode are the same VIP class, so a mutually
    consistent wrong formula still passes. Kept log L426–L436 shows only VIP
    round-trip lines; `v == 0.0` skips the relative assert entirely.
  closure_condition: >
    Compare encodings to an independent PMBus SPEC/reference vector table (or a
    non-VIP reference implementation), not VIP encode/decode against itself; assert
    the zero case explicitly.
  waived_by: null
- id: FIND-004
  tag: '[NO-BLIND-DELAY-SYNC]'
  severity: Major
  artifact_ref: hw/sys/smc/dv/cocotb/seq_lib/smc_csr_seq_utils.py:235-242
  observed: >
    `_i2c0_check_line` (on the `prove_dut_i2c0_pins` proof path this test invokes)
    waits a fixed `ClockCycles(dut.clk_smc_i, 100)` then samples `tb_i2c0_scl/sda`
    with no OVRD/pad completion event. This seed reached the samples (L329/L337/
    L345/L353/L361) after the fixed settle; the settle remains the sync for every
    OVRD pin check.
  closure_condition: >
    Replace the fixed 100-cycle settle with an event/handshake wait that FAIL-ON
    timeout (bounded `[TIMEOUT-MUST-FAIL]` loop on the expected pad state after OVRD
    write); keep a bare delay only if latency itself is the checked quantity.
  waived_by: null
- id: FIND-005
  tag: '[X-AWARE-CHECK]'
  severity: Major
  artifact_ref: hw/sys/smc/dv/cocotb/seq_lib/smc_csr_seq_utils.py:235-242
  observed: >
    Pin-proof and LSIO-ready helpers sample `int(dut.tb_i2c0_scl.value)` /
    `tb_i2c0_sda.value` / `tb_i2c0_scl_i.value` with no prior
    `is_resolvable` / known gate. On cocotb/Verilator an unresolved value can raise
    or resolve arbitrarily, so a compare that passes or fails on X optimism is not
    a cycle-valid proof. Same pattern as sibling SMBus grades; exercised this seed
    on the pin-proof path.
  closure_condition: >
    Resolve-and-assert-known (or equivalent) before numeric compare on
    `tb_i2c0_scl` / `tb_i2c0_sda` / `tb_i2c0_scl_i` samples used as FAIL-ON evidence.
  waived_by: null
- id: FIND-006
  tag: '[NO-DUMMY-DEAD-CODE]'
  severity: Major
  artifact_ref: hw/sys/smc/dv/cocotb/seq_lib/smc_smbus_pmbus_test_seq.py:92-98
  observed: >
    A labeled "SMBus PEC self-check" computes `expected_pec` via
    `SmcI2cMasterVip.smbus_pec` and logs it; comment cites calculator PEC `0x2E` for
    frame `[0xA0,0x10,0xA5]` but never asserts that (or any independent golden). Kept
    log L437 shows VIP `PEC=0x6D` only. Readers reasonably conclude a CRC check ran
    when only a log line exists.
  closure_condition: >
    Either assert `expected_pec` against an independent golden (and drop the stale
    `0x2E` comment), or remove the "self-check" framing so it cannot be mistaken for
    an active check.
  waived_by: null
waivers: []
recommendation: NOT-READY
---

# Grade Report — smc_smbus_pmbus_test (standalone Layer 1)

**VERDICT: 0/0 PROVEN — NOT READY** (mode NO-CHECKBOX, no_contract_reason STANDALONE-REQUEST)

| Mode | Entry gate | Checkers | Findings | Recommendation |
|---|---|---|---|---|
| `NO-CHECKBOX` | — NOT-EVALUATED | 0/0 PROVEN | 🔴 3 Blocking · 🟠 3 Major | ⛔ NOT-READY |

> No approved checkbox card or parent plan record governs this testcase
> (`STANDALONE-REQUEST` / active-regression L1 wave). Layer 1 findings are the entire
> scope of this report. `NOT-READY` records the **absence of a closure claim, not a
> defect** in the test by itself. Kept log is a sim **PASS** (seed 1): cocotb
> `TESTS=1 PASS=1 FAIL=0 SKIP=0`, pin-proof + Linear11/16 + PEC bus + ARA completed,
> zero unexplained `ERROR`/`FATAL`/`Traceback` — Layer 2 entry would still be blocked
> by open Blocking findings if a card existed.

## DELTA (re-audit vs prior grade `0/0 NOT-READY` on log `f7a6d4b8…`)

| Prior id | Tag | Status this round | Notes |
|---|---|---|---|
| FIND-001 | `[ADDRESS-FROM-AUTHORITATIVE-MAP]` | CLOSED | `prove_dut_i2c0_pins` / GPIO LSIO now use `smc_addr` / `smc_indexed_addr`; this log OKAY-writes CTRL `0xc0005e00`, OVRD `0xc0005034`, pad37 `0xc0003250` |
| FIND-002 | `[NO-BLIND-DELAY-SYNC]` | OPEN → FIND-004 | Still `ClockCycles(..., 100)` before pad sample; now exercised (PASS path) |
| FIND-003 | `[NO-ALWAYS-PASS-CHECKER]` | OPEN → FIND-001 | PEC bus golden still VIP return; now reached (L437–L438) |
| FIND-004 | `[MUST-FAIL-ON-MISMATCH]` | OPEN → FIND-002 | ARA still log-only; now reached (L439 `0xFF`) |
| — | `[INDEPENDENT-EXPECTED-MODEL]` | NEW → FIND-003 | PMBus Linear11/16 VIP round-trip only |
| — | `[X-AWARE-CHECK]` | NEW → FIND-005 | Pad samples without `is_resolvable` |
| — | `[NO-DUMMY-DEAD-CODE]` | NEW → FIND-006 | "PEC self-check" logs without independent assert |

## Your to-do — 6 items (🔴 3 Blocking · 🟠 3 Major)

| # | Kind | Id | Severity / grade | Where |
|---|---|---|---|---|
| 1 | finding | FIND-001 | 🔴 Blocking | `smc_smbus_pmbus_test_seq.py:100-120` |
| 2 | finding | FIND-002 | 🔴 Blocking | `smc_smbus_pmbus_test_seq.py:122-129` |
| 3 | finding | FIND-003 | 🔴 Blocking | `smc_smbus_pmbus_test_seq.py:57-90` |
| 4 | finding | FIND-004 | 🟠 Major | `smc_csr_seq_utils.py:235-242` |
| 5 | finding | FIND-005 | 🟠 Major | `smc_csr_seq_utils.py:235-242` |
| 6 | finding | FIND-006 | 🟠 Major | `smc_smbus_pmbus_test_seq.py:92-98` |

<details>
<summary>1. FIND-001 — 🔴 Blocking <code>[NO-ALWAYS-PASS-CHECKER]</code> — PEC golden is the VIP write value</summary>

- **Where:** `hw/sys/smc/dv/cocotb/seq_lib/smc_smbus_pmbus_test_seq.py:100-120`
- **Observed:** Slave-memory assert uses `pec` returned by the same VIP that wrote it. Log L437–L438: expected `0xA5 0x6D` is the VIP return.
- **Closure:** Independent SPEC/calculator PEC expect; separate transport vs CRC checks.

</details>

<details>
<summary>2. FIND-002 — 🔴 Blocking <code>[MUST-FAIL-ON-MISMATCH]</code> — ARA result only logged</summary>

- **Where:** `hw/sys/smc/dv/cocotb/seq_lib/smc_smbus_pmbus_test_seq.py:122-129`
- **Observed:** `smbus_query_ara()` logged as "expected 0xFF" with no assert (L439).
- **Closure:** Assert exact ARA byte (or alerting address under positive control); FAIL-ON mismatch.

</details>

<details>
<summary>3. FIND-003 — 🔴 Blocking <code>[INDEPENDENT-EXPECTED-MODEL]</code> — PMBus encode/decode is VIP self-round-trip</summary>

- **Where:** `hw/sys/smc/dv/cocotb/seq_lib/smc_smbus_pmbus_test_seq.py:57-90`
- **Observed:** Linear11/16 compare `decode(encode(v))` to `v` inside one VIP; no SPEC vector table (L426–L436).
- **Closure:** Independent PMBus reference encodings; assert zero case.

</details>

<details>
<summary>4. FIND-004 — 🟠 Major <code>[NO-BLIND-DELAY-SYNC]</code> — fixed settle before pad sample</summary>

- **Where:** `hw/sys/smc/dv/cocotb/seq_lib/smc_csr_seq_utils.py:235-242` (`ClockCycles(..., 100)`)
- **Observed:** OVRD pin checks sync with a fixed cycle count, not a completion handshake with FAIL-ON timeout (exercised this PASS seed).
- **Closure:** Event/handshake + bounded timeout that fails; do not treat bare settle as proof sync.

</details>

<details>
<summary>5. FIND-005 — 🟠 Major <code>[X-AWARE-CHECK]</code> — pad samples ignore X/Z</summary>

- **Where:** `hw/sys/smc/dv/cocotb/seq_lib/smc_csr_seq_utils.py:235-242` (`_i2c0_check_line` / LSIO wait)
- **Observed:** `int(tb_i2c0_scl/sda[/scl_i].value)` without `is_resolvable` before FAIL-ON compare.
- **Closure:** Assert known/resolvable before numeric pad compares.

</details>

<details>
<summary>6. FIND-006 — 🟠 Major <code>[NO-DUMMY-DEAD-CODE]</code> — PEC "self-check" never asserts golden</summary>

- **Where:** `hw/sys/smc/dv/cocotb/seq_lib/smc_smbus_pmbus_test_seq.py:92-98`
- **Observed:** Computes/logs `expected_pec`; comment cites `0x2E` but never asserts; log shows `0x6D`.
- **Closure:** Assert independent golden or remove self-check framing.

</details>

**Then:** owner must remediate FIND-001/002/003 on the sequence and FIND-004/005 in the shared CSR helper, re-keep a PASS log, and re-invoke `/dv_test_audit smc_smbus_pmbus_test`. Do not invent a card here (`STANDALONE-REQUEST`).

## All checkers

| Checker | Grade | Proof class | Covers | Findings |
|---|---|---|---|---|
| — | — | — | — | no card checkers (MODE=NO-CHECKBOX) |

### Layer 1 structural rule set

| Rule | Result |
|---|---|
| F1 fabricated verdict / backdoor write | ✅ clean — frontdoor SEP_IN SYS AXI via `SmcSysAxiItem`; pad samples are passive reads; no Force/deposit on proof path; ROM/efuse hex is post-PASS bring-up trailer |
| F2 can't-fail checker | 🔴 Blocking — FIND-001 · FIND-003 |
| E1 skip-to-pass | ✅ clean — missing I2C VIP `assert`s; Linear16 soft-log only when helpers absent (helpers present this run); scoreboard path scored |
| E2 empty phase | ✅ clean — pin-proof + PMBus/PEC/ARA phases run with real stimulus; ARA silence is FIND-002 not an empty stub |
| S1 silent fail | 🔴 Blocking — FIND-002 |
| O1 checker disabled | ✅ clean — SYS AXI / protocol VIP scoreboard analysis active (checks complete without raise) |
| Phase-S obligations — L1 | 🔴 Blocking — FIND-001 · FIND-002 · FIND-003; 🟠 Major — FIND-004 · FIND-005 · FIND-006; else LSIO wait raises on timeout, seed logged, enrolled in `batch_c.toml` / `all.toml`, addresses via `smc_addr_map`, no unconditional CHK token |
| Phase-S obligations — L2 (needs the card) | — not evaluated |

## Evidence appendix

<details>
<summary>Kept log + code proof-path notes</summary>

- Implementation: `hw/sys/smc/dv/cocotb/tests/smc_smbus_pmbus_test.py`
- Sequence (discovered): `hw/sys/smc/dv/cocotb/seq_lib/smc_smbus_pmbus_test_seq.py`
- Shared DUT pin gate: `hw/sys/smc/dv/cocotb/seq_lib/smc_csr_seq_utils.py` `prove_dut_i2c0_pins` / `_i2c0_check_line` / `_arm_i2c0_gpio_lsio`
- Address map: `hw/sys/smc/dv/cocotb/seq_lib/smc_addr_map.py` → generated `smc_addr.h` / `smc_reg.py`
- VIP helpers: `hw/sys/smc/dv/cocotb/seq_lib/smc_i2c_protocol_vip.py` (`smbus_*`, `pmbus_*`)
- Log: `hw/sys/smc/dv/build/runs/20260806_094553__verilator__smc_smbus_pmbus_test/smc_smbus_pmbus_test/logs/smc_smbus_pmbus_test.log`
  sha256 `4783c661f03380c887931f2615153a0b3e0f5752efb04332a8cfefd202906aee` (matches claimed)
- Seed: 1 · simulator: verilator 5.050 2026-07-01 · model fingerprint `2c815fa08277`
- Cocotb summary: `PASS` / `TESTS=1 PASS=1 FAIL=0 SKIP=0`
- Stimulus reached: CLOCK_GATE @ `0xc0010018`; I2C0 CTRL @ `0xc0005e00` OKAY + readback; OVRD @ `0xc0005034` pin matrix; GPIO LSIO pad37–40 @ `0xc0003250`+; Linear11/16; PEC write; ARA `0xFF`
- Enrollment: `hw/sys/smc/dv/testlists/batch_c.toml` (included by `all.toml`)
- Bring-up trailer (post-PASS flush): efuse/ROM hex preload — not used as SMBus golden
- Entry gate / Layer 2 not evaluated (MODE=NO-CHECKBOX)
- Provenance: legacy (`test_author.run_id: unknown`)
- Prior grade log (CLOSED for addressing only): `f7a6d4b86674c289b2c1f3a00db898468a973c1d3672bdc23373c08e94a4c211` (FAIL)

</details>

<details>
<summary>PASS cite (kept log <code>4783c661…</code>)</summary>

| Step | Line | What the log shows | Impl |
|---|---|---|---|
| CLOCK_GATE | ~280–298 | OKAY R/W `0xc0010018` | `prove_dut_i2c0_pins` |
| I2C0_CTRL_EN | 308–318 | OKAY write/readback `0xc0005e00` data `0x11` | `_I2C0_CTRL` via `smc_indexed_addr` |
| OVRD pin matrix | 322–361 | SCL/SDA 1/1→0/1→1/0→0/0→1/1 | `_i2c0_check_line` |
| LSIO arm | 369–425 | GPIO DATA_CTRL pad37–40 `0xc0003250`+; ready | `wait_i2c0_lsio_ready` |
| PMBus L11/L16 | 426–436 | VIP round-trip only | seq body |
| PEC bus | 437–438 | `PEC=0x6D`, mem `a56d` | VIP write + slave mem |
| ARA | 439 | `0xFF` logged, no assert | `smbus_query_ara` |
| cocotb summary | 449–451 | `PASS` / `PASS=1 FAIL=0` | — |

</details>

## Not concluded

- Whether this testcase proves SPEC SMBus/PMBus DUT properties versus VIP-side protocol math (O2) — Skill 3.
- Completeness against a feature_list — no inventory applies in STANDALONE-REQUEST.
- Any closure or PROVEN checker claim — MODE=NO-CHECKBOX forbids inventing checkers.

## Accepted waivers

| Finding | Rule | Where | Why | Approved by |
|---|---|---|---|---|
| — | — | — | none | — |
