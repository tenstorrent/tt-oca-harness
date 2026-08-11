---
schema: dv-quality/v1
artifact: testcase-grade
testcase: smc_cg_zeroer_activity_bringup_test
ip: SMC_CLOCK_GATING_P0
anchor: smc_cg_zeroer_activity_bringup_test
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
card_sha256: 91aeaf4f6e050ebe2fa76dca6013bcfd5a9acee9661d87794a275ceb61954acd
card_revision: 1
card_path: hw/sys/smc/dv/tb/SMC_CLOCK_GATING_P0_VPLAN_DETAIL.md
testcase_plan:
  path: hw/sys/smc/dv/tb/SMC_CLOCK_GATING_P0_TESTCASE_PLAN.md
  plan_revision: 1
  testcase_revision: 1
  testcase_record_sha256: ad90a6ffe25462797477d28fbc5ef3d6bf3c5ab3b38f384757cd94872e3e23f7
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
- path: hw/sys/smc/dv/build/runs/20260805_081125__verilator__smc_cg_zeroer_activity_bringup_test/smc_cg_zeroer_activity_bringup_test/logs/smc_cg_zeroer_activity_bringup_test.log
  sha256: 083e77ab9a53400b318b58a8649520779f78f9e5bb281d2a9a09a46e4161ff78
test_author:
  human_id: minshaoho
  run_id: dv_test_impl-SMCCGP0_004-20260805T081125+0800
  model:
    provider: unknown
    family: unknown
    version: unknown
auditor:
  human_id: minshaoho
  run_id: dv_test_audit-SMCCGP0_004-fresh-20260805T162700+0800
  model:
    provider: cursor
    family: claude
    version: sonnet-5
exceptions: []
checkers:
- id: CHK-REG-CLK-IDLE-GATED
  checks_steps: [S1]
  proves: [SMC-CG-ZEROER]
  covers: [SMC-CG-ZEROER.S5]
  proof_class: LIVE
  expect_source: 'hw/sys/smc/doc/zeroer.adoc "Clock Gating - Register Clock"'
  grade: PROVEN
  evidence:
  - token: 'CHK-REG-CLK-IDLE-GATED: toggle_count=0 sample_window=16 gate_off_latency=0 zeroer_cg_en=1 zeroer_busy_o=0'
    log_sha256: 083e77ab9a53400b318b58a8649520779f78f9e5bb281d2a9a09a46e4161ff78
    line: 382
    seed: 1
    implementation_path: hw/sys/smc/dv/cocotb/seq_lib/smc_cg_zeroer_activity_bringup_test_seq.py:239
  lifecycle_results: null
  coverage_results:
  - key: SMC-CG-ZEROER.S5
    method: DIRECTED
    required_cells: [reg-clk-idle-gated]
    achieved_cells: [reg-clk-idle-gated]
    random_knobs: []
    resolved_knobs: []
    min_seeds: 1
    actual_seeds: [1]
    required_artifact: null
    coverage_artifacts:
    - hw/sys/smc/dv/build/runs/20260805_081125__verilator__smc_cg_zeroer_activity_bringup_test/smc_cg_zeroer_activity_bringup_test/logs/smc_cg_zeroer_activity_bringup_test.log#083e77ab9a53400b318b58a8649520779f78f9e5bb281d2a9a09a46e4161ff78
    satisfied: true
  linked_issue: null
  finding_ids: []
  remediation: null
- id: CHK-REG-ACCESS-UNGATES-REG-CLK
  checks_steps: [S2]
  proves: [SMC-CG-ZEROER]
  covers: [SMC-CG-ZEROER.S6]
  proof_class: LIVE
  expect_source: 'hw/sys/smc/doc/zeroer.adoc "Clock Gating - Register Clock"'
  grade: PROVEN
  evidence:
  - token: 'CHK-REG-ACCESS-UNGATES-REG-CLK: toggle_count=9 first_toggle_smc=6 toggled_during_write_window=1 toggled_before_first_write=0'
    log_sha256: 083e77ab9a53400b318b58a8649520779f78f9e5bb281d2a9a09a46e4161ff78
    line: 410
    seed: 1
    implementation_path: hw/sys/smc/dv/cocotb/seq_lib/smc_cg_zeroer_activity_bringup_test_seq.py:273
  lifecycle_results: null
  coverage_results:
  - key: SMC-CG-ZEROER.S6
    method: DIRECTED
    required_cells: [register-access-ungates-reg-clk]
    achieved_cells: [register-access-ungates-reg-clk]
    random_knobs: []
    resolved_knobs: []
    min_seeds: 1
    actual_seeds: [1]
    required_artifact: null
    coverage_artifacts:
    - hw/sys/smc/dv/build/runs/20260805_081125__verilator__smc_cg_zeroer_activity_bringup_test/smc_cg_zeroer_activity_bringup_test/logs/smc_cg_zeroer_activity_bringup_test.log#083e77ab9a53400b318b58a8649520779f78f9e5bb281d2a9a09a46e4161ff78
    satisfied: true
  linked_issue: null
  finding_ids: []
  remediation: null
- id: CHK-BUSY-UNGATES-AXI-CLK
  checks_steps: [S3]
  proves: [SMC-CG-ZEROER]
  covers: [SMC-CG-ZEROER.S4]
  proof_class: LIVE
  expect_source: 'hw/sys/smc/doc/zeroer.adoc "Clock Gating - AXI Clock"'
  grade: PROVEN
  evidence:
  - token: 'CHK-BUSY-UNGATES-AXI-CLK: resume_within_1cyc=1 resume_cyc=1 toggles_every_cycle=1 enabled_hits=10 post_resume_cycles=10'
    log_sha256: 083e77ab9a53400b318b58a8649520779f78f9e5bb281d2a9a09a46e4161ff78
    line: 412
    seed: 1
    implementation_path: hw/sys/smc/dv/cocotb/seq_lib/smc_cg_zeroer_activity_bringup_test_seq.py:292
  lifecycle_results: null
  coverage_results:
  - key: SMC-CG-ZEROER.S4
    method: DIRECTED
    required_cells: [busy-ungates-axi-clk]
    achieved_cells: [busy-ungates-axi-clk]
    random_knobs: []
    resolved_knobs: []
    min_seeds: 1
    actual_seeds: [1]
    required_artifact: null
    coverage_artifacts:
    - hw/sys/smc/dv/build/runs/20260805_081125__verilator__smc_cg_zeroer_activity_bringup_test/smc_cg_zeroer_activity_bringup_test/logs/smc_cg_zeroer_activity_bringup_test.log#083e77ab9a53400b318b58a8649520779f78f9e5bb281d2a9a09a46e4161ff78
    satisfied: true
  linked_issue: null
  finding_ids: []
  remediation: null
- id: CHK-TIMEOUT-PATHS
  checks_steps: [S4]
  proves: []
  covers: []
  proof_class: INTEGRITY
  expect_source: approved card timeout contract
  grade: PROVEN
  evidence:
  - token: 'CHK-TIMEOUT-PATHS: bound_smc_cycles=2048 expired=0 zeroer_busy_at_completion=0'
    log_sha256: 083e77ab9a53400b318b58a8649520779f78f9e5bb281d2a9a09a46e4161ff78
    line: 414
    seed: 1
    implementation_path: hw/sys/smc/dv/cocotb/seq_lib/smc_cg_zeroer_activity_bringup_test_seq.py:303
  lifecycle_results: null
  coverage_results: []
  linked_issue: null
  finding_ids: []
  remediation: null
- id: CHK-NONVAC
  checks_steps: [S1, S2, S3]
  proves: []
  covers: []
  proof_class: INTEGRITY
  expect_source: approved card ordering contract
  grade: PROVEN
  evidence:
  - token: 'CHK-NONVAC: reg-clk-idle-gated-observed < reg-access-ungates-reg-clk-observed < busy-ungates-axi-clk-observed < PASS'
    log_sha256: 083e77ab9a53400b318b58a8649520779f78f9e5bb281d2a9a09a46e4161ff78
    line: 415
    seed: 1
    implementation_path: hw/sys/smc/dv/cocotb/seq_lib/smc_cg_zeroer_activity_bringup_test_seq.py:321
  lifecycle_results: null
  coverage_results: []
  linked_issue: null
  finding_ids: []
  remediation: null
findings: []
waivers: []
recommendation: EVIDENCE-CLOSED-AWAITING-SIGNOFF
---

# Grade Report — smc_cg_zeroer_activity_bringup_test (SMC_CLOCK_GATING_P0 / SMCCGP0_004)

**VERDICT: 5/5 PROVEN — READY** (mode CHECKBOX, entry PASS)

| Mode | Entry gate | Checkers | Findings | Recommendation |
|---|---|---|---|---|
| `CHECKBOX` | ✅ PASS | 5/5 PROVEN | none | ✅ EVIDENCE-CLOSED-AWAITING-SIGNOFF |

> First Skill 2 audit of SMCCGP0_004 (fresh context, no prior authoring/audit/discussion of
> this test or IP in this session). Entry PASS: cocotb `TESTS=1 PASS=1 FAIL=0 SKIP=0`
> (`result.json` structured `status: PASS`, positive-evidence parser, `return_code: 0`), the
> testcase's own final assertion gate executed (`smc_cg_zeroer_activity_bringup_test.py:36-37`
> `assert not missing` on all five required `CHK-*` tokens), zero unexplained `ERROR`/`FATAL`/
> `Traceback` in the kept log (only benign cocotb/library `DeprecationWarning`s). Card r1 hash
> `91aeaf4f…` matches the parent plan record r1 hash `ad90a6ff…` (both recomputed via
> `manifest.py record-hash`), parent `status: approved`, `current: true`. **Force/deposit
> check: clean** — CSR frontdoor (`SmcCsrSeq`) + JTAG-AXI memory seed (`update_golden=True`,
> approved external-master frontdoor) + passive `tb_zeroer_*` observation only (owner hard
> constraint satisfied).

## Your to-do — 0 items (none)

| # | Rank | Item |
|---|---|---|
| — | — | none open |

**Then:** human signoff on this grade (stamped below) → Skill 2 audit of SMCCGP0_001
(`smc_clk_running_test`, P0 reallocation) → Skill 2 audit of SMCCGP0_002
(`smc_static_cg_sanity_test`, P0 reallocation) → Skill 3 peer audit once all four P0 cards
close.

## All checkers

| Checker | Grade | Proof class | Covers | Findings |
|---|---|---|---|---|
| CHK-REG-CLK-IDLE-GATED | ✅ PROVEN | LIVE | SMC-CG-ZEROER.S5 | — |
| CHK-REG-ACCESS-UNGATES-REG-CLK | ✅ PROVEN | LIVE | SMC-CG-ZEROER.S6 | — |
| CHK-BUSY-UNGATES-AXI-CLK | ✅ PROVEN | LIVE | SMC-CG-ZEROER.S4 | — |
| CHK-TIMEOUT-PATHS | ✅ PROVEN | INTEGRITY | — | — |
| CHK-NONVAC | ✅ PROVEN | INTEGRITY | — | — |

### Layer 1 structural rule set

| Rule | Result |
|---|---|
| F1 fabricated verdict / backdoor write | ✅ clean — CSR access is frontdoor AXI (`SmcCsrSeq`); the Zeroer trigger is DEST_ADDR/SIZE/CTRL_STATUS frontdoor register writes; JTAG-AXI `_write_bytes` seeds the output fabric memory model behind the approved external-master port (`update_golden=True`); `tb_zeroer_*` observation ports are passive; **no `force`/`deposit`/`uvm_hdl_*` on DUT internals** |
| F2 can't-fail checker | ✅ clean — `edges == 0` (idle), `reg_toggle_count > 0` + `first_reg_toggle_smc >= 0` (register-write ungate), `delta <= 1` + `axi_enabled_hits == post_resume_cycles` (busy ungate), and `assert_fence_order` all raise `AssertionError` on real RTL deviation; positive control present — S1 first asserts the reg_clk tap free-runs under `disable_cg` (`free == 4`) before proving it gates, so the idle-gated claim cannot pass on a stuck-low tap |
| E1 skip-to-pass | ✅ clean — missing TB ports `assert hasattr` fail before use; no HDL-path skip-to-pass |
| E2 empty phase | ✅ clean — S1–S4 each program/drive, observe, and assert |
| S1 silent fail | ✅ clean — every mismatch/timeout raises `AssertionError` with diagnostic state (`_trigger_and_monitor` TIMEOUT branch includes bound/busy_at/axi_resume_at/reg_toggle_count/last busy) |
| O1 checker disabled | ✅ clean |
| Phase-S obligations — L1 | ✅ clean — addresses via `smc_addr_map` (generated header); X/Z-aware sampling throughout (`is_resolvable` checks on reg/axi/busy every monitor tick); bounded `RisingEdge`-polled waits with real `TIMEOUT-MUST-FAIL` (`_wait_zeroer_idle`, `_trigger_and_monitor`); tokens emitted only after their asserts (`emit_chk` post-FAIL-ON); enrolled in `testlists/clock.toml` (`smc_cg_zeroer_activity_bringup_test`, listed in the `clock` regression) |
| Phase-S obligations — L2 (needs the card) | ✅ clean — proof fence SETUP→ACTION→RESPONSE→EFFECT→NONVAC ordered per checker; coverage cells from feature_list satisfied; no merged-evidence collision (each checker emits its own token for a distinct `SMC-CG-ZEROER` scenario); force-free per card guardrails |

## Evidence appendix

<details>
<summary>Kept log + build identity</summary>

- Log: `hw/sys/smc/dv/build/runs/20260805_081125__verilator__smc_cg_zeroer_activity_bringup_test/smc_cg_zeroer_activity_bringup_test/logs/smc_cg_zeroer_activity_bringup_test.log`
  sha256 `083e77ab9a53400b318b58a8649520779f78f9e5bb281d2a9a09a46e4161ff78` (verified via
  `sha256sum`; matches invoker hint)
- `result.json`: `status: PASS`, `return_code: 0`, seed 1, target `default`, simulator
  `verilator` `5.050 2026-07-01`, `target_build.fingerprint: 2c815fa08277`, `rebuild: true`,
  positive-evidence parser (`results_xml` "1 testcase(s) passed" + `log_summary`
  `TESTS=1 PASS=1 FAIL=0 SKIP=0`, both `status: PASS`)
- Card: SMCCGP0_004 r1 `91aeaf4f6e050ebe2fa76dca6013bcfd5a9acee9661d87794a275ceb61954acd`
  (recomputed match via `manifest.py record-hash ... --array cards`, `current: true`,
  `status: approved`)
- Parent plan record: SMCCGP0_004 r1
  `ad90a6ffe25462797477d28fbc5ef3d6bf3c5ab3b38f384757cd94872e3e23f7` · `plan_revision: 1` ·
  `status: approved` · `current: true` (recomputed match via `manifest.py record-hash
  ... --array testcases`)
- Cocotb summary L423/L429: `smc_cg_zeroer_activity_bringup_test.smc_cg_zeroer_activity_bringup_test
  passed`, `TESTS=1 PASS=1 FAIL=0 SKIP=0`; final assertion gate in
  `smc_cg_zeroer_activity_bringup_test.py:36-37` checks all five required `CHK-*` tokens landed
  in `seq.chk_seen`; protocol VIP check `passed=True` (L418-419); AXI monitors report 0 errors
  (L421-422); no unexplained `ERROR`/`FATAL`/`Traceback` (only benign cocotb/library
  `DeprecationWarning`s; the post-`$finish` ROM-load lines at L431-437 are standard elaboration
  boilerplate for the next scheduled run, not part of this test's proof path)
- Enrolled: `hw/sys/smc/dv/testlists/clock.toml` (`name = "smc_cg_zeroer_activity_bringup_test"`,
  line 77-78; listed in the `clock` regression's test array, line 96)
- Force/deposit audit (owner hard constraint): only frontdoor CSR writes
  (`CLOCK_GATE_CONTROL`, `ZEROER_CTRL_DEST_ADDR/SIZE/STATUS` via `SmcCsrSeq`) and JTAG-AXI
  `_write_bytes` (`update_golden=True`, approved external-master seed of the output fabric
  memory model). No `force`/`deposit`/`uvm_hdl_*` on DUT internals in test, seq, `_one_shot.py`,
  `smc_csr_seq_utils.py`, or `smc_cg_obs_utils.py`.
- Address map: `smc_addr_map.py` (generated PeakRDL C headers, per its own module docstring);
  seq imports `_addr.CLOCK_GATE_CONTROL` / `ZEROER_CG_EN` / `CG_HYST_SHIFT` / `CG_HYST_MASK` /
  `ZEROER_CTRL_DEST_ADDR` / `ZEROER_CTRL_SIZE` / `ZEROER_CTRL_STATUS` by symbol, no hand-copied
  literals.
- Observation ports `tb_zeroer_cg_en` / `tb_zeroer_gated_axi_clk` / `tb_zeroer_gated_reg_clk` /
  `tb_zeroer_busy` confirmed present via `assert hasattr(dut, port)` (seq.py:200-206) before use.

</details>

<details>
<summary>Token / step cites (kept log `083e77ab…`)</summary>

| Checker | Log line | What the log shows | Impl |
|---|---|---|---|
| (setup) | 333 | `STEP S1: frontdoor-write CLOCK_GATE_CONTROL ZEROER_CG_EN=1; no register activity, zeroer_busy_o=0; sample zeroer_reg_gated_clk for a fixed window` | seq `:216-219` |
| CHK-REG-CLK-IDLE-GATED | 382 | `toggle_count=0 sample_window=16 gate_off_latency=0 zeroer_cg_en=1 zeroer_busy_o=0` | seq `:239` |
| (fence) | 385 | `FENCE reg-clk-idle-gated-observed @ 5484ns` | seq `:245` |
| (setup) | 386-388 | `STEP S2/S3/S4: trigger one zero operation; observe reg_clk / axi_clk / bounded completion` | seq `:249-264` |
| CHK-REG-ACCESS-UNGATES-REG-CLK | 410 | `toggle_count=9 first_toggle_smc=6 toggled_during_write_window=1 toggled_before_first_write=0` | seq `:273` |
| (fence) | 411 | `FENCE reg-access-ungates-reg-clk-observed @ 5724ns` | seq `:280` |
| CHK-BUSY-UNGATES-AXI-CLK | 412 | `resume_within_1cyc=1 resume_cyc=1 toggles_every_cycle=1 enabled_hits=10 post_resume_cycles=10` | seq `:292` |
| (fence) | 413 | `FENCE busy-ungates-axi-clk-observed @ 5724ns` | seq `:301` |
| CHK-TIMEOUT-PATHS | 414 | `bound_smc_cycles=2048 expired=0 zeroer_busy_at_completion=0` | seq `:303` |
| CHK-NONVAC | 415 | `reg-clk-idle-gated-observed < reg-access-ungates-reg-clk-observed < busy-ungates-axi-clk-observed < PASS` | seq `:321` |
| (fence) | 416 | `FENCE PASS @ 5724ns` | seq `:327` |

</details>

<details>
<summary>Layer 1 / Layer 2 notes</summary>

- Ordered fence (ns): `reg-clk-idle-gated-observed`(5484) < `reg-access-ungates-reg-clk-observed`
  (5724) < `busy-ungates-axi-clk-observed`(5724) < `PASS`(5724); `assert_fence_order`
  (`smc_cg_obs_utils.py:267-269`) gates the `CHK-NONVAC` emit — real, list-ordered, non-empty.
- `CHK-REG-CLK-IDLE-GATED` proof fence: SETUP positive control (`disable_cg`, `free==4`, proves
  the tap itself toggles) → program `ZEROER_CG_EN=1` → ACTION idle window (gate-off-latency
  measured, then `IDLE_OBSERVE=16` sample) → RESPONSE/EFFECT exact `edges==0` on
  `tb_zeroer_gated_reg_clk`, X/Z-checked → NONVAC fence term.
- `CHK-REG-ACCESS-UNGATES-REG-CLK` proof fence: SETUP `state["writing"]=True` before the
  DEST_ADDR/SIZE/CTRL_STATUS writes → ACTION concurrent monitor samples `tb_zeroer_gated_reg_clk`
  every `clk_smc_i` rise → RESPONSE/EFFECT `reg_toggle_count>0` and `first_reg_toggle_smc>=0`
  (toggle observed strictly inside the write window, never before) → NONVAC.
- `CHK-BUSY-UNGATES-AXI-CLK` proof fence: SETUP/ACTION monitor tracks `tb_zeroer_busy` assertion
  and `tb_zeroer_gated_axi_clk` resume concurrently → RESPONSE axi resumes within 1 SMC cycle of
  busy (`delta<=1`) → EFFECT axi toggles every cycle of the busy interval
  (`axi_enabled_hits==post_resume_cycles`, exact, not "at least once") → NONVAC.
- `FAIL-ON` paths present and real: any idle toggle on `tb_zeroer_gated_reg_clk`; no toggle
  during the register-write window; axi resume >1 cycle late; missing axi toggle during any
  busy cycle; X/Z on any of `reg`/`axi`/`busy`; zero-operation-completion TIMEOUT (2048 SMC
  cycles) with last-state diagnostics; fence order mismatch; missing `CHK-*` tokens at the test
  wrapper.
- No merged-evidence collision: `CHK-REG-CLK-IDLE-GATED`, `CHK-REG-ACCESS-UNGATES-REG-CLK`,
  `CHK-BUSY-UNGATES-AXI-CLK`, `CHK-TIMEOUT-PATHS`, and `CHK-NONVAC` each emit an independent
  token proving a distinct `SMC-CG-ZEROER` scenario (S5/S6/S4 respectively); `CHK-NONVAC` and
  `CHK-TIMEOUT-PATHS` are ordering/timeout-only (`proves: []`) and substitute for no feature
  proof.
- Coverage: feature_list `SMC-CG-ZEROER.S4`/`.S5`/`.S6`, all `method: DIRECTED`,
  `coverage_artifact: null`; required cells `busy-ungates-axi-clk` / `reg-clk-idle-gated` /
  `register-access-ungates-reg-clk` all hit in this kept log, matching the plan's allocated
  scenarios for `SMCCGP0_004` exactly.
- No fabricated verdict, no always-pass checker, no skip-to-pass, no empty phase, no silent
  fail, no disabled checker.

</details>

## Accepted waivers

| Finding | Rule | Where | Why | Approved by |
|---|---|---|---|---|
| — | — | — | none | — |

## Human signoff

- **signed_off_by:** minshaoho
- **signed_off_at:** 2026-08-05T16:35:00+08:00
- **decision:** Done — evidence accepted by owner signoff. 5/5 PROVEN, recommendation
  `EVIDENCE-CLOSED-AWAITING-SIGNOFF`.
- **note:** Fresh Skill 2 audit (auditor `cursor/claude/sonnet-5`, `run_id`
  `dv_test_audit-SMCCGP0_004-fresh-20260805T162700+0800`, distinct from the Skill 1.5 authoring
  session). Force/deposit check clean (frontdoor CSR + approved JTAG-AXI external-master seed
  only). No blocking findings.
