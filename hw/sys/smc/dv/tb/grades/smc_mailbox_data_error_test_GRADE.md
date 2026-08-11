---
schema: dv-quality/v1
artifact: testcase-grade
testcase: smc_mailbox_data_error_test
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
- path: hw/sys/smc/dv/build/runs/20260806_094550__verilator__smc_mailbox_data_error_test/smc_mailbox_data_error_test/logs/smc_mailbox_data_error_test.log
  sha256: 5f5f6b60032ee25c910423b68722126401f9fe04e75b473c00d85680428d96e0
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
  tag: '[NO-ALWAYS-PASS-CHECKER]'
  severity: Blocking
  artifact_ref: hw/sys/smc/dv/cocotb/seq_lib/smc_mailbox_data_error_test_seq.py:50-54,113-141,147-160
  observed: >-
    Sequence `_model_write` / `_model_expect` operate on TB-only regions at
    `0x1000_0000` / `0x1000_1000` that never receive SEP_IN AXI traffic. Each
    expect reads back the same integer the preceding write deposited into
    `SmcMemoryModel`, so the assert cannot fail for any DUT/RTL behavior. Real
    data compares exist separately via scoreboard `item.expected` on mailbox
    READ_DATA addresses; the model path still presents as an active FIFO-depth
    golden while proving nothing about silicon.
  closure_condition: >-
    Remove the unused mailbox memory-model write/expect pairs (and the
    `0x1000_*` regions), or rebind them to DUT-visible traffic with
    `update_golden`/`check_golden` (or equivalent) so a wrong FIFO data path
    can fail the model compare.
  waived_by: null
- id: FIND-002
  tag: '[ADDRESS-FROM-AUTHORITATIVE-MAP]'
  severity: Major
  artifact_ref: hw/sys/smc/dv/cocotb/seq_lib/smc_mailbox_data_error_test_seq.py:15-25
  observed: >-
    Block bases and CLOCK_GATE_CONTROL now come from `smc_addr(...)`, but
    proof-path register addresses still append hand offsets (`+0x8` / `+0x10` /
    `+0x18`) instead of PeakRDL per-register symbols already present in
    `smc_addr.h` (e.g. `SMC_TOP_SMC_MAILBOX_*_MAILBOX_0_{WRITE,READ}_DATA /
    STATUS / ERROR_FLAGS_BASE_ADDR`). `MAILBOX_CG_EN = 1 << 1` remains a
    hand-copied bit while
    `SMC_BASE_CONFIG__CLOCK_GATE_CONTROL__MAILBOX_CG_EN_bm` exists in
    `smc_base_config.h`. Current values match the generated map (latent-rot
    class, not false-identity).
  closure_condition: >-
    Import every mailbox WRITE/READ/STATUS/ERROR_FLAGS address and the
    MAILBOX_CG_EN mask from `smc_addr_map.smc_addr` / generated field masks;
    stop using parallel hand offsets / `1 << 1` as the addressing source of
    truth.
  waived_by: null
waivers: []
recommendation: NOT-READY
---

# Grade Report — smc_mailbox_data_error_test (standalone Layer 1)

**VERDICT: 0/0 PROVEN — NOT READY** (mode NO-CHECKBOX, no_contract_reason STANDALONE-REQUEST)

| Mode | Entry gate | Checkers | Findings | Recommendation |
|---|---|---|---|---|
| `NO-CHECKBOX` | — NOT-EVALUATED | 0/0 PROVEN | 🔴 1 Blocking · 🟠 1 Major | ⛔ NOT-READY |

> No approved checkbox card or parent plan record governs this testcase
> (`STANDALONE-REQUEST` / active-regression L1 wave). Layer 1 findings are the entire
> scope of this report. `NOT-READY` records the **absence of a closure claim, not a
> defect** in the test by itself. Kept log is a sim **PASS** (seed 1); Layer 2 entry
> is not evaluated in this mode.

## DELTA (re-audit vs prior grade `0/0 NOT-READY` on log `f6945141…`)

| Prior id | Tag / grade | Status this round | Notes |
|---|---|---|---|
| FIND-001 | 🔴 `[NO-ALWAYS-PASS-CHECKER]` | OPEN — unchanged | `_model_write`/`_model_expect` on `0x1000_*` still TB-self-check; AXI `expected=` on READ_DATA remains the real compare |
| FIND-002 | 🟠 `[ADDRESS-FROM-AUTHORITATIVE-MAP]` | OPEN — partial | Block bases / CLOCK_GATE now via `smc_addr(...)`; residual hand `+0x8/+0x10/+0x18` and `MAILBOX_CG_EN=1<<1` while per-reg symbols / `MAILBOX_CG_EN_bm` exist |
| Kept log | `f6945141…` PASS | replaced | `5f5f6b60…` PASS seed=1; model `2c815fa08277`; same stimulus shape (22 SYS AXI + IRQ mask `0x2`) |
| repository_revision | `2ecc7b22…` | updated | `c10b6d63…` |
| Waivers carried | none signed (`waivers: []`) | none | nothing to drop |

## Your to-do — 2 items (🔴 1 Blocking · 🟠 1 Major)

| # | Kind | Id | Severity / grade | Where |
|---|---|---|---|---|
| 1 | finding | FIND-001 | 🔴 Blocking | `smc_mailbox_data_error_test_seq.py:50-54` |
| 2 | finding | FIND-002 | 🟠 Major | `smc_mailbox_data_error_test_seq.py:15-25` |

<details>
<summary>1. FIND-001 — 🔴 Blocking <code>[NO-ALWAYS-PASS-CHECKER]</code> — TB memory-model expect can't fail on RTL</summary>

- **Where:** `hw/sys/smc/dv/cocotb/seq_lib/smc_mailbox_data_error_test_seq.py:50-54,113-141,147-160`
- **Observed:** `_model_write` then `_model_expect` on `0x1000_0000` / `0x1000_1000` regions never touched by AXI; expect always reads the value just written into the TB model. DUT FIFO data is checked separately by scoreboard `expected=` on `0xC0018808` / `0xC0018008` (log checks #13/#14/#17).
- **Closure:** Drop the self-checking model pairs, or wire them to DUT traffic so a bad data path can fail.

</details>

<details>
<summary>2. FIND-002 — 🟠 Major <code>[ADDRESS-FROM-AUTHORITATIVE-MAP]</code> — residual hand mailbox offsets / MAILBOX_CG_EN</summary>

- **Where:** `hw/sys/smc/dv/cocotb/seq_lib/smc_mailbox_data_error_test_seq.py:15-25`
- **Observed:** Bases now via `smc_addr`; still hand-offsets READ/STATUS/ERROR_FLAGS and `MAILBOX_CG_EN=1<<1` despite PeakRDL per-register symbols and `MAILBOX_CG_EN_bm`. Values currently match → Major (latent rot), not Blocking false-identity.
- **Closure:** Source every proof-path mailbox register address and the MAILBOX_CG_EN mask from generated symbols; drop parallel hand offsets / bit literals as truth.

</details>

**Then:** owner remediates FIND-001/FIND-002 and re-invokes `/dv_test_audit smc_mailbox_data_error_test`; do not invent a card here (`STANDALONE-REQUEST`). Closure claims need `/dv_vplan_gen` first.

## All checkers

| Checker | Grade | Proof class | Covers | Findings |
|---|---|---|---|---|
| — | — | — | — | no card checkers (MODE=NO-CHECKBOX) |

### Layer 1 structural rule set

| Rule | Result |
|---|---|
| F1 fabricated verdict / backdoor write | ✅ clean — SEP_IN SYS AXI frontdoor; IRQ path drives architected `tb_sep_mailbox_interrupts` and samples `tb_mailbox_irq_any`; no Force/deposit on mailbox CSR proof path |
| F2 can't-fail checker | 🔴 Blocking — FIND-001; AXI scoreboard `expected` / `expected_resp` and seq `accesses == 22` remain fail-capable |
| E1 skip-to-pass | ✅ clean — no missing-path skip-to-pass; AXI timeout raises |
| E2 empty phase | ✅ clean — 22 SYS AXI accesses + IRQ lifecycle asserts execute |
| S1 silent fail | ✅ clean — scoreboard `assert` on resp/data; IRQ helper raises; final access-count assert |
| O1 checker disabled | ✅ clean — SYS AXI + protocol VIP analysis paths active in log |
| Phase-S obligations — L1 | 🔴 Blocking — FIND-001; 🟠 Major — FIND-002; else timeouts fail, seed logged, enrolled in `batch_b.toml`/`all.toml`/`vplan_triplets.toml`, negative SLVERR paired with OKAY data path, ROM/efuse preload is post-PASS trailer not golden substitution |
| Phase-S obligations — L2 (needs the card) | — not evaluated |

## Evidence appendix

<details>
<summary>Kept log + code proof-path notes</summary>

- Implementation: `hw/sys/smc/dv/cocotb/tests/smc_mailbox_data_error_test.py`
- Sequence: `hw/sys/smc/dv/cocotb/seq_lib/smc_mailbox_data_error_test_seq.py`
- IRQ helper: `hw/sys/smc/dv/cocotb/seq_lib/smc_mailbox_vip_utils.py`
- Scoreboard (proof path): `hw/sys/smc/dv/cocotb/env/smc_scoreboard.py` `_check_sys_axi` / `_check_protocol_vip`
- Log: `hw/sys/smc/dv/build/runs/20260806_094550__verilator__smc_mailbox_data_error_test/smc_mailbox_data_error_test/logs/smc_mailbox_data_error_test.log`
  sha256 `5f5f6b60032ee25c910423b68722126401f9fe04e75b473c00d85680428d96e0` (matches claimed)
- Seed: 1 · simulator: verilator 5.050 2026-07-01 · model fingerprint `2c815fa08277`
- cocotb summary: `TESTS=1 PASS=1 FAIL=0 SKIP=0` · `result.json` `exit_code: 0`
- Stimulus: enable MAILBOX_CG_EN → illegal WRITE to READ_DATA (SLVERR) → depth-2 outbound FIFO fill + overflow SLVERR → inbound consume with expected data → empty-read SLVERR → inbound→outbound path → restore CG → `assert accesses == 22` → IRQ pin toggle mask `0x2`
- Observed SLVERR beats in log: write `0xc0018008`/`0xc0018808` bresp=2; write-full `0xc0018000` bresp=2; empty reads rresp=2; OKAY data `0x1111…`/`0x5555…`/`0xaaaa…` matched scoreboard `exp=`
- Final gate: access count 22 + IRQ assert/clear; protocol VIP recorded `csr_accesses=22` (completion marker `passed=True` is documented non-checker)
- Enrollment: `hw/sys/smc/dv/testlists/batch_b.toml`, `all.toml`, `vplan_triplets.toml`
- Bring-up trailer: efuse/ROM hex preload present after PASS; not used as mailbox golden
- Entry gate / Layer 2 not evaluated (MODE=NO-CHECKBOX)
- Provenance: legacy (`test_author.run_id: unknown`)

</details>

<details>
<summary>Stimulus / sample cites (kept log <code>5f5f6b60…</code>)</summary>

| Step | Line (approx) | What the log shows | Impl |
|---|---|---|---|
| CG enable RMW | 280–314 | `0xc0010018` read `0x1f000000` → write `0x1f000002` → readback | seq `:85-89` |
| illegal WRITE READ_DATA | 343–356 | bresp=2 on `0xc0018008` / `0xc0018808` | seq `:106-110` |
| outbound fill + overflow | 357–377 | two OKAY writes + third bresp=2 | seq `:112-128` |
| inbound consume | 378–391 | rdata matches programmed words | seq `:129-142` |
| empty / reverse path | 392–419 | empty rresp=2; inbound write → outbound read | seq `:143-162` |
| CG restore + IRQ | 434–449 | restore `0x1f000000`; `Mailbox IRQ source VIP toggled mask=0x02` | seq `:167` / test `:22` |
| cocotb result | 454–461 | `PASS` / `TESTS=1 PASS=1 FAIL=0 SKIP=0` | — |

</details>

## Not concluded

- Whether FIFO depth / illegal-access SLVERR behavior matches the SPEC properties a future card would require (O2) — Skill 3.
- Completeness against a feature_list — no inventory applies in STANDALONE-REQUEST.
- Any closure or PROVEN checker claim — MODE=NO-CHECKBOX forbids inventing checkers.

## Accepted waivers

| Finding | Rule | Where | Why | Approved by |
|---|---|---|---|---|
| — | — | — | none | — |
