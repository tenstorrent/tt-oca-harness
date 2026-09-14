// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// Scenario sequence for ocah_jtag_bypass_test (the SV-UVM twin of the cocotb
// selftest): random patterns at random widths (the one-bit and 64-bit corners
// pinned) and one scan wider than 64 bits pass through BYPASS and the
// reference-model prediction emits CHK-BYPASS-LATENCY; every instruction
// outside the device's map behaves as BYPASS; every IR load and DR scan
// reconstructs at its driven width.

class ocah_jtag_bypass_test_seq extends ocah_jtag_vip_base_test_seq;
  `uvm_object_utils(ocah_jtag_bypass_test_seq)

  int unsigned n_scans = 8;
  localparam int unsigned MaxWidth = 64;
  localparam int unsigned WideWidth = 96;
  localparam int unsigned UndefinedWidth = 8;

  function new(string name = "ocah_jtag_bypass_test_seq");
    super.new(name);
  endfunction

  task body();
    bit [63:0] observed, captured, pattern, expected;
    int unsigned width;
    require_handles();
    if (n_scans < 2)
      `uvm_fatal(get_type_name(), $sformatf("n_scans must be >= 2 (width corners); got %0d", n_scans
                 ))

    reset_to_idle();
    for (int unsigned index = 0; index < n_scans; index++) begin
      string ctx;
      case (index)
        0:       width = 1;
        1:       width = MaxWidth;
        default: width = $urandom_range(MaxWidth - 1, 2);
      endcase
      pattern = {$urandom(), $urandom()} & ((width < 64) ? ((64'h1 << width) - 1) : '1);
      ctx     = $sformatf("scan %0d width=%0d", index, width);
      ir_scan(BypassOpcode, IrWidth, captured);
      dr_scan(pattern, width, observed);
      void'(evidence.check_bypass_latency(observed, pattern, width, 1'b0, ctx));
      check_last_scan(1'b1, IrWidth, $sformatf("BYPASS load %0d", index));
      check_last_scan(1'b0, width, ctx);
    end

    wide_scan();
    undefined_instructions();
  endtask

  // A scan wider than 64 bits through BYPASS: bit 0 is the captured 0, every
  // later bit is the previous TDI bit.
  protected task wide_scan();
    bit [63:0] captured;
    bit pattern[], observed[];
    bit match = 1'b1;
    pattern = new[WideWidth];
    foreach (pattern[i]) pattern[i] = bit'($urandom_range(1));
    ir_scan(BypassOpcode, IrWidth, captured);
    dr_scan_wide(pattern, observed);
    foreach (observed[i]) match &= (observed[i] == ((i == 0) ? 1'b0 : pattern[i-1]));
    void'(evidence.expect_true(
        "CHK-BYPASS-LATENCY", match, $sformatf("wide scan width=%0d", WideWidth)
    ));
    check_last_scan(1'b0, WideWidth, "wide scan");
  endtask

  // Every 5-bit instruction the device does not implement decodes as BYPASS.
  protected task undefined_instructions();
    bit [63:0] captured, pattern, observed, expected;
    for (bit [63:0] opcode = 0; opcode < (64'h1 << IrWidth); opcode++) begin
      if (opcode inside {IdcodeOpcode, CtrlOpcode, StatusOpcode, BypassOpcode}) continue;
      ir_scan(opcode, IrWidth, captured);
      pattern = 64'($urandom()) & 64'hFF;
      dr_scan(pattern, UndefinedWidth, observed);
      expected = ocah_jtag_checker::predict_bypass_tdo(pattern, UndefinedWidth);
      void'(evidence.expect_equal(
          "CHK-JTAG-UNDEF-AS-BYPASS", observed, expected, $sformatf("ir=0x%02h", opcode)
      ));
    end
  endtask
endclass : ocah_jtag_bypass_test_seq
