// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// SMU virtual sequencer: one typed handle per agent sequencer, wired by
// smu_env in connect_phase, and nothing else. Scenario virtual sequences
// (smu_base_test_seq family) run on it and start reusable operation
// sequences on the handle each step needs: primary-TAP JTAG operations on
// m_jtag_seqr, memory backdoor, fault injection and back-pressure of the
// outbound SMN responder on m_axi_out_slave_seq.

class smu_virtual_sequencer extends ocah_sequencer;
  `uvm_component_utils(smu_virtual_sequencer)

  // Primary TAP of the embedded DTP (VIP typedef: uvm_sequencer over
  // ocah_jtag_item).
  ocah_jtag_master_sequencer m_jtag_seqr;

  // Responder handle of the outbound SMN slave agent and its test-facing API:
  // memory backdoor (write_bytes, write32, write64, read_bytes, read32,
  // read64), one-shot response errors (inject_error, pending_errors),
  // back-pressure (enable_backpressure, disable_backpressure) and the
  // write_burst_count / read_burst_count statistics.
  ocah_axi_slave_sequence m_axi_out_slave_seq;

  function new(string name = "smu_virtual_sequencer", uvm_component parent = null);
    super.new(name, parent);
  endfunction

endclass : smu_virtual_sequencer
