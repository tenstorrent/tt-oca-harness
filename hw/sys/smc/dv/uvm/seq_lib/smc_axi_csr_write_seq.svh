// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// Reusable SEP_IN operation: one 32-bit CSR write as a narrow single-beat
// AXI4 transfer on the SEP_IN master agent, returning the VIP result item
// (response, timing, timeout). The CSR value is placed on its byte lanes of
// the 64-bit beat with the matching strobes (raw-bus-word item semantics).
// Started by smc_base_test_seq::csr_write(). The cocotb twin is the WRITE
// op of env/smc_sys_axi_agent.py.

class smc_axi_csr_write_seq extends ocah_axi_master_sequence;
  `uvm_object_utils(smc_axi_csr_write_seq)

  bit [63:0] addr;
  bit [31:0] data;
  bit [2:0]  prot = '0;
  bit        check_response = 1'b1;
  bit        allow_timeout  = 1'b0;
  // Result item (response list, timed_out, timing).
  ocah_axi_item result;

  function new(string name = "smc_axi_csr_write_seq");
    super.new(name);
  endfunction

  task body();
    write_result(smc_csr_word_addr(addr), smc_csr_to_bus(addr, data), result,
                 .strb(smc_csr_strb(addr)), .size(SmcCsrSize), .prot(prot),
                 .check_response(check_response), .allow_timeout(allow_timeout));
  endtask

endclass : smc_axi_csr_write_seq
