---
schema: dv-quality/v1
artifact: testcase-grade
testcase: smc_clk_running_test
ip: SMC_CLOCK_GATING
anchor: smc_clk_running_test
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
card_sha256: f62af0cbf3bba2af20a2d632e3c7e626e5896e25a0867957e0d140d99a1cb8fd
card_revision: 1
card_path: hw/sys/smc/dv/tb/SMC_CLOCK_GATING_VPLAN_DETAIL.md
testcase_plan:
  path: hw/sys/smc/dv/tb/SMC_CLOCK_GATING_TESTCASE_PLAN.md
  plan_revision: 1
  testcase_revision: 1
  testcase_record_sha256: c91b2feb06e2c2e916109dce085fddfea9c7b7dbb65d87e33775ac08caba6e32
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
- path: hw/sys/smc/dv/build/runs/20260805_035801__verilator__smc_clk_running_test/smc_clk_running_test/logs/smc_clk_running_test.log
  sha256: 807b1266708bd851f04e28c5cb0a6075dd88f11bb3fc27265225321a45d5f945
test_author:
  human_id: minshaoho
  run_id: dv_test_impl-SMC_CLK_RUNNING_TEST-95afef5e-2325-4e52-878d-d6236ae7bfa7
  model:
    provider: cursor
    family: grok
    version: '4.5'
auditor:
  human_id: minshaoho
  run_id: dv_test_audit-SMC_CLK_RUNNING_TEST-75e9d256c2bd40a8837f1aa4258bb201
  model:
    provider: cursor
    family: grok
    version: '4.5'
exceptions: []
checkers:
- id: CHK-ACTIVE-RUNNING
  checks_steps: [S1, S2]
  proves: [SMC-CG-ARCH-PARAMS]
  covers: [SMC-CG-ARCH-PARAMS.S2]
  proof_class: LIVE
  expect_source: 'hw/sys/smc/doc/clk_rst.adoc §Clock and Reset-Based Power Management Integration, row "Activity Detection" (rev 2f40548ea787240680a1c45ab75b8729e9620778)'
  grade: PROVEN
  evidence:
  - token: 'CHK-ACTIVE-RUNNING: active_module=DMA toggles_every_cycle=1 dma_edges=16 idle_module=Zeroer axi_clk_gated=1 zeroer_edges=0 concurrent_window=16'
    log_sha256: 807b1266708bd851f04e28c5cb0a6075dd88f11bb3fc27265225321a45d5f945
    line: 473
    seed: 1
    implementation_path: hw/sys/smc/dv/cocotb/seq_lib/smc_clk_running_test_seq.py:269
  lifecycle_results: null
  coverage_results:
  - key: SMC-CG-ARCH-PARAMS.S2
    method: DIRECTED
    required_cells: [module_active_clock_running, module_idle_clock_gated]
    achieved_cells: [module_active_clock_running, module_idle_clock_gated]
    random_knobs: []
    resolved_knobs: []
    min_seeds: 1
    actual_seeds: [1]
    required_artifact: null
    coverage_artifacts:
    - hw/sys/smc/dv/build/runs/20260805_035801__verilator__smc_clk_running_test/smc_clk_running_test/logs/smc_clk_running_test.log#807b1266708bd851f04e28c5cb0a6075dd88f11bb3fc27265225321a45d5f945
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
  - token: 'CHK-NONVAC: active-module-observed < idle-module-observed < PASS'
    log_sha256: 807b1266708bd851f04e28c5cb0a6075dd88f11bb3fc27265225321a45d5f945
    line: 474
    seed: 1
    implementation_path: hw/sys/smc/dv/cocotb/seq_lib/smc_clk_running_test_seq.py:281
  lifecycle_results: null
  coverage_results: []
  linked_issue: null
  finding_ids: []
  remediation: null
findings: []
waivers: []
recommendation: EVIDENCE-CLOSED-AWAITING-SIGNOFF
---

# Grade Report — smc_clk_running_test (SMC_CLK_RUNNING_TEST)

**VERDICT: 2/2 PROVEN — READY** (mode CHECKBOX, entry PASS)

| Mode | Entry gate | Checkers | Findings | Recommendation |
|---|---|---|---|---|
| `CHECKBOX` | ✅ PASS | 2/2 PROVEN | none | ✅ EVIDENCE-CLOSED-AWAITING-SIGNOFF |

> Fresh Skill 2 re-audit on rework kept log `807b1266…` (run `20260805_035801`). Prior grade on
> log `cc496fb7…` (**1/2 NOT-READY**) is **not** treated as authoritative. Entry PASS:
> cocotb `TESTS=1 PASS=1 FAIL=0 SKIP=0`, final `assert not missing` on
> `CHK-ACTIVE-RUNNING` / `CHK-NONVAC`, zero unexplained `ERROR`/`FATAL`/`Traceback`. Card r1 hash
> `f62af0cb…` matches parent plan record r1 hash `c91b2feb…` (both recomputed), parent
> `status: approved`. **Force/deposit check: clean** — CSR frontdoor + JTAG memory write +
> passive `tb_dma_*` / `tb_zeroer_*` observation only (owner hard constraint satisfied).

## DELTA (re-audit vs prior grade `1/2 NOT-READY` on log `cc496fb7…`)

| Prior id | Tag | Status this round | Notes |
|---|---|---|---|
| FIND-001 | `[ADDRESS-FROM-AUTHORITATIVE-MAP]` | CLOSED | Seq + `smc_cg_obs_utils` import `CLOCK_GATE_CONTROL` / `DMA_CG_EN` / `ZEROER_CG_EN` / `CG_HYST_*` / fabric + `DMA_CTRL_*` from `smc_addr_map.py` (generated `smc_addr.h` / `smc_base_config.h` / `dma_ctrl_addr.h`) |
| FIND-002 | `[EXACT-EXPECTATION]` | CLOSED | Toggle asserts tightened to `dma_edges == ACTIVE_WINDOW` (and concurrent pair); kept log `dma_edges=16` / `concurrent_window=16` |
| FIND-003 | `[EXACT-EXPECTATION]` | CLOSED | Token prints derived `toggles_every=int(dma_edges2==ACTIVE_WINDOW)` / `axi_gated=int(zaxi_edges==0)` |
| CHK-ACTIVE-RUNNING | INSUFFICIENT-EVIDENCE → PROVEN | UPGRADED | Exact concurrent every-cycle + idle-gated proof on new log |
| CHK-NONVAC | stayed PROVEN | unchanged substance | New kept log `807b1266…` |

## Your to-do — 0 items (none)

| # | Rank | Item |
|---|---|---|
| — | — | none open |

**Then:** human signoff on this grade → Skill 3 peer audit when the remaining SMC_CLOCK_GATING anchors close, or continue Skill 2 on still-open anchors.

## All checkers

| Checker | Grade | Proof class | Covers | Findings |
|---|---|---|---|---|
| CHK-ACTIVE-RUNNING | ✅ PROVEN | LIVE | SMC-CG-ARCH-PARAMS.S2 | — |
| CHK-NONVAC | ✅ PROVEN | INTEGRITY | — | — |

### Layer 1 structural rule set

| Rule | Result |
|---|---|
| F1 fabricated verdict / backdoor write | ✅ clean — CSR/data access is frontdoor AXI (SEP_IN + JTAG memory write); TB observation ports are passive; **no force/deposit** |
| F2 can't-fail checker | ✅ clean — `dma_edges == ACTIVE_WINDOW`, `zaxi_edges == 0`, busy/timeout, and fence-order asserts are real reachable `AssertionError` paths |
| E1 skip-to-pass | ✅ clean |
| E2 empty phase | ✅ clean |
| S1 silent fail | ✅ clean — every mismatch/timeout raises `AssertionError` with diagnostic state |
| O1 checker disabled | ✅ clean |
| Phase-S obligations — L1 | ✅ clean — addresses via `smc_addr_map`; timeouts fail; tokens conditional; X/Z-aware `sample_bit` / enable-count; enrolled in `clock.toml` / `all.toml` |
| Phase-S obligations — L2 (needs the card) | ✅ clean — proof fence SETUP→ACTION→RESPONSE→EFFECT→NONVAC ordered; coverage cells from feature_list satisfied; no merged-evidence collision; force-free per card guardrails |

## Evidence appendix

<details>
<summary>Kept log + build identity</summary>

- Log: `hw/sys/smc/dv/build/runs/20260805_035801__verilator__smc_clk_running_test/smc_clk_running_test/logs/smc_clk_running_test.log`
  sha256 `807b1266708bd851f04e28c5cb0a6075dd88f11bb3fc27265225321a45d5f945`
  (verified via `manifest.py hash-file`; matches invoker hint)
- `result.json`: `status: PASS`, `return_code: 0`, seed 1, target `default`, simulator `verilator`
  `5.050 2026-07-01`, `target_build.fingerprint: 2c815fa08277`, positive-evidence parser
  (`results_xml` + `log_summary`, both PASS)
- Card: SMC_CLK_RUNNING_TEST r1 `f62af0cbf3bba2af20a2d632e3c7e626e5896e25a0867957e0d140d99a1cb8fd`
  (recomputed match against `SMC_CLOCK_GATING_VPLAN_DETAIL.md`)
- Parent plan record: r1 `c91b2feb06e2c2e916109dce085fddfea9c7b7dbb65d87e33775ac08caba6e32` ·
  `plan_revision: 1` · `status: approved` (recomputed match against
  `SMC_CLOCK_GATING_TESTCASE_PLAN.md`)
- Feature list: `SMC-CG-ARCH-PARAMS.S2` method `DIRECTED`, required_cells
  `[module_active_clock_running, module_idle_clock_gated]`, `random_knobs: []`,
  `coverage_artifact: null` — both cells hit in the concurrent S2 window
  (`dma_edges=16`, `zeroer_edges=0`)
- Cocotb summary L488: `TESTS=1 PASS=1 FAIL=0 SKIP=0`; final assertion gate in
  `smc_clk_running_test.py:26-28` checks required `CHK-*` tokens landed in `seq.chk_seen`; no
  unexplained `ERROR`/`FATAL`/`Traceback` (only benign cocotb INFO about pytest / fuse sense)
- Enrolled: `hw/sys/smc/dv/testlists/clock.toml` (`name = "smc_clk_running_test"`) and
  `hw/sys/smc/dv/testlists/all.toml`
- Address sourcing: `smc_clk_running_test_seq.py:28-55` and `smc_cg_obs_utils.py:10-46` import from
  `smc_addr_map`; independently resolved `CLOCK_GATE_CONTROL=0xc0010018`, `DMA_CG_EN=0x1`,
  `ZEROER_CG_EN=0x100`, `CG_HYST_SHIFT=24`, `CG_HYST_MASK=0x3f000000`,
  `DMA_CTRL_NEXT_ID_0=0xc0038048`, `DMA_CTRL_DST_ADDRESS_LO=0xc0038108`
- Observation ports: `tb_dma_cg_en` / `tb_dma_gated_clk` / `tb_dma_busy` /
  `tb_zeroer_cg_en` / `tb_zeroer_gated_axi_clk` / `tb_zeroer_busy` asserted present before use;
  no force/deposit

</details>

<details>
<summary>Token / step cites (kept log `807b1266…`)</summary>

| Checker | Log line | What the log shows | Impl |
|---|---|---|---|
| (setup) | 342 | `STEP S1: enable CG; drive DMA active; observe DMA gated clock running` | seq `:198` |
| (fence) | 470 | `FENCE active-module-observed @ 6720ns` | seq `:239` |
| (setup) | 471 | `STEP S2: keep DMA active; Zeroer idle; observe independent gating concurrently` | seq `:242` |
| (fence) | 472 | `FENCE idle-module-observed @ 6816ns` | seq `:267` |
| CHK-ACTIVE-RUNNING | 473 | `CHK-ACTIVE-RUNNING: active_module=DMA toggles_every_cycle=1 dma_edges=16 idle_module=Zeroer axi_clk_gated=1 zeroer_edges=0 concurrent_window=16` | seq `:269-276` |
| CHK-NONVAC | 474 | `CHK-NONVAC: active-module-observed < idle-module-observed < PASS` | seq `:281-285` |
| (fence) | 475 | `FENCE PASS @ 6816ns` | seq `:286` |

</details>

<details>
<summary>Layer 1 notes</summary>

- Ordered fence active-module-observed(6720ns) < idle-module-observed(6816ns) < PASS(6816ns):
  non-empty, list-ordered, `AssertionError`-gated via `assert_fence_order` (seq.py:278-280)
  before `CHK-NONVAC` is emitted.
- S1/S2 FAIL-ON paths raise on missing active toggles (`== ACTIVE_WINDOW`), idle Zeroer edges
  (`== 0`), unexpected Zeroer busy, DMA accept/busy timeouts, and gated-off timeouts with
  last-state diagnostics — no silent pass.
- `sample_bit` / `count_enabled_*_at_smc_rise` raise on X/Z; missing TB ports fail `hasattr`
  before use.
- Concurrent same-window sample via `count_enabled_pair_at_smc_rise` satisfies the card's
  "observed concurrently" fail_on; exact `== ACTIVE_WINDOW` matches zero-tolerance missing-toggle.
- Tokens emitted only after asserts (`emit_chk` after FAIL-ON paths) — not unconditional.
- Regression enrollment confirmed in `clock.toml` / `all.toml`.
- No merged-evidence collision: `CHK-ACTIVE-RUNNING` and `CHK-NONVAC` emit independent tokens;
  `CHK-NONVAC` is pure ordering (`proves: []`) and substitutes for no feature proof.
- JTAG-AXI `_write_bytes` seeds TB memory-model regions behind the DMA fabric
  (`update_golden = True`) — approved external-master frontdoor, not a DUT backdoor.
- Prior FIND-001/002/003 closed by rework; no unsigned waivers to carry forward
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
