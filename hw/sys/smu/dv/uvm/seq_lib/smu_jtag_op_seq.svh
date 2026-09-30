// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// Base of every reusable JTAG operation sequence (smu_jtag_<op>_seq): one
// operation on the embedded DTP's primary TAP agent, built from the VIP
// sequence API, started by a scenario virtual sequence on the virtual
// sequencer's JTAG handle. The VIP sequence tracks the TAP state in its own
// model, so the caller hands in the state it tracks (entry_state) and reads
// current_state() back after start(); body() re-syncs the model and runs
// do_op(). No randomness, no evidence, no TB-interface access: those belong
// to the scenario layer. Mirrors the DTP bench's dtp_jtag_op_seq.

class smu_jtag_op_seq extends ocah_jtag_master_sequence;
  `uvm_object_utils(smu_jtag_op_seq)

  // TAP state the caller tracks before this operation.
  ocah_jtag_tap_state_e entry_state = OCAH_JTAG_TEST_LOGIC_RESET;

  function new(string name = "smu_jtag_op_seq");
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

endclass : smu_jtag_op_seq
