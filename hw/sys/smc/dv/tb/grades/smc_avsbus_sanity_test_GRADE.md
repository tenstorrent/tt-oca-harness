---
schema: dv-quality/v1
artifact: testcase-grade
testcase: smc_avsbus_sanity_test
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
- path: hw/sys/smc/dv/build/runs/20260806_094605__verilator__smc_avsbus_sanity_test/smc_avsbus_sanity_test/logs/smc_avsbus_sanity_test.log
  sha256: 0efbdde76e4b223a30f885025c5c0c30cc67e12b67c835d8c9d12f7f9faee8cc
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
  artifact_ref: hw/sys/smc/dv/cocotb/seq_lib/smc_sideband_protocol_smoke_test_seq.py:11-20
  observed: >
    All four `SIDEBAND_OKAY_READS` call `csr_read(name, addr)` with
    `expected=None`, so `smc_scoreboard._check_sys_axi` only asserts AXI
    OKAY and never compares `rdata`. Kept log L293–L314 shows non-trivial
    AVSBus-window payloads (`0xc0004008` → `0xdeadbeef`, `0xc0004020` →
    `0x220000`, `0xc0004028` → `0x8000800`) that are never checked against an
    independent SPEC/RDL golden. OKAY-only / activity alone is not an exact
    status-register contract. (AVS_READBACK `expect_error` path does assert
    SLVERR/DECERR and is not this finding.)
  closure_condition: >
    Pass independently derived expected values (SPEC/RDL reset or status
    field model) into `csr_read(..., expected=...)` for each OKAY
    status/debug read whose golden is knowable; keep `expected=None` only
    where no independent golden exists and document that limit. Ensure the
    scoreboard `got == exp` path can fail on wrong data. Re-keep a PASS log.
  waived_by: null
waivers: []
recommendation: NOT-READY
---

# Grade Report — smc_avsbus_sanity_test (standalone Layer 1)

**VERDICT: 0/0 PROVEN — NOT READY** (mode NO-CHECKBOX, no_contract_reason STANDALONE-REQUEST)

| Mode | Entry gate | Checkers | Findings | Recommendation |
|---|---|---|---|---|
| `NO-CHECKBOX` | — NOT-EVALUATED | 0/0 PROVEN | 🟠 1 Major | ⛔ NOT-READY |

> No approved checkbox card or parent plan record governs this testcase
> (`STANDALONE-REQUEST` / active-regression L1 wave). Layer 1 findings are the entire
> scope of this report. `NOT-READY` records the **absence of a closure claim, not a
> defect**. Kept log is a sim **PASS** (seed 1); Layer 2 was not entered.

## DELTA (re-audit vs prior grade `0/0 NOT-READY` on log `a52c59c6…`)

| Prior id | Tag / grade | Status this round | Notes |
|---|---|---|---|
| FIND-001 | 🔴 `[ADDRESS-FROM-AUTHORITATIVE-MAP]` | CLOSED (false identity) | Seq now imports `smc_addr(...)` AVS symbols; kept log hits `0xc0004008/4020/4024/4028/4004`; monitor OKAY=4 SLVERR=1 |
| FIND-002 | 🟠 `[EXACT-EXPECTATION]` | OPEN — refiled FIND-001 🟠 | OKAY reads still `expected=None`; payloads logged but never compared |
| waivers: [] | — | unchanged | Prior ledger empty; no signed `approved_by` to carry; none dropped |
| Kept log | `a52c59c6…` (FAIL) | replaced | `0efbdde7…` (seed=1 PASS; model `2c815fa08277`) |
| repository_revision | `2ecc7b22…` | updated | `c10b6d63…` |

## Your to-do — 1 items (🟠 1 Major)

| # | Sev | Item |
|---|---|---|
| 1 | 🟠 Major | FIND-001 `[EXACT-EXPECTATION]` — OKAY sideband reads have no `expected` |

<details>
<summary>1. 🟠 Major — FIND-001 <code>[EXACT-EXPECTATION]</code> — OKAY reads are activity-only</summary>

- **Where:** `hw/sys/smc/dv/cocotb/seq_lib/smc_sideband_protocol_smoke_test_seq.py:11-20`
- **Observed:** Address path is fixed (`smc_addr` → AVSBus `0xC0004xxx` in kept log). Four OKAY probes still omit `expected`, so the scoreboard only gates `resp_ok` while logging non-trivial `rdata`.
- **Closure:** Wire independently derived expecteds into `csr_read(..., expected=...)` where a SPEC/RDL golden exists so wrong data fails; re-keep PASS log.

</details>

**Then:** owner remediates FIND-001 (exact OKAY expectations), re-keeps a PASS log, and
re-invokes `/dv_test_audit smc_avsbus_sanity_test`. Do not invent a card here
(`STANDALONE-REQUEST`).

## All checkers

| Checker | Grade | Proof class | Covers | Findings |
|---|---|---|---|---|
| — | — | — | — | no card checkers (MODE=NO-CHECKBOX) |

### Layer 1 structural rule set

| Rule | Result |
|---|---|
| F1 fabricated verdict / backdoor write | ✅ clean — frontdoor SEP_IN AXI CSR probes + passive `tb_avsbus_*` / `tb_telemetry_irq_any` observability; no force/deposit on proof path |
| F2 can't-fail checker | ✅ clean — scoreboard `expect_error` / `resp_ok` asserts and seq `accesses == total` can fail; prior FAIL proved error-gate sensitivity |
| E1 skip-to-pass | ✅ clean — no missing-handle skip-to-pass; five AXI accesses + observability completed |
| E2 empty phase | ✅ clean — real CSR read loop + `check_sideband_observability`; VIP record after asserts |
| S1 silent fail | ✅ clean — mismatch raises `AssertionError` in scoreboard / sequence |
| O1 checker disabled | ✅ clean — scoreboard SYS AXI checks #1–#5 active; `expect_error` path not gated off |
| Phase-S obligations — L1 | 🟠 Major — FIND-001 `[EXACT-EXPECTATION]`; else addresses via `smc_addr_map`, force-free TB IRQ/state mirrors, seed logged, enrolled in `batch_d.toml` / `all.toml` / `vplan_triplets.toml`, post-CSR `ClockCycles(16)` settle after AXI handshake (not a completion substitute), X/Z via `is_resolvable`, negative AVS_READBACK has positive OKAY controls, no unconditional CHK token |
| Phase-S obligations — L2 (needs the card) | — not evaluated |

## Evidence appendix

<details>
<summary>Kept log + code proof-path notes</summary>

- Test: `hw/sys/smc/dv/cocotb/tests/smc_avsbus_sanity_test.py` starts
  `smc_sideband_protocol_smoke_test_seq` on `sys_axi_agent.sequencer`, then
  `check_sideband_observability()`.
- Sequence: `hw/sys/smc/dv/cocotb/seq_lib/smc_sideband_protocol_smoke_test_seq.py`
- Observability helper: `hw/sys/smc/dv/cocotb/seq_lib/smc_sideband_vip_utils.py`
- Log: `hw/sys/smc/dv/build/runs/20260806_094605__verilator__smc_avsbus_sanity_test/smc_avsbus_sanity_test/logs/smc_avsbus_sanity_test.log`
  sha256 `0efbdde76e4b223a30f885025c5c0c30cc67e12b67c835d8c9d12f7f9faee8cc`
  (verified via `sha256sum`; matches invoker hint)
- Seed: 1 · simulator: verilator 5.050 2026-07-01 · model fingerprint `2c815fa08277`
- Cocotb summary L333–L335: `smc_avsbus_sanity_test ... PASS` /
  `TESTS=1 PASS=1 FAIL=0 SKIP=0`
- Zero unexplained `ERROR`/`FATAL`/`Traceback` (DeprecationWarning only)
- Authoritative map (resolved this round):
  - `SMC_TOP_SMC_AVSBUS_CONTROLLER_AVS_*` at `0xC0004xxx` via `smc_addr`
  - kept log L293–L321 matches those addresses; R-resp tally OKAY=4, SLVERR=1
- Enrollment: `hw/sys/smc/dv/testlists/batch_d.toml`, `all.toml`, `vplan_triplets.toml`
- Bring-up trailer (post-PASS flush): efuse hex + ROM `$readmemh` — time-0 image load;
  not used as AVS golden on this proof path.
- Entry gate / Layer 2 not evaluated (`MODE=NO-CHECKBOX`; `entry_status: NOT-EVALUATED`).
- Provenance: legacy (`test_author.run_id: unknown`).

</details>

<details>
<summary>Stimulus / pass cites (kept log <code>0efbdde7…</code>)</summary>

| Step | Line (approx) | What the log shows | Impl |
|---|---|---|---|
| bring-up | 266–278 | powergood + cold reset; agents ready | `smc_base_test` |
| OKAY reads | 280–315 | `0xc0004008/4020/4024/4028` OKAY; scoreboard #1–#4 | seq `:29-30` |
| expect_error | 316–322 | `0xc0004004` rresp=2 (SLVERR); scoreboard #5 | seq `:31-32` |
| observability | 323 | `avs_irq=0 telemetry_irq=0 avs_state=0x8` | vip_utils |
| VIP / monitor | 324–327 | proxy VIP + OKAY=4 SLVERR=1 | test / monitor |
| cocotb result | 329–335 | `PASS` / `PASS=1 FAIL=0` | — |

</details>

## Not concluded

- Whether AVSBus CSR decode + IRQ/state observability proves the SPEC properties a future card would require (O2) — Skill 3.
- Completeness against a feature_list — no inventory applies in STANDALONE-REQUEST.
- Any closure or PROVEN checker claim — MODE=NO-CHECKBOX forbids inventing checkers.

## Accepted waivers

| Finding | Rule | Where | Why | Approved by |
|---|---|---|---|---|
| — | — | — | none | — |
