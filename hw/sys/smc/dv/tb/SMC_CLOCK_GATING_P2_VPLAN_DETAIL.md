---
schema: dv-quality/v1
artifact: checkbox-cards
artifact_revision: 1
content_sha256: 6a10cab30c73449a6968b1803148bf19d5de8f91f2dcfea40f2d4886f0afa69b
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
  run_id: dv_vplan_gen-SMC_CLOCK_GATING_P2-amend-SMC_CG_P2_002-2026-08-05T17:25:00+08:00
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
cards:
- id: SMC_CG_P2_001
  anchor: smc_dma_cg_activity_test
  revision: 1
  supersedes_revision: null
  current: true
  status: approved
  record_sha256: f30a819ece07cac193724665274c74e6512a18c0771b7fde11375464acf5489a
  approved_by: minshaoho
  approved_at: '2026-08-05T15:52:00+08:00'
  category: DMA clock-gating hysteresis breadth (P2)
  owns: prim_clk_gater_hysteresis full-range 0-63 cycle sweep and the activity-during-hysteresis race
    for the DMA frontend/request-manager/backend clock only; excludes nominal single-point hysteresis
    assert/deassert already closed under the prior milestone, and excludes the axi_cg_snoop/fabric-capacity
    area (blocked entirely by SF-001 -- no feature exists to own).
  evidence_class: frontdoor-func
  closure_tier: A
  derived_from:
    plan_revision: 1
    testcase_revision: 1
    testcase_record_sha256: 98e628cd4183ce05c02517f1828a9ed5ee18b3a0849be5c14b4c2d8a71dbd316
    allocated_scenarios:
    - SMC-CG-DMA-HYST.S1
    - SMC-CG-DMA-HYST.S2
    testcase_id: SMC_CG_P2_001
  description:
    producer: combined DMA activity signal (frontend wakeup OR backend busy)
    transport: the single prim_clk_gater_hysteresis instance and its 6-bit (0-63 cycle) hysteresis counter
    consumer: gated clock reaching idma_frontend_wrapper, idma_request_manager_wrapper, and idma_backend_wrapper
  steps:
  - id: S1
    text: 'SETUP: bring the DMA block out of reset with clk_smc_i stable, disable_cg=0 (clock gating enabled);
      preload/confirm baseline idle state -- no frontend wakeup, no backend busy, hysteresis counter at
      0, clock gated.'
    derived_from: []
  - id: S2
    text: 'ACTION/RESPONSE/EFFECT for SMC-CG-DMA-HYST.S1: for each swept inter-activity gap in {0, 1,
      32, 63, 64} clk_smc_i cycles, assert then de-assert the combined frontend-wakeup/backend-busy activity
      signal, hold inactivity for exactly that many cycles, and record the exact cycle at which the DMA
      clock-enable output deasserts relative to the last activity de-assert.'
    derived_from:
    - SMC-CG-DMA-HYST.S1
  - id: S3
    text: 'ACTION/RESPONSE/EFFECT for SMC-CG-DMA-HYST.S2: start a hysteresis countdown, then re-assert
      activity (frontend wakeup or backend busy) once early in the countdown and once at the last cycle
      before expiry; after each reassertion, de-assert activity again and record whether the clock-enable
      output ever deasserted during the interrupted window and whether the post-clear countdown restarts
      from the full window.'
    derived_from:
    - SMC-CG-DMA-HYST.S2
  - id: S4
    text: 'Sn (TIMEOUT): every bounded wait for a clock-enable deassertion or a post-clear countdown completion
      fails with last state if it does not resolve within the declared bound (max hysteresis window +
      margin).'
    derived_from: []
  randomization: SMC-CG-DMA-HYST.S1's coverage record (feature_list) is RANDOMIZED -- inter-activity gap
    length swept 0 through 64 clk_smc_i cycles, required cells hyst-gap={0,1,32-mid,63-max,64-just-over-max},
    artifact functional_coverage_report. SMC-CG-DMA-HYST.S2's coverage record is DIRECTED -- required
    cells {activity-reassert-early-in-countdown, activity-reassert-at-last-cycle-of-countdown, activity-clear-immediately-after-reassert,
    back-to-back-reassert-reassert}. The scenario coverage records in the feature_list remain authoritative;
    no seed count is recorded here.
  observation: Passive hierarchical monitor on the prim_clk_gater_hysteresis clock-enable output and on
    the combined frontend-wakeup/backend-busy activity signal, sampled every clk_smc_i edge (cycle-accurate,
    required to resolve an exact swept-cycle boundary and a same-cycle reassertion). A failed, X, or Z
    read on either signal during the observation window is unobservable, never evidence.
  checkers:
  - id: CHK-DMA-HYST-SWEEP
    checks_steps:
    - S2
    proves:
    - SMC-CG-DMA-HYST
    covers:
    - SMC-CG-DMA-HYST.S1
    proof_class: LIVE
    expect_source: hw/sys/smc/doc/dma.adoc §Configuration Parameters (CG_HYSTERESIS_W) and §Performance
      Optimization and Power Management (Clock Gating Configuration) @ e2aae39953bb8001c7c20e3afd3956e68c22440c
    proof: 'For each swept gap in {0, 1, 32, 63}: the DMA clock-enable output deasserts exactly `gap`
      clk_smc_i cycles after the last activity de-assert edge, no earlier and no later. For gap=64: the
      clock-enable output is already deasserted no later than cycle 63 after the last activity de-assert
      (gating has occurred at or before the declared maximum, never later).'
    fail_on: clock-enable observed asserted beyond the expected deassertion cycle for any swept gap; clock-enable
      deasserting earlier than the expected cycle for gap<63; X/Z on the clock-enable or activity signal
      during the window; any of the 5 required cells not observed in the retained log.
    lifecycle: null
  - id: CHK-DMA-HYST-RACE
    checks_steps:
    - S3
    proves:
    - SMC-CG-DMA-HYST
    covers:
    - SMC-CG-DMA-HYST.S2
    proof_class: LIVE
    expect_source: hw/sys/smc/doc/dma.adoc §Performance Optimization and Power Management (Activity Detection);
      hw/sys/smc/doc/clk_rst.adoc §Clock and Reset-Based Power Management Integration (Hysteresis Control)
      @ 2f40548ea787240680a1c45ab75b8729e9620778
    proof: The clock-enable output stays asserted (1) with zero deassert pulses across the entire window
      from each reassertion edge (early-in-countdown, last-cycle-of-countdown) through the following activity
      de-assert; after each de-assert, the countdown restarts and clock-enable deasserts the same declared
      number of cycles later as an uninterrupted countdown (per CHK-DMA-HYST-SWEEP's cycle-exact contract).
    fail_on: any clock-enable deassert pulse, even one cycle, observed between a reassertion edge and
      the following de-assert; the post-clear countdown deasserting at a different cycle count than an
      uninterrupted countdown; timeout waiting for the post-clear deassertion.
    lifecycle: null
  - id: CHK-NONVAC
    checks_steps:
    - S1
    - S2
    - S3
    proves: []
    covers: []
    proof_class: INTEGRITY
    expect_source: approved card ordering contract
    proof: SETUP < ACTIVITY-BASELINE < SWEEP-COMPLETE(5-cells) < RACE-REASSERT-EARLY < RACE-REASSERT-LAST
      < PASS
    fail_on: testcase reports PASS with any term missing or out of order, or a progress log line substituted
      for the real PASS marker.
    lifecycle: null
  - id: CHK-TIMEOUT-PATHS
    checks_steps:
    - S4
    proves: []
    covers: []
    proof_class: INTEGRITY
    expect_source: approved card timeout contract
    proof: Every bounded wait (gap-deassertion wait, post-clear countdown wait) has a finite, logged bound
      derived from the declared maximum hysteresis window (63 cycles) plus margin, a static implementation
      path that fails the testcase on expiry, and logs the last observed clock-enable/activity state at
      expiry.
    fail_on: an unbounded or ignored wait; a wait whose bound is not logged; expiry that does not fail
      the testcase; missing last-state diagnostic on expiry.
    lifecycle: null
  guardrails:
  - No force/deposit on any DMA or clock-gating internal signal (owns_notes constraint); the clock-enable
    and activity signals are observed by passive hierarchical read only.
  - 'CHK-NO-TAUTOLOGY: the expected deassertion cycle for each swept gap is computed from the declared
    stimulus timing (the gap actually applied), never copied from the DUT''s own clock-enable trace.'
  blockers: []
- id: SMC_CG_P2_002
  anchor: smc_zeroer_axiclk_cg_test
  revision: 1
  supersedes_revision: null
  current: false
  status: approved
  record_sha256: b73eb874b510761d3cea18f878ed57f0908994b2b0da30eb40050133ca9ed6a7
  approved_by: minshaoho
  approved_at: '2026-08-05T15:52:00+08:00'
  category: Zeroer axi_clk clock-gating breadth (P2)
  owns: axi_clk_enable = disable_cg | zeroer_busy_o | ~rst_ni gate behavior across the busy-to-idle back-to-back
    trigger race only; excludes reg_clk gating (owned by SMC_CG_P2_003) and excludes nominal single-operation
    axi_clk gate/ungate already closed under the prior milestone.
  evidence_class: frontdoor-func
  closure_tier: A
  derived_from:
    plan_revision: 1
    testcase_revision: 1
    testcase_record_sha256: 53791893d0c2043a2cb1d773b4736eb35027ab47038d3b039c5053a239393681
    allocated_scenarios:
    - SMC-CG-ZEROER-AXICLK.S1
    testcase_id: SMC_CG_P2_002
  description:
    producer: zeroer_busy_o, asserted from trigger through ST_ISSUE_ADDR/ST_ISSUE_DATA until all write
      responses are received, racing a new follow-on trigger write
    transport: prim_clkgater gating the axi_clk domain per axi_clk_enable = disable_cg | zeroer_busy_o
      | ~rst_ni
    consumer: the zeroer AXI4 master interface issuing write addresses and streaming zero data for the
      follow-on operation
  steps:
  - id: S1
    text: 'SETUP: bring the zeroer out of reset with axi_clk/clk_smc_i stable, disable_cg=0; confirm baseline
      idle (zeroer_busy_o=0, axi_clk gated).'
    derived_from: []
  - id: S2
    text: 'ACTION/RESPONSE/EFFECT for SMC-CG-ZEROER-AXICLK.S1: issue a first zero-fill trigger and let
      it run until zeroer_busy_o''s falling edge is imminent; at each of the 3 required relative timings
      (1 cycle before, same cycle as, 1 cycle after the zeroer_busy_o falling edge) issue the follow-on
      DEST_ADDR/SIZE/CTRL_STATUS trigger write; observe axi_clk_enable continuously across the boundary
      and observe whether/how the follow-on operation is accepted and executed.'
    derived_from:
    - SMC-CG-ZEROER-AXICLK.S1
  - id: S3
    text: 'Sn (TIMEOUT): the bounded wait for the follow-on operation''s write-address phase to begin
      (once accepted) fails with last state if it does not resolve within the declared bound.'
    derived_from: []
  randomization: SMC-CG-ZEROER-AXICLK.S1's coverage record (feature_list) is DIRECTED -- required cells
    {new-trigger-1-cycle-before-busy-deassert, new-trigger-same-cycle-as-busy-deassert, new-trigger-1-cycle-after-busy-deassert},
    no random knobs. The scenario coverage record in the feature_list remains authoritative.
  observation: Passive hierarchical monitor on axi_clk_enable and zeroer_busy_o, sampled every axi_clk
    (or clk_smc_i, whichever clocks the gater) edge -- cycle-accurate, required to place the follow-on
    trigger at an exact 1-cycle offset from the busy-to-idle edge. Frontdoor observation of the AXI4 master's
    write-address/write-data channel for the follow-on operation's completion. Failed/X/Z reads are unobservable,
    never evidence.
  checkers:
  - id: CHK-ZEROER-AXICLK-NOGLITCH
    checks_steps:
    - S2
    proves:
    - SMC-CG-ZEROER-AXICLK
    covers:
    - SMC-CG-ZEROER-AXICLK.S1
    proof_class: LIVE
    expect_source: hw/sys/smc/doc/zeroer.adoc §Clock Gating (Clock Gating Control table) @ 2f40548ea787240680a1c45ab75b8729e9620778
    proof: axi_clk_enable remains asserted (1) with zero deassert pulses across the busy-to-idle boundary,
      at every one of the 3 swept follow-on-trigger timings (1-before, same-cycle, 1-after).
    fail_on: any axi_clk_enable deassert pulse observed between the prior operation's busy de-assert and
      the follow-on operation's busy re-assert, at any swept timing; X/Z on axi_clk_enable; any of the
      3 required cells not observed in the retained log.
    lifecycle: null
  - id: CHK-ZEROER-AXICLK-COMPLETION
    checks_steps:
    - S2
    proves:
    - SMC-CG-ZEROER-AXICLK
    covers:
    - SMC-CG-ZEROER-AXICLK.S1
    proof_class: LIVE
    expect_source: hw/sys/smc/doc/zeroer.adoc §State Machine; §Operation Flow (Completion) @ 2f40548ea787240680a1c45ab75b8729e9620778
    proof: At the 'same-cycle' and '1-cycle-after' swept timings (the follow-on trigger arrives at or
      after the busy-to-idle edge), the follow-on operation's write-address phase begins within the card's
      declared bound and the operation completes with a status update, per SMC_CG_P2_002.blockers. At
      the '1-cycle-before' timing (the trigger genuinely races zeroer_busy_o=1), this checker records
      the DUT's observed accept/reject/error response verbatim as evidence-only context and does NOT assert
      a pass/fail verdict on that response's correctness -- the spec-defined outcome for a trigger arriving
      while zeroer_busy_o is still asserted is open per SF-005, and this checker must not invent one.
    fail_on: 'for the ''same-cycle''/''1-cycle-after'' cells: write-address phase does not begin within
      the bound, or the operation does not reach a completion status update. For all 3 cells: this checker
      reports FAIL if it silently drops the ''1-cycle-before'' response instead of logging it, or if it
      asserts a pass/fail verdict on that response ahead of SF-005 being answered.'
    lifecycle: null
  - id: CHK-NONVAC
    checks_steps:
    - S1
    - S2
    proves: []
    covers: []
    proof_class: INTEGRITY
    expect_source: approved card ordering contract
    proof: SETUP < FIRST-OP-BUSY < BOUNDARY-SWEEP(3-cells) < FOLLOWON-OBSERVED < PASS
    fail_on: testcase reports PASS with any term missing or out of order, or progress substituted for
      the real PASS.
    lifecycle: null
  - id: CHK-TIMEOUT-PATHS
    checks_steps:
    - S3
    proves: []
    covers: []
    proof_class: INTEGRITY
    expect_source: approved card timeout contract
    proof: The wait for the follow-on write-address phase has a finite, logged bound, a static implementation
      path that fails the testcase on expiry, and logs the last observed axi_clk_enable/zeroer_busy_o
      state at expiry.
    fail_on: an unbounded/ignored wait, a bound not logged, expiry that does not fail the testcase, or
      missing last-state diagnostic.
    lifecycle: null
  guardrails:
  - No force/deposit on any zeroer or clock-gating internal signal (owns_notes constraint); axi_clk_enable/zeroer_busy_o
    are observed by passive hierarchical read only.
  - 'BY-DESIGN-EXCEPTION note: the ''1-cycle-before'' cell''s protocol-outcome verdict is deliberately
    not scored, per SF-005 (open); this is a declared, not silent, scope limit and must be re-examined
    once SF-005 is answered.'
  blockers:
  - SF-005
- id: SMC_CG_P2_002
  anchor: smc_zeroer_axiclk_cg_test
  revision: 2
  supersedes_revision: 1
  current: true
  status: approved
  record_sha256: 7716914f5e4c5adb60a4a2ebb6c58c271518148cdabc04a7796f561b5743fc7f
  approved_by: minshaoho
  approved_at: '2026-08-05T17:25:00+08:00'
  category: Zeroer axi_clk clock-gating breadth (P2)
  owns: axi_clk_enable = disable_cg | zeroer_busy_o | ~rst_ni gate behavior across the busy-to-idle back-to-back
    trigger race only; excludes reg_clk gating (owned by SMC_CG_P2_003) and excludes nominal single-operation
    axi_clk gate/ungate already closed under the prior milestone.
  evidence_class: frontdoor-func
  closure_tier: A
  derived_from:
    plan_revision: 1
    testcase_revision: 1
    testcase_record_sha256: 53791893d0c2043a2cb1d773b4736eb35027ab47038d3b039c5053a239393681
    allocated_scenarios:
    - SMC-CG-ZEROER-AXICLK.S1
    testcase_id: SMC_CG_P2_002
  description:
    producer: zeroer_busy_o, asserted from trigger through ST_ISSUE_ADDR/ST_ISSUE_DATA until all write
      responses are received, racing a new follow-on trigger write
    transport: prim_clkgater gating the axi_clk domain per axi_clk_enable = disable_cg | zeroer_busy_o
      | ~rst_ni
    consumer: the zeroer AXI4 master interface issuing write addresses and streaming zero data for the
      follow-on operation
  steps:
  - id: S1
    text: 'SETUP: bring the zeroer out of reset with axi_clk/clk_smc_i stable, disable_cg=0; confirm baseline
      idle (zeroer_busy_o=0, axi_clk gated).'
    derived_from: []
  - id: S2
    text: 'ACTION/RESPONSE/EFFECT for SMC-CG-ZEROER-AXICLK.S1: issue a first zero-fill trigger and let
      it run until zeroer_busy_o''s falling edge is imminent; at each of the 3 required relative timings
      (1 cycle before, same cycle as, 1 cycle after the zeroer_busy_o falling edge) issue the follow-on
      DEST_ADDR/SIZE/CTRL_STATUS trigger write (three sequential AXI-Lite register writes: DEST_ADDR,
      then SIZE, then CTRL_STATUS); observe axi_clk_enable continuously across the boundary and observe
      whether/how the follow-on operation is accepted and executed.'
    derived_from:
    - SMC-CG-ZEROER-AXICLK.S1
  - id: S3
    text: 'Sn (TIMEOUT): the bounded wait for the follow-on operation''s write-address phase to begin
      (once accepted) fails with last state if it does not resolve within the declared bound.'
    derived_from: []
  randomization: SMC-CG-ZEROER-AXICLK.S1's coverage record (feature_list) is DIRECTED -- required cells
    {new-trigger-1-cycle-before-busy-deassert, new-trigger-same-cycle-as-busy-deassert, new-trigger-1-cycle-after-busy-deassert},
    no random knobs. The scenario coverage record in the feature_list remains authoritative.
  observation: Passive hierarchical monitor on axi_clk_enable and zeroer_busy_o, sampled every axi_clk
    (or clk_smc_i, whichever clocks the gater) edge -- cycle-accurate, required to place the follow-on
    trigger at an exact 1-cycle offset from the busy-to-idle edge. Frontdoor observation of the AXI4 master's
    write-address/write-data channel for the follow-on operation's completion. The inter-busy deassert
    window (if any) between the prior operation's busy-fall and the follow-on operation's busy-rise is
    logged with its start cycle, end cycle, and duration at each swept timing. Failed/X/Z reads are unobservable,
    never evidence.
  checkers:
  - id: CHK-ZEROER-AXICLK-NOGLITCH
    checks_steps:
    - S2
    proves:
    - SMC-CG-ZEROER-AXICLK
    covers:
    - SMC-CG-ZEROER-AXICLK.S1
    proof_class: LIVE
    expect_source: hw/sys/smc/doc/zeroer.adoc §Clock Gating (Clock Gating Control table); §Operation Flow
      (Configuration -- DEST_ADDR/SIZE writes; Trigger -- CTRL_STATUS write) @ 2f40548ea787240680a1c45ab75b8729e9620778
    proof: 'While zeroer_busy_o==1 for either operation (the prior operation''s tail or the follow-on
      operation), axi_clk_enable remains asserted (1) with zero deassert pulses -- no mid-busy glitch
      -- at every one of the 3 swept follow-on-trigger timings (1-before, same-cycle, 1-after). Between
      the prior operation''s busy-to-idle transition and the follow-on operation''s busy re-assertion,
      axi_clk_enable is PERMITTED to deassert for the duration of the documented multi-write configure-then-trigger
      protocol''s turnaround (DEST_ADDR, then SIZE, then CTRL_STATUS writes) -- observed ~26-28 clk_smc_i
      cycles at all 3 swept timings in the real frontdoor trigger sequence -- and this deassert gap is
      logged (start cycle, end cycle, duration), never scored as a failure, at each swept timing. AMENDMENT
      NOTE (supersedes revision 1): revision 1 required zero axi_clk_enable deassert across the WHOLE
      busy-to-idle boundary including this multi-write turnaround, which Skill 1.5 found physically unreachable
      via the real frontdoor trigger protocol at all 3 swept timings; this revision narrows the proof
      to the mid-busy segment per DV owner decision (minshaoho, standing order).'
    fail_on: any axi_clk_enable deassert pulse observed while zeroer_busy_o==1 for either operation, at
      any swept timing; X/Z on axi_clk_enable while zeroer_busy_o==1; any of the 3 required cells not
      observed in the retained log; an inter-busy deassert window occurring without its start cycle, end
      cycle, and duration being logged.
    lifecycle: null
  - id: CHK-ZEROER-AXICLK-COMPLETION
    checks_steps:
    - S2
    proves:
    - SMC-CG-ZEROER-AXICLK
    covers:
    - SMC-CG-ZEROER-AXICLK.S1
    proof_class: LIVE
    expect_source: hw/sys/smc/doc/zeroer.adoc §State Machine; §Operation Flow (Completion) @ 2f40548ea787240680a1c45ab75b8729e9620778
    proof: At the 'same-cycle' and '1-cycle-after' swept timings (the follow-on trigger arrives at or
      after the busy-to-idle edge), the follow-on operation's write-address phase begins within the card's
      declared bound and the operation completes with a status update, per SMC_CG_P2_002.blockers. At
      the '1-cycle-before' timing (the trigger genuinely races zeroer_busy_o=1), this checker records
      the DUT's observed accept/reject/error response verbatim as evidence-only context and does NOT assert
      a pass/fail verdict on that response's correctness -- the spec-defined outcome for a trigger arriving
      while zeroer_busy_o is still asserted is open per SF-005, and this checker must not invent one.
    fail_on: 'for the ''same-cycle''/''1-cycle-after'' cells: write-address phase does not begin within
      the bound, or the operation does not reach a completion status update. For all 3 cells: this checker
      reports FAIL if it silently drops the ''1-cycle-before'' response instead of logging it, or if it
      asserts a pass/fail verdict on that response ahead of SF-005 being answered.'
    lifecycle: null
  - id: CHK-NONVAC
    checks_steps:
    - S1
    - S2
    proves: []
    covers: []
    proof_class: INTEGRITY
    expect_source: approved card ordering contract
    proof: SETUP < FIRST-OP-BUSY < BOUNDARY-SWEEP(3-cells) < FOLLOWON-OBSERVED < PASS
    fail_on: testcase reports PASS with any term missing or out of order, or progress substituted for
      the real PASS.
    lifecycle: null
  - id: CHK-TIMEOUT-PATHS
    checks_steps:
    - S3
    proves: []
    covers: []
    proof_class: INTEGRITY
    expect_source: approved card timeout contract
    proof: The wait for the follow-on write-address phase has a finite, logged bound, a static implementation
      path that fails the testcase on expiry, and logs the last observed axi_clk_enable/zeroer_busy_o
      state at expiry.
    fail_on: an unbounded/ignored wait, a bound not logged, expiry that does not fail the testcase, or
      missing last-state diagnostic.
    lifecycle: null
  guardrails:
  - No force/deposit on any zeroer or clock-gating internal signal (owns_notes constraint); axi_clk_enable/zeroer_busy_o
    are observed by passive hierarchical read only.
  - 'BY-DESIGN-EXCEPTION note: the ''1-cycle-before'' cell''s protocol-outcome verdict is deliberately
    not scored, per SF-005 (open); this is a declared, not silent, scope limit and must be re-examined
    once SF-005 is answered.'
  - 'BY-DESIGN-EXCEPTION note (new in revision 2): a deassert gap of axi_clk_enable strictly between the
    prior operation''s busy-fall and the follow-on operation''s busy-rise, caused by the documented multi-write
    configure-then-trigger protocol (zeroer.adoc §Operation Flow: Configuration DEST_ADDR/SIZE writes,
    then a CTRL_STATUS trigger write), is expected and logged, not scored as a NOGLITCH failure; only
    a deassert observed while zeroer_busy_o==1 for either operation fails CHK-ZEROER-AXICLK-NOGLITCH.
    This narrows revision 1''s whole-boundary zero-deassert requirement, which Skill 1.5 found unreachable
    via the real frontdoor trigger protocol at all 3 swept timings (owner decision: minshaoho, standing
    order "都簽署繼續").'
  blockers:
  - SF-005
- id: SMC_CG_P2_003
  anchor: smc_zeroer_regclk_cg_test
  revision: 1
  supersedes_revision: null
  current: true
  status: approved
  record_sha256: 93666c6c76e78b0f181dba725025d1652ff5407526e20c4421403218b24e290e
  approved_by: minshaoho
  approved_at: '2026-08-05T15:52:00+08:00'
  category: Zeroer reg_clk clock-gating breadth (P2)
  owns: reg_clk_enable = disable_cg | register_activity | ~rst_ni gate behavior across the pending-access-while-gated
    race only; excludes axi_clk gating (owned by SMC_CG_P2_002) and excludes nominal single-access reg_clk
    gate/ungate already closed under the prior milestone.
  evidence_class: frontdoor-func
  closure_tier: A
  derived_from:
    plan_revision: 1
    testcase_revision: 1
    testcase_record_sha256: 49c886a759cc50a15a1dfbc1bc3e0e51ad3cfa62eb333bbc7b397b689df7f484
    allocated_scenarios:
    - SMC-CG-ZEROER-REGCLK.S1
    testcase_id: SMC_CG_P2_003
  description:
    producer: register_activity, asserted by accesses to the zeroer's register block, racing the reg_clk
      gater's currently-gated state
    transport: prim_clkgater gating the reg_clk domain per reg_clk_enable = disable_cg | register_activity
      | ~rst_ni, independent of AXI activity
    consumer: the zeroer register interface (DEST_ADDR, SIZE, CTRL_STATUS, Interrupt Enable)
  steps:
  - id: S1
    text: 'SETUP: bring the zeroer out of reset with clk_smc_i stable, disable_cg=0; hold the register
      interface idle long enough that reg_clk gates (reg_clk_enable falls to 0) with no zeroer register
      access pending.'
    derived_from: []
  - id: S2
    text: 'ACTION/RESPONSE/EFFECT for SMC-CG-ZEROER-REGCLK.S1: for each of the 3 required cells (immediately
      after reg_clk gates, long after reg_clk gates, and a second access issued back-to-back with the
      first across the gate boundary), issue a register access (a CTRL_STATUS/status read or a new DEST_ADDR/SIZE/CTRL_STATUS
      write) while reg_clk is gated; observe reg_clk_enable''s rising edge and the access''s data/acknowledge
      result.'
    derived_from:
    - SMC-CG-ZEROER-REGCLK.S1
  - id: S3
    text: 'Sn (TIMEOUT): the bounded wait for reg_clk_enable to rise and for the pending access to be
      serviced fails with last state if it does not resolve within the declared bound.'
    derived_from: []
  randomization: SMC-CG-ZEROER-REGCLK.S1's coverage record (feature_list) is DIRECTED -- required cells
    {access-immediately-after-reg_clk-gates, access-long-after-reg_clk-gates, back-to-back-accesses-across-gate-boundary},
    no random knobs. The scenario coverage record in the feature_list remains authoritative.
  observation: Passive hierarchical monitor on reg_clk_enable, sampled every clk_smc_i edge (cycle-accurate,
    required to bound the ungate latency exactly). Frontdoor observation of the register interface's read-data/write-acknowledge
    for the pending access. Failed/X/Z reads are unobservable, never evidence.
  checkers:
  - id: CHK-ZEROER-REGCLK-UNGATE
    checks_steps:
    - S2
    proves:
    - SMC-CG-ZEROER-REGCLK
    covers:
    - SMC-CG-ZEROER-REGCLK.S1
    proof_class: LIVE
    expect_source: hw/sys/smc/doc/zeroer.adoc §Clock Gating (Clock Gating Control table) @ 2f40548ea787240680a1c45ab75b8729e9620778
    proof: reg_clk_enable rises to 1 within the card's declared bound (see CHK-TIMEOUT-PATHS) after each
      swept pending access arrives while gated, at all 3 required cells (immediately-after-gate, long-after-gate,
      back-to-back-across-boundary).
    fail_on: reg_clk_enable does not rise within the declared bound for any swept cell; X/Z on reg_clk_enable;
      any of the 3 required cells not observed in the retained log.
    lifecycle: null
  - id: CHK-ZEROER-REGCLK-ACCESS-COMPLETE
    checks_steps:
    - S2
    proves:
    - SMC-CG-ZEROER-REGCLK
    covers:
    - SMC-CG-ZEROER-REGCLK.S1
    proof_class: LIVE
    expect_source: hw/sys/smc/doc/zeroer.adoc §Operation Control @ 2f40548ea787240680a1c45ab75b8729e9620778
    proof: the pending register access is correctly serviced once reg_clk ungates -- a read returns the
      expected register value (matching the last value written or the documented reset value) and a write
      is reflected in a subsequent status read -- at every one of the 3 swept cells, with the exact maximum
      service latency bound recorded per SMC_CG_P2_003.blockers pending SF-004.
    fail_on: a read returns stale, incorrect, or X/Z data; a write is not reflected in a subsequent read;
      the access hangs beyond the declared bound at any swept cell.
    lifecycle: null
  - id: CHK-NONVAC
    checks_steps:
    - S1
    - S2
    proves: []
    covers: []
    proof_class: INTEGRITY
    expect_source: approved card ordering contract
    proof: SETUP < REG_CLK-GATED-BASELINE < ACCESS-SWEEP(3-cells) < PASS
    fail_on: testcase reports PASS with any term missing or out of order, or progress substituted for
      the real PASS.
    lifecycle: null
  - id: CHK-TIMEOUT-PATHS
    checks_steps:
    - S3
    proves: []
    covers: []
    proof_class: INTEGRITY
    expect_source: approved card timeout contract
    proof: The wait for reg_clk_enable to rise and for the pending access to be serviced has a finite,
      logged bound, a static implementation path that fails the testcase on expiry, and logs the last
      observed reg_clk_enable/access state at expiry.
    fail_on: an unbounded/ignored wait, a bound not logged, expiry that does not fail the testcase, or
      missing last-state diagnostic.
    lifecycle: null
  guardrails:
  - No force/deposit on any zeroer or clock-gating internal signal (owns_notes constraint); reg_clk_enable
    is observed by passive hierarchical read only.
  - 'CHK-NO-TAUTOLOGY: the expected read-back value is taken from the value actually written by the testbench
    stimulus (or the documented reset value), never copied from the DUT''s own register read path.'
  blockers:
  - SF-004
---

## Cards (candidate, 3 of 3, within budget -- 3-4 steps / 4 checkers each, well under the
12-step/12-checker/8-card policy limits)

| ID | Anchor | Owns | Steps | Checkers | Blockers |
|---|---|---|---|---|---|
| SMC_CG_P2_001 | `smc_dma_cg_activity_test` | DMA hysteresis sweep + reassertion race | 4 | 4 | none |
| SMC_CG_P2_002 | `smc_zeroer_axiclk_cg_test` | Zeroer axi_clk vs back-to-back trigger race | 3 | 4 | SF-005 |
| SMC_CG_P2_003 | `smc_zeroer_regclk_cg_test` | Zeroer reg_clk vs pending-access race | 3 | 4 | SF-004 |

Every card follows one `SETUP -> ACTION/RESPONSE/EFFECT -> NONVAC` chain per its allocated
scenario(s); every functional step names its parent scenario in `derived_from`; every
substantive checker's `covers` is a subset of its checked steps' `derived_from` union.
`CHK-NONVAC` and, where the card has a TIMEOUT step, `CHK-TIMEOUT-PATHS` are present on all
three cards. Two cards
(`SMC_CG_P2_002`, `SMC_CG_P2_003`) carry an open-finding `blockers` entry: their contested-race
steps and observation points are fully specified, but one checker on each card is explicitly
scoped to avoid asserting a pass/fail verdict on the exact sub-behavior that `SF-005`/`SF-004`
leaves open, rather than guessing it.

## Amendment log

**`SMC_CG_P2_002` revision 2 (supersedes revision 1, both `current`-flagged correctly, `approved_by:
minshaoho`, `approved_at: '2026-08-05T17:25:00+08:00'`).** Skill 1.5 implementation of the real
Zeroer trigger protocol (3 sequential AXI-Lite writes DEST_ADDR->SIZE->CTRL_STATUS) found that
`axi_clk_enable` necessarily deasserts for ~26-28 `clk_smc_i` cycles between the op1 busy-fall and
the op2 busy-rise at **all three** swept timings `{-1, 0, +1}` -- revision 1's
`CHK-ZEROER-AXICLK-NOGLITCH` required zero deassert across the *whole* busy-to-idle boundary
including that protocol turnaround, which is unreachable via frontdoor. Per DV owner decision
(minshaoho, standing order "都簽署繼續"), revision 2 narrows the proof (amend choice ii):
`axi_clk_enable` must stay asserted only while `zeroer_busy_o==1` for either operation (no
mid-busy glitch); a deassert gap between busy pulses caused by the multi-write trigger latency is
now allowed and logged, not scored as a failure. `CHK-ZEROER-AXICLK-COMPLETION` is unchanged
(same-cycle/1-after scored, 1-cycle-before evidence-only pending `SF-005`). No feature_list or
testcase-plan record required amendment: `owns`, `allocated.scenarios`, and
`allocated.features` for `SMC_CG_P2_002` are byte-identical to plan revision 1 -- this is a
Step-4 checker-exactness narrowing, not an allocation change, so amendment stayed scoped to the
card layer per the skill's escalation rule.
