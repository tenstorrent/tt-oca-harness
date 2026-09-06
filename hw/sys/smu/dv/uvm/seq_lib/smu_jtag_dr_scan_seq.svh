// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// Reusable JTAG operation: one DR scan of up to 64 bits from Run-Test/Idle
// back to Run-Test/Idle, LSB-first (VIP dr_scan), returning the observed
// TDO. Started by smu_base_test_seq::dr_scan().

class smu_jtag_dr_scan_seq extends smu_jtag_op_seq;
  `uvm_object_utils(smu_jtag_dr_scan_seq)

  bit [63:0]   pattern;
  int unsigned width = 1;
  // Result: TDO observed during the scan.
  bit [63:0]   observed;

  function new(string name = "smu_jtag_dr_scan_seq");
    super.new(name);
  endfunction

  virtual task do_op();
    if (width == 0 || width > 64)
      `uvm_fatal(get_type_name(), $sformatf("DR scan width %0d outside 1..64", width))
    dr_scan(pattern, width, observed);
  endtask

endclass : smu_jtag_dr_scan_seq
