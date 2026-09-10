// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// dtp_jtag_zero_length_bypass_test scenario sequence: ZERO_LENGTH_BYPASS
// direct TDI-to-TDO pass-through (CHK-ZLB-PASSTHROUGH) across directed +
// seeded random patterns, plus one plain BYPASS delay reference point
// (CHK-BYPASS-DELAY) proving the zero-length path really skips the one-TCK
// register stage.

class dtp_jtag_zero_length_bypass_test_seq extends dtp_jtag_base_test_seq;
  `uvm_object_utils(dtp_jtag_zero_length_bypass_test_seq)

  function new(string name = "dtp_jtag_zero_length_bypass_test_seq");
    super.new(name);
  endfunction

  task body();
    seed_scenario_rng();
    attach_family_checker({
                          "CHK-TAP-RESET-TLR",
                          "CHK-ZLB-PASSTHROUGH",
                          "CHK-BYPASS-DELAY",
                          "CHK-SCAN-COUNT",
                          "CHK-SCAN-IR-LEN",
                          "CHK-SCAN-DR-LEN",
                          "CHK-NONVAC"
                          });
    reset_to_tlr();
    check_zero_length_bypass_patterns(64);
    check_bypass_delay(BYPASS_INSTR, 64'hA5A5_5A5A_C3C3_3C3C);
    finalize_family_checker();
  endtask

endclass : dtp_jtag_zero_length_bypass_test_seq
