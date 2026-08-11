---
schema: dv-quality/v1
artifact: testcase-grade
testcase: smc_mailbox_field_sweep_test
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
- path: hw/sys/smc/dv/build/runs/20260806_094641__verilator__smc_mailbox_field_sweep_test/smc_mailbox_field_sweep_test/logs/smc_mailbox_field_sweep_test.log
  sha256: 11a7bc1b87f0fcfffa44be965cf80a82659d3caf60bf5cf4e70e10421af4844c
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
  artifact_ref: hw/sys/smc/dv/cocotb/seq_lib/smc_mailbox_field_sweep_test_seq.py:23-35
  observed: >-
    Partial remediation vs prior grade: CLOCK_GATE_CONTROL and OUTBOUND_MAILBOX_0
    *base* now come from `smc_addr(...)`, but the proof path still hand-copies
    `MAILBOX_CG_EN = 1 << 1`, `_MAILBOX_STRIDE = 0x1000`, and six field offsets
    (`+0x010/+0x018/+0x020/+0x028/+0x030/+0x038`) then computes
    `base + i*stride + off` for mailboxes 0–3. Generated PeakRDL absolute
    symbols and the CG bitmask already exist and match the computed values:
    `SMC_TOP_SMC_MAILBOX_OUTBOUND_MAILBOX_{0..3}_{STATUS,ERROR_FLAGS,WIRQT,RIRQT,IRQS,IRQEN}_BASE_ADDR`
    and `SMC_BASE_CONFIG__CLOCK_GATE_CONTROL__MAILBOX_CG_EN_bm=0x2` (latent-rot
    class, not false-identity). Kept log hits those absolute addresses
    (checks #3–#26).
  closure_condition: >-
    Address every swept STATUS/ERROR_FLAGS/WIRQT/RIRQT/IRQS/IRQEN via their
    generated absolute `smc_addr("SMC_TOP_SMC_MAILBOX_OUTBOUND_MAILBOX_{i}_*_BASE_ADDR")`
    symbols (not base+stride+hand offset), and import `MAILBOX_CG_EN` from the
    generated `_bm` mask (via `smc_addr_map` / `smc_base_config.h`, matching
    other CG enables). Drop parallel numeric offsets, stride, and `1 << 1` as
    the addressing source of truth.
  waived_by: null
- id: FIND-002
  tag: '[EXACT-EXPECTATION]'
  severity: Major
  artifact_ref: hw/sys/smc/dv/cocotb/seq_lib/smc_mailbox_field_sweep_test_seq.py:41-60
  observed: >-
    After enabling mailbox CG, all 24 outbound field reads (STATUS, ERROR_FLAGS,
    WIRQT, RIRQT, IRQS, IRQEN × mailboxes 0–3) call `csr_read` with
    `expected=None`. Scoreboard therefore only asserts AXI `resp_ok` for those
    accesses. CLOCK_GATE enable/restore are write-only with no readback expect.
    Kept log shows STATUS `rdata=0x1` and other fields `0x0` with `exp=None` on
    every field check (#3–#26), yet the test PASSes — OKAY + `accesses==27` alone
    is not an exact data contract for the swept fields.
  closure_condition: >-
    For each mailbox register on the proof path, assert an independently derived
    exact expected value (reset / idle / documented side-effect) on the read;
    emit failure when DUT data mismatches. Do not rely on OKAY + access count
    alone for STATUS/ERROR_FLAGS/WIRQT/RIRQT/IRQS/IRQEN.
  waived_by: null
waivers: []
recommendation: NOT-READY
---

# Grade Report — smc_mailbox_field_sweep_test (standalone Layer 1 re-audit)

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

## DELTA (re-audit vs prior grade `0/0 NOT-READY` on log `f874a34e…`)

| Item | Prior (log `f874a34e…`, PASS) | This audit (log `11a7bc1b…`, PASS) |
|---|---|---|
| Verdict | 0/0 PROVEN — NOT READY | 0/0 PROVEN — NOT READY |
| Findings | 🟠 2 Major | 🟠 2 Major |
| Prior FIND-001 hand-copied absolute CSR / CG literals | open Major `[ADDRESS-FROM-AUTHORITATIVE-MAP]` (`0xC001_0018` / `0xC001_8000` / offsets / `1<<1`) | **partially remediated, still open** as FIND-001 Major — bases via `smc_addr`; residual hand offsets `+0x010…+0x038`, `_MAILBOX_STRIDE=0x1000`, and `MAILBOX_CG_EN=1<<1` while absolute per-field symbols and `_bm` exist |
| Prior FIND-002 field-sweep exact expects | open Major `[EXACT-EXPECTATION]` (`expected=None` on 24 field reads) | **unchanged** — still open as FIND-002 Major (`exp=None` on checks #3–#26) |
| Kept log | `f874a34eb1da31afbae7b262f18c79add2d9e931ffe1dd62c6c62ab975f14cb5` | `11a7bc1b87f0fcfffa44be965cf80a82659d3caf60bf5cf4e70e10421af4844c` |
| Seq sha256 | `b072532d1513aad00407a1ad41bbdd291fb51c2dea571161dd6a96f6e7644ae0` | `6970d5b85fe492e223bbdaa5f1d690138e0fb56237d6b6e5d356f1683f3394ce` |
| Test sha256 | `e9d58f9c1ed29fb8b748105d3dbea99a2c5f99c423c91d765cefc33f914f7fa0` | unchanged |
| Repo rev | `2ecc7b227e3926b253c65b5aac21239eec24ba5f` | `c10b6d63e0b3377f8e2fa38c138e2ea72cae92c7` |
| Auditor run_id | `cursor/grok/4.5` | `cursor/grok/4.5-reaudit-20260806` |
| Waivers carried | none signed (`waivers: []`) | none (nothing to drop; no signed entries) |

## Your to-do — 2 items (🟠 2 Major)

| # | Kind | Id | Severity / grade | Where |
|---|---|---|---|---|
| 1 | finding | FIND-001 | 🟠 Major | `smc_mailbox_field_sweep_test_seq.py:23-35` |
| 2 | finding | FIND-002 | 🟠 Major | `smc_mailbox_field_sweep_test_seq.py:41-60` |

<details>
<summary>1. FIND-001 — 🟠 Major <code>[ADDRESS-FROM-AUTHORITATIVE-MAP]</code> — residual hand-copied field offsets / stride / MAILBOX_CG_EN</summary>

- **Where:** `hw/sys/smc/dv/cocotb/seq_lib/smc_mailbox_field_sweep_test_seq.py:23-35`
- **Observed:** Base addresses import via `smc_addr`, but field addresses still use `BASE + i*0x1000 + hand offset` and `MAILBOX_CG_EN = 1 << 1`. Generated absolute STATUS/ERROR_FLAGS/WIRQT/RIRQT/IRQS/IRQEN symbols for mailboxes 0–3 and `MAILBOX_CG_EN_bm=0x2` exist and currently match (latent rot). Log hits `0xc0018010…8038` / `9xxx` / `axxx` / `bxxx`.
- **Closure:** Use generated absolute per-field symbols and the generated CG `_bm` mask; drop hand offsets, stride, and `1 << 1`.

</details>

<details>
<summary>2. FIND-002 — 🟠 Major <code>[EXACT-EXPECTATION]</code> — field-sweep reads lack exact data check</summary>

- **Where:** `hw/sys/smc/dv/cocotb/seq_lib/smc_mailbox_field_sweep_test_seq.py:41-60`
- **Observed:** All 24 mailbox field reads use `expected=None`; scoreboard only requires `resp_ok`. Log: STATUS `0x1`, other fields `0x0`, `exp=None` across checks #3–#26 with PASS. Final `assert accesses == 27` is a count gate, not a data contract. Sequence intentionally avoids `csr_read_bounded` (good for hang/DECERR sensitivity) but still never compares rdata.
- **Closure:** Assert independently derived exact idle/reset (or documented) values for each swept mailbox CSR so a wrong/stale datum fails the test.

</details>

**Then:** owner remediates FIND-001/FIND-002 on `smc_mailbox_field_sweep_test_seq`, re-keeps a PASS log, and re-invokes `/dv_test_audit smc_mailbox_field_sweep_test`. Do not invent a card here (`STANDALONE-REQUEST`).

## All checkers

| Checker | Grade | Proof class | Covers | Findings |
|---|---|---|---|---|
| — | — | — | — | no card checkers (MODE=NO-CHECKBOX) |

### Layer 1 structural rule set

| Rule | Result |
|---|---|
| F1 fabricated verdict / backdoor write | ✅ clean — frontdoor SEP_IN SYS AXI via `SmcSysAxiItem`; no force/deposit on CSR path; CG restore uses previously read value |
| F2 can't-fail checker | ✅ clean — scoreboard `resp_ok` and driver timeout `AssertionError` are reachable; `assert accesses == 27` can fail; intentionally avoids `csr_read_bounded` vacuity |
| E1 skip-to-pass | ✅ clean — no missing-handle skip-to-pass; AXI path must complete or raise |
| E2 empty phase | ✅ clean — real AXI CG enable / 24 field reads / restore (27 accesses logged) |
| S1 silent fail | ✅ clean — mismatch/timeout/`resp_ok` raise; sequence access-count assert |
| O1 checker disabled | ✅ clean — scoreboard SYS AXI path active (log checks #1–#27) |
| Phase-S obligations — L1 | 🟠 Major — FIND-001, FIND-002; timeouts fail; seed logged; enrolled in `p1_coverage_gap_r3.toml`; ROM/efuse preload is post-PASS bring-up trailer not CSR golden |
| Phase-S obligations — L2 (needs the card) | — not evaluated |

## Evidence appendix

<details>
<summary>Kept log + code proof-path notes</summary>

- Implementation: `hw/sys/smc/dv/cocotb/tests/smc_mailbox_field_sweep_test.py`
  sha256 `e9d58f9c1ed29fb8b748105d3dbea99a2c5f99c423c91d765cefc33f914f7fa0`
- Sequence: `hw/sys/smc/dv/cocotb/seq_lib/smc_mailbox_field_sweep_test_seq.py`
  sha256 `6970d5b85fe492e223bbdaa5f1d690138e0fb56237d6b6e5d356f1683f3394ce`
- Scoreboard / driver (proof path): `smc_scoreboard._check_sys_axi`, `smc_sys_axi_agent._drive`
- Authoritative map available: `hw/sys/smc/regs/gen/c/smc_addr.h` +
  `blocks/smc_base_config.h` via `seq_lib/smc_addr_map.py` (bases used; per-reg
  absolute symbols / `_bm` not yet)
- Log: `hw/sys/smc/dv/build/runs/20260806_094641__verilator__smc_mailbox_field_sweep_test/smc_mailbox_field_sweep_test/logs/smc_mailbox_field_sweep_test.log`
  sha256 `11a7bc1b87f0fcfffa44be965cf80a82659d3caf60bf5cf4e70e10421af4844c`
  (verified via `sha256sum`; matches invoker-supplied path; policy revision matches)
- Seed: 1 · simulator: verilator 5.050 2026-07-01 · model fingerprint `2c815fa08277`
- Repo rev: `c10b6d63e0b3377f8e2fa38c138e2ea72cae92c7`
- `result.json`: `status: PASS`, `exit_code: 0`, cocotb summary L492–L494:
  `TESTS=1 PASS=1 FAIL=0 SKIP=0`
- Stimulus: enable `MAILBOX_CG_EN` on CLOCK_GATE_CONTROL → read 6 fields × 4 outbound
  mailboxes → restore CLOCK_GATE; final `assert accesses == 27`
- Exact value compares in log: **none** — every SYS AXI check has `exp=None` (#1–#27)
- Observed rdata (not asserted): STATUS `0x1` on mailboxes 0–3; ERROR_FLAGS/WIRQT/RIRQT/IRQS/IRQEN `0x0`
- AXI monitor trailer: `25 R beats, 2 B resps; R-resp tally OKAY=25; 0 errors` (L486)
- Enrollment: `hw/sys/smc/dv/testlists/p1_coverage_gap_r3.toml`
- Bring-up trailer: efuse/ROM hex preload after cocotb PASS; not used as CSR golden
  on this proof path
- Entry gate / Layer 2 not evaluated (MODE=NO-CHECKBOX)
- Provenance: legacy (`test_author.run_id: unknown`); auditor
  `run_id: cursor/grok/4.5-reaudit-20260806`

</details>

<details>
<summary>Stimulus / sample cites (kept log <code>11a7bc1b…</code>)</summary>

| Step | Line (approx) | What the log shows | Impl |
|---|---|---|---|
| CG enable R/W | 293–306 | CLOCK_GATE read `0x1f000000` → write `0x1f000002`; `exp=None` | seq `:42-44` |
| MBOX0 6 fields | 313–348 | STATUS `0x1`, others `0x0`, `exp=None` | seq `:50-53` |
| MBOX1–3 fields | 355–474 | same pattern at `0xc0019xxx`/`a`/`b` | seq `:50-53` |
| restore CG | 481 | CLOCK_GATE write `0x1f000000`; no readback | seq `:54-55` |
| VIP + cocotb | 483–494 | `csr_accesses=27`; `PASS` / `TESTS=1 PASS=1` | seq `:56-60` |

</details>

## Not concluded

- Whether the per-mailbox 6-field decode-alive sweep proves the SPEC properties a future card would require (O2) — Skill 3.
- Completeness against a feature_list — no inventory applies in STANDALONE-REQUEST.
- Any closure or PROVEN checker claim — MODE=NO-CHECKBOX forbids inventing checkers.

## Accepted waivers

| Finding | Rule | Where | Why | Approved by |
|---|---|---|---|---|
| — | — | — | none | — |
