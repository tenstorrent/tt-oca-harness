// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// Reusable JTAG operation: one DR scan of any width from Run-Test/Idle back
// to Run-Test/Idle, LSB-first, as bit arrays (VIP dr_scan_wide), returning
// the observed TDO bits. The IC_RESET TDR of this wrapper is 155 bits, past
// the 64-bit dr_scan. Started by smu_base_test_seq::dr_scan_wide().

class smu_jtag_dr_scan_wide_seq extends smu_jtag_op_seq;
  `uvm_object_utils(smu_jtag_dr_scan_wide_seq)

  bit pattern[];
  // Result: TDO observed during the scan, one bit per shift cycle.
  bit observed[];

  function new(string name = "smu_jtag_dr_scan_wide_seq");
    super.new(name);
  endfunction

  virtual task do_op();
    if (pattern.size() == 0) `uvm_fatal(get_type_name(), "empty wide DR scan")
    dr_scan_wide(pattern, observed);
  endtask

endclass : smu_jtag_dr_scan_wide_seq
