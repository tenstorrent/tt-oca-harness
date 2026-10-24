// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// dtp_jtag_bsr_disabled_test — the boundary-scan instructions on a DUT built
// without boundary scan, with per-pass family evidence (looped runner).

class dtp_jtag_bsr_disabled_test extends dtp_base_test;
  `uvm_component_utils(dtp_jtag_bsr_disabled_test)

  function new(string name = "dtp_jtag_bsr_disabled_test", uvm_component parent = null);
    super.new(name, parent);
  endfunction

  virtual function ocah_sequence create_scenario_seq();
    return dtp_jtag_bsr_disabled_test_seq::type_id::create("seq");
  endfunction

  virtual function string specific_loops_knob();
    return "DTP_JTAG_BSR_DISABLED_TEST_LOOPS";
  endfunction

  virtual function string group_loops_knob();
    return "DTP_BASIC_JTAG_TEST_LOOPS";
  endfunction

endclass : dtp_jtag_bsr_disabled_test
