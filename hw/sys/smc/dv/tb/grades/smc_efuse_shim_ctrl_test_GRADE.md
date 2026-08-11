---
schema: dv-quality/v1
artifact: testcase-grade
testcase: smc_efuse_shim_ctrl_test
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
- path: hw/sys/smc/dv/build/runs/20260806_094637__verilator__smc_efuse_shim_ctrl_test/smc_efuse_shim_ctrl_test/logs/smc_efuse_shim_ctrl_test.log
  sha256: e8c3d40f004a954dde42aa81ffbfe1b956820d2f386d19d69b72a4e0f2726f6b
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
  artifact_ref: hw/sys/smc/dv/cocotb/seq_lib/smc_efuse_shim_ctrl_test_seq.py:30
  observed: >
    The OSS gate is still `csr_read("EFUSE_INTERFACE_CTRL", EFUSE_INTERFACE_CTRL)`
    with no `expected=` argument, so `smc_scoreboard._check_sys_axi` only asserts
    AXI OKAY (`resp_ok`) and never compares `rdata`. Kept log L280–L293 shows
    STATUS `@ 0xc0008000` → `rdata=0x0` with `exp=None ok=True`. Bootrom header
    `EFUSE_INTERFACE_CTRL_EFUSE_INTERFACE_CTRL_STATUS_REG_DEFAULT` is also
    `0x00000000`, so the observed zero matches reset without any programmed
    compare. Activity / non-error response alone is not an exact INTERFACE_CTRL
    STATUS contract. SHIM uses `csr_read_bounded` / `allow_error` and is
    explicitly non-gating (documented OSS deferral) — not filed separately as
    skip-to-pass.
  closure_condition: >
    Pin an exact INTERFACE_CTRL STATUS expected under the approved efuse / SPEC
    reset or post-sense model for this bench (e.g. header DEFAULT `0x0` if that
    is the contracted post-reset value), or narrow the claimed check to a named
    decode-only / resp-OKAY contract that still documents why value compare is
    out of scope. Re-keep seed 1 after the change.
  waived_by: null
waivers: []
recommendation: NOT-READY
---

# Grade Report — smc_efuse_shim_ctrl_test (standalone Layer 1)

**VERDICT: 0/0 PROVEN — NOT READY** (mode NO-CHECKBOX, no_contract_reason STANDALONE-REQUEST)

| Mode | Entry gate | Checkers | Findings | Recommendation |
|---|---|---|---|---|
| `NO-CHECKBOX` | — NOT-EVALUATED | 0/0 PROVEN | 🟠 1 Major | ⛔ NOT-READY |

> No approved checkbox card or parent plan record governs this testcase
> (`STANDALONE-REQUEST`). Layer 1 findings are the entire scope of this report.
> `NOT-READY` records the **absence of a closure claim, not a defect**. Kept
> log is a sim **PASS** (seed 1, verilator 5.050): INTERFACE_CTRL PeakRDL STATUS
> `@ 0xc0008000` OKAY + SHIM `@ 0xc0403000` DECERR (expected) —
> `TESTS=1 PASS=1 FAIL=0 SKIP=0`. Layer 2 entry is still not evaluated in this mode.

## DELTA (re-audit vs prior grade `0/0 NOT-READY` on log `a6b6b5b0…`)

| Item | Prior (log `a6b6b5b0…`, FAIL) | This audit (log `e8c3d40f…`, PASS) |
|---|---|---|
| Verdict | 0/0 PROVEN — NOT READY | 0/0 PROVEN — NOT READY |
| Findings | 🔴 1 Blocking · 🟠 1 Major | 🟠 1 Major |
| Prior FIND-001 `[ADDRESS-FROM-AUTHORITATIVE-MAP]` | open Blocking — hand `0xC000_C000` / `0xC000_C100` → DECERR / `0xbadcab1e` | **cleared** — seq imports `smc_addr` / `smc_bootrom_addr`; log hits `0xc0008000` OKAY + `0xc0403000` DECERR |
| Prior FIND-002 `[EXACT-EXPECTATION]` | open Major — INTERFACE `expected` omitted | **still open** as FIND-001 Major — same OKAY-only gate; log `rdata=0x0 exp=None` |
| Kept log | FAIL seed=1 (DECERR @ `0xc000c000`) | PASS seed=1; model `2c815fa08277` |
| repository_revision | `2ecc7b22…` | updated `c10b6d63…` |
| seq sha256 | `782405b7…` | updated `67cc07e4…` (`smc_addr_map` import) |
| Waivers carried | none signed (`waivers: []`; nothing to drop) | none |

## Your to-do — 1 item (🟠 1 Major)

| # | Kind | Id | Severity / grade | Where |
|---|---|---|---|---|
| 1 | finding | FIND-001 | 🟠 Major | `smc_efuse_shim_ctrl_test_seq.py:30` |

<details>
<summary>1. FIND-001 — 🟠 Major <code>[EXACT-EXPECTATION]</code> — INTERFACE_CTRL OKAY-only (`expected` omitted)</summary>

- **Where:** `hw/sys/smc/dv/cocotb/seq_lib/smc_efuse_shim_ctrl_test_seq.py:30`
- **Observed:** Gate uses `csr_read` without `expected=`, so scoreboard only
  enforces `resp_ok`. Kept log: STATUS `@ 0xc0008000` → `rdata=0x0` /
  `exp=None ok=True` (matches header DEFAULT `0x0` without a compare).
- **Closure:** Pin a SPEC/model-qualified exact expected (or an explicit
  decode-only / resp-OKAY scope with PeakRDL addressing documented); re-keep
  PASS seed 1.

</details>

**Then:** owner remediates FIND-001 on the sequence, re-runs seed 1 to a kept
PASS log, and re-invokes `/dv_test_audit smc_efuse_shim_ctrl_test`. Do not
invent a card here (`STANDALONE-REQUEST`).

## All checkers

| Checker | Grade | Proof class | Covers | Findings |
|---|---|---|---|---|
| — | — | — | — | no card checkers (MODE=NO-CHECKBOX) |

### Layer 1 structural rule set

| Rule | Result |
|---|---|
| F1 fabricated verdict / backdoor write | ✅ clean — frontdoor SEP_IN SYS AXI via `SmcCsrSeq` / `SmcSysAxiItem`; no force/deposit on CSR path; ROM/efuse `$readmemh` is bring-up trailer, not a fabricated CSR golden |
| F2 can't-fail checker | ✅ clean — scoreboard `resp_ok` FAIL-ON is reachable (prior FAIL at wrong address proved non-OKAY raises); INTERFACE gate is OKAY-sensitive |
| E1 skip-to-pass | ✅ clean — no missing-handle skip-to-pass; INTERFACE_CTRL strict `csr_read` gates OSS pass; SHIM non-gating is documented OSS deferral, not a silent pass over a required check |
| E2 empty phase | ✅ clean — two real SYS AXI reads issued (scoreboard checks #1–#2); body is not a no-op stub |
| S1 silent fail | ✅ clean — non-OKAY on strict `csr_read` raises via scoreboard assert; no swallow-to-pass |
| O1 checker disabled | ✅ clean — SYS AXI scoreboard / axi_monitor active on this path (OKAY=1, DECERR=1 tally) |
| Phase-S obligations — L1 | 🟠 Major — FIND-001 `[EXACT-EXPECTATION]`; else addresses from `smc_addr_map` / PeakRDL + bootrom header, timeouts fail on strict `csr_read`, seed logged, enrolled in `p1_coverage_gap.toml`, no unconditional CHK token |
| Phase-S obligations — L2 (needs the card) | — not evaluated |

## Evidence appendix

<details>
<summary>Kept log + code proof-path notes</summary>

- Implementation: `hw/sys/smc/dv/cocotb/tests/smc_efuse_shim_ctrl_test.py`
  sha256 `82a31a08eadb41e4802d800fc2621305de05201a0cda9efc7dc663edbb1922a5`
- Sequence: `hw/sys/smc/dv/cocotb/seq_lib/smc_efuse_shim_ctrl_test_seq.py`
  sha256 `67cc07e413e1292dff126edbcb61b11cc988bb0e558a66b7363ed01d35082045`
- Helpers on proof path: `smc_addr_map.smc_addr` / `smc_bootrom_addr`,
  `smc_csr_seq_utils.SmcCsrSeq.csr_read` / `csr_read_bounded`,
  `smc_sys_axi_agent`, `smc_scoreboard._check_sys_axi`, `smc_axi_monitor`
- Authoritative map: `hw/sys/smc/regs/gen/c/smc_addr.h` via `seq_lib/smc_addr_map.py`
  (`SMC_TOP_EFUSE_INTERFACE_CTRL_EFUSE_INTERFACE_CTRL_STATUS_BASE_ADDR` @
  `0xC0008000`); SHIM external-mandatory symbol in bootrom `smc_top_regs.h` @
  `0xC0403000` via `smc_bootrom_addr`
- Log: `hw/sys/smc/dv/build/runs/20260806_094637__verilator__smc_efuse_shim_ctrl_test/smc_efuse_shim_ctrl_test/logs/smc_efuse_shim_ctrl_test.log`
  sha256 `e8c3d40f004a954dde42aa81ffbfe1b956820d2f386d19d69b72a4e0f2726f6b`
  (verified via `manifest.py hash-file`; matches invoker hint)
- Seed: 1 · simulator: verilator 5.050 2026-07-01 · model fingerprint `2c815fa08277`
- `result.json`: `status: PASS`, `exit_code: 0`, cocotb summary L312–L314:
  `TESTS=1 PASS=1 FAIL=0 SKIP=0`
- Stimulus path in log: INTERFACE STATUS RD `@ 0xc0008000` → `rdata=0x0` OKAY
  (L280–L293) → SHIM RD `@ 0xc0403000` → DECERR (expected) (L295–L301) →
  protocol VIP `csr_accesses=2 timeouts=0 passed=True` (L303–L304); monitor
  tally OKAY=1, DECERR=1 (L306)
- Enrollment: `hw/sys/smc/dv/testlists/p1_coverage_gap.toml` (also listed in suite)
- Entry gate / Layer 2 not evaluated (MODE=NO-CHECKBOX)
- Provenance: legacy (`test_author.run_id: unknown`); auditor
  `run_id: cursor/grok/4.5-reaudit-20260806`

</details>

<details>
<summary>Stimulus / sample cites (kept log <code>e8c3d40f…</code>)</summary>

| Step | Line (approx) | What the log shows | Impl |
|---|---|---|---|
| seed / start | 13–25 | seed=1; test running | base_test / cocotb |
| powergood / reset | 267–268 | powergood assert; cold release | `smc_base_test` |
| INTERFACE STATUS RD | 280–293 | AXI RD `0xc0008000` → `0x0` OKAY; scoreboard #1 `exp=None` | seq `:30` |
| SHIM RD | 295–301 | AXI RD `0xc0403000` → DECERR (expected); scoreboard #2 | seq `:34` |
| VIP / result | 303–314 | protocol VIP pass; `PASS` / `TESTS=1 PASS=1 FAIL=0` | test + scoreboard |
| bring-up trailer | 316–322 | efuse hex + ROM `$readmemh` after PASS | plusargs / TB |

</details>

## Not concluded

- Whether an INTERFACE_CTRL + SHIM probe proves the SPEC eFuse-shim properties a
  future card would require (O2) — Skill 3.
- Completeness against a feature_list — no inventory applies in STANDALONE-REQUEST.
- Any closure or PROVEN checker claim — MODE=NO-CHECKBOX forbids inventing checkers.

## Accepted waivers

| Finding | Rule | Where | Why | Approved by |
|---|---|---|---|---|
| — | — | — | none | — |
