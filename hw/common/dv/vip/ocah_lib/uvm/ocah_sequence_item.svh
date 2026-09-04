// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// Sequence item base for DUT-local agents and monitors: the observation
// timestamp and the evidence context every published item carries, so a
// scoreboard can name the transaction it compared. The cocotb twin is
// ocah_lib.OcahSequenceItem.

class ocah_sequence_item extends uvm_sequence_item;
  `uvm_object_utils(ocah_sequence_item)

  // Simulation time the item was issued or observed.
  time timestamp;
  // Free-form evidence context (`context=` in a CHK line).
  string context_s = "";

  function new(string name = "ocah_sequence_item");
    super.new(name);
  endfunction

  function void do_copy(uvm_object rhs);
    ocah_sequence_item rhs_item;
    super.do_copy(rhs);
    if (!$cast(rhs_item, rhs)) `uvm_fatal(get_type_name(), "do_copy type mismatch")
    timestamp = rhs_item.timestamp;
    context_s = rhs_item.context_s;
  endfunction

  virtual function string convert2string();
    return $sformatf("%s @%0t %s", get_type_name(), timestamp, context_s);
  endfunction

endclass : ocah_sequence_item
