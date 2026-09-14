// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// Reusable JTAG operation: TRST level control (VIP assert_trst and
// release_trst). Asserting leaves the tracked TAP model in Test-Logic-Reset;
// releasing leaves it unchanged. Started by smu_base_test_seq::set_trst()
// and release_trst(); the scenario layer owns the ref-clock settle wait and
// the evidence.

class smu_jtag_trst_seq extends smu_jtag_op_seq;
  `uvm_object_utils(smu_jtag_trst_seq)

  bit          asserted;
  int unsigned tck_cycles;

  function new(string name = "smu_jtag_trst_seq");
    super.new(name);
  endfunction

  virtual task do_op();
    if (asserted) assert_trst(tck_cycles);
    else release_trst(tck_cycles);
  endtask

endclass : smu_jtag_trst_seq
