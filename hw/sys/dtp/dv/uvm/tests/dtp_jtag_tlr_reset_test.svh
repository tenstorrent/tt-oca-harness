// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// dtp_jtag_tlr_reset_test — TMS-high walk to Test-Logic-Reset
// (`--items dtp_jtag_tlr_reset_test`): runs dtp_jtag_tlr_reset_test_seq at
// the looped floor, each pass proving 5+ consecutive TMS=1 cycles force
// Test-Logic-Reset from distinct start states and that TLR re-selects the
// device-identification register. +DTP_JTAG_TAP_CHECKER_NEGATIVE arms a
// wrong expected IDCODE so the run must FAIL (negative validation).

class dtp_jtag_tlr_reset_test extends dtp_base_test;
  `uvm_component_utils(dtp_jtag_tlr_reset_test)

  function new(string name = "dtp_jtag_tlr_reset_test", uvm_component parent = null);
    super.new(name, parent);
  endfunction

  function void end_of_elaboration_phase(uvm_phase phase);
    super.end_of_elaboration_phase(phase);
    m_env.jtag_require_checks = 1'b1;
    m_env.m_jtag_checker.required_ids.push_back("CHK-TAP-STATE");
    m_env.m_jtag_checker.required_ids.push_back("CHK-TAP-RESET-TLR");
  endfunction

  virtual function dtp_jtag_base_test_seq create_scenario_seq();
    return dtp_jtag_tlr_reset_test_seq::type_id::create("jtag_tlr_reset_seq");
  endfunction

  virtual function string specific_loops_plusarg();
    return "DTP_JTAG_TLR_RESET_TEST_LOOPS";
  endfunction

  virtual function string group_loops_plusarg();
    return "DTP_BASIC_JTAG_TEST_LOOPS";
  endfunction

endclass : dtp_jtag_tlr_reset_test
