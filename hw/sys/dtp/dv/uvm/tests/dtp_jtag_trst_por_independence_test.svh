// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// dtp_jtag_trst_por_independence_test — POR-only TAP reset
// (`--items dtp_jtag_trst_por_independence_test`): runs
// dtp_jtag_trst_por_independence_test_seq at the looped floor, each pass
// proving a power-on reset forces Test-Logic-Reset with TRST_N deasserted
// throughout and that IDCODE reads back after recovery.

class dtp_jtag_trst_por_independence_test extends dtp_base_test;
  `uvm_component_utils(dtp_jtag_trst_por_independence_test)

  function new(string name = "dtp_jtag_trst_por_independence_test", uvm_component parent = null);
    super.new(name, parent);
  endfunction

  function void end_of_elaboration_phase(uvm_phase phase);
    super.end_of_elaboration_phase(phase);
    m_env.jtag_require_checks = 1'b1;
    m_env.m_jtag_checker.required_ids.push_back("CHK-TAP-STATE");
    m_env.m_jtag_checker.required_ids.push_back("CHK-TAP-RESET-TLR");
  endfunction

  virtual function dtp_jtag_base_test_seq create_scenario_seq();
    return
        dtp_jtag_trst_por_independence_test_seq::type_id::create("jtag_trst_por_independence_seq");
  endfunction

  virtual function string specific_loops_plusarg();
    return "DTP_JTAG_TRST_POR_INDEPENDENCE_TEST_LOOPS";
  endfunction

  virtual function string group_loops_plusarg();
    return "DTP_BASIC_JTAG_TEST_LOOPS";
  endfunction

endclass : dtp_jtag_trst_por_independence_test
