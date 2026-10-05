// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// Base test: environment construction and the pass-banner contract.
// "UVM TEST PASSED" is emitted only from report_phase and only when the
// global UVM_ERROR/UVM_FATAL counts are both zero (uvm-log parser contract);
// never from sequence or scoreboard code mid-run.

class ocah_axi_vip_base_test extends uvm_test;
  `uvm_component_utils(ocah_axi_vip_base_test)

  ocah_axi_vip_env m_env;

  function new(string name = "ocah_axi_vip_base_test", uvm_component parent = null);
    super.new(name, parent);
  endfunction

  function void build_phase(uvm_phase phase);
    super.build_phase(phase);
    m_env = ocah_axi_vip_env::type_id::create("m_env", this);
  endfunction

  function void report_phase(uvm_phase phase);
    uvm_report_server svr = uvm_report_server::get_server();
    super.report_phase(phase);
    if (svr.get_severity_count(UVM_FATAL) == 0 && svr.get_severity_count(UVM_ERROR) == 0)
      `uvm_info(get_type_name(), "UVM TEST PASSED", UVM_NONE)
    else `uvm_info(get_type_name(), "UVM TEST FAILED", UVM_NONE)
  endfunction

endclass : ocah_axi_vip_base_test
