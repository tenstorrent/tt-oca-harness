// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// Reusable JTAG operation: navigate the TAP from the tracked state to a
// target state along the shortest TMS path (VIP goto_state, TDI = 0); a
// no-op when already there. Started by dtp_base_test_seq::goto_state(). The
// cocotb realization is dtp_jtag_base_test_seq.goto_tap_state.

class dtp_jtag_goto_state_seq extends dtp_jtag_op_seq;
  `uvm_object_utils(dtp_jtag_goto_state_seq)

  ocah_jtag_tap_state_e target_state = OCAH_JTAG_RUN_TEST_IDLE;

  function new(string name = "dtp_jtag_goto_state_seq");
    super.new(name);
  endfunction

  virtual task do_op();
    goto_state(target_state);
  endtask

endclass : dtp_jtag_goto_state_seq
