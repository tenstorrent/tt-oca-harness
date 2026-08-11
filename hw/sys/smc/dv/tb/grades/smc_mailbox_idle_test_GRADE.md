---
schema: dv-quality/v1
artifact: testcase-grade
testcase: smc_mailbox_idle_test
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
- path: hw/sys/smc/dv/build/runs/20260806_094550__verilator__smc_mailbox_idle_test/smc_mailbox_idle_test/logs/smc_mailbox_idle_test.log
  sha256: 8e8b8d837c5c810a321d8bd31d4a4822d39d145a0f196e51102f95ef7009345d
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
    Partial remediation since prior grade: CLOCK_GATE_CONTROL and mailbox
    STATUS/ERROR_FLAGS/WIRQT/RIRQT now resolve via `smc_addr(...)` (base or
    base+hand offset). Remaining proof-path addressing is still not fully
    symbol-sourced: `MAILBOX_IRQEN = 0xC001_8038` is a bare numeric literal;
    STATUS/ERROR_FLAGS/WIRQT/RIRQT use hand-copied `+ 0x10`/`+ 0x18`/`+ 0x20`/
    `+ 0x28` despite generated per-register symbols
    (`SMC_TOP_SMC_MAILBOX_OUTBOUND_MAILBOX_0_{STATUS,ERROR_FLAGS,WIRQT,RIRQT,IRQEN}_BASE_ADDR`);
    `MAILBOX_CG_EN = 1 << 1` ignores
    `SMC_BASE_CONFIG__CLOCK_GATE_CONTROL__MAILBOX_CG_EN_bm` (loadable via
    `_field_mask` / `smc_addr_map`, as other CG enables already are). Current
    values match the generated map (latent-rot class, not false-identity).
  closure_condition: >-
    Import every proof-path mailbox register address and the MAILBOX_CG_EN mask
    from `smc_addr` / generated field headers; drop parallel numeric constants
    and hand-added offsets as the addressing source of truth.
  waived_by: null
- id: FIND-002
  tag: '[EXACT-EXPECTATION]'
  severity: Major
  artifact_ref: hw/sys/smc/dv/cocotb/seq_lib/smc_mailbox_irq_test_seq.py:64-75
  observed: >-
    After enabling mailbox CG, STATUS/ERROR_FLAGS are read with `expected=None`,
    and the WRITE_READBACK loop writes patterns `0x5`/`0x6`/`0x7` to
    WIRQT/RIRQT/IRQEN then reads without an exact expectation (comment admits
    decode/response-only). Scoreboard therefore only asserts AXI `resp_ok` for
    those accesses. Kept log shows WIRQT write `0x5` then read `0x1`, RIRQT write
    `0x6` then read `0x1`, yet the test PASSes — activity/OKAY alone is not an
    exact contract for the programmed patterns.
  closure_condition: >-
    For each mailbox register on the proof path, assert an independently derived
    exact expected value (or documented side-effect/transform) on the post-write
    read; emit failure when DUT data mismatches. Do not rely on OKAY + access
    count alone for WIRQT/RIRQT/IRQEN/STATUS/ERROR_FLAGS.
  waived_by: null
waivers: []
recommendation: NOT-READY
---

# Grade Report — smc_mailbox_idle_test (standalone Layer 1)

**VERDICT: 0/0 PROVEN — NOT READY** (mode NO-CHECKBOX, no_contract_reason STANDALONE-REQUEST)

| Mode | Entry gate | Checkers | Findings | Recommendation |
|---|---|---|---|---|
| `NO-CHECKBOX` | — NOT-EVALUATED | 0/0 PROVEN | 🟠 2 Major | ⛔ NOT-READY |

> No approved checkbox card or parent plan record governs this testcase
> (`STANDALONE-REQUEST` / active-regression L1 wave). Layer 1 findings are the entire
> scope of this report. `NOT-READY` records the **absence of a closure claim, not a
> defect** in the test by itself.

## DELTA (re-audit vs prior grade `0/0 NOT-READY` on log `970cfa7c…`)

| Item | Prior (log `970cfa7c…`, PASS) | This audit (log `8e8b8d83…`, PASS) |
|---|---|---|
| Verdict | 0/0 PROVEN — NOT READY | 0/0 PROVEN — NOT READY |
| Findings | 🟠 2 Major | 🟠 2 Major |
| FIND-001 `[ADDRESS-FROM-AUTHORITATIVE-MAP]` | open — all CG/mailbox CSR addresses + `MAILBOX_CG_EN` hand-copied literals | narrowed, still open — CG + STATUS/ERROR/WIRQT/RIRQT via `smc_addr`; IRQEN literal, hand offsets, `1<<1` CG bit remain (match map → Major) |
| FIND-002 `[EXACT-EXPECTATION]` | open — IRQ CSR write/read `expected=None`; WIRQT/RIRQT non-mirror PASS | still open — same `exp=None` path; WIRQT `0x5→0x1`, RIRQT `0x6→0x1` on new log |
| Sequence sha256 | `444f2ba3…` | `880465a6…` (partial address-map migration) |
| Kept log | `970cfa7c591da0a54d44909ade4915388804bfc0141a66f319114e864a7502b2` | `8e8b8d837c5c810a321d8bd31d4a4822d39d145a0f196e51102f95ef7009345d` |
| Repo / model | `2ecc7b22…` / `2c815fa08277` | `c10b6d63…` / `2c815fa08277` |
| Waivers carried | none signed (`waivers: []`) | none (nothing to drop; no signed entries) |

## Your to-do — 2 items (🟠 2 Major)

| # | Kind | Id | Severity / grade | Where |
|---|---|---|---|---|
| 1 | finding | FIND-001 | 🟠 Major | `smc_mailbox_irq_test_seq.py:13-20` |
| 2 | finding | FIND-002 | 🟠 Major | `smc_mailbox_irq_test_seq.py:64-75` |

<details>
<summary>1. FIND-001 — 🟠 Major <code>[ADDRESS-FROM-AUTHORITATIVE-MAP]</code> — remaining IRQEN literal / offsets / CG bit</summary>

- **Where:** `hw/sys/smc/dv/cocotb/seq_lib/smc_mailbox_irq_test_seq.py:13-20`
- **Observed:** Partial map migration: CLOCK_GATE + STATUS/ERROR/WIRQT/RIRQT use `smc_addr`. Still hand-sourced: `MAILBOX_IRQEN=0xC001_8038`, `+0x10/+0x18/+0x20/+0x28` offsets (per-reg symbols exist), `MAILBOX_CG_EN=1<<1` (bm symbol exists). Values match → Major (latent rot), not Blocking false-identity.
- **Closure:** Source every proof-path mailbox address and MAILBOX_CG_EN mask from generated symbols; drop parallel literals/offsets as truth.

</details>

<details>
<summary>2. FIND-002 — 🟠 Major <code>[EXACT-EXPECTATION]</code> — IRQ CSR write/read lacks exact data check</summary>

- **Where:** `hw/sys/smc/dv/cocotb/seq_lib/smc_mailbox_irq_test_seq.py:64-75`
- **Observed:** STATUS/ERROR_FLAGS reads and WIRQT/RIRQT/IRQEN write+read use `expected=None`; scoreboard only requires `resp_ok`. Log: WIRQT `0x5→0x1`, RIRQT `0x6→0x1` with PASS. CLOCK_GATE_CONTROL is the only exact value compare (`accesses==19` is a count gate, not a data contract).
- **Closure:** Assert independently derived exact post-write (or idle) values for each mailbox CSR on the proof path so a wrong/stale datum fails the test.

</details>

**Then:** owner remediates FIND-001/FIND-002 on the shared `smc_mailbox_irq_test_seq` proof path, re-keeps a PASS log, and re-invokes `/dv_test_audit smc_mailbox_idle_test`. Do not invent a card here (`STANDALONE-REQUEST`).

## All checkers

| Checker | Grade | Proof class | Covers | Findings |
|---|---|---|---|---|
| — | — | — | — | no card checkers (MODE=NO-CHECKBOX) |

### Layer 1 structural rule set

| Rule | Result |
|---|---|
| F1 fabricated verdict / backdoor write | ✅ clean — frontdoor SEP_IN SYS AXI via `SmcSysAxiItem`; CLOCK_GATE expected is TB-programmed value vs DUT `rdata`; no force/deposit on CSR path |
| F2 can't-fail checker | ✅ clean — scoreboard `resp_ok` / `got==exp` (when set) and driver timeout `AssertionError` are reachable; `assert accesses == 19` can fail |
| E1 skip-to-pass | ✅ clean — no missing-handle skip-to-pass; AXI path must complete or raise |
| E2 empty phase | ✅ clean — real AXI enable / status / write-read / restore sequence (19 accesses logged) |
| S1 silent fail | ✅ clean — mismatch/timeout/`resp_ok` raise; sequence access-count assert |
| O1 checker disabled | ✅ clean — scoreboard SYS AXI path active (log checks #1–#19) |
| Phase-S obligations — L1 | 🟠 Major — FIND-001, FIND-002; timeouts fail; seed logged; enrolled in `batch_b.toml` / `all.toml`; ROM/efuse preload is post-PASS bring-up trailer not CSR golden |
| Phase-S obligations — L2 (needs the card) | — not evaluated |

## Evidence appendix

<details>
<summary>Kept log + code proof-path notes</summary>

- Implementation: `hw/sys/smc/dv/cocotb/tests/smc_mailbox_idle_test.py`
  sha256 `b4a17d0ed323ae3614784b02ad7cfc6c483bb131193005dfdfbf98e3918a1bde`
- Sequence (actual): `hw/sys/smc/dv/cocotb/seq_lib/smc_mailbox_irq_test_seq.py`
  sha256 `880465a610341f1a2b607117adbf90d57441c0a768b8c83277378ad77a97fefe`
  (no `smc_mailbox_idle_test_seq.py`; P0 alias reuses the IRQ seq)
- Scoreboard / driver (proof path): `smc_scoreboard._check_sys_axi`, `smc_sys_axi_agent._drive`
- Log: `hw/sys/smc/dv/build/runs/20260806_094550__verilator__smc_mailbox_idle_test/smc_mailbox_idle_test/logs/smc_mailbox_idle_test.log`
  sha256 `8e8b8d837c5c810a321d8bd31d4a4822d39d145a0f196e51102f95ef7009345d` (matches claimed)
- Seed: 1 · simulator: verilator 5.050 2026-07-01 · model fingerprint `2c815fa08277`
- Cocotb summary: `TESTS=1 PASS=1 FAIL=0 SKIP=0` (L431–L435)
- Stimulus: enable `MAILBOX_CG_EN` on CLOCK_GATE_CONTROL → read STATUS/ERROR_FLAGS → write/read WIRQT/RIRQT/IRQEN → restore zeros → restore CLOCK_GATE; final `assert accesses == 19`
- Exact value compares in log: CLOCK_GATE enable readback `exp=0x1f000002` (check #3) and restore `exp=0x1f000000` (check #19); mailbox IRQ CSR reads have `exp=None`
- Notable non-mirror reads: WIRQT write `0x5` / read `0x1` (L334–L341); RIRQT write `0x6` / read `0x1` (L348–L355); IRQEN write `0x7` / read `0x7` (L362–L369)
- AXI monitor trailer: `11 R beats, 8 B resps; R-resp tally OKAY=11; 0 errors` (L426)
- Enrollment: `hw/sys/smc/dv/testlists/batch_b.toml`, `all.toml`
- Bring-up trailer: efuse/ROM hex preload after cocotb PASS; not used as CSR golden on this proof path
- Entry gate / Layer 2 not evaluated (MODE=NO-CHECKBOX)
- Provenance: legacy (`test_author.run_id: unknown`)

</details>

<details>
<summary>Stimulus / sample cites (kept log <code>8e8b8d83…</code>)</summary>

| Step | Line (approx) | What the log shows | Impl |
|---|---|---|---|
| CG enable R/W/R | 293–313 | CLOCK_GATE `0x1f000000` → write `0x1f000002` → readback match | seq `:59-62` |
| STATUS / ERROR | 320–327 | STATUS `0x1`, ERROR_FLAGS `0x0`, `exp=None` | seq `:64-65` |
| WIRQT / RIRQT / IRQEN | 334–369 | write patterns; WIRQT/RIRQT read ≠ write; IRQEN mirrors `0x7` | seq `:67-71` |
| restore IRQ CSRs | 376–411 | write/read zeros | seq `:73-75` |
| restore CG | 418–425 | CLOCK_GATE restore `exp=0x1f000000` | seq `:77-80` |
| cocotb result | 431–435 | `PASS` / `TESTS=1 PASS=1 FAIL=0 SKIP=0` | seq `:81` |

</details>

## Not concluded

- Whether mailbox CSR decode/response (and the idle/proxy alias naming) proves the SPEC properties a future card would require (O2) — Skill 3.
- Completeness against a feature_list — no inventory applies in STANDALONE-REQUEST.
- Any closure or PROVEN checker claim — MODE=NO-CHECKBOX forbids inventing checkers.

## Accepted waivers

| Finding | Rule | Where | Why | Approved by |
|---|---|---|---|---|
| — | — | — | none | — |
