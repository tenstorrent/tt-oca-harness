---
schema: dv-quality/v1
artifact: testcase-grade
testcase: smc_mailbox_multi_instance_test
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
- path: hw/sys/smc/dv/build/runs/20260806_094640__verilator__smc_mailbox_multi_instance_test/smc_mailbox_multi_instance_test/logs/smc_mailbox_multi_instance_test.log
  sha256: a53439db894e8a4af51f10595e58f56a87bc57d1f4f51c6a440dfc468197ec22
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
  artifact_ref: hw/sys/smc/dv/cocotb/seq_lib/smc_mailbox_multi_instance_test_seq.py:21-27
  observed: >-
    Partial remediation vs prior grade: CLOCK_GATE_CONTROL and outbound/inbound
    mailbox-0 *bases* now come from `smc_addr(...)`, but the proof path still
    hand-copies `_MAILBOX_STRIDE=0x1000`, `_STATUS_OFFSET=0x010`, and
    `MAILBOX_CG_EN = 1 << 1`. Generated PeakRDL absolute per-instance STATUS
    symbols and the field mask already exist and match the formula:
    `SMC_TOP_SMC_MAILBOX_{OUTBOUND,INBOUND}_MAILBOX_{N}_STATUS_BASE_ADDR`
    (e.g. OUT0 `0xC0018010` … OUT31 `0xC0037010`, IN0 `0xC0018810` … IN31
    `0xC0037810`) and
    `SMC_BASE_CONFIG__CLOCK_GATE_CONTROL__MAILBOX_CG_EN_bm=0x2` (latent-rot
    class, not false-identity). Kept log hits those absolute addresses
    (checks #3–#66).
  closure_condition: >-
    Address every STATUS via generated absolute
    `smc_addr("SMC_TOP_SMC_MAILBOX_{OUTBOUND,INBOUND}_MAILBOX_{N}_STATUS_BASE_ADDR")`
    (or an equivalent generated stride API), and import `MAILBOX_CG_EN` from the
    generated `_bm` mask (via `smc_addr_map` / `smc_base_config.h`). Drop
    parallel numeric stride/offset and `1 << 1` as the addressing source of truth.
  waived_by: null
- id: FIND-002
  tag: '[EXACT-EXPECTATION]'
  severity: Major
  artifact_ref: hw/sys/smc/dv/cocotb/seq_lib/smc_mailbox_multi_instance_test_seq.py:43-53
  observed: >-
    All 64 mailbox STATUS reads still call `csr_read(..., expected=None)`
    (default). Scoreboard therefore only asserts AXI `resp_ok` for those
    accesses; kept log shows every STATUS `rdata=0x1` with `exp=None`
    (checks #3–#66). CLOCK_GATE enable and restore are also write/read without
    an exact enable readback contract. Final `assert accesses == 67` and
    protocol-VIP `csr_accesses=67` prove issued count + OKAY completion, not an
    independently derived STATUS (or CG) value. Activity / OKAY alone is not an
    exact contract for the STATUS sweep the sequence claims to prove.
  closure_condition: >-
    For each mailbox STATUS on the proof path, assert an independently derived
    exact idle/reset (or SPEC-documented) expected value on the read; emit
    failure when DUT data mismatches. Optionally add an exact CLOCK_GATE_CONTROL
    enable/restore readback. Do not rely on OKAY + access count alone.
  waived_by: null
waivers: []
recommendation: NOT-READY
---

# Grade Report — smc_mailbox_multi_instance_test (standalone Layer 1 re-audit)

**VERDICT: 0/0 PROVEN — NOT READY** (mode NO-CHECKBOX, no_contract_reason STANDALONE-REQUEST)

| Mode | Entry gate | Checkers | Findings | Recommendation |
|---|---|---|---|---|
| `NO-CHECKBOX` | — NOT-EVALUATED | 0/0 PROVEN | 🟠 2 Major | ⛔ NOT-READY |

> No approved checkbox card or parent plan record governs this testcase
> (`STANDALONE-REQUEST` / active-regression L1 wave). Layer 1 findings are the entire
> scope of this report. `NOT-READY` records the **absence of a closure claim, not a
> defect** in the test by itself. Kept log is a sim **PASS** (seed 1):
> `TESTS=1 PASS=1 FAIL=0 SKIP=0`, `result.json status: PASS`, zero unexplained
> `ERROR`/`FATAL`/`Traceback` — Layer 2 entry is still not evaluated without a card.

## DELTA (re-audit vs prior grade `0/0 NOT-READY` on log `11ef135c…`)

| Item | Prior (log `11ef135c…`, PASS) | This audit (log `a53439db…`, PASS) |
|---|---|---|
| Verdict | 0/0 PROVEN — NOT READY | 0/0 PROVEN — NOT READY |
| Findings | 🟠 2 Major | 🟠 2 Major |
| Prior FIND-001 hand-copied absolute CSR / CG literals | open Major `[ADDRESS-FROM-AUTHORITATIVE-MAP]` (`0xC001_0018` / `0xC001_8000` / … / `1<<1`) | **partially remediaged, still open** as FIND-001 Major — CG + mailbox-0 bases via `smc_addr`; residual hand `_MAILBOX_STRIDE` / `_STATUS_OFFSET` / `MAILBOX_CG_EN=1<<1` while per-instance STATUS absolutes and `_bm` exist |
| Prior FIND-002 STATUS `expected=None` | open Major `[EXACT-EXPECTATION]` (checks #3–#66 `exp=None`) | **unchanged open** — still `expected=None` on all 64 STATUS reads; gate remains `accesses == 67` + AXI OKAY |
| Kept log | `11ef135c0159269e0987e421f43d39bc233d743afedeefb2ec30303e64a879e0` | `a53439db894e8a4af51f10595e58f56a87bc57d1f4f51c6a440dfc468197ec22` |
| Seq sha256 | `dca6ce34bff8caf03661642c1a34c9fc3f8fed61c7004c542e9fd8b90e79f72a` | `b75fd8bfa5e9ba04fae38c5e7d6ff0805c81df0a36bb54ca7301b33b4fe63d37` |
| Repo rev | `2ecc7b227e3926b253c65b5aac21239eec24ba5f` | `c10b6d63e0b3377f8e2fa38c138e2ea72cae92c7` |
| Auditor run_id | `cursor/grok/4.5` | `cursor/grok/4.5-reaudit-20260806` |
| Waivers carried | none signed (`waivers: []`) | none (nothing to drop; no signed entries) |

## Your to-do — 2 items (🟠 2 Major)

| # | Kind | Id | Severity / grade | Where |
|---|---|---|---|---|
| 1 | finding | FIND-001 | 🟠 Major | `smc_mailbox_multi_instance_test_seq.py:21-27` |
| 2 | finding | FIND-002 | 🟠 Major | `smc_mailbox_multi_instance_test_seq.py:43-53` |

<details>
<summary>1. FIND-001 — 🟠 Major <code>[ADDRESS-FROM-AUTHORITATIVE-MAP]</code> — residual hand-copied stride / STATUS offset / MAILBOX_CG_EN</summary>

- **Where:** `hw/sys/smc/dv/cocotb/seq_lib/smc_mailbox_multi_instance_test_seq.py:21-27`
- **Observed:** CLOCK_GATE and mailbox-0 bases now import via `smc_addr`, but STATUS addresses are still `base + i*0x1000 + 0x010` and `MAILBOX_CG_EN = 1 << 1`. Generated per-instance STATUS absolutes and `MAILBOX_CG_EN_bm=0x2` exist and currently match (latent rot). Log hits `0xc0018010`…`0xc0037010` and `0xc0018810`…`0xc0037810`.
- **Closure:** Source every STATUS address and the MAILBOX_CG_EN mask from generated symbols; drop parallel stride/offset/`1<<1` as truth.

</details>

<details>
<summary>2. FIND-002 — 🟠 Major <code>[EXACT-EXPECTATION]</code> — STATUS sweep lacks exact data check</summary>

- **Where:** `hw/sys/smc/dv/cocotb/seq_lib/smc_mailbox_multi_instance_test_seq.py:43-53`
- **Observed:** All 64 STATUS reads use `expected=None`; scoreboard only requires `resp_ok`. Log: every STATUS `rdata=0x1` with `exp=None` (checks #3–#66). Gate is `accesses == 67` + AXI OKAY, not a STATUS value contract.
- **Closure:** Assert independently derived exact STATUS (and preferably CG readback) values so a wrong/stale datum fails the test.

</details>

**Then:** owner remediates FIND-001/FIND-002 on `smc_mailbox_multi_instance_test_seq`, re-keeps a PASS log, and re-invokes `/dv_test_audit smc_mailbox_multi_instance_test`. Do not invent a card here (`STANDALONE-REQUEST`).

## All checkers

| Checker | Grade | Proof class | Covers | Findings |
|---|---|---|---|---|
| — | — | — | — | no card checkers (MODE=NO-CHECKBOX) |

### Layer 1 structural rule set

| Rule | Result |
|---|---|
| F1 fabricated verdict / backdoor write | ✅ clean — frontdoor SEP_IN SYS AXI via `SmcSysAxiItem`; no force/deposit on CSR path; ROM/efuse preload is post-PASS bring-up trailer |
| F2 can't-fail checker | ✅ clean — scoreboard `resp_ok` and driver timeout `AssertionError` are reachable; sequence intentionally avoids `csr_read_bounded`; `assert accesses == 67` can fail |
| E1 skip-to-pass | ✅ clean — no missing-handle skip-to-pass; AXI path must complete or raise; comment forbids bounded-read vacuity |
| E2 empty phase | ✅ clean — real CG enable + 32 out + 32 in STATUS + CG restore (67 accesses logged) |
| S1 silent fail | ✅ clean — mismatch/timeout/`resp_ok` raise; sequence access-count assert |
| O1 checker disabled | ✅ clean — scoreboard SYS AXI path active (log checks #1–#67) |
| Phase-S obligations — L1 | 🟠 Major — FIND-001, FIND-002; timeouts fail; seed logged; enrolled in `p1_coverage_gap_r2.toml`; ROM/efuse preload is post-PASS trailer not CSR golden |
| Phase-S obligations — L2 (needs the card) | — not evaluated |

## Evidence appendix

<details>
<summary>Kept log + code proof-path notes</summary>

- Implementation: `hw/sys/smc/dv/cocotb/tests/smc_mailbox_multi_instance_test.py`
  sha256 `5e33d5298df9f88992533dce16f9b16b6033fd438c2cd56c8b667090fb37f846`
- Sequence: `hw/sys/smc/dv/cocotb/seq_lib/smc_mailbox_multi_instance_test_seq.py`
  sha256 `b75fd8bfa5e9ba04fae38c5e7d6ff0805c81df0a36bb54ca7301b33b4fe63d37`
- Scoreboard / driver (proof path): `smc_scoreboard._check_sys_axi`, `smc_sys_axi_agent._drive`
- Authoritative map available: `hw/sys/smc/regs/gen/c/smc_addr.h` +
  `blocks/smc_base_config.h` via `seq_lib/smc_addr_map.py` (bases used; per-instance
  STATUS absolutes / `_bm` not yet)
- Log: `hw/sys/smc/dv/build/runs/20260806_094640__verilator__smc_mailbox_multi_instance_test/smc_mailbox_multi_instance_test/logs/smc_mailbox_multi_instance_test.log`
  sha256 `a53439db894e8a4af51f10595e58f56a87bc57d1f4f51c6a440dfc468197ec22`
  (verified via `manifest.py hash-file`; matches recomputed sha256)
- Seed: 1 · simulator: verilator 5.050 2026-07-01 · model fingerprint `2c815fa08277`
- Repo rev: `c10b6d63e0b3377f8e2fa38c138e2ea72cae92c7`
- `result.json`: `status: PASS`, `exit_code: 0`, cocotb summary L772–L774:
  `TESTS=1 PASS=1 FAIL=0 SKIP=0`
- Stimulus: enable `MAILBOX_CG_EN` on CLOCK_GATE_CONTROL → read STATUS of
  outbound[0..31] then inbound[0..31] → restore CLOCK_GATE; final
  `assert accesses == 67`
- Exact value compares in log: none on STATUS (`exp=None` for checks #3–#66);
  CG enable is write of OR'd save value without expected readback; restore write
  check #67 also `exp=None`
- Protocol VIP: `mailbox:smc_mailbox_multi_instance_test … csr_accesses=67 timeouts=0 passed=True`
- Enrollment: `hw/sys/smc/dv/testlists/p1_coverage_gap_r2.toml`
- Bring-up trailer: efuse/ROM hex preload after cocotb PASS; not used as CSR golden
  on this proof path
- Entry gate / Layer 2 not evaluated (MODE=NO-CHECKBOX)
- Provenance: legacy (`test_author.run_id: unknown`); auditor
  `run_id: cursor/grok/4.5-reaudit-20260806`

</details>

<details>
<summary>Stimulus / sample cites (kept log <code>a53439db…</code>)</summary>

| Step | Line (approx) | What the log shows | Impl |
|---|---|---|---|
| CG enable R/W | 293–306 | CLOCK_GATE read `0x1f000000` → write `0x1f000002` | seq `:34-36` |
| OUT STATUS 0..31 | 313–530 | `0xc0018010`…`0xc0037010`, `rdata=0x1`, `exp=None` | seq `:43-45` |
| IN STATUS 0..31 | 537–754 | `0xc0018810`…`0xc0037810`, `rdata=0x1`, `exp=None` | seq `:46-48` |
| restore CG | 761 | CLOCK_GATE write `0x1f000000` (check #67) | seq `:49-50` |
| access gate / VIP | 763–764 | `csr_accesses=67 timeouts=0` + protocol VIP check | seq `:52-54` |
| cocotb result | 772–774 | `PASS` / `TESTS=1 PASS=1 FAIL=0 SKIP=0` | test `:19-28` |

</details>

## Not concluded

- Whether the 32+32 STATUS decode sweep proves the SPEC properties a future card would require (O2) — Skill 3.
- Completeness against a feature_list — no inventory applies in STANDALONE-REQUEST.
- Any closure or PROVEN checker claim — MODE=NO-CHECKBOX forbids inventing checkers.

## Accepted waivers

| Finding | Rule | Where | Why | Approved by |
|---|---|---|---|---|
| — | — | — | none | — |
