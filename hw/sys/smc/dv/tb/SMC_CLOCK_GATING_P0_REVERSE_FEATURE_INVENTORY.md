---
schema: dv-quality/v1
artifact: reverse-feature-inventory
reverse_inventory: true
ip: SMC_CLOCK_GATING_P0
milestone: P0
status: candidate
pin_consulted: false
sealed_derivation: true
anchor_seal_mechanism: ordered-single-context
spec:
- path: hw/sys/smc/doc/index.adoc
  revision: "git:2ecc7b227e3926b253c65b5aac21239eec24ba5f blob:1ebe3476b72721f2b7cb450dea6c8627ae5b4e79"
- path: hw/sys/smc/doc/overview.adoc
  revision: "git:2f40548ea787240680a1c45ab75b8729e9620778 blob:6a91db1690354be3378788ad1ec6f2b1a4af67f4"
- path: hw/sys/smc/doc/clk_rst.adoc
  revision: "git:2f40548ea787240680a1c45ab75b8729e9620778 blob:1624576459c333df2917427e747bb02201a23e96"
- path: hw/sys/smc/doc/port_table.adoc
  revision: "git:2ecc7b227e3926b253c65b5aac21239eec24ba5f blob:24f71bc5f1e94f917a9ef6d2bac5239e36e1ec47"
- path: hw/sys/smc/doc/dma.adoc
  revision: "git:e2aae39953bb8001c7c20e3afd3956e68c22440c blob:76e6588b565fd72bfc7721e4314b954149dd41ce"
- path: hw/sys/smc/doc/zeroer.adoc
  revision: "git:2f40548ea787240680a1c45ab75b8729e9620778 blob:c07fa1a2729c42db741ce0998e781da8bd3a9914"
- path: hw/sys/smc/doc/periphs.adoc
  revision: "git:ffc8cdcc349e1e01a2b970442a01070b1c62c0d7 blob:3f361e2a89e28f0f026ee794585ad67865e0cacf"
- path: hw/sys/smc/doc/fabric.adoc
  revision: "git:ffc8cdcc349e1e01a2b970442a01070b1c62c0d7 blob:756385874b9e21eeaf36fe392e09b78a28744617"
- path: hw/sys/smc/doc/memmap.adoc
  revision: "git:2ecc7b227e3926b253c65b5aac21239eec24ba5f blob:c805b5bee77815cd203025c1036aad9bf3ba0da9"
generated_by:
  human_id: fresh-subagent-unattended
  run_id: dv_vplan_gen-SMC_CLOCK_GATING_P0-reverse-inventory-20260805T090055Z-fresh
  model: {provider: anthropic, family: claude, version: claude-sonnet-4.5}
content_sha256: TBD-COMPUTE
features:
- key: SMC-CG-DMA
  title: DMA Frontend/Request-Manager/Backend Clock Gating (Single Hysteresis Gater)
  intent: >
    A single prim_clk_gater_hysteresis instance gates the shared clock feeding the DMA
    frontend (idma_frontend_wrapper), request manager (idma_request_manager_wrapper), and
    backend (idma_backend_wrapper), so the DMA clock consumers are held un-clocked when idle
    and re-enabled on activity, with a firmware-visible enable/disable and a DFT bypass.
  spec_refs:
  - 'hw/sys/smc/doc/dma.adoc "Performance Optimization and Power Management / Clock Gating Configuration"'
  - 'hw/sys/smc/doc/dma.adoc "Configuration Parameters" (CG_HYSTERESIS_W)'
  - 'hw/sys/smc/doc/port_table.adoc "SMC Port Declaration" (test_en_i row)'
  - 'hw/sys/smc/doc/memmap.adoc "Detailed Address Map" (DMA Controller row)'
  scenarios:
  - key: SMC-CG-DMA.S1
    intent: >
      After reset release, the DMA-domain gated clock is present and capable of toggling
      (not stuck low/high), as a basic bring-up presence/toggling check named by the P0
      boundary.
    requires: LIVE
    spec_refs:
    - 'hw/sys/smc/doc/dma.adoc "Clock Gating Configuration" (Clock Gating Implementation row)'
  - key: SMC-CG-DMA.S2
    intent: >
      Single idle-to-activity smoke: with cg_enable_i asserted and no frontend
      wakeup/backend-busy activity, the gated DMA clock leaves the free-running reset/test
      state (i.e. is observed gated while idle), then re-toggles once activity
      (frontend wakeup or backend busy) is asserted.
    requires: LIVE
    spec_refs:
    - 'hw/sys/smc/doc/dma.adoc "Clock Gating Configuration" (Activity Detection, Gating Control rows)'
  - key: SMC-CG-DMA.S3
    intent: >
      CSR/frontdoor reachability of the DMA clock-gate enable control (cg_enable_i) through
      the DMA controller's AXI4-Lite control interface at its documented address range, so
      firmware can enable/disable DMA clock gating.
    requires: CONNECTIVITY
    spec_refs:
    - 'hw/sys/smc/doc/dma.adoc "Clock Gating Configuration" (Gating Control row)'
    - 'hw/sys/smc/doc/dma.adoc "DMA Controller Integration" (Address Range, Control Interface rows)'
    - 'hw/sys/smc/doc/memmap.adoc "Detailed Address Map" (DMA Controller row)'
  - key: SMC-CG-DMA.S4
    intent: >
      The top-level test_en_i DFT/scan test-enable input reaches the DMA clock-gater's test
      bypass port, so clock gating is bypassed (clock free-runs) during test mode.
    requires: CONNECTIVITY
    spec_refs:
    - 'hw/sys/smc/doc/dma.adoc "Clock Gating Configuration" (Test Mode row)'
    - 'hw/sys/smc/doc/port_table.adoc "SMC Port Declaration" (test_en_i row)'
- key: SMC-CG-ZEROER-AXI
  title: Zeroer AXI-Master Clock Gating (Busy-Gated)
  intent: >
    The zeroer's AXI-domain clock (axi_clk) is gated by a prim_clkgater such that it is
    enabled only while the zeroer is actively performing a zero operation
    (axi_clk_enable = disable_cg | zeroer_busy_o | ~rst_ni), independent of register-path
    activity.
  spec_refs:
  - 'hw/sys/smc/doc/zeroer.adoc "Dual Clock Domain Architecture / Clock Domains"'
  - 'hw/sys/smc/doc/zeroer.adoc "Clock Gating" (Clock Gating Control table, AXI Clock row)'
  - 'hw/sys/smc/doc/memmap.adoc "Detailed Address Map" (Memory Zeroer row)'
  scenarios:
  - key: SMC-CG-ZEROER-AXI.S1
    intent: >
      After reset release, the zeroer's axi_clk gated clock is present and capable of
      toggling (not stuck), as a basic bring-up presence/toggling check named by the P0
      boundary.
    requires: LIVE
    spec_refs:
    - 'hw/sys/smc/doc/zeroer.adoc "Clock Gating Control" (AXI Clock row)'
  - key: SMC-CG-ZEROER-AXI.S2
    intent: >
      Single idle-to-activity smoke: with disable_cg de-asserted and zeroer_busy_o low
      (ST_IDLE), axi_clk leaves the free-running reset/test state (observed gated while
      idle), then re-toggles once a zero operation is triggered and zeroer_busy_o asserts.
    requires: LIVE
    spec_refs:
    - 'hw/sys/smc/doc/zeroer.adoc "Clock Gating Control" (AXI Clock row)'
    - 'hw/sys/smc/doc/zeroer.adoc "State Machine" (ST_IDLE description)'
  - key: SMC-CG-ZEROER-AXI.S3
    intent: >
      CSR/frontdoor reachability of the zeroer's clock-gate disable control (disable_cg)
      through the zeroer's AXI4-Lite control interface at its documented address range,
      so firmware can force axi_clk free-running.
    requires: CONNECTIVITY
    spec_refs:
    - 'hw/sys/smc/doc/zeroer.adoc "Clock Gating Control" (AXI Clock row)'
    - 'hw/sys/smc/doc/zeroer.adoc "Memory Zeroer Integration" (Address Range, Control Interface rows)'
    - 'hw/sys/smc/doc/memmap.adoc "Detailed Address Map" (Memory Zeroer row)'
  - key: SMC-CG-ZEROER-AXI.S4
    intent: >
      The top-level test_en_i test-enable reaches the zeroer's AXI-clock-gater test bypass
      ("Test Support: Test enable override for manufacturing test"), bypassing gating during
      test mode.
    requires: CONNECTIVITY
    spec_refs:
    - 'hw/sys/smc/doc/zeroer.adoc "Clock Gating Control" (Test Support row)'
    - 'hw/sys/smc/doc/port_table.adoc "SMC Port Declaration" (test_en_i row)'
- key: SMC-CG-ZEROER-REG
  title: Zeroer Register-Interface Clock Gating (Register-Activity-Gated, AXI-Independent)
  intent: >
    The zeroer's register-domain clock (reg_clk) is gated by a separate prim_clkgater such
    that it is enabled by register_activity independent of AXI activity
    (reg_clk_enable = disable_cg | register_activity | ~rst_ni), per the doc's explicit
    statement that the register clock is "independent of AXI activity."
  spec_refs:
  - 'hw/sys/smc/doc/zeroer.adoc "Dual Clock Domain Architecture / Clock Domains" (Register Clock row)'
  - 'hw/sys/smc/doc/zeroer.adoc "Clock Gating" (Clock Gating Control table, Register Clock row)'
  - 'hw/sys/smc/doc/memmap.adoc "Detailed Address Map" (Memory Zeroer row)'
  scenarios:
  - key: SMC-CG-ZEROER-REG.S1
    intent: >
      After reset release, the zeroer's reg_clk gated clock is present and capable of
      toggling (not stuck), as a basic bring-up presence/toggling check named by the P0
      boundary.
    requires: LIVE
    spec_refs:
    - 'hw/sys/smc/doc/zeroer.adoc "Clock Gating Control" (Register Clock row)'
  - key: SMC-CG-ZEROER-REG.S2
    intent: >
      Single idle-to-activity smoke: with disable_cg de-asserted and no register_activity,
      reg_clk leaves the free-running reset/test state (observed gated while idle), then
      re-toggles on a single register access (e.g. a CTRL_STATUS/DEST_ADDR/SIZE access).
      P0 scope is this single smoke only; full AXI/REG independence proof (that reg_clk
      keeps toggling on register access while axi_clk stays gated, and vice versa) is
      explicitly OUT for P0 per the boundary text.
    requires: LIVE
    spec_refs:
    - 'hw/sys/smc/doc/zeroer.adoc "Clock Gating Control" (Register Clock row)'
  - key: SMC-CG-ZEROER-REG.S3
    intent: >
      CSR/frontdoor reachability of the zeroer's register block itself (DEST_ADDR, SIZE,
      CTRL_STATUS) at its documented address range, as the precondition path by which
      register_activity can be exercised.
    requires: CONNECTIVITY
    spec_refs:
    - 'hw/sys/smc/doc/zeroer.adoc "Control and Status / Operation Control" (register table)'
    - 'hw/sys/smc/doc/memmap.adoc "Detailed Address Map" (Memory Zeroer row)'
interactions: []   # No SPEC-mandated joint/ordered behavior between DMA clock gating and
                   # Zeroer clock gating (or between the Zeroer's two gated clocks beyond the
                   # single independence smoke already captured as SMC-CG-ZEROER-REG.S2) is
                   # named by the pinned docs; the two blocks' gating mechanisms are described
                   # independently with no cross-block sequencing or shared-state requirement.
sf_findings:
- id: SF-001
  severity: Medium
  text: >
    dma.adoc names the DMA clock-gate enable signal only as "cg_enable_i" with no register
    or bit-field identity given; the P0 boundary's "CSR/frontdoor reachability of clock-gate
    enable controls" cannot be tied to a concrete decodable register/bit from the pinned
    docs alone (regs/gen is explicitly OUT of scope for this derivation).
- id: SF-002
  severity: Medium
  text: >
    zeroer.adoc names "disable_cg" and "register_activity" in its clock-gating formulas but
    the register table in "Control and Status / Operation Control" (DEST_ADDR, SIZE,
    CTRL_STATUS, Interrupt Enable) does not name which field maps to disable_cg; the mapping
    from CTRL_STATUS bit(s) to disable_cg is not established by the pinned docs.
- id: SF-003
  severity: Low
  text: >
    clk_rst.adoc's generic "Clock and Reset-Based Power Management Integration" table lists
    "Hysteresis Control (6-bit programmable)" as a cross-module clock-gating parameter, and
    dma.adoc's CG_HYSTERESIS_W=6 confirms this for DMA — but zeroer.adoc's documented gating
    formulas (axi_clk_enable, reg_clk_enable) show only level-sensitive OR-reduction with no
    hysteresis/delay term. It is ambiguous whether the Zeroer's clock gating is intended to
    include hysteresis (per the generic table) or is a pure level-gated cell (per the
    zeroer-specific formulas); this affects whether the P0 boundary's "full hysteresis
    sweeps" exclusion is even applicable to the Zeroer.
- id: SF-004
  severity: Medium
  text: >
    None of clk_rst.adoc, dma.adoc, or port_table.adoc explicitly states which top-level
    clock domain (clk_smc_i, clk_ref_i, or clk_periph_i) feeds the DMA controller's or the
    Zeroer's gated clocks. clk_rst.adoc's "The SMC Clock Domain" description enumerates the
    CPU cluster, local fabric, and control/remap/filtering logic as clk_smc_i members but
    does not name the DMA engine or the memory Zeroer. The P0 boundary text asserts these
    are "clk_smc-domain gated clocks," but that specific domain assignment is not directly
    traceable to an explicit statement in the 9 pinned docs read for this derivation.
- id: SF-005
  severity: Low
  text: >
    zeroer.adoc names its two clocks descriptively as "AXI Clock (axi_clk)" and "Register
    Clock (reg_clk)"; these names do not appear in port_table.adoc's "SMC Port Declaration"
    table, which only lists clk_smc_i/clk_ref_i/clk_periph_i/clk_telemetry_i at the SMC
    top level. Whether axi_clk/reg_clk are internally-generated gated versions of clk_smc_i,
    or distinct wires, is not stated — an identity gap for any test needing to name a
    probeable signal.
- id: SF-006
  severity: Low
  text: >
    dma.adoc's "Test Mode: Clock gating bypassed during test mode" and zeroer.adoc's "Test
    Support: Test enable override for manufacturing test" both presumably rely on the single
    top-level test_en_i port (port_table.adoc: "Drives clock-gater test ports and AXI cell
    test inputs"), but neither dma.adoc nor zeroer.adoc names the exact internal test-enable
    port reached on each block's specific gater cell — an untestable-at-this-level identity
    gap for any DECODE-precision connectivity check.
---

# SMC_CLOCK_GATING_P0 — Reverse Feature Inventory (candidate, anchor-blind)

This candidate inventory was derived strictly forward from the 9 pinned SMC SPEC AsciiDoc
files listed above (`index.adoc`, `overview.adoc`, `clk_rst.adoc`, `port_table.adoc`,
`dma.adoc`, `zeroer.adoc`, `periphs.adoc`, `fabric.adoc`, `memmap.adoc`) and the P0
bring-up/observability boundary text supplied directly in the task prompt. It identifies
**3 features**, **11 scenarios**, **0 interactions**, and **6 SF-findings**.

The three features correspond to the only clock-gating mechanisms named anywhere in the
9 pinned docs within the P0 boundary: the DMA controller's single hysteresis-based gater
shared across its frontend/request-manager/backend (`SMC-CG-DMA`), and the memory Zeroer's
two independent busy/activity-gated clocks — the AXI-master clock (`SMC-CG-ZEROER-AXI`) and
the register-interface clock (`SMC-CG-ZEROER-REG`). No other SMC block documented in
`periphs.adoc` or `fabric.adoc` names a clock-gating mechanism, so no additional features
were derived from those two files (they were read in full but contributed no clock-gating
content in scope). Each feature's scenarios were scoped to the P0 boundary's three named
behavior classes — gated-clock presence/toggling, CSR/frontdoor reachability of the
gate-enable control, and a single idle→activity smoke proving escape from the free-running
reset/test state — plus a DFT/test_en_i bypass-reachability check, since `test_en_i` is
explicitly named in `port_table.adoc` as driving "clock-gater test ports." Full hysteresis
sweeps, activity-during-hysteresis races, the Zeroer's AXI/REG independence proof beyond a
single smoke, the DFT/test_en full matrix, multi-ID counter capacity, and PLL/CGM/AWM
material were all treated as OUT per the boundary text and are not represented as P0
scenarios (they remain latent in the SPEC for a later milestone). No SPEC-mandated joint or
ordered behavior between the DMA and Zeroer clock-gating mechanisms was found, so
`interactions` is empty. Six SF-findings were recorded, chiefly around missing
register/bit-field identity for the `cg_enable_i`/`disable_cg` controls, an unstated
clock-domain-membership claim for DMA/Zeroer within `clk_smc_i`, and a possible hysteresis
vs. pure-level-gating ambiguity between the generic power-management table and the
Zeroer-specific gating formulas.

**No existing DV planning artifact, test, grade, card, pin file, or prior audit for this IP
was consulted at any point during this derivation.** No file matching the forbidden
patterns (`SMC_CLOCK_GATING*`, `smc_cg_*`, `smc_clk_*`, `smc_static_cg_*`, `smc_zeroer_*`,
`audit_status_smc*`, anything under `hw/sys/smc/dv/`, or any file named with
"PEER_AUDIT", "VPLAN", "TESTCASE_PLAN", "FEATURE_LIST", "PIN.yaml", "GRADE", "REVIEW", or
"REVERSE_FEATURE_INVENTORY") was opened, searched for, or globbed. This inventory reflects
only what the 9 pinned SPEC files and the given P0 boundary text support.
