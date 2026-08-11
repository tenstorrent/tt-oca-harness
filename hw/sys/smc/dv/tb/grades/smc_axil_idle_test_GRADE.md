---
schema: dv-quality/v1
artifact: testcase-grade
testcase: smc_axil_idle_test
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
- path: hw/sys/smc/dv/build/runs/20260806_094547__verilator__smc_axil_idle_test/smc_axil_idle_test/logs/smc_axil_idle_test.log
  sha256: 19b6aa4f0ca4c16691396646bcc4896fd5c4513b88296818711556fcda5bc6cb
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
  tag: '[OBSERVATION-VALIDITY]'
  severity: Major
  artifact_ref: hw/sys/smc/dv/cocotb/seq_lib/smc_axil_idle_test_seq.py:17-22
  observed: >
    Test/docstring claim masters "must stay idle after cold reset release",
    but the sequence issues a single `SmcAxilOp.SAMPLE` at one post-settle
    instant (kept log L279 at 4152.00ns). A one-shot poll cannot resolve
    sustained idle or catch a pulse outside that latch; sibling
    `smc_axil_burst_idle_test` already uses 8 spaced SAMPLEs for that reason.
  closure_condition: >
    Sample across a multi-cycle post-reset window (fail if any sample sees
    activity / X), or reword the claim to a single-cycle post-settle snapshot
    and keep burst-idle as the sustained-idle proof.
  waived_by: null
- id: FIND-002
  tag: '[NO-DUMMY-DEAD-CODE]'
  severity: Minor
  artifact_ref: hw/sys/smc/dv/cocotb/seq_lib/smc_axil_idle_test_seq.py:15-22
  observed: >
    Sequence stores `self.sample = item` after SAMPLE, but neither the
    sequence nor the test reads it. Live FAIL-ON path is only scoreboard
    `_check_axil` via the analysis port (`resolvable` + `any_master_active == 0`).
    The unused field resembles an unfinished local assert.
  closure_condition: >
    Assert on `self.sample` in the sequence (resolvable / idle), or drop the
    unused attribute so evidence ownership stays solely on the scoreboard path.
  waived_by: null
waivers: []
recommendation: NOT-READY
---

# Grade Report — smc_axil_idle_test (standalone Layer 1)

**VERDICT: 0/0 PROVEN — NOT READY** (mode NO-CHECKBOX, no_contract_reason STANDALONE-REQUEST)

| Mode | Entry gate | Checkers | Findings | Recommendation |
|---|---|---|---|---|
| `NO-CHECKBOX` | — NOT-EVALUATED | 0/0 PROVEN | 🟠 1 Major · 🟡 1 Minor | ⛔ NOT-READY |

> No approved checkbox card or parent plan record governs this testcase. Layer 1 findings
> are the entire scope of this report. `NOT-READY` records the **absence of a closure
> claim, not a defect**. Kept log is a sim PASS (seed 1); Layer 2 was not entered.

## DELTA (re-audit vs prior grade `0/0 NOT-READY` on log `443042a6…`)

| Item | Prior (log `443042a6…`, PASS) | This audit (log `19b6aa4f…`, PASS) |
|---|---|---|
| Verdict | 0/0 PROVEN — NOT READY | 0/0 PROVEN — NOT READY |
| Findings | 🔴 1 Blocking · 🟠 1 Major · 🟡 1 Minor | 🟠 1 Major · 🟡 1 Minor |
| Prior FIND-001 PLL/PVT OR | open Blocking — claimed missing `axil_pll_req_o` / `axil_pvt_req_o` in `tb_axil_any_master_active` | **closed** — those ports are not SMC AXI-Lite masters; PLL/PVT are demux slaves of `smc_external_req` (`smc_ip_integration.sv`); `tb_axil_external_active` covers that traffic |
| Prior FIND-002 single SAMPLE | open Major `[OBSERVATION-VALIDITY]` | **still open** as FIND-001 Major — one SAMPLE unchanged |
| Prior FIND-003 unused `self.sample` | open Minor `[NO-DUMMY-DEAD-CODE]` | **still open** as FIND-002 Minor — dead store unchanged |
| Kept log | `443042a6024100b97b302b5f1c49953ae1be025a9bbf8a86a28187c962eb8e97` | `19b6aa4f0ca4c16691396646bcc4896fd5c4513b88296818711556fcda5bc6cb` |
| Repo rev | `2ecc7b227e3926b253c65b5aac21239eec24ba5f` | `c10b6d63e0b3377f8e2fa38c138e2ea72cae92c7` |
| Waivers carried | none signed (`waivers: []`) | none (nothing to drop; no signed entries) |

## Your to-do — 2 items (🟠 1 Major · 🟡 1 Minor)

| # | Kind | Id | Severity / grade | Where |
|---|---|---|---|---|
| 1 | finding | FIND-001 | 🟠 Major | `smc_axil_idle_test_seq.py:17-22` |
| 2 | finding | FIND-002 | 🟡 Minor | `smc_axil_idle_test_seq.py:15-22` |

<details>
<summary>1. FIND-001 — 🟠 Major <code>[OBSERVATION-VALIDITY]</code> — single SAMPLE vs "stay idle"</summary>

- **Where:** `hw/sys/smc/dv/cocotb/seq_lib/smc_axil_idle_test_seq.py:17-22`
- **Observed:** "Stay idle after cold reset" is checked with one SAMPLE after settle (log L279). That latch lacks temporal resolution for a sustained-idle claim; burst-idle already demonstrates multi-sample spacing.
- **Closure:** multi-cycle sample window with fail-on-activity, or narrow the claim to a single post-settle snapshot.

</details>

<details>
<summary>2. FIND-002 — 🟡 Minor <code>[NO-DUMMY-DEAD-CODE]</code> — unused <code>self.sample</code></summary>

- **Where:** `hw/sys/smc/dv/cocotb/seq_lib/smc_axil_idle_test_seq.py:15-22`
- **Observed:** `self.sample` is written and never read; scoreboard analysis-port asserts are the only FAIL-ON path.
- **Closure:** assert on `self.sample` locally, or remove the dead store.

</details>

**Then:** owner remediates FIND-001 (temporal claim vs single SAMPLE), optionally FIND-002; re-invoke `/dv_test_audit smc_axil_idle_test`. Do not invent a card here (`STANDALONE-REQUEST`).

## All checkers

| Checker | Grade | Proof class | Covers | Findings |
|---|---|---|---|---|
| — | — | — | — | no card checkers (MODE=NO-CHECKBOX) |

### Layer 1 structural rule set

| Rule | Result |
|---|---|
| F1 fabricated verdict / backdoor write | ✅ clean — passive reads of `tb_axil_*_active`; no force/deposit on proof path |
| F2 can't-fail checker | ✅ clean — `assert resolvable` and `assert any_master_active == 0` can fail; `check_phase` fails if zero SAMPLE items |
| E1 skip-to-pass | ✅ clean — missing HDL handles raise; no skip-to-pass branch |
| E2 empty phase | ✅ clean — one SAMPLE dispatched; scoreboard `_check_axil` + `check_phase` require activity |
| S1 silent fail | ✅ clean — scoreboard mismatches raise `AssertionError` |
| O1 checker disabled | ✅ clean — axil analysis path connected; log shows Scoreboard AXIL sample #1 |
| Phase-S obligations — L1 | 🟠 Major — FIND-001; 🟡 Minor — FIND-002; else X-aware `resolvable`, force-free, enrolled in `axil.toml` / `all.toml`, seed logged, no blind-delay sync on this path; SMC AXIL masters observed are dtp \| external \| efuse (PLL/PVT sit behind external demux) |
| Phase-S obligations — L2 (needs the card) | — not evaluated |

## Evidence appendix

<details>
<summary>Kept log + code proof-path notes</summary>

- Log: `hw/sys/smc/dv/build/runs/20260806_094547__verilator__smc_axil_idle_test/smc_axil_idle_test/logs/smc_axil_idle_test.log`
  sha256 `19b6aa4f0ca4c16691396646bcc4896fd5c4513b88296818711556fcda5bc6cb`
  (verified via `sha256sum`; matches invoker hint)
- Seed: 1 · simulator: verilator 5.050 · model fingerprint `2c815fa08277`
- `result.json`: `status: PASS`, `return_code: 0`, cocotb summary L288–L290:
  `TESTS=1 PASS=1 FAIL=0 SKIP=0`
- Test: `hw/sys/smc/dv/cocotb/tests/smc_axil_idle_test.py`
  sha256 `147631286d791387c0e92ecbdb47c9ea905043e28c09903001fe7850da99e6a5`
  → `smc_axil_idle_test_seq` on `env.axil_agent.sequencer` after `smc_base_test` bring-up
- Seq: `hw/sys/smc/dv/cocotb/seq_lib/smc_axil_idle_test_seq.py`
  sha256 `f73573b0a497ab9ee87502b02951c3d1cab8131b81a8852cf0699c640c91729e`
  — one `SmcAxilOp.SAMPLE`; `self.sample` unused
- Driver: `smc_axil_agent.py:38-55` samples `tb_axil_{dtp_csr,external,efuse_bank,any_master}_active`
- Scoreboard: `smc_scoreboard.py:144-153` asserts resolvable + `any_master_active == 0`;
  `check_phase` requires `total > 0`
- TB OR: `tb_top.sv:1162-1170` — any = dtp \| external \| efuse (matches SMC's three AXI-Lite master outputs in `smc.sv`; PLL/PVT are `smc_ip_integration` demux slaves of `smc_external_req`)
- Kept-log cites: SAMPLE L279 (`any=0, dtp=0, ext=0, efuse=0`); scoreboard L280–L281;
  PASS L284–L290
- Enrollment: `hw/sys/smc/dv/testlists/axil.toml`, `all.toml`
- Bring-up trailer: efuse hex + ROM `$readmemh` — time-0 image load; not used as golden
  for these pin samples (policy §6 standing preload; off this proof path)
- No unexplained `ERROR`/`FATAL`/`Traceback`; only cocotb/library `DeprecationWarning`s
- Provenance: legacy (`test_author.run_id: unknown`)
- Entry gate / Layer 2 not evaluated (MODE=NO-CHECKBOX)

</details>

## Not concluded

- Whether post-reset AXI-Lite idle observability matches SPEC fabric/master properties (O2) —
  Skill 3.
- Completeness against a feature_list — no inventory applies in STANDALONE-REQUEST.
- Any closure or PROVEN checker claim — MODE=NO-CHECKBOX forbids inventing checkers.

## Accepted waivers

| Finding | Rule | Where | Why | Approved by |
|---|---|---|---|---|
| — | — | — | none | — |
