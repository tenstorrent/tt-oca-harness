// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// dtp_ijtag_dft_test — secure/non-secure DFT SIB access, cross-resource isolation, and
// stored-state preservation across a gate
// (looped runner with per-pass family evidence).

class dtp_ijtag_dft_test extends dtp_base_test;
  `uvm_component_utils(dtp_ijtag_dft_test)

  function new(string name = "dtp_ijtag_dft_test", uvm_component parent = null);
    super.new(name, parent);
  endfunction

  virtual function ocah_sequence create_scenario_seq();
    dtp_ijtag_scan_test_seq seq = dtp_ijtag_scan_test_seq::type_id::create("seq");
    seq.scenario = "dft";
    return seq;
  endfunction

  virtual function string specific_loops_knob();
    return "DTP_IJTAG_DFT_TEST_LOOPS";
  endfunction

  virtual function string group_loops_knob();
    return "DTP_SCAN_TEST_LOOPS";
  endfunction

endclass : dtp_ijtag_dft_test
