// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// Reusable JTAG operation: navigate the TAP from the tracked state to a
// target state along the shortest TMS path (VIP goto_state, TDI = 0); a
// no-op when already there. Started by smu_base_test_seq::goto_state().

class smu_jtag_goto_state_seq extends smu_jtag_op_seq;
  `uvm_object_utils(smu_jtag_goto_state_seq)

  ocah_jtag_tap_state_e target_state = OCAH_JTAG_RUN_TEST_IDLE;

  function new(string name = "smu_jtag_goto_state_seq");
    super.new(name);
  endfunction

  virtual task do_op();
    goto_state(target_state);
  endtask

endclass : smu_jtag_goto_state_seq
