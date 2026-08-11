---
schema: dv-quality/v1
artifact: testcase-grade
testcase: smc_mailbox_event_irq_test
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
- path: hw/sys/smc/dv/build/runs/20260806_094616__verilator__smc_mailbox_event_irq_test/smc_mailbox_event_irq_test/logs/smc_mailbox_event_irq_test.log
  sha256: 2e71a787c1b6ac84041c9644c5276f472a56115b24466e56e26c998023b58ff3
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
  artifact_ref: hw/sys/smc/dv/cocotb/seq_lib/smc_mailbox_irq_test_seq.py:13-20
  observed: >-
    Partial remaster: CLOCK_GATE_CONTROL and the outbound mailbox-0 base resolve via
    `smc_addr(...)`, but STATUS/ERROR_FLAGS/WIRQT/RIRQT still use hand-copied
    `base + 0x10/0x18/0x20/0x28`, MAILBOX_IRQEN remains the absolute literal
    `0xC001_8038`, and MAILBOX_CG_EN remains `1 << 1`. Generated PeakRDL symbols
    already exist
    (`SMC_TOP_SMC_MAILBOX_OUTBOUND_MAILBOX_0_{STATUS,ERROR_FLAGS,WIRQT,RIRQT,IRQEN}_BASE_ADDR`,
    `SMC_BASE_CONFIG__CLOCK_GATE_CONTROL__MAILBOX_CG_EN_bm`) and currently match the
    computed values (latent-rot class, not false-identity). Kept log shows the matching
    addresses (CLOCK_GATE `0xc0010018`, STATUS `0xc0018010`, … IRQEN `0xc0018038`).
  closure_condition: >-
    Import every proof-path mailbox register address and the MAILBOX_CG_EN mask from
    `smc_addr_map` / generated headers (per-register `*_BASE_ADDR` symbols and
    `MAILBOX_CG_EN_bm`), and stop using parallel numeric offsets/literals as the
    addressing source of truth.
  waived_by: null
- id: FIND-002
  tag: '[EXACT-EXPECTATION]'
  severity: Major
  artifact_ref: hw/sys/smc/dv/cocotb/seq_lib/smc_mailbox_irq_test_seq.py:64-75; hw/sys/smc/dv/cocotb/seq_lib/smc_mailbox_vip_utils.py:19-23
  observed: >-
    After enabling mailbox CG, STATUS/ERROR_FLAGS are read with `expected=None`,
    and the WRITE_READBACK loop writes patterns `0x5`/`0x6`/`0x7` to
    WIRQT/RIRQT/IRQEN then reads without an exact expectation (comment admits
    decode/response-only). Scoreboard therefore only asserts AXI `resp_ok` for
    those accesses. Kept log shows WIRQT write `0x5` then read `0x1` (L334–L341),
    RIRQT write `0x6` then read `0x1` (L348–L355), yet the test PASSes — activity/OKAY
    alone is not an exact contract for the programmed patterns. CLOCK_GATE enable
    and restore remain the only exact value compares (`accesses==19` is a count
    gate, not a data contract). Separately, the event-IRQ VIP path injects
    `mask=0x4` on `tb_sep_mailbox_interrupts` but only asserts
    `tb_mailbox_irq_any==1` (OR of `peripheral_interrupts[7:0]`), so bit-2
    identity is not checked; VIP/protocol details also claim "SMC sync IRQ"
    while the sampled handle is the mailbox aggregate, not `tb_sync_irq`.
  closure_condition: >-
    For each mailbox register on the proof path, assert an independently derived
    exact expected value (or documented side-effect/transform) on the post-write
    read; emit failure when DUT data mismatches. For the event-IRQ injection,
    assert the exact peripheral interrupt bit corresponding to `mask=0x4` (not
    only the OR aggregate), and align logged/VIP wording with the observed
    signal.
  waived_by: null
- id: FIND-003
  tag: '[NO-BLIND-DELAY-SYNC]'
  severity: Major
  artifact_ref: hw/sys/smc/dv/cocotb/seq_lib/smc_mailbox_vip_utils.py:14-28
  observed: >-
    `check_mailbox_irq_source` drives `tb_sep_mailbox_interrupts`, waits a fixed
    `ClockCycles(dut.clk_smc_i, 8)`, then samples `tb_mailbox_irq_any` for the
    low→high→low sequence. There is no edge/handshake wait with a bounded
    timeout; completion sync is a magic settle count. A late assert past 8 cycles
    fails incorrectly; an early pulse that drops before sample 8 can also miss.
    Kept log shows VIP toggle after CSR restore (L427) with no edge-wait evidence.
  closure_condition: >-
    Replace the fixed settle with an event/handshake wait on the IRQ aggregate
    (or documented CDC bound) that converts timeout into testcase failure with
    last-state diagnostics (`[TIMEOUT-MUST-FAIL]`), then assert the exact level.
  waived_by: null
waivers: []
recommendation: NOT-READY
---

# Grade Report — smc_mailbox_event_irq_test (standalone Layer 1)

**VERDICT: 0/0 PROVEN — NOT READY** (mode NO-CHECKBOX, no_contract_reason STANDALONE-REQUEST)

| Mode | Entry gate | Checkers | Findings | Recommendation |
|---|---|---|---|---|
| `NO-CHECKBOX` | — NOT-EVALUATED | 0/0 PROVEN | 🟠 3 Major | ⛔ NOT-READY |

> No approved checkbox card or parent plan record governs this testcase
> (`STANDALONE-REQUEST` / active-regression L1 wave). Layer 1 findings are the entire
> scope of this report. `NOT-READY` records the **absence of a closure claim, not a
> defect** in the test by itself.

## DELTA (re-audit vs prior grade `0/0 NOT-READY` on log `2e71a787…`)

| Prior id | Tag / grade | Status this round | Notes |
|---|---|---|---|
| FIND-001 | 🟠 `[ADDRESS-FROM-AUTHORITATIVE-MAP]` | OPEN — confirmed | Same residual hand offsets / `IRQEN` literal / `MAILBOX_CG_EN=1<<1`; values still match generated map (latent rot → Major) |
| FIND-002 | 🟠 `[EXACT-EXPECTATION]` | OPEN — confirmed | Same `expected=None` CSR path; log still shows WIRQT/RIRQT write≠read with PASS; event path still OR-collapses `mask=0x4` |
| FIND-003 | 🟠 `[NO-BLIND-DELAY-SYNC]` | OPEN — confirmed | VIP helper still fixed `ClockCycles(..., 8)` settle |
| waivers: [] | — | unchanged | Prior ledger empty; no signed `approved_by` to carry; none dropped |
| Kept log | `2e71a787…` | unchanged | same seed=1 PASS; model `2c815fa08277` |
| repository_revision | `c10b6d63…` | unchanged | same HEAD |
| seq / vip sha256 | `880465a6…` / `80ed41a1…` | unchanged | no remediation landed |

## Your to-do — 3 items (🟠 3 Major)

| # | Kind | Id | Severity / grade | Where |
|---|---|---|---|---|
| 1 | finding | FIND-001 | 🟠 Major | `smc_mailbox_irq_test_seq.py:13-20` |
| 2 | finding | FIND-002 | 🟠 Major | `smc_mailbox_irq_test_seq.py:64-75` / `smc_mailbox_vip_utils.py:19-23` |
| 3 | finding | FIND-003 | 🟠 Major | `smc_mailbox_vip_utils.py:14-28` |

<details>
<summary>1. FIND-001 — 🟠 Major <code>[ADDRESS-FROM-AUTHORITATIVE-MAP]</code> — residual hand-copied mailbox offsets / IRQEN / CG bit</summary>

- **Where:** `hw/sys/smc/dv/cocotb/seq_lib/smc_mailbox_irq_test_seq.py:13-20`
- **Observed:** CLOCK_GATE and mailbox-0 base now come from `smc_addr`, but STATUS/ERROR/WIRQT/RIRQT still use `base +` hand offsets, IRQEN is still `0xC001_8038`, and `MAILBOX_CG_EN=1<<1`. Per-register PeakRDL symbols and `MAILBOX_CG_EN_bm` already exist and currently match → Major (latent rot), not Blocking false-identity.
- **Closure:** Source every proof-path mailbox CSR address and the MAILBOX_CG_EN mask from generated symbols; drop parallel numeric offsets/literals.

</details>

<details>
<summary>2. FIND-002 — 🟠 Major <code>[EXACT-EXPECTATION]</code> — IRQ CSR write/read and event-bit check lack exact data/bit contract</summary>

- **Where:** `hw/sys/smc/dv/cocotb/seq_lib/smc_mailbox_irq_test_seq.py:64-75`; `hw/sys/smc/dv/cocotb/seq_lib/smc_mailbox_vip_utils.py:19-23`
- **Observed:** STATUS/ERROR_FLAGS reads and WIRQT/RIRQT/IRQEN write+read use `expected=None`; scoreboard only requires `resp_ok`. Log: WIRQT `0x5→0x1`, RIRQT `0x6→0x1` with PASS. CLOCK_GATE_CONTROL is the only exact value compare (`accesses==19` is a count gate, not a data contract). Event path injects `mask=0x4` then asserts only `tb_mailbox_irq_any==1` (OR collapse); VIP prose says sync IRQ.
- **Closure:** Assert independently derived exact post-write (or idle) values for each mailbox CSR on the proof path, and assert the exact interrupt bit for mask `0x4` so a wrong/stale datum or remapped bit fails the test.

</details>

<details>
<summary>3. FIND-003 — 🟠 Major <code>[NO-BLIND-DELAY-SYNC]</code> — fixed ClockCycles settle before IRQ sample</summary>

- **Where:** `hw/sys/smc/dv/cocotb/seq_lib/smc_mailbox_vip_utils.py:14-28`
- **Observed:** After each `tb_sep_mailbox_interrupts` drive, helper waits `ClockCycles(..., 8)` then samples `tb_mailbox_irq_any`. Log shows VIP toggle after CSR restore (L427) with no edge wait. Fixed settle stands in for completion handshake.
- **Closure:** Wait for the IRQ aggregate transition (bounded timeout that fails) before asserting the exact 0/1 level.

</details>

**Then:** owner remediates FIND-001/FIND-002/FIND-003 on the shared `smc_mailbox_irq_test_seq` / `smc_mailbox_vip_utils` proof path, re-keeps a PASS log, and re-invokes `/dv_test_audit smc_mailbox_event_irq_test`. Do not invent a card here (`STANDALONE-REQUEST`).

## All checkers

| Checker | Grade | Proof class | Covers | Findings |
|---|---|---|---|---|
| — | — | — | — | no card checkers (MODE=NO-CHECKBOX) |

### Layer 1 structural rule set

| Rule | Result |
|---|---|
| F1 fabricated verdict / backdoor write | ✅ clean — frontdoor SEP_IN SYS AXI via `SmcSysAxiItem`; SEP mailbox IRQ via TB pin `tb_sep_mailbox_interrupts` → DUT `sep_mailbox_interrupts_i`; observe `tb_mailbox_irq_any` (TB OR of hierarchical `peripheral_interrupts`); no force/deposit of success state |
| F2 can't-fail checker | ✅ clean — scoreboard `resp_ok` / `got==exp` (when set), driver timeout `AssertionError`, `assert accesses == 19`, and IRQ 0→1→0 asserts are reachable FAIL paths |
| E1 skip-to-pass | ✅ clean — no missing-handle skip-to-pass; AXI path must complete or raise; VIP asserts before protocol VIP record |
| E2 empty phase | ✅ clean — real AXI enable / status / write-read / restore (19 accesses) plus event IRQ source VIP toggle (`mask=0x4`) |
| S1 silent fail | ✅ clean — mismatch/timeout/`resp_ok` raise; sequence access-count assert; VIP level asserts |
| O1 checker disabled | ✅ clean — scoreboard SYS AXI path active (log checks #1–#19); protocol VIP recorded after VIP asserts |
| Phase-S obligations — L1 | 🟠 Major — FIND-001, FIND-002, FIND-003; timeouts fail on AXI; seed=1 logged; enrolled in `vplan_triplets.toml`; ROM/efuse preload is post-PASS bring-up trailer not CSR/IRQ golden |
| Phase-S obligations — L2 (needs the card) | — not evaluated |

## Evidence appendix

<details>
<summary>Kept log + code proof-path notes</summary>

- Implementation: `hw/sys/smc/dv/cocotb/tests/smc_mailbox_event_irq_test.py`
  sha256 `55f246f22b72cf50ef3429f881bd3565b019e441c7510e893e7daaa99d2c40f2`
- Sequence: `hw/sys/smc/dv/cocotb/seq_lib/smc_mailbox_irq_test_seq.py`
  sha256 `880465a610341f1a2b607117adbf90d57441c0a768b8c83277378ad77a97fefe`
- IRQ VIP helper: `hw/sys/smc/dv/cocotb/seq_lib/smc_mailbox_vip_utils.py`
  sha256 `80ed41a1e536712a3032c8020638f726a479e65e1721a362f779dc68a150e546`
- Scoreboard / driver (proof path): `smc_scoreboard._check_sys_axi`, `smc_sys_axi_agent._drive`
- Log: `hw/sys/smc/dv/build/runs/20260806_094616__verilator__smc_mailbox_event_irq_test/smc_mailbox_event_irq_test/logs/smc_mailbox_event_irq_test.log`
  sha256 `2e71a787c1b6ac84041c9644c5276f472a56115b24466e56e26c998023b58ff3` (matches claimed)
- Seed: 1 · simulator: verilator 5.050 2026-07-01 · model fingerprint `2c815fa08277`
- Cocotb summary: `TESTS=1 PASS=1 FAIL=0 SKIP=0` (L437–L439); no unexplained ERROR/FATAL/Traceback
- Stimulus: enable `MAILBOX_CG_EN` → read STATUS/ERROR_FLAGS → write/read WIRQT/RIRQT/IRQEN → restore zeros → restore CLOCK_GATE → `check_mailbox_irq_source(mask=0x4)` → protocol VIP record
- Exact value compares in log: CLOCK_GATE enable readback `exp=0x1f000002` (check #3) and restore `exp=0x1f000000` (check #19); mailbox IRQ CSR reads have `exp=None`
- Notable non-mirror reads: WIRQT write `0x5` / read `0x1` (L334–L341); RIRQT write `0x6` / read `0x1` (L348–L355); IRQEN write `0x7` / read `0x7` (L362–L369)
- IRQ VIP: `Mailbox IRQ source VIP toggled mask=0x04` (L427) after CSR restore; protocol VIP details claim "SMC sync IRQ"
- Map cross-check: generated STATUS/ERROR/WIRQT/RIRQT/IRQEN absolutes and `MAILBOX_CG_EN_bm=0x2` match hand offsets/literals used today
- Enrollment: `hw/sys/smc/dv/testlists/vplan_triplets.toml`
- Bring-up trailer: efuse/ROM hex preload after cocotb PASS; not used as CSR/IRQ golden on this proof path
- Entry gate / Layer 2 not evaluated (MODE=NO-CHECKBOX)
- Provenance: legacy (`test_author.run_id: unknown`)

</details>

<details>
<summary>Stimulus / sample cites (kept log <code>2e71a787…</code>)</summary>

| Step | Line (approx) | What the log shows | Impl |
|---|---|---|---|
| CG enable R/W/R | 293–313 | CLOCK_GATE `0x1f000000` → write `0x1f000002` → readback match | seq `:59-62` |
| STATUS / ERROR | 320–327 | STATUS `0x1`, ERROR_FLAGS `0x0`, `exp=None` | seq `:64-65` |
| WIRQT / RIRQT / IRQEN | 334–369 | write patterns; WIRQT/RIRQT read ≠ write; IRQEN mirrors `0x7` | seq `:67-71` |
| restore IRQ CSRs | 376–411 | write/read zeros | seq `:73-75` |
| restore CG | 418–425 | CLOCK_GATE restore `exp=0x1f000000` | seq `:77-80` |
| event IRQ inject | 427 | VIP toggled `mask=0x04` after low→high→low asserts | vip `:10-30` / test `:22` |
| cocotb result | 437–439 | `PASS` / `TESTS=1 PASS=1 FAIL=0 SKIP=0` | test `:19-29` |

</details>

## Not concluded

- Whether mailbox CSR decode/response plus SEP mailbox event-bit injection proves the SPEC properties a future card would require (O2) — Skill 3.
- Completeness against a feature_list — no inventory applies in STANDALONE-REQUEST.
- Any closure or PROVEN checker claim — MODE=NO-CHECKBOX forbids inventing checkers.

## Accepted waivers

| Finding | Rule | Where | Why | Approved by |
|---|---|---|---|---|
| — | — | — | none | — |
