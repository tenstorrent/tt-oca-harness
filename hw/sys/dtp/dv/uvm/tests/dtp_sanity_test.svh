// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// dtp_sanity_test — runs dtp_sanity_test_seq on the shared ocah_jtag_vip
// agent's sequencer and asserts full FSM state/edge closure within every
// pass via the env checker (CHK-TAP-VISIT-ALL, this scenario's closure
// obligation — the per-cycle legality check is always on). Also arms the
// JTAG TAP-contract named evidence: the required CHK-* IDs below finalize
// through env.m_jtag_checker in check_phase, and the sequence's family
// checker requires CHK-TAP-GOTO and CHK-IR-DECODE in every pass.

class dtp_sanity_test extends dtp_base_test;
  `uvm_component_utils(dtp_sanity_test)

  function new(string name = "dtp_sanity_test", uvm_component parent = null);
    super.new(name, parent);
  endfunction

  virtual function void configure_test_cfg(dtp_test_cfg cfg);
    super.configure_test_cfg(cfg);
    cfg.require_jtag_ids('{"CHK-TAP-STATE", "CHK-TAP-RESET-TLR", "CHK-TAP-TLR-TMS5",
                         "CHK-TAP-VISIT-ALL", "CHK-TAP-TLR-IDCODE", "CHK-IDCODE-RAW",
                         "CHK-IDCODE-STABLE", "CHK-IDCODE-MARKER", "CHK-BYPASS-LATENCY",
                         "CHK-SCAN-IR-LEN", "CHK-SCAN-DR-LEN", "CHK-NONVAC"});
    cfg.require_feature(DtpFeatureBypass);
    cfg.require_feature(DtpFeatureIdcode);
  endfunction

  virtual function ocah_sequence create_scenario_seq();
    return dtp_sanity_test_seq::type_id::create("seq");
  endfunction

  virtual function string specific_loops_knob();
    return "DTP_SANITY_TEST_LOOPS";
  endfunction

  // Closure gate per pass: every TAP state visited and every legal edge
  // taken within the pass (the deterministic walk in each pass guarantees
  // it; the checker proves it). A pass is judged when the next one starts,
  // the last one after the loop.
  virtual function void pre_scenario_pass(int unsigned idx);
    super.pre_scenario_pass(idx);
    if (idx > 0) m_env.m_fsm_checker.check_fsm_closure($sformatf("pass=%0d", idx));
    m_env.m_fsm_checker.clear_closure();
  endfunction

  task run_phase(uvm_phase phase);
    phase.raise_objection(this, {get_type_name(), " running"});
    run_looped_scenario();
    m_env.m_fsm_checker.check_fsm_closure("last pass");
    phase.drop_objection(this, {get_type_name(), " done"});
  endtask

endclass : dtp_sanity_test
