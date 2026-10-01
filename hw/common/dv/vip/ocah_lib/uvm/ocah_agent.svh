// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// Agent base for the DUT-local agent a one-consumer protocol gets: the same
// item, sequencer, driver, monitor structure as a shared VIP agent, so the
// day the protocol gains a second consumer the agent moves to the VIP root
// unchanged. The cocotb twin is ocah_lib.OcahAgent.

class ocah_agent extends uvm_agent;
  `uvm_component_utils(ocah_agent)

  function new(string name = "ocah_agent", uvm_component parent = null);
    super.new(name, parent);
  endfunction

endclass : ocah_agent
