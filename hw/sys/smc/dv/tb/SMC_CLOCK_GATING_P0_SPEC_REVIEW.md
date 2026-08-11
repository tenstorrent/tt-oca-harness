---
schema: dv-quality/v1
artifact: spec-audit
artifact_revision: 1
content_sha256: 4b59d2ed1c0e98626bf5b46c2ffac448b4466d871af7c7de570a2f1855a889d2
ip: SMC_CLOCK_GATING_P0
milestone: P0
status: approved
pin_revision: 1
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
source_revision: 2ecc7b227e3926b253c65b5aac21239eec24ba5f
quality_policy:
  path: /home/minshaoho/.claude/skills/dv_common/DV_QUALITY_POLICY.md
  revision: 51a3357d9c31a018d69451b055bc956c089af26e1051368e25ce396c84ac2a75
generated_by:
  human_id: minshaoho
  run_id: dv_vplan_gen-SMC_CLOCK_GATING_P0-P0-20260805T151500+0800-fresh
  model:
    provider: anthropic
    family: claude
    version: sonnet-5
derivation_provenance:
  sealed_derivation: true
  anchor_seal_mechanism: ordered-single-context
  fresh_context_route: fresh-subagent
  feature_list_frozen_at: '2026-08-05T15:30:00+08:00'
approved_by: minshaoho
approved_at: '2026-08-05T15:52:00+08:00'
findings:
- id: SF-001
  category: SF-AMBIGUOUS
  severity: Medium
  spec_refs:
  - hw/sys/smc/doc/clk_rst.adoc "The SMC Clock Domain"
  - hw/sys/smc/doc/dma.adoc "DMA Controller Integration"
  - hw/sys/smc/doc/zeroer.adoc "Dual Clock Domain Architecture"
  observed: clk_rst.adoc names the CPU cluster, local fabric, address remap, and filtering as members
    of the primary SMC clock domain (clk_smc_i), but neither dma.adoc nor zeroer.adoc states which top-level
    clock (clk_smc_i, clk_ref_i, or clk_periph_i) feeds the DMA gated clock branch or the Zeroer axi_clk/reg_clk
    domains. The pin boundary's phrase "clk_smc-domain gated clocks for DMA and Zeroer" is the pin author's
    working assumption, not a statement traceable to these pinned docs.
  question: do the DMA gated clock branch and the Zeroer axi_clk/reg_clk domains derive from clk_smc_i,
    and if so where is that binding documented (a missing sentence in dma.adoc/zeroer.adoc, or a different
    pinned source)?
  affects:
    features:
    - SMC-CG-DMA
    - SMC-CG-ZEROER
    scenarios: []
    anchors:
    - SMCCGP0_001
    - SMCCGP0_002
    - SMCCGP0_003
    - SMCCGP0_004
  status: waived
  resolution:
    answered_or_waived_by: minshaoho
    answered_or_waived_at: '2026-08-05T15:52:00+08:00'
    note: P0 accepts the pin-boundary working assumption that DMA gated clock and Zeroer axi_clk/reg_clk
      are observed as clk_smc-domain gated clocks in bring-up. Exact top-level clock-name binding remains
      a documentation debt for dma.adoc/zeroer.adoc; not a P0 bring-up blocker.
    spec_revision: 2f40548ea787240680a1c45ab75b8729e9620778
- id: SF-002
  category: SF-MISSING
  severity: High
  spec_refs:
  - hw/sys/smc/doc/dma.adoc "Clock Gating Configuration"
  - hw/sys/smc/doc/clk_rst.adoc "Clock and Reset-Based Power Management Integration"
  observed: dma.adoc names the cg_enable_i module input and its effect ("cg_enable_i input enables/disables
    clock gating") and clk_rst.adoc names a generic "Module Gating" parameter ("Individual enable/disable
    ... per functional block"), but no pinned source gives the register name, offset, or bit field that
    a firmware/frontdoor write must target to drive cg_enable_i. regs/gen/ is out of the pin's boundary,
    so this cannot be resolved from the generated register map either.
  question: which SMC register (and bit) is cg_enable_i wired from, and in which pinned doc should that
    mapping be stated?
  affects:
    features:
    - SMC-CG-ENABLE-CTRL
    scenarios:
    - SMC-CG-ENABLE-CTRL.S1
    anchors:
    - SMCCGP0_001
  status: answered
  resolution:
    answered_or_waived_by: minshaoho
    answered_or_waived_at: '2026-08-05T15:52:00+08:00'
    note: For P0/P1 verification frontdoor, DMA cg_enable_i is driven from the SMC clock-gate enable CSR
      bit DMA_CG_EN (same path already used by smc_clk_running_test / smc_static_cg_sanity_test). Pin
      boundary excludes regs/gen/; docs should eventually name this mapping in dma.adoc or memmap.adoc.
    spec_revision: e2aae39953bb8001c7c20e3afd3956e68c22440c
- id: SF-003
  category: SF-MISSING
  severity: High
  spec_refs:
  - hw/sys/smc/doc/zeroer.adoc "Clock Gating"
  - hw/sys/smc/doc/clk_rst.adoc "Clock and Reset-Based Power Management Integration"
  observed: zeroer.adoc names the disable_cg signal and its effect on both axi_clk_enable and reg_clk_enable,
    but no pinned source gives the register name, offset, or bit field a firmware/frontdoor write must
    target to drive disable_cg. regs/gen/ is out of the pin's boundary, so this cannot be resolved from
    the generated register map either.
  question: which SMC register (and bit) is disable_cg wired from, and in which pinned doc should that
    mapping be stated?
  affects:
    features:
    - SMC-CG-ENABLE-CTRL
    scenarios:
    - SMC-CG-ENABLE-CTRL.S2
    anchors:
    - SMCCGP0_001
  status: answered
  resolution:
    answered_or_waived_by: minshaoho
    answered_or_waived_at: '2026-08-05T15:52:00+08:00'
    note: For P0/P1 verification frontdoor, Zeroer disable_cg is driven from the SMC clock-gate enable
      CSR bit ZEROER_CG_EN (same path already used by smc_clk_running_test / smc_static_cg_sanity_test).
      Pin boundary excludes regs/gen/; docs should eventually name this mapping in zeroer.adoc or memmap.adoc.
    spec_revision: 2f40548ea787240680a1c45ab75b8729e9620778
---

# SMC_CLOCK_GATING_P0 — Spec Audit (candidate v1)

Three open findings from the same anchor-sealed read that produced the
feature list. `SF-002`/`SF-003` are High because the pinned docs never state
which register/bit drives `cg_enable_i`/`disable_cg` — a real documentation
gap for the spec owner — even though `SMCCGP0_001` (see the testcase plan)
is able to close `SMC-CG-ENABLE-CTRL.S1`/`.S2` anyway, by reusing the
existing anchor's frontdoor writes rather than by resolving this finding.
Closing this finding is still owed to the docs, independent of the fact that
allocation was not blocked. `SF-001` is Medium: it does not block any
scenario's existence, only the "clk_smc-domain" label the pin boundary
applies to the DMA/Zeroer gated clocks; it affects every testcase that
observes those clocks.
