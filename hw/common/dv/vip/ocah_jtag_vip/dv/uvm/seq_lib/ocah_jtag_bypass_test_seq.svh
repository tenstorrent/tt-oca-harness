// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// Scenario sequence for ocah_jtag_bypass_test (the SV-UVM twin of the cocotb
// selftest): random patterns at random widths (the one-bit and 64-bit corners
// pinned) scan through BYPASS and the reference-model prediction emits
// CHK-BYPASS-LATENCY; an unimplemented instruction behaves as BYPASS; every
// IR load and DR scan reconstructs at its driven width.

class ocah_jtag_bypass_test_seq extends ocah_jtag_vip_base_test_seq;
  `uvm_object_utils(ocah_jtag_bypass_test_seq)

  int unsigned n_scans = 8;
  localparam int unsigned MaxWidth = 64;

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

    ir_scan(UnusedOpcode, IrWidth, captured);
    pattern = {$urandom(), $urandom()};
    dr_scan(pattern, MaxWidth, observed);
    expected = ocah_jtag_checker::predict_bypass_tdo(pattern, MaxWidth);
    void'(evidence.expect_equal(
        "CHK-JTAG-UNDEF-AS-BYPASS", observed, expected, $sformatf("ir=0x%02h", UnusedOpcode)
    ));
  endtask
endclass : ocah_jtag_bypass_test_seq
