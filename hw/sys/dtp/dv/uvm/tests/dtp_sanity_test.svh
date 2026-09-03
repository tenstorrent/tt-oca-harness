// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// dtp_sanity_test — VPLAN 0.1 (`--items dtp_sanity_test`): runs
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

  function void end_of_elaboration_phase(uvm_phase phase);
    super.end_of_elaboration_phase(phase);
    m_env.jtag_require_checks = 1'b1;
    m_env.m_jtag_checker.required_ids.push_back("CHK-TAP-STATE");
    m_env.m_jtag_checker.required_ids.push_back("CHK-TAP-RESET-TLR");
    m_env.m_jtag_checker.required_ids.push_back("CHK-TAP-TLR-TMS5");
    m_env.m_jtag_checker.required_ids.push_back("CHK-TAP-GOTO");
    m_env.m_jtag_checker.required_ids.push_back("CHK-TAP-TLR-IDCODE");
    m_env.m_jtag_checker.required_ids.push_back("CHK-IDCODE-RAW");
    m_env.m_jtag_checker.required_ids.push_back("CHK-IDCODE-STABLE");
    m_env.m_jtag_checker.required_ids.push_back("CHK-IDCODE-MARKER");
    m_env.m_jtag_checker.required_ids.push_back("CHK-BYPASS-LATENCY");
    m_env.m_jtag_checker.required_ids.push_back("CHK-SCAN-IR-LEN");
    m_env.m_jtag_checker.required_ids.push_back("CHK-SCAN-DR-LEN");
    m_env.m_jtag_checker.required_ids.push_back("CHK-NONVAC");
  endfunction

  task run_phase(uvm_phase phase);
    dtp_sanity_test_seq seq;
    phase.raise_objection(this, "dtp_sanity_test running");
    seq = dtp_sanity_test_seq::type_id::create("seq");
    seq.tb_vif       = m_env.tb_vif;
    seq.evidence     = m_env.m_jtag_checker;
    seq.scan_builder = m_env.m_scan_builder;
    seq.start(m_env.m_jtag_env.m_sequencer);
    m_env.m_fsm_checker.check_fsm_closure();
    phase.drop_objection(this, "dtp_sanity_test done");
  endtask

endclass : dtp_sanity_test
