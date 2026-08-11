---
schema: dv-quality/v1
artifact: testcase-grade
testcase: smc_cluster_beu_test
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
- path: hw/sys/smc/dv/build/runs/20260806_094643__verilator__smc_cluster_beu_test/smc_cluster_beu_test/logs/smc_cluster_beu_test.log
  sha256: 378b8b0702645bbb1452f19429f4dcb0e2ead411860c64c425cee2d0cf2208af
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
  tag: '[INDEPENDENT-EXPECTED-MODEL]'
  severity: Blocking
  artifact_ref: hw/sys/smc/dv/cocotb/seq_lib/smc_cluster_beu_test_seq.py:24-39
  observed: >
    `BEU_EXPECTED` is explicitly labeled REGRESSION-LOCK of observed Ascalon
    cluster black-box readbacks, not an independently derived SPEC/RDL reset
    vector. Sequence comments state PeakRDL `bus_error_unit` reset is
    CAUSE=0x0 / ENABLE=0xE6 / PLIC_ENABLE=0x0, which matches none of the locked
    values, and that cores 2/3 read all-zero (vs RDL ENABLE 0xE6) — "proof these
    reads come from the cluster model, not a live register block" and "does NOT
    verify a spec-defined reset (golden == observed)". Kept log scoreboard
    checks #1–#12 lock exactly those observed values (cores 0/1:
    CAUSE=0x40000000, ENABLE=0x01000000, PLIC_ENABLE=0x1F000000; cores 2/3: all
    0). Core 2/3 zero expecteds are also indistinguishable from open-bus /
    unmapped zero return.
  closure_condition: >
    Derive every proof-path expected from an independent source (PeakRDL /
    `bus_error_unit.h` field resets, or a pre-approved fixed vector table for
    the real BEU RTL once integrated), and stop locking sim-observed cluster
    black-box values. Until live BEU RTL is present, either fail the sweep when
    readbacks diverge from the RDL reset contract or re-scope the claim to a
    non-reset decode probe that does not assert golden==observed register
    values.
  waived_by: null
- id: FIND-002
  tag: '[ADDRESS-FROM-AUTHORITATIVE-MAP]'
  severity: Major
  artifact_ref: hw/sys/smc/dv/cocotb/seq_lib/smc_cluster_beu_test_seq.py:15-22
  observed: >
    Proof-path BEU bases/offsets are hand-copied numeric literals
    (`BEU_CORE_BASE=0xC801_0000`, `BEU_CORE_STRIDE=0x1000`,
    `BEU_CAUSE_OFFSET=0x00`, `BEU_ENABLE_OFFSET=0x10`,
    `BEU_PLIC_ENABLE_OFFSET=0x18`). Generated PeakRDL symbols already exist in
    `smc_addr.h` / `smc_reg.py` and are loadable via `smc_addr_map.smc_addr`
    (e.g. `SMC_TOP_SMC_CLUSTER_CORE{0..3}_BEU_{CAUSE,ENABLE,PLIC_ENABLE}_BASE_ADDR`).
    Current literals match those macros (latent-rot class, not false-identity).
  closure_condition: >
    Import every proof-path BEU address from `smc_addr_map.smc_addr` (or
    `smc_reg` absolute symbols) and stop using a parallel numeric constant
    table as the addressing source of truth.
  waived_by: null
waivers: []
recommendation: NOT-READY
---

# Grade Report — smc_cluster_beu_test (standalone Layer 1)

**VERDICT: 0/0 PROVEN — NOT READY** (mode NO-CHECKBOX, no_contract_reason STANDALONE-REQUEST)

| Mode | Entry gate | Checkers | Findings | Recommendation |
|---|---|---|---|---|
| `NO-CHECKBOX` | — NOT-EVALUATED | 0/0 PROVEN | 🔴 1 Blocking · 🟠 1 Major | ⛔ NOT-READY |

> No approved checkbox card or parent plan record governs this testcase. Layer 1 findings
> are the entire scope of this report. `NOT-READY` records the **absence of a closure
> claim, not a defect**. Kept log is a sim **PASS** (seed 1, verilator 5.050): twelve
> frontdoor SEP_IN SYS AXI BEU reads completed OKAY with matching `rdata`/`exp`, then
> CPU protocol VIP — Layer 2 entry is still not evaluated in this mode.

## DELTA (re-audit vs prior grade `0/0 NOT-READY` on log `a630ae47…`)

| Item | Prior (log `a630ae47…`, PASS) | This audit (log `378b8b07…`, PASS) |
|---|---|---|
| Verdict | 0/0 PROVEN — NOT READY | 0/0 PROVEN — NOT READY |
| Findings | 🔴 1 Blocking FIND-001 · 🟠 1 Major FIND-002 | same — FIND-001 / FIND-002 reopen on unchanged source |
| FIND-001 | open — REGRESSION-LOCK golden==observed `BEU_EXPECTED` | still open — seq sha256 unchanged (`23e024b0…`) |
| FIND-002 | open — hand-copied BEU bases/offsets | still open — literals still at seq `:15-22` |
| Kept log | `a630ae477d5bc468a2ec167922de524e81aba30ef0e1e33f869581be59077a06` PASS seed=1 | `378b8b0702645bbb1452f19429f4dcb0e2ead411860c64c425cee2d0cf2208af` PASS seed=1; 12/12 SYS AXI + VIP |
| Repo rev | `2ecc7b227e3926b253c65b5aac21239eec24ba5f` | `c10b6d63e0b3377f8e2fa38c138e2ea72cae92c7` |
| Waivers carried | none signed (`waivers: []`; nothing to drop) | none |

## Your to-do — 2 items (🔴 1 Blocking · 🟠 1 Major)

| # | Sev | Item |
|---|---|---|
| 1 | 🔴 Blocking | FIND-001 `[INDEPENDENT-EXPECTED-MODEL]` — REGRESSION-LOCK golden==observed BEU values |
| 2 | 🟠 Major | FIND-002 `[ADDRESS-FROM-AUTHORITATIVE-MAP]` — hand-copied BEU addresses |

<details>
<summary>1. 🔴 Blocking — FIND-001 `[INDEPENDENT-EXPECTED-MODEL]` at seq `BEU_EXPECTED`</summary>

`BEU_EXPECTED` locks observed Ascalon cluster black-box readbacks (cores 0/1 non-zero
magic; cores 2/3 all-zero). Sequence comments admit these match none of the PeakRDL
`bus_error_unit` resets (CAUSE=0 / ENABLE=0xE6 / PLIC=0) and that the compare is
golden==observed, not a SPEC reset check. Scoreboard checks #1–#12 in the kept log
reproduce exactly those locked values.

**Close when:** expecteds come from PeakRDL / `bus_error_unit.h` (or an approved fixed
vector for real BEU RTL); drop golden==observed cluster-model locks. If live BEU is
absent, fail or re-scope rather than locking the stub's present values.

</details>

<details>
<summary>2. 🟠 Major — FIND-002 `[ADDRESS-FROM-AUTHORITATIVE-MAP]` at seq bases/offsets</summary>

Hand-copied `0xC801_0000` / stride `0x1000` / offsets `0x00`/`0x10`/`0x18` on the SYS
AXI proof path. Generated map exists (`smc_addr.h` via `smc_addr_map`). Literals
currently match → Major (latent rot), not Blocking false-identity.

**Close when:** every BEU address is imported from `smc_addr_map` / `smc_reg` symbols.

</details>

**Then:** owner remediates FIND-001 (Blocking) and FIND-002 on the sequence, re-keeps a
PASS log, and re-invokes `/dv_test_audit`. Do not invent a card here (`STANDALONE-REQUEST`).

## All checkers

| Checker | Grade | Proof class | Covers | Findings |
|---|---|---|---|---|
| — | — | — | — | no card checkers (MODE=NO-CHECKBOX) |

### Layer 1 structural rule set

| Rule | Result |
|---|---|
| F1 fabricated verdict / backdoor write | ✅ clean — frontdoor SEP_IN SYS AXI via `SmcSysAxiItem`; scoreboard compares DUT `rdata` to sequence-supplied `expected`; no force/deposit on CSR path |
| F2 can't-fail checker | ✅ clean — scoreboard `got == exp`, non-OKAY `resp_ok`, driver timeout, and final `assert self.accesses == BEU_CORES * 3` are reachable FAIL-ON paths (wrong-source golden is FIND-001, not a can't-fail checker) |
| E1 skip-to-pass | ✅ clean — no missing-handle skip-to-pass on this path |
| E2 empty phase | ✅ clean — twelve real SYS AXI reads executed (scoreboard checks #1–#12) |
| S1 silent fail | ✅ clean — mismatch/timeout/`resp_ok` raise; no swallow-to-pass |
| O1 checker disabled | ✅ clean — SYS AXI scoreboard path active |
| Phase-S obligations — L1 | 🔴 Blocking — FIND-001 `[INDEPENDENT-EXPECTED-MODEL]`; 🟠 Major — FIND-002 `[ADDRESS-FROM-AUTHORITATIVE-MAP]`; timeouts fail; enrolled in `p1_coverage_gap_r4.toml`; no unconditional CHK token |
| Phase-S obligations — L2 (needs the card) | — not evaluated |

## Evidence appendix

<details>
<summary>Kept log + code proof-path notes</summary>

- Log: `hw/sys/smc/dv/build/runs/20260806_094643__verilator__smc_cluster_beu_test/smc_cluster_beu_test/logs/smc_cluster_beu_test.log`
  sha256 `378b8b0702645bbb1452f19429f4dcb0e2ead411860c64c425cee2d0cf2208af`
  (verified via `manifest.py hash-file`; matches invoker hint)
- Seed: 1 · simulator: verilator 5.050 · model fingerprint `2c815fa08277`
- `result.json`: `status: PASS`, `exit_code: 0`, cocotb summary L377–L383:
  `TESTS=1 PASS=1 FAIL=0 SKIP=0`
- Final assertion gate: seq `assert self.accesses == BEU_CORES * 3` (12) after
  twelve scoreboard SYS AXI value checks; protocol VIP records `csr_accesses=12`,
  `timeouts=0`
- Scoreboard value checks (log): cores 0/1 CAUSE/ENABLE/PLIC match
  `0x40000000` / `0x01000000` / `0x1f000000`; cores 2/3 all `0x0`
- AXI monitor trailer: `12 R beats … R-resp tally OKAY=12; 0 errors` (L375)
- Test: `hw/sys/smc/dv/cocotb/tests/smc_cluster_beu_test.py`
  sha256 `e13e9866ab0ed36f1024d763f8d277bc5eed75084c63a0946c722d9d179af478`
- Seq: `hw/sys/smc/dv/cocotb/seq_lib/smc_cluster_beu_test_seq.py`
  sha256 `23e024b037a2797d905ec6e8f88c79f5ef904919029514b0a6a7806503cd9de6`
- Addressing: literals at seq `:15-22`; generated truth in
  `hw/sys/smc/regs/gen/c/smc_addr.h` matches the exercised addresses
- Expecteds: `BEU_EXPECTED` at seq `:24-39` — REGRESSION-LOCK / golden==observed;
  RDL ENABLE reset bits `{1,2,5,6,7}` = `0xE6` (`bus_error_unit.rdl` /
  `bus_error_unit.h`)
- Driver FAIL-ON: `smc_sys_axi_agent.py` raises on unexpected AXI timeout
  (`[TIMEOUT-MUST-FAIL]` satisfied for this path)
- Enrollment: `hw/sys/smc/dv/testlists/p1_coverage_gap_r4.toml`
- Bring-up trailer (post-PASS flush): efuse hex + ROM `$readmemh` — time-0 image
  load; not used as CSR golden substitution on this proof path
- No unexplained `ERROR`/`FATAL`/`Traceback` in the kept log
- Provenance: legacy (`test_author.run_id: unknown`)

</details>

<details>
<summary>Stimulus / sample cites (kept log <code>378b8b07…</code>)</summary>

| Step | Line (approx) | What the log shows | Impl |
|---|---|---|---|
| CORE0 CAUSE | 280–293 | read `0xc8010000` → `0x40000000` exp match | seq `:47-48` |
| CORE0 ENABLE | 295–300 | read `0xc8010010` → `0x1000000` exp match | seq `:49-50` |
| CORE0 PLIC_ENABLE | 302–307 | read `0xc8010018` → `0x1f000000` exp match | seq `:51-54` |
| CORE1 CAUSE/ENABLE/PLIC | 309–328 | same non-zero triple at `0xc8011xxx` | seq `:44-54` |
| CORE2 CAUSE/ENABLE/PLIC | 330–349 | all `0x0` at `0xc8012xxx` | seq `:44-54` |
| CORE3 CAUSE/ENABLE/PLIC | 351–370 | all `0x0` at `0xc8013xxx` | seq `:44-54` |
| protocol VIP | 372 | `csr_accesses=12` cpu mode | test `:22-29` |
| cocotb result | 377–383 | `PASS` / `TESTS=1 PASS=1 FAIL=0 SKIP=0` | seq `:55` |

</details>

## Not concluded

- Whether cluster-BEU decode/reset reads prove the SPEC properties a future card would require (O2) — Skill 3.
- Completeness against a feature_list — no inventory applies in STANDALONE-REQUEST.
- Any closure or PROVEN checker claim — MODE=NO-CHECKBOX forbids inventing checkers.

## Accepted waivers

| Finding | Rule | Where | Why | Approved by |
|---|---|---|---|---|
| — | — | — | none | — |
