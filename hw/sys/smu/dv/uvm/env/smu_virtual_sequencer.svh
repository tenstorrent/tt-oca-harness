// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// SMU virtual sequencer: one typed handle per agent sequencer, wired by
// smu_env in connect_phase, and nothing else. Scenario virtual sequences
// (smu_base_test_seq family) run on it and start reusable operation
// sequences on the handle each step needs: primary-TAP JTAG operations on
// m_jtag_seqr, backdoor memory access and fault programming of the outbound
// SMN responder on m_axi_out_slave_seq.

class smu_virtual_sequencer extends ocah_sequencer;
  `uvm_component_utils(smu_virtual_sequencer)

  // Primary TAP of the embedded DTP (VIP typedef: uvm_sequencer over
  // ocah_jtag_item).
  ocah_jtag_master_sequencer m_jtag_seqr;

  // Responder sequence of the outbound SMN slave agent (VIP slave sequence
  // API: write32/read32/write_bytes, inject_error, enable_backpressure).
  ocah_axi_slave_sequence m_axi_out_slave_seq;

  function new(string name = "smu_virtual_sequencer", uvm_component parent = null);
    super.new(name, parent);
  endfunction

endclass : smu_virtual_sequencer
