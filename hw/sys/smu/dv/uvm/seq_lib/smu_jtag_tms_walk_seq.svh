// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// Reusable JTAG operation: a raw TMS/TDI walk of one TCK cycle per element
// from any TAP state, returning the TDO sampled on every cycle; a single
// step is a one-element walk. Built directly on the VIP raw item so the
// scenario layer can shift a data register cycle by cycle while it checks
// the TAP state observable between the legs (the VIP raw_walk discards
// TDO). Started by smu_base_test_seq::step() and raw_walk().

class smu_jtag_tms_walk_seq extends smu_jtag_op_seq;
  `uvm_object_utils(smu_jtag_tms_walk_seq)

  bit tms_bits[];
  bit tdi_bits[];
  // Result: TDO sampled before each rising edge, one per element.
  bit tdo_bits[];

  function new(string name = "smu_jtag_tms_walk_seq");
    super.new(name);
  endfunction

  virtual task do_op();
    ocah_jtag_item walk;
    if (tms_bits.size() == 0) `uvm_fatal(get_type_name(), "empty TMS walk")
    if (tdi_bits.size() != tms_bits.size())
      `uvm_fatal(
          get_type_name(), $sformatf(
          "tdi_bits (%0d) and tms_bits (%0d) differ in length", tdi_bits.size(), tms_bits.size()))
    walk          = ocah_jtag_item::type_id::create("walk");
    walk.op       = OCAH_JTAG_RAW_TMS;
    walk.tms_bits = tms_bits;
    walk.tdi_bits = tdi_bits;
    do_jtag(walk);
    tdo_bits = walk.tdo_bits;
    foreach (tms_bits[i]) void'(m_model.step(tms_bits[i]));
  endtask

endclass : smu_jtag_tms_walk_seq
