// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// Reusable SEP_IN operation: one FULL-WIDTH 64-bit memory read as a
// single-beat AXI4 transfer (AxSIZE = 3), returning the VIP result item and
// the 64-bit word it carries. Started by smc_base_test_seq::mem_read(). The
// cocotb twin is a `length=8` READ of env/smc_sys_axi_agent.py.

class smc_axi_mem_read_seq extends ocah_axi_master_sequence;
  `uvm_object_utils(smc_axi_mem_read_seq)

  bit [63:0] addr;
  bit [2:0]  prot = '0;
  bit        check_response = 1'b1;
  bit        allow_timeout  = 1'b0;
  // Result item and the 64-bit word it carries.
  ocah_axi_item result;
  bit [63:0]    data;

  function new(string name = "smc_axi_mem_read_seq");
    super.new(name);
  endfunction

  task body();
    read_result(smc_mem_word_addr(addr), result, .size(SmcMemSize), .prot(prot),
                .check_response(check_response), .allow_timeout(allow_timeout));
    data = result.first_data();
  endtask

endclass : smc_axi_mem_read_seq
