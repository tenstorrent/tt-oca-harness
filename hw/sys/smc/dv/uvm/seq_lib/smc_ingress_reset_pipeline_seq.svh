// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 VNCHIP LABS
//
// Collects a bounded pipeline, including expected timeouts after reset.
class smc_ingress_reset_pipeline_seq extends ocah_axi_master_sequence;
  `uvm_object_utils(smc_ingress_reset_pipeline_seq)
  ocah_axi_item ops[$], result;
  int unsigned hold_cycles;
  bit done;
  function new(string name = "smc_ingress_reset_pipeline_seq");
    super.new(name);
  endfunction
  function void add_access(bit is_write, bit [63:0] addr, bit [63:0] data, bit [15:0] id);
    ocah_axi_item op;
    op = is_write ? pipeline_write(addr, data) : pipeline_read(addr);
    op.transaction_id = id;
    ops.push_back(op);
  endfunction
  task body();
    pipeline_result(ops, result, .b_hold_cycles(hold_cycles), .r_hold_cycles(hold_cycles),
                    .check_response(0), .allow_timeout(1));
    done = 1;
  endtask
endclass : smc_ingress_reset_pipeline_seq
