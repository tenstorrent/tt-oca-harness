// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// Reusable SEP_IN operation: one 32-bit CSR read as a narrow single-beat
// AXI4 transfer on the SEP_IN master agent, returning the VIP result item
// and the CSR value extracted from its byte lanes of the 64-bit beat.
// Started by smc_base_test_seq::csr_read(). The cocotb twin is the READ op
// of env/smc_sys_axi_agent.py.

class smc_axi_csr_read_seq extends ocah_axi_master_sequence;
  `uvm_object_utils(smc_axi_csr_read_seq)

  bit [63:0] addr;
  bit [2:0]  prot = '0;
  bit        check_response = 1'b1;
  bit        allow_timeout  = 1'b0;
  // Result item and the CSR word it carries.
  ocah_axi_item result;
  bit [31:0]    data;

  function new(string name = "smc_axi_csr_read_seq");
    super.new(name);
  endfunction

  task body();
    bit [31:0] data_xz_mask;
    read_result(smc_csr_word_addr(addr), result, .size(SmcCsrSize), .prot(prot),
                .check_response(check_response), .allow_timeout(allow_timeout));
    // Inactive bus lanes do not contribute to the narrow CSR value.
    data_xz_mask = smc_csr_from_bus(addr, result.first_xz_mask());
    if (!result.timed_out &&
        (result.data_words.size() != 1 || result.data_xz_masks.size() != 1 ||
         data_xz_mask != 0))
      `uvm_error("SMC-CSR-READ-XZ", $sformatf(
                 "read addr=0x%0h data_beats=%0d mask_beats=%0d csr_xz_mask=0x%08h",
                 addr,
                 result.data_words.size(),
                 result.data_xz_masks.size(),
                 data_xz_mask
                 ))
    data = smc_csr_from_bus(addr, result.first_data());
  endtask

endclass : smc_axi_csr_read_seq
