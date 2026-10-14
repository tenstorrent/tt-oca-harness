// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// Reusable JTAG operation: one TRST level change (VIP assert_trst() or
// release_trst(), a single TRST_LEVEL item), then tck_cycles TCK cycles with
// TMS at `tms`. Asserting leaves the tracked TAP model in Test-Logic-Reset;
// with tck_cycles 0 the operation returns before any TCK edge. Started by
// dtp_base_test_seq::trst_op(); the scenario layer samples the TAP state
// and records the evidence. The cocotb realization makes the same level
// change in DtpJtagDriver's SET_TRST operation.

class dtp_jtag_trst_seq extends dtp_jtag_op_seq;
  `uvm_object_utils(dtp_jtag_trst_seq)

  bit          asserted   = 1'b1;
  int unsigned tck_cycles = 0;
  bit          tms        = 1'b1;

  function new(string name = "dtp_jtag_trst_seq");
    super.new(name);
  endfunction

  virtual task do_op();
    if (asserted) assert_trst(tck_cycles, tms);
    else release_trst(tck_cycles, tms);
  endtask

endclass : dtp_jtag_trst_seq
