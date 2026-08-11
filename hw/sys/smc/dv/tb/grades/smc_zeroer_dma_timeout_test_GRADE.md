---
schema: dv-quality/v1
artifact: testcase-grade
testcase: smc_zeroer_dma_timeout_test
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
- path: hw/sys/smc/dv/build/runs/20260806_163854__verilator__smc_zeroer_dma_timeout_test/smc_zeroer_dma_timeout_test/logs/smc_zeroer_dma_timeout_test.log
  sha256: 2dfc85a94b6b8f00507bcbcb4ba9ffc1f52ef734bf455d3793452fe10e3c7627
test_author:
  human_id: unknown
  run_id: unknown
  model:
    provider: unknown
    family: unknown
    version: unknown
auditor:
  human_id: minshaoho
  run_id: cursor/grok/4.5-fixloop-20260806
  model:
    provider: cursor
    family: grok
    version: '4.5'
exceptions: []
checkers: []
findings:
- id: FIND-001
  tag: '[NO-DUMMY-DEAD-CODE]'
  severity: Minor
  artifact_ref: hw/sys/smc/dv/cocotb/tests/smc_zeroer_dma_timeout_test.py:1-36
  observed: >-
    Testcase name `smc_zeroer_dma_timeout_test`, VIP kind `ZEROER_DMA`, and
    `timeouts=seq.timeouts` plumbing still imply a DMA/timeout scenario, but the
    sequence body is a zeroer DEST/SIZE region-clear + neighbour-untouched
    payload check (`timeouts=0` in the kept log; no DMA engine timeout path).
    Module docstring already says "datapath payload"; the timeout/DMA naming
    resembles a different unfinished check.
  closure_condition: >-
    Rename/relabel the test and VIP kind/details to the zeroer payload/region
    proof actually implemented, or add a real DMA-timeout stimulus and failing
    timeout assertion if that remains the intent.
  waived_by: null
waivers: []
recommendation: NOT-READY
---

# Grade Report — smc_zeroer_dma_timeout_test (standalone Layer 1 re-audit)

**VERDICT: 0/0 PROVEN — NOT READY** (mode NO-CHECKBOX, no_contract_reason STANDALONE-REQUEST)

| Mode | Entry gate | Checkers | Findings | Recommendation |
|---|---|---|---|---|
| `NO-CHECKBOX` | — NOT-EVALUATED | 0/0 PROVEN | 🟡 1 Minor | ⛔ NOT-READY |

> No approved checkbox card or parent plan record governs this testcase
> (`STANDALONE-REQUEST` / active-regression L1 wave). Layer 1 findings are the entire
> scope of this report. `NOT-READY` records the **absence of a closure claim, not a
> defect**. Kept log is a sim **PASS** (seed 1, verilator 5.050): post-preload write-count
> baseline, post-trigger `2->3`, and JTAG poison→zero / neighbour preserve land — Layer 2
> entry is still not evaluated in this mode.

## DELTA (re-audit vs prior grade `0/0 NOT-READY` on log `3bef8e3d…`)

| Item | Prior (log `3bef8e3d…`, PASS) | This audit (log `2dfc85a9…`, PASS) |
|---|---|---|
| Verdict | 0/0 PROVEN — NOT READY | 0/0 PROVEN — NOT READY |
| Findings | 🔴 2 Blocking · 🟡 1 Minor | 🟡 1 Minor |
| Prior FIND-001 `[NO-ALWAYS-PASS-CHECKER]` | open Blocking — write-count baseline before preload; log `0->2` same ns as CTRL_STATUS | **closed** — seq samples baseline after preload (`:207`); wait/assert `baseline+1`; kept log L365 `baseline after preload=2`, L390 `2->3` at 5190ns after CTRL B at 5166ns (not `0->2`) |
| Prior FIND-002 `[NO-ALWAYS-PASS-CHECKER]` | open Blocking — `memory_model.write(ZEROER_EXPECTED)` then `expect` + VIP "matched memory model" | **closed** — no post-trigger model rewrite/expect; VIP details name JTAG AXI readback (`checked_bytes=8; neighbour poison unchanged`) |
| Prior FIND-003 `[NO-DUMMY-DEAD-CODE]` | open Minor — dma_timeout / ZEROER_DMA naming vs payload clear | **still open** as FIND-001 — name/VIP/`timeouts=0` unchanged |
| Kept log | PASS seed=1 (`20260806_094611…`) | PASS seed=1 (`20260806_163854…`); repo `c10b6d63…`; model `2c815fa08277` |
| Waivers carried | none signed (`waivers: []`; nothing to drop) | none |

## Your to-do — 1 item (🟡 1 Minor)

| # | Kind | Id | Severity / grade | Where |
|---|---|---|---|---|
| 1 | finding | FIND-001 | 🟡 Minor | `smc_zeroer_dma_timeout_test.py:1-36` |

<details>
<summary>1. FIND-001 — 🟡 Minor <code>[NO-DUMMY-DEAD-CODE]</code> — dma_timeout / ZEROER_DMA naming vs payload clear</summary>

- **Where:** `hw/sys/smc/dv/cocotb/tests/smc_zeroer_dma_timeout_test.py:1-36`
- **Observed:** Name/VIP kind/timeouts plumbing imply DMA timeout; body is zeroer region clear (`timeouts=0`).
- **Closure:** Align name/VIP/details with the payload proof, or implement a real DMA-timeout failing check.

</details>

**Then:** owner optionally renames/relabels (FIND-001 hygiene). Prior Blocking always-pass paths are closed on this kept log — do not invent a card here (`STANDALONE-REQUEST`).

## All checkers

| Checker | Grade | Proof class | Covers | Findings |
|---|---|---|---|---|
| — | — | — | — | no card checkers (MODE=NO-CHECKBOX) |

### Layer 1 structural rule set

| Rule | Result |
|---|---|
| F1 fabricated verdict / backdoor write | ✅ clean — CSR via SEP_IN frontdoor; fabric preload/readback via JTAG AXI; `tb_output_axi_write_count` is passive observe; no force/deposit on proof path |
| F2 can't-fail checker | ✅ clean — post-preload baseline+1 wait raises on miss; JTAG `assert actual == ZEROER_EXPECTED` / neighbour asserts have FAIL-ON; no model write-then-expect |
| E1 skip-to-pass | ✅ clean — no missing-handle skip-to-pass; sequence runs full S1–S3 |
| E2 empty phase | ✅ clean — real filter CSR writes, JTAG preload/readback, zeroer program/trigger, post-trigger fabric reads |
| S1 silent fail | ✅ clean — JTAG payload/neighbour asserts and wait expiry raise `AssertionError` |
| O1 checker disabled | ✅ clean — SYS AXI scoreboard checks #1–#15 and protocol VIP check #1 active |
| Phase-S obligations — L1 | 🟡 Minor — FIND-001; else ZEROER_* CSR addrs from PeakRDL `smc_reg.py`; wait bound raises; CHK tokens after asserts; X/Z-aware write-count sample; enrolled in `batch_d.toml` / `all.toml` / `vplan_triplets.toml` |
| Phase-S obligations — L2 (needs the card) | — not evaluated |

## Evidence appendix

<details>
<summary>Kept log + code proof-path notes</summary>

- Implementation: `hw/sys/smc/dv/cocotb/tests/smc_zeroer_dma_timeout_test.py`
  starts `smc_zeroer_dma_timeout_test_seq` on `sys_axi_agent.sequencer`
- Sequence: `hw/sys/smc/dv/cocotb/seq_lib/smc_zeroer_dma_timeout_test_seq.py`
- Helpers on proof path: `SmcCsrSeq.csr_write` → SEP_IN `smc_sys_axi_agent` /
  scoreboard `resp_ok`; JTAG `_write_bytes`/`_read_bytes` via `jtag_axi_agent`;
  passive `cocotb.top.tb_output_axi_write_count`
- Log: `hw/sys/smc/dv/build/runs/20260806_163854__verilator__smc_zeroer_dma_timeout_test/smc_zeroer_dma_timeout_test/logs/smc_zeroer_dma_timeout_test.log`
  sha256 `2dfc85a94b6b8f00507bcbcb4ba9ffc1f52ef734bf455d3793452fe10e3c7627`
  (verified via `hashlib.sha256` of file bytes; size 47296; matches parallel hash check)
- Seed: 1 · simulator: verilator 5.050 2026-07-01 · model fingerprint `2c815fa08277`
- `result.json`: `status: PASS`, `exit_code: 0`, cocotb summary:
  `TESTS=1 PASS=1 FAIL=0 SKIP=0`
- Stimulus: pass-all inbound/outbound filters → JTAG poison+neighbour preload +
  readback → **sample write-count baseline** → program `ZEROER_DEST_ADDR`/`SIZE`
  from `smc_reg` → `ZEROER_CTRL_STATUS=1` → wait write-count ≥ baseline+1 →
  JTAG zero/neighbour readback (no `memory_model.expect` of `ZEROER_EXPECTED`)
- Addressing: PeakRDL `ZEROER_CTRL_*_REG_ADDR` (`0xc0038200` / `8208` / `8210`);
  fabric window `0x0200_0000` is TB SYS_OUT memory target (non-CSR)
- Real FAIL-ON present: `_wait_for_zeroer_write` expiry, `assert actual == ZEROER_EXPECTED`,
  `assert neighbour_after == ZEROER_NEIGHBOUR_POISON`, `assert write_count >= start_writes + 1`
- Enrollment: `hw/sys/smc/dv/testlists/batch_d.toml`, `all.toml`, `vplan_triplets.toml`
- Entry gate / Layer 2 not evaluated (`MODE=NO-CHECKBOX`; `entry_status: NOT-EVALUATED`)
- Provenance: legacy (`test_author.run_id: unknown`); auditor `run_id: cursor/grok/4.5-fixloop-20260806`
- Note: test file carries a DV-CARD provenance header (SMC_006); this audit is
  `STANDALONE-REQUEST` and does not grade or invent checkbox closure from that header

</details>

<details>
<summary>Stimulus / sample cites (kept log <code>2dfc85a9…</code>)</summary>

| Step | Line (approx) | What the log shows | Impl |
|---|---|---|---|
| STEP S1 | 268 | SETUP pass-all + JTAG poison/neighbour | seq `:183-187` |
| CHK-NONVAC | 365 | preload observed; **baseline after preload=2** | seq `:200-213` |
| STEP S2 / DECODE | 366–381 | DEST/SIZE CSR OKAY `@0xc0038200/8208` | seq `:215-226` |
| CTRL_STATUS B | 385–388 | write write complete @ 5166ns | seq `:232` |
| TRIGGER | 390 | **`2->3` (post-preload baseline+1)** @ 5190ns | seq `:234-241` |
| CHK-ZEROED | 405 | fabric `00…00`, neighbour preserved; count `3` ≥ baseline+1 | seq `:243-269` |
| VIP / monitors | 407–411 | JTAG AXI readback details; `timeouts=0`; SYS_OUT `4 R / 3 B` | test + monitors |
| cocotb result | 412–418 | `PASS` / `TESTS=1 PASS=1 FAIL=0 SKIP=0` | — |

</details>

## Not concluded

- Whether this payload/region-clear sequence proves the SPEC zeroer or DMA-timeout
  properties a future card would require (O2) — Skill 3.
- Completeness against a feature_list — no inventory applies in STANDALONE-REQUEST.
- Any closure or PROVEN checker claim — MODE=NO-CHECKBOX forbids inventing checkers.

## Accepted waivers

| Finding | Rule | Where | Why | Approved by |
|---|---|---|---|---|
| — | — | — | none | — |
