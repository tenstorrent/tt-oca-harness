---
schema: dv-quality/v1
artifact: testcase-grade
testcase: smc_output_filter_remap_security_test
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
- path: hw/sys/smc/dv/build/runs/20260806_095046__verilator__smc_output_filter_remap_security_test/smc_output_filter_remap_security_test/logs/smc_output_filter_remap_security_test.log
  sha256: 27ccc7df48ebc96639537fdaf79ab3ddbea06abcd38c2976d8fe359ec19caf9d
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
  tag: '[NO-DUMMY-DEAD-CODE]'
  severity: Major
  artifact_ref: hw/sys/smc/dv/cocotb/seq_lib/smc_output_filter_remap_security_test_seq.py:8-48
  observed: >
    A same-named sequence class `smc_output_filter_remap_security_test_seq`
    performs ALIAS0/OUTBOUND0/OUTBOUND1 CSR read/write/restore depth checks
    with a real access-count assert
    (`assert self.accesses == expected_accesses`), but
    `smc_output_filter_remap_security_test.run_scenario` never imports or
    `start_seq`s it. Kept log shows only
    `output_fabric_pass_all_cfg_seq` /
    `output_fabric_block_write_cfg_seq` + JTAG AXI fabric traffic
    (STEP S1–S3); no ALIAS0_* CSR accesses appear. Dead code that resembles
    an active remap/filter CSR check misleads readers into believing remap
    programming was exercised. Most orphan addresses now use
    `smc_indexed_addr`, but `OUTBOUND1_FILTER_CONFIG` remains a hand-copied
    literal (`0xC001_6020`).
  closure_condition: >
    Either wire the sequence into `run_scenario` (and source every CSR
    address from generated `smc_reg` / `smc_addr_map` symbols), or
    delete/retire the orphan file and stop presenting a same-named remap
    CSR depth body that this test never runs.
  waived_by: null
- id: FIND-002
  tag: '[NO-BLIND-DELAY-SYNC]'
  severity: Major
  artifact_ref: hw/sys/smc/dv/cocotb/seq_lib/smc_output_fabric_vip_utils.py:193
  observed: >
    `check_output_responder_delta` waits
    `await ClockCycles(dut.clk_smc_i, 8)` then samples
    `tb_output_axi_*` counters/last_addr/last_wdata. JTAG AXI completions
    already used the frontdoor handshake; the fixed 8-cycle delay stands in
    for a settle/completion event on the TB observation path and is not
    itself a SPEC-bounded quantity under test. Called twice on this proof
    path (pass-all and post-block phases).
  closure_condition: >
    Replace the bare 8-cycle wait with an event/handshake-bounded wait that
    fails on timeout (`[TIMEOUT-MUST-FAIL]`), or sample the TB counters
    without a magic settle delay once observation is coupled to the AXI
    completion that updates them.
  waived_by: null
waivers: []
recommendation: NOT-READY
---

# Grade Report — smc_output_filter_remap_security_test (standalone Layer 1)

**VERDICT: 0/0 PROVEN — NOT READY** (mode NO-CHECKBOX, no_contract_reason STANDALONE-REQUEST)

| Mode | Entry gate | Checkers | Findings | Recommendation |
|---|---|---|---|---|
| `NO-CHECKBOX` | — NOT-EVALUATED | 0/0 PROVEN | 🟠 2 Major | ⛔ NOT-READY |

> No approved checkbox card or parent plan record governs this testcase. Layer 1 findings
> are the entire scope of this report. `NOT-READY` records the **absence of a closure
> claim, not a defect**. Kept log is a sim **PASS** (seed 1, verilator 5.050): outbound
> filter pass-all write/read then read-only blocked write (`DECERR`) with responder
> counters — Layer 2 entry is still not evaluated in this mode.

## DELTA (re-audit vs prior grade `0/0 NOT-READY` on log `ce215e36…`)

| Item | Prior (log `ce215e36…`, PASS) | This audit (log `27ccc7df…`, PASS) |
|---|---|---|
| Verdict | 0/0 PROVEN — NOT READY | 0/0 PROVEN — NOT READY |
| Findings | 🟠 2 Major | 🟠 2 Major |
| Prior FIND-001 orphan remap CSR seq | open Major `[NO-DUMMY-DEAD-CODE]` | **still open** as FIND-001 Major — still never `start_seq`'d; orphan mostly map-sourced now, one literal remains |
| Prior FIND-002 `ClockCycles(8)` | open Major `[NO-BLIND-DELAY-SYNC]` | **still open** as FIND-002 Major — helper unchanged at `smc_output_fabric_vip_utils.py:193` |
| Kept log | `ce215e36f5956bea8b14289fe9ecb432e9699907706f87709cec93e32373e45c` | `27ccc7df48ebc96639537fdaf79ab3ddbea06abcd38c2976d8fe359ec19caf9d` |
| repository_revision | `2ecc7b22…` | `c10b6d63…` |
| auditor.run_id | `cursor/grok/4.5` | `cursor/grok/4.5-reaudit-20260806` |
| Waivers carried | none signed (`waivers: []`) | none (nothing to drop; no signed entries) |

## Your to-do — 2 items (🟠 2 Major)

| # | Sev | Item |
|---|---|---|
| 1 | 🟠 Major | FIND-001 `[NO-DUMMY-DEAD-CODE]` — orphan same-named remap CSR seq never started |
| 2 | 🟠 Major | FIND-002 `[NO-BLIND-DELAY-SYNC]` — `check_output_responder_delta` `ClockCycles(8)` |

<details>
<summary>1. 🟠 Major — FIND-001 `[NO-DUMMY-DEAD-CODE]` at orphan remap CSR seq</summary>

`smc_output_filter_remap_security_test_seq.py` implements ALIAS0/OUTBOUND CSR
read/write/restore with a real access-count assert, but the live test never starts
it. Kept log only shows filter-config + JTAG fabric traffic. Orphan addresses are
mostly `smc_indexed_addr`-sourced; `OUTBOUND1_FILTER_CONFIG` is still a literal.

**Close when:** wire the seq (with map-sourced addresses) into `run_scenario`, or
retire the orphan and stop presenting a same-named remap CSR check that never runs.

</details>

<details>
<summary>2. 🟠 Major — FIND-002 `[NO-BLIND-DELAY-SYNC]` at responder-delta helper</summary>

`check_output_responder_delta` uses a fixed 8-cycle settle before sampling
`tb_output_axi_*` after AXI handshakes already completed.

**Close when:** event/handshake-bounded wait with timeout-must-fail, or drop the
magic delay once sampling is tied to the counter update event.

</details>

**Then:** leave enrolled under `STANDALONE-REQUEST`, or allocate a real IP pin + card via
`/dv_vplan_gen` before any closure claim. Re-invoke `/dv_test_audit` only after material
test/log changes. Do not invent a card here (`STANDALONE-REQUEST`).

## All checkers

| Checker | Grade | Proof class | Covers | Findings |
|---|---|---|---|---|
| — | — | — | — | no card checkers (MODE=NO-CHECKBOX) |

### Layer 1 structural rule set

| Rule | Result |
|---|---|
| F1 fabricated verdict / backdoor write | ✅ clean — frontdoor SEP_IN CSR program + JTAG AXI fabric; scoreboard compares DUT `rdata`/`resp` to independently supplied expecteds; no force/deposit on proof path |
| F2 can't-fail checker | ✅ clean — scoreboard `expect_error`/`expected`/`resp_ok`, test `assert resp_code == DECERR`, responder-delta asserts, and driver timeout `AssertionError` are reachable FAIL-ON paths |
| E1 skip-to-pass | ✅ clean — no missing-handle skip-to-pass; blocked path uses `expect_error=True` with scoreboard + exact DECERR assert |
| E2 empty phase | ✅ clean — live STEP S1–S3 perform real CSR writes and JTAG write/read/block traffic (orphan remap seq is FIND-001, not an empty live phase) |
| S1 silent fail | ✅ clean — mismatch/timeout/`resp_ok`/`resp_code` raise; no swallow-to-pass |
| O1 checker disabled | ✅ clean — SYS AXI scoreboard + output AXI monitor active (checks #1–#16; SYS_OUT 2R/1B) |
| Phase-S obligations — L1 | 🟠 Major — FIND-001 · FIND-002 |
| Phase-S obligations — L2 (needs the card) | — not evaluated |

## Evidence appendix

<details>
<summary>Kept log + code proof-path notes</summary>

- Log: `hw/sys/smc/dv/build/runs/20260806_095046__verilator__smc_output_filter_remap_security_test/smc_output_filter_remap_security_test/logs/smc_output_filter_remap_security_test.log`
  sha256 `27ccc7df48ebc96639537fdaf79ab3ddbea06abcd38c2976d8fe359ec19caf9d`
  (verified via `manifest.py hash-file`; matches invoker hint)
- Seed: 1 · simulator: verilator 5.050 2026-07-01 · model fingerprint `2c815fa08277`
- `result.json`: `status: PASS`, `exit_code: 0`, cocotb summary:
  `TESTS=1 PASS=1 FAIL=0 SKIP=0`
- Discovered seq on live path: `output_fabric_pass_all_cfg_seq` +
  `output_fabric_block_write_cfg_seq` from `smc_output_fabric_vip_utils.py`
  (same-named `smc_output_filter_remap_security_test_seq` is NOT started — FIND-001)
- Final assertion gate: blocked-write `assert resp_code == RESP_DECERR`, second
  `check_output_responder_delta`, X-resolvable asserts on `tb_output_axi_*`, then
  `SMC_005 scenario PASS` + protocol VIP `csr_accesses=16 timeouts=0`
- Live CSR addresses imported from PeakRDL `smc_reg.py`
  (`SMC_*_FILTER_CTRL_0__*_REG_ADDR` → `0xc0015000` / `0xc0016000` family); fabric
  window `0x0200_0000` is TB responder base (not an SMC CSR)
- Positive then negative: PASS_ALL write+read OKAY + responder delta, then
  READ_ONLY blocked write `bresp=3` with follow-up read still
  `0x1122334455667788` and write-count still 1
- Scoreboard `expect_error` path rejects OKAY/timeout on the blocked write; test
  further pins exact `RESP_DECERR`
- Driver FAIL-ON: `smc_sys_axi_agent.py:160-163` raises on unexpected AXI timeout
- Enrollment: `hw/sys/smc/dv/testlists/batch_d.toml`, `all.toml`, `vplan_triplets.toml`
- Bring-up trailer (post-PASS flush): efuse hex + ROM `$readmemh` — time-0 image load;
  not used as fabric golden substitution (policy §6 standing preload)
- No unexplained `ERROR`/`FATAL`/`Traceback` in the kept log
- Entry gate / Layer 2 not evaluated (MODE=NO-CHECKBOX)
- Provenance: legacy (`test_author.run_id: unknown`); auditor `run_id: cursor/grok/4.5-reaudit-20260806`

</details>

<details>
<summary>Stimulus / sample cites (kept log <code>27ccc7df…</code>)</summary>

| Step | Line (approx) | What the log shows | Impl |
|---|---|---|---|
| S1 pass-all CSR | 281–330 | INBOUND/OUTBOUND START/END/CONFIG writes OKAY | `output_fabric_pass_all_cfg_seq` |
| S2 fabric WR/RD | 331–356 | JTAG write/read `0x2000000` data match; CHK-OUTBOUND-PASS-ALL | `jtag_axi_*` + delta |
| S3 block-write cfg | 357–399 | OUTBOUND window + `FILTER_CONFIG=0x3011` | `output_fabric_block_write_cfg_seq` |
| blocked write | 400–416 | `bresp=3`; follow-up read still prior data; CHK-OUTBOUND-BLOCK-WRITE | test assert DECERR |
| NONVAC / VIP | 417–423 | writes=1 reads=2; SYS_OUT `2 R / 1 B`; VIP csr_accesses=16 | test + monitors |
| cocotb result | 424–430 | `PASS` / `TESTS=1 PASS=1 FAIL=0 SKIP=0` | — |

</details>

## Not concluded

- Whether filter allow/block at the fabric responder proves the SPEC remap/security
  properties implied by the test name (O2) — Skill 3.
- Completeness against a feature_list — no inventory applies in STANDALONE-REQUEST.
- Any closure or PROVEN checker claim — MODE=NO-CHECKBOX forbids inventing checkers.

## Accepted waivers

| Finding | Rule | Where | Why | Approved by |
|---|---|---|---|---|
| — | — | — | none | — |
