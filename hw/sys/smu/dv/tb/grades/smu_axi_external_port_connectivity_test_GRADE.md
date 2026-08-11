---
schema: dv-quality/v1
artifact: testcase-grade
testcase: smu_axi_external_port_connectivity_test
ip: SMU_ALL
anchor: smu_axi_external_port_connectivity_test
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
card_sha256: 833d5b2b2baad8adf5b14a87f8be1eb5103d13f3e53119afb76c15966d24a6c0
card_revision: 18
card_path: hw/sys/smu/dv/tb/SMU_ALL_VPLAN_DETAIL.md
testcase_plan:
  path: hw/sys/smu/dv/tb/SMU_ALL_TESTCASE_PLAN.md
  plan_revision: 18
  testcase_revision: 3
  testcase_record_sha256: 68670b83ed1825edffb684356e0e887488144ba3dfd3b7a17c25a7a30bedf0b9
  parent_approved: true
evidence_class: frontdoor-func
closure_tier: B
quality_policy:
  path: hw/sys/smu/dv/tb/SMU_ALL_QUALITY_POLICY.md
  revision: 936b77700909a93bb122f9fb124a3ffb6f5dac5f508c623c5950285a5cefb79a
build_config: default
simulator: verilator
simulator_version: 5.050 2026-07-01 rev v5.050 (mod)
compile_target: default
model_fingerprint: 74386ebf48af
compile_inputs_sha256: null
seeds:
- 1
logs:
- path: hw/sys/smu/dv/build/kept_logs/smu_axi_external_port_connectivity_test.seed1.log
  sha256: df05f91ec71e702daea2a045fba9e06b4f5c5d659a09890589ca586c9947fb8b
test_author:
  human_id: minshaoho
  run_id: dv_test_impl-SMU_ALL_002-27bcecd2
  model:
    provider: cursor
    family: grok
    version: '4.5'
auditor:
  human_id: minshaoho
  run_id: dv_test_audit-SMU_ALL_002-r18-75c1aff41eb5
  model:
    provider: cursor
    family: grok
    version: '4.5'
exceptions: []
checkers:
- id: CHK-SMU-PORT-SMN-AXI-S1
  checks_steps:
  - S2
  proves:
  - SMU-PORT-SMN-AXI
  covers:
  - SMU-PORT-SMN-AXI.S1
  proof_class: CONNECTIVITY
  expect_source: pinned SPEC citations on SMU-PORT-SMN-AXI.S1 in SMU_ALL_SPEC_FEATURE_LIST.md
  grade: PROVEN
  evidence:
  - token: 'CHK-SMU-PORT-SMN-AXI-S1: PASS (dir=in dest=smc_aperture path=direct_iw addr=0xc0002900 awid=0x42 bid=0x42 bresp=DECERR arid=0x43 rid=0x43 rresp=DECERR rdata=0xbadcab1e)'
    log_sha256: df05f91ec71e702daea2a045fba9e06b4f5c5d659a09890589ca586c9947fb8b
    line: 126
    seed: 1
    implementation_path: hw/sys/smu/dv/cocotb/seq_lib/smu_axi_external_port_connectivity_test_seq.py:235
  lifecycle_results: null
  coverage_results:
  - key: SMU-PORT-SMN-AXI.S1
    method: DIRECTED
    required_cells:
    - dir=in
    - dest=smc_aperture
    achieved_cells:
    - dir=in
    - dest=smc_aperture
    random_knobs: []
    resolved_knobs: []
    min_seeds: 1
    actual_seeds:
    - 1
    required_artifact: null
    coverage_artifacts:
    - hw/sys/smu/dv/build/kept_logs/smu_axi_external_port_connectivity_test.seed1.log#df05f91ec71e702daea2a045fba9e06b4f5c5d659a09890589ca586c9947fb8b
    satisfied: true
  linked_issue: null
  finding_ids: []
  remediation: null
- id: CHK-SMU-SEP-PARAM-S2
  checks_steps:
  - S3
  proves:
  - SMU-SEP-PARAM
  covers:
  - SMU-SEP-PARAM.S2
  proof_class: CONNECTIVITY
  expect_source: pinned SPEC citations on SMU-SEP-PARAM.S2 in SMU_ALL_SPEC_FEATURE_LIST.md
  grade: PROVEN
  evidence:
  - token: 'CHK-SMU-SEP-PARAM-S2: PASS (sep=0 path=direct_smc_ext iw=u_iw_conv_smc_in+u_iw_conv_smc_out xbar=absent clk_identity=1)'
    log_sha256: df05f91ec71e702daea2a045fba9e06b4f5c5d659a09890589ca586c9947fb8b
    line: 132
    seed: 1
    implementation_path: hw/sys/smu/dv/cocotb/seq_lib/smu_axi_external_port_connectivity_test_seq.py:263
  lifecycle_results: null
  coverage_results:
  - key: SMU-SEP-PARAM.S2
    method: DIRECTED
    required_cells:
    - sep=0
    - path=direct_smc_ext
    achieved_cells:
    - sep=0
    - path=direct_smc_ext
    random_knobs: []
    resolved_knobs: []
    min_seeds: 1
    actual_seeds:
    - 1
    required_artifact: null
    coverage_artifacts:
    - hw/sys/smu/dv/build/kept_logs/smu_axi_external_port_connectivity_test.seed1.log#df05f91ec71e702daea2a045fba9e06b4f5c5d659a09890589ca586c9947fb8b
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
  proves: []
  covers: []
  proof_class: INTEGRITY
  expect_source: approved card ordering contract
  grade: PROVEN
  evidence:
  - token: 'CHK-NONVAC: Ordered fence S1<S2<S3<S4<PASS all hold'
    log_sha256: df05f91ec71e702daea2a045fba9e06b4f5c5d659a09890589ca586c9947fb8b
    line: 147
    seed: 1
    implementation_path: hw/sys/smu/dv/cocotb/seq_lib/smu_axi_external_port_connectivity_test_seq.py:335
  lifecycle_results: null
  coverage_results: []
  linked_issue: null
  finding_ids: []
  remediation: null
- id: CHK-TIMEOUT-PATHS
  checks_steps:
  - S4
  proves: []
  covers: []
  proof_class: INTEGRITY
  expect_source: approved card timeout contract
  grade: PROVEN
  evidence:
  - token: 'CHK-TIMEOUT-PATHS: Finite bound on S4; expiry fails with last-state diagnostics (paths=2 expect=2 bound=200000ns)'
    log_sha256: df05f91ec71e702daea2a045fba9e06b4f5c5d659a09890589ca586c9947fb8b
    line: 142
    seed: 1
    implementation_path: hw/sys/smu/dv/cocotb/seq_lib/smu_axi_external_port_connectivity_test_seq.py:302
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
content_sha256: 2ce8cf592be3261c156b08ac16b15a1809bebf07b873bb116fdbef1c8a93662e
---

# Grade Report — smu_axi_external_port_connectivity_test (SMU_ALL_002)

**VERDICT: 4/4 PROVEN — READY** (mode CHECKBOX, entry PASS)

| Mode | Entry gate | Checkers | Findings | Recommendation |
|---|---|---|---|---|
| `CHECKBOX` | ✅ PASS | 4/4 PROVEN | none | ✅ EVIDENCE-CLOSED-AWAITING-SIGNOFF |

> Entry PASS on kept log `df05f91e…` (run `20260803_104221`, byte-identical). Parent plan r18 hash `68670b83…` matches card r4→r18. Prior FIND-001 closed by FL S1 split (`dest=smc_aperture` only); FIND-002/003 closed in the r4 test body. All four checkers PROVEN.

## DELTA (re-audit vs prior grade)

| Item | Prior (`dv_test_audit-SMU_ALL_002-r4-a7f3c291-6e4b-4d18-9c2a-8f15b0e3d749`, card r4) | This audit (`dv_test_audit-SMU_ALL_002-r18-75c1aff41eb5`, card r18) |
|---|---|---|
| Verdict | 4/4 PROVEN — READY | 4/4 PROVEN — READY |
| Card hash | `61e6a1d6e4b3a7f36b116cea03e3071127257a88b50b87161c3dd4b5bc62cca6` (STALE vs plan r18) | `833d5b2b2baad8adf5b14a87f8be1eb5103d13f3e53119afb76c15966d24a6c0` (current) |
| Plan revision | 4 | 18 |
| Checkers / OWNS | unchanged | unchanged — all 4 tokens re-verified on same kept log |
| Kept log | `df05f91ec71e702daea2a045fba9e06b4f5c5d659a09890589ca586c9947fb8b` | `df05f91ec71e702daea2a045fba9e06b4f5c5d659a09890589ca586c9947fb8b` (unchanged) |
| Findings | none open | none open |
| Waivers carried | none signed | none |
| Signoff | prior `2026-08-05T17:16:48+08:00` | renewed `2026-08-05T18:14:08+08:00` (standing order) |


## Your to-do — none

**SIGNOFF RECORDED** — see ## Human signoff below.

**Then:** `/dv_peer_audit` on SMU_ALL when all seven r18 grades are filed.

## All checkers

| Checker | Grade | Proof class | Covers |
|---|---|---|---|
| CHK-SMU-PORT-SMN-AXI-S1 | ✅ PROVEN | CONNECTIVITY | SMU-PORT-SMN-AXI.S1 |
| CHK-SMU-SEP-PARAM-S2 | ✅ PROVEN | CONNECTIVITY | SMU-SEP-PARAM.S2 |
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

- Log: `hw/sys/smu/dv/build/kept_logs/smu_axi_external_port_connectivity_test.seed1.log` sha256 `df05f91ec71e702daea2a045fba9e06b4f5c5d659a09890589ca586c9947fb8b` (byte-identical to run `20260803_104221__verilator__smu_axi_external_port_connectivity_test` sim log)
- Seed: 1 · simulator: verilator 5.050 · target: `default` · model_fingerprint: `74386ebf48af`
- Card: SMU_ALL_002 r18 `833d5b2b2baad8adf5b14a87f8be1eb5103d13f3e53119afb76c15966d24a6c0` (recomputed match)
- Parent plan record: r3 `68670b83ed1825edffb684356e0e887488144ba3dfd3b7a17c25a7a30bedf0b9` · `plan_revision: 4` · `parent_approved: true` (recomputed match)
- Feature list: artifact_revision 2; `SMU-PORT-SMN-AXI.S1` required_cells `[dir=in, dest=smc_aperture]`; `SMU-SEP-PARAM.S2` `[sep=0, path=direct_smc_ext]`
- Cocotb summary L166: `TESTS=1 PASS=1 FAIL=0 SKIP=0`; final assertion gates executed; no unexplained ERROR/FATAL/Traceback
- Enrolled: `hw/sys/smu/dv/testlists/fabric.toml` → `smu_axi_external_port_connectivity_test`
- Address probe: `SMC_CHIP_CONFIG_VERSION_LO` from generated `smc_addr.h` via `smu_addr_map.py` (authoritative map)

</details>

<details>
<summary>Token / step cites (kept log `df05f91e…`)</summary>

| Checker | Line | What the log shows | Impl |
|---|---|---|---|
| (setup) | 23 | `STEP S1` | seq `:168` |
| CHK-SMU-PORT-SMN-AXI-S1 | 126 | `… PASS (… dest=smc_aperture … bresp=DECERR … rdata=0xbadcab1e)` + AXI write/read @ `0xc0002900` L110–121 | seq `:235` |
| CHK-SMU-SEP-PARAM-S2 | 132 | `… PASS (… iw=u_iw_conv_smc_in+u_iw_conv_smc_out xbar=absent clk_identity=1)` | seq `:263` |
| CHK-TIMEOUT-PATHS | 142 | `… paths=2 expect=2 bound=200000ns` (TIMEOUT-PATH L140–141) | seq `:302` |
| CHK-NONVAC | 147 | `Ordered fence S1<S2<S3<S4<PASS all hold` | seq `:335` |

</details>

<details>
<summary>Layer 1 notes (no open F/E/S)</summary>

- Ordered fence S1 SETUP → S2 frontdoor AXI ACTION/RESPONSE (DECERR+poison) → S3 hierarchy EFFECT → S4 timeout inventory → PASS: non-empty, ordered, AssertionError-gated.
- S1 FAIL-ON: unexpected BRESP/RRESP, BID/RID mismatch, DECERR without SMC filter poison `0xBADCAB1E`; address from authoritative map.
- S2 FAIL-ON: `gen_sep` / `u_smu_axi_xbar` presence, missing IW converters, clk identity mismatch, SEP aperture outputs not tied off; scoreboard compares sampled `sep_*_o` to 0 (not `True/True`).
- Timeout paths use `with_timeout(..., 200_000 ns)` and log the same bound; expiry raises with last-state.
- NONVAC compares positive wall-clock step-delta count to 4 (not decorative True/True).
- `+skip_fuse_sense` / ROM backdoor appear in trailer for bring-up only; not on the AXI/IW proof path.
- Regression enrolled; evidence map lists the four Option B tokens.
- No merged-evidence collision: each feature checker has an independent token; integrity checkers do not substitute for feature proof.

</details>

<details>
<summary>Prior finding closure verification</summary>

- FIND-001: frozen FL `SMU-PORT-SMN-AXI.S1` now requires only `dir=in` + `dest=smc_aperture`; `dest=sep_aperture` moved to `SMU-PORT-SMN-AXI.S4` on SMU_ALL_008. Kept log L109/L126 achieve both required cells.
- FIND-002: `sb.expect_eq` now compares `sep_global_base_o`/`sep_region_size_o` to 0 and NONVAC positive-delta count to 4 (seq `:265–275`, `:336–341`); log L133/L148 show numeric compares.
- FIND-003: TIMEOUT-PATH / CHK-TIMEOUT-PATHS log `bound=200000ns` (L140–142), matching `AXI_TIMEOUT_NS = 200_000` passed to `with_timeout`.

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
