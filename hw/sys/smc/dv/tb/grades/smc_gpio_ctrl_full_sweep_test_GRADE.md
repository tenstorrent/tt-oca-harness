---
schema: dv-quality/v1
artifact: testcase-grade
testcase: smc_gpio_ctrl_full_sweep_test
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
- path: hw/sys/smc/dv/build/runs/20260806_094637__verilator__smc_gpio_ctrl_full_sweep_test/smc_gpio_ctrl_full_sweep_test/logs/smc_gpio_ctrl_full_sweep_test.log
  sha256: 2df28a22569b611c9e68f1cb0617abe415811ca28630accc4999a441cde57966
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
  tag: '[NEGATIVE-NEEDS-POSITIVE-CONTROL]'
  severity: Blocking
  artifact_ref: hw/sys/smc/dv/cocotb/seq_lib/smc_gpio_ctrl_full_sweep_test_seq.py:17-19
  observed: >-
    Sequence body only issues negative-path reads through
    `csr_read_decerr_zero` (`expect_error=True`, assert `resp_code > 1` and
    `rdata==0`) for every bootrom `EXTERNAL_MANDATORY_GPIO_CTRL_*` CONTROL
    address. Kept log L813–L819 is PASS with 65 DECERR+0 completions
    (`R-resp tally DECERR=65`, SYS AXI scoreboard checks #1–#65) and no
    same-test allow/normal SEP_IN CSR read that proves the master/scoreboard
    path returns OKAY for a real mapped register before treating DECERR as
    proof of the gpio_ctrl error-slave route. A dead or mis-wired allow path
    would not be distinguished by this negative-only sweep.
  closure_condition: >-
    Add a positive-control OKAY read of an authoritative mapped CSR on the same
    SEP_IN master (or cite an enrolled linked test that already proves that
    allow path), then keep the DECERR+0 sweep as the negative leg against the
    map-sourced gpio_ctrl window.
  waived_by: null
- id: FIND-002
  tag: '[NO-DUMMY-DEAD-CODE]'
  severity: Minor
  artifact_ref: hw/sys/smc/dv/cocotb/tests/smc_gpio_ctrl_full_sweep_test.py:1-29
  observed: >-
    Test module/class docstrings still say "GPIO_CTRL 46-entry full sweep", and
    `record_protocol_vip` details still claim "U5 GPIO_CTRL RW-stub WR->RD sweep
    (CSR storage, not pad protocol)", but the sequence only issues map-driven
    `csr_read_decerr_zero` reads (kept log: `csr_accesses=65`, no writes, no RW
    storage check). The stale 46-entry / WR->RD prose describes a different
    positive CSR sweep than the DECERR decode body that actually ran.
  closure_condition: >-
    Align test/VIP prose with the actual DECERR+0 decode sweep and the
    bootrom-derived entry count (65: indices 0..64), or restore a real WR->RD
    stub check if that remains the intended proof.
  waived_by: null
waivers: []
recommendation: NOT-READY
---

# Grade Report — smc_gpio_ctrl_full_sweep_test (standalone Layer 1 re-audit)

**VERDICT: 0/0 PROVEN — NOT READY** (mode NO-CHECKBOX, no_contract_reason STANDALONE-REQUEST)

| Mode | Entry gate | Checkers | Findings | Recommendation |
|---|---|---|---|---|
| `NO-CHECKBOX` | — NOT-EVALUATED | 0/0 PROVEN | 🔴 1 Blocking · 🟡 1 Minor | ⛔ NOT-READY |

> No approved checkbox card or parent plan record governs this testcase
> (`STANDALONE-REQUEST`). Layer 1 findings are the entire scope of this report.
> `NOT-READY` records the **absence of a closure claim, not a defect**. Kept
> log is a sim **PASS** (seed 1, verilator 5.050): 65 map-sourced GPIO_CTRL
> CONTROL reads completed DECERR+0 — Layer 2 entry is still not evaluated in
> this mode.

## DELTA (re-audit vs prior grade `0/0 NOT-READY` on log `a08b52c6…`)

| Item | Prior (log `a08b52c6…`, FAIL) | This audit (log `2df28a22…`, PASS) |
|---|---|---|
| Verdict | 0/0 PROVEN — NOT READY | 0/0 PROVEN — NOT READY |
| Findings | 🔴 2 Blocking · 🟡 1 Minor | 🔴 1 Blocking · 🟡 1 Minor |
| Prior FIND-001 `[ADDRESS-FROM-AUTHORITATIVE-MAP]` (`0xC000_4440`) | open Blocking — false identity / OKAY@gap | **cleared** — seq uses `external_gpio_ctrl_addr` / bootrom `SMC_TOP_SMC_EXTERNAL_MANDATORY_GPIO_CTRL_*__CONTROL_BASE_ADDR`; log starts `@ 0xc0400100`, ends `@ 0xc0400900` |
| Prior FIND-002 `[NEGATIVE-NEEDS-POSITIVE-CONTROL]` | open Blocking | **still open** as FIND-001 Blocking — DECERR-only sweep, no allow-path OKAY control |
| Prior FIND-003 `[NO-DUMMY-DEAD-CODE]` (46-entry / WR->RD prose) | open Minor | **still open** as FIND-002 Minor — docs/VIP prose unchanged vs DECERR body |
| Kept log | `a08b52c6cb9d8a5117cce2409d206b8558423cf22aa1078e31a9955ca8ebe8ba` (FAIL @ `0xc0004440` OKAY) | `2df28a22569b611c9e68f1cb0617abe415811ca28630accc4999a441cde57966` (PASS, DECERR×65; sha256 verified) |
| Repo rev | `2ecc7b227e3926b253c65b5aac21239eec24ba5f` | `c10b6d63e0b3377f8e2fa38c138e2ea72cae92c7` |
| Auditor run_id | `cursor/grok/4.5` | `cursor/grok/4.5-reaudit-20260806` |
| Waivers carried | none signed (`waivers: []`) | none (nothing to drop; no signed entries) |

## Your to-do — 2 items (🔴 1 Blocking · 🟡 1 Minor)

| # | Kind | Id | Severity / grade | Where |
|---|---|---|---|---|
| 1 | finding | FIND-001 | 🔴 Blocking | `smc_gpio_ctrl_full_sweep_test_seq.py:17-19` |
| 2 | finding | FIND-002 | 🟡 Minor | `smc_gpio_ctrl_full_sweep_test.py:1-29` |

<details>
<summary>1. FIND-001 — 🔴 Blocking <code>[NEGATIVE-NEEDS-POSITIVE-CONTROL]</code> — DECERR-only sweep, no allow path</summary>

- **Where:** `hw/sys/smc/dv/cocotb/seq_lib/smc_gpio_ctrl_full_sweep_test_seq.py:17-19` (`csr_read_decerr_zero`)
- **Observed:** Every access sets `expect_error` and asserts SLVERR/DECERR + `rdata==0`. Kept log PASS shows 65 DECERR+0 completions and zero OKAY control on a real mapped SEP_IN CSR authenticating the master/scoreboard before the negative leg.
- **Closure:** Prove an allow-path OKAY CSR on the same master (inline or linked enrolled test), then keep the DECERR+0 sweep on the map-sourced window.

</details>

<details>
<summary>2. FIND-002 — 🟡 Minor <code>[NO-DUMMY-DEAD-CODE]</code> — stale 46-entry / WR-&gt;RD prose</summary>

- **Where:** `hw/sys/smc/dv/cocotb/tests/smc_gpio_ctrl_full_sweep_test.py:1-29`
- **Observed:** Docs say "46-entry"; VIP details say "RW-stub WR->RD"; body/log are 65 DECERR-expect reads only (`csr_accesses=65`).
- **Closure:** Rewrite prose to match the DECERR decode sweep and bootrom count, or implement the claimed WR->RD check.

</details>

**Then:** owner adds positive-control OKAY evidence and aligns stale prose, re-keeps a PASS log, then re-invoke `/dv_test_audit smc_gpio_ctrl_full_sweep_test`. Do not invent a card here (`STANDALONE-REQUEST`).

## All checkers

| Checker | Grade | Proof class | Covers | Findings |
|---|---|---|---|---|
| — | — | — | — | no card checkers (MODE=NO-CHECKBOX) |

### Layer 1 structural rule set

| Rule | Result |
|---|---|
| F1 fabricated verdict / backdoor write | ✅ clean — frontdoor SEP_IN AXI reads only; no force/deposit on proof path |
| F2 can't-fail checker | ✅ clean — `expect_error` / `resp_code > 1` and `rdata==0` paths are reachable FAIL-ON; prior FAIL log proved the scoreboard path |
| E1 skip-to-pass | ✅ clean — no missing-handle skip-to-pass; 65 AXI completes + final `accesses == len(idxs)` gate |
| E2 empty phase | ✅ clean — body issues real CSR reads for every bootrom GPIO_CTRL index |
| S1 silent fail | ✅ clean — sequence asserts + scoreboard raise on OKAY when `expect_error`; mismatch fails the test |
| O1 checker disabled | ✅ clean — SYS AXI scoreboard checks #1–#65 active; sequence not gated off |
| Phase-S obligations — L1 | 🔴 Blocking — FIND-001; 🟡 Minor — FIND-002; else addresses from bootrom map via `smc_addr_map`, seed logged, enrolled in `p1_coverage_gap.toml`, timeout not used on this path, no unconditional CHK token, ROM/efuse `$readmemh` is post-PASS bring-up trailer |
| Phase-S obligations — L2 (needs the card) | — not evaluated |

## Evidence appendix

<details>
<summary>Kept log + code proof-path notes</summary>

- Implementation: `hw/sys/smc/dv/cocotb/tests/smc_gpio_ctrl_full_sweep_test.py`
- Sequence: `hw/sys/smc/dv/cocotb/seq_lib/smc_gpio_ctrl_full_sweep_test_seq.py`
- Address map helper: `hw/sys/smc/dv/cocotb/seq_lib/smc_addr_map.py`
  (`external_gpio_ctrl_addr` / `external_gpio_ctrl_indices` → bootrom
  `smc_top_regs.h`)
- Scoreboard (proof path): `hw/sys/smc/dv/cocotb/env/smc_scoreboard.py`
  (`_check_sys_axi` `expect_error` branch)
- Log: `hw/sys/smc/dv/build/runs/20260806_094637__verilator__smc_gpio_ctrl_full_sweep_test/smc_gpio_ctrl_full_sweep_test/logs/smc_gpio_ctrl_full_sweep_test.log`
  sha256 `2df28a22569b611c9e68f1cb0617abe415811ca28630accc4999a441cde57966`
  (verified via `sha256sum`; 98949 bytes)
- Seed: 1 · simulator: verilator 5.050 2026-07-01 · model fingerprint `2c815fa08277`
- Repo rev: `c10b6d63e0b3377f8e2fa38c138e2ea72cae92c7`
- Policy rev: `51a3357d9c31a018d69451b055bc956c089af26e1051368e25ce396c84ac2a75`
- `result.json`: `status: PASS`, `exit_code: 0`, cocotb summary L813–L819:
  `TESTS=1 PASS=1 FAIL=0 SKIP=0`
- Stimulus: for each bootrom
  `SMC_TOP_SMC_EXTERNAL_MANDATORY_GPIO_CTRL_{idx}__CONTROL_BASE_ADDR`
  (indices 0..64 → 65 entries): `csr_read_decerr_zero`, then
  `assert accesses == len(idxs)`
- Observed in log: first read `@ 0xc0400100` DECERR `resp=3` `rdata=0`; last
  `@ 0xc0400900` (GPIO_CTRL_64); monitor `65 R beats … DECERR=65; 0 errors`;
  protocol VIP `csr_accesses=65 … passed=True` (details string still WR->RD)
- Addressing: remediated vs prior — no hand `0xC000_4440` base; symbols from
  bootrom map (PeakRDL `smc_addr.h` does not export EXTERNAL_MANDATORY GPIO_CTRL)
- Helper FAIL-ON: `csr_read_decerr_zero` asserts error resp + zero data;
  scoreboard also asserts `resp_code > 1` when `expect_error`
- Enrollment: `hw/sys/smc/dv/testlists/p1_coverage_gap.toml`
- Bring-up trailer (post-PASS flush): efuse hex + ROM `$readmemh` — time-0 image
  load; not used as GPIO_CTRL golden on this proof path
- No unexplained `ERROR`/`FATAL`/`Traceback` in the kept log (DeprecationWarning
  only)
- Provenance: legacy (`test_author.run_id: unknown`)
- Entry gate / Layer 2 not evaluated (MODE=NO-CHECKBOX)

</details>

<details>
<summary>Stimulus / sample cites (kept log <code>2df28a22…</code>)</summary>

| Step | Line (approx) | What the log shows | Impl |
|---|---|---|---|
| bring-up | 266–278 | clocks + cold reset; agents ready | `smc_base_test` |
| AXI read #1 | 280–294 | `0xc0400100` DECERR `resp=3` `rdata=0`; scoreboard #1 | seq `:17-19` / sys_axi |
| AXI read #65 | 800–807 | `0xc0400900` DECERR `resp=3` `rdata=0`; scoreboard #65 | seq loop / map idx 64 |
| monitor tally | 811 | `65 R beats … DECERR=65; 0 errors` | `smc_axi_monitor` |
| VIP proxy | 808–809 | `csr_accesses=65` / stale WR->RD details | test `:22-29` |
| cocotb result | 813–819 | `PASS` / `TESTS=1 PASS=1 FAIL=0 SKIP=0` | — |

</details>

## Not concluded

- Whether a correct gpio_ctrl / err_slv decode sweep proves the SPEC properties a
  future card would require (O2) — Skill 3.
- Completeness against a feature_list — no inventory applies in STANDALONE-REQUEST.
- Any closure or PROVEN checker claim — MODE=NO-CHECKBOX forbids inventing checkers.

## Accepted waivers

| Finding | Rule | Where | Why | Approved by |
|---|---|---|---|---|
| — | — | — | none | — |
