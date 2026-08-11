---
schema: dv-quality/v1
artifact: testcase-grade
testcase: smc_remap_cla_test
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
- path: hw/sys/smc/dv/build/runs/20260806_094640__verilator__smc_remap_cla_test/smc_remap_cla_test/logs/smc_remap_cla_test.log
  sha256: 97ffd01e12e847fd051971e360a2d657210cf9a8ddb3460b53d9e7d78de19948
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
  tag: '[EXACT-EXPECTATION]'
  severity: Major
  artifact_ref: hw/sys/smc/dv/cocotb/seq_lib/smc_remap_cla_test_seq.py:119-127
  observed: >-
    All eight MMODE_REMAP_*_ATTRS and twenty-four ALIAS_REMAP_* START/END/ATTRS
    reads call `csr_read` with `expected=None`, so `smc_scoreboard._check_sys_axi`
    only asserts AXI `resp_ok`. Kept log shows every remap check (#1–#32) with
    `rdata=0x0 exp=None ok=True` — OKAY + final `accesses == 35` is activity /
    decode-alive, not an exact data contract. PeakRDL already exports
    `OUTPUT_REMAP_REGION_REGION_ATTRS_REG_DEFAULT` /
    `REMAP_REGION_REGION_{START,END,ATTRS}_REG_DEFAULT` (=0), and sibling
    `smc_xvisor_remap_test_seq` pins ATTRS reset. CLA window probes use
    `csr_read_expect_error`, which only requires `resp_code > 1` ("some error")
    without pinning SLVERR vs DECERR or rdata (log: resp=2, data=0).
  closure_condition: >-
    Pass independently derived exact expecteds on every MMODE/ALIAS remap read
    (PeakRDL reset defaults, as xvisor_remap does for ATTRS). For CLA
    error-slave probes, assert the exact error response and/or data signature
    the OSS terminator produces (e.g. `csr_read_decerr_zero` or pinned
    resp_code + rdata), not merely `resp > 1`. Re-keep a PASS log.
  waived_by: null
waivers: []
recommendation: NOT-READY
---

# Grade Report — smc_remap_cla_test (standalone Layer 1 re-audit)

**VERDICT: 0/0 PROVEN — NOT READY** (mode NO-CHECKBOX, no_contract_reason STANDALONE-REQUEST)

| Mode | Entry gate | Checkers | Findings | Recommendation |
|---|---|---|---|---|
| `NO-CHECKBOX` | — NOT-EVALUATED | 0/0 PROVEN | 🟠 1 Major | ⛔ NOT-READY |

> No approved checkbox card or parent plan record governs this testcase
> (`STANDALONE-REQUEST` / active-regression L1 wave). Layer 1 findings are the entire
> scope of this report. `NOT-READY` records the **absence of a closure claim, not a
> defect** in the test by itself.

## DELTA (re-audit vs prior grade `0/0 NOT-READY` on log `868f6609…`)

| Item | Prior (log `868f6609…`, PASS) | This audit (log `97ffd01e…`, PASS) |
|---|---|---|
| Verdict | 0/0 PROVEN — NOT READY | 0/0 PROVEN — NOT READY |
| Findings | 🟠 1 Major | 🟠 1 Major |
| FIND-001 `[EXACT-EXPECTATION]` | open Major — remap `exp=None`; CLA `resp>1` only | **unchanged open** Major — same seq `:119-127`; new kept log still `#1–#32 exp=None`, CLA `#33–#35` SLVERR resp=2 data=0 unpinned |
| Kept log | `868f66095d6df8b7a867b54987c795de00f8fcbc5f78e489c052765d8ce6f55f` | `97ffd01e12e847fd051971e360a2d657210cf9a8ddb3460b53d9e7d78de19948` |
| Repo rev | `2ecc7b227e3926b253c65b5aac21239eec24ba5f` | `c10b6d63e0b3377f8e2fa38c138e2ea72cae92c7` |
| Auditor run_id | `cursor/grok/4.5` | `cursor/grok/4.5-reaudit-20260806` |
| Waivers carried | none signed (`waivers: []`) | none (nothing to drop; no signed entries) |

## Your to-do — 1 items (🟠 1 Major)

| # | Kind | Id | Severity / grade | Where |
|---|---|---|---|---|
| 1 | finding | FIND-001 | 🟠 Major | `smc_remap_cla_test_seq.py:119-127` |

<details>
<summary>1. FIND-001 — 🟠 Major <code>[EXACT-EXPECTATION]</code> — remap OKAY-only; CLA only "some error"</summary>

- **Where:** `hw/sys/smc/dv/cocotb/seq_lib/smc_remap_cla_test_seq.py:119-127`
- **Observed:** MMODE (8) + ALIAS (24) `csr_read` calls omit `expected=`, so scoreboard only gates `resp_ok`. Log checks #1–#32: `rdata=0x0 exp=None`. CLA uses `csr_read_expect_error` (`resp > 1` only); log #33–#35: SLVERR (`resp=2`) + `0x0` unasserted as exact data. Final `assert accesses == 35` is a count gate, not a value contract. Sibling xvisor_remap already pins ATTRS reset via PeakRDL default.
- **Closure:** Assert PeakRDL reset defaults on every MMODE/ALIAS read; pin exact CLA error resp and/or rdata (e.g. `csr_read_decerr_zero`); re-keep PASS.

</details>

**Then:** owner remediates FIND-001 on `smc_remap_cla_test_seq`, re-keeps a PASS log, and re-invokes `/dv_test_audit smc_remap_cla_test`. Do not invent a card here (`STANDALONE-REQUEST`).

## All checkers

| Checker | Grade | Proof class | Covers | Findings |
|---|---|---|---|---|
| — | — | — | — | no card checkers (MODE=NO-CHECKBOX) |

### Layer 1 structural rule set

| Rule | Result |
|---|---|
| F1 fabricated verdict / backdoor write | ✅ clean — frontdoor SEP_IN SYS AXI via `SmcSysAxiItem`; no force/deposit on CSR path; protocol VIP `passed=True` is completion marker only |
| F2 can't-fail checker | ✅ clean — scoreboard `resp_ok` / `expect_error` and driver timeout `AssertionError` are reachable; `assert accesses == 35` can fail |
| E1 skip-to-pass | ✅ clean — no missing-handle skip-to-pass; every probe issues a real AXI read |
| E2 empty phase | ✅ clean — 8 MMODE + 24 ALIAS + 3 CLA SYS AXI accesses (35 logged) |
| S1 silent fail | ✅ clean — mismatch/timeout/`resp_ok`/`expect_error` raise; sequence access-count assert |
| O1 checker disabled | ✅ clean — SYS AXI scoreboard path active (log checks #1–#35) |
| Phase-S obligations — L1 | 🟠 Major — FIND-001; else addresses from PeakRDL `smc_reg.py` (CLA probes = map base + in-window offsets, not mis-named regs); CLA negative has fabric OKAY positive control in-test; timeouts fail; seed logged; enrolled in `p1_coverage_gap.toml`; no unconditional CHK token; ROM/efuse preload is post-PASS bring-up trailer not CSR golden |
| Phase-S obligations — L2 (needs the card) | — not evaluated |

## Evidence appendix

<details>
<summary>Kept log + code proof-path notes</summary>

- Implementation: `hw/sys/smc/dv/cocotb/tests/smc_remap_cla_test.py`
  sha256 `7242041747b6b531de1ef49ec317f00864d7ab2bc654d2a58b825ad1f4f5a35c`
- Sequence: `hw/sys/smc/dv/cocotb/seq_lib/smc_remap_cla_test_seq.py`
  sha256 `3e70a1f8582f59a24fc8e74535856e9b0e572209df0830cde640a58353bb9b46`
- Scoreboard / driver (proof path): `smc_scoreboard._check_sys_axi`, `smc_sys_axi_agent` drive/timeout
- Log: `hw/sys/smc/dv/build/runs/20260806_094640__verilator__smc_remap_cla_test/smc_remap_cla_test/logs/smc_remap_cla_test.log`
  sha256 `97ffd01e12e847fd051971e360a2d657210cf9a8ddb3460b53d9e7d78de19948`
  (verified via `openssl dgst -sha256`; matches invoker-kept path)
- Seed: 1 · simulator: verilator 5.050 2026-07-01 · model fingerprint `2c815fa08277`
- `result.json`: `status: PASS`, `exit_code: 0`, cocotb summary:
  `TESTS=1 PASS=1 FAIL=0 SKIP=0`
- Final assertion gate: seq `assert self.accesses == _EXPECTED_ACCESSES` (35) reached;
  protocol VIP records `csr_accesses=35 timeouts=0` (completion marker only)
- Stimulus: MMODE_REMAP_0..7 ATTRS → ALIAS_REMAP_0..7 START/END/ATTRS → CLA window
  OFF0/OFF4/OFF8 via `csr_read_expect_error`
- Addressing: PeakRDL symbols from `hw/sys/smc/regs/gen/py/smc_reg.py`
  (MMODE ATTRS `0xC0013000`…`0xC0013038`, ALIAS `0xC0012000`…`0xC00120F0`,
  CLA base `0xC0160000` + 0x0/0x4/0x8 window probes)
- Exact value compares in log: **none** on remap (`exp=None` #1–#32); CLA asserts
  error class only (#33–#35 SLVERR)
- AXI monitor trailer: `35 R beats; R-resp tally OKAY=32, SLVERR=3; 0 errors`
- Enrollment: `hw/sys/smc/dv/testlists/p1_coverage_gap.toml` (+ group list)
- Bring-up trailer: efuse/ROM hex preload after cocotb PASS; not used as CSR golden
- No unexplained `ERROR`/`FATAL`/`Traceback` in the kept log
- Entry gate / Layer 2 not evaluated (MODE=NO-CHECKBOX)
- Provenance: legacy (`test_author.run_id: unknown`); auditor `run_id: cursor/grok/4.5-reaudit-20260806`

</details>

<details>
<summary>Stimulus / sample cites (kept log <code>97ffd01e…</code>)</summary>

| Step | Line (approx) | What the log shows | Impl |
|---|---|---|---|
| MMODE_0 ATTRS | 280–293 | RD `0xc0013000` OKAY `rdata=0x0 exp=None` | seq `:119-120` |
| MMODE_1..7 ATTRS | 295–343 | OKAY `0xc0013008`…`0xc0013038`, `exp=None` | seq `:119-120` |
| ALIAS_0 START/END/ATTRS | 344–363 | OKAY `0xc0012000`/`08`/`10`, `exp=None` | seq `:121-122` |
| ALIAS_1..7 sweep | 365–511 | OKAY through `0xc00120f0`, `exp=None` | seq `:121-122` |
| CLA OFF0/4/8 | 512–532 | SLVERR resp=2, data=0 @ `0xc0160000`+ | seq `:126-127` |
| VIP + monitor | 533–537 | `csr_accesses=35`; OKAY=32 SLVERR=3 | test `:22-28` |
| cocotb result | 538–545 | `PASS` / `TESTS=1 PASS=1 FAIL=0 SKIP=0` | — |

</details>

## Not concluded

- Whether MMODE/ALIAS/CLA decode sweeps prove the SPEC remap/CLA properties a future card would require (O2) — Skill 3.
- Completeness against a feature_list — no inventory applies in STANDALONE-REQUEST.
- Any closure or PROVEN checker claim — MODE=NO-CHECKBOX forbids inventing checkers.

## Accepted waivers

| Finding | Rule | Where | Why | Approved by |
|---|---|---|---|---|
| — | — | — | none | — |
