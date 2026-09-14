// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// dtp_sanity_test — VPLAN 0.1: runs
// dtp_sanity_test_seq on the shared ocah_jtag_vip agent's sequencer, then
// asserts full FSM state/edge closure via the env checker (this scenario's
// closure obligation — the per-cycle legality check is always on). Also
// arms the JTAG TAP-contract named evidence: required CHK-*
// IDs finalize through env.m_jtag_checker in check_phase.

class dtp_sanity_test extends dtp_base_test;
  `uvm_component_utils(dtp_sanity_test)

  function new(string name = "dtp_sanity_test", uvm_component parent = null);
    super.new(name, parent);
  endfunction

  virtual function void configure_test_cfg(dtp_test_cfg cfg);
    super.configure_test_cfg(cfg);
    cfg.require_jtag_ids('{"CHK-TAP-STATE", "CHK-TAP-RESET-TLR", "CHK-TAP-TLR-TMS5", "CHK-TAP-GOTO",
                         "CHK-TAP-TLR-IDCODE", "CHK-IDCODE-RAW", "CHK-IDCODE-STABLE",
                         "CHK-IDCODE-MARKER", "CHK-BYPASS-LATENCY", "CHK-SCAN-IR-LEN",
                         "CHK-SCAN-DR-LEN", "CHK-NONVAC"});
    cfg.require_feature(DtpFeatureBypass);
    cfg.require_feature(DtpFeatureIdcode);
  endfunction

  virtual function ocah_sequence create_scenario_seq();
    return dtp_sanity_test_seq::type_id::create("seq");
  endfunction

  virtual function string specific_loops_knob();
    return "DTP_SANITY_TEST_LOOPS";
  endfunction

  // VPLAN 0.1 closure gate: after the looped passes, every TAP state must
  // have been visited and every legal edge taken (the deterministic walk
  // in each pass guarantees it; the checker proves it).
  task run_phase(uvm_phase phase);
    phase.raise_objection(this, {get_type_name(), " running"});
    run_looped_scenario();
    m_env.m_fsm_checker.check_fsm_closure();
    phase.drop_objection(this, {get_type_name(), " done"});
  endtask

endclass : dtp_sanity_test
