// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// Reusable SEP_IN operation: one FULL-WIDTH 64-bit memory write as a
// single-beat AXI4 transfer (AxSIZE = 3, every byte lane strobed), returning
// the VIP result item (response, timing, timeout). Distinct from
// smc_axi_csr_write_seq, which places a 32-bit CSR on its byte lanes of the
// same 64-bit beat. Started by smc_base_test_seq::mem_write(). The cocotb
// twin is a `length=8` WRITE of env/smc_sys_axi_agent.py.

class smc_axi_mem_write_seq extends ocah_axi_master_sequence;
  `uvm_object_utils(smc_axi_mem_write_seq)

  bit [63:0] addr;
  bit [63:0] data;
  bit [2:0]  prot = '0;
  bit        check_response = 1'b1;
  bit        allow_timeout  = 1'b0;
  // Result item (response list, timed_out, timing).
  ocah_axi_item result;

  function new(string name = "smc_axi_mem_write_seq");
    super.new(name);
  endfunction

  task body();
    write_result(smc_mem_word_addr(addr), data, result, .strb(8'hFF), .size(SmcMemSize),
                 .prot(prot), .check_response(check_response), .allow_timeout(allow_timeout));
  endtask

endclass : smc_axi_mem_write_seq
