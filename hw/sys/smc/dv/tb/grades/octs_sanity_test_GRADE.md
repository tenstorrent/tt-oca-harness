---
schema: dv-quality/v1
artifact: testcase-grade
testcase: octs_sanity_test
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
- path: hw/sys/smc/dv/build/runs/20260806_094625__verilator__octs_sanity_test/octs_sanity_test/logs/octs_sanity_test.log
  sha256: 3e58f2092ac9de4e32b84e3befec90d5fe18869e32ba73a2a8cecba9dc6c7806
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
  artifact_ref: hw/sys/smc/dv/cocotb/seq_lib/smc_avsbus_status_depth_test_seq.py:29-30
  observed: >-
    After the map fix, OKAY-path probes still call `csr_read(n, addr)` with
    `expected=None`, so `smc_scoreboard._check_sys_axi` only asserts AXI OKAY
    and never compares `rdata`. Kept log (PASS, seed 1) shows scoreboard
    checks #1–#4 with `exp=None`: DEBUG_READBACK `0xdeadbeef`, NORMAL_STATUS
    `0x220000`, SLAVE_STATUS `0x0`, FIFOS_STATUS `0x8000800` — OKAY/activity
    alone is not an exact status-decode contract. (PeakRDL defaults differ
    again for some symbols: DEBUG_READBACK default `0xFFFFFFFF`, FIFOS
    `0x08000800` in `smc_reg.py`; wiring those without an independent
    SPEC/fixed-vector golden would still be the wrong expect-source.)
  closure_condition: >-
    Pass independent exact expecteds (SPEC/reset table or approved fixed
    vectors — not RTL-copied) into `csr_read(..., expected=...)` for every
    OKAY probe that claims a value; keep `expected=None` only where no
    independent golden exists and document that limit. Retain the
    fail-capable `expect_error` path for AVS_READBACK if SPEC still requires
    SLVERR on this SEP_IN window.
  waived_by: null
waivers: []
recommendation: NOT-READY
---

# Grade Report — octs_sanity_test (standalone Layer 1)

**VERDICT: 0/0 PROVEN — NOT READY** (mode NO-CHECKBOX, no_contract_reason STANDALONE-REQUEST)

| Mode | Entry gate | Checkers | Findings | Recommendation |
|---|---|---|---|---|
| `NO-CHECKBOX` | — NOT-EVALUATED | 0/0 PROVEN | 🟠 1 Major | ⛔ NOT-READY |

> No approved checkbox card or parent plan record governs this testcase
> (`STANDALONE-REQUEST` / active-regression L1 wave). Layer 1 findings are the entire
> scope of this report. `NOT-READY` records the **absence of a closure claim, not a
> defect** in the test by itself. Kept log is a sim **PASS** (seed 1); Layer 2 entry
> is not evaluated in this mode.

## DELTA (re-audit vs prior grade `0/0 NOT-READY` on log `1a9c557a…`)

| Item | Prior (log `1a9c557a…`, FAIL) | This audit (log `3e58f209…`, PASS) |
|---|---|---|
| Verdict | 0/0 PROVEN — NOT READY | 0/0 PROVEN — NOT READY |
| Findings | 🔴 1 Blocking · 🟠 1 Major | 🟠 1 Major |
| Prior FIND-001 `[ADDRESS-FROM-AUTHORITATIVE-MAP]` | open — AVS names on `0xC0008xxx` | **closed** — seq uses `smc_addr(...)`; log hits `0xC0004xxx` (DEBUG/NORMAL/SLAVE/FIFOS + READBACK SLVERR) |
| Prior FIND-002 `[EXACT-EXPECTATION]` | open — OKAY `exp=None` | still open → this FIND-001; OKAY checks #1–#4 still `exp=None` on correct window |
| Kept log | `1a9c557aee39aba10a613e886b26d84a7437c498e5dc5bd3a4c4239bdffc8ee5` | `3e58f2092ac9de4e32b84e3befec90d5fe18869e32ba73a2a8cecba9dc6c7806` |
| repository_revision | `2ecc7b22…` | `c10b6d63…` |
| Sim result | FAIL (expect_error got OKAY at wrong addr) | PASS (4 OKAY + 1 SLVERR; sideband + VIP recorded) |
| Waivers carried | none signed (`waivers: []`) | none (nothing to drop; no signed entries) |

## Your to-do — 1 item (🟠 1 Major)

| # | Kind | Id | Severity / grade | Where |
|---|---|---|---|---|
| 1 | finding | FIND-001 | 🟠 Major | `smc_avsbus_status_depth_test_seq.py:29-30` |

<details>
<summary>1. FIND-001 — 🟠 Major <code>[EXACT-EXPECTATION]</code> — OKAY status reads never compare rdata</summary>

- **Where:** `hw/sys/smc/dv/cocotb/seq_lib/smc_avsbus_status_depth_test_seq.py:29-30` (invoked by `octs_sanity_test.py:20-21`)
- **Observed:** `csr_read` without `expected=` → scoreboard `exp=None` on checks #1–#4 (log L293/L300/L307/L314). Values observed (`0xdeadbeef` / `0x220000` / `0x0` / `0x8000800`) are never contracted; OKAY-only is not an exact status-decode proof.
- **Closure:** Wire independent exact expecteds into `item.expected` for every value-claiming OKAY probe; re-keep a PASS log showing non-`None` `exp=` compares.

</details>

**Then:** owner remediates FIND-001 in the shared sequence (also used by `smc_avsbus_status_depth_test`), re-keeps a PASS log for `octs_sanity_test`, and re-invokes `/dv_test_audit octs_sanity_test`; do not invent a card here (`STANDALONE-REQUEST`). Closure claims need `/dv_vplan_gen` first.

## All checkers

| Checker | Grade | Proof class | Covers | Findings |
|---|---|---|---|---|
| — | — | — | — | no card checkers (MODE=NO-CHECKBOX) |

### Layer 1 structural rule set

| Rule | Result |
|---|---|
| F1 fabricated verdict / backdoor write | ✅ clean — SEP_IN SYS AXI frontdoor via `SmcSysAxiItem`; no force/deposit on the CSR proof path; ROM/efuse hex preload is bring-up trailer, not golden substitution; protocol VIP `passed` is a completion marker (scoreboard does not assert it) |
| F2 can't-fail checker | ✅ clean — scoreboard `expect_error` assert and seq `resp_code > 1` / `accesses == total` are fail-capable (this PASS exercised SLVERR on AVS_READBACK) |
| E1 skip-to-pass | ✅ clean — no missing-path skip-to-pass; AXI timeout raises; body completed all five CSR probes |
| E2 empty phase | ✅ clean — five SYS AXI reads + sideband observability + protocol VIP record (scoreboard checks #1–#5 + VIP #1) |
| S1 silent fail | ✅ clean — scoreboard raises on expect_error/OKAY mismatch; no swallow-to-pass |
| O1 checker disabled | ✅ clean — SYS AXI scoreboard path active in log (`Scoreboard SYS AXI check #1`…`#5`) |
| Phase-S obligations — L1 | 🟠 Major — FIND-001; else address-from-map clean (`smc_addr` → `0xC0004xxx`), timeouts fail, seed=1 logged, enrolled in `vplan_triplets.toml`, negative READBACK SLVERR paired with OKAY probes, sideband helper X-aware `is_resolvable`, no unconditional CHK token; OCTS pad BFM deferred by declared SUBSTITUTE (not graded as O2 here) |
| Phase-S obligations — L2 (needs the card) | — not evaluated |

## Evidence appendix

<details>
<summary>Kept log + code proof-path notes</summary>

- Implementation: `hw/sys/smc/dv/cocotb/tests/octs_sanity_test.py`
- Sequence: `hw/sys/smc/dv/cocotb/seq_lib/smc_avsbus_status_depth_test_seq.py`
- Sideband helper: `hw/sys/smc/dv/cocotb/seq_lib/smc_sideband_vip_utils.py` `check_sideband_observability`
- CSR helpers: `hw/sys/smc/dv/cocotb/seq_lib/smc_csr_seq_utils.py` `csr_read` / `csr_read_expect_error`
- Scoreboard (proof path): `hw/sys/smc/dv/cocotb/env/smc_scoreboard.py` `_check_sys_axi`
- Authoritative map: `hw/sys/smc/regs/gen/c/smc_addr.h` via `smc_addr_map.py`
- Log: `hw/sys/smc/dv/build/runs/20260806_094625__verilator__octs_sanity_test/octs_sanity_test/logs/octs_sanity_test.log`
  sha256 `3e58f2092ac9de4e32b84e3befec90d5fe18869e32ba73a2a8cecba9dc6c7806` (matches claimed / `manifest.py hash-file`)
- Seed: 1 · simulator: verilator 5.050 2026-07-01 · model fingerprint `2c815fa08277`
- `result.json`: `status: PASS`, `exit_code: 0`, cocotb summary L333–L335:
  `octs_sanity_test … PASS` / `TESTS=1 PASS=1 FAIL=0 SKIP=0`
- Stimulus: 4× OKAY `csr_read` + 1× `csr_read_expect_error` (AVS_READBACK SLVERR);
  then `check_sideband_observability` + `record_protocol_vip` (SUBSTITUTE note)
- Observed beats: OKAY at `0xc0004008` rdata=`0xdeadbeef`, `0xc0004020`=`0x220000`,
  `0xc0004024`=`0x0`, `0xc0004028`=`0x8000800`; expect_error at `0xc0004004` rresp=2
- AXI monitor: `5 R beats … OKAY=4, SLVERR=1; 0 errors`
- Sideband: `avs_irq=0 telemetry_irq=0 avs_state=0x8` (resolvability asserted; values logged)
- Enrollment: `hw/sys/smc/dv/testlists/vplan_triplets.toml`
- Bring-up trailer: efuse/ROM hex preload after PASS flush; not used as AVSBus golden
- Entry gate / Layer 2 not evaluated (MODE=NO-CHECKBOX); authoritative PASS (§5) met for
  the kept log but unused for entry in this mode
- Provenance: legacy (`test_author.run_id: unknown`)

</details>

<details>
<summary>Stimulus / sample cites (kept log <code>3e58f209…</code>)</summary>

| Step | Line (approx) | What the log shows | Impl |
|---|---|---|---|
| DEBUG OKAY | 280–294 | `0xc0004008` rresp=0 rdata=`0xdeadbeef` `exp=None` | seq `:30` / FIND-001 |
| NORMAL OKAY | 295–301 | `0xc0004020` rdata=`0x220000` `exp=None` | seq `:30` |
| SLAVE OKAY | 302–308 | `0xc0004024` rdata=`0x0` `exp=None` | seq `:30` |
| FIFOS OKAY | 309–315 | `0xc0004028` rdata=`0x8000800` `exp=None` | seq `:30` |
| READBACK expect_error | 316–321 | `0xc0004004` rresp=2 → scoreboard OK | seq `:32` |
| Sideband + VIP | 323–325 | resolvable IRQs/state; SUBSTITUTE proxy record | test `:22-32` |
| cocotb result | 329–335 | `PASS` / `PASS=1 FAIL=0` | — |

</details>

## Not concluded

- Whether this OCTS-named / AVS-proxy scenario matches the SPEC properties a future card would require (O2) — Skill 3.
- Completeness against a feature_list — no inventory applies in STANDALONE-REQUEST.
- Any closure or PROVEN checker claim — MODE=NO-CHECKBOX forbids inventing checkers.

## Accepted waivers

| Finding | Rule | Where | Why | Approved by |
|---|---|---|---|---|
| — | — | — | none | — |
