// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// Driver base for the DUT-local agent a one-consumer protocol gets. A driver
// is the only class besides a monitor that waits on pin edges, always
// through its cfg's virtual interface and always bounded by a cfg timeout.
// The cocotb twin is ocah_lib.OcahDriver.

class ocah_driver #(
  type REQ = uvm_sequence_item,
  type RSP = REQ
) extends uvm_driver #(REQ, RSP);
  `uvm_component_param_utils(ocah_driver#(REQ, RSP))

  function new(string name = "ocah_driver", uvm_component parent = null);
    super.new(name, parent);
  endfunction

endclass : ocah_driver
