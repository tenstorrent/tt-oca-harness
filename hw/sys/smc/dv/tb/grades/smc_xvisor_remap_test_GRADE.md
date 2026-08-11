---
schema: dv-quality/v1
artifact: testcase-grade
testcase: smc_xvisor_remap_test
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
- path: hw/sys/smc/dv/build/runs/20260806_094643__verilator__smc_xvisor_remap_test/smc_xvisor_remap_test/logs/smc_xvisor_remap_test.log
  sha256: 997580801669a825bfc6b824ac9eb5c10840e3a8ae5d47729c771f1ccf89190a
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
  artifact_ref: hw/sys/smc/dv/cocotb/seq_lib/smc_xvisor_remap_test_seq.py:53-58
  observed: >-
    Sequence claims RDL reset content for ATTRS-only XVISOR_REMAP entries
    (comment: offset[55:0]=0 and remap disabled) and passes
    `OUTPUT_REMAP_REGION_REGION_ATTRS_REG_DEFAULT` (64-bit `0x0` from PeakRDL)
    into `csr_read`, but never sets `length=8`. Default `length=4` drives a
    32-bit AXI beat (`arsize=2` in the kept log) and the scoreboard masks the
    compare to 32 bits (`mask = (1 << length*8) - 1`). Generated map size is
    8 bytes per entry (`SMC_XVISOR_REMAP_0__REG_MAP_SIZE = 0x8`). Kept log
    scoreboard checks #1–#8 all show `len=4` / `exp=0x0` / `data: 00 00 00 00`.
    Sibling `smc_local_fabric_csr_depth_test_seq` and
    `smc_input_output_fabric_wr_rd_test_seq` already use `length=8` for ATTRS.
    Upper half of REGION_ATTRS is never observed, so a stuck/non-reset upper
    word still PASSes.
  closure_condition: >-
    Call `csr_read(..., expected=OUTPUT_REMAP_REGION_REGION_ATTRS_REG_DEFAULT,
    length=8)` for every XVISOR_REMAP_0..7 ATTRS access so the full 64-bit
    PeakRDL DEFAULT is compared, and re-keep a PASS log showing `len=8` on
    scoreboard SYS AXI checks #1–#8.
  waived_by: null
waivers: []
recommendation: NOT-READY
---

# Grade Report — smc_xvisor_remap_test (standalone Layer 1 re-audit)

**VERDICT: 0/0 PROVEN — NOT READY** (mode NO-CHECKBOX, no_contract_reason STANDALONE-REQUEST)

| Mode | Entry gate | Checkers | Findings | Recommendation |
|---|---|---|---|---|
| `NO-CHECKBOX` | — NOT-EVALUATED | 0/0 PROVEN | 🟠 1 Major | ⛔ NOT-READY |

> No approved checkbox card or parent plan record governs this testcase
> (`STANDALONE-REQUEST` / active-regression L1 wave). Layer 1 findings are the entire
> scope of this report. `NOT-READY` records the **absence of a closure claim, not a
> defect** in the test by itself.

## DELTA (re-audit vs prior grade `0/0 NOT-READY` on log `e0de6ea3…`)

| Item | Prior (log `e0de6ea3…`, PASS) | This audit (log `99758080…`, PASS) |
|---|---|---|
| Verdict | 0/0 PROVEN — NOT READY | 0/0 PROVEN — NOT READY |
| Findings | 🟠 1 Major | 🟠 1 Major |
| FIND-001 `[EXACT-EXPECTATION]` | open Major — 32-bit read of 64-bit REGION_ATTRS (`len=4`) | **unchanged open** Major — same seq `:53-58`; new kept log still checks #1–#8 `len=4` / `arsize: 2` / `data: 00 00 00 00` |
| Test / seq sha256 | `ae13be96…` / `7ee04781…` | unchanged |
| Kept log | `e0de6ea37a25415ad744171d7365842d103c21dcc9543f3a1be88d38758f7d95` | `997580801669a825bfc6b824ac9eb5c10840e3a8ae5d47729c771f1ccf89190a` |
| Repo rev | `2ecc7b227e3926b253c65b5aac21239eec24ba5f` | `c10b6d63e0b3377f8e2fa38c138e2ea72cae92c7` |
| Auditor run_id | `cursor/grok/4.5` | `cursor/grok/4.5-reaudit-20260806` |
| Waivers carried | none signed (`waivers: []`) | none (nothing to drop; no signed entries) |

## Your to-do — 1 items (🟠 1 Major)

| # | Kind | Id | Severity / grade | Where |
|---|---|---|---|---|
| 1 | finding | FIND-001 | 🟠 Major | `smc_xvisor_remap_test_seq.py:53-58` |

<details>
<summary>1. FIND-001 — 🟠 Major <code>[EXACT-EXPECTATION]</code> — 32-bit read of 64-bit REGION_ATTRS</summary>

- **Where:** `hw/sys/smc/dv/cocotb/seq_lib/smc_xvisor_remap_test_seq.py:53-58`
- **Observed:** ATTRS map entries are 8 bytes (`REG_MAP_SIZE=0x8`); PeakRDL DEFAULT is
  64-bit `0x0` and the sequence comments claim offset[55:0]/disabled reset content, but
  `csr_read` uses default `length=4`. Kept log checks #1–#8 all `len=4` / `arsize: 2`.
  Scoreboard masks to 32 bits, so the upper ATTRS word is never proven.
- **Closure:** Pass `length=8` on every XVISOR_REMAP ATTRS `csr_read` and re-keep a log
  with scoreboard `len=8` on all eight SYS AXI value checks.

</details>

**Then:** owner remediates FIND-001 on `smc_xvisor_remap_test_seq`, re-keeps a PASS log, and re-invokes `/dv_test_audit smc_xvisor_remap_test`. Do not invent a card here (`STANDALONE-REQUEST`).

## All checkers

| Checker | Grade | Proof class | Covers | Findings |
|---|---|---|---|---|
| — | — | — | — | no card checkers (MODE=NO-CHECKBOX) |

### Layer 1 structural rule set

| Rule | Result |
|---|---|
| F1 fabricated verdict / backdoor write | ✅ clean — frontdoor SEP_IN SYS AXI via `SmcSysAxiItem`; scoreboard compares DUT `rdata` to PeakRDL `OUTPUT_REMAP_REGION_REGION_ATTRS_REG_DEFAULT`; no force/deposit on CSR path |
| F2 can't-fail checker | ✅ clean — scoreboard `got == exp` / `resp_ok`, driver timeout `AssertionError`, and final `assert self.accesses == 8` are reachable FAIL-ON paths (width truncation is FIND-001, not a can't-fail checker) |
| E1 skip-to-pass | ✅ clean — strict `csr_read` (no `allow_timeout` / skip-on-missing-handle) |
| E2 empty phase | ✅ clean — eight real SYS AXI reads to XVISOR_REMAP_0..7 (scoreboard checks #1–#8; monitor OKAY=8) |
| S1 silent fail | ✅ clean — mismatch/timeout/`resp_ok` raise; no swallow-to-pass |
| O1 checker disabled | ✅ clean — SYS AXI scoreboard path active (log checks #1–#8) |
| Phase-S obligations — L1 | 🟠 Major — FIND-001 `[EXACT-EXPECTATION]`; addresses + DEFAULT from generated `smc_reg.py`; timeouts fail; seed logged; enrolled in `p1_coverage_gap_r4.toml`; no unconditional CHK token; ROM/efuse preload is post-PASS bring-up trailer not CSR golden |
| Phase-S obligations — L2 (needs the card) | — not evaluated |

## Evidence appendix

<details>
<summary>Kept log + code proof-path notes</summary>

- Implementation: `hw/sys/smc/dv/cocotb/tests/smc_xvisor_remap_test.py`
  sha256 `ae13be965b7b3b9ddb341658fc5fb4e88234067b2ba7ec9f8d76198e83b6a27e`
- Sequence: `hw/sys/smc/dv/cocotb/seq_lib/smc_xvisor_remap_test_seq.py`
  sha256 `7ee04781dba519dba899532494c3c62987df6f3cda6a5a33cc4f3cd962757fca`
- Scoreboard / driver (proof path): `smc_scoreboard._check_sys_axi`, `smc_sys_axi_agent._drive`
- Log: `hw/sys/smc/dv/build/runs/20260806_094643__verilator__smc_xvisor_remap_test/smc_xvisor_remap_test/logs/smc_xvisor_remap_test.log`
  sha256 `997580801669a825bfc6b824ac9eb5c10840e3a8ae5d47729c771f1ccf89190a`
  (verified via `manifest.py hash-file` / `sha256sum`; matches claimed)
- Seed: 1 · simulator: verilator 5.050 2026-07-01 · model fingerprint `2c815fa08277`
- `result.json`: `status: PASS`, `exit_code: 0`; cocotb summary:
  `TESTS=1 PASS=1 FAIL=0 SKIP=0` (L349–L355)
- Final assertion gate: seq `assert self.accesses == 8` reached; protocol VIP
  records `csr_accesses=8 timeouts=0` (completion marker only)
- Stimulus: for i in 0..7 `csr_read(XVISOR_REMAP_i_ATTRS,
  SMC_XVISOR_REMAP_i__REGION_REGION_ATTRS_REG_ADDR,
  expected=OUTPUT_REMAP_REGION_REGION_ATTRS_REG_DEFAULT)` then `assert accesses == 8`
- Addressing / goldens: imported PeakRDL symbols from `hw/sys/smc/regs/gen/py/smc_reg.py`
  (authoritative map clean); DEFAULT is 64-bit `0x0`; map size 8 bytes/entry
- Width defect: default `length=4` vs map size 8 / sibling ATTRS `length=8` → FIND-001
- AXI monitor trailer: `8 R beats, 0 B resps; R-resp tally OKAY=8; 0 errors` (L347)
- Enrollment: `hw/sys/smc/dv/testlists/p1_coverage_gap_r4.toml`
- Bring-up trailer: efuse/ROM hex preload after cocotb PASS; not used as CSR golden
- No unexplained `ERROR`/`FATAL`/`Traceback` in the kept log
- Entry gate / Layer 2 not evaluated (MODE=NO-CHECKBOX)
- Provenance: legacy (`test_author.run_id: unknown`); auditor `run_id: cursor/grok/4.5-reaudit-20260806`

</details>

<details>
<summary>Stimulus / sample cites (kept log <code>99758080…</code>)</summary>

| Step | Line (approx) | What the log shows | Impl |
|---|---|---|---|
| XVISOR_REMAP_0 ATTRS | 280–293 | `0xc0014000` rdata=`0x0` exp=`0x0` **len=4** arsize=2 | seq `:53-58` |
| XVISOR_REMAP_1 ATTRS | 295–300 | `0xc0014008` → `0x0` len=4 | seq |
| XVISOR_REMAP_2..6 | 302–335 | stride `+8` OKAY reads, all len=4 / exp=0 | seq |
| XVISOR_REMAP_7 ATTRS | 337–342 | `0xc0014038` → `0x0` len=4 | seq |
| protocol VIP | 344–345 | `csr_accesses=8 timeouts=0` (completion marker) | test `:22-29` |
| AXI monitor | 347 | `8 R beats; OKAY=8; 0 errors` | monitor |
| cocotb result | 349–355 | `PASS` / `TESTS=1 PASS=1 FAIL=0 SKIP=0` | seq `:59-61` |

</details>

## Not concluded

- Whether these eight ATTRS reset reads prove the SPEC hypervisor-remap properties a future card would require (O2) — Skill 3.
- Completeness against a feature_list — no inventory applies in STANDALONE-REQUEST.
- Any closure or PROVEN checker claim — MODE=NO-CHECKBOX forbids inventing checkers.

## Accepted waivers

| Finding | Rule | Where | Why | Approved by |
|---|---|---|---|---|
| — | — | — | none | — |
