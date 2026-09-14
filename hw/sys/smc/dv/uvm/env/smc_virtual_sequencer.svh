// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// SMC virtual sequencer: one typed handle per agent sequencer, wired by
// smc_env in connect_phase, and nothing else. Scenario virtual sequences
// (smc_base_test_seq family) run on it and start reusable operation
// sequences on the handle each step needs: SEP_IN CSR accesses on
// m_sep_in_seqr, backdoor memory access and fault programming of the
// SYS_OUT responder on m_sys_out_slave_seq.

class smc_virtual_sequencer extends ocah_sequencer;
  `uvm_component_utils(smc_virtual_sequencer)

  // SEP_IN AXI4 initiator (VIP typedef: uvm_sequencer over ocah_axi_item).
  ocah_axi_master_sequencer m_sep_in_seqr;

  // Responder sequence of the SYS_OUT slave agent (VIP slave sequence API:
  // write32/read32/write_bytes, inject_error, enable_backpressure).
  ocah_axi_slave_sequence m_sys_out_slave_seq;

  function new(string name = "smc_virtual_sequencer", uvm_component parent = null);
    super.new(name, parent);
  endfunction

endclass : smc_virtual_sequencer
