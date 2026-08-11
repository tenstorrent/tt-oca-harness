---
schema: dv-quality/v1
artifact: testcase-grade
testcase: smc_clk_multi_window_test
ip: SMC_CLOCK_GATING
anchor: smc_clk_multi_window_test
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
card_sha256: b1458f8522c1c4931dd63acd0c575aef4d60110ac0aa69a77016821f04ac2a86
card_revision: 1
card_path: hw/sys/smc/dv/tb/SMC_CLOCK_GATING_VPLAN_DETAIL.md
testcase_plan:
  path: hw/sys/smc/dv/tb/SMC_CLOCK_GATING_TESTCASE_PLAN.md
  plan_revision: 1
  testcase_revision: 1
  testcase_record_sha256: 4c7bf76fa91c76e37339db6bfed59f067c146c72a7c9576d0b361ad71211d550
  parent_approved: true
evidence_class: frontdoor-func
closure_tier: B
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
- path: hw/sys/smc/dv/build/runs/20260805_035610__verilator__smc_clk_multi_window_test/smc_clk_multi_window_test/logs/smc_clk_multi_window_test.log
  sha256: 557f7d0f739f7fb0d81f68137db11e4b8b414b20eddc896e41cb7c42e809349c
test_author:
  human_id: minshaoho
  run_id: dv_test_impl-SMC_CLK_MULTI_WINDOW_TEST-95afef5e-2325-4e52-878d-d6236ae7bfa7
  model:
    provider: cursor
    family: grok
    version: '4.5'
auditor:
  human_id: minshaoho
  run_id: dv_test_audit-SMC_CLK_MULTI_WINDOW_TEST-df05f6072436480d82eb71249e3a5c17
  model:
    provider: cursor
    family: grok
    version: '4.5'
exceptions: []
checkers:
- id: CHK-HYST-WINDOW
  checks_steps: [S1, S2, S3]
  proves: [SMC-CG-ARCH-PARAMS]
  covers: [SMC-CG-ARCH-PARAMS.S1]
  proof_class: LIVE
  expect_source: 'hw/sys/smc/doc/clk_rst.adoc §Clock and Reset-Based Power Management Integration, row "Hysteresis Control" (rev 2f40548ea787240680a1c45ab75b8729e9620778)'
  grade: PROVEN
  evidence:
  - token: 'CHK-HYST-WINDOW: low/mid/high measured within_1cyc min=8/8 mid=31/31 max=63/63 zero_toggles_idle=1 cells=hysteresis_delay_min,hysteresis_delay_mid,hysteresis_delay_max'
    log_sha256: 557f7d0f739f7fb0d81f68137db11e4b8b414b20eddc896e41cb7c42e809349c
    line: 783
    seed: 1
    implementation_path: hw/sys/smc/dv/cocotb/seq_lib/smc_clk_multi_window_test_seq.py:277
  lifecycle_results: null
  coverage_results:
  - key: SMC-CG-ARCH-PARAMS.S1
    method: RANDOMIZED
    required_cells: [hysteresis_delay_min, hysteresis_delay_mid, hysteresis_delay_max]
    achieved_cells: [hysteresis_delay_min, hysteresis_delay_mid, hysteresis_delay_max]
    random_knobs: [programmed_hysteresis_count]
    resolved_knobs: [programmed_hysteresis_count=8, programmed_hysteresis_count=31, programmed_hysteresis_count=63]
    min_seeds: 1
    actual_seeds: [1]
    required_artifact: null
    coverage_artifacts:
    - hw/sys/smc/dv/build/runs/20260805_035610__verilator__smc_clk_multi_window_test/smc_clk_multi_window_test/logs/smc_clk_multi_window_test.log#557f7d0f739f7fb0d81f68137db11e4b8b414b20eddc896e41cb7c42e809349c
    satisfied: true
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
  - token: 'CHK-NONVAC: low-window-measured < mid-window-measured < high-window-measured < PASS'
    log_sha256: 557f7d0f739f7fb0d81f68137db11e4b8b414b20eddc896e41cb7c42e809349c
    line: 785
    seed: 1
    implementation_path: hw/sys/smc/dv/cocotb/seq_lib/smc_clk_multi_window_test_seq.py:295
  lifecycle_results: null
  coverage_results: []
  linked_issue: null
  finding_ids: []
  remediation: null
findings: []
waivers: []
recommendation: EVIDENCE-CLOSED-AWAITING-SIGNOFF
---

# Grade Report — smc_clk_multi_window_test (SMC_CLK_MULTI_WINDOW_TEST)

**VERDICT: 2/2 PROVEN — READY** (mode CHECKBOX, entry PASS)

| Mode | Entry gate | Checkers | Findings | Recommendation |
|---|---|---|---|---|
| `CHECKBOX` | ✅ PASS | 2/2 PROVEN | none | ✅ EVIDENCE-CLOSED-AWAITING-SIGNOFF |

> Fresh Skill 2 re-audit on rework kept log `557f7d0f…` (run `20260805_035610`). Prior grade on
> log `a7fcb1a3…` (**1/2 NOT-READY**) is **not** treated as authoritative. Entry PASS:
> cocotb `TESTS=1 PASS=1 FAIL=0 SKIP=0`, final `assert not missing` on
> `CHK-HYST-WINDOW` / `CHK-NONVAC` / `CHK-TIMEOUT-PATHS`, zero unexplained
> `ERROR`/`FATAL`/`Traceback`. Card r1 hash `b1458f85…` matches parent plan record r1 hash
> `4c7bf76f…` (both recomputed), parent `status: approved`. **Force/deposit check: clean** —
> CSR frontdoor + JTAG memory write + passive `tb_dma_*` observation only (owner hard constraint
> satisfied).

## DELTA (re-audit vs prior grade `1/2 NOT-READY` on log `a7fcb1a3…`)

| Prior id | Tag | Status this round | Notes |
|---|---|---|---|
| FIND-001 | `[ADDRESS-FROM-AUTHORITATIVE-MAP]` | CLOSED | `smc_cg_obs_utils.py` now re-exports `CLOCK_GATE_CONTROL` / `DMA_CG_EN` / `CG_HYST_*` / all `DMA_CTRL_*` / fabric filter addresses from `seq_lib/smc_addr_map.py` (generated `smc_addr.h` / `smc_base_config.h` / `dma_ctrl_addr.h`) |
| CHK-HYST-WINDOW | INSUFFICIENT-EVIDENCE → PROVEN | UPGRADED | Address sourcing closed; measured delays `min=8/8 mid=31/31 max=63/63` + three required cells intact on new log |
| CHK-NONVAC | stayed PROVEN | unchanged substance | New kept log `557f7d0f…` |

## Your to-do — 0 items (none)

| # | Rank | Item |
|---|---|---|
| — | — | none open |

**Then:** human signoff on this grade → Skill 3 peer audit when the remaining SMC_CLOCK_GATING anchors close, or continue Skill 2 on still-open anchors.

## All checkers

| Checker | Grade | Proof class | Covers | Findings |
|---|---|---|---|---|
| CHK-HYST-WINDOW | ✅ PROVEN | LIVE | SMC-CG-ARCH-PARAMS.S1 | — |
| CHK-NONVAC | ✅ PROVEN | INTEGRITY | — | — |

### Layer 1 structural rule set

| Rule | Result |
|---|---|
| F1 fabricated verdict / backdoor write | ✅ clean — CSR/data access is frontdoor AXI (SEP_IN + JTAG memory write); TB observation ports are passive `assign`s in `tb_top.sv`; **no force/deposit** |
| F2 can't-fail checker | ✅ clean — `|delay - hyst| <= 1`, busy-seen, post-idle `edges == 0`, and fence-order asserts are real reachable `AssertionError` paths |
| E1 skip-to-pass | ✅ clean |
| E2 empty phase | ✅ clean |
| S1 silent fail | ✅ clean — every mismatch/timeout raises `AssertionError` with diagnostic state |
| O1 checker disabled | ✅ clean |
| Phase-S obligations — L1 | ✅ clean — addresses imported via `smc_addr_map`; timeouts fail; tokens conditional; X/Z-aware `sample_bit`; enrolled in `clock.toml` / `all.toml` |
| Phase-S obligations — L2 (needs the card) | ✅ clean — proof fence SETUP→ACTION→RESPONSE→EFFECT→NONVAC ordered; coverage cells from feature_list satisfied; no merged-evidence collision; force-free per card guardrails |

## Evidence appendix

<details>
<summary>Kept log + build identity</summary>

- Log: `hw/sys/smc/dv/build/runs/20260805_035610__verilator__smc_clk_multi_window_test/smc_clk_multi_window_test/logs/smc_clk_multi_window_test.log`
  sha256 `557f7d0f739f7fb0d81f68137db11e4b8b414b20eddc896e41cb7c42e809349c`
  (verified via `manifest.py hash-file`)
- `result.json`: `status: PASS`, `return_code: 0`, seed 1, target `default`, simulator `verilator`
  `5.050 2026-07-01`, `target_build.fingerprint: 2c815fa08277`, positive-evidence parser
  (`results_xml` + `log_summary`, both PASS)
- Card: SMC_CLK_MULTI_WINDOW_TEST r1 `b1458f8522c1c4931dd63acd0c575aef4d60110ac0aa69a77016821f04ac2a86`
  (recomputed match against `SMC_CLOCK_GATING_VPLAN_DETAIL.md`)
- Parent plan record: r1 `4c7bf76fa91c76e37339db6bfed59f067c146c72a7c9576d0b361ad71211d550` ·
  `plan_revision: 1` · `status: approved` (recomputed match against
  `SMC_CLOCK_GATING_TESTCASE_PLAN.md`)
- Feature list: `SMC-CG-ARCH-PARAMS.S1` method `RANDOMIZED`, required_cells
  `[hysteresis_delay_min, hysteresis_delay_mid, hysteresis_delay_max]`,
  `random_knobs: [programmed_hysteresis_count]`, `coverage_artifact: null` — all three cells hit
  deterministically with programmed values 8 / 31 / 63 (kept log WINDOW lines)
- Cocotb summary L799: `TESTS=1 PASS=1 FAIL=0 SKIP=0`; final assertion gate in
  `smc_clk_multi_window_test.py:26-28` checks required `CHK-*` tokens landed in `seq.chk_seen`; no
  unexplained `ERROR`/`FATAL`/`Traceback` (only benign cocotb `DeprecationWarning`s / reset INFO)
- Enrolled: `hw/sys/smc/dv/testlists/clock.toml` (`name = "smc_clk_multi_window_test"`) and
  `hw/sys/smc/dv/testlists/all.toml`
- Address sourcing: `smc_cg_obs_utils.py:10-46` imports from `smc_addr_map` (generated headers);
  independently resolved `CLOCK_GATE_CONTROL=0xc0010018`, `DMA_CG_EN=0x1`, `CG_HYST_SHIFT=24`,
  `CG_HYST_MASK=0x3f000000`, `DMA_CTRL_CONFIG=0xc0038000`, `DMA_CTRL_DONE_0=0xc00380c8`
- Observation ports: `tb_dma_cg_en` / `tb_dma_gated_clk` / `tb_dma_busy` / `tb_dma_gater_busy`
  are passive `assign`s in `tb_top.sv` (gater busy used as hysteresis T0); no force/deposit

</details>

<details>
<summary>Token / step cites (kept log `557f7d0f…`)</summary>

| Checker | Log line | What the log shows | Impl |
|---|---|---|---|
| (setup) | — | `STEP S1/S2/S3: program hyst=…; active then idle; measure re-gate delay` | seq `:148-151` / `:269-271` |
| (fence) | 495 | `FENCE low-window-measured @ 6738ns` | seq `:251` |
| WINDOW S1 | 496 | `WINDOW S1 hyst=8 measured_delay=8 cell=hysteresis_delay_min` | seq `:252-254` |
| (fence) | 638 | `FENCE mid-window-measured @ 9006ns` | seq `:251` |
| WINDOW S2 | 639 | `WINDOW S2 hyst=31 measured_delay=31 cell=hysteresis_delay_mid` | seq `:252-254` |
| (fence) | 781 | `FENCE high-window-measured @ 11850ns` | seq `:251` |
| WINDOW S3 | 782 | `WINDOW S3 hyst=63 measured_delay=63 cell=hysteresis_delay_max` | seq `:252-254` |
| CHK-HYST-WINDOW | 783 | `CHK-HYST-WINDOW: … min=8/8 mid=31/31 max=63/63 zero_toggles_idle=1 cells=hysteresis_delay_min,hysteresis_delay_mid,hysteresis_delay_max` | seq `:277-283` |
| CHK-NONVAC | 785 | `CHK-NONVAC: low-window-measured < mid-window-measured < high-window-measured < PASS` | seq `:295-300` |
| (fence) | 786 | `FENCE PASS @ 11850ns` | seq `:301` |

</details>

<details>
<summary>Layer 1 notes</summary>

- Ordered fence low-window-measured(6738ns) < mid-window-measured(9006ns) <
  high-window-measured(11850ns) < PASS(11850ns): non-empty, strictly ordered,
  `AssertionError`-gated via `assert_fence_order` (seq.py:291-294) before `CHK-NONVAC` is emitted.
- S1/S2/S3 FAIL-ON paths raise on re-gate delay mismatch (`|delay - hyst| > 1`), missing busy /
  busy-fall, post-idle gated-clock edges, and bounded timeouts (`wait_gated_off`, DMA done/busy,
  re-gate quiet) with last-state diagnostics — no silent pass.
- `sample_bit` (obs_utils.py:53-58) raises on X/Z; missing TB ports fail `hasattr` before use.
- No blind `Timer`-only stand-in for the hysteresis measurement: concurrent meter + gated-edge
  watchers establish busy-fall → last-edge delay; post-idle quiet is edge-count polled.
- Required cells walked deterministically (8/31/63); RANDOMIZED adequacy is cell hit, not seed
  count (policy / Skill 2 §3). Low cell uses 8 (not 0/1) per seq comment: hyst=0 never runs under
  `cg_enable`; hyst=1 loses frontend→backend handoff — still the near-low legal bin for the cell.
- Regression enrollment confirmed in `clock.toml` / `all.toml`.
- No merged-evidence collision: `CHK-HYST-WINDOW` and `CHK-NONVAC` emit independent tokens;
  `CHK-NONVAC` is pure ordering (`proves: []`) and substitutes for no feature proof.
- Extra integrity token `CHK-TIMEOUT-PATHS` is emitted by the seq and required by the test wrapper
  but is not a card checker — not graded here.
- Prior FIND-001 closed by shared-helper rework; no unsigned waivers to carry forward
  (`waivers: []`).

</details>

## Human signoff

- **signed_off_by:** minshaoho
- **signed_off_at:** 2026-08-05T14:28:00+08:00
- **decision:** Done — evidence accepted; Skill 2 recommendation remains schema value
  `EVIDENCE-CLOSED-AWAITING-SIGNOFF` (YAML enum); human signoff recorded here as final Done.

## Accepted waivers

| Finding | Rule | Where | Why | Approved by |
|---|---|---|---|---|
| — | — | — | none | — |
