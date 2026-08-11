---
schema: dv-quality/v1
artifact: testcase-grade
testcase: smc_zeroer_regclk_cg_test
ip: SMC_CLOCK_GATING_P2
anchor: smc_zeroer_regclk_cg_test
mode: CHECKBOX
no_contract_reason: null
entry_status: PASS
repository_revision: 2ecc7b227e3926b253c65b5aac21239eec24ba5f
spec:
- path: hw/sys/smc/doc/index.adoc
  revision: 2ecc7b227e3926b253c65b5aac21239eec24ba5f
- path: hw/sys/smc/doc/overview.adoc
  revision: 2f40548ea787240680a1c45ab75b8729e9620778
- path: hw/sys/smc/doc/clk_rst.adoc
  revision: 2f40548ea787240680a1c45ab75b8729e9620778
- path: hw/sys/smc/doc/port_table.adoc
  revision: 2ecc7b227e3926b253c65b5aac21239eec24ba5f
- path: hw/sys/smc/doc/dma.adoc
  revision: e2aae39953bb8001c7c20e3afd3956e68c22440c
- path: hw/sys/smc/doc/zeroer.adoc
  revision: 2f40548ea787240680a1c45ab75b8729e9620778
- path: hw/sys/smc/doc/periphs.adoc
  revision: ffc8cdcc349e1e01a2b970442a01070b1c62c0d7
- path: hw/sys/smc/doc/fabric.adoc
  revision: ffc8cdcc349e1e01a2b970442a01070b1c62c0d7
- path: hw/sys/smc/doc/memmap.adoc
  revision: 2ecc7b227e3926b253c65b5aac21239eec24ba5f
card_sha256: 93666c6c76e78b0f181dba725025d1652ff5407526e20c4421403218b24e290e
card_revision: 1
card_path: hw/sys/smc/dv/tb/SMC_CLOCK_GATING_P2_VPLAN_DETAIL.md
testcase_plan:
  path: hw/sys/smc/dv/tb/SMC_CLOCK_GATING_P2_TESTCASE_PLAN.md
  plan_revision: 1
  testcase_revision: 1
  testcase_record_sha256: 49c886a759cc50a15a1dfbc1bc3e0e51ad3cfa62eb333bbc7b397b689df7f484
  parent_approved: true
evidence_class: frontdoor-func
closure_tier: A
quality_policy:
  path: /home/minshaoho/.claude/skills/dv_common/DV_QUALITY_POLICY.md
  revision: 51a3357d9c31a018d69451b055bc956c089af26e1051368e25ce396c84ac2a75
build_config: default
simulator: verilator
simulator_version: 5.050 2026-07-01
compile_target: default
model_fingerprint: 2c815fa08277
compile_inputs_sha256: null
seeds: [1]
logs:
- path: hw/sys/smc/dv/build/runs/20260805_091748__verilator__smc_zeroer_regclk_cg_test/smc_zeroer_regclk_cg_test/logs/smc_zeroer_regclk_cg_test.log
  sha256: f6d7df5fd00b9f40a4e5cc728f7ed4afbb2a364d6b4718c25ea58513c539d111
test_author:
  human_id: minshaoho
  run_id: dv_test_impl-SMC_CG_P2_003-2026-08-05T09:17:48Z
  model:
    provider: cursor
    family: claude
    version: sonnet-5
auditor:
  human_id: minshaoho
  run_id: dv_test_audit-SMC_CG_P2_003-fresh-3a7c92e1-2026-08-05T17:21:00+08:00
  model:
    provider: cursor
    family: claude
    version: sonnet-5
exceptions: []
checkers:
- id: CHK-ZEROER-REGCLK-UNGATE
  checks_steps: [S2]
  proves: [SMC-CG-ZEROER-REGCLK]
  covers: [SMC-CG-ZEROER-REGCLK.S1]
  proof_class: LIVE
  expect_source: 'hw/sys/smc/doc/zeroer.adoc §Clock Gating (Clock Gating Control table) @ 2f40548ea787240680a1c45ab75b8729e9620778'
  grade: PROVEN
  evidence:
  - token: 'CHK-ZEROER-REGCLK-UNGATE: immediately-after(resume_delta=1) long-after(resume_delta=1) back-to-back(resume_delta_a=1,resume_delta_b=1) ungate_bound_smc_cycles=32'
    log_sha256: f6d7df5fd00b9f40a4e5cc728f7ed4afbb2a364d6b4718c25ea58513c539d111
    line: 525
    seed: 1
    implementation_path: hw/sys/smc/dv/cocotb/seq_lib/smc_zeroer_regclk_cg_test_seq.py:225
  lifecycle_results: null
  coverage_results:
  - key: SMC-CG-ZEROER-REGCLK.S1
    method: DIRECTED
    required_cells: [access-immediately-after-reg_clk-gates, access-long-after-reg_clk-gates, back-to-back-accesses-across-gate-boundary]
    achieved_cells: [access-immediately-after-reg_clk-gates, access-long-after-reg_clk-gates, back-to-back-accesses-across-gate-boundary]
    random_knobs: []
    resolved_knobs: []
    min_seeds: 1
    actual_seeds: [1]
    required_artifact: null
    coverage_artifacts:
    - hw/sys/smc/dv/build/runs/20260805_091748__verilator__smc_zeroer_regclk_cg_test/smc_zeroer_regclk_cg_test/logs/smc_zeroer_regclk_cg_test.log#f6d7df5fd00b9f40a4e5cc728f7ed4afbb2a364d6b4718c25ea58513c539d111
    satisfied: true
  linked_issue: null
  finding_ids: []
  remediation: null
- id: CHK-ZEROER-REGCLK-ACCESS-COMPLETE
  checks_steps: [S2]
  proves: [SMC-CG-ZEROER-REGCLK]
  covers: [SMC-CG-ZEROER-REGCLK.S1]
  proof_class: LIVE
  expect_source: 'hw/sys/smc/doc/zeroer.adoc §Operation Control @ 2f40548ea787240680a1c45ab75b8729e9620778; SF-004 resolution note (SMC_CLOCK_GATING_P2_SPEC_REVIEW.md) -- pending-access service must complete within the card''s own declared bounded wait'
  grade: PROVEN
  evidence:
  - token: 'CHK-ZEROER-REGCLK-ACCESS-COMPLETE: immediately-after(written=0xa5a50001,readback=0xa5a50001,match=1) long-after(written=0xa5a50002,readback=0xa5a50002,match=1) back-to-back(written_a=0xa5a50003,written_b=0xa5a50004,readback=0xa5a50004,match=1) service_latency_bound_smc_cycles=128'
    log_sha256: f6d7df5fd00b9f40a4e5cc728f7ed4afbb2a364d6b4718c25ea58513c539d111
    line: 526
    seed: 1
    implementation_path: hw/sys/smc/dv/cocotb/seq_lib/smc_zeroer_regclk_cg_test_seq.py:229
  lifecycle_results: null
  coverage_results:
  - key: SMC-CG-ZEROER-REGCLK.S1
    method: DIRECTED
    required_cells: [access-immediately-after-reg_clk-gates, access-long-after-reg_clk-gates, back-to-back-accesses-across-gate-boundary]
    achieved_cells: [access-immediately-after-reg_clk-gates, access-long-after-reg_clk-gates, back-to-back-accesses-across-gate-boundary]
    random_knobs: []
    resolved_knobs: []
    min_seeds: 1
    actual_seeds: [1]
    required_artifact: null
    coverage_artifacts:
    - hw/sys/smc/dv/build/runs/20260805_091748__verilator__smc_zeroer_regclk_cg_test/smc_zeroer_regclk_cg_test/logs/smc_zeroer_regclk_cg_test.log#f6d7df5fd00b9f40a4e5cc728f7ed4afbb2a364d6b4718c25ea58513c539d111
    satisfied: true
  linked_issue: null
  finding_ids: []
  remediation: null
- id: CHK-NONVAC
  checks_steps: [S1, S2]
  proves: []
  covers: []
  proof_class: INTEGRITY
  expect_source: approved card ordering contract
  grade: PROVEN
  evidence:
  - token: 'CHK-NONVAC: SETUP < REG_CLK-GATED-BASELINE < ACCESS-SWEEP(3-cells) < PASS'
    log_sha256: f6d7df5fd00b9f40a4e5cc728f7ed4afbb2a364d6b4718c25ea58513c539d111
    line: 529
    seed: 1
    implementation_path: hw/sys/smc/dv/cocotb/seq_lib/smc_zeroer_regclk_cg_test_seq.py:362
  lifecycle_results: null
  coverage_results: []
  linked_issue: null
  finding_ids: []
  remediation: null
- id: CHK-TIMEOUT-PATHS
  checks_steps: [S3]
  proves: []
  covers: []
  proof_class: INTEGRITY
  expect_source: approved card timeout contract
  grade: PROVEN
  evidence:
  - token: 'CHK-TIMEOUT-PATHS: ungate_bound_smc_cycles=32 service_bound_smc_cycles=128 long_idle_cycles=40 expired=0 last_reg_clk_enable=0 last_bus_active=0'
    log_sha256: f6d7df5fd00b9f40a4e5cc728f7ed4afbb2a364d6b4718c25ea58513c539d111
    line: 528
    seed: 1
    implementation_path: hw/sys/smc/dv/cocotb/seq_lib/smc_zeroer_regclk_cg_test_seq.py:349
  lifecycle_results: null
  coverage_results: []
  linked_issue: null
  finding_ids: []
  remediation: null
findings: []
waivers: []
recommendation: EVIDENCE-CLOSED-AWAITING-SIGNOFF
---

# Grade Report — smc_zeroer_regclk_cg_test (SMC_CG_P2_003, IP SMC_CLOCK_GATING_P2)

**VERDICT: 4/4 PROVEN — EVIDENCE-CLOSED-AWAITING-SIGNOFF** (mode CHECKBOX, entry PASS)

| Mode | Entry gate | Checkers | Findings | Recommendation |
|---|---|---|---|---|
| `CHECKBOX` | ✅ PASS | 4/4 PROVEN | none | ✅ EVIDENCE-CLOSED-AWAITING-SIGNOFF |

**SIGNOFF RECORDED** — see [Human signoff](#human-signoff) below.

> Fresh Skill 2 audit of the **P2** card `SMC_CG_P2_003` on kept log `f6d7df5f…` (run
> `20260805_091748`). This anchor also carries a **separate, already-closed P1 grade**
> (`grades/smc_zeroer_regclk_cg_test_GRADE.md`, `ip: SMC_CLOCK_GATING`, card
> `SMC_CLOCK_GATING_VPLAN_DETAIL.md`) — that file governs the unrelated P1 checkers
> (`CHK-ZREG-GATE-OFF-IDLE`, `CHK-ZREG-ACTIVITY-ENABLE`, `CHK-ZREG-DISABLE-CG`,
> `CHK-ZREG-RESET-OVERRIDE`, P1's own `CHK-NONVAC`) and was **not read as authoritative for
> this round, not overwritten, and not touched**. This report grades only the 4 checkers on
> the P2 card. Card r1 hash `93666c6c…` (recomputed via `manifest.py record-hash`) matches;
> parent plan record r1 hash `49c886a7…` (recomputed) matches the card's
> `derived_from.testcase_record_sha256`; parent `status: approved`, `current: true`. Entry
> PASS: `result.json status: PASS`, cocotb `TESTS=1 PASS=1 FAIL=0 SKIP=0`, zero unexplained
> `ERROR`/`FATAL`/`Traceback`. Force/deposit check: clean.

## Blocker resolution: SF-004

The card carries `blockers: [SF-004]` (Critical, `SF-MISSING`, affecting
`SMC-CG-ZEROER-REGCLK`/`.S1`). Verified in `SMC_CLOCK_GATING_P2_SPEC_REVIEW.md` front matter:
`findings[SF-004].status: answered`, with a substantive `resolution.note` from the same
`approved_by: minshaoho` / `approved_at: 2026-08-05T15:52:00+08:00` stamp as the document's
own top-level `status: approved` — "`register_activity` asserts on any AXI4-Lite access...
while the access is outstanding/active... Pending-access service must complete within the
card's declared bounded wait; max wait is that bound, not a separate SPEC constant."
Cross-checked mechanically: `schema_check.py SMC_CLOCK_GATING_P2_VPLAN_DETAIL.md
--spec-audit SMC_CLOCK_GATING_P2_SPEC_REVIEW.md --plan SMC_CLOCK_GATING_P2_TESTCASE_PLAN.md`
→ `"status": "valid", "problems": []` (no `BLOCKED-BY-FINDING`-class problem raised). The
seq file's own docstring (seq.py:14-18) cites the same resolved reading and implements it
directly: `register_activity` is driven by *any* AXI4-Lite access to the Zeroer register
block (not a specific-register subset), and completion is checked against the card's own
declared bound (`P2_SERVICE_BOUND_SMC=128`), not an invented separate SPEC constant. SF-004
is therefore genuinely resolved for this card's purposes, and the card is unblocked.

**Documentation-hygiene observation, not a finding against this testcase or its evidence:**
`SMC_CLOCK_GATING_P2_SPEC_REVIEW.md`'s own rendered "Questions awaiting your answer:" section
(near end of file) still lists **every** finding — including SF-002, SF-003, SF-004, SF-006,
all of which the front matter marks `status: answered` — as `STATUS: open`. This looks like a
stale/un-refreshed render left over from before the owner's answers were recorded into front
matter, not a live discrepancy in the finding's actual resolution: the front matter (`status:
answered` + `resolution` block, schema-checked and mechanically valid) is the normative
record per `dv-quality/v1`, and `schema_check.py`'s own blocked-by-finding cross-check against
this exact file independently confirms no open blocker remains. This is a Skill 1 artifact
render-consistency issue belonging to whoever next revises `SMC_CLOCK_GATING_P2_SPEC_REVIEW.md`
(analogous to `render_lint.py`'s YAML-vs-body agreement check, which does not currently cover
the `spec-audit` artifact kind) — it does not change this testcase's grade and is called out
here only so it is not silently missed.

## All checkers

| Checker | Grade | Proof class | Covers | Findings |
|---|---|---|---|---|
| CHK-ZEROER-REGCLK-UNGATE | ✅ PROVEN | LIVE | SMC-CG-ZEROER-REGCLK.S1 | — |
| CHK-ZEROER-REGCLK-ACCESS-COMPLETE | ✅ PROVEN | LIVE | SMC-CG-ZEROER-REGCLK.S1 | — |
| CHK-NONVAC | ✅ PROVEN | INTEGRITY | — | — |
| CHK-TIMEOUT-PATHS | ✅ PROVEN | INTEGRITY | — | — |

### Layer 1 structural rule set

| Rule | Result |
|---|---|
| F1 fabricated verdict / backdoor write | ✅ clean — all P2 stimulus is frontdoor AXI4-Lite CSR read/write via `SmcCsrSeq.csr_read`/`csr_write` and generated `smc_addr_map`/`smc_cg_obs_utils` symbols; `tb_zeroer_bus_active`/`tb_zeroer_gated_reg_clk` are passive observation taps; no `force`/`deposit`/`uvm_hdl_*` anywhere in `smc_zeroer_regclk_cg_test_seq.py` / `smc_zeroer_regclk_cg_test.py` |
| F2 can't-fail checker | ✅ clean — every P2 checker has a reachable `AssertionError` fail path: `_p2_timed_access` raises on ungate/resume timeout before any token is emitted; `assert meas["delta"] <= P2_UNGATE_BOUND_SMC` / `assert rb == val` gate each of the 3 cells before `CHK-ZEROER-REGCLK-UNGATE`/`CHK-ZEROER-REGCLK-ACCESS-COMPLETE` are emitted — the emitted token's `match=1`/`resume_delta=…` values are therefore guaranteed-true report-outs, not unchecked claims |
| E1 skip-to-pass | ✅ clean — `assert hasattr(dut, port)` on all required TB ports (body() top); no HDL-path skip-to-pass |
| E2 empty phase | ✅ clean — P2-S1..S3 each program, observe, and assert with real state transitions (gate-to-idle settle, 3-cell access sweep, timeout-bound reporting) |
| S1 silent fail | ✅ clean — every mismatch/timeout raises `AssertionError` with diagnostic state (`f"{label}: ..."` messages embed the offending value); no `log.info`/`warning`-only handling |
| O1 checker disabled | ✅ clean |
| Phase-S obligations — L1 | ✅ clean — X/Z guarded via `cg.sample_bit` and explicit `gval.is_resolvable is False` raises in both `_measure_access_window`/`_p2_timed_access`; edge-driven sampling throughout (`RisingEdge(dut.clk_smc_i)` + `ReadOnly()`, `Timer(1, unit="ps")` used only as a same-edge-alignment bridge, never the checked quantity); addresses sourced from generated `smc_addr_map`/`smc_cg_obs_utils` symbols, never hand literals; regression enrolled (`hw/sys/smc/dv/testlists/clock.toml`) |
| Phase-S obligations — L2 (needs the card) | ✅ clean — SF-004 blocker resolved (see above); proof fence, static sensitivity, no merged evidence between `CHK-ZEROER-REGCLK-UNGATE`/`CHK-ZEROER-REGCLK-ACCESS-COMPLETE`/`CHK-NONVAC`/`CHK-TIMEOUT-PATHS` all clean; `CHK-NO-TAUTOLOGY` guardrail honored (expected values are the TB's own written constants `0xA5A5_0001..0004`, never copied from the DUT's own read-back path) |

## Evidence appendix

<details>
<summary>Kept log + build identity + entry-gate recomputation</summary>

- Log: `hw/sys/smc/dv/build/runs/20260805_091748__verilator__smc_zeroer_regclk_cg_test/smc_zeroer_regclk_cg_test/logs/smc_zeroer_regclk_cg_test.log`
  sha256 `f6d7df5fd00b9f40a4e5cc728f7ed4afbb2a364d6b4718c25ea58513c539d111` (verified via
  `manifest.py hash-file`)
- `result.json`: `status: PASS`, `return_code: 0`, seed 1, target `default`, simulator
  `verilator` `5.050 2026-07-01`, `target_build.fingerprint: 2c815fa08277`,
  `build_cache.rebuild: false`, positive-evidence parser (`results_xml` + `log_summary`, both
  PASS)
- Card `SMC_CG_P2_003` r1 `93666c6c76e78b0f181dba725025d1652ff5407526e20c4421403218b24e290e`
  — recomputed via `manifest.py record-hash SMC_CLOCK_GATING_P2_VPLAN_DETAIL.md --id
  SMC_CG_P2_003 --array cards` → `match: true`
- Parent plan record `SMC_CG_P2_003` r1 `49c886a759cc50a15a1dfbc1bc3e0e51ad3cfa62eb333bbc7b397b689df7f484`
  — recomputed via `manifest.py record-hash SMC_CLOCK_GATING_P2_TESTCASE_PLAN.md --id
  SMC_CG_P2_003 --array testcases` → `match: true`; matches card's
  `derived_from.testcase_record_sha256` verbatim; `plan_revision: 1` / `testcase_revision: 1`
  both match; parent `status: approved`, `current: true` → no `ENTRY-STALE` /
  `ENTRY-PARENT-UNAPPROVED`
- Blocked-by-finding gate: `schema_check.py SMC_CLOCK_GATING_P2_VPLAN_DETAIL.md --spec-audit
  SMC_CLOCK_GATING_P2_SPEC_REVIEW.md --plan SMC_CLOCK_GATING_P2_TESTCASE_PLAN.md` →
  `{"status": "valid", "problems": []}`
- Canonical testcase name `smc_zeroer_regclk_cg_test` consistent across card `anchor`, plan
  `anchor`, `testlists/clock.toml` `name`/`module`, `tests/smc_zeroer_regclk_cg_test.py` class
  name, and the cocotb log's `running smc_zeroer_regclk_cg_test.smc_zeroer_regclk_cg_test`
  line → no `ENTRY-IDENTITY-MISMATCH`
- Cocotb summary L543: `TESTS=1 PASS=1 FAIL=0 SKIP=0`; final assertion gate in
  `smc_zeroer_regclk_cg_test.py:32-44` checks all nine required `CHK-*` tokens (5 P1 + 4 P2,
  `CHK-NONVAC-P2` used as the P2 dict key to avoid clobbering the P1 `CHK-NONVAC` entry) landed
  in `seq.chk_seen`; zero unexplained `ERROR`/`FATAL`/`Traceback` (only benign
  cocotb/cocotbext-axi `DeprecationWarning`s)
- Enrolled: `hw/sys/smc/dv/testlists/clock.toml` → `smc_zeroer_regclk_cg_test`
- Force/deposit audit: no `force`/`deposit`/`uvm_hdl_*` in `smc_zeroer_regclk_cg_test_seq.py`
  or `smc_zeroer_regclk_cg_test.py`
- Address map: seq imports `CLOCK_GATE_CONTROL`/`ZEROER_CG_EN`/`CG_HYST_SHIFT`/`CG_HYST_MASK`/
  `ZEROER_CTRL_DEST_ADDR` from `seq_lib/smc_addr_map.py` (generated header re-export); all P2
  register accesses (`P2_ZREG_IMM_WR/RB`, `P2_ZREG_LONG_WR/RB`, `P2_ZREG_B2B_A_WR`,
  `P2_ZREG_B2B_B_WR`, `P2_ZREG_B2B_RB`) go through `SmcCsrSeq.csr_read`/`csr_write` against
  `ZEROER_CTRL_DEST_ADDR`

</details>

<details>
<summary>Token / step cites (kept log `f6d7df5f…`)</summary>

| Checker | Log line | What the log shows | Impl |
|---|---|---|---|
| (setup) | 450 (STEP P2-S1) | SETUP: hold register interface idle until reg_clk gates | seq.py:191-209 |
| (fence) | 473 | `FENCE REG_CLK-GATED-BASELINE @ 6768ns` | seq.py:209 |
| (setup) | 474 (STEP P2-S2) | ACTION/RESPONSE/EFFECT for S1: sweep pending access across 3 gate-boundary timings | seq.py:211-215 |
| (fence) | 524 | `FENCE ACCESS-SWEEP(3-cells) @ 7686ns` | seq.py:299 |
| CHK-ZEROER-REGCLK-UNGATE | 525 | `immediately-after(resume_delta=1) long-after(resume_delta=1) back-to-back(resume_delta_a=1,resume_delta_b=1) ungate_bound_smc_cycles=32` — all 3 required cells, each `resume_delta <= 32` (asserted before emission) | seq.py:225,252,279,287,301-311 |
| CHK-ZEROER-REGCLK-ACCESS-COMPLETE | 526 | `immediately-after(written=0xa5a50001,readback=0xa5a50001,match=1) long-after(written=0xa5a50002,readback=0xa5a50002,match=1) back-to-back(written_a=0xa5a50003,written_b=0xa5a50004,readback=0xa5a50004,match=1) service_latency_bound_smc_cycles=128` — every `match=1` follows a prior `assert rb == val` (seq.py:229,256,291) | seq.py:229,256,291,312-341 |
| (setup) | 527 (STEP P2-S3) | TIMEOUT: bounded wait, fail-on-expiry, last-state diagnostic | seq.py:343-348 |
| CHK-TIMEOUT-PATHS | 528 | `ungate_bound_smc_cycles=32 service_bound_smc_cycles=128 long_idle_cycles=40 expired=0 last_reg_clk_enable=0 last_bus_active=0` | seq.py:349-360 |
| CHK-NONVAC (P2) | 529 | `SETUP < REG_CLK-GATED-BASELINE < ACCESS-SWEEP(3-cells) < PASS` | seq.py:362-369 |
| (fence) | 530 | `FENCE PASS @ 7686ns` | seq.py:370 |

**Token-hygiene observation (not a finding):** `CHK-NONVAC:` is emitted twice in this kept log
— once by the unrelated, already-closed P1 flow at line 447 (`idle-gate-off-observed < … <
PASS`) and once by this P2 card's own checker at line 529 (`SETUP < REG_CLK-GATED-BASELINE <
… < PASS`). Fully independent content, line numbers, and fence-term lists — not a
`[MERGED-EVIDENCE]` violation, but the test file correctly disambiguates by using a separate
dict key (`CHK-NONVAC-P2`) for the required-token gate, and a reader running a naive
`grep 'CHK-NONVAC:'` must likewise disambiguate by content/line number, not by name alone.

</details>

<details>
<summary>Layer 1 / Layer 2 notes</summary>

- Ordered fence (ns) for the P2 flow: SETUP(6294) < REG_CLK-GATED-BASELINE(6768) <
  ACCESS-SWEEP(3-cells)(7686) < PASS(7686); `assert p2_terms == expected_p2_pre_pass`
  (seq.py:362-364) gates the P2 `CHK-NONVAC` token before it is trusted.
- `CHK-ZEROER-REGCLK-UNGATE` / `CHK-ZEROER-REGCLK-ACCESS-COMPLETE` proof fence: SETUP
  (`wait_gated_off` to a genuinely gated reg_clk baseline, confirmed by
  `count_enabled_at_smc_rise(...) == 0`) → ACTION (`_p2_timed_access` drives one CSR write per
  cell while a concurrent monitor coroutine samples `tb_zeroer_bus_active`/
  `tb_zeroer_gated_reg_clk` every `clk_smc_i` rise) → RESPONSE/EFFECT (resume delta =
  `resume_at - active_at`, glitch-tracked) → static compare `delta <= P2_UNGATE_BOUND_SMC=32`
  and `rb == val` (the value the TB itself wrote — `0xA5A5_0001..0004` — never copied from the
  DUT's own read-back path, satisfying `CHK-NO-TAUTOLOGY`/`[INDEPENDENT-EXPECTED-MODEL]`). All
  3 required cells (`access-immediately-after-reg_clk-gates`, `access-long-after-reg_clk-gates`,
  `back-to-back-accesses-across-gate-boundary`) are hit, each with its own independent
  assertion instance in the source (seq.py:225-229, 252-256, 279-291) — genuinely 3 separate
  proof events, not one assertion re-labeled 3 times.
- `CHK-TIMEOUT-PATHS`: the actual enforcement lives in `_p2_timed_access`
  (seq.py:180-184, raises `AssertionError` with `active_at`/`resume_at` last-state on timeout)
  and in `wait_gated_off`'s own `timeout_smc` bound; the emitted token (seq.py:349-360) reports
  the declared bounds (`P2_UNGATE_BOUND_SMC=32`, `P2_SERVICE_BOUND_SMC=128`,
  `P2_LONG_IDLE_CYCLES=40`) and the live last-observed state at the point of emission
  (`expired=0` because the run reached this line without raising).
- `CHK-NONVAC`: `proves: []` / `covers: []`, ordering/structural (`INTEGRITY`) claim verified
  directly against the fence-order assert (seq.py:363-364).
- No merged-evidence collision among the 4 P2 checkers: each emits its own token from its own
  step; `CHK-NONVAC`/`CHK-TIMEOUT-PATHS` carry `proves: []` (ordering/structural only).
- No blind `Timer`-only wait stands in for a measured event: every sample is `RisingEdge`-driven
  per `clk_smc_i`; the only bare `Timer(1, unit="ps")` calls in `_measure_access_window`/
  `_p2_timed_access` are same-timestep-alignment bridges after `ReadOnly()`, never the checked
  quantity itself.
- X-awareness: `cg.sample_bit` and the explicit `gval.is_resolvable is False` check both raise
  `AssertionError` on an unresolvable (X/Z) value before any compare uses it.
- Regression enrollment confirmed in `hw/sys/smc/dv/testlists/clock.toml`.
- P1/P2 additivity: the P1 flow's 5 evidence tokens (lines 331-447, unchanged content and step
  structure from the closed P1 grade's own kept-log excerpt, only shifted in wall-clock
  timestamp/line-number by this new run) confirm the P2 extension did not alter the P1 proof
  path (out of scope for this report; the P1 grade file was not read as authoritative for this
  P2 round and was not touched).

</details>

## Accepted waivers

| Finding | Rule | Where | Why | Approved by |
|---|---|---|---|---|
| — | — | — | none — 0 findings this round; no prior `smc_zeroer_regclk_cg_test_P2_GRADE.md` exists to carry forward from | — |

## Human signoff

- **who:** minshaoho
- **when:** 2026-08-05T17:21:00+08:00
- **decision:** Done — evidence accepted by owner signoff. 4/4 PROVEN, recommendation
  `EVIDENCE-CLOSED-AWAITING-SIGNOFF`. `SF-004` blocker independently confirmed resolved via
  front matter + mechanical `schema_check.py --spec-audit` gate. This P2 grade is independent
  of, and does not alter, the separately-closed P1 grade for the same anchor.
- **note:** Per user instruction, signoff recorded automatically since all four checkers
  graded PROVEN with zero open findings.
