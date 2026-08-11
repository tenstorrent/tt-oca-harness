---
schema: dv-quality/v1
artifact: testcase-grade
testcase: smc_efuse_otp_clock_config_depth_test
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
- path: hw/sys/smc/dv/build/runs/20260806_094600__verilator__smc_efuse_otp_clock_config_depth_test/smc_efuse_otp_clock_config_depth_test/logs/smc_efuse_otp_clock_config_depth_test.log
  sha256: 38a865af3d2774e5701bdc53830fdcdac0e3df4dde101c56dae90e77a11fec77
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
  artifact_ref: hw/sys/smc/dv/cocotb/seq_lib/smc_efuse_otp_clock_config_depth_test_seq.py:9-18
  observed: >-
    Partial remediation since prior grade: CLOCK_GATE_CONTROL and the
    CHIP_CONFIG / RAS_BANK_INFO bases now come from smc_addr(...). Remaining
    proof-path field bits and register offsets are still hand-maintained:
    CLOCK_GATE_PATTERN=(1<<8)|(1<<11)|(1<<12) and CLOCK_GATE_MASK=0x0000_1FFF
    instead of smc_addr_map ZEROER_CG_EN|I2C_CG_EN|UART_CG_EN (and OR of
    generated _bm masks for the cleared window); VERSION_HI / CHIP_ID /
    LC_STATE addressed as CHIP_CONFIG_BASE+0x4/+0x8/+0xC while
    SMC_TOP_SMC_MISC_WRAP_CHIP_CONFIG_{VERSION_HI,CHIP_ID,LC_STATE}_BASE_ADDR
    already exist in smc_addr.h. Current values match the generated map
    (0x100/0x800/0x1000; 0xC0002904/2908/290C; mask 0x1FFF) → Major latent-rot,
    not Blocking false-identity.
  closure_condition: >-
    Import CLOCK_GATE_PATTERN / MASK field bits from smc_addr_map /
    smc_base_config.h _bm symbols, and every EFUSE_PROXY_READS address from
    the per-register CHIP_CONFIG_*_BASE_ADDR symbols via smc_addr; drop
    parallel bit-shift and +offset arithmetic as the source of truth on this
    proof path.
  waived_by: null
- id: FIND-002
  tag: '[EXACT-EXPECTATION]'
  severity: Major
  artifact_ref: hw/sys/smc/dv/cocotb/seq_lib/smc_efuse_otp_clock_config_depth_test_seq.py:16-18
  observed: >-
    CHIP_CONFIG_CHIP_ID, CHIP_CONFIG_LC_STATE, and CHIP_CONFIG_RAS_BANK_INFO
    are issued with expected=None, so smc_scoreboard._check_sys_axi only
    asserts AXI OKAY and never compares rdata. Kept log L313–L328 shows
    CHIP_ID rdata=0x0 exp=None, LC_STATE rdata=0xf0 exp=None, RAS_BANK_INFO
    rdata=0x0 exp=None (all ok=True). VERSION_LO (0x0001_00A0) and VERSION_HI
    (0) already carry exact expecteds; CLOCK_GATE pattern/restore compares are
    exact — these three proxy reads are the open value gap on this surface.
  closure_condition: >-
    Pin exact CHIP_ID / LC_STATE / RAS_BANK_INFO expectations from the
    approved efuse/chip-config model (or SPEC-qualified golden for this
    bring-up hex), or drop those open fields from this test's value-bearing
    claim and keep decode-only coverage in a separately scoped test that owns
    the open fields.
  waived_by: null
- id: FIND-003
  tag: '[OBSERVATION-VALIDITY]'
  severity: Major
  artifact_ref: hw/sys/smc/dv/cocotb/seq_lib/smc_efuse_vip_utils.py:10-21
  observed: >-
    check_efuse_otp_observability claims "eFuse-bank observability" and asserts
    tb_axil_efuse_bank_active == 0 after "bounded OTP checks". This test's
    stimulus is SEP_IN SYS AXI RW of CLOCK_GATE_CONTROL and CHIP_CONFIG
    (misc-wrap / base-config register surface), which never drive
    efuse_bank_ctrl_req_o (the OR behind tb_axil_efuse_bank_active in
    tb_top.sv:1168). Kept log shows SYS AXI checks #1–#10 then the helper idle
    log at L364 with no preceding efuse-bank AXI-Lite activity. Idle-at-end
    without a prior activity→idle transition cannot prove eFuse-bank
    observability; the assert holds by construction for this stimulus.
  closure_condition: >-
    Either exercise and observe real efuse-bank AXI-Lite traffic (activity then
    idle, or an in-window sample that can see a pulse), or remove this helper
    from smc_efuse_otp_clock_config_depth_test and stop advertising eFuse-bank
    observability on a CHIP_CONFIG / CLOCK_GATE SYS AXI path.
  waived_by: null
- id: FIND-004
  tag: '[NO-BLIND-DELAY-SYNC]'
  severity: Major
  artifact_ref: hw/sys/smc/dv/cocotb/seq_lib/smc_efuse_vip_utils.py:14
  observed: >-
    Helper waits await ClockCycles(dut.clk_smc_i, 8) then samples
    tb_axil_efuse_bank_active. That fixed delay stands in for a completion /
    settle handshake on the observation path; AXI CSR completions already used
    the frontdoor handshake, and this delay is not a SPEC-bounded quantity
    under test.
  closure_condition: >-
    Replace the bare 8-cycle wait with an event/handshake-bounded wait that
    fails on timeout ([TIMEOUT-MUST-FAIL]), or sample without a magic settle
    delay once the observation target is coupled to real bank traffic.
  waived_by: null
waivers: []
recommendation: NOT-READY
---

# Grade Report — smc_efuse_otp_clock_config_depth_test (standalone Layer 1 re-audit)

**VERDICT: 0/0 PROVEN — NOT READY** (mode NO-CHECKBOX, no_contract_reason STANDALONE-REQUEST)

| Mode | Entry gate | Checkers | Findings | Recommendation |
|---|---|---|---|---|
| `NO-CHECKBOX` | — NOT-EVALUATED | 0/0 PROVEN | 🟠 4 Major | ⛔ NOT-READY |

> No approved checkbox card or parent plan record governs this testcase
> (`STANDALONE-REQUEST`). Layer 1 findings are the entire scope of this report.
> `NOT-READY` records the **absence of a closure claim, not a defect** in the
> test by itself. Kept log is a sim **PASS** (seed 1, verilator 5.050); Layer 2
> entry is still not evaluated in this mode.

## DELTA (re-audit vs prior grade `0/0 NOT-READY` on log `d1aeb930…`)

| Item | Prior (log `d1aeb930…`, PASS) | This audit (log `38a865af…`, PASS) |
|---|---|---|
| Verdict | 0/0 PROVEN — NOT READY | 0/0 PROVEN — NOT READY |
| Findings | 🟠 1 Major | 🟠 4 Major |
| FIND-001 `[ADDRESS-FROM-AUTHORITATIVE-MAP]` | open — CLOCK_GATE + all CHIP_CONFIG literals + PATTERN/MASK hand-copied | narrowed, still open — bases via `smc_addr`; PATTERN/MASK bits and VERSION_HI/CHIP_ID/LC_STATE `+offset` remain (match map → Major) |
| FIND-002 `[EXACT-EXPECTATION]` | not filed | **new** — CHIP_ID / LC_STATE / RAS_BANK_INFO `expected=None` (OKAY-only) |
| FIND-003 `[OBSERVATION-VALIDITY]` | not filed | **new** — efuse-bank idle helper uncoupled from CLOCK_GATE/CHIP_CONFIG stimulus |
| FIND-004 `[NO-BLIND-DELAY-SYNC]` | not filed | **new** — helper `ClockCycles(..., 8)` before idle sample |
| Sequence sha256 | `ee2909e8…` | `13dccd7b…` (partial address-map migration) |
| Kept log | `d1aeb930cc8c8f5e45a32c967b553ca4b323b9c227c3e5299fa011da80adf6cf` | `38a865af3d2774e5701bdc53830fdcdac0e3df4dde101c56dae90e77a11fec77` |
| Repo / model | `2ecc7b22…` / `2c815fa08277` | `c10b6d63…` / `2c815fa08277` |
| Waivers carried | none signed (`waivers: []`) | none (nothing to drop; no signed entries) |

## Your to-do — 4 items (🟠 4 Major)

| # | Kind | Id | Severity / grade | Where |
|---|---|---|---|---|
| 1 | finding | FIND-001 | 🟠 Major | `smc_efuse_otp_clock_config_depth_test_seq.py:9-18` |
| 2 | finding | FIND-002 | 🟠 Major | `smc_efuse_otp_clock_config_depth_test_seq.py:16-18` |
| 3 | finding | FIND-003 | 🟠 Major | `smc_efuse_vip_utils.py:10-21` |
| 4 | finding | FIND-004 | 🟠 Major | `smc_efuse_vip_utils.py:14` |

<details>
<summary>1. FIND-001 — 🟠 Major <code>[ADDRESS-FROM-AUTHORITATIVE-MAP]</code> — remaining CLOCK_GATE bits / CHIP_CONFIG offsets</summary>

- **Where:** `hw/sys/smc/dv/cocotb/seq_lib/smc_efuse_otp_clock_config_depth_test_seq.py:9-18`
- **Observed:** CLOCK_GATE / CHIP_CONFIG bases now via `smc_addr`. Remaining: `CLOCK_GATE_PATTERN` / `MASK` hand bit-shifts, and VERSION_HI/CHIP_ID/LC_STATE as `BASE+0x4/+0x8/+0xC` despite per-register `*_BASE_ADDR` macros. Values currently match → Major latent-rot, not Blocking false-identity.
- **Closure:** Source PATTERN/MASK from `smc_addr_map` / `_bm` symbols and every proxy address from per-register `smc_addr(...)`; stop parallel bit/offset tables as source of truth.

</details>

<details>
<summary>2. FIND-002 — 🟠 Major <code>[EXACT-EXPECTATION]</code> — CHIP_ID / LC_STATE / RAS OKAY-only</summary>

- **Where:** `hw/sys/smc/dv/cocotb/seq_lib/smc_efuse_otp_clock_config_depth_test_seq.py:16-18`
- **Observed:** Three proxy reads use `expected=None`; scoreboard never compares `rdata` (log L313–L328: CHIP_ID `0` / LC_STATE `0xf0` / RAS `0`, all `exp=None`). VERSION_LO/HI and CLOCK_GATE pattern/restore already exact.
- **Closure:** Pin exact goldens for those fields, or move open-value coverage out of this value-bearing claim.

</details>

<details>
<summary>3. FIND-003 — 🟠 Major <code>[OBSERVATION-VALIDITY]</code> — efuse-bank idle helper uncoupled from stimulus</summary>

- **Where:** `hw/sys/smc/dv/cocotb/seq_lib/smc_efuse_vip_utils.py:10-21`
- **Observed:** Helper asserts `tb_axil_efuse_bank_active == 0` after CLOCK_GATE / CHIP_CONFIG SYS AXI traffic that never touches `efuse_bank_ctrl_req_o`. Idle-by-construction is not eFuse-bank observability; no activity→idle evidence in the kept log.
- **Closure:** Couple the helper to real bank AXI-Lite traffic (or remove it from this test and stop claiming bank observability here).

</details>

<details>
<summary>4. FIND-004 — 🟠 Major <code>[NO-BLIND-DELAY-SYNC]</code> — helper <code>ClockCycles(..., 8)</code></summary>

- **Where:** `hw/sys/smc/dv/cocotb/seq_lib/smc_efuse_vip_utils.py:14`
- **Observed:** Fixed 8-cycle settle before the idle sample substitutes for a handshake/timeout on the observation path.
- **Closure:** Event/handshake-bounded wait with timeout-must-fail, or drop the magic delay once observation is correctly coupled.

</details>

**Then:** owner remediates FIND-001–FIND-004 on the sequence/helper, re-keeps a PASS log, and re-invokes `/dv_test_audit smc_efuse_otp_clock_config_depth_test`. Do not invent a card here (`STANDALONE-REQUEST`).

## All checkers

| Checker | Grade | Proof class | Covers | Findings |
|---|---|---|---|---|
| — | — | — | — | no card checkers (MODE=NO-CHECKBOX) |

### Layer 1 structural rule set

| Rule | Result |
|---|---|
| F1 fabricated verdict / backdoor write | ✅ clean — frontdoor SEP_IN SYS AXI via `SmcSysAxiItem`; CLOCK_GATE expected is TB-programmed / prior DUT read vs DUT `rdata`; no force/deposit on CSR path |
| F2 can't-fail checker | ✅ clean — scoreboard `got == exp`, masked pattern assert, restore compare, `accesses == 10`, and efuse-bank idle `== 0` are reachable FAIL-ON paths (idle vacuity for *this* stimulus is FIND-003, not F2) |
| E1 skip-to-pass | ✅ clean — no missing-handle skip-to-pass; AXI / resolvable asserts raise |
| E2 empty phase | ✅ clean — real AXI save → 5× CHIP_CONFIG proxy reads → pattern write/readback → restore (10 SYS AXI checks) + idle sample |
| S1 silent fail | ✅ clean — mismatch/`resp_ok`/idle asserts raise; PASS log shows scoreboard value checks |
| O1 checker disabled | ✅ clean — SYS AXI scoreboard + protocol VIP path active |
| Phase-S obligations — L1 | 🟠 Major — FIND-001 `[ADDRESS-FROM-AUTHORITATIVE-MAP]`, FIND-002 `[EXACT-EXPECTATION]`, FIND-003 `[OBSERVATION-VALIDITY]`, FIND-004 `[NO-BLIND-DELAY-SYNC]`; seed logged; enrolled in `batch_d.toml` / `all.toml` / `vplan_triplets.toml`; VERSION_LO/HI + CLOCK_GATE pattern/restore exact; timeouts fail; no unconditional CHK token; ROM/efuse hex preload is bring-up trailer not CLOCK_GATE RW golden |
| Phase-S obligations — L2 (needs the card) | — not evaluated |

## Evidence appendix

<details>
<summary>Kept log + code proof-path notes</summary>

- Implementation: `hw/sys/smc/dv/cocotb/tests/smc_efuse_otp_clock_config_depth_test.py`
  sha256 `081945476c05211a25cc7c69eaf18a2b3082e5b263998787e32ed203b7a49255`
- Sequence: `hw/sys/smc/dv/cocotb/seq_lib/smc_efuse_otp_clock_config_depth_test_seq.py`
  sha256 `13dccd7b5f2b1e2f0874e5febc444f47d693bfccf2f481316903bb6990682248`
- Observability helper: `hw/sys/smc/dv/cocotb/seq_lib/smc_efuse_vip_utils.py`
  sha256 `3b57c161b62496816b2ed76af9ea7eabdf6272f1b8db6bd82a675b31784a946b`
- Log: `hw/sys/smc/dv/build/runs/20260806_094600__verilator__smc_efuse_otp_clock_config_depth_test/smc_efuse_otp_clock_config_depth_test/logs/smc_efuse_otp_clock_config_depth_test.log`
  sha256 `38a865af3d2774e5701bdc53830fdcdac0e3df4dde101c56dae90e77a11fec77`
  (verified via `manifest.py hash-file`; matches invoker hint)
- Seed: 1 · simulator: verilator 5.050 2026-07-01 · model fingerprint `2c815fa08277`
- `result.json`: `status: PASS`, `exit_code: 0`, cocotb summary L370–L376:
  `TESTS=1 PASS=1 FAIL=0 SKIP=0`
- Stimulus: CLOCK_GATE_CONTROL save → CHIP_CONFIG VERSION_LO/HI (+ CHIP_ID/LC_STATE/RAS open reads) → pattern write/readback → restore; then `check_efuse_otp_observability` (idle `tb_axil_efuse_bank_active==0`)
- Scoreboard (L293–L362): SYS AXI checks #1–#10; value compares on VERSION_LO `0x100a0`, VERSION_HI `0x0`, restore `0x1f000000`; pattern readback asserted in-seq against mask `0x1FFF`; CHIP_ID/LC/RAS OKAY-only
- Protocol VIP: `csr_accesses=10` / `timeouts=0` / `passed=True` (completion marker only; real FAIL-ON is seq + SYS AXI scoreboard)
- Enrollment: `hw/sys/smc/dv/testlists/batch_d.toml`, `all.toml`, `vplan_triplets.toml`
- Bring-up trailer: efuse/ROM hex preload present; CLOCK_GATE RW is frontdoor CSR
- Entry gate / Layer 2 not evaluated (MODE=NO-CHECKBOX)
- Provenance: legacy (`test_author.run_id: unknown`)
- Auditor: `cursor/grok/4.5-reaudit-20260806` (re-audit; prior auditor `cursor/grok/4.5`)

</details>

<details>
<summary>Stimulus / sample cites (kept log <code>38a865af…</code>)</summary>

| Step | Line (approx) | What the log shows | Impl |
|---|---|---|---|
| CLOCK_GATE save | 280–293 | SEP_IN read `0xc0010018` → `0x1f000000` | seq `:29` |
| CHIP_CONFIG proxy | 295–328 | VERSION_LO `0x100a0`/exp match; VERSION_HI `0`; CHIP_ID/LC/RAS OKAY `exp=None` | seq `:30` |
| pattern write/RB | 330–348 | write `0x1f001900`, readback same | seq `:32–37` |
| restore | 350–362 | write/read `0x1f000000` exp match | seq `:38–39` |
| access count gate | (seq) | `accesses == 10` | seq `:41–42` |
| efuse idle | 364 | `tb_axil_efuse_bank_active==0` | vip_utils `:15–20` |
| protocol VIP | 365–366 | `csr_accesses=10` | test `:25–31` |
| cocotb result | 370–376 | `PASS` / `TESTS=1 PASS=1 FAIL=0 SKIP=0` | — |

</details>

## Not concluded

- Whether CLOCK_GATE RW depth plus CHIP_CONFIG proxy reads prove the SPEC properties a future card would require (O2) — Skill 3.
- Completeness against a feature_list — no inventory applies in STANDALONE-REQUEST.
- Any closure or PROVEN checker claim — MODE=NO-CHECKBOX forbids inventing checkers.

## Accepted waivers

| Finding | Rule | Where | Why | Approved by |
|---|---|---|---|---|
| — | — | — | none | — |
