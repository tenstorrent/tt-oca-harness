---
schema: dv-quality/v1
artifact: spec-audit
artifact_revision: 1
content_sha256: 5feed47c2b391917eea1b0dcadf39c6ca69bdce2a2023eae75598f4093b7e9f8
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
findings:
- id: SF-001
  category: SF-MISSING
  severity: Critical
  spec_refs:
  - hw/sys/smc/doc/clk_rst.adoc §Clock and Reset-Based Power Management Integration (Clock Gating Control
    Parameters table) @ 2f40548ea787240680a1c45ab75b8729e9620778
  - hw/sys/smc/doc/fabric.adoc §Configuration Parameters (MaxTrans, FABRIC_MAX_TRANS, MAX_INFLIGHT_IDS,
    ERR_SLV_MAX_TRANS) @ ffc8cdcc349e1e01a2b970442a01070b1c62c0d7
  observed: The boundary names an "axi_cg_snoop OutstandingTx capacity vs fabric MaxTrans/ID-bucket sizing"
    behavior as P2 in-scope, but none of the nine pinned documents names an `axi_cg_snoop` module, an
    "OutstandingTx" counter, or any other snoop-style outstanding-transaction tracker used to hold a clock-gating
    decision open until in-flight DMA/fabric traffic drains. `clk_rst.adoc`'s Clock Gating Control Parameters
    table lists only "Hysteresis Control", "Activity Detection", "Enable Threshold", and "Module Gating"
    — no snoop or outstanding-counter row. `fabric.adoc` §Configuration Parameters states exact outstanding-
    transaction *capacity* numbers (MaxTrans=32, FABRIC_MAX_TRANS=32, MAX_INFLIGHT_IDS=4, ERR_SLV_MAX_TRANS=32)
    but never ties any of them to a clock-gating consumer. The producer (a snoop counter), transport (a
    comparison against fabric capacity), and consumer (a gating decision the counter protects) legs of
    this behavior are all absent from the pinned SPEC — the triad test fails on every leg, not just the
    exact value.
  question: Does an `axi_cg_snoop` (or equivalently named) OutstandingTx-tracking mechanism exist in the
    SMC clock-gating architecture at all? If so, which document/section defines it, what counter width
    and maximum value does it use, which fabric capacity parameter(s) (MaxTrans, FABRIC_MAX_TRANS, MAX_INFLIGHT_IDS,
    or something else) must it stay bounded against, and which clock-gating decision (which module's gate)
    does it hold open? If no such mechanism exists yet, should this boundary item be withdrawn from P2,
    or does it describe a behavior that still needs to be specified before it can be verified?
  affects:
    features: []
    scenarios: []
    anchors: []
  status: waived
  resolution:
    answered_or_waived_by: minshaoho
    answered_or_waived_at: '2026-08-05T15:52:00+08:00'
    note: 'P2 withdraws axi_cg_snoop / OutstandingTx capacity verification from THIS pin''s contract:
      the nine pinned SPEC docs do not name the mechanism (triad fails). RTL-as-spec is OUT of boundary.
      Re-pin with an authoritative SPEC section before any OutstandingTx feature/testcase may be derived.
      smc_clk_multi_window_test remains unallocated for this withdrawn area.'
    spec_revision: 2f40548ea787240680a1c45ab75b8729e9620778
- id: SF-002
  category: SF-AMBIGUOUS
  severity: High
  spec_refs:
  - hw/sys/smc/doc/clk_rst.adoc §Clock and Reset-Based Power Management Integration ("Hysteresis Control
    | 6-bit programmable | Prevents clock gating oscillation under varying load") @ 2f40548ea787240680a1c45ab75b8729e9620778
  - hw/sys/smc/doc/dma.adoc §Configuration Parameters ("CG_HYSTERESIS_W | 6 | Clock gating hysteresis
    width in bits (6-bit = 0-63 cycle delay)") @ e2aae39953bb8001c7c20e3afd3956e68c22440c
  observed: '`clk_rst.adoc` describes "Hysteresis Control" as "6-bit programmable", which reads as a firmware/register-settable
    value. `dma.adoc` names the same 6-bit width as `CG_HYSTERESIS_W`, listed among synthesis-time "DMA
    Configuration Parameters" (default 6) with no associated register described in any of the nine pinned
    documents (the DMA register map itself is `regs/gen`, out of scope for this audit). It is unclear
    whether "programmable" means firmware can set an actual hysteresis delay value at runtime (via what
    register/field?) or only that the counter''s bit-width is a build-time RTL parameter, in which case
    the only way to exercise different points in the 0-63 cycle range is by varying the timing of activity
    stimulus, not by writing a register.'
  question: Is the DMA hysteresis delay software-programmable at runtime? If yes, which register/field
    sets it, what is its exact address and reset value, and is the settable range the full 0-63 or some
    subset? If no, please confirm `CG_HYSTERESIS_W` is purely a synthesis-time parameter and that "programmable"
    in `clk_rst.adoc`'s table refers to that build-time parameterization rather than a runtime register.
  affects:
    features:
    - SMC-CG-DMA-HYST
    scenarios:
    - SMC-CG-DMA-HYST.S1
    anchors: []
  status: answered
  resolution:
    answered_or_waived_by: minshaoho
    answered_or_waived_at: '2026-08-05T15:52:00+08:00'
    note: CG_HYSTERESIS_W is a synthesis-time RTL parameter (dma.adoc Configuration Parameters). clk_rst.adoc
      '6-bit programmable' refers to that build-time width, not a runtime CSR. P2 hysteresis sweep varies
      activity-stimulus timing across the 0-63 cycle range; it does not write a hysteresis-delay register.
    spec_revision: e2aae39953bb8001c7c20e3afd3956e68c22440c
- id: SF-003
  category: SF-AMBIGUOUS
  severity: High
  spec_refs:
  - hw/sys/smc/doc/dma.adoc §Performance Optimization and Power Management ("Activity Detection | Clock
    enabled when frontend wakeup or backend busy") @ e2aae39953bb8001c7c20e3afd3956e68c22440c
  observed: '"frontend wakeup" is used as one of the two activity-detection conditions that keeps the
    DMA clock enabled (the other being "backend busy", which zeroer.adoc-style busy semantics do not directly
    define for the DMA frontend either). No section in the pinned docs states what architecturally visible
    event constitutes a "wakeup" of the frontend — e.g. a new control-interface command write, a non-empty
    frontend-to-midend FIFO, or something else — nor how long the wakeup condition is asserted once triggered.'
  question: What exact, architecturally observable signal or event is "frontend wakeup"? Is it asserted
    for exactly one cycle per triggering event, for the duration the F2M FIFO is non-empty, or for some
    other defined interval? Without this, a hysteresis-race checker cannot state an exact cycle at which
    the countdown is expected to restart.
  affects:
    features:
    - SMC-CG-DMA-HYST
    scenarios:
    - SMC-CG-DMA-HYST.S2
    anchors: []
  status: answered
  resolution:
    answered_or_waived_by: minshaoho
    answered_or_waived_at: '2026-08-05T15:52:00+08:00'
    note: For P2 race checkers, 'frontend wakeup' is the architecturally observable DMA frontend activity
      condition already used by the prior milestone (tb_dma_frontend_busy / frontend busy side of 'frontend
      wakeup or backend busy' in dma.adoc). Countdown restart is keyed off reassertion of that frontend
      activity (or backend busy) during the hysteresis window.
    spec_revision: e2aae39953bb8001c7c20e3afd3956e68c22440c
- id: SF-004
  category: SF-MISSING
  severity: Critical
  spec_refs:
  - hw/sys/smc/doc/zeroer.adoc §Clock Gating ("Register Clock | reg_clk_enable = disable_cg | register_activity
    | ~rst_ni") @ 2f40548ea787240680a1c45ab75b8729e9620778
  - hw/sys/smc/doc/zeroer.adoc §Clock Domains ("Register Clock (reg_clk) | Separate clock for register
    interface, independent of AXI activity") @ 2f40548ea787240680a1c45ab75b8729e9620778
  observed: '`zeroer.adoc` names `register_activity` as the sole activity term keeping `reg_clk` enabled,
    but no section defines which accesses generate it (any read, any write, only writes to specific registers
    such as `CTRL_STATUS`?), what its pulse width or hold time is, or whether it has any hysteresis of
    its own (unlike the DMA path, no hysteresis width is named for the Zeroer register clock at all).
    This is the consumer-side exactness needed to write a bounded-completion checker for the pending-access
    race the boundary names for this domain.'
  question: Exactly which register accesses assert `register_activity`, for how many `reg_clk` (or `clk_smc_i`)
    cycles does it stay asserted per access, and is there any hysteresis/hold time after the access completes
    before `reg_clk` is allowed to gate again? What is the maximum number of cycles a pending register
    access may have to wait for `reg_clk` to ungate before the access is guaranteed to be serviced?
  affects:
    features:
    - SMC-CG-ZEROER-REGCLK
    scenarios:
    - SMC-CG-ZEROER-REGCLK.S1
    anchors: []
  status: answered
  resolution:
    answered_or_waived_by: minshaoho
    answered_or_waived_at: '2026-08-05T15:52:00+08:00'
    note: register_activity asserts on any AXI4-Lite access (read or write) to the Zeroer register block
      while the access is outstanding/active (same owner answer as P1 SF-004). Zeroer reg_clk has no separate
      named hysteresis in the pinned docs; after the access completes, reg_clk may gate again once register_activity
      deasserts. Pending-access service must complete within the card's declared bounded wait; max wait
      is that bound, not a separate SPEC constant.
    spec_revision: 2f40548ea787240680a1c45ab75b8729e9620778
- id: SF-005
  category: SF-MISSING
  severity: Critical
  spec_refs:
  - hw/sys/smc/doc/zeroer.adoc §Clock Gating ("AXI Clock | axi_clk_enable = disable_cg | zeroer_busy_o
    | ~rst_ni") @ 2f40548ea787240680a1c45ab75b8729e9620778
  - hw/sys/smc/doc/zeroer.adoc §Configuration and Control ("Validation | Hardware validates configuration
    parameters") @ 2f40548ea787240680a1c45ab75b8729e9620778
  observed: '`zeroer.adoc` describes a "Configuration Lock" concept for the DMA controller (`dma.adoc`
    §Control Interface: "Configuration Lock | Protection against modification during active transfers")
    but states no equivalent for the Zeroer. Neither the state-machine description (§State Machine, §Operation
    Flow) nor the register description (§Operation Control) states what happens if a new `DEST_ADDR`/`SIZE`/`CTRL_STATUS`
    trigger write arrives while `zeroer_busy_o` is still asserted from a prior operation: rejected, silently
    queued for after completion, flagged as an error status, or allowed to corrupt the in-flight address/size
    state. This is exactly the back-to-back contested access the boundary names as in-scope for P2, and
    it cannot be given an exact pass/fail expectation from the pinned SPEC alone.'
  question: What is the defined behavior when a new trigger write is issued to the Zeroer's `CTRL_STATUS`/`DEST_ADDR`/`SIZE`
    registers while `zeroer_busy_o` is still asserted from a previous operation? Is there a configuration-lock
    or busy-reject mechanism analogous to the DMA controller's, and if so what status/error indication
    does it produce?
  affects:
    features:
    - SMC-CG-ZEROER-AXICLK
    scenarios:
    - SMC-CG-ZEROER-AXICLK.S1
    anchors: []
  status: answered
  resolution:
    answered_or_waived_by: minshaoho
    answered_or_waived_at: '2026-08-05T15:52:00+08:00'
    note: 'Owner policy for P2: (a) trigger at same-cycle or after zeroer_busy_o falling edge MUST start
      and complete the follow-on op (scored). (b) trigger while still busy (1-cycle-before / genuine overlap)
      remains undefined in the pinned SPEC — evidence-only, no pass/fail on protocol outcome (matches
      card CHK-ZEROER-AXICLK-COMPLETION scope). Spec owner still owes a normative busy-reject/lock statement
      in zeroer.adoc for a future tightening.'
    spec_revision: 2f40548ea787240680a1c45ab75b8729e9620778
- id: SF-006
  category: SF-TERM
  severity: Medium
  spec_refs:
  - hw/sys/smc/doc/clk_rst.adoc §Clock and Reset-Based Power Management Integration ("Enable Threshold
    | Configurable delay | Balances responsiveness vs. power savings") @ 2f40548ea787240680a1c45ab75b8729e9620778
  - hw/sys/smc/doc/dma.adoc §Performance Optimization and Power Management (Clock Gating Configuration
    table) @ e2aae39953bb8001c7c20e3afd3956e68c22440c
  - hw/sys/smc/doc/zeroer.adoc §Clock Gating (Clock Gating Control table) @ 2f40548ea787240680a1c45ab75b8729e9620778
  observed: '`clk_rst.adoc`''s generic Clock Gating Control Parameters table lists an "Enable Threshold
    | Configurable delay" row alongside "Hysteresis Control". Neither `dma.adoc`''s Clock Gating Configuration
    table nor `zeroer.adoc`''s Clock Gating Control table names an "Enable Threshold" register, signal,
    or delay distinct from the hysteresis mechanisms they do describe. It is unclear whether "Enable Threshold"
    is a synonym for the same hysteresis/wakeup mechanism described per-module (a terminology inconsistency)
    or a distinct, currently undocumented per-module parameter.'
  question: Is "Enable Threshold" in the generic Clock Gating Control Parameters table the same mechanism
    as each module's named hysteresis/activity detection (i.e. just a generic name for it), or a separate,
    independently configurable delay that exists in some modules? If separate, which modules implement
    it and where is it documented?
  affects:
    features: []
    scenarios: []
    anchors: []
  status: answered
  resolution:
    answered_or_waived_by: minshaoho
    answered_or_waived_at: '2026-08-05T15:52:00+08:00'
    note: Enable Threshold in clk_rst.adoc's generic table is a synonym for the module hysteresis/activity-detection
      delay mechanism (same reading as P1 SF-002). No independent Enable Threshold field is claimed for
      DMA or Zeroer in this milestone.
    spec_revision: 2f40548ea787240680a1c45ab75b8729e9620778
---

Questions awaiting your answer:

SF-ID:     SF-001
CATEGORY:  SF-MISSING
SEVERITY:  Critical
SPEC-REF:  `clk_rst.adoc` §Clock and Reset-Based Power Management Integration (Clock Gating Control Parameters table); `fabric.adoc` §Configuration Parameters
OBSERVED:  No `axi_cg_snoop`/OutstandingTx-tracking mechanism, nor any tie between fabric's stated outstanding-transaction capacity numbers and a clock-gating consumer, is named anywhere in the nine pinned documents.
QUESTION:  Does an `axi_cg_snoop` (or equivalently named) OutstandingTx-tracking mechanism exist in the SMC clock-gating architecture? If so, where is it defined (counter width/max, which fabric capacity parameter it bounds against, which gate it holds open)? If not, should this boundary item be withdrawn from P2 or does it await a spec update?
AFFECTS:   (no feature could be derived for this area)
STATUS:    open

SF-ID:     SF-004
CATEGORY:  SF-MISSING
SEVERITY:  Critical
SPEC-REF:  `zeroer.adoc` §Clock Gating; §Clock Domains
OBSERVED:  `register_activity` (the Zeroer reg_clk gate condition) has no defined generating-access set, pulse width, or hold time.
QUESTION:  Which accesses assert `register_activity`, for how long, and is there any post-access hold before `reg_clk` may gate again? What is the maximum wait an access may see before `reg_clk` ungates?
AFFECTS:   SMC-CG-ZEROER-REGCLK / SMC-CG-ZEROER-REGCLK.S1
STATUS:    open

SF-ID:     SF-005
CATEGORY:  SF-MISSING
SEVERITY:  Critical
SPEC-REF:  `zeroer.adoc` §Clock Gating; §Configuration and Control
OBSERVED:  No defined outcome for a new trigger write arriving while `zeroer_busy_o` is still asserted from a prior operation (unlike the DMA controller's documented Configuration Lock).
QUESTION:  What happens on a trigger-during-busy write to the Zeroer — rejected, queued, error status, or undefined? Is there a lock/reject mechanism analogous to the DMA controller's?
AFFECTS:   SMC-CG-ZEROER-AXICLK / SMC-CG-ZEROER-AXICLK.S1
STATUS:    open

SF-ID:     SF-002
CATEGORY:  SF-AMBIGUOUS
SEVERITY:  High
SPEC-REF:  `clk_rst.adoc` §Clock and Reset-Based Power Management Integration; `dma.adoc` §Configuration Parameters
OBSERVED:  "Hysteresis Control | 6-bit programmable" (clk_rst.adoc) vs. `CG_HYSTERESIS_W` framed as a synthesis-time RTL parameter with no associated register (dma.adoc) — unclear whether the hysteresis delay is runtime-settable.
QUESTION:  Is the DMA hysteresis delay software-programmable at runtime via a register, or is `CG_HYSTERESIS_W` purely a build-time parameter?
AFFECTS:   SMC-CG-DMA-HYST / SMC-CG-DMA-HYST.S1
STATUS:    open

SF-ID:     SF-003
CATEGORY:  SF-AMBIGUOUS
SEVERITY:  High
SPEC-REF:  `dma.adoc` §Performance Optimization and Power Management
OBSERVED:  "frontend wakeup" is used as an activity-detection condition with no exact, observable definition.
QUESTION:  What exact signal/event constitutes "frontend wakeup", and for how long is it asserted per triggering event?
AFFECTS:   SMC-CG-DMA-HYST / SMC-CG-DMA-HYST.S2
STATUS:    open

SF-ID:     SF-006
CATEGORY:  SF-TERM
SEVERITY:  Medium
SPEC-REF:  `clk_rst.adoc` §Clock and Reset-Based Power Management Integration; `dma.adoc` §Performance Optimization and Power Management; `zeroer.adoc` §Clock Gating
OBSERVED:  Generic "Enable Threshold | Configurable delay" row has no corresponding named mechanism in either per-module (DMA, Zeroer) clock-gating description.
QUESTION:  Is "Enable Threshold" a synonym for the per-module hysteresis/activity-detection mechanisms already described, or a separate, currently undocumented parameter?
AFFECTS:   (no specific feature/scenario blocked)
STATUS:    open
