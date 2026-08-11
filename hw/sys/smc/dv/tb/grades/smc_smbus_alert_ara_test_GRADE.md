---
schema: dv-quality/v1
artifact: testcase-grade
testcase: smc_smbus_alert_ara_test
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
- path: hw/sys/smc/dv/build/runs/20260806_094554__verilator__smc_smbus_alert_ara_test/smc_smbus_alert_ara_test/logs/smc_smbus_alert_ara_test.log
  sha256: 738a7860e127aa1342038bf011fbeadaa58db48ac90fef5e8f227a7066272bda
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
  artifact_ref: hw/sys/smc/dv/cocotb/seq_lib/smc_smbus_alert_ara_test_seq.py:58-63
  observed: >-
    CSR absolute addresses on the proof path are now imported via
    `smc_addr` / `smc_indexed_addr` from PeakRDL `smc_addr.h`, and the kept log
    hits the real I2C wrap (`0xc0005e00` WRAP/CTRL, `0xc000500c` SMBUS_CTRL,
    `0xc0005010` CTRL, `0xc0005054` TARGET_ID, `0xc000505c` TXDATA,
    `0xc0003250+` GPIO pad DATA_CTRL). Field encodes remain hand-copied literals:
    `I2C_WRAP_TARGET_SMBUS=0x101`, `I2C_CTRL_ENABLETARGET=0x2`,
    `I2C_SMBUS_CTRL_SMBALERT=0x10`, plus prove-path
    `_I2C0_CTRL_ENABLE=0x11` / OVRD packs `0x7|0x5|0x3|0x1` and
    `_GPIO_LSIO_SELECT = 1 << 17` in `smc_csr_seq_utils.py`. Generated symbols
    exist (`I2C_CTRL__I2C_CTRL__I2C_EN_bm|SMBUS_EN_bm`,
    `I2C__CTRL__ENABLETARGET_bm`, `I2C__SMBUS_CTRL__SMBALERT_bm`,
    `I2C__OVRD__*`, `GPIO_INTF__DATA_CTRL__LSIO_SELECT_bm` in
    `hw/ip/i2c/regs/gen/c/` / `hw/ip/gpio/regs/gen/c/gpio_intf.h`). Values match
    today (latent rot only — Major, not Blocking wrong-identity).
  closure_condition: >-
    Build WRAP/CTRL/SMBUS/OVRD/LSIO field packs from the generated
    `*_bm` / `*_bp` symbols (or an `smc_addr_map` helper that loads them); drop
    the hand numeric field constants on the proof path; re-keep a PASS log.
  waived_by: null
- id: FIND-002
  tag: '[NO-BLIND-DELAY-SYNC]'
  severity: Major
  artifact_ref: hw/sys/smc/dv/cocotb/seq_lib/smc_csr_seq_utils.py:235-242
  observed: >-
    On the proof path this test invokes, `_i2c0_check_line` waits a fixed
    `ClockCycles(dut.clk_smc_i, 100)` then samples SCL/SDA with no pad/OVRD
    completion event. The alert ARA sequence also has
    `await ClockCycles(cocotb.top.clk_smc_i, 20)` after ENABLETARGET
    (`smc_smbus_alert_ara_test_seq.py:153`) before sampling SMBALERT# idle.
    Those settles stand in for a handshake; `_wait_smbalert` itself is a bounded
    poll with FAIL-ON timeout (fine). This seed PASSed, so the fixed settles
    were exercised on the live path.
  closure_condition: >-
    Replace fixed cycle settles with event/handshake waits that FAIL-ON timeout
    (pad state match or VIP completion with a bounded `[TIMEOUT-MUST-FAIL]`
    loop); keep a bare delay only when the latency itself is the checked quantity.
  waived_by: null
- id: FIND-003
  tag: '[X-AWARE-CHECK]'
  severity: Major
  artifact_ref: hw/sys/smc/dv/cocotb/seq_lib/smc_smbus_alert_ara_test_seq.py:115-124
  observed: >-
    `_wait_smbalert` and the idle sample use `int(dut.tb_i2c0_smbalert.value)`
    with no prior known/X/Z gate; pin-proof / LSIO helpers likewise use
    `int(dut.tb_i2c0_scl.value)` / `sda` / `scl_i` / `enable`
    (`smc_csr_seq_utils.py:238-239`, `:283-286`). On cocotb/Verilator an
    unresolved value can raise or resolve arbitrarily, so a compare that passes
    on X optimism is not a cycle-valid proof. Exercised this seed (pin proof +
    SMBALERT# assert/clear + LSIO ready).
  closure_condition: >-
    Resolve-and-assert-known (or equivalent X/Z reject) before numeric compare on
    `tb_i2c0_smbalert` / SCL / SDA / scl_i samples used as FAIL-ON evidence.
  waived_by: null
waivers: []
recommendation: NOT-READY
---

# Grade Report — smc_smbus_alert_ara_test (standalone Layer 1)

**VERDICT: 0/0 PROVEN — NOT READY** (mode NO-CHECKBOX, no_contract_reason STANDALONE-REQUEST)

| Mode | Entry gate | Checkers | Findings | Recommendation |
|---|---|---|---|---|
| `NO-CHECKBOX` | — NOT-EVALUATED | 0/0 PROVEN | 🟠 3 Major | ⛔ NOT-READY |

> No approved checkbox card or parent plan record governs this testcase
> (`STANDALONE-REQUEST` / active-regression L1 wave). Layer 1 findings are the entire
> scope of this report. `NOT-READY` records the **absence of a closure claim, not a
> defect** in the test by itself. Kept log is a sim **PASS** (seed 1): SMBALERT#
> assert → VIP ARA reply `0x20` → pad clear, plus pin-proof OVRD path — Layer 2
> entry is still not evaluated in this mode.

## DELTA (re-audit vs prior grade `0/0 NOT-READY` on log `5364be8c…`)

| Item | Prior (log `5364be8c…`, FAIL) | This audit (log `738a7860…`, PASS) |
|---|---|---|
| Verdict | 0/0 PROVEN — NOT READY | 0/0 PROVEN — NOT READY |
| Findings | 🔴 1 Blocking · 🟠 2 Major | 🟠 3 Major |
| Prior FIND-001 wrong I2C map | open Blocking — WRAP `0xC0009E00` / I2C `0xC0009xxx` → TELEMETRY/unmapped | **closed** — `smc_addr` / `smc_indexed_addr`; log hits `0xc0005e00` / `0xc00050xx` / GPIO `0xc00032xx` OKAY |
| Field encodes | bundled under prior Blocking address hole | **open** as FIND-001 Major — hand `0x101`/`0x2`/`0x10`/OVRD/LSIO vs generated `*_bm` |
| Prior FIND-002 settle | open Major `[NO-BLIND-DELAY-SYNC]` | **still open** as FIND-002 Major — `ClockCycles(100)` / `(20)` unchanged; now exercised on PASS |
| Prior FIND-003 X-aware | open Major `[X-AWARE-CHECK]` | **still open** as FIND-003 Major — `int(...value)` still ungated |
| Kept log | FAIL SLVERR @ `0xc0009e00` before ARA | PASS seed=1; `SMBALERT# asserted` / `ARA OK: reply=0x20`; final assert + VIP scoreboard reached |
| Waivers carried | none signed (`waivers: []`; nothing to drop) | none |

## Your to-do — 3 items (🟠 3 Major)

| # | Sev | Item |
|---|---|---|
| 1 | 🟠 Major | FIND-001 `[ADDRESS-FROM-AUTHORITATIVE-MAP]` — hand field encodes (WRAP/CTRL/SMBUS/OVRD/LSIO) |
| 2 | 🟠 Major | FIND-002 `[NO-BLIND-DELAY-SYNC]` — fixed `ClockCycles` before pad/idle sample |
| 3 | 🟠 Major | FIND-003 `[X-AWARE-CHECK]` — pad samples without known/X gate |

<details>
<summary>1. 🟠 Major — FIND-001 <code>[ADDRESS-FROM-AUTHORITATIVE-MAP]</code> at field encode literals</summary>

- **Where:** `hw/sys/smc/dv/cocotb/seq_lib/smc_smbus_alert_ara_test_seq.py:58-63`; prove/LSIO helpers `smc_csr_seq_utils.py:229-250`
- **Observed:** Address identity is fixed (real I2C wrap in kept log). Field packs
  (`0x101` WRAP I2C_EN|SMBUS_EN, `0x2` ENABLETARGET, `0x10` SMBALERT, OVRD
  `0x7/0x5/0x3/0x1`, `1<<17` LSIO_SELECT) are still hand literals; they equal
  `i2c_ctrl.h` / `i2c_wrap.h` / `gpio_intf.h` masks today but are not imported.
- **Closure:** Build packs from generated `*_bm`/`*_bp` symbols (or `smc_addr_map`
  loaders); re-keep PASS log.

</details>

<details>
<summary>2. 🟠 Major — FIND-002 <code>[NO-BLIND-DELAY-SYNC]</code> at pin-proof / post-ENABLETARGET settle</summary>

- **Where:** `hw/sys/smc/dv/cocotb/seq_lib/smc_csr_seq_utils.py:235-242` (`ClockCycles(..., 100)`); also `smc_smbus_alert_ara_test_seq.py:153` (`ClockCycles(..., 20)`)
- **Observed:** OVRD pin checks and post-ENABLETARGET idle sample sync with fixed
  delays, not a completion handshake with FAIL-ON timeout. Exercised this PASS seed.
- **Closure:** Event/handshake + bounded timeout that fails; do not treat bare settle
  as proof sync. (`_wait_smbalert` poll already FAIL-ON — keep that pattern.)

</details>

<details>
<summary>3. 🟠 Major — FIND-003 <code>[X-AWARE-CHECK]</code> at SMBALERT# / SCL / SDA samples</summary>

- **Where:** `hw/sys/smc/dv/cocotb/seq_lib/smc_smbus_alert_ara_test_seq.py:115-124` (`_wait_smbalert` / idle `int(tb_i2c0_smbalert.value)`); pin-proof / LSIO line samples likewise
- **Observed:** Numeric compare on potentially X/Z pad values with no resolve-and-assert-known. Exercised this seed.
- **Closure:** Assert known before FAIL-ON numeric compare on SMBALERT# / SCL / SDA / scl_i.

</details>

**Then:** owner imports field symbols (FIND-001), replaces blind settles (FIND-002),
adds X-aware gates (FIND-003), re-keeps a PASS log, and re-invokes
`/dv_test_audit smc_smbus_alert_ara_test`. Do not invent a card here
(`STANDALONE-REQUEST`).

## All checkers

| Checker | Grade | Proof class | Covers | Findings |
|---|---|---|---|---|
| — | — | — | — | no card checkers (MODE=NO-CHECKBOX) |

### Layer 1 structural rule set

| Rule | Result |
|---|---|
| F1 fabricated verdict / backdoor write | ✅ clean — frontdoor SEP_IN SYS AXI via `SmcSysAxiItem`; `observed_bytes` from VIP ARA reply (not copied from expected); pad samples are passive reads; no force/deposit on proof path; ROM/efuse hex is post-PASS bring-up trailer |
| F2 can't-fail checker | ✅ clean — scoreboard `assert item.resp_ok` / VIP byte compare, seq asserts on alert/ARA/clear, and test final `assert seq.alert_asserted and seq.ara_ok and seq.alert_cleared` are reachable FAIL-ON; prior seed failed on SLVERR proving the path |
| E1 skip-to-pass | ✅ clean — missing VIP raises `assert _I2C_VIP_AVAILABLE`; missing `tb_i2c0_smbalert` raises; `_wait_smbalert` timeout returns False then assert fails; LSIO ready reached with `bus_scl=1 scl_i=1` |
| E2 empty phase | ✅ clean — prove pins + CSR program + VIP ARA + pad clear executed (log shows pin-proof samples, SMBALERT# assert, ARA OK, clear) |
| S1 silent fail | ✅ clean — scoreboard/seq/test `assert` raise; no swallow-to-pass |
| O1 checker disabled | ✅ clean — SYS AXI scoreboard checks #1–#34 and protocol VIP check #1 active in log |
| Phase-S obligations — L1 | 🟠 Major — FIND-001 · FIND-002 · FIND-003; else `_wait_smbalert` timeout fails, seed logged, enrolled in `batch_c.toml` / `all.toml`, no unconditional CHK token; ARA expected `0x20` derived from programmed target `0x10<<1` (SPEC ARA address `0x0C`) |
| Phase-S obligations — L2 (needs the card) | — not evaluated |

## Evidence appendix

<details>
<summary>Kept log + code proof-path notes</summary>

- Implementation: `hw/sys/smc/dv/cocotb/tests/smc_smbus_alert_ara_test.py`
- Sequence: `hw/sys/smc/dv/cocotb/seq_lib/smc_smbus_alert_ara_test_seq.py`
- Shared prove helper (on path): `hw/sys/smc/dv/cocotb/seq_lib/smc_csr_seq_utils.py`
  `prove_dut_i2c0_pins` / `_i2c0_check_line` / `wait_i2c0_lsio_ready`
- VIP: `hw/sys/smc/dv/cocotb/seq_lib/smc_i2c_protocol_vip.py` `smbus_query_ara`
- Scoreboard (proof path): `hw/sys/smc/dv/cocotb/env/smc_scoreboard.py` `_check_sys_axi` / `_check_protocol_vip`
- Authoritative map: `hw/sys/smc/regs/gen/c/smc_addr.h` via `smc_addr_map.py`; field headers
  `hw/ip/i2c/regs/gen/c/i2c_wrap.h` / `i2c_ctrl.h`, `hw/ip/gpio/regs/gen/c/gpio_intf.h`
- Log: `hw/sys/smc/dv/build/runs/20260806_094554__verilator__smc_smbus_alert_ara_test/smc_smbus_alert_ara_test/logs/smc_smbus_alert_ara_test.log`
  sha256 `738a7860e127aa1342038bf011fbeadaa58db48ac90fef5e8f227a7066272bda`
  (verified via `sha256sum`; matches invoker hint)
- Seed: 1 · simulator: verilator 5.050 2026-07-01 · model fingerprint `2c815fa08277`
- `result.json`: `status: PASS`, `exit_code: 0`, cocotb summary L549–L551:
  `smc_smbus_alert_ara_test ... PASS` / `TESTS=1 PASS=1 FAIL=0 SKIP=0`
- Addressing identity (this run): CLOCK_GATE `0xc0010018`; WRAP/CTRL `0xc0005e00`
  wdata `0x11` then `0x101`; OVRD `0xc0005034`; SMBUS_CTRL `0xc000500c` wdata `0x10`;
  CTRL `0xc0005010` ENABLETARGET `0x2`; TARGET_ID `0xc0005054`; TXDATA `0xc000505c`
  `0x20`; GPIO pads `0xc0003250`..`0xc0003280` LSIO arm — all OKAY
- Stimulus reached: pin-proof OVRD matrix (L329–L361) → LSIO ready (L446) → SMBALERT#
  asserted (L524) → ARA OK reply `0x20` + clear (L525) → protocol VIP scoreboard
  golden=20 obs=20 (L540–L541) → final test assert
- Enrollment: `hw/sys/smc/dv/testlists/batch_c.toml`, `all.toml`
- Bring-up trailer (post-PASS flush): efuse/ROM hex preload — time-0 image load; not
  used as SMBALERT/ARA golden
- No unexplained `ERROR`/`FATAL`/`Traceback` (DeprecationWarnings only)
- Provenance: legacy (`test_author.run_id: unknown`); auditor
  `run_id: cursor/grok/4.5-reaudit-20260806`
- Entry gate / Layer 2 not evaluated (MODE=NO-CHECKBOX)

</details>

<details>
<summary>Stimulus / sample cites (kept log <code>738a7860…</code>)</summary>

| Step | Line (approx) | What the log shows | Impl |
|---|---|---|---|
| CLOCK_GATE ungate | 292–306 | `0xc0010018` read/write OKAY | prove + seq |
| WRAP enable + RB | 308–320 | `0xc0005e00 <- 0x11` / readback `0x11` | `prove_dut_i2c0_pins` |
| OVRD pin matrix | 322–361 | release/scl/sda/both samples | `_i2c0_check_line` |
| WRAP target+SMBus | 383–388 | `0xc0005e00 <- 0x101` | seq body |
| LSIO arm + ready | 390–446 | GPIO `0xc0003250+` then `bus_scl=1 scl_i=1` | `wait_i2c0_lsio_ready` |
| TARGET/TX/ENABLE | 496–516 | TARGET_ID / TXDATA `0x20` / ENABLETARGET | seq body |
| SMBALERT# assert | 517–524 | SMBUS_CTRL `0x10` then `tb_i2c0_smbalert=0` | seq |
| VIP ARA + clear | 525 | `ARA OK: reply=0x20; SMBALERT# cleared` | `smbus_query_ara` |
| VIP scoreboard | 540–541 | golden=20 obs=20 `passed=True` | `record_protocol_vip` |
| cocotb result | 545–551 | `PASS` / `PASS=1 FAIL=0` | — |

</details>

## Not concluded

- Whether SMBALERT# assert → ARA@0x0C → hwclr matches SPEC SMBus alert properties (O2) —
  Skill 3.
- Completeness against a feature_list — no inventory applies in STANDALONE-REQUEST.
- Any closure or PROVEN checker claim — MODE=NO-CHECKBOX forbids inventing checkers.

## Accepted waivers

| Finding | Rule | Where | Why | Approved by |
|---|---|---|---|---|
| — | — | — | none | — |
