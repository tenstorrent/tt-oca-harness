// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// Boundary-scan-disabled scenario. The DUT is elaborated with its
// boundary-scan instructions disabled (DTP_BSR_DISABLED). JTAG_CAPS reports
// the four boundary-scan enables clear, and SAMPLE/PRELOAD, EXTEST,
// EXTEST_TRAIN, EXTEST_PULSE, and INTEST each behave as BYPASS at the
// boundary-scan host port and on TDO ("Boundary Scan Support", PTAP document):
// the instruction decodes as itself, its DR scan leaves the boundary-scan
// select low while the TAP's strobes pulse, and the scan returns TDI one TCK
// late behind a leading 0. tb_top ties the boundary-scan return to its output,
// which returns TDI through no register, so a scan that holds TDI at 0 into
// Shift-DR sees the same TDO on both paths. A scan that holds TDI at 1 into
// Shift-DR tells them apart: the bypass register's captured 0 leads its TDO,
// where the return would lead with 1. Mirrors the cocotb
// dtp_jtag_bsr_disabled_test_seq.

class dtp_jtag_bsr_disabled_test_seq extends dtp_debug_tdr_base_test_seq;
  `uvm_object_utils(dtp_jtag_bsr_disabled_test_seq)

  // The boundary-scan enables, JTAG_CAPS bits 8 to 11: bsr_en,
  // extest_train_en, extest_pulse_en, intest_en.
  localparam int unsigned BsrCapsLsb = 8;
  localparam int unsigned BsrCapsWidth = 4;

  function new(string name = "dtp_jtag_bsr_disabled_test_seq");
    super.new(name);
  endfunction

  task body();
    string required[$] = {"CHK-TAP-RESET-TLR",
                          "CHK-CAPS",
                          "CHK-IR-DECODE",
                          "CHK-BSR-SELECT",
                          "CHK-BSR-SCAN-CTRL",
                          "CHK-BYPASS-DELAY",
                          "CHK-SCAN-COUNT",
                          "CHK-SCAN-IR-LEN",
                          "CHK-SCAN-DR-LEN",
                          "CHK-NONVAC"};
    dtp_jtag_instr_e bsr_instrs[$] = {SAMPLE_PRELOAD_INSTR,
                                      EXTEST_INSTR,
                                      EXTEST_TRAIN_INSTR,
                                      EXTEST_PULSE_INSTR,
                                      INTEST_INSTR};
    string caps_fields[BsrCapsWidth] = '{"bsr_en", "extest_train_en", "extest_pulse_en",
                                         "intest_en"};
    bit [63:0] expected = expected_jtag_caps() & ~(bit_mask(BsrCapsWidth) << BsrCapsLsb);
    bit [63:0] value;
    bit [63:0] patterns[$];
    bit [63:0] pattern;
    bit [63:0] observed;
    seed_scenario_rng();
    attach_family_checker(required);
    reset_to_tlr();

    log_step("1", "JTAG_CAPS reports the boundary-scan enables clear");
    read_caps_tdr(6'(JTAG_CAPS_INSTR), JtagCapsLen, value);
    `uvm_info(get_type_name(), $sformatf("JTAG_CAPS raw=0x%015h", value), UVM_LOW)
    family_check("CHK-CAPS", "JTAG_CAPS", value, expected, "packed value");
    foreach (caps_fields[i])
      family_check("CHK-CAPS", {"JTAG_CAPS.", caps_fields[i]}, (value >> (BsrCapsLsb + i)) & 64'h1,
                   64'h0);

    log_step("2", "Every boundary-scan instruction scans the one-bit bypass register");
    foreach (bsr_instrs[i]) begin
      log_iteration(i + 1, bsr_instrs.size(), bsr_instrs[i].name());
      directed_patterns(DtpBsrModelLen, patterns);
      foreach (patterns[p]) begin
        check_bsr_scan_ctrl(6'(bsr_instrs[i]), patterns[p], DtpBsrModelLen,
                            DTP_SCAN_CTRL_UNSELECTED);
      end
    end

    log_step("3", "A DR scan with TDI high into Shift-DR leads with the bypass register's 0");
    foreach (bsr_instrs[i]) begin
      log_iteration(i + 1, bsr_instrs.size(), bsr_instrs[i].name());
      pattern = random_pattern(DtpBsrModelLen);
      load_ir(6'(bsr_instrs[i]));
      expect_decoded_instruction(bsr_instrs[i]);
      raw_shift_dr(pattern, DtpBsrModelLen, 1'b1, observed);
      check_bypass_tdo(6'(bsr_instrs[i]), observed, pattern, DtpBsrModelLen, 1'b0,
                       "TDI high into Shift-DR");
    end
    finalize_family_checker();
  endtask

endclass : dtp_jtag_bsr_disabled_test_seq
