// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// SEP OTP JTAG2AXI_CAPS scenario: the 14-bit capability TDR must report
// the bridge geometry the dtp_types table holds, stay stable across
// repeated reads and instruction switches, and ignore write attempts.
// Mirrors the cocotb dtp_dbg_sep_otp_jtag2axi_caps_test_seq.

class dtp_dbg_sep_otp_jtag2axi_caps_test_seq extends dtp_debug_tdr_base_test_seq;
  `uvm_object_utils(dtp_dbg_sep_otp_jtag2axi_caps_test_seq)

  function new(string name = "dtp_dbg_sep_otp_jtag2axi_caps_test_seq");
    super.new(name);
  endfunction

  task body();
    string required[$] = {"CHK-TAP-RESET-TLR", "CHK-CAPS", "CHK-CAPS-RO"};
    seed_scenario_rng();
    attach_family_checker(required);
    reset_to_tlr();
    check_jtag2axi_caps(dtp_j2a_target_sep_otp(), "SEP_OTP_JTAG2AXI_CAPS");
    finalize_family_checker();
  endtask

endclass : dtp_dbg_sep_otp_jtag2axi_caps_test_seq
