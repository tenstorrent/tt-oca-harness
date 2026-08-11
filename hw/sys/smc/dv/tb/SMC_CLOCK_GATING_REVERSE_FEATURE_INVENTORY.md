---
schema: dv-quality/v1
artifact: feature-list
artifact_revision: 1
content_sha256: 535b4a2d146baf5f1c822ecc0588516d0016b92fe18725e5d626558c711eef92
ip: SMC_CLOCK_GATING
milestone: P1
status: candidate
pin_revision: null
source_revision: 2ecc7b227e3926b253c65b5aac21239eec24ba5f
quality_policy:
  path: .claude/skills/dv_common/DV_QUALITY_POLICY.md
  revision: 51a3357d9c31a018d69451b055bc956c089af26e1051368e25ce396c84ac2a75
approved_by: null
approved_at: null
generated_by:
  human_id: fresh-subagent-unattended
  run_id: dv_vplan_gen-SMC_CLOCK_GATING-reverse-inventory-20260805T121100+0800-fresh-claude-sonnet5
  model:
    provider: cursor
    family: claude
    version: sonnet-5
derivation_provenance:
  sealed_derivation: true
  anchor_seal_mechanism: fresh-subagent
  fresh_context_route: fresh-subagent
  feature_list_frozen_at: '2026-08-05T12:20:00+08:00'
  notes: 'This run is a Skill 1 "reverse inventory" pass, not a normal Skill 1 generation run. The agent
    NEVER opened SMC_CLOCK_GATING_PIN.yaml, any SMC_CLOCK_GATING_*.md artifact, any grade/peer-audit report,
    or any testlist. It received only the pinned SPEC paths listed below, the milestone label (P1), and
    the boundary text verbatim from the dispatching prompt, and derived every feature/scenario/finding
    from those SPEC sources alone. pin_revision is null by design: the pin was never read, so this artifact
    cites no pin authority and must not be treated as pin-confirmed. Consumer (Skill 3) is responsible
    for comparing this file''s feature/scenario key set against the sealed feature_list it already holds.'
reverse_inventory: true
pin_consulted: false
boundary_verbatim: 'IN: SMC clock-gating and clock-domain power-management behaviors named by the pinned
  hw/sys/smc/doc/ sources — multi-domain clocks (clk_smc/clk_ref/clk_periph/clk_telemetry), module/per-IP
  clock-gate enable and hysteresis/activity-detection controls, DMA and zeroer clock-gating paths (including
  test-mode/reset overrides), and the producer->CSR/control->gated-clock/consumer effects those docs state.
  This pin closes P0-P2 scenarios (milestone P2); P3 corner/stress remains OUT-OF-MILESTONE unless later
  re-pinned. OUT: DV/VPLAN/testplan/testlist docs under hw/sys/smc/dv/; generated register adoc under
  regs/gen/; RTL-as-spec; PLL frequency synthesis / DVFS / CGM-AWM programming beyond what clk_rst names
  as clock-gating control; deep reset-isolation power-island behaviors that clk_rst places outside clock
  gating; and IP-internal behaviors never restated at the SMC clock/reset boundary.'
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
features:
- key: CG-CTRL-PARAMS
  title: SMC-wide clock-gating control parameter architecture
  intent: clk_rst.adoc's "Clock and Reset-Based Power Management Integration" section names a generic,
    cross-module clock-gating control scheme (programmable hysteresis, per-module activity detection,
    a configurable enable threshold, and individual per-block module gating enable/disable) that concrete
    gated blocks such as DMA and the Zeroer are expected to instantiate. This feature captures the architecture-level
    commitment itself, distinct from any single block's concrete implementation.
  spec_refs:
  - hw/sys/smc/doc/clk_rst.adoc "Clock Gating Control Parameters" table (Clock and Reset-Based Power Management
    Integration)
  triad:
    producer: 'per-module clock-gating control parameter set named generically by clk_rst.adoc: a 6-bit
      programmable hysteresis value, a per-module activity-detection signal, a configurable enable-threshold
      delay, and an individual module-gating enable/disable'
    transport: per-module clock-gating cell (a prim_clk_gater-class primitive instantiated once per gated
      functional block; concrete instances are named separately in DMA-CG and ZEROER-*-CG)
    consumer: the individual functional block's gated clock domain (generic per this table)
  scenarios:
  - key: CG-CTRL-PARAMS.S1
    requires: LIVE
    intent: '[BOUNDED-LIVENESS] Programming the 6-bit hysteresis value changes how long a per-module clock-gate
      cell holds its clock enabled after activity de-asserts, preventing enable/disable oscillation ("chatter")
      under intermittent load.'
    spec_refs:
    - hw/sys/smc/doc/clk_rst.adoc "Hysteresis Control" row
    coverage:
      method: RANDOMIZED
      required_cells:
      - hysteresis-min
      - hysteresis-max
      - hysteresis-mid
      - activity-toggle-within-hysteresis-window
      random_knobs:
      - hysteresis_value
      - activity_toggle_period
      coverage_artifact: functional coverage bin on (hysteresis_value, gate_state_transition)
  - key: CG-CTRL-PARAMS.S2
    requires: LIVE
    intent: 'Per-module activity detection means one functional block''s own activity signal, independent
      of any other block''s activity, determines that block''s own clock-gating decision: gating (or not
      gating) one module never forces the gating decision of an unrelated module.'
    spec_refs:
    - hw/sys/smc/doc/clk_rst.adoc "Activity Detection" row
    coverage:
      method: DIRECTED
      required_cells:
      - module-a-active-module-b-idle
      - module-a-idle-module-b-active
      random_knobs: []
      coverage_artifact: cross-module gating-independence checklist
  - key: CG-CTRL-PARAMS.S3
    requires: LIVE
    intent: 'A configurable enable-threshold delay balances gating responsiveness against power savings:
      changing the threshold changes how quickly a module''s gate re-engages after activity resumes and/or
      disengages after activity stops.'
    spec_refs:
    - hw/sys/smc/doc/clk_rst.adoc "Enable Threshold" row
    coverage:
      method: RANDOMIZED
      required_cells:
      - threshold-min
      - threshold-max
      random_knobs:
      - enable_threshold_value
      coverage_artifact: functional coverage bin on (enable_threshold_value, response_latency)
  - key: CG-CTRL-PARAMS.S4
    requires: LIVE
    intent: A per-module gate-enable control independently switches clock gating on or off for exactly
      one functional block, without changing any sibling functional block's gating state.
    spec_refs:
    - hw/sys/smc/doc/clk_rst.adoc "Module Gating" row
    coverage:
      method: DIRECTED
      required_cells:
      - module-gating-enabled
      - module-gating-disabled
      random_knobs: []
      coverage_artifact: per-module gate-enable truth table
  record_sha256: bec5485b2f3a462d327cfa41e89e36d625f45e98c6589ee1fda41c7ddfd29d0d
- key: DMA-CG
  title: DMA controller module-level clock gating (activity + hysteresis + enable)
  intent: The DMA subsystem gates the single clock shared by its frontend, request manager, and backend
    as one unit through a single prim_clk_gater_hysteresis instance, driven by an activity OR-condition
    (frontend wakeup OR backend busy), a gating-enable control input, and a programmable hysteresis width
    (CG_HYSTERESIS_W).
  spec_refs:
  - hw/sys/smc/doc/dma.adoc "Clock Gating Configuration" table
  - hw/sys/smc/doc/dma.adoc "DMA Configuration Parameters" table (CG_HYSTERESIS_W row)
  triad:
    producer: cg_enable_i control input, frontend-wakeup and backend-busy activity signals, and the CG_HYSTERESIS_W-configured
      hysteresis counter
    transport: single prim_clk_gater_hysteresis instance shared by frontend, request manager, and backend
    consumer: DMA frontend (idma_frontend_wrapper), request manager (idma_request_manager_wrapper), and
      backend (idma_backend_wrapper) gated clock
  scenarios:
  - key: DMA-CG.S1
    requires: LIVE
    intent: With cg_enable_i asserted, either the frontend-wakeup signal or the backend-busy signal being
      asserted holds the shared DMA clock enabled.
    spec_refs:
    - 'hw/sys/smc/doc/dma.adoc "Activity Detection" row: clock enabled when frontend wakeup or backend
      busy'
    coverage:
      method: DIRECTED
      required_cells:
      - frontend-wakeup-only
      - backend-busy-only
      - both-asserted
      random_knobs: []
      coverage_artifact: activity-OR truth table
  - key: DMA-CG.S2
    requires: LIVE
    intent: '[BOUNDED-LIVENESS] With cg_enable_i asserted and both frontend-wakeup and backend-busy de-asserted
      for longer than the programmed CG_HYSTERESIS_W delay, the shared DMA clock gates off.'
    spec_refs:
    - hw/sys/smc/doc/dma.adoc "Hysteresis Width" row + CG_HYSTERESIS_W parameter
    coverage:
      method: RANDOMIZED
      required_cells:
      - gate-off-at-min-hysteresis
      - gate-off-at-max-hysteresis
      random_knobs:
      - hysteresis_value
      - idle_duration
      coverage_artifact: gate-state vs. elapsed-idle-time coverage bin
  - key: DMA-CG.S3
    requires: LIVE
    intent: With cg_enable_i de-asserted, the shared DMA clock remains continuously enabled regardless
      of frontend/backend activity state (module-gating bypass).
    spec_refs:
    - 'hw/sys/smc/doc/dma.adoc "Gating Control" row: cg_enable_i input enables/disables clock gating'
    coverage:
      method: DIRECTED
      required_cells:
      - cg-disabled-no-activity
      - cg-disabled-with-activity
      random_knobs: []
      coverage_artifact: bypass truth table
  - key: DMA-CG.S4
    requires: LIVE
    intent: '[BOUNDED-LIVENESS] If activity re-asserts (frontend wakeup or backend busy) before the hysteresis
      window expires, the shared DMA clock never gates off: the hysteresis timer restarts rather than
      allowing a glitch.'
    spec_refs:
    - hw/sys/smc/doc/dma.adoc "Hysteresis Width" row (anti-oscillation intent)
    coverage:
      method: RANDOMIZED
      required_cells:
      - reassert-just-before-expiry
      - reassert-well-before-expiry
      random_knobs:
      - reassert_gap
      coverage_artifact: no-glitch assertion coverage
  record_sha256: ef1120d3749f6c69384f71ab3ff4dfe999463142199a81370f6d01520c5df74c
- key: DMA-CG-TESTMODE
  title: DMA clock-gating test-mode bypass
  intent: The top-level SMC test-enable input overrides the DMA's clock-gating cell during manufacturing
    test, forcing the shared DMA clock free-running independent of cg_enable_i or activity state.
  spec_refs:
  - 'hw/sys/smc/doc/dma.adoc "Test Mode" row: Clock gating bypassed during test mode'
  - 'hw/sys/smc/doc/port_table.adoc test_en_i row: Drives clock-gater test ports'
  triad:
    producer: test_en_i (top-level SMC DFT test-enable port)
    transport: DMA's prim_clk_gater_hysteresis test-bypass path
    consumer: DMA frontend/request-manager/backend gated clock
  scenarios:
  - key: DMA-CG-TESTMODE.S1
    requires: LIVE
    intent: With test_en_i asserted, the shared DMA clock is free-running (bypasses gating) regardless
      of cg_enable_i and frontend/backend activity state.
    spec_refs:
    - hw/sys/smc/doc/dma.adoc "Test Mode" row
    - hw/sys/smc/doc/port_table.adoc test_en_i row
    coverage:
      method: DIRECTED
      required_cells:
      - test-mode-cg-would-have-gated
      - test-mode-cg-would-have-been-enabled-anyway
      random_knobs: []
      coverage_artifact: test-bypass truth table
  record_sha256: 7fbd18b8d93f59ec7a124cc2ff6959243e83d65bb6ccc426e8a5603499a5703e
- key: ZEROER-AXI-CG
  title: Memory Zeroer AXI-clock domain gating
  intent: 'The zeroer''s AXI master clock is enabled whenever gating is disabled by control, the zeroer
    is actively busy, or the domain is in reset; otherwise (idle, gating enabled, not in reset) the AXI
    clock gates off. Formula per spec: axi_clk_enable = disable_cg | zeroer_busy_o | ~rst_ni.'
  spec_refs:
  - hw/sys/smc/doc/zeroer.adoc "Clock Gating Control" table, AXI Clock row
  triad:
    producer: disable_cg control input, zeroer_busy_o activity status, rst_ni reset
    transport: prim_clkgater instance gating axi_clk
    consumer: zeroer AXI master datapath (axi_clk domain)
  scenarios:
  - key: ZEROER-AXI-CG.S1
    requires: LIVE
    intent: disable_cg=1 -> axi_clk enabled unconditionally regardless of busy/reset state.
    spec_refs:
    - hw/sys/smc/doc/zeroer.adoc axi_clk_enable formula
    coverage:
      method: DIRECTED
      required_cells:
      - disable_cg-1-idle
      - disable_cg-1-busy
      random_knobs: []
      coverage_artifact: bypass truth table
  - key: ZEROER-AXI-CG.S2
    requires: LIVE
    intent: disable_cg=0, zeroer_busy_o=1 -> axi_clk enabled (active zeroing in progress).
    spec_refs:
    - hw/sys/smc/doc/zeroer.adoc axi_clk_enable formula
    coverage:
      method: DIRECTED
      required_cells:
      - busy-asserted-not-in-reset
      random_knobs: []
      coverage_artifact: activity truth table
  - key: ZEROER-AXI-CG.S3
    requires: LIVE
    intent: disable_cg=0, zeroer_busy_o=0, rst_ni=1 -> axi_clk gates off (idle power savings).
    spec_refs:
    - hw/sys/smc/doc/zeroer.adoc axi_clk_enable formula
    coverage:
      method: DIRECTED
      required_cells:
      - idle-not-in-reset
      random_knobs: []
      coverage_artifact: idle-gate truth table
  - key: ZEROER-AXI-CG.S4
    requires: LIVE
    intent: rst_ni=0 -> axi_clk enabled per formula regardless of disable_cg/busy (glitch-free operation
      through reset).
    spec_refs:
    - hw/sys/smc/doc/zeroer.adoc axi_clk_enable formula
    coverage:
      method: DIRECTED
      required_cells:
      - reset-asserted-idle
      - reset-asserted-busy
      random_knobs: []
      coverage_artifact: reset-override truth table
  record_sha256: 3c451bf41361d6f9f6233bf6adf495a40f8d49bb439cf6ed598ade47e6907022
- key: ZEROER-REG-CG
  title: Memory Zeroer register-clock domain gating (independent of AXI activity)
  intent: 'The zeroer''s register-interface clock is enabled whenever gating is disabled by control, register-interface
    activity is present, or the domain is in reset; this decision is independent of AXI-side busy state.
    Formula per spec: reg_clk_enable = disable_cg | register_activity | ~rst_ni.'
  spec_refs:
  - hw/sys/smc/doc/zeroer.adoc "Clock Gating Control" table, Register Clock row
  triad:
    producer: disable_cg control input, register_activity status, rst_ni reset
    transport: prim_clkgater instance gating reg_clk
    consumer: zeroer register-interface datapath (reg_clk domain)
  scenarios:
  - key: ZEROER-REG-CG.S1
    requires: LIVE
    intent: disable_cg=1 -> reg_clk enabled unconditionally.
    spec_refs:
    - hw/sys/smc/doc/zeroer.adoc reg_clk_enable formula
    coverage:
      method: DIRECTED
      required_cells:
      - disable_cg-1-no-reg-activity
      - disable_cg-1-reg-activity
      random_knobs: []
      coverage_artifact: bypass truth table
  - key: ZEROER-REG-CG.S2
    requires: LIVE
    intent: disable_cg=0, register_activity=1 -> reg_clk enabled.
    spec_refs:
    - hw/sys/smc/doc/zeroer.adoc reg_clk_enable formula
    coverage:
      method: DIRECTED
      required_cells:
      - reg-activity-asserted-not-in-reset
      random_knobs: []
      coverage_artifact: activity truth table
  - key: ZEROER-REG-CG.S3
    requires: LIVE
    intent: disable_cg=0, register_activity=0, rst_ni=1 -> reg_clk gates off.
    spec_refs:
    - hw/sys/smc/doc/zeroer.adoc reg_clk_enable formula
    coverage:
      method: DIRECTED
      required_cells:
      - idle-not-in-reset
      random_knobs: []
      coverage_artifact: idle-gate truth table
  - key: ZEROER-REG-CG.S4
    requires: LIVE
    intent: rst_ni=0 -> reg_clk enabled per formula regardless of disable_cg/register_activity.
    spec_refs:
    - hw/sys/smc/doc/zeroer.adoc reg_clk_enable formula
    coverage:
      method: DIRECTED
      required_cells:
      - reset-asserted-idle
      - reset-asserted-reg-active
      random_knobs: []
      coverage_artifact: reset-override truth table
  record_sha256: 740ee3d60ff8f3ece72439778ad6e8ff4c5a67ee57c8f837f9bb046cd9bf1d5f
- key: ZEROER-CG-TESTMODE
  title: Zeroer clock-gating test-mode override
  intent: Manufacturing test-enable overrides the zeroer's clock-gating cell(s), forcing the gated clock(s)
    free-running for DFT, per zeroer.adoc's "Test Support" row.
  spec_refs:
  - hw/sys/smc/doc/zeroer.adoc "Clock Gating Control" table, Test Support row
  - hw/sys/smc/doc/port_table.adoc test_en_i row
  triad:
    producer: test_en_i (top-level SMC DFT test-enable port)
    transport: zeroer prim_clkgater test-bypass path(s)
    consumer: zeroer axi_clk and/or reg_clk gated clock domain(s) — exact scope (unified vs. per-domain
      override) is ambiguous per SF-004
  scenarios:
  - key: ZEROER-CG-TESTMODE.S1
    requires: LIVE
    intent: With test_en_i asserted, the zeroer's gated clock(s) are free-running (bypass gating) regardless
      of disable_cg/activity/reset state.
    spec_refs:
    - hw/sys/smc/doc/zeroer.adoc "Test Support" row
    - hw/sys/smc/doc/port_table.adoc test_en_i row
    coverage:
      method: DIRECTED
      required_cells:
      - test-mode-would-have-gated-axi
      - test-mode-would-have-gated-reg
      random_knobs: []
      coverage_artifact: test-bypass truth table
  record_sha256: 4c5d0b494d52884ce43ff338ad0467b49484fce0cd71c5f095f9bb4d49c47f50
interactions:
- key: INT-ZEROER-CG-INDEP
  features:
  - ZEROER-AXI-CG
  - ZEROER-REG-CG
  intent: 'zeroer.adoc explicitly states the register clock is "independent of AXI activity" — this interaction
    proves the two gating decisions are decoupled: AXI-idle + register-active gates only the AXI clock
    (reg_clk stays enabled), and register-idle + AXI-active gates only reg_clk (axi_clk stays enabled).'
  spec_refs:
  - hw/sys/smc/doc/zeroer.adoc "Clock Domains" table + "Clock Gating Control" table
  requires: LIVE
  coverage:
    method: DIRECTED
    required_cells:
    - axi-active-reg-idle-decoupled
    - reg-active-axi-idle-decoupled
    random_knobs: []
    coverage_artifact: cross-domain independence truth table
  record_sha256: eb607339bb8f72bd92c368b7205e24f65aac73083841cdb902e3666a3808d3df
findings:
- id: SF-001
  category: SF-CONFLICT
  severity: Medium
  spec_refs:
  - 'hw/sys/smc/doc/clk_rst.adoc "Module Gating" row: Individual enable/disable, Allows selective power
    optimization per functional block'
  - 'hw/sys/smc/doc/fabric.adoc (entire file: no clock-gating control named for the fabric crossbar or
    filters)'
  - 'hw/sys/smc/doc/periphs.adoc (entire file: no clock-gating control named for any listed peripheral)'
  observed: clk_rst.adoc's generic "Clock Gating Control Parameters" table claims per-module individual
    gate enable/disable is available architecture-wide ("per functional block"), but among the pinned
    SPEC sources only DMA (dma.adoc) and the Zeroer (zeroer.adoc) name a concrete gate-enable signal.
    The fabric (crossbar, filters, CPU cluster local fabric) and every peripheral in periphs.adoc (Mailbox,
    System Timer OCTS, eFuse, UART 16550, Log Engine, I2C, AVSBus, GPIO, Telemetry Receiver) are named
    as consumers of clk_smc/clk_periph but never restated with a clock-gating control of their own.
  question: Does every functional block architecturally imply clock gating (per the generic table), with
    the omission in fabric.adoc/periphs.adoc simply meaning "not yet documented at this boundary", or
    is DMA/Zeroer clock gating a deliberately scoped exception rather than the general case? If the latter,
    the "per functional block" wording in clk_rst.adoc over-states the actual SMC clock-gating footprint.
  affects:
    features:
    - CG-CTRL-PARAMS
    scenarios:
    - CG-CTRL-PARAMS.S2
    - CG-CTRL-PARAMS.S4
    anchors: []
  status: open
  resolution: null
- id: SF-002
  category: SF-AMBIGUOUS
  severity: Low
  spec_refs:
  - hw/sys/smc/doc/clk_rst.adoc "Hysteresis Control" and "Enable Threshold" rows
  - hw/sys/smc/doc/dma.adoc "DMA Configuration Parameters" table (CG_HYSTERESIS_W row only)
  observed: clk_rst.adoc's table lists "Hysteresis Control" (6-bit programmable, prevents oscillation)
    and "Enable Threshold" (configurable delay, balances responsiveness vs. power) as two distinct clock-gating
    parameters. dma.adoc, the only pinned source with a concrete register/parameter name for this mechanism,
    exposes only a single hysteresis-width parameter (CG_HYSTERESIS_W) and never names a separate "enable
    threshold" field.
  question: Is "Enable Threshold" the same physical knob as "Hysteresis Control" restated with a different
    name, or a genuinely separate control with its own field that simply has no concrete instance in the
    pinned dma.adoc/zeroer.adoc text?
  affects:
    features:
    - CG-CTRL-PARAMS
    scenarios:
    - CG-CTRL-PARAMS.S1
    - CG-CTRL-PARAMS.S3
    anchors: []
  status: open
  resolution: null
- id: SF-003
  category: SF-MISSING
  severity: High
  spec_refs:
  - hw/sys/smc/doc/clk_rst.adoc "Clock Architecture" section (Reference / Peripheral / Telemetry Clock
    Domain subsections)
  observed: The boundary text names clk_ref, clk_periph, and clk_telemetry as in-scope multi-domain clocks
    for clock-gating / clock-domain power-management behaviors. None of the pinned SPEC sources (clk_rst.adoc,
    periphs.adoc, port_table.adoc) state a clock-gating enable, hysteresis, or activity-detection control
    for the reference clock domain, the peripheral clock domain (or its listed peripherals AVSBus/I2C/
    UART/I3C), or the telemetry clock domain. Only the SMC clock domain's DMA and Zeroer modules have
    documented clock-gating behavior in the pinned sources.
  question: Do clk_ref, clk_periph, and clk_telemetry have any clock-gating mechanism at all within the
    pinned-SPEC boundary, or is clock gating in this milestone scoped exclusively to clk_smc-domain blocks
    (DMA, Zeroer)? If the former, which document states it (none of the 9 pinned sources do)?
  affects:
    features: []
    scenarios: []
    anchors: []
  status: open
  resolution: null
- id: SF-004
  category: SF-AMBIGUOUS
  severity: Low
  spec_refs:
  - hw/sys/smc/doc/zeroer.adoc "Clock Gating Control" table, Test Support row
  observed: zeroer.adoc's "Clock Gating" table lists a single "Test Support" row ("Test enable override
    for manufacturing test") without stating whether the override is one top-level signal that bypasses
    both the AXI-clock and register-clock gating formulas simultaneously, or two independent per-domain
    test overrides.
  question: Is the zeroer's test-mode clock-gating bypass a single unified override for both axi_clk and
    reg_clk, or two independent overrides that could be exercised/observed separately?
  affects:
    features:
    - ZEROER-CG-TESTMODE
    scenarios:
    - ZEROER-CG-TESTMODE.S1
    anchors: []
  status: open
  resolution: null
- id: SF-005
  category: SF-MISSING
  severity: Medium
  spec_refs:
  - hw/sys/smc/doc/dma.adoc "Clock Gating Configuration" table, Gating Control row (cg_enable_i)
  - hw/sys/smc/doc/zeroer.adoc "Clock Gating Control" table (disable_cg)
  - hw/sys/smc/doc/port_table.adoc (full SMC port list)
  observed: dma.adoc names cg_enable_i and zeroer.adoc names disable_cg as the control-plane producers
    of clock-gating enable/disable, but neither signal appears in the pinned port_table.adoc's top-level
    SMC port list. Register-level RDL documentation that might expose either as a CSR field is explicitly
    out of scope for this boundary.
  question: Is cg_enable_i / disable_cg a software-programmable CSR bit, a design-time parameter/strap,
    or an internal signal not exposed as either a top-level port or a documented register within the pinned-SPEC
    boundary? The producer leg of this feature's triad cannot be pinned more precisely than "control input"
    from the SPEC sources alone.
  affects:
    features:
    - DMA-CG
    - ZEROER-AXI-CG
    - ZEROER-REG-CG
    scenarios: []
    anchors: []
  status: open
  resolution: null
out_of_boundary_observations: 'The following SPEC-stated behaviors were considered and deliberately excluded
  as OUT-OF-SCOPE per the boundary text, not omitted by oversight: (1) clk_rst.adoc''s "Advanced Reset
  Features" (Reference Clock Forcing, Configuration Hold, SRAM Preservation, Debug State Preservation)
  and the reset architecture''s power-island / subsystem-isolation capability, both of which clk_rst.adoc
  itself frames as "power management beyond clock gating"; (2) Function Level Reset (FLR) isolation control,
  programmable reset timing, and memory-test bypass (skip_mem_repair_o), which are reset-isolation/power-island
  behaviors, not clock gating; (3) dma.adoc''s BYPASS_DMA_CTRL_FLOPS / BYPASS_DMA_MST_FLOPS (register-cut
  timing bypass) and "Configuration Lock" (anti-modification-during-transfer), neither of which is a clock-gating
  mechanism; (4) any PLL/clock-generation, PVT, or frequency-scaling content (out per the DVFS/CGM-AWM
  exclusion); (5) all register-level field encodings, which live under regs/gen/ and are out of scope
  for this boundary.'
---

= SMC_CLOCK_GATING — Reverse Feature Inventory (candidate, anchor-blind)

*This is a Skill 1 "reverse inventory" artifact, not a normal feature_list generation
run.* It was produced by a fresh subagent that never read any `SMC_CLOCK_GATING_*.md`
artifact, the pin file, any grade or peer-audit report, or any testlist. Its only inputs
were the 9 pinned SPEC sources under `hw/sys/smc/doc/` and the boundary text supplied
verbatim in the dispatching prompt. Every feature, scenario, and finding below is
derived from those sources alone, forward-from-SPEC and milestone-blind (nothing here
is trimmed to a milestone or to what any existing test happens to touch).

Everything in this file is `status: candidate`. Nothing here is approved, allocated, or
closed. This file makes no claim about what any existing test proves — that comparison
is Skill 3's job, using this file as the independent reference inventory for its reverse
inventory diff.

== How to read this file

* `features[]` / `interactions[]` — the complete in-scope clock-gating / clock-domain
  power-management surface as read from the 9 pinned SPEC sources, scoped by the
  boundary text alone (never by milestone). Six features and one interaction were
  derived; see `findings[]` for the SPEC gaps and ambiguities surfaced along the way.
* `findings[]` — five `SF-*` spec-audit findings (`SF-001`..`SF-005`), each naming the
  SPEC location(s), what is missing/ambiguous/conflicting, and a question for the SPEC
  owner. None are invented fixes; each is a question.
* `out_of_boundary_observations` — SPEC-stated behaviors that were read, considered, and
  deliberately excluded per the boundary text, recorded here so a reviewer can see this
  was a decision and not an omission.

== Coverage summary

[cols="3,1,1", options="header"]
|===
|Feature |Scenarios |Notes
|CG-CTRL-PARAMS |4 |Architecture-level clock-gating control parameters (clk_rst.adoc)
|DMA-CG |4 |DMA frontend/request-manager/backend shared clock gating
|DMA-CG-TESTMODE |1 |DMA test-mode bypass (test_en_i)
|ZEROER-AXI-CG |4 |Zeroer AXI-clock domain gating
|ZEROER-REG-CG |4 |Zeroer register-clock domain gating
|ZEROER-CG-TESTMODE |1 |Zeroer test-mode bypass (test_en_i)
|===

One interaction (`INT-ZEROER-CG-INDEP`) proves the AXI-clock and register-clock gating
decisions in the Zeroer are decoupled, per zeroer.adoc's explicit "independent of AXI
activity" statement.

Total: 6 features, 18 scenarios, 1 interaction, 5 SF-* findings.

== Findings requiring an owner decision

`SF-003` (High) is the most material: three of the four boundary-named clock domains
(`clk_ref`, `clk_periph`, `clk_telemetry`) have **no** documented clock-gating behavior
anywhere in the 9 pinned sources. If that is intentional (clock gating is `clk_smc`-only
for this milestone), the boundary text's domain list is broader than what the SPEC
actually supports; if it is an oversight, the SPEC owner needs to add the missing
sections before any test can be written against them. `SF-001`/`SF-005` (Medium) affect
how confidently `CG-CTRL-PARAMS` and the two producer legs (`cg_enable_i`/`disable_cg`)
can be pinned to a concrete register/port. `SF-002`/`SF-004` (Low) are narrower
terminology/scope ambiguities.

== Not a testcase plan

This file allocates nothing. It does not know whether any anchor exists, and it must
not be read as a coverage claim, a closure claim, or a substitute for the sealed
feature_list that Skill 1 already produced for this IP. Its only job is to let Skill 3
diff "what the SPEC independently implies" against "what the sealed plan already
covers" without that independent read ever having seen the sealed plan's shape.
