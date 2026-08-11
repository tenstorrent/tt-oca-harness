---
schema: dv-quality/v1
artifact: testcase-grade
testcase: smc_i3c_to_fabric_test
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
- path: hw/sys/smc/dv/build/runs/20260806_094553__verilator__smc_i3c_to_fabric_test/smc_i3c_to_fabric_test/logs/smc_i3c_to_fabric_test.log
  sha256: c3e78c3f02cf9796e459cf49401f32247941f153dd7319b67d114fc4c4f19a33
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
  tag: '[NO-BLIND-DELAY-SYNC]'
  severity: Major
  artifact_ref: hw/sys/smc/dv/cocotb/seq_lib/smc_i3c_vip_utils.py:97
  observed: >-
    `i3c_directed_sdr_write_proof` still uses bare `await Timer(1000, units="ns")`
    to settle the I3CTarget `_run` coroutine before SDR traffic. That helper is
    on this test's post-sequence proof path (`check_i3c0_external_pull_low`
    always calls it; the sequence also calls it when VIP import succeeds). On
    this kept log VIP bind failed so the Timer was not reached, but the sync
    remains a fixed delay standing in for a target-ready / handshake condition
    with no bounded event wait that fails on expiry.
  closure_condition: >-
    Replace the settle `Timer(1000)` with an event/handshake wait for the
    target coroutine ready state (or an equivalent VIP-documented ready
    signal) under a bounded timeout that fails the step
    (`[TIMEOUT-MUST-FAIL]`); do not use a magic nanosecond delay as sync.
  waived_by: null
waivers: []
recommendation: NOT-READY
---

# Grade Report — smc_i3c_to_fabric_test (standalone Layer 1)

**VERDICT: 0/0 PROVEN — NOT READY** (mode NO-CHECKBOX, no_contract_reason STANDALONE-REQUEST)

| Mode | Entry gate | Checkers | Findings | Recommendation |
|---|---|---|---|---|
| `NO-CHECKBOX` | — NOT-EVALUATED | 0/0 PROVEN | 🟠 1 Major | ⛔ NOT-READY |

> No approved checkbox card or parent plan record governs this testcase
> (`STANDALONE-REQUEST` / active-regression L1 wave). Layer 1 findings are the entire
> scope of this report. `NOT-READY` records the **absence of a closure claim, not a
> defect** in the test by itself. Kept log is a sim **PASS** (seed 1): CLOCK_GATE
> RMW + I3C0 HCI_VERSION OKAY/`0x120` + pin pull-low asserts completed;
> `TESTS=1 PASS=1 FAIL=0 SKIP=0`. Layer 2 entry is still not evaluated in this mode.

## DELTA (re-audit vs prior grade `0/0 NOT-READY` on log `547ea8e1…`)

| Item | Prior (log `547ea8e1…`, FAIL) | This audit (log `c3e78c3f…`, PASS) |
|---|---|---|
| Verdict | 0/0 PROVEN — NOT READY | 0/0 PROVEN — NOT READY |
| Findings | 🟠 2 Major | 🟠 1 Major |
| Prior FIND-001 `[ADDRESS-FROM-AUTHORITATIVE-MAP]` (`I3C_CG_EN = 1 << 9`) | open Major | **cleared** — seq imports `I3C_CG_EN` from `smc_addr_map` → generated `SMC_BASE_CONFIG__CLOCK_GATE_CONTROL__I3C_CG_EN_bm` |
| Prior FIND-002 `[NO-BLIND-DELAY-SYNC]` (`Timer(1000)` in VIP helper) | open Major | **still open** as FIND-001 Major — same `smc_i3c_vip_utils.py:97` settle delay |
| I3C0 window expectation | stub SLVERR + `0xBADCAB1E` → scoreboard FAIL on OKAY/`0x120` | **real-core** OKAY + `I3C_HCI_VERSION_RESET=0x120` asserts; scoreboard check #6 OKAY |
| Kept log | FAIL seed=1 | PASS seed=1; VIP optional bind still skipped (`cocotbext-i3c` absent); pull-low pin asserts ran |
| Waivers carried | none signed (`waivers: []`; nothing to drop) | none |

## Your to-do — 1 items (🟠 1 Major)

| # | Kind | Id | Severity / grade | Where |
|---|---|---|---|---|
| 1 | finding | FIND-001 | 🟠 Major | `smc_i3c_vip_utils.py:97` |

<details>
<summary>1. FIND-001 — 🟠 Major <code>[NO-BLIND-DELAY-SYNC]</code> — VIP settle Timer(1000 ns)</summary>

- **Where:** `hw/sys/smc/dv/cocotb/seq_lib/smc_i3c_vip_utils.py:97`
- **Observed:** Bare `Timer(1000, units="ns")` before SDR drive in `i3c_directed_sdr_write_proof`, invoked from this test's `check_i3c0_external_pull_low` path (and optional sequence VIP proof). This run skipped before the Timer (VIP unavailable), but the helper still syncs with a magic delay when VIP binds.
- **Closure:** Event/handshake + bounded timeout that fails; no magic delay sync.

</details>

**Then:** owner remediates FIND-001 (VIP ready handshake / `[TIMEOUT-MUST-FAIL]`), re-keeps a PASS log, and re-invokes `/dv_test_audit smc_i3c_to_fabric_test`. Do not invent a card here (`STANDALONE-REQUEST`).

## All checkers

| Checker | Grade | Proof class | Covers | Findings |
|---|---|---|---|---|
| — | — | — | — | no card checkers (MODE=NO-CHECKBOX) |

### Layer 1 structural rule set

| Rule | Result |
|---|---|
| F1 fabricated verdict / backdoor write | ✅ clean — frontdoor SEP_IN SYS AXI via `SmcSysAxiItem`; HCI_VERSION compared to named constant; no force/deposit on CSR path (ROM/efuse preload is post-result bring-up trailer) |
| F2 can't-fail checker | ✅ clean — seq asserts `reads == 4`, `last_resp_code == 0`, `rdata == I3C_HCI_VERSION_RESET`; CG enable/restore use scoreboard `expected=`; pull-low pin asserts raise on mismatch |
| E1 skip-to-pass | ✅ clean — optional cocotbext-i3c VIP bind soft-skips with warning; primary gate remains CLOCK_GATE RMW + HCI_VERSION + pull-low pin checks (all executed this PASS) |
| E2 empty phase | ✅ clean — CLOCK_GATE enable/restore + I3C0 HCI_VERSION read + pull-low 4-leg pin sweep executed (6 SYS AXI checks + protocol VIP record) |
| S1 silent fail | ✅ clean — mismatch raises in seq asserts / `smc_scoreboard._check_sys_axi` / pull-low `assert`; AXI timeout raises in driver |
| O1 checker disabled | ✅ clean — SYS AXI scoreboard active (checks #1–#6); protocol VIP analysis recorded; no disabled scoreboard gate for the CSR claim |
| Phase-S obligations — L1 | 🟠 Major — FIND-001; PeakRDL addresses for CLOCK_GATE / `OCA_I3C_WRAP_0` and `I3C_CG_EN` via `smc_addr_map`; seed logged; enrolled in `batch_c.toml` / `all.toml` / `vplan_triplets.toml`; VIP settle uses blind delay; CG OKAY positive control before HCI_VERSION read; no unconditional CHK success token |
| Phase-S obligations — L2 (needs the card) | — not evaluated |

## Evidence appendix

<details>
<summary>Kept log + code proof-path notes</summary>

- Implementation: `hw/sys/smc/dv/cocotb/tests/smc_i3c_to_fabric_test.py`
  sha256 `d6ee652d86ffb3c07b59e46d02049cc19e08cac9f32a623c4f95e0308ee45f10`
- Sequence: `hw/sys/smc/dv/cocotb/seq_lib/smc_i3c_to_fabric_test_seq.py`
  sha256 `c46fa0e4dfaa007902af3f5f9bf6f2318ae9c48168f9f34242a08489be78ef19`
- Addr map: `hw/sys/smc/dv/cocotb/seq_lib/smc_addr_map.py`
  sha256 `cc43ce2029ebd0ceda50d06c3f9e7e8b7d04bcdd0b63510999ae7a85afd9c803`
- VIP / pull-low helper: `hw/sys/smc/dv/cocotb/seq_lib/smc_i3c_vip_utils.py`
  sha256 `9b986d53efbdeed7ca889e479622b1f0f32946c2d9b7e6fa5903a630458aaa5e`
- Scoreboard / driver (proof path): `smc_scoreboard._check_sys_axi`, `smc_sys_axi_agent._drive`
- Log: `hw/sys/smc/dv/build/runs/20260806_094553__verilator__smc_i3c_to_fabric_test/smc_i3c_to_fabric_test/logs/smc_i3c_to_fabric_test.log`
  sha256 `c3e78c3f02cf9796e459cf49401f32247941f153dd7319b67d114fc4c4f19a33`
  (verified via `manifest.py hash-file`; matches invoker hint)
- Seed: 1 · simulator: verilator 5.050 2026-07-01 · model fingerprint `2c815fa08277`
- `result.json`: `status: PASS`, `exit_code: 0`, cocotb summary L355–L357:
  `TESTS=1 PASS=1 FAIL=0 SKIP=0`
- Addressing: PeakRDL via `smc_addr` —
  `SMC_TOP_SMC_BASE_CONFIG_CLOCK_GATE_CONTROL_BASE_ADDR` / `SMC_TOP_OCA_I3C_WRAP_0_BASE_ADDR`;
  field `I3C_CG_EN` from generated `SMC_BASE_CONFIG__CLOCK_GATE_CONTROL__I3C_CG_EN_bm`
- Expected I3C completion: OKAY + `I3C_HCI_VERSION_RESET=0x120`
- Observed I3C completion (log L333–L336): `rresp=0` OKAY, data `20 01 00 00` → `rdata=0x120`
- VIP: bind skipped — `cocotbext-i3c not available` (L268–L269, L338–L345); SDR loopback skipped; pull-low pin asserts still reached (L346)
- Enrollment: `hw/sys/smc/dv/testlists/batch_c.toml`, `all.toml`, `vplan_triplets.toml`
- Bring-up trailer: efuse/ROM hex preload after cocotb PASS; not used as CSR golden
- Entry gate / Layer 2 not evaluated (MODE=NO-CHECKBOX)
- Provenance: legacy (`test_author.run_id: unknown`)

</details>

<details>
<summary>Stimulus / sample cites (kept log <code>c3e78c3f…</code>)</summary>

| Step | Line (approx) | What the log shows | Impl |
|---|---|---|---|
| VIP bind | 268–269 | cocotbext-i3c unavailable; bind skipped | seq `:77-79`, utils |
| CG read | 284–295 | `0xc0010018` → `0x1f000000` OKAY | seq `:81-83` |
| CG enable wr/rd | 299–315 | write `0x1f000200`, readback match | seq `:84-86` |
| CG restore wr/rd | 319–329 | restore `0x1f000000`, readback match | seq `:88-95` |
| I3C0 HCI_VERSION | 333–336 | `0xc003a000` → OKAY `rdata=0x120` | seq `:98-107` |
| VIP / SDR skip | 338–345 | loopback skipped (wrapper unavailable) | utils `:93-95` |
| pull-low + VIP record | 346–348 | protocol VIP `passed=True` pull-low details | test `:22-28`, utils `:112-149` |
| cocotb result | 351–357 | `PASS` / `TESTS=1 PASS=1 FAIL=0 SKIP=0` | — |

</details>

## Not concluded

- Whether fabric→I3C decode / HCI_VERSION behavior matches the SPEC properties a future card would require (O2) — Skill 3.
- Completeness against a feature_list — no inventory applies in STANDALONE-REQUEST.
- Any closure or PROVEN checker claim — MODE=NO-CHECKBOX forbids inventing checkers.

## Accepted waivers

| Finding | Rule | Where | Why | Approved by |
|---|---|---|---|---|
| — | — | — | none | — |
