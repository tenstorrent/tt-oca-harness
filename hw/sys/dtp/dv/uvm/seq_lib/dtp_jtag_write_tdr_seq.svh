// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// Reusable JTAG operation: write a PTAP test data register by instruction:
// a plain 6-bit IR load followed by a DR scan of `width` bits shifting
// `value` in; the register latches on Update-DR. Started by
// dtp_base_test_seq::write_tdr(). The cocotb twin is
// seq_lib/dtp_jtag_write_tdr_seq.py.

class dtp_jtag_write_tdr_seq extends dtp_jtag_op_seq;
  `uvm_object_utils(dtp_jtag_write_tdr_seq)

  bit [DtpIrWidth-1:0] instr;
  int unsigned         width = 1;
  bit [63:0]           value;
  // Result: the value shifted out while writing (the previous contents).
  bit [63:0]           captured;

  function new(string name = "dtp_jtag_write_tdr_seq");
    super.new(name);
  endfunction

  virtual task do_op();
    bit [63:0] ir_captured;
    if (width == 0 || width > 64)
      `uvm_fatal(get_type_name(), $sformatf("TDR width %0d outside 1..64", width))
    ir_scan(64'(instr), DtpIrWidth, ir_captured);
    dr_scan(value & ocah_rng::bit_mask(width), width, captured);
  endtask

endclass : dtp_jtag_write_tdr_seq
