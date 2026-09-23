// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// dtp_jtag_inv_bypass_test scenario sequence: INV_BYPASS one-bit register
// checks — capture bit 1, then the inverted pattern delayed by one TCK
// (CHK-INV-BYPASS) across directed + seeded random patterns, an IDCODE read
// returning the identification (CHK-IDCODE-RAW), plus one plain
// BYPASS delay reference point (CHK-BYPASS-DELAY) proving the inversion is
// specific to INV_BYPASS.

class dtp_jtag_inv_bypass_test_seq extends dtp_jtag_base_test_seq;
  `uvm_object_utils(dtp_jtag_inv_bypass_test_seq)

  function new(string name = "dtp_jtag_inv_bypass_test_seq");
    super.new(name);
  endfunction

  task body();
    bit [63:0] idcode;
    seed_scenario_rng();
    attach_family_checker({
                          "CHK-TAP-RESET-TLR",
                          "CHK-INV-BYPASS",
                          "CHK-BYPASS-DELAY",
                          "CHK-IDCODE-RAW",
                          "CHK-SCAN-COUNT",
                          "CHK-SCAN-IR-LEN",
                          "CHK-SCAN-DR-LEN",
                          "CHK-NONVAC"
                          });
    reset_to_tlr();
    check_inverted_bypass_patterns(64);
    read_idcode(idcode);
    family_check("CHK-IDCODE-RAW", "IDCODE after the inverted-bypass scans", idcode & 64'hFFFF_FFFF,
                 64'(DtpDefaultIdcode), "no TDR side effect");
    check_bypass_delay(BYPASS_INSTR, 64'h0123_4567_89AB_CDEF);
    finalize_family_checker();
  endtask

endclass : dtp_jtag_inv_bypass_test_seq
