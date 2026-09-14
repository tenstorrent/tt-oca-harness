// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// Base test of the harness selftests: builds the environment, binds a
// scenario sequence's handles, and prints the pass/fail banner.

class ocah_jtag_vip_base_test extends uvm_test;
  `uvm_component_utils(ocah_jtag_vip_base_test)

  ocah_jtag_vip_env m_env;

  function new(string name = "ocah_jtag_vip_base_test", uvm_component parent = null);
    super.new(name, parent);
  endfunction

  function void build_phase(uvm_phase phase);
    super.build_phase(phase);
    m_env = ocah_jtag_vip_env::type_id::create("m_env", this);
  endfunction

  // +OCAH_CHECKER_SELFTEST_NEGATIVE arms a required ID no scenario records, so
  // the evidence core's finalization must reject the run (missing=1).
  localparam string CheckerNegativeKnob = "OCAH_CHECKER_SELFTEST_NEGATIVE";
  localparam string NeverRecordedId = "CHK-NEVER-RECORDED";

  protected function void require_ids(string ids[$]);
    m_env.require_checks = 1'b1;
    foreach (ids[i]) m_env.m_checker.required_ids.push_back(ids[i]);
    if (ocah_knobs::is_set(CheckerNegativeKnob)) begin
      `uvm_warning(get_type_name(), {"NEGATIVE VALIDATION: required ID ", NeverRecordedId,
                                     " is never recorded; CHECKER_SUMMARY must report missing=1"})
      m_env.m_checker.required_ids.push_back(NeverRecordedId);
    end
  endfunction

  protected task run_scenario(ocah_jtag_vip_base_test_seq seq, uvm_phase phase);
    phase.raise_objection(this, {get_type_name(), " running"});
    seq.evidence  = m_env.m_checker;
    seq.slave_seq = m_env.m_slave_seq;
    seq.scans     = m_env.m_scan_builder;
    seq.start(m_env.m_master_env.m_sequencer);
    phase.drop_objection(this, {get_type_name(), " done"});
  endtask

  function void report_phase(uvm_phase phase);
    uvm_report_server svr = uvm_report_server::get_server();
    super.report_phase(phase);
    if (svr.get_severity_count(UVM_FATAL) == 0 && svr.get_severity_count(UVM_ERROR) == 0)
      `uvm_info(get_type_name(), "UVM TEST PASSED", UVM_NONE)
    else `uvm_info(get_type_name(), "UVM TEST FAILED", UVM_NONE)
  endfunction
endclass : ocah_jtag_vip_base_test
