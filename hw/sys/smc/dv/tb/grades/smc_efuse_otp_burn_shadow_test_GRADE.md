---
schema: dv-quality/v1
artifact: testcase-grade
testcase: smc_efuse_otp_burn_shadow_test
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
- path: hw/sys/smc/dv/build/runs/20260806_094631__verilator__smc_efuse_otp_burn_shadow_test/smc_efuse_otp_burn_shadow_test/logs/smc_efuse_otp_burn_shadow_test.log
  sha256: c5962e63ef7f3f5cfdac2e9861fafed184899b94a07d258357573210887dee43
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
  tag: '[NO-FORCED-INTERNAL-STATE]'
  severity: Blocking
  artifact_ref: hw/sys/smc/dv/testlists/vplan_triplets.toml:193-195
  observed: >
    Testlist args include +smc_efuse_prog_fail_count=1. Kept log trailer
    confirms "program fail injection count=1" (L369) and "injected program
    failure at paddr 0x0" (L377). Sequence PROGRAM_FAIL path
    (smc_efuse_otp_burn_shadow_test_seq.py:82-102) asserts program_status=1 and
    no sticky-OR solely against that bank-model inject. There is no silicon
    equivalent "fail first N programs" pin/plusarg; no §6 exception record is
    attached. Under STANDALONE-REQUEST there is also no approved-card
    BY-DESIGN-EXCEPTION. Governing §2 question 1 (no-HW-equivalent) → Blocking.
    This PASS run reaches and relies on the inject path (L324 after injected
    fail; programmed stays 0xa5a55a5a).
  closure_condition: >
    Either (a) prove program-fail / no-sticky-OR without bank-model fail
    injection (real HW fail stimulus or a documented silicon-equivalent path),
    or (b) record a human-approved §6 / future-card BY-DESIGN-EXCEPTION naming
    the plusarg, scope, and why frontdoor fail is impossible, and keep at least
    one burn-success path with the inject OFF (second PROGRAM already consumes
    count=1; document that split). Re-keep seed 1 after the exception or
    stimulus change.
  waived_by: null
- id: FIND-002
  tag: '[NO-BLIND-DELAY-SYNC]'
  severity: Major
  artifact_ref: hw/sys/smc/dv/cocotb/seq_lib/smc_efuse_otp_burn_shadow_test_seq.py:53-60
  observed: >
    After polling only tb_fuse_sense_done, the sequence settles with
    ClockCycles(clk, 20) then issues warm-domain CSR traffic. Base helper
    smc_base_test_seq.wait_fuse_sense_done() documents that sense-done + a
    short settle is insufficient (fuse_reset_n delay → rst_warm sync) and waits
    on tb_fuse_reset_n / tb_rst_warm_smc_clk_n. Sibling
    smc_efuse_map_read_test_seq already calls wait_fuse_sense_done(). This seed
    PASSed (CSR at 16566 ns completed), but the completion barrier remains a
    fixed delay, not a warm-domain handshake with TIMEOUT-MUST-FAIL.
  closure_condition: >
    Replace the hand-rolled sense poll + ClockCycles(20) with
    await self.wait_fuse_sense_done() (or equivalent handshake wait on
    tb_rst_warm_smc_clk_n with TIMEOUT-MUST-FAIL). Do not use a fixed delay as
    the warm-domain completion barrier.
  waived_by: null
waivers: []
recommendation: NOT-READY
---

# Grade Report — smc_efuse_otp_burn_shadow_test (standalone Layer 1)

**VERDICT: 0/0 PROVEN — NOT READY** (mode NO-CHECKBOX, no_contract_reason STANDALONE-REQUEST)

| Mode | Entry gate | Checkers | Findings | Recommendation |
|---|---|---|---|---|
| `NO-CHECKBOX` | — NOT-EVALUATED | 0/0 PROVEN | 🔴 1 Blocking · 🟠 1 Major | ⛔ NOT-READY |

> No approved checkbox card or parent plan record governs this testcase
> (`STANDALONE-REQUEST` / active-regression L1 wave). Layer 1 findings are the entire
> scope of this report. `NOT-READY` records the **absence of a closure claim, not a
> defect** in the test by itself. Kept log is a sim **PASS** (seed 1): sense +
> PeakRDL eFuse CSR MAP/PROGRAM/STATUS path completes; `TESTS=1 PASS=1 FAIL=0 SKIP=0`.
> Layer 2 entry is still not evaluated in this mode.

## DELTA (re-audit vs prior grade `0/0 NOT-READY` on log `73641156…`)

| Item | Prior (log `73641156…`, FAIL) | This audit (log `c5962e63…`, PASS) |
|---|---|---|
| Verdict | 0/0 PROVEN — NOT READY | 0/0 PROVEN — NOT READY |
| Findings | 🔴 1 Blocking · 🟠 2 Major | 🔴 1 Blocking · 🟠 1 Major |
| Prior FIND-001 `[ADDRESS-FROM-AUTHORITATIVE-MAP]` | open Blocking — hand `0xC000_B000` / `0xC000_C00x` false identity | **cleared** — seq imports `smc_addr`; log hits `0xc0007000` / `8004` / `8000` OKAY |
| Prior FIND-002 `[NO-BLIND-DELAY-SYNC]` | open Major — sense + `ClockCycles(20)` | **still open** as FIND-002 Major — same settle; this seed luckily completed CSR |
| Prior FIND-003 `[NO-FORCED-INTERNAL-STATE]` | open Major — inject not reached on FAIL log | **still open / escalated** as FIND-001 Blocking — inject executed; PASS relies on it (no-HW-equivalent) |
| Kept log | FAIL seed=1 (AXI timeout @ `0xc000b000`) | PASS seed=1; model `2c815fa08277` |
| repository_revision | `2ecc7b22…` | updated `c10b6d63…` |
| seq sha256 | `68f506fc…` | updated `2a5ae3ba…` (`smc_addr` import) |
| Waivers carried | none signed (`waivers: []`; nothing to drop) | none |

## Your to-do — 2 items (🔴 1 Blocking · 🟠 1 Major)

| # | Kind | Id | Severity / grade | Where |
|---|---|---|---|---|
| 1 | finding | FIND-001 | 🔴 Blocking | `vplan_triplets.toml:193-195` |
| 2 | finding | FIND-002 | 🟠 Major | `smc_efuse_otp_burn_shadow_test_seq.py:53-60` |

<details>
<summary>1. FIND-001 — 🔴 Blocking <code>[NO-FORCED-INTERNAL-STATE]</code> — bank-model prog-fail plusarg on proof path</summary>

- **Where:** `hw/sys/smc/dv/testlists/vplan_triplets.toml:193-195` (consumed by seq
  PROGRAM_FAIL path `:82-102`)
- **Observed:** `+smc_efuse_prog_fail_count=1` injects the first-program failure the
  sequence asserts (`program_status=1`, no sticky-OR). Kept log L369/L377/L324
  show the inject fired and the assert path passed. No silicon-equivalent
  plusarg; no §6 / card exception. §2 Q1 → Blocking.
- **Closure:** Prove fail/sticky-OR without inject, or attach an approved exception
  and keep a burn-success path with inject OFF; re-keep seed 1.

</details>

<details>
<summary>2. FIND-002 — 🟠 Major <code>[NO-BLIND-DELAY-SYNC]</code> — sense-done + 20 cycles instead of warm handshake</summary>

- **Where:** `hw/sys/smc/dv/cocotb/seq_lib/smc_efuse_otp_burn_shadow_test_seq.py:53-60`
- **Observed:** Hand-rolled `tb_fuse_sense_done` poll + `ClockCycles(20)` then CSR.
  Base `wait_fuse_sense_done()` exists because that pattern can leave warm-domain
  AXI without ready. This PASS seed completed, but the barrier is still a fixed
  delay.
- **Closure:** Call `await self.wait_fuse_sense_done()` (or wait
  `tb_rst_warm_smc_clk_n` with fail-on-timeout); drop the fixed settle as the barrier.

</details>

**Then:** owner decides inject exception vs real fail stimulus, replaces the warm-domain
settle with `wait_fuse_sense_done()`, re-runs seed 1, and re-invokes
`/dv_test_audit smc_efuse_otp_burn_shadow_test`. Do not invent a card here
(`STANDALONE-REQUEST`).

## All checkers

| Checker | Grade | Proof class | Covers | Findings |
|---|---|---|---|---|
| — | — | — | — | no card checkers (MODE=NO-CHECKBOX) |

### Layer 1 structural rule set

| Rule | Result |
|---|---|
| F1 fabricated verdict / backdoor write | ✅ clean — CSR via SEP_IN `SmcCsrSeq` / `SmcSysAxiItem`; hierarchical `tb_*` probes are passive observes (`tb_top` assigns); no Force/deposit on proof path |
| F2 can't-fail checker | ✅ clean — marker / sticky-OR / program_status / sense_done asserts and `_wait_program_done` timeout are reachable FAIL-ON paths |
| E1 skip-to-pass | ✅ clean — sense hang raises; no missing-handle skip-to-pass |
| E2 empty phase | ✅ clean — sense → map golden → PROGRAM fail → PROGRAM sticky-OR → STATUS all execute in kept log |
| S1 silent fail | ✅ clean — mismatch/`AssertionError` raise; AXI / program_done waits fail on timeout |
| O1 checker disabled | ✅ clean — SYS AXI scoreboard checks #1–#8 and protocol VIP path active |
| Phase-S obligations — L1 | 🔴 Blocking — FIND-001; 🟠 Major — FIND-002; else addresses from `smc_addr_map`, timeouts fail, seed logged, enrolled in `vplan_triplets.toml` / `all.toml`, no unconditional CHK token, sense wait bound fails |
| Phase-S obligations — L2 (needs the card) | — not evaluated |

## Evidence appendix

<details>
<summary>Kept log + code proof-path notes</summary>

- Implementation: `hw/sys/smc/dv/cocotb/tests/smc_efuse_otp_burn_shadow_test.py`
  sha256 `5e7ae52aed51aa5e9447738edc06f09e06cada9196b2e58c27a3446620e8ebf6`
- Sequence: `hw/sys/smc/dv/cocotb/seq_lib/smc_efuse_otp_burn_shadow_test_seq.py`
  sha256 `2a5ae3ba49eff9e3fe1c93094d1a900089ad7641291969b606fb8b7bf085f0eb`
- Helpers on proof path: `smc_csr_seq_utils.SmcCsrSeq`, `smc_sys_axi_agent._drive` /
  `_timed_event`, `smc_addr_map.smc_addr`; `smc_base_test_seq.wait_fuse_sense_done`
  available but unused
- Authoritative map: `hw/sys/smc/regs/gen/c/smc_addr.h` via `seq_lib/smc_addr_map.py`
- Log: `hw/sys/smc/dv/build/runs/20260806_094631__verilator__smc_efuse_otp_burn_shadow_test/smc_efuse_otp_burn_shadow_test/logs/smc_efuse_otp_burn_shadow_test.log`
  sha256 `c5962e63ef7f3f5cfdac2e9861fafed184899b94a07d258357573210887dee43`
  (verified via `sha256sum`; matches invoker hint)
- Seed: 1 · simulator: verilator 5.050 2026-07-01 · model fingerprint `2c815fa08277`
- `result.json`: `status: PASS`, `exit_code: 0`, cocotb summary L364–L366:
  `TESTS=1 PASS=1 FAIL=0 SKIP=0`
- Stimulus path in log: OTP word0 `0xa5a55a5a` (L280) → MAP RD `@0xc0007000`
  `0xa5a55a5a` (L281–L296) → PROGRAM_FAIL WR/RD `@0xc0008004` status=1 programmed
  unchanged (L297–L324) → PROGRAM_OK sticky-OR `0xa5a55a5b` (L325–L346) →
  STATUS `@0xc0008000` `0x1` (L347–L354) → protocol VIP passed (L355)
- Plusargs (testlist / trailer): `+smc_efuse_hex=.../smc_efuse_default.hex`,
  `+smc_efuse_prog_fail_count=1`; no `+skip_fuse_sense` (L368–L370)
- TB note: `tb_efuse_programmed_word0` is assigned equal to `tb_efuse_otp_word0`
  (single bank-model store); not graded as a fabricated verdict here
- Enrollment: `hw/sys/smc/dv/testlists/vplan_triplets.toml`, `all.toml`
- Entry gate / Layer 2 not evaluated (MODE=NO-CHECKBOX)
- Provenance: legacy (`test_author.run_id: unknown`)

</details>

<details>
<summary>Stimulus / sample cites (kept log <code>c5962e63…</code>)</summary>

| Step | Line (approx) | What the log shows | Impl |
|---|---|---|---|
| seed / start | 13–25 | seed=1; test running | base_test / cocotb |
| powergood / reset | 266–268 | powergood assert; cold release | `smc_base_test` |
| sense probe | 280 | `OTP word0 after sense = 0xa5a55a5a` | seq `:62-66` |
| MAP CSR | 281–296 | AXI RD `0xc0007000` → `0xa5a55a5a` | seq `:68-72` |
| PROGRAM fail | 297–324 | WR/RD `0xc0008004`; status=1; programmed unchanged | seq `:86-102` |
| PROGRAM ok | 325–346 | sticky-OR programmed `0xa5a55a5b` | seq `:105-120` |
| STATUS | 347–354 | AXI RD `0xc0008000` → `0x1` | seq `:122-124` |
| cocotb result | 360–366 | `PASS` / `TESTS=1 PASS=1 FAIL=0` | — |
| bank model trailer | 368–377 | no skip_fuse_sense; prog_fail_count=1; inject @ paddr 0 | plusargs |

</details>

## Not concluded

- Whether sense + burn/fail through the behavioral bank model proves the SPEC OTP
  properties a future card would require (O2) — Skill 3.
- Completeness against a feature_list — no inventory applies in STANDALONE-REQUEST.
- Any closure or PROVEN checker claim — MODE=NO-CHECKBOX forbids inventing checkers.

## Accepted waivers

| Finding | Rule | Where | Why | Approved by |
|---|---|---|---|---|
| — | — | — | none | — |
