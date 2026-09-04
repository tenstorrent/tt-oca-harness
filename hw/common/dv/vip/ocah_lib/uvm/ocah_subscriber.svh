// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// Subscriber base for an always-on invariant checker on a VIP event or item
// stream (a bench `<dut>_<x>_checker`). The env hands it the shared
// evidence recorder; the subclass errors inline on every violation in
// write() and turns the run's aggregate into one named CHK record in
// report_evidence(), which the env calls once from check_phase. write()
// never blocks. The cocotb twin is ocah_lib.OcahSubscriber.

class ocah_subscriber #(
  type T = uvm_object
) extends uvm_subscriber #(T);
  `uvm_component_param_utils(ocah_subscriber#(T))

  // Shared named-evidence sink, set by the env before run_phase; a null
  // handle leaves only the inline uvm_error path.
  ocah_checker evidence;

  function new(string name = "ocah_subscriber", uvm_component parent = null);
    super.new(name, parent);
  endfunction

  // The stream handler; every concrete checker overrides it. The base
  // accepts and drops, so an unconnected base instance is inert.
  virtual function void write(T t);
  endfunction

  // One aggregate named-evidence record for the whole run; called once by
  // the env's check_phase.
  virtual function void report_evidence();
  endfunction

endclass : ocah_subscriber
