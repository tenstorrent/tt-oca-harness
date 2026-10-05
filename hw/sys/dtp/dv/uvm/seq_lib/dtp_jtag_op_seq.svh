// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// Base of every reusable JTAG operation sequence (dtp_jtag_<op>_seq): one
// DUT operation on the primary TAP agent, built from the VIP sequence API,
// started by a scenario virtual sequence on the virtual sequencer's JTAG
// handle. The VIP sequence tracks the TAP state in its own model, so the
// caller hands in the state it tracks (entry_state) and reads
// current_state() back after start(); body() re-syncs the model and runs
// do_op(). No randomness, no evidence, no TB-interface access: those belong
// to the scenario layer. The cocotb twin is seq_lib/dtp_jtag_op_seq.py.

class dtp_jtag_op_seq extends ocah_jtag_master_sequence;
  `uvm_object_utils(dtp_jtag_op_seq)

  // TAP state the caller tracks before this operation.
  ocah_jtag_tap_state_e entry_state = OCAH_JTAG_TEST_LOGIC_RESET;

  function new(string name = "dtp_jtag_op_seq");
    super.new(name);
  endfunction

  task body();
    sync_model(entry_state);
    do_op();
  endtask

  // The one operation this sequence performs.
  virtual task do_op();
    `uvm_fatal(get_type_name(), "do_op() not implemented")
  endtask

endclass : dtp_jtag_op_seq
