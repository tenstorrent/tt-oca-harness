// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// SMC OTP JTAG2AXI_CAPS scenario: the 14-bit capability TDR must report
// the bridge geometry the dtp_types table holds, stay stable across
// repeated reads and instruction switches, and ignore write attempts.
// Mirrors the cocotb dtp_dbg_smc_otp_jtag2axi_caps_test_seq.

class dtp_dbg_smc_otp_jtag2axi_caps_test_seq extends dtp_debug_tdr_base_test_seq;
  `uvm_object_utils(dtp_dbg_smc_otp_jtag2axi_caps_test_seq)

  function new(string name = "dtp_dbg_smc_otp_jtag2axi_caps_test_seq");
    super.new(name);
  endfunction

  task body();
    string required[$] = {"CHK-TAP-RESET-TLR", "CHK-CAPS", "CHK-CAPS-RO"};
    seed_scenario_rng();
    attach_family_checker(required);
    log_step("1", "Reset TAP before reading SMC_OTP_JTAG2AXI_CAPS");
    reset_to_tlr();
    log_step("2", "Run common JTAG2AXI_CAPS checks");
    check_jtag2axi_caps(dtp_j2a_target_smc_otp(), "SMC_OTP_JTAG2AXI_CAPS");
    finalize_family_checker();
  endtask

endclass : dtp_dbg_smc_otp_jtag2axi_caps_test_seq
