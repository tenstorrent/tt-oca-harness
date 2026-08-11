---
schema: dv-quality/v1
artifact: testcase-grade
testcase: smc_smbus_hostnotify_test
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
- path: hw/sys/smc/dv/build/runs/20260806_094554__verilator__smc_smbus_hostnotify_test/smc_smbus_hostnotify_test/logs/smc_smbus_hostnotify_test.log
  sha256: d577900736e7f900663e06db959a7eb27fc561359d9cc8542d8028bec9ec2a1a
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
  artifact_ref: hw/sys/smc/dv/cocotb/tests/smc_smbus_hostnotify_test.py:26-38
  observed: >-
    After `assert seq.dut_host_notify_ok`, the test sets
    `obs = exp if seq.dut_host_notify_ok else b""` with
    `exp = bytes([0xA0, 0xEF, 0xBE])`, then passes both into
    `record_protocol_vip(..., expected_bytes=exp, observed_bytes=obs)`.
    Once the boolean gate has passed, `obs` is always `exp`, so
    `smc_scoreboard._check_protocol_vip` byte compare cannot fail — observed
    bytes are canned from the expected vector, not from DUT ACQDATA. Kept log
    PASS confirms `golden=a0efbe obs=a0efbe` (L593–L594). Sequence-body ACQDATA
    match against independently packed `expected_payload` is separate and
    fail-capable (L576 entries `0xA0/0xEF/0xBE`).
  closure_condition: >-
    Pass the actual drained Host Notify payload bytes from the sequence (the
    same `data_bytes` / VIP `payload` already compared to `expected_payload`)
    as `observed_bytes`; keep `expected_bytes` as the independently derived
    vector. Never assign `obs = exp`.
  waived_by: null
- id: FIND-002
  tag: '[NO-BLIND-DELAY-SYNC]'
  severity: Major
  artifact_ref: hw/sys/smc/dv/cocotb/seq_lib/smc_csr_seq_utils.py:235-242
  observed: >-
    On the proof path this test invokes, `_i2c0_check_line` waits a fixed
    `ClockCycles(dut.clk_smc_i, 100)` then samples SCL/SDA with no pad/OVRD
    completion event (executed this seed: pin-proof lines at L329–L361). The
    host-notify sequence also uses `await ClockCycles(..., 20)` after
    ENABLETARGET and a bare `await Timer(50, units="us")` after ACQ nonempty
    before drain (`smc_smbus_hostnotify_test_seq.py:153-167`). Those settles
    stand in for a handshake. (The ACQEMPTY poll loop itself has a FAIL-ON
    timeout — that part is fine.)
  closure_condition: >-
    Replace fixed cycle/time settles with event/handshake waits that FAIL-ON
    timeout (pad state match, VIP completion, or ACQ occupancy with a bounded
    `[TIMEOUT-MUST-FAIL]` loop); keep a bare delay only when the latency itself
    is the checked quantity.
  waived_by: null
- id: FIND-003
  tag: '[X-AWARE-CHECK]'
  severity: Major
  artifact_ref: hw/sys/smc/dv/cocotb/seq_lib/smc_csr_seq_utils.py:238-242
  observed: >-
    Pin-proof and LSIO-ready helpers on this test's path use
    `int(dut.tb_i2c0_scl.value)` / `int(dut.tb_i2c0_sda.value)` /
    `int(dut.tb_i2c0_scl_i.value)` with no X/Z gate. An unresolved pad during
    the check window can raise or resolve arbitrarily in cocotb, so a pass is
    not X-aware. Reached this seed (OVRD pin-proof + LSIO ready both executed).
  closure_condition: >-
    Resolve-and-assert-known (or equivalent X/Z reject) before comparing pad
    levels in `_i2c0_check_line` / `wait_i2c0_lsio_ready`; fail the test on
    unknown values during the checked window.
  waived_by: null
waivers: []
recommendation: NOT-READY
---

# Grade Report — smc_smbus_hostnotify_test (standalone Layer 1)

**VERDICT: 0/0 PROVEN — NOT READY** (mode NO-CHECKBOX, no_contract_reason STANDALONE-REQUEST)

| Mode | Entry gate | Checkers | Findings | Recommendation |
|---|---|---|---|---|
| `NO-CHECKBOX` | — NOT-EVALUATED | 0/0 PROVEN | 🔴 1 Blocking · 🟠 2 Major | ⛔ NOT-READY |

> No approved checkbox card or parent plan record governs this testcase
> (`STANDALONE-REQUEST` / active-regression L1 wave). Layer 1 findings are the entire
> scope of this report. `NOT-READY` records the **absence of a closure claim, not a
> defect** in the test by itself. Kept log is a sim **PASS** (seed 1); Layer 2 entry
> is not evaluated in this mode. Authoritative PASS (policy §5) holds for the kept
> log (cocotb PASS, final `assert seq.dut_host_notify_ok` executed, no unexplained
> ERROR/FATAL/Traceback) but does not close Layer 1 findings.

## DELTA (re-audit vs prior grade `0/0 NOT-READY` on log `d9faed86…`)

| Item | Prior (log `d9faed86…`, FAIL) | This audit (log `d5779007…`, PASS) |
|---|---|---|
| Verdict | 0/0 PROVEN — NOT READY | 0/0 PROVEN — NOT READY |
| Findings | 🔴 2 Blocking · 🟠 2 Major | 🔴 1 Blocking · 🟠 2 Major |
| Prior FIND-001 `[ADDRESS-FROM-AUTHORITATIVE-MAP]` | open — hand `0xC0009xxx` / WRAP `0xC0009E00` → SLVERR | **closed** — seq + prove helpers use `smc_addr` / `smc_indexed_addr`; log hits I2C wrap `0xc0005e00` / `0xc00050xx` / GPIO `0xc00032xx` |
| Prior FIND-002 `[NO-FABRICATED-VERDICT]` | open — VIP `obs←exp` (not reached) | still open → this FIND-001; log `golden=a0efbe obs=a0efbe` |
| Prior FIND-003 `[NO-BLIND-DELAY-SYNC]` | open — fixed settles (not reached) | still open → this FIND-002; pin-proof + post-ACQ `Timer(50us)` executed |
| Prior FIND-004 `[X-AWARE-CHECK]` | open — pad `int(.value)` (not reached) | still open → this FIND-003; OVRD/LSIO path executed |
| Kept log | `d9faed861c10686b0b7ca3fb49066329e6d15da19889ce527198e1932c921654` FAIL | `d577900736e7f900663e06db959a7eb27fc561359d9cc8542d8028bec9ec2a1a` PASS |
| repository_revision | `2ecc7b22…` | `c10b6d63…` |
| Sim result | FAIL (WRAP write SLVERR @ `0xc0009e00`) | PASS (`TESTS=1 PASS=1 FAIL=0`; ACQDATA `a0efbe`) |
| Waivers carried | none signed (`waivers: []`) | none (nothing to drop; no signed entries) |

## Your to-do — 3 items (🔴 1 Blocking · 🟠 2 Major)

| # | Kind | Id | Severity / grade | Where |
|---|---|---|---|---|
| 1 | finding | FIND-001 | 🔴 Blocking | `smc_smbus_hostnotify_test.py:26-38` |
| 2 | finding | FIND-002 | 🟠 Major | `smc_csr_seq_utils.py:235-242` |
| 3 | finding | FIND-003 | 🟠 Major | `smc_csr_seq_utils.py:238-242` |

<details>
<summary>1. FIND-001 — 🔴 Blocking <code>[NO-FABRICATED-VERDICT]</code> — VIP observed_bytes copied from expected</summary>

- **Where:** `hw/sys/smc/dv/cocotb/tests/smc_smbus_hostnotify_test.py:26-38`
- **Observed:** `obs = exp if seq.dut_host_notify_ok else b""` feeds `record_protocol_vip`; after the assert, scoreboard byte compare is tautological (`golden=a0efbe obs=a0efbe`). Sequence ACQDATA match remains fail-capable and did run this seed.
- **Closure:** Record real ACQ/VIP payload bytes as `observed_bytes`; never assign `obs = exp`.

</details>

<details>
<summary>2. FIND-002 — 🟠 Major <code>[NO-BLIND-DELAY-SYNC]</code> — fixed settle before pad / ACQ sample</summary>

- **Where:** `hw/sys/smc/dv/cocotb/seq_lib/smc_csr_seq_utils.py:235-242` (`ClockCycles(..., 100)`); also hostnotify seq `:153` / `:167`
- **Observed:** OVRD pin checks and post-ACQ drain sync with fixed delays, not a completion handshake with FAIL-ON timeout (ACQEMPTY poll exception path is OK). Executed this PASS seed.
- **Closure:** Event/handshake + bounded timeout that fails; do not treat bare settle as proof sync.

</details>

<details>
<summary>3. FIND-003 — 🟠 Major <code>[X-AWARE-CHECK]</code> — pad samples ignore X/Z</summary>

- **Where:** `hw/sys/smc/dv/cocotb/seq_lib/smc_csr_seq_utils.py:238-242` (and LSIO wait `int(...value)` path)
- **Observed:** `int(tb_i2c0_scl/sda[/scl_i].value)` without knownness gate on the prove/LSIO path this test calls. Executed this seed.
- **Closure:** Assert known before level compare; fail on X/Z in the checked window.

</details>

**Then:** owner remediates FIND-001 (VIP `observed_bytes`) and FIND-002/003 on the shared prove helpers + hostnotify settles, re-keeps a PASS log, and re-invokes `/dv_test_audit smc_smbus_hostnotify_test`. Do not invent a card here (`STANDALONE-REQUEST`).

## All checkers

| Checker | Grade | Proof class | Covers | Findings |
|---|---|---|---|---|
| — | — | — | — | no card checkers (MODE=NO-CHECKBOX) |

### Layer 1 structural rule set

| Rule | Result |
|---|---|
| F1 fabricated verdict / backdoor write | 🔴 Blocking — FIND-001; AXI path itself is frontdoor `SmcSysAxiItem` (no Force/deposit); ROM/efuse hex is post-PASS bring-up trailer |
| F2 can't-fail checker | 🔴 Blocking — FIND-001 (VIP `obs←exp` makes scoreboard byte compare can't-fail); sequence ACQDATA/`assert entries`/`matched` are fail-capable and ran this seed |
| E1 skip-to-pass | ✅ clean — missing I2C VIP raises; no soft-pass on unavailable HDL path; body completed Host Notify + ACQ drain |
| E2 empty phase | ✅ clean — prove_dut_i2c0_pins + Host Notify body issue real CSR/VIP stimulus (pin-proof + ACQDATA entries logged) |
| S1 silent fail | ✅ clean — scoreboard/`AssertionError` raise on mismatch; STOP-missing is warning only after payload gate |
| O1 checker disabled | ✅ clean — SYS AXI scoreboard analysis active (checks #1–#35+) and protocol VIP check #1 in log |
| Phase-S obligations — L1 | 🔴 Blocking — FIND-001; 🟠 Major — FIND-002 · FIND-003; else address-from-map clean (`smc_addr`/`smc_indexed_addr` → I2C `0xC0005xxx` / GPIO `0xC0003xxx`), ACQEMPTY poll timeout raises, seed=1 logged, enrolled in `batch_c.toml`/`all.toml`, no unconditional CHK token |
| Phase-S obligations — L2 (needs the card) | — not evaluated |

## Evidence appendix

<details>
<summary>Kept log + code proof-path notes</summary>

- Implementation: `hw/sys/smc/dv/cocotb/tests/smc_smbus_hostnotify_test.py`
  sha256 `7a331462be509421f2f7910b6fdd43d1e080907b3870f2a48959b1d064eae080`
- Sequence: `hw/sys/smc/dv/cocotb/seq_lib/smc_smbus_hostnotify_test_seq.py`
  sha256 `49615acf089ce11609685fea0bbae50f9f491ebc1ce4c81af0601cdf88259dd6`
- Prove / LSIO helpers (proof path): `hw/sys/smc/dv/cocotb/seq_lib/smc_csr_seq_utils.py`
  sha256 `0485781080654788045c5746017779f0c956af1d3cba2d40e03780976046e648`
  (`prove_dut_i2c0_pins` / `_i2c0_check_line` / `wait_i2c0_lsio_ready`)
- Scoreboard (proof path): `hw/sys/smc/dv/cocotb/env/smc_scoreboard.py` `_check_sys_axi` /
  `_check_protocol_vip`
- Authoritative map: `hw/sys/smc/regs/gen/c/smc_addr.h` via `seq_lib/smc_addr_map.py`
- Log: `hw/sys/smc/dv/build/runs/20260806_094554__verilator__smc_smbus_hostnotify_test/smc_smbus_hostnotify_test/logs/smc_smbus_hostnotify_test.log`
  sha256 `d577900736e7f900663e06db959a7eb27fc561359d9cc8542d8028bec9ec2a1a`
  (verified via `manifest.py hash-file`; matches claimed)
- Seed: 1 · simulator: verilator 5.050 2026-07-01 · model fingerprint `2c815fa08277`
- `result.json`: `status: PASS`, `exit_code: 0`, cocotb summary L602–L604:
  `smc_smbus_hostnotify_test … PASS` / `TESTS=1 PASS=1 FAIL=0 SKIP=0`
- Stimulus reached: prove_dut_i2c0_pins (WRAP `0xc0005e00`, OVRD `0xc0005034`, pad toggles);
  CLOCK_GATE ungating; LSIO GPIO DATA_CTRL `0xc0003250+`; timing/TARGET_ID/ENABLETARGET;
  VIP Host Notify; ACQDATA drain `0xA0/0xEF/0xBE`; `record_protocol_vip`
- Addressing identity (resolved this round):
  - I2C_CTRL / OVRD / CTRL / STATUS / ACQDATA → `0xc0005e00` / `5034` / `5010` / `5014` / `5058`
  - GPIO0 DATA_CTRL base `0xc0003000` (pad 37 → `0xc0003250`)
- Enrollment: `hw/sys/smc/dv/testlists/batch_c.toml`, `all.toml`
- Bring-up trailer: efuse/ROM hex preload after PASS flush — not used as Host Notify golden
- Entry gate / Layer 2 not evaluated (MODE=NO-CHECKBOX); authoritative PASS (§5) met for
  the kept log but unused for entry in this mode
- Provenance: legacy (`test_author.run_id: unknown`)

</details>

<details>
<summary>PASS cite (kept log <code>d5779007…</code>)</summary>

| Step | Line | What the log shows | Impl |
|---|---|---|---|
| WRAP enable OKAY | 308–313 | write `0xc0005e00` ← `0x11`, bresp=0 | prove `_I2C0_CTRL` |
| OVRD pin-proof | 329–361 | `i2c0_release`…`release_restore` SCL/SDA match | `_i2c0_check_line` |
| LSIO ready | 447 | `I2C0_HOSTNOTIFY_WRAP ready: bus_scl=1 scl_i=1 enable=1` | `wait_i2c0_lsio_ready` |
| ENABLETARGET | 504–509 | write `0xc0005010` ← `0x2` OKAY | seq `:150-152` |
| ACQDATA drain | 534–576 | reads `0xc0005058` → `a0`/`ef`/`be`; entries logged | `_drain_acq` |
| VIP record | 592–594 | `ACQDATA OK` + scoreboard VIP #1 `golden=a0efbe obs=a0efbe` | test `:26-38` / FIND-001 |
| cocotb summary | 602–604 | `PASS` / `PASS=1 FAIL=0` | — |

</details>

## Not concluded

- Whether this testcase proves the SPEC SMBus Host Notify / DUT-target ACQDATA property (O2) — Skill 3.
- Completeness against a feature_list — no inventory applies in STANDALONE-REQUEST.
- Any closure or PROVEN checker claim — MODE=NO-CHECKBOX forbids inventing checkers.

## Accepted waivers

| Finding | Rule | Where | Why | Approved by |
|---|---|---|---|---|
| — | — | — | none | — |
