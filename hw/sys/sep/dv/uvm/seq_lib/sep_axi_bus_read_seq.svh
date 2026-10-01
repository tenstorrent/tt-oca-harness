// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// Reusable CPU-LSU operation: one single-beat read at any address and size
// (a memory word, a narrow or misaligned beat) on the CPU-LSU master agent.
// It never escalates the response: the scenario grades the data and the
// response of the returned VIP result item. Started by
// sep_base_test_seq::bus_read().

class sep_axi_bus_read_seq extends ocah_axi_master_sequence;
  `uvm_object_utils(sep_axi_bus_read_seq)

  bit [63:0] addr;
  int        size = SepCsrSize;
  bit [2:0]  prot = '0;
  // Result item (data words, response list, timeout).
  ocah_axi_item result;

  function new(string name = "sep_axi_bus_read_seq");
    super.new(name);
  endfunction

  task body();
    read_result(addr, result, .size(size), .prot(prot), .check_response(1'b0),
                .allow_timeout(1'b0));
  endtask

endclass : sep_axi_bus_read_seq
