// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// Reusable JTAG operation: a raw TMS/TDI walk of one TCK cycle per element
// (one VIP OCAH_JTAG_RAW_TMS item) from any TAP state; a single step is a
// one-element walk. tdo_bits returns the TDO sampled in each cycle. Started
// by dtp_base_test_seq::step(), raw_walk() and raw_walk_tdo(). The cocotb
// realization is dtp_base_test_seq.tms_step, one call per cycle.

class dtp_jtag_tms_walk_seq extends dtp_jtag_op_seq;
  `uvm_object_utils(dtp_jtag_tms_walk_seq)

  bit tms_bits[];
  bit tdi_bits[];
  bit tdo_bits[];

  function new(string name = "dtp_jtag_tms_walk_seq");
    super.new(name);
  endfunction

  virtual task do_op();
    ocah_jtag_item it;
    if (tms_bits.size() == 0) `uvm_fatal(get_type_name(), "empty TMS walk")
    if (tdi_bits.size() != tms_bits.size())
      `uvm_fatal(
          get_type_name(), $sformatf(
          "tdi_bits (%0d) and tms_bits (%0d) differ in length", tdi_bits.size(), tms_bits.size()))
    it = ocah_jtag_item::type_id::create("raw_walk");
    it.op       = OCAH_JTAG_RAW_TMS;
    it.tms_bits = tms_bits;
    it.tdi_bits = tdi_bits;
    do_jtag(it);
    foreach (tms_bits[i]) void'(m_model.step(tms_bits[i]));
    tdo_bits = it.tdo_bits;
  endtask

endclass : dtp_jtag_tms_walk_seq
