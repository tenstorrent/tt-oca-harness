---
schema: dv-quality/v1
artifact: testcase-grade
testcase: smc_sideband_protocol_smoke_test
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
- path: hw/sys/smc/dv/build/runs/20260806_094601__verilator__smc_sideband_protocol_smoke_test/smc_sideband_protocol_smoke_test/logs/smc_sideband_protocol_smoke_test.log
  sha256: fd6d10b383498c656928bd35dad2abf24c87d0cf910496d48707ff398399eac8
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
  artifact_ref: hw/sys/smc/dv/cocotb/seq_lib/smc_sideband_protocol_smoke_test_seq.py:29-30
  observed: >
    All four `SIDEBAND_OKAY_READS` still call `csr_read(name, addr)` with
    `expected=None`, so `smc_scoreboard._check_sys_axi` only asserts AXI
    OKAY and never compares `rdata`. Kept log L280–L314 shows non-trivial
    payloads at the corrected AVSBus window (`0xc0004008` → `0xdeadbeef`,
    `0xc0004020` → `0x220000`, `0xc0004028` → `0x8000800`) that are never
    checked against an independently derived golden. OKAY-only / activity
    alone is not an exact status-register contract.
  closure_condition: >
    Pass independently derived expected values (SPEC/RDL reset or status
    field model) into `csr_read(..., expected=...)` for each OKAY
    status/debug read whose golden is knowable; keep `expected=None` only
    where no independent golden exists and document that limit. Ensure the
    scoreboard `got == exp` path can fail on wrong data.
  waived_by: null
waivers: []
recommendation: NOT-READY
---

# Grade Report — smc_sideband_protocol_smoke_test (standalone Layer 1)

**VERDICT: 0/0 PROVEN — NOT READY** (mode NO-CHECKBOX, no_contract_reason STANDALONE-REQUEST)

| Mode | Entry gate | Checkers | Findings | Recommendation |
|---|---|---|---|---|
| `NO-CHECKBOX` | — NOT-EVALUATED | 0/0 PROVEN | 🟠 1 Major | ⛔ NOT-READY |

> No approved checkbox card or parent plan record governs this testcase
> (`STANDALONE-REQUEST` / active-regression L1 wave). Layer 1 findings are the entire
> scope of this report. `NOT-READY` records the **absence of a closure claim, not a
> defect**. Kept log is a sim **PASS** (seed 1, verilator 5.050): five frontdoor
> AVSBus CSR probes completed (4× OKAY + 1× SLVERR on `AVS_READBACK`) — Layer 2
> entry is still not evaluated in this mode.

## DELTA (re-audit vs prior grade `0/0 NOT-READY` on log `0a8a55ea…`)

| Item | Prior (log `0a8a55ea…`, FAIL) | This audit (log `fd6d10b3…`, PASS) |
|---|---|---|
| Verdict | 0/0 PROVEN — NOT READY | 0/0 PROVEN — NOT READY |
| Findings | 🔴 1 Blocking · 🟠 1 Major | 🟠 1 Major |
| Prior FIND-001 AVS→eFuse literals | open Blocking `[ADDRESS-FROM-AUTHORITATIVE-MAP]` | **closed** — tables import `smc_addr(...)`; kept log hits `0xC0004xxx` AVSBus window |
| Prior FIND-002 OKAY `expected=None` | open Major `[EXACT-EXPECTATION]` | **still open** as FIND-001 Major — four OKAY reads still omit `expected` |
| Kept log | `0a8a55ea414266c261a666a199de81888c0cfa63927f897278eff756e83aaf67` (FAIL) | `fd6d10b383498c656928bd35dad2abf24c87d0cf910496d48707ff398399eac8` (PASS) |
| Repo rev | `2ecc7b227e3926b253c65b5aac21239eec24ba5f` | `c10b6d63e0b3377f8e2fa38c138e2ea72cae92c7` |
| Waivers carried | none signed (`waivers: []`) | none (nothing to drop; no signed entries) |

## Your to-do — 1 item (🟠 1 Major)

| # | Sev | Item |
|---|---|---|
| 1 | 🟠 Major | FIND-001 `[EXACT-EXPECTATION]` — OKAY sideband reads have no `expected` |

<details>
<summary>1. 🟠 Major — FIND-001 <code>[EXACT-EXPECTATION]</code> — OKAY reads are activity-only</summary>

- **Where:** `hw/sys/smc/dv/cocotb/seq_lib/smc_sideband_protocol_smoke_test_seq.py:29-30`
- **Observed:** `csr_read` for the four OKAY AVS status/debug probes never sets
  `expected`, so the scoreboard only gates `resp_ok`. Log shows concrete `rdata`
  (`0xdeadbeef`, `0x220000`, `0x8000800`, …) that is never compared.
- **Closure:** wire independently derived expecteds into
  `csr_read(..., expected=...)` where a SPEC/RDL golden exists so wrong data fails;
  document any probe that must remain response-class-only.

</details>

**Then:** owner remediates FIND-001 (exact OKAY expectations), re-runs seed 1, keeps a
PASS log, then re-invoke `/dv_test_audit smc_sideband_protocol_smoke_test`.
Do not invent a card here (`STANDALONE-REQUEST`).

## All checkers

| Checker | Grade | Proof class | Covers | Findings |
|---|---|---|---|---|
| — | — | — | — | no card checkers (MODE=NO-CHECKBOX) |

### Layer 1 structural rule set

| Rule | Result |
|---|---|
| F1 fabricated verdict / backdoor write | ✅ clean — frontdoor SEP_IN AXI CSR probes via `SmcCsrSeq` / `smc_addr`; no force/deposit on proof path |
| F2 can't-fail checker | ✅ clean — scoreboard `resp_ok` / `expect_error` asserts and seq `accesses == total` are reachable FAIL-ON paths; this run exercised 4 OKAY + 1 SLVERR |
| E1 skip-to-pass | ✅ clean — no missing-handle skip-to-pass; all five CSR accesses completed |
| E2 empty phase | ✅ clean — real CSR read loop; scoreboard SYS AXI checks #1–#5 present |
| S1 silent fail | ✅ clean — mismatch raises `AssertionError` in scoreboard/sequence; no swallow-to-pass |
| O1 checker disabled | ✅ clean — scoreboard SYS AXI checks #1–#5 active; `expect_error` path not gated off |
| Phase-S obligations — L1 | 🟠 Major — FIND-001 `[EXACT-EXPECTATION]`; else addresses from `smc_addr_map`, force-free, seed logged, enrolled in `batch_d.toml` / `all.toml` / `vplan_triplets.toml`, negative `AVS_READBACK` SLVERR has same-window OKAY positive control, X/Z via resolvable AXI responses, no unconditional CHK token |
| Phase-S obligations — L2 (needs the card) | — not evaluated |

## Evidence appendix

<details>
<summary>Kept log + code proof-path notes</summary>

- Test: `hw/sys/smc/dv/cocotb/tests/smc_sideband_protocol_smoke_test.py` starts
  `smc_sideband_protocol_smoke_test_seq` on `sys_axi_agent.sequencer`.
- Sequence: `hw/sys/smc/dv/cocotb/seq_lib/smc_sideband_protocol_smoke_test_seq.py`
  (addresses via `smc_addr(...)` from `seq_lib/smc_addr_map.py`).
- Helpers: `hw/sys/smc/dv/cocotb/seq_lib/smc_csr_seq_utils.py` (`csr_read`,
  `csr_read_expect_error`); scoreboard `smc_scoreboard.py:_check_sys_axi`
- Log: `hw/sys/smc/dv/build/runs/20260806_094601__verilator__smc_sideband_protocol_smoke_test/smc_sideband_protocol_smoke_test/logs/smc_sideband_protocol_smoke_test.log`
  sha256 `fd6d10b383498c656928bd35dad2abf24c87d0cf910496d48707ff398399eac8`
  (verified via `sha256sum`; matches invoker hint)
- Seed: 1 · simulator: verilator 5.050 2026-07-01 · model fingerprint `2c815fa08277`
- Cocotb summary L328–L334: `smc_sideband_protocol_smoke_test ... PASS` /
  `TESTS=1 PASS=1 FAIL=0 SKIP=0`
- Final seq gate: `assert self.accesses == total` (5) after the five CSR probes;
  no unexplained `ERROR`/`FATAL`/`Traceback` on the proof path.
- Address map agreement (generated symbols → kept log):
  - `AVS_DEBUG_READBACK` `0xC0004008` OKAY `rdata=0xdeadbeef` (L280–L293)
  - `AVS_NORMAL_STATUS` `0xC0004020` OKAY `rdata=0x220000` (L295–L300)
  - `AVS_SLAVE_STATUS` `0xC0004024` OKAY `rdata=0x0` (L302–L307)
  - `AVS_FIFOS_STATUS` `0xC0004028` OKAY `rdata=0x8000800` (L309–L314)
  - `AVS_READBACK` `0xC0004004` SLVERR `resp=2` (L316–L321); monitor OKAY=4, SLVERR=1
- Protocol VIP post-scenario record is a completion marker (`mode=proxy`,
  `csr_accesses=0`); scoreboard documents real proof lives in SYS-AXI checks.
- Enrollment: `hw/sys/smc/dv/testlists/batch_d.toml`, `all.toml`, `vplan_triplets.toml`
- Bring-up trailer: efuse hex + ROM `$readmemh` — time-0 image load; not used as
  AVS golden on this proof path.
- Entry gate / Layer 2 not evaluated (`MODE=NO-CHECKBOX`; `entry_status: NOT-EVALUATED`).
- Provenance: legacy (`test_author.run_id: unknown`).

</details>

<details>
<summary>Stimulus / pass cites (kept log <code>fd6d10b3…</code>)</summary>

| Step | Line (approx) | What the log shows | Impl |
|---|---|---|---|
| bring-up | 266–279 | powergood + cold reset; agents ready | `smc_base_test` |
| OKAY reads | 280–314 | `0xc0004008/4020/4024/4028` OKAY; scoreboard #1–#4 | seq `:29-30` |
| expect_error | 316–321 | `0xc0004004` SLVERR resp=2; scoreboard #5 | seq `:31-32` |
| cocotb result | 328–334 | `PASS` / `PASS=1 FAIL=0` | — |

</details>

## Not concluded

- Whether a corrected AVSBus CSR decode precheck proves the SPEC properties a future card would require (O2) — Skill 3.
- Completeness against a feature_list — no inventory applies in STANDALONE-REQUEST.
- Any closure or PROVEN checker claim — MODE=NO-CHECKBOX forbids inventing checkers.

## Accepted waivers

| Finding | Rule | Where | Why | Approved by |
|---|---|---|---|---|
| — | — | — | none | — |
