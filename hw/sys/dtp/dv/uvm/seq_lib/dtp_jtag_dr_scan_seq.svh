// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// Reusable JTAG operation: one DR scan from Run-Test/Idle back to
// Run-Test/Idle, LSB-first, returning the observed TDO. Up to 64 bits ride
// `pattern`/`width`/`observed` (VIP dr_scan); wider scans ride the bit
// arrays `pattern_bits`/`observed_bits` (VIP dr_scan_wide) whenever
// `pattern_bits` is non-empty. Started by dtp_base_test_seq::dr_scan() and
// dr_scan_wide(). The cocotb realization is dtp_base_test_seq.shift_dr.

class dtp_jtag_dr_scan_seq extends dtp_jtag_op_seq;
  `uvm_object_utils(dtp_jtag_dr_scan_seq)

  bit [63:0]   pattern;
  int unsigned width = 1;
  bit          pattern_bits[];
  // Results.
  bit [63:0]   observed;
  bit          observed_bits[];

  function new(string name = "dtp_jtag_dr_scan_seq");
    super.new(name);
  endfunction

  virtual task do_op();
    if (pattern_bits.size() != 0) begin
      dr_scan_wide(pattern_bits, observed_bits);
      return;
    end
    if (width == 0 || width > 64)
      `uvm_fatal(get_type_name(), $sformatf("DR scan width %0d outside 1..64", width))
    dr_scan(pattern, width, observed);
  endtask

endclass : dtp_jtag_dr_scan_seq
