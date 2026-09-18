// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// Reusable CPU-LSU operation: one 32-bit CSR read as a narrow single-beat
// AXI4 transfer on the CPU-LSU master agent, returning the VIP result item
// and the CSR value extracted from its byte lanes of the 64-bit beat.
// Started by sep_base_test_seq::csr_read(). The cocotb twin is the READ op
// of env/sep_axi_agent.py.

class sep_axi_csr_read_seq extends ocah_axi_master_sequence;
  `uvm_object_utils(sep_axi_csr_read_seq)

  bit [63:0] addr;
  bit [2:0]  prot = '0;
  bit        check_response = 1'b1;
  bit        allow_timeout  = 1'b0;
  // Result item and the CSR word it carries.
  ocah_axi_item result;
  bit [31:0]    data;

  function new(string name = "sep_axi_csr_read_seq");
    super.new(name);
  endfunction

  task body();
    read_result(sep_csr_word_addr(addr), result, .size(SepCsrSize), .prot(prot),
                .check_response(check_response), .allow_timeout(allow_timeout));
    data = sep_csr_from_bus(addr, result.first_data());
  endtask

endclass : sep_axi_csr_read_seq
