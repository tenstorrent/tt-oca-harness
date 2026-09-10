// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// Monitor base for a DUT-local observation no VIP provides. A monitor
// publishes items or events on a `<stream>_ap` analysis port and never
// checks protocol content; checking lives in the scoreboard, a subscriber,
// or a reference model. The cocotb twin is ocah_lib.OcahMonitor.

class ocah_monitor extends uvm_monitor;
  `uvm_component_utils(ocah_monitor)

  function new(string name = "ocah_monitor", uvm_component parent = null);
    super.new(name, parent);
  endfunction

endclass : ocah_monitor
