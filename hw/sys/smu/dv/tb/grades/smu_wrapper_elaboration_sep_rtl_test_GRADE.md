---
schema: dv-quality/v1
artifact: testcase-grade
testcase: smu_wrapper_elaboration_sep_rtl_test
ip: SMU_ALL
anchor: smu_wrapper_elaboration_sep_rtl_test
mode: CHECKBOX
no_contract_reason: null
entry_status: PASS
repository_revision: e02d5a97ba46d97eb4469041e115efca949f0184
spec:
- path: hw/sys/smu/doc/SMU_SPEC.md
  revision: 88ddf2482d1e542c0801722975e1f4171907b4fcb68cb511574a88ea9efe88c9
- path: hw/sys/smu/doc/port_table.adoc
  revision: 2f40548ea787240680a1c45ab75b8729e9620778
- path: hw/sys/smc/doc/index.adoc
  revision: 1e98bd45a59ae32ca1bb4715a963b721e26aaf3b
- path: hw/sys/smc/doc/overview.adoc
  revision: 2f40548ea787240680a1c45ab75b8729e9620778
- path: hw/sys/smc/doc/fabric.adoc
  revision: ffc8cdcc349e1e01a2b970442a01070b1c62c0d7
- path: hw/sys/smc/doc/port_table.adoc
  revision: 2f40548ea787240680a1c45ab75b8729e9620778
- path: hw/sys/smc/doc/cpu.adoc
  revision: 2f40548ea787240680a1c45ab75b8729e9620778
- path: hw/sys/smc/doc/clk_rst.adoc
  revision: 2f40548ea787240680a1c45ab75b8729e9620778
- path: hw/sys/smc/doc/interrupts.adoc
  revision: 2f40548ea787240680a1c45ab75b8729e9620778
- path: hw/sys/smc/doc/memmap.adoc
  revision: 2f40548ea787240680a1c45ab75b8729e9620778
- path: hw/sys/smc/doc/periphs.adoc
  revision: ffc8cdcc349e1e01a2b970442a01070b1c62c0d7
- path: hw/sys/smc/doc/dma.adoc
  revision: e2aae39953bb8001c7c20e3afd3956e68c22440c
- path: hw/sys/smc/doc/rom.adoc
  revision: df9e3efe4c8a68f95acb339d0aaf9c9f3f90ab4d
- path: hw/sys/sep/doc/index.adoc
  revision: 2f40548ea787240680a1c45ab75b8729e9620778
- path: hw/sys/sep/doc/introduction.adoc
  revision: 2f40548ea787240680a1c45ab75b8729e9620778
- path: hw/sys/sep/doc/overview.adoc
  revision: 2f40548ea787240680a1c45ab75b8729e9620778
- path: hw/sys/sep/doc/fabric.adoc
  revision: 2f40548ea787240680a1c45ab75b8729e9620778
- path: hw/sys/sep/doc/cpu.adoc
  revision: 2f40548ea787240680a1c45ab75b8729e9620778
- path: hw/sys/sep/doc/crypto.adoc
  revision: 2f40548ea787240680a1c45ab75b8729e9620778
- path: hw/sys/sep/doc/periphs.adoc
  revision: 2f40548ea787240680a1c45ab75b8729e9620778
- path: hw/sys/sep/doc/memory_map.adoc
  revision: 2f40548ea787240680a1c45ab75b8729e9620778
- path: hw/sys/sep/doc/port_table.adoc
  revision: 2f40548ea787240680a1c45ab75b8729e9620778
- path: hw/sys/sep/doc/lifecycle_controller.adoc
  revision: 2f40548ea787240680a1c45ab75b8729e9620778
- path: hw/sys/sep/doc/security_disable.adoc
  revision: 2f40548ea787240680a1c45ab75b8729e9620778
- path: hw/sys/sep/doc/test_mode.adoc
  revision: 2f40548ea787240680a1c45ab75b8729e9620778
- path: hw/sys/sep/doc/token_processing.adoc
  revision: 2f40548ea787240680a1c45ab75b8729e9620778
- path: hw/sys/dtp/doc/index.adoc
  revision: ffc8cdcc349e1e01a2b970442a01070b1c62c0d7
- path: hw/sys/dtp/doc/overview.adoc
  revision: 2f40548ea787240680a1c45ab75b8729e9620778
- path: hw/sys/dtp/doc/jtag.adoc
  revision: 2f40548ea787240680a1c45ab75b8729e9620778
- path: hw/sys/dtp/doc/clock_stop.adoc
  revision: 2f40548ea787240680a1c45ab75b8729e9620778
- path: hw/sys/dtp/doc/port_table.adoc
  revision: 2f40548ea787240680a1c45ab75b8729e9620778
card_sha256: 9bc02021c17f5120c9ad40bc86209c9e563513e2204478498efd0b4610addefc
card_revision: 18
card_path: hw/sys/smu/dv/tb/SMU_ALL_VPLAN_DETAIL.md
testcase_plan:
  path: hw/sys/smu/dv/tb/SMU_ALL_TESTCASE_PLAN.md
  plan_revision: 18
  testcase_revision: 2
  testcase_record_sha256: d093a5fa0100b964afe783af8343c735c5c70e0442ea533666db118fe6164d57
  parent_approved: true
evidence_class: frontdoor-func
closure_tier: B
quality_policy:
  path: hw/sys/smu/dv/tb/SMU_ALL_QUALITY_POLICY.md
  revision: 936b77700909a93bb122f9fb124a3ffb6f5dac5f508c623c5950285a5cefb79a
build_config: compile_smu_chiplet_sep_rtl
simulator: verilator
simulator_version: 5.050 2026-07-01 rev v5.050 (mod)
compile_target: compile_smu_chiplet_sep_rtl
model_fingerprint: f31560a93189
compile_inputs_sha256: c7cc376f29001a1573c9f75feec587896c8b6e09d2c1c13c15993111d4cbf048
seeds:
- 1
logs:
- path: hw/sys/smu/dv/build/kept_logs/smu_wrapper_elaboration_sep_rtl_test.seed1.log
  sha256: ce58253444b88a16cc5e5940f1f6afb5bf658749b431f0d220a43231e185a9c2
test_author:
  human_id: minshaoho
  run_id: dv_test_impl-SMU_ALL_001-20260803T074047
  model:
    provider: cursor
    family: grok
    version: '4.5'
auditor:
  human_id: minshaoho
  run_id: dv_test_audit-SMU_ALL_001-r18-77499f4e3b45
  model:
    provider: cursor
    family: grok
    version: '4.5'
exceptions: []
checkers:
- id: CHK-SMU-COMPOSE-BLOCKS-S1
  checks_steps:
  - S2
  proves:
  - SMU-COMPOSE-BLOCKS
  covers:
  - SMU-COMPOSE-BLOCKS.S1
  proof_class: CONNECTIVITY
  expect_source: pinned SPEC citations on SMU-COMPOSE-BLOCKS.S1 in SMU_ALL_SPEC_FEATURE_LIST.md
  grade: PROVEN
  evidence:
  - token: 'CHK-SMU-COMPOSE-BLOCKS-S1: PASS (sep=1 blocks=smc+sep+dtp+xbar hier_clk_identity={''top'': 0, ''smc'': 0, ''sep'': 0, ''dtp'': 0, ''xbar'': 0})'
    log_sha256: ce58253444b88a16cc5e5940f1f6afb5bf658749b431f0d220a43231e185a9c2
    line: 47
    seed: 1
    implementation_path: hw/sys/smu/dv/cocotb_wrapper/seq_lib/smu_wrapper_elaboration_seq.py:214
  lifecycle_results: null
  coverage_results:
  - key: SMU-COMPOSE-BLOCKS.S1
    method: DIRECTED
    required_cells:
    - sep=1
    - blocks=smc+sep+dtp+xbar
    achieved_cells:
    - sep=1
    - blocks=smc+sep+dtp+xbar
    random_knobs: []
    resolved_knobs: []
    min_seeds: 1
    actual_seeds:
    - 1
    required_artifact: null
    coverage_artifacts:
    - hw/sys/smu/dv/build/kept_logs/smu_wrapper_elaboration_sep_rtl_test.seed1.log#ce58253444b88a16cc5e5940f1f6afb5bf658749b431f0d220a43231e185a9c2
    satisfied: true
  linked_issue: null
  finding_ids: []
  remediation: null
- id: CHK-SMU-COMPOSE-BLOCKS-S2
  checks_steps:
  - S3
  proves:
  - SMU-COMPOSE-BLOCKS
  covers:
  - SMU-COMPOSE-BLOCKS.S2
  proof_class: CONNECTIVITY
  expect_source: pinned SPEC citations on SMU-COMPOSE-BLOCKS.S2 in SMU_ALL_SPEC_FEATURE_LIST.md
  grade: PROVEN
  evidence:
  - token: 'CHK-SMU-COMPOSE-BLOCKS-S2: PASS (domain=clk_smu rst=rst_primary_smc_clk_no clk_last={''top'': 1, ''smc'': 1, ''sep'': 1, ''dtp'': 1, ''xbar'': 1} rst=1)'
    log_sha256: ce58253444b88a16cc5e5940f1f6afb5bf658749b431f0d220a43231e185a9c2
    line: 49
    seed: 1
    implementation_path: hw/sys/smu/dv/cocotb_wrapper/seq_lib/smu_wrapper_elaboration_seq.py:262
  lifecycle_results: null
  coverage_results:
  - key: SMU-COMPOSE-BLOCKS.S2
    method: DIRECTED
    required_cells:
    - domain=clk_smu
    - rst=rst_primary_smc_clk_no
    achieved_cells:
    - domain=clk_smu
    - rst=rst_primary_smc_clk_no
    random_knobs: []
    resolved_knobs: []
    min_seeds: 1
    actual_seeds:
    - 1
    required_artifact: null
    coverage_artifacts:
    - hw/sys/smu/dv/build/kept_logs/smu_wrapper_elaboration_sep_rtl_test.seed1.log#ce58253444b88a16cc5e5940f1f6afb5bf658749b431f0d220a43231e185a9c2
    satisfied: true
  linked_issue: null
  finding_ids: []
  remediation: null
- id: CHK-SMU-COMPOSE-BLOCKS-S3
  checks_steps:
  - S4
  proves:
  - SMU-COMPOSE-BLOCKS
  covers:
  - SMU-COMPOSE-BLOCKS.S3
  proof_class: CONNECTIVITY
  expect_source: pinned SPEC citations on SMU-COMPOSE-BLOCKS.S3 in SMU_ALL_SPEC_FEATURE_LIST.md
  grade: PROVEN
  evidence:
  - token: 'CHK-SMU-COMPOSE-BLOCKS-S3: PASS (port_group=jtag,smu_axi,xtrig,lifecycle jtag=0 axi=1 xtrig=0 lc=0xf0)'
    log_sha256: ce58253444b88a16cc5e5940f1f6afb5bf658749b431f0d220a43231e185a9c2
    line: 52
    seed: 1
    implementation_path: hw/sys/smu/dv/cocotb_wrapper/seq_lib/smu_wrapper_elaboration_seq.py:287
  lifecycle_results: null
  coverage_results:
  - key: SMU-COMPOSE-BLOCKS.S3
    method: DIRECTED
    required_cells:
    - port_group=jtag
    - port_group=smu_axi
    - port_group=xtrig
    - port_group=lifecycle
    achieved_cells:
    - port_group=jtag
    - port_group=smu_axi
    - port_group=xtrig
    - port_group=lifecycle
    random_knobs: []
    resolved_knobs: []
    min_seeds: 1
    actual_seeds:
    - 1
    required_artifact: null
    coverage_artifacts:
    - hw/sys/smu/dv/build/kept_logs/smu_wrapper_elaboration_sep_rtl_test.seed1.log#ce58253444b88a16cc5e5940f1f6afb5bf658749b431f0d220a43231e185a9c2
    satisfied: true
  linked_issue: null
  finding_ids: []
  remediation: null
- id: CHK-SMU-PORT-CLK-RST-S1
  checks_steps:
  - S5
  proves:
  - SMU-PORT-CLK-RST
  covers:
  - SMU-PORT-CLK-RST.S1
  proof_class: LIVE
  expect_source: pinned SPEC citations on SMU-PORT-CLK-RST.S1 in SMU_ALL_SPEC_FEATURE_LIST.md
  grade: PROVEN
  evidence:
  - token: 'CHK-SMU-PORT-CLK-RST-S1: PASS (rst=cold_assert,cold_deassert obs=rst_primary_smc assert_prim=0 release_prim=1)'
    log_sha256: ce58253444b88a16cc5e5940f1f6afb5bf658749b431f0d220a43231e185a9c2
    line: 61
    seed: 1
    implementation_path: hw/sys/smu/dv/cocotb_wrapper/seq_lib/smu_wrapper_elaboration_seq.py:342
  lifecycle_results:
    set:
      token: 'LIFECYCLE SMU-PORT-CLK-RST.S1 set: assert rst_cold_ni=0'
      line: 54
    observed:
      token: 'LIFECYCLE SMU-PORT-CLK-RST.S1 observed: rst_cold_n_o=0 rst_primary_smc_clk_n_o=0'
      line: 56
    cleared:
      token: 'LIFECYCLE SMU-PORT-CLK-RST.S1 cleared: release rst_cold_ni=1'
      line: 57
    checked_cleared:
      token: 'LIFECYCLE SMU-PORT-CLK-RST.S1 checked_cleared: rst_cold_n_o=1 rst_primary_smc_clk_n_o=1'
      line: 60
    complete: true
  coverage_results:
  - key: SMU-PORT-CLK-RST.S1
    method: DIRECTED
    required_cells:
    - rst=cold_assert
    - rst=cold_deassert
    - obs=rst_primary_smc
    achieved_cells:
    - rst=cold_assert
    - rst=cold_deassert
    - obs=rst_primary_smc
    random_knobs: []
    resolved_knobs: []
    min_seeds: 1
    actual_seeds:
    - 1
    required_artifact: null
    coverage_artifacts:
    - hw/sys/smu/dv/build/kept_logs/smu_wrapper_elaboration_sep_rtl_test.seed1.log#ce58253444b88a16cc5e5940f1f6afb5bf658749b431f0d220a43231e185a9c2
    satisfied: true
  linked_issue: null
  finding_ids: []
  remediation: null
- id: CHK-SMU-PORT-CLK-RST-S3
  checks_steps:
  - S6
  proves:
  - SMU-PORT-CLK-RST
  covers:
  - SMU-PORT-CLK-RST.S3
  proof_class: CONNECTIVITY
  expect_source: pinned SPEC citations on SMU-PORT-CLK-RST.S3 in SMU_ALL_SPEC_FEATURE_LIST.md
  grade: PROVEN
  evidence:
  - token: 'CHK-SMU-PORT-CLK-RST-S3: PASS (clk=telemetry,sep_wdt separate_from clk_smu_i smu_ns=8 tel_ns=16 wdt_ns=100)'
    log_sha256: ce58253444b88a16cc5e5940f1f6afb5bf658749b431f0d220a43231e185a9c2
    line: 67
    seed: 1
    implementation_path: hw/sys/smu/dv/cocotb_wrapper/seq_lib/smu_wrapper_elaboration_seq.py:408
  lifecycle_results:
    set:
      token: 'LIFECYCLE SMU-PORT-CLK-RST.S3 set: observe domain periods smu=8 ref/tel=16 wdt=100'
      line: 63
    observed:
      token: 'LIFECYCLE SMU-PORT-CLK-RST.S3 observed: tel_hier==clk_ref (1) wdt_hier==clk_sep_wdt (1) smc_clk==clk_smu (1); periods distinct smu/ref/wdt=8/16/100'
      line: 64
    cleared:
      token: 'LIFECYCLE SMU-PORT-CLK-RST.S3 cleared: observation window closed'
      line: 65
    checked_cleared:
      token: 'LIFECYCLE SMU-PORT-CLK-RST.S3 checked_cleared: tel_hier=1 wdt_hier=1 still on distinct domains'
      line: 66
    complete: true
  coverage_results:
  - key: SMU-PORT-CLK-RST.S3
    method: DIRECTED
    required_cells:
    - clk=telemetry
    - clk=sep_wdt
    achieved_cells:
    - clk=telemetry
    - clk=sep_wdt
    random_knobs: []
    resolved_knobs: []
    min_seeds: 1
    actual_seeds:
    - 1
    required_artifact: null
    coverage_artifacts:
    - hw/sys/smu/dv/build/kept_logs/smu_wrapper_elaboration_sep_rtl_test.seed1.log#ce58253444b88a16cc5e5940f1f6afb5bf658749b431f0d220a43231e185a9c2
    satisfied: true
  linked_issue: null
  finding_ids: []
  remediation: null
- id: CHK-SMU-SEP-PARAM-S1
  checks_steps:
  - S7
  proves:
  - SMU-SEP-PARAM
  covers:
  - SMU-SEP-PARAM.S1
  proof_class: CONNECTIVITY
  expect_source: pinned SPEC citations on SMU-SEP-PARAM.S1 in SMU_ALL_SPEC_FEATURE_LIST.md
  grade: PROVEN
  evidence:
  - token: 'CHK-SMU-SEP-PARAM-S1: PASS (sep=1 xbar=present lc_state=from_sep sep_lc=0xf0 lc_state_o=0xf0 match=1 hier_clk={''top'': 0, ''smc'': 0, ''sep'': 0, ''dtp'': 0, ''xbar'': 0})'
    log_sha256: ce58253444b88a16cc5e5940f1f6afb5bf658749b431f0d220a43231e185a9c2
    line: 69
    seed: 1
    implementation_path: hw/sys/smu/dv/cocotb_wrapper/seq_lib/smu_wrapper_elaboration_seq.py:438
  lifecycle_results: null
  coverage_results:
  - key: SMU-SEP-PARAM.S1
    method: DIRECTED
    required_cells:
    - sep=1
    - xbar=present
    - lc_state=from_sep
    achieved_cells:
    - sep=1
    - xbar=present
    - lc_state=from_sep
    random_knobs: []
    resolved_knobs: []
    min_seeds: 1
    actual_seeds:
    - 1
    required_artifact: null
    coverage_artifacts:
    - hw/sys/smu/dv/build/kept_logs/smu_wrapper_elaboration_sep_rtl_test.seed1.log#ce58253444b88a16cc5e5940f1f6afb5bf658749b431f0d220a43231e185a9c2
    satisfied: true
  linked_issue: null
  finding_ids: []
  remediation: null
- id: CHK-NONVAC
  checks_steps:
  - S1
  - S2
  - S3
  - S4
  - S5
  - S6
  - S7
  - S8
  proves: []
  covers: []
  proof_class: INTEGRITY
  expect_source: approved card ordering contract
  grade: PROVEN
  evidence:
  - token: 'CHK-NONVAC: Ordered fence S1<S2<S3<S4<S5<S6<S7<S8<PASS all hold'
    log_sha256: ce58253444b88a16cc5e5940f1f6afb5bf658749b431f0d220a43231e185a9c2
    line: 78
    seed: 1
    implementation_path: hw/sys/smu/dv/cocotb_wrapper/seq_lib/smu_wrapper_elaboration_seq.py:484
  lifecycle_results: null
  coverage_results: []
  linked_issue: null
  finding_ids: []
  remediation: null
- id: CHK-TIMEOUT-PATHS
  checks_steps:
  - S8
  proves: []
  covers: []
  proof_class: INTEGRITY
  expect_source: approved card timeout contract
  grade: PROVEN
  evidence:
  - token: 'CHK-TIMEOUT-PATHS: Finite bound on S8; expiry fails with last-state diagnostics (paths=5 bound=500)'
    log_sha256: ce58253444b88a16cc5e5940f1f6afb5bf658749b431f0d220a43231e185a9c2
    line: 76
    seed: 1
    implementation_path: hw/sys/smu/dv/cocotb_wrapper/seq_lib/smu_wrapper_elaboration_seq.py:469
  lifecycle_results: null
  coverage_results: []
  linked_issue: null
  finding_ids: []
  remediation: null
findings: []
waivers: []
recommendation: EVIDENCE-CLOSED-AWAITING-SIGNOFF
signed_off_by: minshaoho
signed_off_at: '2026-08-05T18:14:08+08:00'
content_sha256: ce6fa84090103bf23e60ac999e49a0c89275722c6bbcdcbdd67ac432bd9ca34b
---

# Grade Report — smu_wrapper_elaboration_sep_rtl_test (SMU_ALL_001)

**VERDICT: 8/8 PROVEN — READY** (mode CHECKBOX, entry PASS)

| Mode | Entry gate | Checkers | Findings | Recommendation |
|---|---|---|---|---|
| `CHECKBOX` | ✅ PASS | 8/8 PROVEN | none | ✅ EVIDENCE-CLOSED-AWAITING-SIGNOFF |

> Entry PASS on kept log `ce582534…` (run `20260803_083741`). Parent plan r18 hash matches the card. Prior Blocking FIND-001/FIND-002 are closed by hierarchical observe-path remediations; no open findings remain.

## DELTA (re-audit vs prior grade)

| Item | Prior (`dv_test_audit-SMU_ALL_001-47070151-1204-44b7-a697-e85e46194ce1`, card r2) | This audit (`dv_test_audit-SMU_ALL_001-r18-77499f4e3b45`, card r18) |
|---|---|---|
| Verdict | 8/8 PROVEN — READY | 8/8 PROVEN — READY |
| Card hash | `4e5e5594db63d991c8012442ba4bd759549b907e0779d3dd1d9b91b93f61b1cb` (STALE vs plan r18) | `9bc02021c17f5120c9ad40bc86209c9e563513e2204478498efd0b4610addefc` (current) |
| Plan revision | 2 | 18 |
| Checkers / OWNS | unchanged | unchanged — all 8 tokens re-verified on same kept log |
| Kept log | `ce58253444b88a16cc5e5940f1f6afb5bf658749b431f0d220a43231e185a9c2` | `ce58253444b88a16cc5e5940f1f6afb5bf658749b431f0d220a43231e185a9c2` (unchanged) |
| Findings | none open | none open |
| Waivers carried | none signed | none |
| Signoff | prior `2026-08-05T17:16:48+08:00` | renewed `2026-08-05T18:14:08+08:00` (standing order) |


## Your to-do — none

**SIGNOFF RECORDED** — see ## Human signoff below.

**Then:** `/dv_peer_audit` on SMU_ALL when all seven r18 grades are filed.

## All checkers

| Checker | Grade | Proof class | Covers |
|---|---|---|---|
| CHK-SMU-COMPOSE-BLOCKS-S1 | ✅ PROVEN | CONNECTIVITY | SMU-COMPOSE-BLOCKS.S1 |
| CHK-SMU-COMPOSE-BLOCKS-S2 | ✅ PROVEN | CONNECTIVITY | SMU-COMPOSE-BLOCKS.S2 |
| CHK-SMU-COMPOSE-BLOCKS-S3 | ✅ PROVEN | CONNECTIVITY | SMU-COMPOSE-BLOCKS.S3 |
| CHK-SMU-PORT-CLK-RST-S1 | ✅ PROVEN | LIVE | SMU-PORT-CLK-RST.S1 |
| CHK-SMU-PORT-CLK-RST-S3 | ✅ PROVEN | CONNECTIVITY | SMU-PORT-CLK-RST.S3 |
| CHK-SMU-SEP-PARAM-S1 | ✅ PROVEN | CONNECTIVITY | SMU-SEP-PARAM.S1 |
| CHK-NONVAC | ✅ PROVEN | INTEGRITY | — |
| CHK-TIMEOUT-PATHS | ✅ PROVEN | INTEGRITY | — |

### Layer 1 structural rule set

| Rule | Result |
|---|---|
| F1 fabricated verdict / backdoor write | ✅ clean |
| F2 can't-fail checker | ✅ clean |
| E1 skip-to-pass | ✅ clean |
| E2 empty phase | ✅ clean |
| S1 silent fail | ✅ clean |
| O1 checker disabled | ✅ clean |
| Phase-S obligations — L1 | ✅ clean |
| Phase-S obligations — L2 (needs the card) | ✅ clean |

## Evidence appendix

<details>
<summary>Kept log + build identity</summary>

- Log: `hw/sys/smu/dv/build/kept_logs/smu_wrapper_elaboration_sep_rtl_test.seed1.log` sha256 `ce58253444b88a16cc5e5940f1f6afb5bf658749b431f0d220a43231e185a9c2` (byte-identical to run `20260803_083741__verilator__smu_wrapper_elaboration_sep_rtl_test` sim log)
- Seed: 1 · simulator: verilator 5.050 · target: `compile_smu_chiplet_sep_rtl` · model_fingerprint: `f31560a93189`
- Card: SMU_ALL_001 r18 `9bc02021c17f5120c9ad40bc86209c9e563513e2204478498efd0b4610addefc`
- Parent plan record: r2 `d093a5fa0100b964afe783af8343c735c5c70e0442ea533666db118fe6164d57` · `parent_approved: true`
- Cocotb summary L90: `TESTS=1 PASS=1 FAIL=0 SKIP=0`; final gates L76/L78 executed; no unexplained ERROR/FATAL/Traceback
- Enrolled: `hw/sys/smu/dv/testlists/wrapper.toml` → `smu_wrapper_elaboration_sep_rtl_test`
</details>

<details>
<summary>PROVEN token cites</summary>

| Checker | Line | Token (abbrev) | Impl |
|---|---|---|---|
| CHK-SMU-COMPOSE-BLOCKS-S1 | 47 | `CHK-SMU-COMPOSE-BLOCKS-S1: PASS (sep=1 blocks=smc+sep+dtp+xbar …)` | `smu_wrapper_elaboration_seq.py:214` |
| CHK-SMU-COMPOSE-BLOCKS-S2 | 49 | `CHK-SMU-COMPOSE-BLOCKS-S2: PASS (domain=clk_smu …)` | `:262` |
| CHK-SMU-COMPOSE-BLOCKS-S3 | 52 | `CHK-SMU-COMPOSE-BLOCKS-S3: PASS (port_group=…)` | `:287` |
| CHK-SMU-PORT-CLK-RST-S1 | 61 | `CHK-SMU-PORT-CLK-RST-S1: PASS (rst=cold_assert…)` + lifecycle L54/56/57/60 | `:342` |
| CHK-SMU-PORT-CLK-RST-S3 | 67 | `CHK-SMU-PORT-CLK-RST-S3: PASS (clk=telemetry,sep_wdt…)` + lifecycle L63–66 | `:408` |
| CHK-SMU-SEP-PARAM-S1 | 69 | `CHK-SMU-SEP-PARAM-S1: PASS (… lc_state=from_sep … match=1 …)` | `:438` |
| CHK-TIMEOUT-PATHS | 76 | `CHK-TIMEOUT-PATHS: … (paths=5 bound=500)` | `:469` |
| CHK-NONVAC | 78 | `CHK-NONVAC: Ordered fence S1<…<PASS all hold` | `:484` |
</details>

<details>
<summary>Prior finding closure notes</summary>

- FIND-001: sequence now proves compose presence via `_assert_compose_hier_clk_identity` (hierarchical `obs_*_clk_o` vs toggling `clk_smu_i`, `allow_xz=False`); hardwired `obs_compose_*_present_o` are not asserted on the FAIL-ON path.
- FIND-002: `CHK-SMU-SEP-PARAM-S1` asserts `obs_sep_lc_state_o == lc_state_o` before emitting `lc_state=from_sep`; under `SMU_NO_SEP` the hierarchical source is tied to `8'h00`, so a SEP=0 `0xf0` boundary tie cannot satisfy the compare by coincidence.
</details>

## Accepted waivers

| Finding | Rule | Where | Why | Approved by |
|---|---|---|---|---|
| — | — | — | none | — |

## Human signoff

- **signed_off_by:** minshaoho
- **signed_off_at:** 2026-08-05T18:14:08+08:00
- **decision:** accept evidence-closed grade (Done)
- **note:** Re-audit for plan/card artifact_revision 18 mechanical hash bump; OWNS/checkers unchanged; same kept log; standing-order signoff renewed.
