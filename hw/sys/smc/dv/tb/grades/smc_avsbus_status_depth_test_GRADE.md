---
schema: dv-quality/v1
artifact: testcase-grade
testcase: smc_avsbus_status_depth_test
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
- path: hw/sys/smc/dv/build/runs/20260806_094605__verilator__smc_avsbus_status_depth_test/smc_avsbus_status_depth_test/logs/smc_avsbus_status_depth_test.log
  sha256: 9351d92a62ab13e449244b624862d13b9a6368e28444582e1b44e89186658efc
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
- id: FIND-002
  tag: '[EXACT-EXPECTATION]'
  severity: Major
  artifact_ref: hw/sys/smc/dv/cocotb/seq_lib/smc_avsbus_status_depth_test_seq.py:29-30
  observed: >-
    OKAY-path probes call `csr_read(name, addr)` with `expected=None`, so
    `smc_scoreboard._check_sys_axi` only asserts AXI OKAY and never compares
    `rdata`. The test docstring / protocol VIP details claim "AVSBus status
    decode", and the kept PASS log shows non-trivial payloads
    (DEBUG_READBACK `0xdeadbeef`, NORMAL_STATUS `0x220000`, FIFOS_STATUS
    `0x08000800`) with `exp=None` on scoreboard checks #1–#4. OKAY/activity
    alone is not an exact status-decode contract. (RDL defaults in
    `smc_reg.py`: NORMAL/SLAVE `0x0`, FIFOS `0x08000800` — available as
    independent reset vectors once wired.)
  closure_condition: >-
    Pass independently derived exact expecteds (SPEC/RDL reset table or
    approved fixed vectors — not RTL-copied) into
    `csr_read(..., expected=...)` for every OKAY probe that claims a value;
    keep `expected=None` only where no independent golden exists and document
    that limit. Retain the fail-capable `expect_error` path for AVS_READBACK.
  waived_by: null
waivers: []
recommendation: NOT-READY
---

# Grade Report — smc_avsbus_status_depth_test (standalone Layer 1)

**VERDICT: 0/0 PROVEN — NOT READY** (mode NO-CHECKBOX, no_contract_reason STANDALONE-REQUEST)

| Mode | Entry gate | Checkers | Findings | Recommendation |
|---|---|---|---|---|
| `NO-CHECKBOX` | — NOT-EVALUATED | 0/0 PROVEN | 🟠 1 Major | ⛔ NOT-READY |

> No approved checkbox card or parent plan record governs this testcase
> (`STANDALONE-REQUEST` / active-regression L1 wave). Layer 1 findings are the entire
> scope of this report. `NOT-READY` records the **absence of a closure claim, not a
> defect** in the test by itself. Kept log is a sim **PASS** (seed 1); Layer 2 entry
> is not evaluated in this mode.

## DELTA (re-audit vs prior grade `0/0 NOT-READY` on log `49bc82c0…`)

| Prior id | Tag / grade | Status this round | Notes |
|---|---|---|---|
| FIND-001 | 🔴 `[ADDRESS-FROM-AUTHORITATIVE-MAP]` | CLOSED | Seq now imports `smc_addr(...)` AVSBus symbols; kept log hits `0xc0004008/4020/4024/4028/4004` (PeakRDL window), not eFuse `0xC0008xxx` |
| FIND-002 | 🟠 `[EXACT-EXPECTATION]` | OPEN — unchanged | OKAY `csr_read` still omits `expected=`; scoreboard #1–#4 show `exp=None` on real AVSBus rdata |
| Kept log | `49bc82c0…` FAIL | replaced | `9351d92a…` PASS seed=1; model `2c815fa08277`; AVS_READBACK expect_error gets resp=2 |
| repository_revision | `2ecc7b22…` | updated | `c10b6d63…` |
| waivers: [] | — | unchanged | Prior ledger empty; no signed `approved_by` to carry; none dropped |

## Your to-do — 1 items (🟠 1 Major)

| # | Kind | Id | Severity / grade | Where |
|---|---|---|---|---|
| 1 | finding | FIND-002 | 🟠 Major | `smc_avsbus_status_depth_test_seq.py:29-30` |

<details>
<summary>1. FIND-002 — 🟠 Major <code>[EXACT-EXPECTATION]</code> — OKAY status reads never compare rdata</summary>

- **Where:** `hw/sys/smc/dv/cocotb/seq_lib/smc_avsbus_status_depth_test_seq.py:29-30`
- **Observed:** Four OKAY `csr_read` calls leave `expected=None`. Kept log L293–L314: DEBUG/NORMAL/SLAVE/FIFOS named reads complete OKAY with non-trivial `rdata` but scoreboard never runs `got == exp`. Name/details claim status decode; OKAY-only is not that contract.
- **Closure:** Wire independent exact expecteds into `item.expected` for every value-claiming OKAY probe; re-keep a PASS log where scoreboard value checks fire.

</details>

**Then:** owner remediates FIND-002, re-keeps a PASS log with scoreboard value compares on the AVSBus OKAY window, and re-invokes `/dv_test_audit smc_avsbus_status_depth_test`; do not invent a card here (`STANDALONE-REQUEST`). Closure claims need `/dv_vplan_gen` first.

## All checkers

| Checker | Grade | Proof class | Covers | Findings |
|---|---|---|---|---|
| — | — | — | — | no card checkers (MODE=NO-CHECKBOX) |

### Layer 1 structural rule set

| Rule | Result |
|---|---|
| F1 fabricated verdict / backdoor write | ✅ clean — SEP_IN SYS AXI frontdoor via `SmcSysAxiItem`; no force/deposit on the CSR proof path; ROM/efuse hex preload is bring-up trailer, not golden substitution |
| F2 can't-fail checker | ✅ clean — scoreboard `expect_error` / `resp_ok` and seq `accesses == total` are fail-capable; AVS_READBACK path asserted SLVERR this run |
| E1 skip-to-pass | ✅ clean — no missing-path skip-to-pass; AXI timeout raises; sequence completed all five accesses |
| E2 empty phase | ✅ clean — five SYS AXI reads issued (scoreboard checks #1–#5) plus sideband observability; body is not a no-op stub |
| S1 silent fail | ✅ clean — scoreboard raises on expect_error/OKAY mismatch; no swallow-to-pass |
| O1 checker disabled | ✅ clean — SYS AXI scoreboard path active in log (`Scoreboard SYS AXI check #1`…`#5`); protocol VIP check #1 recorded |
| Phase-S obligations — L1 | 🟠 Major — FIND-002; else addresses from `smc_addr_map`, timeouts fail, seed=1 logged, enrolled in `batch_d.toml`/`all.toml`, negative `expect_error` paired with OKAY probes on the same AVSBus window, sideband helper X-aware `is_resolvable`, no unconditional CHK token |
| Phase-S obligations — L2 (needs the card) | — not evaluated |

## Evidence appendix

<details>
<summary>Kept log + code proof-path notes</summary>

- Implementation: `hw/sys/smc/dv/cocotb/tests/smc_avsbus_status_depth_test.py`
- Sequence: `hw/sys/smc/dv/cocotb/seq_lib/smc_avsbus_status_depth_test_seq.py`
- Sideband helper: `hw/sys/smc/dv/cocotb/seq_lib/smc_sideband_vip_utils.py` `check_sideband_observability`
- CSR helpers: `hw/sys/smc/dv/cocotb/seq_lib/smc_csr_seq_utils.py` `csr_read` / `csr_read_expect_error`
- Scoreboard (proof path): `hw/sys/smc/dv/cocotb/env/smc_scoreboard.py` `_check_sys_axi`
- Authoritative map: `hw/sys/smc/regs/gen/c/smc_addr.h` via `smc_addr_map.py`
- Log: `hw/sys/smc/dv/build/runs/20260806_094605__verilator__smc_avsbus_status_depth_test/smc_avsbus_status_depth_test/logs/smc_avsbus_status_depth_test.log`
  sha256 `9351d92a62ab13e449244b624862d13b9a6368e28444582e1b44e89186658efc` (matches claimed / `manifest.py hash-file`)
- Seed: 1 · simulator: verilator 5.050 2026-07-01 · model fingerprint `2c815fa08277`
- `result.json`: `status: PASS`, `exit_code: 0`, cocotb summary L333–L335:
  `smc_avsbus_status_depth_test … PASS` / `TESTS=1 PASS=1 FAIL=0 SKIP=0`
- Final assertion gate: seq `assert self.accesses == total` (5) reached; sideband observability logged; protocol VIP `csr_accesses=5 timeouts=0`
- Stimulus: 4× OKAY `csr_read` + 1× `csr_read_expect_error` on PeakRDL AVSBus window
- Observed beats: OKAY at `0xc0004008` rdata=`0xdeadbeef`, `0xc0004020` rdata=`0x220000`,
  `0xc0004024` rdata=`0`, `0xc0004028` rdata=`0x8000800` (all `exp=None`); expect_error at
  `0xc0004004` rresp=2 (SLVERR) — scoreboard check #5
- Sideband: L323 `avs_irq=0 telemetry_irq=0 avs_state=0x8` after resolvable asserts
- Enrollment: `hw/sys/smc/dv/testlists/batch_d.toml`, `all.toml`
- Bring-up trailer: efuse/ROM hex preload after PASS flush; not used as AVSBus golden
- Entry gate / Layer 2 not evaluated (MODE=NO-CHECKBOX); sim PASS meets policy §5 shape but
  closure is out of scope without a card
- Provenance: legacy (`test_author.run_id: unknown`); auditor
  `run_id: cursor/grok/4.5-reaudit-20260806`

</details>

<details>
<summary>Stimulus / sample cites (kept log <code>9351d92a…</code>)</summary>

| Step | Line (approx) | What the log shows | Impl |
|---|---|---|---|
| DEBUG OKAY | 280–293 | `0xc0004008` rresp=0 rdata=`0xdeadbeef` `exp=None` | seq `:29-30` / FIND-002 |
| NORMAL OKAY | 295–300 | `0xc0004020` rdata=`0x220000` `exp=None` | seq `:29-30` |
| SLAVE OKAY | 302–307 | `0xc0004024` rdata=`0` `exp=None` | seq `:29-30` |
| FIFOS OKAY | 309–314 | `0xc0004028` rdata=`0x8000800` `exp=None` | seq `:29-30` |
| READBACK expect_error | 316–321 | `0xc0004004` rresp=2 SLVERR | seq `:31-32` / scoreboard |
| sideband + VIP | 323–326 | resolvable pins; protocol VIP check #1 | test `:22-28` |
| cocotb result | 333–335 | `PASS` / `PASS=1 FAIL=0` | — |

</details>

## Not concluded

- Whether AVSBus status-depth behavior matches the SPEC properties a future card would require (O2) — Skill 3.
- Completeness against a feature_list — no inventory applies in STANDALONE-REQUEST.
- Any closure or PROVEN checker claim — MODE=NO-CHECKBOX forbids inventing checkers.

## Accepted waivers

| Finding | Rule | Where | Why | Approved by |
|---|---|---|---|---|
| — | — | — | none | — |
