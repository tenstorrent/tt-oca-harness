---
schema: dv-quality/v1
artifact: testcase-grade
testcase: smc_axi_error_response_depth_test
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
- path: hw/sys/smc/dv/build/runs/20260806_094614__verilator__smc_axi_error_response_depth_test/smc_axi_error_response_depth_test/logs/smc_axi_error_response_depth_test.log
  sha256: 6f73a775309d4073cab30625d9764890b91e350c2e51df24b252cf3f790c41f4
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
  artifact_ref: hw/sys/smc/dv/cocotb/seq_lib/smc_axi_error_response_depth_test_seq.py:18-23
  observed: >-
    `_UNMAPPED_HIGH = smc_addr(WDT_BASE) + 0x0FFF_F000` (0xCFFFF000) is still
    labeled an intentional unmapped hole citing memmap.adoc "SMC Address Space
    Layout", but that table assigns BASE+0x080_0000–BASE+0x1FF_FFFF to Address
    Remapping (24MB). The HIGH offset sits inside that remapping window, not in
    an unspecified gap (unlike `_UNMAPPED_LOW` at BASE+0x00FF_F000, which falls
    between Memory and CLA). Alive / GPIO_CTRL bases are imported from generated
    maps; the HIGH hand offset + hole identity is the remaining rot/identity
    risk. This seed returned DECERR as coded, so the compare is not a
    false-register pass — Major (latent SPEC-identity mismatch), not Blocking.
  closure_condition: >-
    Re-derive every intentional DECERR probe address from the cited memmap
    ranges (true gaps only), or from an authoritative decode/default-slave
    table; stop calling BASE+0x0FFF_F000 an "unmapped" hole while the SPEC maps
    that span to Address Remapping. Keep bases on generated `smc_addr` /
    bootrom symbols.
  waived_by: null
waivers: []
recommendation: NOT-READY
---

# Grade Report — smc_axi_error_response_depth_test (standalone Layer 1)

**VERDICT: 0/0 PROVEN — NOT READY** (mode NO-CHECKBOX, no_contract_reason STANDALONE-REQUEST)

| Mode | Entry gate | Checkers | Findings | Recommendation |
|---|---|---|---|---|
| `NO-CHECKBOX` | — NOT-EVALUATED | 0/0 PROVEN | 🟠 1 Major | ⛔ NOT-READY |

> No approved checkbox card or parent plan record governs this testcase
> (`STANDALONE-REQUEST` / active-regression L1 wave). Layer 1 findings are the entire
> scope of this report. `NOT-READY` records the **absence of a closure claim, not a
> defect** in the test by itself. Kept log is a sim **PASS** (seed 1): three DECERR
> probes + alive baseline/recovery completed; final `error_responses=3` /
> `timeouts=0` reached — Layer 2 entry is still not evaluated in this mode.

## DELTA (re-audit vs prior grade `0/0 NOT-READY` on log `0b3693bb…`)

| Item | Prior (log `0b3693bb…`, FAIL) | This audit (log `6f73a775…`, PASS) |
|---|---|---|
| Verdict | 0/0 PROVEN — NOT READY | 0/0 PROVEN — NOT READY |
| Findings | 🟠 1 Major | 🟠 1 Major |
| Prior FIND-001 UNMAPPED_HIGH | open Major — BASE+0x0FFF_F000 inside remapping window | **still open** as FIND-001 Major — same HIGH offset / SPEC mislabel (base now via `smc_addr`) |
| Third error probe | MISALIGNED_I3C `0xC003A001` expected SLVERR → FAIL (OKAY) | **replaced** by `GPIO_CTRL_ERR_SLAVE` via `external_gpio_ctrl_addr(0)` → DECERR PASS |
| Kept log | FAIL scoreboard `resp 0, expected 2` | PASS seed=1; `TESTS=1 PASS=1 FAIL=0 SKIP=0`; VIP `error_responses=3` |
| Waivers carried | none signed (`waivers: []`; nothing to drop) | none |

## Your to-do — 1 items (🟠 1 Major)

| # | Kind | Id | Severity / grade | Where |
|---|---|---|---|---|
| 1 | finding | FIND-001 | 🟠 Major | `smc_axi_error_response_depth_test_seq.py:18-23` |

<details>
<summary>1. FIND-001 — 🟠 Major <code>[ADDRESS-FROM-AUTHORITATIVE-MAP]</code> — UNMAPPED_HIGH offset conflicts with SPEC remapping window</summary>

- **Where:** `hw/sys/smc/dv/cocotb/seq_lib/smc_axi_error_response_depth_test_seq.py:18-23`
- **Observed:** `smc_addr(WDT_BASE) + 0x0FFF_F000` is named/justified as an unmapped hole via memmap.adoc, but that layout table places BASE+0x080_0000–0x1FF_FFFF in Address Remapping. Generated bases for ALIVE / GPIO_CTRL are fine; the HIGH hand offset asserts a hole identity the cited SPEC does not support.
- **Closure:** Pick DECERR probe addresses that are true gaps (or an authoritative default-slave list) under the same memmap; do not label remapping-window offsets as unmapped holes.

</details>

**Then:** owner remediates FIND-001 (true-gap / authoritative DECERR targets only), re-keeps a PASS log, and re-invokes `/dv_test_audit smc_axi_error_response_depth_test`. Do not invent a card here (`STANDALONE-REQUEST`).

## All checkers

| Checker | Grade | Proof class | Covers | Findings |
|---|---|---|---|---|
| — | — | — | — | no card checkers (MODE=NO-CHECKBOX) |

### Layer 1 structural rule set

| Rule | Result |
|---|---|
| F1 fabricated verdict / backdoor write | ✅ clean — frontdoor SEP_IN SYS AXI via `SmcSysAxiItem`; no Force/deposit on proof path; ROM/efuse hex is post-PASS bring-up trailer |
| F2 can't-fail checker | ✅ clean — seq `resp_code == expected_resp` / `timeouts==0` / `error_responses==len(ERROR_PROBES)` and scoreboard `expected_resp` asserts are reachable FAIL-ON paths |
| E1 skip-to-pass | ✅ clean — monitor `expected_decerr_addrs` update is optional tally only; missing monitor does not mark pass; AXI path still scored |
| E2 empty phase | ✅ clean — alive baseline + 3 error probes + recovery read coded; 5 SYS AXI checks executed |
| S1 silent fail | ✅ clean — scoreboard/seq `assert` raise; timeout path raises in driver when `allow_timeout=False` |
| O1 checker disabled | ✅ clean — SYS AXI scoreboard analysis active (checks #1–#5 in log) |
| Phase-S obligations — L1 | 🟠 Major — FIND-001; else exact AXI resp codes, timeouts fail (`allow_timeout=False`), negative probes paired with ALIVE_SENTINEL OKAY baseline/recovery, seed logged, enrolled in `vplan_triplets.toml` (pulled by `all.toml`), no unconditional CHK token |
| Phase-S obligations — L2 (needs the card) | — not evaluated |

## Evidence appendix

<details>
<summary>Kept log + code proof-path notes</summary>

- Implementation: `hw/sys/smc/dv/cocotb/tests/smc_axi_error_response_depth_test.py`
- Sequence: `hw/sys/smc/dv/cocotb/seq_lib/smc_axi_error_response_depth_test_seq.py`
- Scoreboard (proof path): `hw/sys/smc/dv/cocotb/env/smc_scoreboard.py` `_check_sys_axi` (`expected_resp`)
- Driver: `hw/sys/smc/dv/cocotb/env/smc_sys_axi_agent.py` (`allow_error` / `timeout_ns` / `allow_timeout=False`)
- Log: `hw/sys/smc/dv/build/runs/20260806_094614__verilator__smc_axi_error_response_depth_test/smc_axi_error_response_depth_test/logs/smc_axi_error_response_depth_test.log`
  sha256 `6f73a775309d4073cab30625d9764890b91e350c2e51df24b252cf3f790c41f4` (matches claimed)
- Seed: 1 · simulator: verilator 5.050 2026-07-01 · model fingerprint `2c815fa08277`
- `result.json`: `status: PASS`, `exit_code: 0`, cocotb summary L337:
  `TESTS=1 PASS=1 FAIL=0 SKIP=0`
- Stimulus / observed:
  - ALIVE_SENTINEL `0xC0010018` OKAY (check #1, L280–L293; recovery check #5, L319–L324)
  - UNMAPPED_LOW `0xC0FFF000` DECERR (check #2, L295–L301)
  - UNMAPPED_HIGH `0xCFFFF000` DECERR (check #3, L303–L309)
  - GPIO_CTRL_ERR_SLAVE `0xC0400100` DECERR (check #4, L311–L317)
- Final seq gates reached: VIP details `csr_accesses=5 timeouts=0` /
  `error_responses=3`; monitor `OKAY=2, DECERR=3; 0 errors` (L326–L329)
- Addressing: generated `smc_addr` / `external_gpio_ctrl_addr` for ALIVE and
  GPIO_CTRL; hand hole offsets at seq `:22-23`
- Positive control: alive CSR OKAY before and after error probes
- Enrollment: `hw/sys/smc/dv/testlists/vplan_triplets.toml` (included by `all.toml`)
- Bring-up trailer (post-PASS flush): efuse/ROM hex preload — not used as AXI resp golden
- Entry gate / Layer 2 not evaluated (MODE=NO-CHECKBOX)
- Provenance: legacy (`test_author.run_id: unknown`)

</details>

<details>
<summary>PASS cite (kept log <code>6f73a775…</code>)</summary>

| Step | Line | What the log shows | Impl |
|---|---|---|---|
| alive baseline | 280–293 | OKAY read `0xc0010018` data `0x1f000000` | seq `:79` |
| UNMAPPED_LOW | 295–301 | DECERR `rresp: 3`, monitor "expected" | seq `:32` / `:81-82` |
| UNMAPPED_HIGH | 303–309 | DECERR `rresp: 3` | seq `:33` / `:81-82` |
| GPIO_CTRL_ERR_SLAVE | 311–317 | DECERR `rresp: 3` @ `0xc0400100` | seq `:34` / `:28` |
| alive recovery | 319–324 | OKAY read `0xc0010018` | seq `:84` |
| VIP / monitor | 326–329 | `error_responses=3`; `OKAY=2, DECERR=3` | test `:23-32` |
| cocotb summary | 331–337 | `PASS` / `PASS=1 FAIL=0` | — |

</details>

## Not concluded

- Whether these probes prove the SPEC fabric error/recovery properties the VPLAN names (O2) — Skill 3.
- Completeness against a feature_list — no inventory applies in STANDALONE-REQUEST.
- Any closure or PROVEN checker claim — MODE=NO-CHECKBOX forbids inventing checkers.

## Accepted waivers

| Finding | Rule | Where | Why | Approved by |
|---|---|---|---|---|
| — | — | — | none | — |
