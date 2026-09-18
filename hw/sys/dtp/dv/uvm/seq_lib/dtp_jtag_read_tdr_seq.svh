// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// Reusable JTAG operation: read a PTAP test data register by instruction:
// a plain 6-bit IR load followed by a DR scan of `width` bits shifting
// `shift_value` in (zero by default, which catches unwanted R/W side
// effects), returning the masked capture. Started by
// dtp_base_test_seq::read_tdr(). The cocotb twin is
// seq_lib/dtp_jtag_read_tdr_seq.py.

class dtp_jtag_read_tdr_seq extends dtp_jtag_op_seq;
  `uvm_object_utils(dtp_jtag_read_tdr_seq)

  bit [DtpIrWidth-1:0] instr;
  int unsigned         width = 1;
  bit [63:0]           shift_value = '0;
  // Result: captured register value masked to `width`.
  bit [63:0]           value;

  function new(string name = "dtp_jtag_read_tdr_seq");
    super.new(name);
  endfunction

  virtual task do_op();
    bit [63:0] ir_captured;
    if (width == 0 || width > 64)
      `uvm_fatal(get_type_name(), $sformatf("TDR width %0d outside 1..64", width))
    ir_scan(64'(instr), DtpIrWidth, ir_captured);
    dr_scan(shift_value & ocah_rng::bit_mask(width), width, value);
    value &= ocah_rng::bit_mask(width);
  endtask

endclass : dtp_jtag_read_tdr_seq
