---
schema: dv-quality/v1
artifact: testcase-grade
testcase: smc_mailbox_inbound_test
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
- path: hw/sys/smc/dv/build/runs/20260806_094634__verilator__smc_mailbox_inbound_test/smc_mailbox_inbound_test/logs/smc_mailbox_inbound_test.log
  sha256: 4c386cf0229a8bddd6d9bf61c24e14a012b8fdebd6a850943e1083e376ee93fa
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
  artifact_ref: hw/sys/smc/dv/cocotb/seq_lib/smc_mailbox_inbound_test_seq.py:15-20
  observed: >-
    Partial remmediation vs prior grade: CLOCK_GATE_CONTROL and the inbound
    mailbox-0 *base* now come from `smc_addr(...)`, but the proof path still
    hand-copies register offsets and the CG bit (`MAILBOX_CG_EN = 1 << 1`,
    `BASE + 0x10` / `+ 0x18` / `+ 0x38`). Generated PeakRDL absolute symbols
    and the field mask already exist and match the computed values:
    `SMC_TOP_SMC_MAILBOX_INBOUND_MAILBOX_0_{STATUS,ERROR_FLAGS,IRQEN}_BASE_ADDR`
    (`0xC0018810` / `0xC0018818` / `0xC0018838`) and
    `SMC_BASE_CONFIG__CLOCK_GATE_CONTROL__MAILBOX_CG_EN_bm=0x2` (latent-rot
    class, not false-identity). Kept log hits those absolute addresses
    (checks #3–#5).
  closure_condition: >-
    Address STATUS / ERROR_FLAGS / IRQEN via their generated absolute
    `smc_addr("SMC_TOP_SMC_MAILBOX_INBOUND_MAILBOX_0_*_BASE_ADDR")` symbols
    (not base+hand offset), and import `MAILBOX_CG_EN` from the generated
    `_bm` mask (via `smc_addr_map` / `smc_base_config.h`). Drop parallel
    numeric offsets and `1 << 1` as the addressing source of truth.
  waived_by: null
waivers: []
recommendation: NOT-READY
---

# Grade Report — smc_mailbox_inbound_test (standalone Layer 1 re-audit)

**VERDICT: 0/0 PROVEN — NOT READY** (mode NO-CHECKBOX, no_contract_reason STANDALONE-REQUEST)

| Mode | Entry gate | Checkers | Findings | Recommendation |
|---|---|---|---|---|
| `NO-CHECKBOX` | — NOT-EVALUATED | 0/0 PROVEN | 🟠 1 Major | ⛔ NOT-READY |

> No approved checkbox card or parent plan record governs this testcase
> (`STANDALONE-REQUEST` / active-regression L1 wave). Layer 1 findings are the entire
> scope of this report. `NOT-READY` records the **absence of a closure claim, not a
> defect** in the test by itself. Kept log is a sim **PASS** (seed 1):
> `TESTS=1 PASS=1 FAIL=0 SKIP=0`, `result.json status: PASS`, zero unexplained
> `ERROR`/`FATAL`/`Traceback` — Layer 2 entry is still not evaluated without a card.

## DELTA (re-audit vs prior grade `0/0 NOT-READY` on log `ceb03e8c…`)

| Item | Prior (log `ceb03e8c…`, PASS) | This audit (log `4c386cf0…`, PASS) |
|---|---|---|
| Verdict | 0/0 PROVEN — NOT READY | 0/0 PROVEN — NOT READY |
| Findings | 🟠 1 Major | 🟠 1 Major |
| Prior FIND-001 hand-copied absolute CSR / CG literals | open Major `[ADDRESS-FROM-AUTHORITATIVE-MAP]` (`0xC001_0018` / `0xC001_8810` / … / `1<<1`) | **partially remediaged, still open** as FIND-001 Major — bases via `smc_addr`; residual hand offsets `+0x10/+0x18/+0x38` and `MAILBOX_CG_EN=1<<1` while absolute STATUS/ERROR/IRQEN symbols and `_bm` exist |
| Exact STATUS/ERROR/IRQEN expects | present (`exp=0x1/0x0/0x0`) | unchanged — still present (checks #3–#5) |
| Kept log | `ceb03e8c5ca3b49aa0ffae64249773fe3d3c4c0cefccb12194516f2d8ac28839` | `4c386cf0229a8bddd6d9bf61c24e14a012b8fdebd6a850943e1083e376ee93fa` |
| Seq sha256 | `91854541efca8c238291c47a56c7950582ec92791cf6288d0c19b78fc699dbb7` | `dbbbae1f651929eba92e22987b31f228088a9d933a65a578dd83e45f1d3971c3` |
| Repo rev | `2ecc7b227e3926b253c65b5aac21239eec24ba5f` | `c10b6d63e0b3377f8e2fa38c138e2ea72cae92c7` |
| Auditor run_id | `cursor/grok/4.5` | `cursor/grok/4.5-reaudit-20260806` |
| Waivers carried | none signed (`waivers: []`) | none (nothing to drop; no signed entries) |

## Your to-do — 1 item (🟠 1 Major)

| # | Kind | Id | Severity / grade | Where |
|---|---|---|---|---|
| 1 | finding | FIND-001 | 🟠 Major | `smc_mailbox_inbound_test_seq.py:15-20` |

<details>
<summary>1. FIND-001 — 🟠 Major <code>[ADDRESS-FROM-AUTHORITATIVE-MAP]</code> — residual hand-copied inbound offsets / MAILBOX_CG_EN</summary>

- **Where:** `hw/sys/smc/dv/cocotb/seq_lib/smc_mailbox_inbound_test_seq.py:15-20`
- **Observed:** Base addresses import via `smc_addr`, but STATUS/ERROR_FLAGS/IRQEN still use `BASE + 0x10/0x18/0x38` and `MAILBOX_CG_EN = 1 << 1`. Generated absolute symbols and `MAILBOX_CG_EN_bm=0x2` exist and currently match (latent rot). Log hits `0xc0018810` / `8818` / `8838`.
- **Closure:** Use generated absolute STATUS/ERROR_FLAGS/IRQEN symbols and the generated CG `_bm` mask; drop hand offsets and `1 << 1`.

</details>

**Then:** owner remediates FIND-001 residual addressing on `smc_mailbox_inbound_test_seq`, re-keeps a PASS log, and re-invokes `/dv_test_audit smc_mailbox_inbound_test`. Do not invent a card here (`STANDALONE-REQUEST`).

## All checkers

| Checker | Grade | Proof class | Covers | Findings |
|---|---|---|---|---|
| — | — | — | — | no card checkers (MODE=NO-CHECKBOX) |

### Layer 1 structural rule set

| Rule | Result |
|---|---|
| F1 fabricated verdict / backdoor write | ✅ clean — frontdoor SEP_IN SYS AXI via `SmcSysAxiItem`; no force/deposit on CSR path; CG restore uses previously read value |
| F2 can't-fail checker | ✅ clean — scoreboard `got==exp` for STATUS/ERROR_FLAGS/IRQEN; `assert accesses == 6` and driver timeout `AssertionError` are reachable |
| E1 skip-to-pass | ✅ clean — no missing-handle skip-to-pass; AXI path must complete or raise |
| E2 empty phase | ✅ clean — real CG enable → inbound CSR reads → CG restore (6 accesses logged) |
| S1 silent fail | ✅ clean — scoreboard mismatch/`resp_ok` raise; sequence access-count assert |
| O1 checker disabled | ✅ clean — scoreboard SYS AXI path active (log checks #1–#6) |
| Phase-S obligations — L1 | 🟠 Major — FIND-001 residual offsets/`MAILBOX_CG_EN`; exact expected values on inbound STATUS/ERROR/IRQEN; timeouts fail; seed logged; enrolled in `p1_coverage_gap.toml`; ROM/efuse preload is post-PASS bring-up trailer not CSR golden |
| Phase-S obligations — L2 (needs the card) | — not evaluated |

## Evidence appendix

<details>
<summary>Kept log + code proof-path notes</summary>

- Implementation: `hw/sys/smc/dv/cocotb/tests/smc_mailbox_inbound_test.py`
  sha256 `94d48de50369b605d15299c21534372f41a2e6c4cf9637b310f66857e78809dc`
- Sequence: `hw/sys/smc/dv/cocotb/seq_lib/smc_mailbox_inbound_test_seq.py`
  sha256 `dbbbae1f651929eba92e22987b31f228088a9d933a65a578dd83e45f1d3971c3`
- Scoreboard / driver (proof path): `smc_scoreboard._check_sys_axi`, `smc_sys_axi_agent._drive`
- Authoritative map available: `hw/sys/smc/regs/gen/c/smc_addr.h` +
  `blocks/smc_base_config.h` via `seq_lib/smc_addr_map.py` (bases used; per-reg
  absolute symbols / `_bm` not yet)
- Log: `hw/sys/smc/dv/build/runs/20260806_094634__verilator__smc_mailbox_inbound_test/smc_mailbox_inbound_test/logs/smc_mailbox_inbound_test.log`
  sha256 `4c386cf0229a8bddd6d9bf61c24e14a012b8fdebd6a850943e1083e376ee93fa`
  (verified via `manifest.py hash-file`; matches invoker hint)
- Seed: 1 · simulator: verilator 5.050 2026-07-01 · model fingerprint `2c815fa08277`
- Repo rev: `c10b6d63e0b3377f8e2fa38c138e2ea72cae92c7`
- `result.json`: `status: PASS`, `exit_code: 0`, cocotb summary L342–L348:
  `TESTS=1 PASS=1 FAIL=0 SKIP=0`
- Stimulus: enable `MAILBOX_CG_EN` on CLOCK_GATE_CONTROL → read inbound STATUS
  (`exp=0x1`) / ERROR_FLAGS (`exp=0x0`) / IRQEN (`exp=0x0`) → restore CLOCK_GATE;
  final `assert accesses == 6`
- Exact value compares in log: STATUS check #3 `exp=0x1`, ERROR_FLAGS #4 `exp=0x0`,
  IRQEN #5 `exp=0x0`; CG R/W have `exp=None` (setup/restore)
- STATUS=0x1 documented as REGRESSION-LOCK (FIFO-empty wire vs RDL `empty` reset 0);
  ERROR/IRQEN anchored to RDL reset constants
- AXI monitor trailer: `4 R beats, 2 B resps; R-resp tally OKAY=4; 0 errors` (L339)
- Enrollment: `hw/sys/smc/dv/testlists/p1_coverage_gap.toml`
- Bring-up trailer: efuse/ROM hex preload after cocotb PASS; not used as CSR golden
  on this proof path
- Entry gate / Layer 2 not evaluated (MODE=NO-CHECKBOX)
- Provenance: legacy (`test_author.run_id: unknown`); auditor
  `run_id: cursor/grok/4.5-reaudit-20260806`

</details>

<details>
<summary>Stimulus / sample cites (kept log <code>4c386cf0…</code>)</summary>

| Step | Line (approx) | What the log shows | Impl |
|---|---|---|---|
| CG save / enable | 280–307 | CLOCK_GATE read `0x1f000000` → write `0x1f000002` | seq `:25-27` |
| STATUS | 308–314 | inbound STATUS `0x1` `exp=0x1` ok | seq `:34-35` |
| ERROR_FLAGS | 315–321 | ERROR_FLAGS `0x0` `exp=0x0` ok | seq `:36-37` |
| IRQEN | 322–328 | IRQEN `0x0` `exp=0x0` ok | seq `:38-39` |
| CG restore | 329–335 | CLOCK_GATE write restore `0x1f000000` | seq `:40` |
| cocotb result | 342–348 | `PASS` / `TESTS=1 PASS=1 FAIL=0 SKIP=0` | seq `:41` |

</details>

## Not concluded

- Whether inbound mailbox STATUS/ERROR/IRQEN precheck proves the SPEC properties a future card would require (O2) — Skill 3.
- Completeness against a feature_list — no inventory applies in STANDALONE-REQUEST.
- Any closure or PROVEN checker claim — MODE=NO-CHECKBOX forbids inventing checkers.

## Accepted waivers

| Finding | Rule | Where | Why | Approved by |
|---|---|---|---|---|
| — | — | — | none | — |
