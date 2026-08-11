---
schema: dv-quality/v1
artifact: testcase-grade
testcase: smc_efuse_otp_clock_test
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
- path: hw/sys/smc/dv/build/runs/20260806_094559__verilator__smc_efuse_otp_clock_test/smc_efuse_otp_clock_test/logs/smc_efuse_otp_clock_test.log
  sha256: 8c647f35e5f4cdd217c7c6a714db6385e795457f02f3f944f84840590671c6d3
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
  artifact_ref: hw/sys/smc/dv/cocotb/seq_lib/smc_efuse_otp_clock_test_seq.py:10-13
  observed: >-
    Absolute CLOCK_GATE / CHIP_CONFIG hex literals are gone: CLOCK_GATE_CONTROL
    and CHIP_CONFIG block base now call smc_addr(...). Residual gap:
    CHIP_CONFIG_VERSION_HI and CHIP_CONFIG_CHIP_ID still use hand-copied field
    offsets (CHIP_CONFIG_BASE_ADDR + 0x4 / +0x8) while generated per-register
    symbols already exist and resolve identically
    (SMC_TOP_SMC_MISC_WRAP_CHIP_CONFIG_{VERSION_HI,CHIP_ID}_BASE_ADDR).
    VERSION_LO uses the block base symbol (same value as VERSION_LO_BASE_ADDR).
    Offsets currently match the map (latent-rot class, not false-identity).
    Kept log L280–L320 probes 0xc0010018 / 0xc0002900 / 2904 / 2908.
  closure_condition: >-
    Import every CHIP_CONFIG_READS address from the matching
    smc_addr("SMC_TOP_SMC_MISC_WRAP_CHIP_CONFIG_<REG>_BASE_ADDR") symbol (no
    parallel +0x4/+0x8 offset table) so register identity and addressing share
    one generated source of truth.
  waived_by: null
- id: FIND-002
  tag: '[EXACT-EXPECTATION]'
  severity: Major
  artifact_ref: hw/sys/smc/dv/cocotb/seq_lib/smc_efuse_otp_clock_test_seq.py:13
  observed: >-
    CHIP_CONFIG_CHIP_ID is issued with expected=None, so
    smc_scoreboard._check_sys_axi only asserts AXI OKAY and never compares
    rdata. Kept log L313–L314 shows rdata=0x0 exp=None ok=True. VERSION_LO
    (0x0001_00A0) and VERSION_HI (0) carry exact expecteds; CHIP_ID is the
    open value gap on this proxy surface. CLOCK_GATE_CONTROL_RECHECK correctly
    pins expected to the prior DUT read (stability), so that compare is not
    this finding.
  closure_condition: >-
    Pin an exact CHIP_ID expectation from the approved efuse/chip-config
    model (or SPEC-qualified golden for this bring-up hex), or drop CHIP_ID
    from this test's value-bearing claim and keep decode-only coverage in a
    separately scoped test that owns the open field.
  waived_by: null
- id: FIND-003
  tag: '[OBSERVATION-VALIDITY]'
  severity: Major
  artifact_ref: hw/sys/smc/dv/cocotb/seq_lib/smc_efuse_vip_utils.py:10-21
  observed: >-
    check_efuse_otp_observability claims "eFuse-bank observability" and asserts
    tb_axil_efuse_bank_active == 0 after "bounded OTP checks". This test's
    stimulus is SEP_IN SYS AXI reads of CLOCK_GATE_CONTROL and CHIP_CONFIG
    (misc-wrap / base-config register surface), which never drive
    efuse_bank_ctrl_req_o (the OR behind tb_axil_efuse_bank_active in
    tb_top.sv). Kept log shows SYS AXI checks #1–#5 then the helper idle log
    at L323 with no preceding efuse-bank AXI-Lite activity. Idle-at-end without
    a prior activity→idle transition cannot prove eFuse-bank observability;
    the assert holds by construction for this stimulus.
  closure_condition: >-
    Either exercise and observe real efuse-bank AXI-Lite traffic (activity then
    idle, or an in-window sample that can see a pulse), or remove this helper
    from smc_efuse_otp_clock_test and stop advertising eFuse-bank observability
    on a CHIP_CONFIG / CLOCK_GATE SYS AXI path.
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

# Grade Report — smc_efuse_otp_clock_test (standalone Layer 1)

**VERDICT: 0/0 PROVEN — NOT READY** (mode NO-CHECKBOX, no_contract_reason STANDALONE-REQUEST)

| Mode | Entry gate | Checkers | Findings | Recommendation |
|---|---|---|---|---|
| `NO-CHECKBOX` | — NOT-EVALUATED | 0/0 PROVEN | 🟠 4 Major | ⛔ NOT-READY |

> No approved checkbox card or parent plan record governs this testcase
> (`STANDALONE-REQUEST` / active-regression L1 wave). Layer 1 findings are the entire
> scope of this report. `NOT-READY` records the **absence of a closure claim, not a
> defect** in the test by itself.

## DELTA (re-audit vs prior grade `0/0 NOT-READY` on log `d569440a…`)

| Prior id | Tag / grade | Status this round | Notes |
|---|---|---|---|
| FIND-001 | 🟠 `[ADDRESS-FROM-AUTHORITATIVE-MAP]` (absolute hex) | CLOSED (absolute hex) | Seq now sources CLOCK_GATE + CHIP_CONFIG block base via `smc_addr`; log probes `0xc0010018` / `0xc0002900+` |
| — | 🟠 `[ADDRESS-FROM-AUTHORITATIVE-MAP]` residual offsets | NEW as FIND-001 🟠 | `VERSION_HI` / `CHIP_ID` still `BASE + 0x4/0x8` while per-register symbols exist (latent rot) |
| FIND-002 | 🟠 `[EXACT-EXPECTATION]` | OPEN — unchanged | CHIP_ID still `expected=None` (log L314 `exp=None`) |
| FIND-003 | 🟠 `[OBSERVATION-VALIDITY]` | OPEN — unchanged | Bank-idle helper still uncoupled from CLOCK_GATE / CHIP_CONFIG SYS AXI stimulus |
| FIND-004 | 🟠 `[NO-BLIND-DELAY-SYNC]` | OPEN — unchanged | Helper still `ClockCycles(..., 8)` before idle sample |
| waivers: [] | — | unchanged | Prior ledger empty; no signed `approved_by` to carry; none dropped |
| Kept log | `d569440a…` (084635) | replaced | `8c647f35…` (094559; seed=1 PASS; model `2c815fa08277`) |
| repository_revision | `2ecc7b22…` | updated | `c10b6d63…` |
| seq sha256 | `64fa95d8…` | updated | `25df9cef…` (`smc_addr` import; residual hand offsets remain) |

## Your to-do — 4 items (🟠 4 Major)

| # | Kind | Id | Severity / grade | Where |
|---|---|---|---|---|
| 1 | finding | FIND-001 | 🟠 Major | `smc_efuse_otp_clock_test_seq.py:10-13` |
| 2 | finding | FIND-002 | 🟠 Major | `smc_efuse_otp_clock_test_seq.py:13` |
| 3 | finding | FIND-003 | 🟠 Major | `smc_efuse_vip_utils.py:10-21` |
| 4 | finding | FIND-004 | 🟠 Major | `smc_efuse_vip_utils.py:14` |

<details>
<summary>1. FIND-001 — 🟠 Major <code>[ADDRESS-FROM-AUTHORITATIVE-MAP]</code> — residual CHIP_CONFIG hand offsets</summary>

- **Where:** `hw/sys/smc/dv/cocotb/seq_lib/smc_efuse_otp_clock_test_seq.py:10-13`
- **Observed:** Absolute hex is gone; `smc_addr` is used for CLOCK_GATE and CHIP_CONFIG block base. Residual: `VERSION_HI` / `CHIP_ID` still address via `BASE + 0x4/0x8` while `…_VERSION_HI_BASE_ADDR` / `…_CHIP_ID_BASE_ADDR` exist. Values currently match → Major (latent rot), not Blocking false-identity.
- **Closure:** Source every `CHIP_CONFIG_READS` address from the matching per-register `smc_addr(...)` symbol; drop the parallel offset table.

</details>

<details>
<summary>2. FIND-002 — 🟠 Major <code>[EXACT-EXPECTATION]</code> — CHIP_ID OKAY-only (<code>expected=None</code>)</summary>

- **Where:** `hw/sys/smc/dv/cocotb/seq_lib/smc_efuse_otp_clock_test_seq.py:13`
- **Observed:** `CHIP_CONFIG_CHIP_ID` is issued with `expected=None`, so the scoreboard never compares `rdata` (log L313–L314: `rdata=0x0 exp=None`). VERSION_LO/HI already carry exact expecteds; CLOCK_GATE recheck pins the prior DUT read.
- **Closure:** Pin an exact CHIP_ID golden for this bring-up, or move open CHIP_ID coverage out of this value-bearing claim.

</details>

<details>
<summary>3. FIND-003 — 🟠 Major <code>[OBSERVATION-VALIDITY]</code> — efuse-bank idle helper uncoupled from stimulus</summary>

- **Where:** `hw/sys/smc/dv/cocotb/seq_lib/smc_efuse_vip_utils.py:10-21`
- **Observed:** Helper asserts `tb_axil_efuse_bank_active == 0` after CLOCK_GATE / CHIP_CONFIG SYS AXI reads that never touch `efuse_bank_ctrl_req_o`. Idle-by-construction is not eFuse-bank observability; no activity→idle evidence appears in the kept log (L323 idle only).
- **Closure:** Couple the helper to real bank AXI-Lite traffic (or remove it from this test and stop claiming bank observability here).

</details>

<details>
<summary>4. FIND-004 — 🟠 Major <code>[NO-BLIND-DELAY-SYNC]</code> — helper <code>ClockCycles(..., 8)</code></summary>

- **Where:** `hw/sys/smc/dv/cocotb/seq_lib/smc_efuse_vip_utils.py:14`
- **Observed:** Fixed 8-cycle settle before the idle sample substitutes for a handshake/timeout on the observation path.
- **Closure:** Event/handshake-bounded wait with timeout-must-fail, or drop the magic delay once observation is correctly coupled.

</details>

**Then:** owner remediates FIND-001–FIND-004 on the sequence/helper, re-keeps a PASS log, and re-invokes `/dv_test_audit smc_efuse_otp_clock_test`. Do not invent a card here (`STANDALONE-REQUEST`).

## All checkers

| Checker | Grade | Proof class | Covers | Findings |
|---|---|---|---|---|
| — | — | — | — | no card checkers (MODE=NO-CHECKBOX) |

### Layer 1 structural rule set

| Rule | Result |
|---|---|
| F1 fabricated verdict / backdoor write | ✅ clean — frontdoor SEP_IN SYS AXI via `SmcSysAxiItem`; CLOCK_GATE recheck expected is prior DUT read (stability), not TB-programmed golden; no force/deposit on CSR path |
| F2 can't-fail checker | ✅ clean — scoreboard `got == exp` (VERSION_LO/HI, CLOCK_GATE recheck), non-OKAY `resp_ok`, `accesses == 5`, and efuse-bank idle `== 0` are reachable FAIL-ON paths |
| E1 skip-to-pass | ✅ clean — no missing-handle skip-to-pass; AXI / resolvable asserts raise |
| E2 empty phase | ✅ clean — real AXI CLOCK_GATE save → 3× CHIP_CONFIG proxy reads → CLOCK_GATE recheck (5 SYS AXI checks) + idle sample |
| S1 silent fail | ✅ clean — mismatch/`resp_ok`/idle asserts raise; PASS log shows scoreboard value checks |
| O1 checker disabled | ✅ clean — SYS AXI scoreboard + protocol VIP path active |
| Phase-S obligations — L1 | 🟠 Major — FIND-001 `[ADDRESS-FROM-AUTHORITATIVE-MAP]`, FIND-002 `[EXACT-EXPECTATION]`, FIND-003 `[OBSERVATION-VALIDITY]`, FIND-004 `[NO-BLIND-DELAY-SYNC]`; seed logged; enrolled in `batch_d.toml` / `all.toml` / `vplan_triplets.toml`; VERSION_LO/HI + CLOCK_GATE recheck exact; timeouts fail; no unconditional CHK token; ROM/efuse hex preload is bring-up trailer not CSR golden path |
| Phase-S obligations — L2 (needs the card) | — not evaluated |

## Evidence appendix

<details>
<summary>Kept log + code proof-path notes</summary>

- Implementation: `hw/sys/smc/dv/cocotb/tests/smc_efuse_otp_clock_test.py`
  sha256 `90c045a6fb38965f89588ab372fc78455d689137e4449c4661140c19f869f190`
- Sequence: `hw/sys/smc/dv/cocotb/seq_lib/smc_efuse_otp_clock_test_seq.py`
  sha256 `25df9ceffdd63c4519feeab048fe65dc200467716ee37d651d05656650f0adf7`
- Observability helper: `hw/sys/smc/dv/cocotb/seq_lib/smc_efuse_vip_utils.py`
  sha256 `3b57c161b62496816b2ed76af9ea7eabdf6272f1b8db6bd82a675b31784a946b`
- Log: `hw/sys/smc/dv/build/runs/20260806_094559__verilator__smc_efuse_otp_clock_test/smc_efuse_otp_clock_test/logs/smc_efuse_otp_clock_test.log`
  sha256 `8c647f35e5f4cdd217c7c6a714db6385e795457f02f3f944f84840590671c6d3` (matches claimed)
- Seed: 1 · simulator: verilator 5.050 2026-07-01 · model fingerprint `2c815fa08277`
- `result.json`: `status: PASS`, `exit_code: 0`, cocotb summary L329–L335:
  `TESTS=1 PASS=1 FAIL=0 SKIP=0`
- Stimulus: CLOCK_GATE_CONTROL save → CHIP_CONFIG VERSION_LO/HI/CHIP_ID → CLOCK_GATE recheck; then `check_efuse_otp_observability` (idle `tb_axil_efuse_bank_active==0`)
- Scoreboard (L292–L321): SYS AXI checks #1–#5; value compares on VERSION_LO `0x100a0`, VERSION_HI `0x0`, CLOCK_GATE recheck `0x1f000000`; CHIP_ID OKAY-only (`exp=None`)
- Protocol VIP: `csr_accesses=5` / `timeouts=0` / `passed=True` (completion marker; real FAIL-ON is seq + SYS AXI scoreboard)
- Enrollment: `hw/sys/smc/dv/testlists/batch_d.toml`, `all.toml`, `vplan_triplets.toml`
- Bring-up trailer: efuse/ROM hex preload present; CSR path is frontdoor SYS AXI
- Entry gate / Layer 2 not evaluated (MODE=NO-CHECKBOX)
- Provenance: legacy (`test_author.run_id: unknown`)

</details>

<details>
<summary>Stimulus / sample cites (kept log <code>8c647f35…</code>)</summary>

| Step | Line (approx) | What the log shows | Impl |
|---|---|---|---|
| CLOCK_GATE save | 280–293 | SEP_IN read `0xc0010018` → `0x1f000000` | seq `:24` |
| CHIP_CONFIG proxy | 295–314 | VERSION_LO `0x100a0`/exp match; VERSION_HI `0`; CHIP_ID `0`/`exp=None` | seq `:25` |
| CLOCK_GATE recheck | 316–321 | read `0x1f000000` exp match | seq `:26–27` |
| access count gate | (seq) | `accesses == 5` | seq `:28` |
| efuse idle | 323 | `tb_axil_efuse_bank_active==0` | vip_utils `:15–20` |
| protocol VIP | 324–325 | `csr_accesses=5` | test `:23–29` |
| cocotb result | 329–335 | `PASS` / `TESTS=1 PASS=1 FAIL=0 SKIP=0` | — |

</details>

## Not concluded

- Whether CLOCK_GATE stability plus CHIP_CONFIG proxy reads prove the SPEC properties a future card would require (O2) — Skill 3.
- Completeness against a feature_list — no inventory applies in STANDALONE-REQUEST.
- Any closure or PROVEN checker claim — MODE=NO-CHECKBOX forbids inventing checkers.

## Accepted waivers

| Finding | Rule | Where | Why | Approved by |
|---|---|---|---|---|
| — | — | — | none | — |
