---
schema: dv-quality/v1
artifact: feature-list
artifact_revision: 1
content_sha256: 98edfcafc4474d142fa0a6ad9ef0f619826ceeedaf5eea953d0b7399bd56df9b
ip: SMC_CLOCK_GATING_P2
milestone: P2
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
  run_id: dv_vplan_gen-SMC_CLOCK_GATING_P2-step1-2026-08-05T15:09:00+08:00
  model:
    provider: cursor
    family: claude
    version: sonnet-5
derivation_provenance:
  sealed_derivation: true
  anchor_seal_mechanism: fresh-subagent
  fresh_context_route: fresh-subagent
  feature_list_frozen_at: '2026-08-05T15:09:00+08:00'
approved_by: minshaoho
approved_at: '2026-08-05T15:52:00+08:00'
features:
- key: SMC-CG-DMA-HYST
  title: DMA clock-gating hysteresis breadth and activity-reassertion race
  intent: A single prim_clk_gater_hysteresis instance gates the clock feeding the DMA frontend, request
    manager, and backend based on a combined activity signal (frontend wakeup or backend busy), holding
    the clock enabled for a programmable 6-bit hysteresis window after activity de-asserts; the gate must
    resolve correctly both across the full hysteresis range and when activity re-asserts mid-countdown.
  triad:
    producer: combined DMA activity signal (frontend wakeup OR backend busy), dma.adoc §Performance Optimization
      and Power Management
    transport: the single prim_clk_gater_hysteresis instance and its 6-bit (0-63 cycle) hysteresis counter,
      dma.adoc §Configuration Parameters (CG_HYSTERESIS_W) and §Performance Optimization and Power Management
      (Clock Gating Configuration)
    consumer: gated clock reaching idma_frontend_wrapper, idma_request_manager_wrapper, and idma_backend_wrapper,
      dma.adoc §Performance Optimization and Power Management (Clock Gating Configuration)
  spec_refs:
  - hw/sys/smc/doc/dma.adoc §Performance Optimization and Power Management (Clock Gating Configuration
    table) @ e2aae39953bb8001c7c20e3afd3956e68c22440c
  - hw/sys/smc/doc/clk_rst.adoc §Clock and Reset-Based Power Management Integration (Clock Gating Control
    Parameters table) @ 2f40548ea787240680a1c45ab75b8729e9620778
  record_sha256: 8397ed290ae0c00ab96e181e2f8a59db7fc48ec2e523eb2d5f6a654654447c5b
  scenarios:
  - key: SMC-CG-DMA-HYST.S1
    intent: Sweep the hysteresis countdown across its full declared range (0 to 63 cycles of inactivity
      between the last activity pulse and clock gating) and confirm the gate deasserts neither earlier
      nor later than the declared window at each swept point.
    requires: LIVE
    spec_refs:
    - 'hw/sys/smc/doc/dma.adoc §Configuration Parameters (CG_HYSTERESIS_W: "6-bit = 0-63 cycle delay")
      @ e2aae39953bb8001c7c20e3afd3956e68c22440c'
    - 'hw/sys/smc/doc/dma.adoc §Performance Optimization and Power Management (Clock Gating Configuration:
      "Hysteresis Width | 6-bit configurable hysteresis (CG_HYSTERESIS_W=6)") @ e2aae39953bb8001c7c20e3afd3956e68c22440c'
    coverage:
      method: RANDOMIZED
      required_cells:
      - hyst-gap=0
      - hyst-gap=1
      - hyst-gap=32-mid
      - hyst-gap=63-max
      - hyst-gap=64-just-over-max
      random_knobs:
      - inter-activity gap length in clk_smc_i cycles, swept 0 through 64
      coverage_artifact: functional_coverage_report
  - key: SMC-CG-DMA-HYST.S2
    intent: 'Contested state: activity (frontend wakeup or backend busy) re-asserts at an arbitrary point
      during an in-progress hysteresis countdown; the gate must not close while the countdown is interrupted
      and must resume a correct countdown once activity clears again, with bounded completion (no missed
      reactivation, no premature gate).'
    requires: LIVE
    spec_refs:
    - 'hw/sys/smc/doc/dma.adoc §Performance Optimization and Power Management (Clock Gating Configuration:
      "Activity Detection | Clock enabled when frontend wakeup or backend busy") @ e2aae39953bb8001c7c20e3afd3956e68c22440c'
    - hw/sys/smc/doc/clk_rst.adoc §Clock and Reset-Based Power Management Integration ("Hysteresis Control
      | 6-bit programmable | Prevents clock gating oscillation under varying load") @ 2f40548ea787240680a1c45ab75b8729e9620778
    coverage:
      method: DIRECTED
      required_cells:
      - activity-reassert-early-in-countdown
      - activity-reassert-at-last-cycle-of-countdown
      - activity-clear-immediately-after-reassert
      - back-to-back-reassert-reassert
      random_knobs: []
      coverage_artifact: null
- key: SMC-CG-ZEROER-AXICLK
  title: Zeroer axi_clk gating vs. back-to-back operation race
  intent: The zeroer's AXI master clock (axi_clk) is gated by a prim_clkgater whose enable is disable_cg
    OR zeroer_busy_o OR ~rst_ni; a new configuration/ trigger arriving back-to-back with the prior operation's
    busy-to-idle transition must be observed and executed correctly without the gate glitching the clock
    mid-transfer or dropping the new request.
  triad:
    producer: zeroer_busy_o, asserted from trigger through the state machine's ST_ISSUE_ADDR/ST_ISSUE_DATA
      phases until all write responses are received, zeroer.adoc §State Machine and §Outstanding Transaction
      Management
    transport: prim_clkgater gating the axi_clk domain per axi_clk_enable = disable_cg | zeroer_busy_o
      | ~rst_ni, zeroer.adoc §Clock Gating
    consumer: the zeroer AXI4 master interface issuing write addresses and streaming zero data, zeroer.adoc
      §AXI Master Interface
  spec_refs:
  - hw/sys/smc/doc/zeroer.adoc §Clock Gating (Clock Gating Control table) @ 2f40548ea787240680a1c45ab75b8729e9620778
  - hw/sys/smc/doc/zeroer.adoc §State Machine @ 2f40548ea787240680a1c45ab75b8729e9620778
  record_sha256: d18b4172cfd3d47c00a8ee8aaf29111c9e0fc95dd572ddcda2ba28c3ecdf1c97
  scenarios:
  - key: SMC-CG-ZEROER-AXICLK.S1
    intent: 'Contested state: a new DEST_ADDR/SIZE/CTRL_STATUS trigger write for a follow-on zero operation
      is issued back-to-back with the prior operation''s busy-to-idle transition (zeroer_busy_o falling
      edge); the axi_clk gate must not spuriously close between the two operations, and the new operation
      must start and complete correctly within a bounded time.'
    requires: LIVE
    spec_refs:
    - hw/sys/smc/doc/zeroer.adoc §Clock Gating ("AXI Clock | axi_clk_enable = disable_cg | zeroer_busy_o
      | ~rst_ni") @ 2f40548ea787240680a1c45ab75b8729e9620778
    - 'hw/sys/smc/doc/zeroer.adoc §Operation Flow ("Completion: State machine returns to idle with status
      update") @ 2f40548ea787240680a1c45ab75b8729e9620778'
    coverage:
      method: DIRECTED
      required_cells:
      - new-trigger-1-cycle-before-busy-deassert
      - new-trigger-same-cycle-as-busy-deassert
      - new-trigger-1-cycle-after-busy-deassert
      random_knobs: []
      coverage_artifact: null
- key: SMC-CG-ZEROER-REGCLK
  title: Zeroer reg_clk gating vs. pending register access race
  intent: The zeroer's register-interface clock (reg_clk) is gated by a prim_clkgater whose enable is
    disable_cg OR register_activity OR ~rst_ni, independent of AXI activity; a register access arriving
    while reg_clk is currently gated (no recent register_activity) must be able to ungate the clock and
    complete within a bounded time.
  triad:
    producer: register_activity, asserted by accesses to the zeroer's register block, zeroer.adoc §Clock
      Gating
    transport: prim_clkgater gating the reg_clk domain per reg_clk_enable = disable_cg | register_activity
      | ~rst_ni, zeroer.adoc §Clock Gating
    consumer: the zeroer register interface (DEST_ADDR, SIZE, CTRL_STATUS, Interrupt Enable), zeroer.adoc
      §Operation Control
  spec_refs:
  - hw/sys/smc/doc/zeroer.adoc §Clock Gating (Clock Gating Control table) @ 2f40548ea787240680a1c45ab75b8729e9620778
  - hw/sys/smc/doc/zeroer.adoc §Operation Control @ 2f40548ea787240680a1c45ab75b8729e9620778
  record_sha256: d3c51980b2955271cc4ab3cf55599a9b096c17f6e1f89bd10e9b5139a0596abf
  scenarios:
  - key: SMC-CG-ZEROER-REGCLK.S1
    intent: 'Contested state: a register access (e.g. a status read or a new DEST_ADDR/SIZE/CTRL_STATUS
      write) arrives while reg_clk is gated because no register_activity has been observed; the pending
      access must ungate reg_clk and complete within a bounded time rather than being dropped, corrupted,
      or hung.'
    requires: LIVE
    spec_refs:
    - hw/sys/smc/doc/zeroer.adoc §Clock Gating ("Register Clock | reg_clk_enable = disable_cg | register_activity
      | ~rst_ni") @ 2f40548ea787240680a1c45ab75b8729e9620778
    - hw/sys/smc/doc/zeroer.adoc §Clock Domains ("Register Clock (reg_clk) | Separate clock for register
      interface, independent of AXI activity") @ 2f40548ea787240680a1c45ab75b8729e9620778
    coverage:
      method: DIRECTED
      required_cells:
      - access-immediately-after-reg_clk-gates
      - access-long-after-reg_clk-gates
      - back-to-back-accesses-across-gate-boundary
      random_knobs: []
      coverage_artifact: null
interactions: []
---

## Features

**Scope note.** Per the confirmed boundary, this inventory admits only the SMC
clock-gating breadth/error behaviors the pinned docs name that a prior
milestone deferred: the DMA hysteresis controller's full range and its
activity-reassertion race, and the Zeroer's two independent clock-gated
domains' contested back-to-back/pending-access races. Nominal clock-gating
formula cells (frontend/backend activity → gate enable, disable_cg pass-
through, DFT test-mode bypass) are explicitly OUT for P2 except where a race
below requires their joint observation, so they are not separately listed as
features here; PLL CGM/AWM programming and power-island isolation outside
clk_rst CG are OUT always for this milestone. The `axi_cg_snoop`
OutstandingTx-vs-fabric-capacity behavior named in the boundary is walked in
its own subsection below and could not be turned into a feature at all — see
`SF-001`.

### Area: DMA hysteresis clock gating

**SMC-CG-DMA-HYST — DMA clock-gating hysteresis breadth and activity-reassertion race:**
A single `prim_clk_gater_hysteresis` instance gates the clock feeding the DMA
frontend, request manager, and backend, driven by a combined activity signal
(frontend wakeup OR backend busy) and a 6-bit (0-63 cycle) hysteresis window.
[ATOMIC-FEATURE]
  - Spec: `hw/sys/smc/doc/dma.adoc` §Performance Optimization and Power
    Management (Clock Gating Configuration table); `hw/sys/smc/doc/clk_rst.adoc`
    §Clock and Reset-Based Power Management Integration (Clock Gating Control
    Parameters table) [SPEC-CITATION]
  - Triad: producer combined DMA activity (frontend wakeup OR backend busy) |
    transport the single `prim_clk_gater_hysteresis` 6-bit counter gating the
    frontend/request-manager/backend clock | consumer the gated clock reaching
    `idma_frontend_wrapper`, `idma_request_manager_wrapper`,
    `idma_backend_wrapper` [ATOMIC-FEATURE]
  - Required scenarios: [REQUIRED-SCENARIOS]
    - SMC-CG-DMA-HYST.S1 [REQUIRES: LIVE]: sweep the hysteresis countdown
      across its full declared 0-63 cycle range and confirm the gate transition
      lands exactly on the swept boundary, neither early nor late.
      SPEC: `dma.adoc` §Configuration Parameters (`CG_HYSTERESIS_W`: "6-bit =
      0-63 cycle delay"); §Performance Optimization and Power Management
      (Clock Gating Configuration: "Hysteresis Width | 6-bit configurable
      hysteresis (CG_HYSTERESIS_W=6)") [SPEC-CITATION]
      COVERAGE: {method: RANDOMIZED, required_cells: [hyst-gap=0, hyst-gap=1,
      hyst-gap=32-mid, hyst-gap=63-max, hyst-gap=64-just-over-max],
      random_knobs: [inter-activity gap length in clk_smc_i cycles, swept 0
      through 64], coverage_artifact: functional_coverage_report}
    - SMC-CG-DMA-HYST.S2 [REQUIRES: LIVE] [BOUNDED-LIVENESS]: activity
      re-asserts at an arbitrary point during an in-progress hysteresis
      countdown; the gate must not close while interrupted and must resume a
      correct countdown once activity clears again, with bounded
      completion-or-error (no missed reactivation, no premature gate).
      SPEC: `dma.adoc` §Performance Optimization and Power Management (Clock
      Gating Configuration: "Activity Detection | Clock enabled when frontend
      wakeup or backend busy"); `clk_rst.adoc` §Clock and Reset-Based Power
      Management Integration ("Hysteresis Control | 6-bit programmable |
      Prevents clock gating oscillation under varying load") [SPEC-CITATION]
      COVERAGE: {method: DIRECTED, required_cells:
      [activity-reassert-early-in-countdown,
      activity-reassert-at-last-cycle-of-countdown,
      activity-clear-immediately-after-reassert,
      back-to-back-reassert-reassert], random_knobs: [], coverage_artifact: null}

**Underspecified aspects of this area:** the exact mechanism by which the
"6-bit programmable" hysteresis value of `clk_rst.adoc` is actually set (a
runtime register vs. a synthesis-time RTL parameter as `dma.adoc`'s
`CG_HYSTERESIS_W` implies) is unclear — see `SF-002`. The exact observable
condition that constitutes "frontend wakeup" is not defined — see `SF-003`.

### Area: Zeroer axi_clk / reg_clk clock gating

**SMC-CG-ZEROER-AXICLK — Zeroer axi_clk gating vs. back-to-back operation race:**
The zeroer's AXI master clock is gated per
`axi_clk_enable = disable_cg | zeroer_busy_o | ~rst_ni`. [ATOMIC-FEATURE]
  - Spec: `hw/sys/smc/doc/zeroer.adoc` §Clock Gating (Clock Gating Control
    table); §State Machine [SPEC-CITATION]
  - Triad: producer `zeroer_busy_o` (asserted from trigger through
    `ST_ISSUE_ADDR`/`ST_ISSUE_DATA` until all write responses are received) |
    transport `prim_clkgater` gating the `axi_clk` domain | consumer the
    zeroer AXI4 master interface (write address/data phases) [ATOMIC-FEATURE]
  - Required scenarios: [REQUIRED-SCENARIOS]
    - SMC-CG-ZEROER-AXICLK.S1 [REQUIRES: LIVE] [BOUNDED-LIVENESS]: a new
      trigger for a follow-on zero operation is issued back-to-back with the
      prior operation's busy-to-idle transition; the `axi_clk` gate must not
      spuriously close between the two operations and the new operation must
      start and complete correctly within a bounded time.
      SPEC: `zeroer.adoc` §Clock Gating ("AXI Clock | axi_clk_enable =
      disable_cg | zeroer_busy_o | ~rst_ni"); §Operation Flow ("Completion:
      State machine returns to idle with status update") [SPEC-CITATION]
      COVERAGE: {method: DIRECTED, required_cells:
      [new-trigger-1-cycle-before-busy-deassert,
      new-trigger-same-cycle-as-busy-deassert,
      new-trigger-1-cycle-after-busy-deassert], random_knobs: [],
      coverage_artifact: null}

**Underspecified aspects of this scenario:** the spec does not state what
happens when a new trigger write arrives while `zeroer_busy_o` is still
asserted from a prior operation (rejected, queued, error, or corrupted state)
— see `SF-005`.

**SMC-CG-ZEROER-REGCLK — Zeroer reg_clk gating vs. pending register access race:**
The zeroer's register-interface clock is gated per
`reg_clk_enable = disable_cg | register_activity | ~rst_ni`, independent of
AXI activity. [ATOMIC-FEATURE]
  - Spec: `hw/sys/smc/doc/zeroer.adoc` §Clock Gating (Clock Gating Control
    table); §Operation Control [SPEC-CITATION]
  - Triad: producer `register_activity` (accesses to the zeroer's register
    block) | transport `prim_clkgater` gating the `reg_clk` domain | consumer
    the zeroer register interface (`DEST_ADDR`, `SIZE`, `CTRL_STATUS`,
    Interrupt Enable) [ATOMIC-FEATURE]
  - Required scenarios: [REQUIRED-SCENARIOS]
    - SMC-CG-ZEROER-REGCLK.S1 [REQUIRES: LIVE] [BOUNDED-LIVENESS]: a register
      access arrives while `reg_clk` is gated because no `register_activity`
      has been observed; the pending access must ungate `reg_clk` and complete
      within a bounded time rather than being dropped, corrupted, or hung.
      SPEC: `zeroer.adoc` §Clock Gating ("Register Clock | reg_clk_enable =
      disable_cg | register_activity | ~rst_ni"); §Clock Domains ("Register
      Clock (reg_clk) | Separate clock for register interface, independent of
      AXI activity") [SPEC-CITATION]
      COVERAGE: {method: DIRECTED, required_cells:
      [access-immediately-after-reg_clk-gates,
      access-long-after-reg_clk-gates,
      back-to-back-accesses-across-gate-boundary], random_knobs: [],
      coverage_artifact: null}

**Underspecified aspects of this scenario:** the spec does not define what
generates or sustains `register_activity` (which accesses count, pulse width,
hold time) — see `SF-004`.

### Area: axi_cg_snoop / fabric outstanding-transaction capacity

Walking `clk_rst.adoc`'s clock-gating architecture/snoop-mechanism text, and
`fabric.adoc`'s `MaxTrans`/`FABRIC_MAX_TRANS`/`MAX_INFLIGHT_IDS` capacity
parameters, for any named counter that tracks outstanding DMA/fabric
transactions specifically for clock-gating purposes: none of the nine pinned
documents name an `axi_cg_snoop` module, an "OutstandingTx" counter, or any
other snoop-style outstanding-transaction tracker used to hold a clock-gating
decision open until in-flight traffic drains. `clk_rst.adoc`'s clock-gating
section describes only the generic "Hysteresis Control" / "Activity
Detection" / "Enable Threshold" / "Module Gating" parameters (no snoop/counter
mechanism); `fabric.adoc` states exact outstanding-transaction *capacity*
numbers (`MaxTrans=32`, `FABRIC_MAX_TRANS=32`, `MAX_INFLIGHT_IDS=4`,
`ERR_SLV_MAX_TRANS=32`) but never ties them to any clock-gating consumer. The
producer/transport/consumer triad the boundary describes for this area cannot
be constructed from the pinned SPEC at all, so **no feature is emitted for
this area** — the gap is raised as `SF-001` instead of being guessed.

## Required interactions

None — the SPEC names no cross-feature requirement within this boundary. The
DMA hysteresis gate (`SMC-CG-DMA-HYST`) and the two Zeroer clock domains
(`SMC-CG-ZEROER-AXICLK`, `SMC-CG-ZEROER-REGCLK`) are documented as
independent gating mechanisms in independent modules with independent
producer signals; none of the nine pinned docs states a requirement that any
one of these gates' behavior depends on, or must be jointly observed with,
another feature's gate. `zeroer.adoc` §Clock Domains explicitly states the
register clock is "independent of AXI activity," which is a statement against
an interaction, not for one. No `INT-*` key is emitted.

## Spec-visible but underspecified / incomplete

The following gaps were found while deriving the inventory above and are
raised in full, with severities and exact questions, in
`SMC_CLOCK_GATING_P2_SPEC_REVIEW.md`:

- **SF-001** (Critical) — no `axi_cg_snoop`/OutstandingTx-vs-fabric-capacity
  mechanism is named anywhere in the pinned docs; the boundary's named area
  could not be turned into a feature.
- **SF-002** (High) — `clk_rst.adoc`'s "6-bit programmable" Hysteresis Control
  wording conflicts (or is at least unclear against) `dma.adoc`'s framing of
  `CG_HYSTERESIS_W` as a synthesis-time RTL parameter; affects
  `SMC-CG-DMA-HYST.S1`.
- **SF-003** (High) — "frontend wakeup" is used as an activity-detection
  condition without an exact, observable definition; affects
  `SMC-CG-DMA-HYST.S2`.
- **SF-004** (Critical) — `register_activity` (Zeroer reg_clk gate condition)
  has no defined generation/duration semantics; affects
  `SMC-CG-ZEROER-REGCLK.S1`.
- **SF-005** (Critical) — Zeroer trigger-during-busy (back-to-back access)
  outcome is undefined; affects `SMC-CG-ZEROER-AXICLK.S1`.
- **SF-006** (Medium) — `clk_rst.adoc`'s "Enable Threshold" CG parameter row
  has no corresponding named register/mechanism in any per-module (DMA,
  Zeroer) description; informational, does not block a specific scenario.
