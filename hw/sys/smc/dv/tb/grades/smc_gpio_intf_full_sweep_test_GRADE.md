---
schema: dv-quality/v1
artifact: testcase-grade
testcase: smc_gpio_intf_full_sweep_test
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
- path: hw/sys/smc/dv/build/runs/20260806_094641__verilator__smc_gpio_intf_full_sweep_test/smc_gpio_intf_full_sweep_test/logs/smc_gpio_intf_full_sweep_test.log
  sha256: 0f0f01f28bbec6ec4f70d00edfbd140bf770cbe537f03f3704821e70b0aa6540
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
  artifact_ref: hw/sys/smc/dv/cocotb/seq_lib/smc_gpio_intf_full_sweep_test_seq.py:14
  observed: >-
    Register addresses and sweep count are now sourced from the generated map
    via `smc_indexed_addr("SMC_TOP_GPIO_INTF_DATA_CTRL_BASE_ADDR", idx)` and
    `GPIO_INTF_NUM` (`SMC_TOP_GPIO_INTF_NUM=0x41`); kept log walks
    `0xc0003000`…`0xc0003400` (65 OKAY reads). The allowed non-zero DATA_CTRL
    value remains a hand-copied literal `_GPIO_INTF_DEFAULT_BIT25 =
    0x0200_0000` instead of
    `GPIO_INTF__DATA_CTRL__LSIO_ENABLE_bm` from
    `hw/ip/gpio/regs/gen/c/gpio_intf.h` (same numeric `0x2000000` today).
    Correct identity, latent rot on field encode — Major per policy §3
    conditional adjustment.
  closure_condition: >-
    Import `GPIO_INTF__DATA_CTRL__LSIO_ENABLE_bm` (or an `smc_addr_map` helper
    that loads `gpio_intf.h` field masks) and use that symbol as the allowed
    HW-tie bit; drop the parallel numeric constant. Re-keep a PASS log.
  waived_by: null
- id: FIND-002
  tag: '[EXACT-EXPECTATION]'
  severity: Major
  artifact_ref: hw/sys/smc/dv/cocotb/seq_lib/smc_gpio_intf_full_sweep_test_seq.py:22-25
  observed: >-
    Per-entry check is membership `assert got in (0x0, _GPIO_INTF_DEFAULT_BIT25)`
    with scoreboard `expected=None` (log checks #1–#65 `exp=None ok=True`). Kept
    log shows a mixed window: most entries return `0x0`, at least 18 return
    `0x2000000` (e.g. `0xc0003390`, `0xc00033e0`…`0xc0003400`), but the sequence
    never states which indices must show LSIO_ENABLE vs reset-0. An entry that
    flips between the two accepted values still passes; activity + set
    membership is not an exact per-instance reset/HW-tie contract.
  closure_condition: >-
    Derive a per-index expected DATA_CTRL value from the TB/SPEC HW-tie model
    (or a fixed authoritative table) using `gpio_intf.h` field symbols; assert
    exact equality (scoreboard `expected=` or sequence assert); fail on
    mismatch. Re-keep a PASS log.
  waived_by: null
- id: FIND-003
  tag: '[NO-DUMMY-DEAD-CODE]'
  severity: Minor
  artifact_ref: hw/sys/smc/dv/cocotb/tests/smc_gpio_intf_full_sweep_test.py:2-28
  observed: >-
    Test/sequence/VIP prose still says "GPIO_INTF full 68-entry sweep" (module
    docstring, class docstring, `record_protocol_vip` details; kept log L20 /
    L743), while the sequence sweeps `range(GPIO_INTF_NUM)` = 65
    (`SMC_TOP_GPIO_INTF_NUM=0x41`) and the VIP records `csr_accesses=65`. The
    stale 68-entry legend resembles the pre-map-fix count and misstates the
    proven window size.
  closure_condition: >-
    Align all test/seq/VIP prose with the generated count (65 /
    `SMC_TOP_GPIO_INTF_NUM`) or stop claiming a fixed numeric size in details.
  waived_by: null
waivers: []
recommendation: NOT-READY
---

# Grade Report — smc_gpio_intf_full_sweep_test (standalone Layer 1)

**VERDICT: 0/0 PROVEN — NOT READY** (mode NO-CHECKBOX, no_contract_reason STANDALONE-REQUEST)

| Mode | Entry gate | Checkers | Findings | Recommendation |
|---|---|---|---|---|
| `NO-CHECKBOX` | — NOT-EVALUATED | 0/0 PROVEN | 🟠 2 Major · 🟡 1 Minor | ⛔ NOT-READY |

> No approved checkbox card or parent plan record governs this testcase
> (`STANDALONE-REQUEST` / active-regression L1 wave). Layer 1 findings are the entire
> scope of this report. `NOT-READY` records the **absence of a closure claim, not a
> defect**. Kept log is a sim **PASS** (seed 1): 65 SEP_IN GPIO_INTF DATA_CTRL reads
> OKAY + `accesses == GPIO_INTF_NUM` — Layer 2 entry is still not evaluated in this mode.

## DELTA (re-audit vs prior grade)

| Item | Prior (log `57c5779a…`, FAIL) | This audit (log `0f0f01f2…`, PASS) |
|---|---|---|
| Verdict | 0/0 PROVEN — NOT READY | 0/0 PROVEN — NOT READY |
| Findings | 🔴 1 Blocking | 🟠 2 Major · 🟡 1 Minor |
| Prior FIND-001 address | open Blocking — base `0xC0004000` = AVSBus, not GPIO_INTF; count 68 | **closed** — `smc_indexed_addr("SMC_TOP_GPIO_INTF_DATA_CTRL_BASE_ADDR", idx)` + `GPIO_INTF_NUM=65`; log starts `@0xc0003000` |
| Field encode / exact expect | bundled under prior Blocking false identity | **open** FIND-001 Major hand-copied `0x0200_0000`; FIND-002 Major set-membership vs per-index expect |
| Stale "68-entry" prose | present under wrong-map FAIL | **open** FIND-003 Minor — prose still says 68; VIP `csr_accesses=65` |
| Kept log | FAIL scoreboard `#3` `@0xc0004020` exp `0x0` got `0x220000` | PASS seed=1; checks #1–#65; `TESTS=1 PASS=1 FAIL=0` |
| Waivers carried | none signed (`waivers: []`; nothing to drop) | none |

## Your to-do — 3 items (🟠 2 Major · 🟡 1 Minor)

| # | Sev | Item |
|---|---|---|
| 1 | 🟠 Major | FIND-001 `[ADDRESS-FROM-AUTHORITATIVE-MAP]` — hand-copied LSIO_ENABLE mask `0x0200_0000` |
| 2 | 🟠 Major | FIND-002 `[EXACT-EXPECTATION]` — `{0, bit25}` membership instead of per-index expect |
| 3 | 🟡 Minor | FIND-003 `[NO-DUMMY-DEAD-CODE]` — stale "68-entry" prose vs generated count 65 |

<details>
<summary>1. 🟠 Major — FIND-001 <code>[ADDRESS-FROM-AUTHORITATIVE-MAP]</code> — hand-copied LSIO_ENABLE mask</summary>

- **Where:** `hw/sys/smc/dv/cocotb/seq_lib/smc_gpio_intf_full_sweep_test_seq.py:14`
- **Observed:** Address/count now PeakRDL-sourced; allowed non-zero value is still
  literal `_GPIO_INTF_DEFAULT_BIT25 = 0x0200_0000`. Generated
  `GPIO_INTF__DATA_CTRL__LSIO_ENABLE_bm` in `gpio_intf.h` is the same numeric today.
- **Closure:** Import/use `GPIO_INTF__DATA_CTRL__LSIO_ENABLE_bm` (or map helper);
  drop the parallel constant; re-keep PASS log.

</details>

<details>
<summary>2. 🟠 Major — FIND-002 <code>[EXACT-EXPECTATION]</code> — set membership, not per-index expect</summary>

- **Where:** `hw/sys/smc/dv/cocotb/seq_lib/smc_gpio_intf_full_sweep_test_seq.py:22-25`
- **Observed:** `got in (0x0, bit25)` with scoreboard `exp=None`. Log mixes `0x0` and
  `0x2000000` across the 65-entry window without stating which indices must show
  LSIO_ENABLE; flip within the set still passes.
- **Closure:** Per-index expected from TB/SPEC HW-tie model + field symbols; exact
  compare; re-keep PASS log.

</details>

<details>
<summary>3. 🟡 Minor — FIND-003 <code>[NO-DUMMY-DEAD-CODE]</code> — stale 68-entry legend</summary>

- **Where:** `hw/sys/smc/dv/cocotb/tests/smc_gpio_intf_full_sweep_test.py:2-28`
  (and seq/VIP details; log L20 / L743)
- **Observed:** Prose claims "68-entry" while sweep/`csr_accesses` are 65 from
  `SMC_TOP_GPIO_INTF_NUM`.
- **Closure:** Align prose with generated count (or stop hard-coding the size in details).

</details>

**Then:** owner sources the LSIO_ENABLE mask, pins per-index expects, fixes the 68→65
prose, re-runs seed 1, keeps a PASS log, then re-invoke
`/dv_test_audit smc_gpio_intf_full_sweep_test`. Do not invent a card here
(`STANDALONE-REQUEST`).

## All checkers

| Checker | Grade | Proof class | Covers | Findings |
|---|---|---|---|---|
| — | — | — | — | no card checkers (MODE=NO-CHECKBOX) |

### Layer 1 structural rule set

| Rule | Result |
|---|---|
| F1 fabricated verdict / backdoor write | ✅ clean — frontdoor SEP_IN AXI CSR reads; sequence compares DUT `rdata` to a fixed allowed set; no force/deposit on proof path |
| F2 can't-fail checker | ✅ clean — `assert got in (…)`, `assert accesses == GPIO_INTF_NUM`, and driver/scoreboard resp paths are reachable FAIL-ON |
| E1 skip-to-pass | ✅ clean — no missing-handle skip-to-pass; full 65-entry AXI path ran to completion |
| E2 empty phase | ✅ clean — 65 real CSR reads issued (`csr_accesses=65`) |
| S1 silent fail | ✅ clean — mismatch raises `AssertionError`; no swallow-to-pass |
| O1 checker disabled | ✅ clean — SYS AXI scoreboard active (checks #1–#65); sequence value gate active |
| Phase-S obligations — L1 | 🟠 Major — FIND-001 `[ADDRESS-FROM-AUTHORITATIVE-MAP]` (field mask) · FIND-002 `[EXACT-EXPECTATION]`; 🟡 Minor — FIND-003 `[NO-DUMMY-DEAD-CODE]`; else addresses/count from PeakRDL, force-free AXI, seed logged, enrolled in `p1_coverage_gap_r3.toml`, timeout/resp_ok path present, final access-count gate reached, ROM/efuse preload is post-PASS trailer |
| Phase-S obligations — L2 (needs the card) | — not evaluated |

## Evidence appendix

<details>
<summary>Kept log + code proof-path notes</summary>

- Log: `hw/sys/smc/dv/build/runs/20260806_094641__verilator__smc_gpio_intf_full_sweep_test/smc_gpio_intf_full_sweep_test/logs/smc_gpio_intf_full_sweep_test.log`
  sha256 `0f0f01f28bbec6ec4f70d00edfbd140bf770cbe537f03f3704821e70b0aa6540`
  (verified via `sha256sum`; matches invoker path)
- Seed: 1 · simulator: verilator 5.050 2026-07-01 · model fingerprint `2c815fa08277`
- Cocotb summary L752–L754: `smc_gpio_intf_full_sweep_test ... PASS` /
  `TESTS=1 PASS=1 FAIL=0 SKIP=0`
- Final gate: seq `assert self.accesses == _GPIO_INTF_COUNT` reached; protocol VIP
  `csr_accesses=65 timeouts=0 passed=True` (L743–L744)
- Address window: first read `@0xc0003000` (L280–L293 check #1); last
  `@0xc0003400` (L736–L741 check #65) — matches
  `SMC_TOP_GPIO_INTF_DATA_CTRL_BASE_ADDR(idx)` / `SMC_TOP_GPIO_INTF_NUM=0x41`
- Mixed DATA_CTRL: ≥18 entries return `0x2000000` (LSIO_ENABLE bit25), remainder `0x0`;
  membership assert accepts both
- Test: `hw/sys/smc/dv/cocotb/tests/smc_gpio_intf_full_sweep_test.py` starts
  `smc_gpio_intf_full_sweep_test_seq` on `sys_axi_agent.sequencer`
- Seq: `smc_gpio_intf_full_sweep_test_seq.py` — PeakRDL address/count; hand literal
  bit25; `got in (0, bit25)`
- Authoritative field: `hw/ip/gpio/regs/gen/c/gpio_intf.h`
  `GPIO_INTF__DATA_CTRL__LSIO_ENABLE_bm 0x2000000` (unused by seq)
- Enrollment: `hw/sys/smc/dv/testlists/p1_coverage_gap_r3.toml`
- Bring-up trailer (post-PASS flush): efuse hex + ROM `$readmemh` — time-0 image load;
  not used as GPIO golden on this proof path
- No unexplained `ERROR`/`FATAL`/`Traceback` in the kept log
- Entry gate / Layer 2 not evaluated (`MODE=NO-CHECKBOX`; `entry_status: NOT-EVALUATED`)
- Provenance: legacy (`test_author.run_id: unknown`); auditor
  `run_id: cursor/grok/4.5-reaudit-20260806`

</details>

<details>
<summary>Stimulus / sample cites (kept log <code>0f0f01f2…</code>)</summary>

| Step | Line (approx) | What the log shows | Impl |
|---|---|---|---|
| bring-up | 266–278 | powergood + cold release | `smc_base_test` |
| AXI read idx0 | 280–293 | `0xc0003000 -> 0x0` OKAY; scoreboard #1 `exp=None` | seq `:19-25` |
| AXI read mid | 691–692 | `0xc0003390 -> 0x2000000` OKAY; check #58 | seq |
| AXI read last | 736–741 | `0xc0003400 -> 0x2000000` OKAY; check #65 | seq |
| protocol VIP | 743–744 | `csr_accesses=65 timeouts=0 passed=True` (details still say 68-entry) | test `:22-28` |
| AXI monitor | 746 | `65 R beats; OKAY=65; 0 errors` | monitor |
| cocotb result | 748–754 | `PASS` / `TESTS=1 PASS=1 FAIL=0` | — |

</details>

## Not concluded

- Whether a GPIO_INTF DATA_CTRL reset/HW-tie sweep proves the SPEC properties a future
  card would require (O2) — Skill 3.
- Completeness against a feature_list — no inventory applies in STANDALONE-REQUEST.
- Any closure or PROVEN checker claim — MODE=NO-CHECKBOX forbids inventing checkers.

## Accepted waivers

| Finding | Rule | Where | Why | Approved by |
|---|---|---|---|---|
| — | — | — | none | — |
