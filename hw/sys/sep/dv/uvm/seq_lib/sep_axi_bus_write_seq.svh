// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// Reusable CPU-LSU operation: one single-beat write at any address and size
// with explicit byte strobes, on the CPU-LSU master agent. The data is the
// raw 64-bit bus word (raw-bus-word item semantics of the shared AXI VIP).
// It never escalates the response: the scenario grades the response of the
// returned VIP result item. Started by sep_base_test_seq::bus_write().

class sep_axi_bus_write_seq extends ocah_axi_master_sequence;
  `uvm_object_utils(sep_axi_bus_write_seq)

  bit [63:0] addr;
  bit [63:0] word;
  bit [7:0]  strb = 8'hFF;
  int        size = 3;
  bit [2:0]  prot = '0;
  // Result item (response list, timeout).
  ocah_axi_item result;

  function new(string name = "sep_axi_bus_write_seq");
    super.new(name);
  endfunction

  task body();
    write_result(addr, word, result, .strb(strb), .size(size), .prot(prot), .check_response(1'b0),
                 .allow_timeout(1'b0));
  endtask

endclass : sep_axi_bus_write_seq
