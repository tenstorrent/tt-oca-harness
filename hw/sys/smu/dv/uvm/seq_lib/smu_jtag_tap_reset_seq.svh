// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// Reusable JTAG operation: TAP reset by TRST pulse (VIP tap_reset_op); the
// tracked TAP model ends in Test-Logic-Reset. Started by
// smu_base_test_seq::tap_reset_op(); the scenario layer records the
// evidence.

class smu_jtag_tap_reset_seq extends smu_jtag_op_seq;
  `uvm_object_utils(smu_jtag_tap_reset_seq)

  function new(string name = "smu_jtag_tap_reset_seq");
    super.new(name);
  endfunction

  virtual task do_op();
    tap_reset_op();
  endtask

endclass : smu_jtag_tap_reset_seq
