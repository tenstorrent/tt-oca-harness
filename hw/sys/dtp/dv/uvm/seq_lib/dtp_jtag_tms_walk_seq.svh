// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// Reusable JTAG operation: a raw TMS/TDI walk of one TCK cycle per element
// (VIP raw_walk) from any TAP state; a single step is a one-element walk.
// Started by dtp_base_test_seq::step() and raw_walk(). The cocotb twin is
// seq_lib/dtp_jtag_tms_walk_seq.py.

class dtp_jtag_tms_walk_seq extends dtp_jtag_op_seq;
  `uvm_object_utils(dtp_jtag_tms_walk_seq)

  bit tms_bits[];
  bit tdi_bits[];

  function new(string name = "dtp_jtag_tms_walk_seq");
    super.new(name);
  endfunction

  virtual task do_op();
    if (tms_bits.size() == 0) `uvm_fatal(get_type_name(), "empty TMS walk")
    if (tdi_bits.size() != tms_bits.size())
      `uvm_fatal(
          get_type_name(), $sformatf(
          "tdi_bits (%0d) and tms_bits (%0d) differ in length", tdi_bits.size(), tms_bits.size()))
    raw_walk(tms_bits, tdi_bits);
  endtask

endclass : dtp_jtag_tms_walk_seq
