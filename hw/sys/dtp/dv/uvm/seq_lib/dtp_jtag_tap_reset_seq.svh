// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// Reusable JTAG operation: TAP reset by TRST pulse (VIP tap_reset_op); the
// tracked TAP model ends in Test-Logic-Reset. Started by
// dtp_base_test_seq::tap_reset_op(); the scenario layer records the
// evidence. The cocotb twin is seq_lib/dtp_jtag_tap_reset_seq.py.

class dtp_jtag_tap_reset_seq extends dtp_jtag_op_seq;
  `uvm_object_utils(dtp_jtag_tap_reset_seq)

  function new(string name = "dtp_jtag_tap_reset_seq");
    super.new(name);
  endfunction

  virtual task do_op();
    tap_reset_op();
  endtask

endclass : dtp_jtag_tap_reset_seq
