// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 VNCHIP LABS
//
// Writes one 32-bit CSR with explicit byte enables.
class smc_extreg_csr_strobe_write_seq extends ocah_axi_master_sequence;
  `uvm_object_utils(smc_extreg_csr_strobe_write_seq)
  bit [63:0] addr;
  bit [31:0] data;
  bit [3:0] strb;
  ocah_axi_item result;
  function new(string name = "smc_extreg_csr_strobe_write_seq");
    super.new(name);
  endfunction
  task body();
    write_result(smc_csr_word_addr(addr), smc_csr_to_bus(addr, data), result,
                 .strb(8'(strb) << smc_csr_lane(addr)), .size(SmcCsrSize), .check_response(0),
                 .allow_timeout(1));
  endtask
endclass : smc_extreg_csr_strobe_write_seq
