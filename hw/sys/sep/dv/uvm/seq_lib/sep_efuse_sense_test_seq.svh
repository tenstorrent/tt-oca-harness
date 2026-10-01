// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// SEP eFuse sense scenario sequence, carrying the cocotb
// tests/efuse/sep_efuse_sense_test.py semantics with no AXI access:
//   * the eFuse bank model loads the committed default image at reset
//     (+sep_efuse_hex, from the testlist), and the real OTP sense runs (no
//     +skip_fuse_sense);
//   * wait for sep_fuse_sense_done_o, bounded by
//     test_cfg.fuse_sense_timeout_cycles (20 000 system clocks, the cocotb
//     _MAX_SENSE_CYCLES), then the settle window;
//   * require the shadow probe tb_vif.efuse_shadow and the committed expected
//     shadow (+sep_efuse_shadow_hex) to each hold exactly ShadowWords 32-bit
//     words, the fuse-map size of the eFuse specification;
//   * compare the sensed shadow, word for word, with the expected shadow. The
//     file is produced by cocotb/env/sep_efuse_default_shadow.py from the
//     same preload; this sequence holds no mapping logic. A non-zero expected
//     shadow makes a shadow left at reset fail the compare.
// The sense runs once at bring-up; each later pass compares the held shadow
// again. Evidence: CHK-FUSE-SENSE-DONE and CHK-SENSE.

class sep_efuse_sense_test_seq extends sep_base_test_seq;
  `uvm_object_utils(sep_efuse_sense_test_seq)

  localparam string ChkSense = "CHK-SENSE";

  // Plusarg that names the expected-shadow file.
  localparam string ShadowFileArg = "sep_efuse_shadow_hex";

  // Fuse-map size: hw/sys/sep/doc/otp_fuse_controller.adoc, "The fuse map is
  // exactly 8192 bits with exclusive end address 0x400 (1024 bytes, 256 x
  // 32-bit words)".
  localparam int unsigned WordBits = 32;
  localparam int unsigned ShadowWords = 256;
  localparam int unsigned ShadowBits = ShadowWords * WordBits;
  localparam int unsigned HexDigitsPerWord = WordBits / 4;

  // Mismatched words named in the log before the report stops.
  localparam int unsigned MaxReportedMismatches = 8;

  typedef logic [ShadowBits-1:0] shadow_t;

  function new(string name = "sep_efuse_sense_test_seq");
    super.new(name);
  endfunction

  // Count the data lines and hex digits of the expected-shadow file, outside
  // "//" comment lines and whitespace. The file form is one data line of
  // ShadowWords * HexDigitsPerWord digits. A file that cannot open counts
  // zero lines.
  function void count_file_digits(string path, output int unsigned data_lines,
                                  output int unsigned digits);
    int    fd;
    string line;
    data_lines = 0;
    digits = 0;
    fd = $fopen(path, "r");
    if (fd == 0) return;
    while ($fgets(
        line, fd
    ) > 0) begin
      int unsigned line_digits = 0;
      if (line.len() >= 2 && line.substr(0, 1) == "//") continue;
      foreach (line[i]) if (line[i] inside {["0" : "9"], ["a" : "f"], ["A" : "F"]}) line_digits++;
      if (line_digits > 0) data_lines++;
      digits += line_digits;
    end
    $fclose(fd);
  endfunction

  // Load the expected-shadow file into one ShadowBits-wide word. A missing
  // file leaves X, which the load check reports.
  function shadow_t load_expected_shadow(output string path);
    shadow_t mem[1];
    mem[0] = 'x;
    if (!$value$plusargs({ShadowFileArg, "=%s"}, path))
      `uvm_fatal(get_type_name(), {"+", ShadowFileArg, "=<file> is not set"})
    $readmemh(path, mem);
    return mem[0];
  endfunction

  task body();
    shadow_t     expected;
    shadow_t     sensed;
    string       path;
    int unsigned nonzero_words = 0;
    int unsigned mismatches = 0;
    bit          expected_loaded;
    int unsigned file_lines;
    int unsigned file_digits;

    seed_scenario_rng();
    attach_evidence('{ChkFuseSense, ChkSense});

    expected = load_expected_shadow(path);
    count_file_digits(path, file_lines, file_digits);
    for (int unsigned w = 0; w < ShadowWords; w++)
      if (expected[w*WordBits+:WordBits] !== '0) nonzero_words++;
    `uvm_info(get_type_name(),
              $sformatf("SEP SV-UVM eFuse sense: expected shadow %s (%0d of %0d words non-zero)",
                        path, nonzero_words, ShadowWords), UVM_LOW)

    void'(m_check.expect_true(
        ChkSense, !$test$plusargs("skip_fuse_sense"), "real fuse sense: +skip_fuse_sense is absent"
    ));
    // Word count: the RTL shadow width and the committed file, each against
    // the specification fuse-map size.
    check_evidence(ChkSense, "efuse_shadow_probe_bits", 64'($bits(tb_vif.efuse_shadow)),
                   64'(ShadowBits), $sformatf("= %0d words x %0d bits", ShadowWords, WordBits));
    check_evidence(
        ChkSense, "expected_shadow_file_digits", 64'(file_digits),
        64'(ShadowWords * HexDigitsPerWord), $sformatf(
        "= %0d words x %0d hex digits, %0d data line(s)", ShadowWords, HexDigitsPerWord, file_lines
        ));
    check_evidence(ChkSense, "expected_shadow_file_data_lines", 64'(file_lines), 64'(1));
    expected_loaded = !$isunknown(expected) && nonzero_words > 0;
    void'(m_check.expect_true(
        ChkSense,
        expected_loaded,
        $sformatf(
            "expected shadow loaded: no X, %0d non-zero words", nonzero_words)
    ));

    wait_fuse_sense_done();

    sensed = tb_vif.efuse_shadow;
    for (int unsigned w = 0; w < ShadowWords; w++) begin
      if (sensed[w*WordBits+:WordBits] !== expected[w*WordBits+:WordBits]) begin
        if (mismatches < MaxReportedMismatches)
          `uvm_info(get_type_name(), $sformatf(
                    "shadow word %0d: sensed 0x%08h expected 0x%08h",
                    w,
                    sensed[w*WordBits+:WordBits],
                    expected[w*WordBits+:WordBits]
                    ), UVM_NONE)
        mismatches++;
      end
    end
    check_evidence(ChkSense, "efuse_shadow_mismatched_words", 64'(mismatches), 64'(0), $sformatf(
                   "of %0d words; word0 sensed 0x%08h, word%0d sensed 0x%08h",
                   ShadowWords,
                   sensed[0+:WordBits],
                   ShadowWords - 1,
                   sensed[(ShadowWords-1)*WordBits+:WordBits]
                   ));
    finalize_evidence();
  endtask

endclass : sep_efuse_sense_test_seq
