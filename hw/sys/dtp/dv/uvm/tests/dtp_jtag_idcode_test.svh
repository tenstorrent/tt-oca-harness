// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// dtp_jtag_idcode_test — Smoke VPLAN scenario: looped IDCODE reads with
// deterministic random TAP preconditioning, run through the looped-scenario
// floor with per-pass seeds. The power-on reset each pass drives records
// CHK-RESET-COUNT on the env recorder. Reads per pass come from
// +DTP_IDCODE_READS_PER_LOOP (default 4); the scenario has no group knob
// beyond the suite-wide +DTP_TEST_LOOPS, matching the cocotb smoke entry.

class dtp_jtag_idcode_test extends dtp_base_test;
  `uvm_component_utils(dtp_jtag_idcode_test)

  function new(string name = "dtp_jtag_idcode_test", uvm_component parent = null);
    super.new(name, parent);
  endfunction

  virtual function void configure_test_cfg(dtp_test_cfg cfg);
    super.configure_test_cfg(cfg);
    cfg.require_jtag_ids('{"CHK-RESET-COUNT"});
    cfg.require_feature(DtpFeatureIdcode);
  endfunction

  virtual function ocah_sequence create_scenario_seq();
    return dtp_jtag_idcode_test_seq::type_id::create("seq");
  endfunction

  virtual function string specific_loops_knob();
    return "DTP_JTAG_IDCODE_TEST_LOOPS";
  endfunction

endclass : dtp_jtag_idcode_test
