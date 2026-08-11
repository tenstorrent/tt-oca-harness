---
schema: dv-quality/v1
artifact: testcase-grade
testcase: smc_efuse_chip_config_read_test
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
- path: hw/sys/smc/dv/build/runs/20260806_094601__verilator__smc_efuse_chip_config_read_test/smc_efuse_chip_config_read_test/logs/smc_efuse_chip_config_read_test.log
  sha256: 3c910f903d7775737754ede57912484ca1a9f901946fad89aa08ebf1198a7867
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
  artifact_ref: hw/sys/smc/dv/cocotb/seq_lib/smc_efuse_chip_config_read_test_seq.py:15-21
  observed: >
    Absolute CHIP_CONFIG hex literals are gone: addresses now call
    `smc_addr(...)`. Residual gap: `VERSION_HI` / `CHIP_ID` / `LC_STATE` still
    use hand-copied field offsets (`CHIP_CONFIG_BASE_ADDR + 0x4 / +0x8 / +0xC`)
    while generated per-register symbols already exist and resolve identically
    (`SMC_TOP_SMC_MISC_WRAP_CHIP_CONFIG_{VERSION_HI,CHIP_ID,LC_STATE}_BASE_ADDR`).
    `VERSION_LO` uses the block base symbol (same value as `VERSION_LO_BASE_ADDR`);
    `RAS_BANK_INFO` already uses its per-register symbol. Offsets currently match
    the map (latent-rot class, not false-identity).
  closure_condition: >
    Import every `CHIP_CONFIG_EFUSE_READS` address from the matching
    `smc_addr("SMC_TOP_SMC_MISC_WRAP_CHIP_CONFIG_<REG>_BASE_ADDR")` symbol
    (no parallel `+0x4`/`+0x8`/`+0xC` offset table) so register identity and
    addressing share one generated source of truth.
  waived_by: null
- id: FIND-002
  tag: '[EXACT-EXPECTATION]'
  severity: Major
  artifact_ref: hw/sys/smc/dv/cocotb/seq_lib/smc_efuse_chip_config_read_test_seq.py:19
  observed: >
    `LC_STATE` is issued with `expected=None`, so `smc_scoreboard._check_sys_axi`
    only asserts AXI OKAY and never compares `rdata`. Kept log L314 shows
    `rdata=0xf0 exp=None ok=True`. Sequence comments cite Verilator/VCS divergence
    (`0xF0` vs `0x0`) as the reason, but OKAY-only / activity alone is not an exact
    LC_STATE contract. The other four CHIP_CONFIG reads do carry exact expecteds
    (VERSION_LO/HI, CHIP_ID, RAS_BANK_INFO) — LC_STATE is the gap on this surface.
  closure_condition: >
    Pin an exact LC_STATE expectation under a simulator-qualified golden (e.g.
    Verilator `0xF0` / VCS `0x0` from the approved efuse model + SPEC decode), or
    drop LC_STATE from this test's value-bearing claim and keep decode-only coverage
    in a separately scoped LC test that owns the simulator split.
  waived_by: null
- id: FIND-003
  tag: '[OBSERVATION-VALIDITY]'
  severity: Major
  artifact_ref: hw/sys/smc/dv/cocotb/seq_lib/smc_efuse_vip_utils.py:10-21
  observed: >
    `check_efuse_otp_observability` claims "eFuse-bank observability" and asserts
    `tb_axil_efuse_bank_active == 0` after "bounded OTP checks". This test's stimulus
    is five SEP_IN SYS AXI reads of CHIP_CONFIG (misc-wrap register surface), which
    never drive `efuse_bank_ctrl_req_o` (the OR behind `tb_axil_efuse_bank_active` in
    `tb_top.sv`). Kept log shows SYS AXI checks #1–#5 then the helper idle log at
    L323 with no preceding efuse-bank AXI-Lite activity. Idle-at-end without a prior
    activity→idle transition cannot prove eFuse-bank observability; the assert holds
    by construction for this stimulus.
  closure_condition: >
    Either exercise and observe real efuse-bank AXI-Lite traffic (activity then
    idle, or an in-window sample that can see a pulse), or remove this helper from
    `smc_efuse_chip_config_read_test` and stop advertising eFuse-bank observability
    on a CHIP_CONFIG-only SYS AXI path.
  waived_by: null
- id: FIND-004
  tag: '[NO-BLIND-DELAY-SYNC]'
  severity: Major
  artifact_ref: hw/sys/smc/dv/cocotb/seq_lib/smc_efuse_vip_utils.py:14
  observed: >
    Helper waits `await ClockCycles(dut.clk_smc_i, 8)` then samples
    `tb_axil_efuse_bank_active`. That fixed delay stands in for a completion /
    settle handshake on the observation path; AXI chip-config completions already
    used the frontdoor handshake, and this delay is not a SPEC-bounded quantity
    under test.
  closure_condition: >
    Replace the bare 8-cycle wait with an event/handshake-bounded wait that fails
    on timeout (`[TIMEOUT-MUST-FAIL]`), or sample without a magic settle delay once
    the observation target is coupled to real bank traffic.
  waived_by: null
waivers: []
recommendation: NOT-READY
---

# Grade Report — smc_efuse_chip_config_read_test (standalone Layer 1)

**VERDICT: 0/0 PROVEN — NOT READY** (mode NO-CHECKBOX, no_contract_reason STANDALONE-REQUEST)

| Mode | Entry gate | Checkers | Findings | Recommendation |
|---|---|---|---|---|
| `NO-CHECKBOX` | — NOT-EVALUATED | 0/0 PROVEN | 🟠 4 Major | ⛔ NOT-READY |

> No approved checkbox card or parent plan record governs this testcase. Layer 1 findings
> are the entire scope of this report. `NOT-READY` records the **absence of a closure
> claim, not a defect**. Kept log is a sim **PASS** (seed 1, verilator 5.050): five
> frontdoor SYS AXI CHIP_CONFIG reads completed (four with exact `rdata` compares,
> LC_STATE OKAY-only) — Layer 2 entry is still not evaluated in this mode.

## DELTA (re-audit vs prior grade `0/0 NOT-READY` on log `9550320c…`)

| Item | Prior (log `9550320c…`, PASS) | This audit (log `3c910f90…`, PASS) |
|---|---|---|
| Verdict | 0/0 PROVEN — NOT READY | 0/0 PROVEN — NOT READY |
| Findings | 🟠 4 Major (FIND-001…004) | 🟠 4 Major (FIND-001…004) — FIND-001 narrowed: absolute hex → residual hand offsets `+0x4/+0x8/+0xC`; FIND-002/003/004 unchanged in substance |
| Layer 1 matrix | F/E/S/O ✅; Phase-S L1 🟠 FIND-001…004; L2 — not evaluated | **same shape** — Phase-S L1 still 🟠 FIND-001…004 |
| Kept log | `9550320ca01752b668062866cb673d191a75ad1cc32b8caea52c68317102c4b1` | `3c910f903d7775737754ede57912484ca1a9f901946fad89aa08ebf1198a7867` |
| Repo rev | `2ecc7b227e3926b253c65b5aac21239eec24ba5f` | `c10b6d63e0b3377f8e2fa38c138e2ea72cae92c7` |
| Waivers carried | none signed (`waivers: []`) | none (nothing to drop; no signed entries) |

## Your to-do — 4 items (🟠 4 Major)

| # | Sev | Item |
|---|---|---|
| 1 | 🟠 Major | FIND-001 `[ADDRESS-FROM-AUTHORITATIVE-MAP]` — residual hand offsets on VERSION_HI/CHIP_ID/LC_STATE |
| 2 | 🟠 Major | FIND-002 `[EXACT-EXPECTATION]` — LC_STATE OKAY-only (`expected=None`) |
| 3 | 🟠 Major | FIND-003 `[OBSERVATION-VALIDITY]` — efuse-bank idle helper uncoupled from stimulus |
| 4 | 🟠 Major | FIND-004 `[NO-BLIND-DELAY-SYNC]` — helper `ClockCycles(..., 8)` before sample |

<details>
<summary>1. 🟠 Major — FIND-001 `[ADDRESS-FROM-AUTHORITATIVE-MAP]` at seq `CHIP_CONFIG_EFUSE_READS`</summary>

Absolute hex is gone; `smc_addr` is used. Residual: `VERSION_HI` / `CHIP_ID` /
`LC_STATE` still address via `CHIP_CONFIG_BASE_ADDR + 0x4/0x8/0xC` while
`…_VERSION_HI_BASE_ADDR` / `…_CHIP_ID_BASE_ADDR` / `…_LC_STATE_BASE_ADDR` exist.
Values currently match → Major (latent rot), not Blocking false-identity.

**Close when:** every `CHIP_CONFIG_EFUSE_READS` address is the matching
per-register `smc_addr(...)` symbol; drop the parallel offset table.

</details>

<details>
<summary>2. 🟠 Major — FIND-002 `[EXACT-EXPECTATION]` at LC_STATE `expected=None`</summary>

`LC_STATE` is issued with `expected=None`, so the scoreboard never compares
`rdata` (log L314: `rdata=0xf0 exp=None`). Simulator divergence is documented
but does not convert OKAY-only into an exact LC_STATE contract. VERSION_LO/HI,
CHIP_ID, and RAS_BANK_INFO already carry exact expecteds on this sequence.

**Close when:** pin a simulator-qualified exact golden for LC_STATE, or move
decode-only LC coverage to a test that owns the Verilator/VCS split.

</details>

<details>
<summary>3. 🟠 Major — FIND-003 `[OBSERVATION-VALIDITY]` at `check_efuse_otp_observability`</summary>

Helper asserts `tb_axil_efuse_bank_active == 0` after CHIP_CONFIG SYS AXI reads that
never touch `efuse_bank_ctrl_req_o`. Idle-by-construction is not eFuse-bank
observability; no activity→idle evidence appears in the kept log (idle at L323).

**Close when:** couple the helper to real bank AXI-Lite traffic (or remove it from
this CHIP_CONFIG-only test and stop claiming bank observability here).

</details>

<details>
<summary>4. 🟠 Major — FIND-004 `[NO-BLIND-DELAY-SYNC]` at helper `ClockCycles(8)`</summary>

Fixed 8-cycle settle before the idle sample substitutes for a handshake/timeout on
the observation path.

**Close when:** event/handshake-bounded wait with timeout-must-fail, or drop the
magic delay once observation is correctly coupled.

</details>

**Then:** owner remediates FIND-001–FIND-004 on the sequence/helper, re-keeps a PASS
log, and re-invokes `/dv_test_audit`. Do not invent a card here (`STANDALONE-REQUEST`).

## All checkers

| Checker | Grade | Proof class | Covers | Findings |
|---|---|---|---|---|
| — | — | — | — | no card checkers (MODE=NO-CHECKBOX) |

### Layer 1 structural rule set

| Rule | Result |
|---|---|
| F1 fabricated verdict / backdoor write | ✅ clean — frontdoor SEP_IN SYS AXI via `SmcSysAxiItem`; scoreboard compares DUT `rdata` to independently supplied `expected` when set; no force/deposit on CSR path |
| F2 can't-fail checker | ✅ clean — scoreboard `got == exp` (VERSION_LO/HI, CHIP_ID, RAS), non-OKAY `resp_ok`, driver timeout, and final `assert self.accesses == len(CHIP_CONFIG_EFUSE_READS)` are reachable FAIL-ON paths |
| E1 skip-to-pass | ✅ clean — no missing-handle skip-to-pass on this path |
| E2 empty phase | ✅ clean — five real SYS AXI reads executed (scoreboard checks #1–#5) |
| S1 silent fail | ✅ clean — mismatch/timeout/`resp_ok` raise; no swallow-to-pass |
| O1 checker disabled | ✅ clean — SYS AXI scoreboard path active |
| Phase-S obligations — L1 | 🟠 Major — FIND-001 `[ADDRESS-FROM-AUTHORITATIVE-MAP]`, FIND-002 `[EXACT-EXPECTATION]`, FIND-003 `[OBSERVATION-VALIDITY]`, FIND-004 `[NO-BLIND-DELAY-SYNC]`; timeouts fail; enrolled in `batch_d.toml` / `all.toml`; no unconditional CHK token; efuse/ROM `$readmemh` is post-PASS bring-up trailer, not CSR golden for VERSION_* |
| Phase-S obligations — L2 (needs the card) | — not evaluated |

## Evidence appendix

<details>
<summary>Kept log + code proof-path notes</summary>

- Log: `hw/sys/smc/dv/build/runs/20260806_094601__verilator__smc_efuse_chip_config_read_test/smc_efuse_chip_config_read_test/logs/smc_efuse_chip_config_read_test.log`
  sha256 `3c910f903d7775737754ede57912484ca1a9f901946fad89aa08ebf1198a7867`
  (verified via `manifest.py hash-file`; matches invoker hint)
- Seed: 1 · simulator: verilator 5.050 · model fingerprint `2c815fa08277`
- `result.json`: `status: PASS`, `exit_code: 0`, cocotb summary L335:
  `TESTS=1 PASS=1 FAIL=0 SKIP=0`
- Final assertion gate: seq `assert self.accesses == len(CHIP_CONFIG_EFUSE_READS)` (5)
  reached after five scoreboard SYS AXI checks; protocol VIP records `csr_accesses=5`
- Test: `hw/sys/smc/dv/cocotb/tests/smc_efuse_chip_config_read_test.py` starts
  `smc_efuse_chip_config_read_test_seq` on `sys_axi_agent.sequencer`, then
  `check_efuse_otp_observability()`, then records protocol VIP CSR accesses
- Seq body: `csr_read_many(CHIP_CONFIG_EFUSE_READS)` — VERSION_LO `0x0001_00A0`,
  VERSION_HI/CHIP_ID/RAS `0`, LC_STATE `None`; addresses via `smc_addr` (+ residual
  offsets for HI/CHIP_ID/LC_STATE)
- Kept-log cites: VERSION_LO L293 `rdata=0x100a0 exp=0x100a0`; LC_STATE L314
  `rdata=0xf0 exp=None`; helper idle L323; VIP L324–L325 `csr_accesses=5`; PASS L329–L335
- Addressing: `smc_efuse_chip_config_read_test_seq.py:15-21`; generated truth in
  `hw/sys/smc/regs/gen/c/smc_addr.h` (per-register symbols match current offsets)
- Driver FAIL-ON: `smc_sys_axi_agent.py` raises on unexpected AXI timeout
  (`[TIMEOUT-MUST-FAIL]` satisfied for this path)
- Scoreboard value check: `smc_scoreboard.py:188-194` asserts `rdata` vs `expected`
  only when `expected is not None` (FIND-002 for LC_STATE)
- Helper: `smc_efuse_vip_utils.py:10-21` — `ClockCycles(8)` then
  `tb_axil_efuse_bank_active == 0` (FIND-003/FIND-004); TB OR at `tb_top.sv:1168-1169`
- Enrollment: `hw/sys/smc/dv/testlists/batch_d.toml`, `all.toml`
- Bring-up trailer (post-PASS flush): efuse hex + ROM `$readmemh` — time-0 image load;
  VERSION_* expecteds are RDL/static constants on this path, not substituted from the
  hex as golden
- No unexplained `ERROR`/`FATAL`/`Traceback` in the kept log
- Provenance: legacy (`test_author.run_id: unknown`); auditor
  `run_id: cursor/grok/4.5-reaudit-20260806`
- Entry gate / Layer 2 not evaluated (MODE=NO-CHECKBOX)

</details>

## Not concluded

- Whether CHIP_CONFIG / eFuse-derived reads prove the SPEC properties claimed for this
  surface (O2) — Skill 3.
- Completeness against a feature_list — no inventory applies in STANDALONE-REQUEST.
- Any closure or PROVEN checker claim — MODE=NO-CHECKBOX forbids inventing checkers.

## Accepted waivers

| Finding | Rule | Where | Why | Approved by |
|---|---|---|---|---|
| — | — | — | none | — |
