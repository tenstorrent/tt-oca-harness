---
schema: dv-quality/v1
artifact: feature-list
artifact_revision: 1
content_sha256: a5d5f6f1f55a8d4de7436f84c1729ec544c123251bf3338d4f49bff48df2fe90
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
features:
- key: SMC-CG-DMA
  title: DMA controller clock-gated operation
  intent: the DMA frontend/request-manager/backend share one hysteresis-gated clock branch, gated by activity
    and by a gating-enable input, bypassed under DFT test mode
  triad:
    producer: DMA activity signals (frontend wakeup, backend busy) and the cg_enable_i gating-enable input
    transport: single prim_clk_gater_hysteresis clock gater, with a test_en_i bypass mux ahead of it
    consumer: DMA frontend / request-manager / backend logic clocked by the gated clock branch
  spec_refs:
  - hw/sys/smc/doc/dma.adoc Clock Gating Configuration
  record_sha256: 0b959f560c46676f9888744019438d13f207418c5551218becad52e9845f664d
  scenarios:
  - key: SMC-CG-DMA.S1
    intent: test_en_i asserted bypasses DMA clock gating so the gated clock stays free-running under DFT/manufacturing
      test
    requires: LIVE
    spec_refs:
    - hw/sys/smc/doc/dma.adoc "Clock Gating Configuration - Test Mode"
    - hw/sys/smc/doc/port_table.adoc test_en_i
    coverage:
      method: DIRECTED
      required_cells:
      - test-mode-bypass-free-running
      random_knobs: []
      coverage_artifact: null
  - key: SMC-CG-DMA.S2
    intent: after reset release, with cg_enable_i asserted (gating enabled) and no frontend wakeup / backend
      busy activity, the DMA gated clock is held gated — the idle baseline the bring-up smoke starts from
    requires: LIVE
    spec_refs:
    - hw/sys/smc/doc/dma.adoc "Clock Gating Configuration - Activity Detection"
    coverage:
      method: DIRECTED
      required_cells:
      - idle-gated-post-reset
      random_knobs: []
      coverage_artifact: null
  - key: SMC-CG-DMA.S3
    intent: frontend wakeup or backend busy activity ungates the DMA clock from the idle/free-running
      reset-or-test baseline — the boundary's single idle/activity bring-up smoke for DMA
    requires: LIVE
    spec_refs:
    - hw/sys/smc/doc/dma.adoc "Clock Gating Configuration - Activity Detection"
    coverage:
      method: DIRECTED
      required_cells:
      - activity-ungates-clock
      random_knobs: []
      coverage_artifact: null
  - key: SMC-CG-DMA.S4
    intent: with cg_enable_i deasserted (gating disabled), the DMA gated clock stays free-running regardless
      of activity
    requires: LIVE
    spec_refs:
    - hw/sys/smc/doc/dma.adoc "Clock Gating Configuration - Gating Control"
    coverage:
      method: DIRECTED
      required_cells:
      - gate-disabled-free-running
      random_knobs: []
      coverage_artifact: null
- key: SMC-CG-ZEROER
  title: Memory Zeroer dual-clock-domain clock-gated operation
  intent: the Zeroer's AXI-clock and register-clock domains are each independently gated by their own
    activity signal, overridden free-running during reset or manufacturing test, and forced free-running
    by disable_cg
  triad:
    producer: zeroer_busy_o / register_activity activity signals, the disable_cg configuration input,
      and the rst_ni / manufacturing test-enable overrides
    transport: two prim_clkgater instances, one per clock domain (axi_clk, reg_clk)
    consumer: Zeroer AXI master datapath (axi_clk domain) and Zeroer register interface (reg_clk domain)
  spec_refs:
  - hw/sys/smc/doc/zeroer.adoc "Clock Gating"
  record_sha256: 02ad383d2ee0f2fea7c6f684caa86645305856adc50cc30d85401484d7ef523a
  scenarios:
  - key: SMC-CG-ZEROER.S1
    intent: reset asserted (~rst_ni) forces both axi_clk and reg_clk free-running, per the reset-override
      term present in each domain's documented gating equation
    requires: CONNECTIVITY
    spec_refs:
    - hw/sys/smc/doc/zeroer.adoc "Clock Gating - Reset Override"
    coverage:
      method: DIRECTED
      required_cells:
      - reset-forces-free-running
      random_knobs: []
      coverage_artifact: null
  - key: SMC-CG-ZEROER.S2
    intent: the manufacturing test-enable override bypasses gating on both axi_clk and reg_clk
    requires: LIVE
    spec_refs:
    - hw/sys/smc/doc/zeroer.adoc "Clock Gating - Test Support"
    coverage:
      method: DIRECTED
      required_cells:
      - test-enable-bypass
      random_knobs: []
      coverage_artifact: null
  - key: SMC-CG-ZEROER.S3
    intent: after reset release, with disable_cg=0 and zeroer_busy_o=0, axi_clk is held gated — the idle
      baseline for the AXI domain
    requires: LIVE
    spec_refs:
    - hw/sys/smc/doc/zeroer.adoc "Clock Gating - AXI Clock"
    coverage:
      method: DIRECTED
      required_cells:
      - axi-clk-idle-gated
      random_knobs: []
      coverage_artifact: null
  - key: SMC-CG-ZEROER.S4
    intent: triggering a zero operation (zeroer_busy_o asserted) ungates axi_clk from the idle/free-running
      baseline — the boundary's single idle/activity bring-up smoke for the AXI domain
    requires: LIVE
    spec_refs:
    - hw/sys/smc/doc/zeroer.adoc "Clock Gating - AXI Clock"
    coverage:
      method: DIRECTED
      required_cells:
      - busy-ungates-axi-clk
      random_knobs: []
      coverage_artifact: null
  - key: SMC-CG-ZEROER.S5
    intent: after reset release, with disable_cg=0 and register_activity=0, reg_clk is held gated — the
      idle baseline for the register-clock domain
    requires: LIVE
    spec_refs:
    - hw/sys/smc/doc/zeroer.adoc "Clock Gating - Register Clock"
    coverage:
      method: DIRECTED
      required_cells:
      - reg-clk-idle-gated
      random_knobs: []
      coverage_artifact: null
  - key: SMC-CG-ZEROER.S6
    intent: a register access (register_activity asserted) ungates reg_clk from the idle/free-running
      baseline — the boundary's single idle/activity bring-up smoke for the register-clock domain
    requires: LIVE
    spec_refs:
    - hw/sys/smc/doc/zeroer.adoc "Clock Gating - Register Clock"
    coverage:
      method: DIRECTED
      required_cells:
      - register-access-ungates-reg-clk
      random_knobs: []
      coverage_artifact: null
  - key: SMC-CG-ZEROER.S7
    intent: with disable_cg asserted (gating disabled), axi_clk and reg_clk stay free-running regardless
      of zeroer_busy_o / register_activity — the Zeroer counterpart of the DMA gate-disabled free-running
      scenario
    requires: LIVE
    spec_refs:
    - hw/sys/smc/doc/zeroer.adoc "Clock Gating"
    coverage:
      method: DIRECTED
      required_cells:
      - gate-disabled-free-running
      random_knobs: []
      coverage_artifact: null
- key: SMC-CG-ENABLE-CTRL
  title: Frontdoor reachability of the DMA and Zeroer clock-gating enable controls
  intent: firmware can reach the per-module clock-gating enable/disable control (DMA cg_enable_i, Zeroer
    disable_cg) that the SMC clock-gating parameter table names generically as Module Gating
  triad:
    producer: firmware/frontdoor register write on the SMC register bus
    transport: SMC AXI4-Lite register decode path into the module's gating-enable input (the pinned docs
      name the destination signals but not the register/bit that drives them — see SF-002/SF-003)
    consumer: DMA cg_enable_i / Zeroer disable_cg gating-enable inputs
  spec_refs:
  - hw/sys/smc/doc/clk_rst.adoc "Clock and Reset-Based Power Management Integration"
  record_sha256: 600221153c5dfe99b02b424ff834ba5b89ed94498121e31f0ba5be74a024557b
  scenarios:
  - key: SMC-CG-ENABLE-CTRL.S1
    intent: DMA's cg_enable_i clock-gating enable input is reachable from a firmware-writable register
    requires: CONNECTIVITY
    spec_refs:
    - hw/sys/smc/doc/clk_rst.adoc "Clock and Reset-Based Power Management Integration"
    - hw/sys/smc/doc/dma.adoc "Clock Gating Configuration - Gating Control"
    coverage:
      method: DIRECTED
      required_cells:
      - dma-cg-enable-frontdoor-reachable
      random_knobs: []
      coverage_artifact: null
  - key: SMC-CG-ENABLE-CTRL.S2
    intent: Zeroer's disable_cg clock-gating disable input is reachable from a firmware-writable register
    requires: CONNECTIVITY
    spec_refs:
    - hw/sys/smc/doc/clk_rst.adoc "Clock and Reset-Based Power Management Integration"
    - hw/sys/smc/doc/zeroer.adoc "Clock Gating"
    coverage:
      method: DIRECTED
      required_cells:
      - zeroer-disable-cg-frontdoor-reachable
      random_knobs: []
      coverage_artifact: null
interactions: []
---

# SMC_CLOCK_GATING_P0 — Spec Feature List (candidate v1)

Complete in-scope spec surface for the `SMC_CLOCK_GATING_P0` pin's boundary
(P0 bring-up only, after reset release): DMA and Zeroer clock-gated clock
branches, and frontdoor/CSR reachability of their gating-enable controls.
Derived forward from the 9 pinned SPEC sources only, anchor-sealed
(`ordered-single-context`) until this freeze. No feature here was trimmed to
what an existing test happens to cover.

Three features / thirteen scenarios. No interaction is required by the pinned
docs within this boundary — DMA gating and Zeroer gating are each
self-contained bring-up behaviors with no SPEC-mandated joint observation
between them, so `interactions: []` is authoritative, not an omission.

Two scenarios (`SMC-CG-ENABLE-CTRL.S1`, `.S2`) cite an unresolved register
identity — see `SMC_CLOCK_GATING_P0_SPEC_REVIEW.md` findings `SF-002`/`SF-003`.
