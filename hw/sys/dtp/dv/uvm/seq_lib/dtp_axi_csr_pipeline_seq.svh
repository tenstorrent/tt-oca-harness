// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// Reusable AXI-Lite operation: single-beat CSR reads and writes kept in
// flight together on the XTRIG master agent (the VIP's pipeline_result).
// `ops` lists the accesses in issue order as plain data; body() builds each
// through the VIP's pipeline_write / pipeline_read, so the master
// configuration supplies the transfer size and strobes. BREADY and RREADY
// stay low for b_hold_cycles and r_hold_cycles after the first BVALID and
// RVALID. `result` carries the per-channel request stall cycles the VIP
// observed, and op_results[i] the completed item of ops[i]. Response
// checking stays with the caller (check_response = 0), so scenarios that
// expect DECERR judge the response themselves. Started by
// dtp_xtrig_base_test_seq::pipeline_result().

class dtp_axi_csr_pipeline_seq extends ocah_axi_master_sequence;
  `uvm_object_utils(dtp_axi_csr_pipeline_seq)

  // One access. aw/w_valid_delay (writes) and ar_valid_delay (reads) count
  // the cycles from the start of the operation before that channel's VALID
  // may assert for this access; strb is a write's WSTRB.
  typedef struct {
    ocah_axi_dir_e direction;
    bit [63:0]     addr;
    bit [63:0]     data;
    bit [7:0]      strb;
    bit [2:0]      prot;
    int unsigned   aw_valid_delay;
    int unsigned   w_valid_delay;
    int unsigned   ar_valid_delay;
  } op_t;

  op_t         ops[$];
  int unsigned b_hold_cycles  = 0;
  int unsigned r_hold_cycles  = 0;
  bit          check_response = 1'b1;
  bit          allow_timeout  = 1'b0;
  ocah_axi_item result;
  ocah_axi_item op_results[$];

  function new(string name = "dtp_axi_csr_pipeline_seq");
    super.new(name);
  endfunction

  task body();
    ocah_axi_item item;
    ocah_axi_item items[$];
    foreach (ops[i]) begin
      op_t op = ops[i];
      if (op.direction == OCAH_AXI_DIR_WRITE)
        item = pipeline_write(
            op.addr, op.data, op.aw_valid_delay, op.w_valid_delay, op.strb, op.prot
        );
      else item = pipeline_read(op.addr, op.ar_valid_delay, op.prot);
      items.push_back(item);
    end
    pipeline_result(items, result, b_hold_cycles, r_hold_cycles, check_response, allow_timeout);
    op_results = result.ops;
  endtask

endclass : dtp_axi_csr_pipeline_seq
