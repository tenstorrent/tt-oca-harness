// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// JTAG_CAPS scenario: the 60-bit capability TDR must match the standalone
// OSS DTP elaboration constants (whole value plus every decoded field),
// stay stable across repeated reads, ignore directed and seeded random
// write attempts (read-only), and survive instruction switches. Mirrors
// the cocotb dtp_dbg_jtag_caps_test_seq.

class dtp_dbg_jtag_caps_test_seq extends dtp_debug_tdr_base_test_seq;
  `uvm_object_utils(dtp_dbg_jtag_caps_test_seq)

  function new(string name = "dtp_dbg_jtag_caps_test_seq");
    super.new(name);
  endfunction

  // One decoded-field compare of observed vs expected JTAG_CAPS.
  protected function void check_caps_field(bit [63:0] value, bit [63:0] expected, string name,
                                           int unsigned lsb, int unsigned width);
    family_check("CHK-CAPS", {"JTAG_CAPS.", name}, (value >> lsb) & bit_mask(width),
                 (expected >> lsb) & bit_mask(width));
  endfunction

  task body();
    string required[$] = {"CHK-TAP-RESET-TLR", "CHK-CAPS", "CHK-CAPS-RO"};
    bit [63:0] expected = expected_jtag_caps();
    bit [63:0] value, reread;
    seed_scenario_rng();
    attach_family_checker(required);

    reset_to_tlr();
    read_caps_tdr(6'(JTAG_CAPS_INSTR), JtagCapsLen, value);
    `uvm_info(get_type_name(), $sformatf("JTAG_CAPS raw=0x%015h", value), UVM_LOW)
    family_check("CHK-CAPS", "JTAG_CAPS", value, expected, "packed value");

    // Every decoded field ("JTAG Capabilities" table, PTAP document).
    check_caps_field(value, expected, "num_xtrig_int_ct", 54, 6);
    check_caps_field(value, expected, "num_xtrig_ctp", 48, 6);
    check_caps_field(value, expected, "num_extra_staps", 44, 4);
    check_caps_field(value, expected, "stap_io_en", 43, 1);
    check_caps_field(value, expected, "sep_dbg_en", 42, 1);
    check_caps_field(value, expected, "smc_dbg_en", 41, 1);
    check_caps_field(value, expected, "num_smc_ic_reset", 33, 8);
    check_caps_field(value, expected, "num_sep_ic_reset", 25, 8);
    check_caps_field(value, expected, "num_ext_ic_reset", 17, 8);
    check_caps_field(value, expected, "ic_reset_en", 16, 1);
    check_caps_field(value, expected, "tmp_en", 15, 1);
    check_caps_field(value, expected, "runbist_en", 14, 1);
    check_caps_field(value, expected, "highz_en", 13, 1);
    check_caps_field(value, expected, "clamp_en", 12, 1);
    check_caps_field(value, expected, "intest_en", 11, 1);
    check_caps_field(value, expected, "extest_pulse_en", 10, 1);
    check_caps_field(value, expected, "extest_train_en", 9, 1);
    check_caps_field(value, expected, "bsr_en", 8, 1);
    check_caps_field(value, expected, "och_ver", 0, 8);

    check_caps_multi_read(6'(JTAG_CAPS_INSTR), JtagCapsLen, value, "JTAG_CAPS");
    check_caps_read_only_patterns(6'(JTAG_CAPS_INSTR), JtagCapsLen, value, "JTAG_CAPS");

    // Instruction switches must not disturb the capability value.
    load_ir(6'(IDCODE_INSTR));
    read_caps_tdr(6'(JTAG_CAPS_INSTR), JtagCapsLen, reread);
    family_check("CHK-CAPS", "JTAG_CAPS after IDCODE", reread, value);
    load_ir(6'(BYPASS_INSTR));
    read_caps_tdr(6'(JTAG_CAPS_INSTR), JtagCapsLen, reread);
    family_check("CHK-CAPS", "JTAG_CAPS after BYPASS", reread, value);

    finalize_family_checker();
  endtask

endclass : dtp_dbg_jtag_caps_test_seq
