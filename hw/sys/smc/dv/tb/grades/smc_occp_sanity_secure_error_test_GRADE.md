---
schema: dv-quality/v1
artifact: testcase-grade
testcase: smc_occp_sanity_secure_error_test
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
- path: hw/sys/smc/dv/build/runs/20260806_094630__verilator__smc_occp_sanity_secure_error_test/smc_occp_sanity_secure_error_test/logs/smc_occp_sanity_secure_error_test.log
  sha256: 3229df6f8352b47f7949bb9f9d68ecf8d9151278bd81a0599c5523e3680ed02b
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
  artifact_ref: hw/sys/smc/dv/testlists/vplan_triplets.toml:181-183
  observed: >
    Testlist args include +smc_efuse_prog_fail_count=1. Kept log confirms the
    bank model armed the inject ("program fail injection count=1", L366) and
    applied it on the first PROGRAM ("injected program failure at paddr 0x1",
    L374). The sequence's secure-error negative (seq :62-85) treats that inject
    as the producer of "secure program-fail must not sticky-OR"
    (before=after=0xa5a55a5a at L329). This is DV-only fail injection into the
    behavioral bank model — no silicon-equivalent "fail first N programs"
    pin/plusarg. No §6 exception record is attached; under STANDALONE-REQUEST
    there is also no approved-card BY-DESIGN-EXCEPTION. Governing §2 question 1
    (no-HW-equivalent for the injected fail) applies; severity is Blocking
    because this PASS log reached and asserted the inject-produced negative
    (prior grade held Major only while the run died before the inject path).
  closure_condition: >
    Either (a) prove program-fail / sticky-OR behavior without bank-model fail
    injection (real HW fail stimulus or a documented silicon-equivalent path),
    or (b) record a human-approved §6 / card BY-DESIGN-EXCEPTION naming the
    plusarg, scope, and why frontdoor fail is impossible, and keep at least one
    burn-success path with the inject OFF. Re-keep the log after remediation.
  waived_by: null
- id: FIND-002
  tag: '[NO-BLIND-DELAY-SYNC]'
  severity: Major
  artifact_ref: hw/sys/smc/dv/cocotb/seq_lib/smc_occp_sanity_secure_error_test_seq.py:45-52
  observed: >
    After polling only tb_fuse_sense_done, the sequence settles with
    ClockCycles(clk, 10) then issues CSR traffic (EFUSE_MAP_0 /
    CHIP_CONFIG_VERSION_LO / EFUSE_PROGRAM_CTRL). Base helper
    smc_base_test_seq.wait_fuse_sense_done() documents that sense-done + a
    short settle is insufficient (fuse_reset_n delay → rst_warm sync) and waits
    on tb_fuse_reset_n / tb_rst_warm_smc_clk_n (both present on tb_top). This
    PASS completed AXI OKAY at the PeakRDL windows, so the fixed settle did not
    hang the bus this seed — but completion sync is still a magic cycle count,
    not an event/handshake with TIMEOUT-MUST-FAIL. Sibling sequences (e.g.
    smc_efuse_map_read_test_seq) already call wait_fuse_sense_done().
  closure_condition: >
    Replace the hand-rolled sense poll + ClockCycles(10) with
    await self.wait_fuse_sense_done() (or equivalent handshake wait on
    tb_rst_warm_smc_clk_n with TIMEOUT-MUST-FAIL). Do not use a fixed delay as
    the warm-domain completion barrier.
  waived_by: null
waivers: []
recommendation: NOT-READY
---

# Grade Report — smc_occp_sanity_secure_error_test (standalone Layer 1)

**VERDICT: 0/0 PROVEN — NOT READY** (mode NO-CHECKBOX, no_contract_reason STANDALONE-REQUEST)

| Mode | Entry gate | Checkers | Findings | Recommendation |
|---|---|---|---|---|
| `NO-CHECKBOX` | — NOT-EVALUATED | 0/0 PROVEN | 🔴 1 Blocking · 🟠 1 Major | ⛔ NOT-READY |

> No approved checkbox card or parent plan record governs this testcase
> (`STANDALONE-REQUEST` / active-regression L1 wave). Layer 1 findings are the entire
> scope of this report. `NOT-READY` records the **absence of a closure claim, not a
> defect**. Kept log is a sim **PASS** (seed 1): frontdoor PeakRDL eFuse /
> chip-config CSRs completed, fail-then-recover sticky-OR path ran under bank-model
> prog-fail inject — Layer 2 entry is still not evaluated in this mode.

## DELTA (re-audit vs prior grade `0/0 NOT-READY` on log `c6c0e8bd…`)

| Item | Prior (log `c6c0e8bd…`, FAIL) | This audit (log `3229df6f…`, PASS) |
|---|---|---|
| Verdict | 0/0 PROVEN — NOT READY | 0/0 PROVEN — NOT READY |
| Findings | 🔴 1 Blocking · 🟠 2 Major | 🔴 1 Blocking · 🟠 1 Major |
| Prior FIND-001 `[ADDRESS-FROM-AUTHORITATIVE-MAP]` | open Blocking — `0xC000B000`/`0xC000C004` literals | **closed** — seq now imports PeakRDL via `smc_addr`; log hits `0xc0007000` / `0xc0002900` / `0xc0008004` |
| Prior FIND-002 `[NO-BLIND-DELAY-SYNC]` | open Major — sense + `ClockCycles(10)` | **still open** as FIND-002 Major — same settle; AXI completed this seed |
| Prior FIND-003 `[NO-FORCED-INTERNAL-STATE]` | open Major — inject not reached | **still open / escalated** as FIND-001 Blocking — inject armed + applied; sticky-OR negative asserted on PASS |
| Kept log | `c6c0e8bd…` FAIL (AXI timeout @ `0xc000b000`) | `3229df6f…` PASS; 8 CSR accesses; fail-then-recover OK |
| Repo rev | `2ecc7b227e3926b253c65b5aac21239eec24ba5f` | `c10b6d63e0b3377f8e2fa38c138e2ea72cae92c7` |
| Waivers carried | none signed (`waivers: []`; nothing to drop) | none |

## Your to-do — 2 items (🔴 1 Blocking · 🟠 1 Major)

| # | Kind | Id | Severity / grade | Where |
|---|---|---|---|---|
| 1 | finding | FIND-001 | 🔴 Blocking | `vplan_triplets.toml:181-183` |
| 2 | finding | FIND-002 | 🟠 Major | `smc_occp_sanity_secure_error_test_seq.py:45-52` |

<details>
<summary>1. FIND-001 — 🔴 Blocking <code>[NO-FORCED-INTERNAL-STATE]</code> — bank-model prog-fail plusarg on proof path</summary>

- **Where:** `hw/sys/smc/dv/testlists/vplan_triplets.toml:181-183` (consumed by seq
  PROGRAM_FAIL path `:62-85`)
- **Observed:** `+smc_efuse_prog_fail_count=1` injects the first-program failure the
  sequence asserts (log L366/L374; before=after sticky-OR at L329). No §6 / card
  exception. No-HW-equivalent shortcut; this PASS reached the inject path → Blocking.
- **Closure:** Prove fail/sticky-OR without inject, or attach an approved exception and
  keep a burn-success path with inject OFF; re-keep log.

</details>

<details>
<summary>2. FIND-002 — 🟠 Major <code>[NO-BLIND-DELAY-SYNC]</code> — sense-done + 10 cycles instead of warm handshake</summary>

- **Where:** `hw/sys/smc/dv/cocotb/seq_lib/smc_occp_sanity_secure_error_test_seq.py:45-52`
- **Observed:** Hand-rolled `tb_fuse_sense_done` poll + `ClockCycles(10)` then CSR.
  Base `wait_fuse_sense_done()` exists for warm-domain ready. This seed completed AXI
  OKAY, but sync is still a fixed settle, not a handshake with fail-on-timeout.
- **Closure:** Call `await self.wait_fuse_sense_done()` (or wait
  `tb_rst_warm_smc_clk_n` with fail-on-timeout); drop the fixed settle as the barrier.

</details>

**Then:** owner decides inject exception vs real fail stimulus, replaces the sense settle
with `wait_fuse_sense_done()`, re-runs seed 1, and re-invokes
`/dv_test_audit smc_occp_sanity_secure_error_test`.
Do not invent a card here (`STANDALONE-REQUEST`).

## All checkers

| Checker | Grade | Proof class | Covers | Findings |
|---|---|---|---|---|
| — | — | — | — | no card checkers (MODE=NO-CHECKBOX) |

### Layer 1 structural rule set

| Rule | Result |
|---|---|
| F1 fabricated verdict / backdoor write | ✅ clean — CSR via SEP_IN `SmcCsrSeq` / `SmcSysAxiItem`; hierarchical `tb_*` probes are passive observes (`tb_top` assigns); no Force/deposit on proof path |
| F2 can't-fail checker | ✅ clean — marker / sticky-OR / program_done asserts and AXI driver timeout are reachable FAIL-ON paths |
| E1 skip-to-pass | ✅ clean — sense hang raises; no missing-handle skip-to-pass; all programmed steps ran |
| E2 empty phase | ✅ clean — sense → map/version → PROGRAM fail → recovery burn are real executed paths (8 CSR accesses in log) |
| S1 silent fail | ✅ clean — mismatch/`AssertionError` raise; timeout becomes test FAIL |
| O1 checker disabled | ✅ clean — no scoreboard/VIP disable for this seq path |
| Phase-S obligations — L1 | 🔴 Blocking — FIND-001; 🟠 Major — FIND-002; else addresses from `smc_addr_map`, timeouts fail, seed logged, enrolled in `vplan_triplets.toml` / `all.toml`, positive control present for sticky-OR allow path, no unconditional CHK token |
| Phase-S obligations — L2 (needs the card) | — not evaluated |

## Evidence appendix

<details>
<summary>Kept log + code proof-path notes</summary>

- Implementation: `hw/sys/smc/dv/cocotb/tests/smc_occp_sanity_secure_error_test.py`
  sha256 `5964563f760b92465574af083243e54df79595cef12b616624b940feb47c616d`
- Sequence: `hw/sys/smc/dv/cocotb/seq_lib/smc_occp_sanity_secure_error_test_seq.py`
  sha256 `da2be74eb4fa41f4325ca8064f4b4d2f670728f1abed03e923712808801aca01`
- Helpers on proof path: `smc_csr_seq_utils.SmcCsrSeq`, `smc_sys_axi_agent._drive` /
  `_timed_event`, `smc_addr_map.smc_addr` (used); `smc_base_test_seq.wait_fuse_sense_done`
  (available, unused)
- Authoritative map: `hw/sys/smc/regs/gen/c/smc_addr.h` via `seq_lib/smc_addr_map.py`
- Log: `hw/sys/smc/dv/build/runs/20260806_094630__verilator__smc_occp_sanity_secure_error_test/smc_occp_sanity_secure_error_test/logs/smc_occp_sanity_secure_error_test.log`
  sha256 `3229df6f8352b47f7949bb9f9d68ecf8d9151278bd81a0599c5523e3680ed02b`
  (verified via `sha256sum`; matches invoker hint)
- Seed: 1 · simulator: verilator 5.050 2026-07-01 · model fingerprint `2c815fa08277`
- `result.json`: `status` PASS / `exit_code: 0`, cocotb summary L361–L363:
  `TESTS=1 PASS=1 FAIL=0 SKIP=0`
- Proof-path CSR traffic (PeakRDL windows):
  - RD `0xc0007000` → `0xa5a55a5a` (EFUSE_MAP / LOCKS; marker assert)
  - RD `0xc0002900` → `0x100a0` (CHIP_CONFIG_VERSION_LO)
  - WR/RD `0xc0008004` PROGRAM fail then recovery (program_done bit25 polls)
- Sticky-OR: fail path before=after `0xa5a55a5a` (L329); recovery asserts bit0 set;
  log L351 `fail-then-recover OK`; protocol VIP `csr_accesses=8` `passed=True`
- Plusargs (testlist / trailer): `+smc_efuse_hex=.../smc_efuse_default.hex`,
  `+smc_efuse_prog_fail_count=1` (L366–L367); inject applied L374
- TB note: `tb_efuse_programmed_word0` is assigned equal to `tb_efuse_otp_word0`
  (single bank-model store); not graded as a fabricated verdict here
- Enrollment: `hw/sys/smc/dv/testlists/vplan_triplets.toml`, `all.toml`
- No unexplained `ERROR`/`FATAL`/`Traceback` in the kept log
- Entry gate / Layer 2 not evaluated (MODE=NO-CHECKBOX)
- Provenance: legacy (`test_author.run_id: unknown`)

</details>

<details>
<summary>Stimulus / sample cites (kept log <code>3229df6f…</code>)</summary>

| Step | Line (approx) | What the log shows | Impl |
|---|---|---|---|
| seed / start | 13–20 | seed=1; test running | base_test / cocotb |
| powergood / reset | 266–268 | powergood assert; cold release | `smc_base_test` |
| EFUSE_MAP_0 | 280–293 | AXI RD `0xc0007000` → `0xa5a55a5a` | seq `:55` |
| CHIP_CONFIG_VERSION_LO | 295–300 | AXI RD `0xc0002900` → `0x100a0` | seq `:59` |
| PROGRAM fail | 302–329 | WR/RD `0xc0008004`; before=after marker | seq `:64-85` |
| recovery burn | 330–351 | second PROGRAM; `fail-then-recover OK` | seq `:88-103` |
| protocol VIP | 352–353 | `csr_accesses=8` `passed=True` | test `:27-36` |
| cocotb result | 361–363 | `PASS` / `TESTS=1 PASS=1 FAIL=0` | — |
| bank model trailer | 365–374 | prog_fail_count=1; fuse sense done; inject at paddr 0x1 | plusargs |

</details>

## Not concluded

- Whether OTP program-fail + signature gates through the behavioral bank model prove
  the SPEC secure-error / OCCP properties a future card would require (O2) — Skill 3.
- Completeness against a feature_list — no inventory applies in STANDALONE-REQUEST.
- Any closure or PROVEN checker claim — MODE=NO-CHECKBOX forbids inventing checkers.

## Accepted waivers

| Finding | Rule | Where | Why | Approved by |
|---|---|---|---|---|
| — | — | — | none | — |
