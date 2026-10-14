// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// dtp_ctm_rand_all_source_select_coverage_test — per-source CTM select masks
// with neighbor no-aliasing reads (looped runner with per-pass CHK-XTRIG-*
// evidence).

class dtp_ctm_rand_all_source_select_coverage_test extends dtp_xtrig_base_test;
  `uvm_component_utils(dtp_ctm_rand_all_source_select_coverage_test)

  function new(string name = "dtp_ctm_rand_all_source_select_coverage_test",
               uvm_component parent = null);
    super.new(name, parent);
  endfunction

  virtual function ocah_sequence create_scenario_seq();
    dtp_xtrig_csr_test_seq seq = dtp_xtrig_csr_test_seq::type_id::create("seq");
    seq.scenario = "ctm_all_source_select";
    return seq;
  endfunction

  virtual function string specific_loops_knob();
    return "DTP_CTM_RAND_ALL_SOURCE_SELECT_COVERAGE_TEST_LOOPS";
  endfunction

endclass : dtp_ctm_rand_all_source_select_coverage_test
