---
schema: dv-quality/v1
artifact: testcase-grade
testcase: smc_dma_sanity_test
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
- path: hw/sys/smc/dv/build/runs/20260806_095341__verilator__smc_dma_sanity_test/smc_dma_sanity_test/logs/smc_dma_sanity_test.log
  sha256: 1fed727fa6e20215e565c58c10fd1f77e1198c0d203d3aeec1663ca940d8330a
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
  artifact_ref: hw/sys/smc/dv/cocotb/seq_lib/smc_dma_sanity_test_seq.py:15-31
  observed: >
    Partial remediation vs prior grade: inbound/outbound filter CSRs now resolve
    via `smc_indexed_addr(...)` (matches PeakRDL). Proof-path DMA_CTRL_* absolute
    addresses and `DMA_CONFIG_ENABLED_ND = 1 << 10` remain hand-copied numeric
    literals (`DMA_CTRL_CONFIG=0xC003_8000` through
    `DMA_CTRL_NUM_REPETITIONS_HI=0xC003_8134`). Generated symbols already exist
    in `smc_addr_map` (`DMA_CTRL_*`, `DMA_CONFIG_ENABLED_ND` from
    `smc_addr.h` / `dma_ctrl_addr.h` / `dma_ctrl.h`) and every literal currently
    matches the map (latent-rot class, not false-identity). Sibling
    `smc_dma_cg_activity_test_seq.py` already imports the same DMA symbols.
    `PASS_ALL_CONFIG = 0x0100_3013` is still a parallel hand constant for filter
    CONFIG data (not an address identity failure).
  closure_condition: >
    Replace every proof-path DMA_CTRL_* address and `DMA_CONFIG_ENABLED_ND`
    with imports from `smc_addr_map` (same pattern as
    `smc_dma_cg_activity_test_seq.py`); keep `PASS_ALL_CONFIG` only if derived
    from generated field masks or an explicitly SPEC-cited constant, not a
    parallel hand table.
  waived_by: null
waivers: []
recommendation: NOT-READY
---

# Grade Report — smc_dma_sanity_test (standalone Layer 1 re-audit)

**VERDICT: 0/0 PROVEN — NOT READY** (mode NO-CHECKBOX, no_contract_reason STANDALONE-REQUEST)

| Mode | Entry gate | Checkers | Findings | Recommendation |
|---|---|---|---|---|
| `NO-CHECKBOX` | — NOT-EVALUATED | 0/0 PROVEN | 🟠 1 Major | ⛔ NOT-READY |

> No approved checkbox card or parent plan record governs this testcase
> (`STANDALONE-REQUEST`). Layer 1 findings are the entire scope of this report.
> `NOT-READY` records the **absence of a closure claim, not a defect**. Kept
> log is a sim **PASS** (seed 1, verilator 5.050): DMA programmed, DONE advanced,
> destination bytes matched the predicted payload, and output-fabric activity
> counters moved — Layer 2 entry is still not evaluated in this mode.

## DELTA (re-audit vs prior grade `0/0 NOT-READY` on log `22c9ed28…`)

| Item | Prior (log `22c9ed28…`, PASS) | This audit (log `1fed727f…`, PASS) |
|---|---|---|
| Verdict | 0/0 PROVEN — NOT READY | 0/0 PROVEN — NOT READY |
| Findings | 🟠 1 Major | 🟠 1 Major |
| Prior FIND-001 DMA/filter/`ENABLED_ND` literals | open Major `[ADDRESS-FROM-AUTHORITATIVE-MAP]` (`:14-38` incl. filter `0xC001_5xxx`/`0xC001_6xxx`) | **partially remediated, still open** as FIND-001 Major — filters via `smc_indexed_addr`; residual hand-copied `DMA_CTRL_*` (`:15-30`) and `DMA_CONFIG_ENABLED_ND=1<<10` (`:31`) while `smc_addr_map` exports matching symbols |
| Kept log | `22c9ed28d8f4e05b37fabf706fca832dae6c21bd68bc745792071932676fa85a` | `1fed727fa6e20215e565c58c10fd1f77e1198c0d203d3aeec1663ca940d8330a` |
| Repo rev | `2ecc7b227e3926b253c65b5aac21239eec24ba5f` | `c10b6d63e0b3377f8e2fa38c138e2ea72cae92c7` |
| Auditor run_id | `cursor/grok/4.5` | `cursor/grok/4.5-reaudit-20260806` |
| Waivers carried | none signed (`waivers: []`) | none (nothing to drop; no signed entries) |

## Your to-do — 1 items (🟠 1 Major)

| # | Kind | Id | Severity / grade | Where |
|---|---|---|---|---|
| 1 | finding | FIND-001 | 🟠 Major | `smc_dma_sanity_test_seq.py:15-31` |

<details>
<summary>1. FIND-001 — 🟠 Major <code>[ADDRESS-FROM-AUTHORITATIVE-MAP]</code> — residual hand-copied DMA CSR addresses / ENABLED_ND</summary>

- **Where:** `hw/sys/smc/dv/cocotb/seq_lib/smc_dma_sanity_test_seq.py:15-31`
- **Observed:** Filter CSRs now use `smc_indexed_addr`. All `DMA_CTRL_*` addresses and
  `DMA_CONFIG_ENABLED_ND = 1 << 10` remain numeric literals on the proof path.
  `smc_addr_map` already exports matching symbols; values currently agree → Major
  (latent rot), not Blocking false-identity. Log hits `0xc0038000`…`0xc0038134`
  and CONFIG wdata `0x400`.
- **Closure:** Import every proof-path DMA address and the ENABLED_ND mask from
  `smc_addr_map` (mirror `smc_dma_cg_activity_test_seq.py`); re-keep a PASS log.

</details>

**Then:** owner remediates FIND-001 residual DMA addressing on the sequence, re-keeps a PASS log, and
re-invokes `/dv_test_audit`. Do not invent a card here (`STANDALONE-REQUEST`).

## All checkers

| Checker | Grade | Proof class | Covers | Findings |
|---|---|---|---|---|
| — | — | — | — | no card checkers (MODE=NO-CHECKBOX) |

### Layer 1 structural rule set

| Rule | Result |
|---|---|
| F1 fabricated verdict / backdoor write | ✅ clean — frontdoor SEP_IN CSR + JTAG AXI preload/read; golden prediction via TB `memory_model.write` before DUT read; no force/deposit on proof path |
| F2 can't-fail checker | ✅ clean — `start_id != 0`, DONE timeout `AssertionError`, `actual == DMA_PAYLOAD`, fabric write/read count floors, and `memory_model_checks_seen >= 3` are reachable FAIL-ON paths |
| E1 skip-to-pass | ✅ clean — no missing-handle skip-to-pass; sequence aborts on timeout/mismatch |
| E2 empty phase | ✅ clean — filter program, preload, DMA program, DONE wait, post-copy model check, fabric activity asserts all execute (log CSR/AXI traffic + CHECK #3) |
| S1 silent fail | ✅ clean — mismatches/timeouts raise; scoreboard `assert got == exp` on `check_golden` |
| O1 checker disabled | ✅ clean — SYS AXI + memory-model scoreboard path active (checks #1–#28; memory-model CHECK #1–#3) |
| Phase-S obligations — L1 | 🟠 Major — FIND-001 residual `[ADDRESS-FROM-AUTHORITATIVE-MAP]` on DMA_CTRL_*/ENABLED_ND; DONE poll converts expiry to fail; enrolled in `vplan_triplets.toml`; min activity on fabric/model checks; seed logged; ROM/efuse trailer not proof-path substitution |
| Phase-S obligations — L2 (needs the card) | — not evaluated |

## Evidence appendix

<details>
<summary>Kept log + code proof-path notes</summary>

- Implementation: `hw/sys/smc/dv/cocotb/tests/smc_dma_sanity_test.py`
- Sequence: `hw/sys/smc/dv/cocotb/seq_lib/smc_dma_sanity_test_seq.py`
- Scoreboard (proof path): `hw/sys/smc/dv/cocotb/env/smc_scoreboard.py` (`update_golden` / `check_golden`)
- Log: `hw/sys/smc/dv/build/runs/20260806_095341__verilator__smc_dma_sanity_test/smc_dma_sanity_test/logs/smc_dma_sanity_test.log`
  sha256 `1fed727fa6e20215e565c58c10fd1f77e1198c0d203d3aeec1663ca940d8330a`
  (verified via `manifest.py hash-file`; matches invoker hint)
- Seed: 1 · simulator: verilator 5.050 2026-07-01 · model fingerprint `2c815fa08277`
- Repo rev: `c10b6d63e0b3377f8e2fa38c138e2ea72cae92c7`
- `result.json`: `status: PASS`, `exit_code: 0`, cocotb summary L505–L511:
  `TESTS=1 PASS=1 FAIL=0 SKIP=0`
- Stimulus: pass-all inbound/outbound filters → JTAG preload poison@dst + payload@src
  → DMA ND program → wait DONE > baseline → predict dst in TB model → JTAG
  `check_golden` read of dst → assert fabric write/read counters and
  `memory_model_checks_seen >= 3`
- Observed in log: DONE baseline `0x1` → start_id `0x2` → DONE `0x2`; post-copy
  dst read `10 20 30 40 50 60 70 80`; memory-model CHECK #3; SYS_OUT monitor
  `4 R / 3 B`; protocol VIP `checked_bytes=8, start_id=2, done_id=2`
- Addressing: filter CSRs via `smc_indexed_addr` (`:33-38`); residual DMA literals
  at seq `:15-31`; generated truth in `smc_addr_map` matches every DMA literal and
  `DMA_CONFIG_ENABLED_ND` (0x400)
- Driver FAIL-ON: `_wait_done` raises after 50 polls; scoreboard memory-model
  mismatch raises (`[TIMEOUT-MUST-FAIL]` / `[MUST-FAIL-ON-MISMATCH]` satisfied)
- Enrollment: `hw/sys/smc/dv/testlists/vplan_triplets.toml`
- Bring-up trailer (post-PASS flush): efuse hex + ROM `$readmemh` — time-0 image
  load; not used as DMA payload golden substitution
- No unexplained `ERROR`/`FATAL`/`Traceback` in the kept log
- Provenance: legacy (`test_author.run_id: unknown`)
- Entry gate / Layer 2 not evaluated (MODE=NO-CHECKBOX)

</details>

<details>
<summary>Stimulus / sample cites (kept log <code>1fed727f…</code>)</summary>

| Step | Line (approx) | What the log shows | Impl |
|---|---|---|---|
| filter pass-all | 293–328 | SEP_IN writes `0xc0015000`/`0xc0016000` windows | seq `:63-73` |
| preload dst/src | 335–347 | JTAG writes poison + payload; model UPDATE #1–#2 | seq `:138-139` |
| preload verify | 359–371 | JTAG reads match; memory-model CHECK #1–#2 | seq `:140-145` |
| DMA program + start | 377–475 | CONFIG/addr/len writes; NEXT_ID=2 | seq `:147-150` |
| DONE wait | 482–489 | DONE 1→2 | seq `:152` / `:120-129` |
| post-copy check | 496–499 | dst=`1020304050607080`; CHECK #3 | seq `:155-161` |
| activity gates | 500–504 | VIP details + SYS_OUT 4R/3B | seq `:162-168` |
| cocotb result | 505–511 | `PASS` / `TESTS=1 PASS=1 FAIL=0 SKIP=0` | — |

</details>

## Not concluded

- Whether this DMA payload path proves the SPEC properties a future card would
  require (O2) — Skill 3.
- Completeness against a feature_list — no inventory applies in STANDALONE-REQUEST.
- Any closure or PROVEN checker claim — MODE=NO-CHECKBOX forbids inventing checkers.

## Accepted waivers

| Finding | Rule | Where | Why | Approved by |
|---|---|---|---|---|
| — | — | — | none | — |
