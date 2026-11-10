// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 VNCHIP LABS
//
// One command's declared, predicted or observed byte window, keyed across resets.
class smc_zeroer_range_sample extends uvm_object;
  `uvm_object_utils(smc_zeroer_range_sample)
  int unsigned epoch, command_id, size, phase_index, guard_bytes;
  bit [63:0] destination;
  bit [7:0] bytes_by_addr[bit [63:0]];
  bit response_error;
  function new(string name = "smc_zeroer_range_sample");
    super.new(name);
  endfunction
  function string key();
    return $sformatf("%0d:%0d", epoch, command_id);
  endfunction
endclass : smc_zeroer_range_sample
