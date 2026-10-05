// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// SEP virtual sequencer: one typed handle per agent sequencer, wired by
// sep_env in connect_phase, and nothing else. Scenario virtual sequences
// (sep_base_test_seq family) run on it and start reusable operation
// sequences on the handle each step needs: CPU-LSU CSR accesses on
// m_lsu_seqr. An added initiator adds its sequencer handle here. The
// scoreboard handle is read-only: scenarios read its per-feature compare
// count for their non-vacuity evidence and never push items into it.

typedef class sep_scoreboard;

class sep_virtual_sequencer extends ocah_sequencer;
  `uvm_component_utils(sep_virtual_sequencer)

  // CPU-LSU AXI4 initiator (VIP typedef: uvm_sequencer over ocah_axi_item).
  ocah_axi_master_sequencer m_lsu_seqr;
  // Always-on scoreboard (compare counts only).
  sep_scoreboard            m_scoreboard;

  function new(string name = "sep_virtual_sequencer", uvm_component parent = null);
    super.new(name, parent);
  endfunction

endclass : sep_virtual_sequencer
