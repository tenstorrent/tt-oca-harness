// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// Reusable AXI-Lite operation: one single-beat CSR read on the XTRIG master
// agent, returning the VIP result item (data, response, hold stability,
// timeout). A non-zero hold_cycles selects the VIP's RREADY-hold read,
// which also reports whether RDATA/RRESP stayed stable while RREADY was
// low. With `pair` set, a second read of pair_addr launches while the
// first response is held (the VIP's two-outstanding read), and pair_result
// carries its item. Started by dtp_xtrig_base_test_seq::csr_read(),
// csr_read_hold(), and read_pair_hold(). In the cocotb realization,
// dtp_xtrig_base_test_seq calls the VIP master sequence's read_result,
// read_hold_result and read_pair_hold_result itself.

class dtp_axi_csr_read_seq extends ocah_axi_master_sequence;
  `uvm_object_utils(dtp_axi_csr_read_seq)

  bit [63:0]   addr;
  int unsigned hold_cycles    = 0;
  bit          check_response = 1'b1;
  bit          allow_timeout  = 1'b0;
  bit          pair = 1'b0;
  bit [63:0]   pair_addr;
  // Result items (first_data() is the CSR word); pair_result is the second
  // read of a pair.
  ocah_axi_item result;
  ocah_axi_item pair_result;

  function new(string name = "dtp_axi_csr_read_seq");
    super.new(name);
  endfunction

  task body();
    if (pair)
      read_pair_hold_result(addr, pair_addr, hold_cycles, result, pair_result,
                            .check_response(check_response), .allow_timeout(allow_timeout));
    else if (hold_cycles == 0)
      read_result(addr, result, .check_response(check_response), .allow_timeout(allow_timeout));
    else
      read_hold_result(addr, hold_cycles, result, .check_response(check_response),
                       .allow_timeout(allow_timeout));
  endtask

endclass : dtp_axi_csr_read_seq
