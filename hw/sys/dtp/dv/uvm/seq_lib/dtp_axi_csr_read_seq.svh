// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// Reusable AXI-Lite operation: one single-beat CSR read on the XTRIG master
// agent, returning the VIP result item (data, response, hold stability,
// timeout). A non-zero hold_cycles selects the VIP's RREADY-hold read,
// which also reports whether RDATA/RRESP stayed stable while RREADY was
// low. Started by dtp_xtrig_base_test_seq::csr_read() and csr_read_hold().
// The cocotb twin is seq_lib/dtp_axi_csr_read_seq.py.

class dtp_axi_csr_read_seq extends ocah_axi_master_sequence;
  `uvm_object_utils(dtp_axi_csr_read_seq)

  bit [63:0]   addr;
  int unsigned hold_cycles    = 0;
  bit          check_response = 1'b1;
  bit          allow_timeout  = 1'b0;
  // Result item (first_data() is the CSR word).
  ocah_axi_item result;

  function new(string name = "dtp_axi_csr_read_seq");
    super.new(name);
  endfunction

  task body();
    if (hold_cycles == 0)
      read_result(addr, result, .check_response(check_response), .allow_timeout(allow_timeout));
    else
      read_hold_result(addr, hold_cycles, result, .check_response(check_response),
                       .allow_timeout(allow_timeout));
  endtask

endclass : dtp_axi_csr_read_seq
