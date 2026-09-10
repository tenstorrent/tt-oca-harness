// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// SEP virtual sequencer: one typed handle per agent sequencer, wired by
// sep_env in connect_phase, and nothing else. Scenario virtual sequences
// (sep_base_test_seq family) run on it and start reusable operation
// sequences on the handle each step needs: CPU-LSU CSR accesses on
// m_lsu_seqr. Further initiators (the SMN-inbound external master, the
// SEP-OTP JTAG AXI-Lite master) add a handle here with their agents.

class sep_virtual_sequencer extends ocah_sequencer;
  `uvm_component_utils(sep_virtual_sequencer)

  // CPU-LSU AXI4 initiator (VIP typedef: uvm_sequencer over ocah_axi_item).
  ocah_axi_master_sequencer m_lsu_seqr;

  function new(string name = "sep_virtual_sequencer", uvm_component parent = null);
    super.new(name, parent);
  endfunction

endclass : sep_virtual_sequencer
