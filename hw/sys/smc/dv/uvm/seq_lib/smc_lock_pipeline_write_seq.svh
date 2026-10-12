// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 VNCHIP LABS
//
// Drives pipelined writes and observes AW/W/B acceptance and response overlap.

class smc_lock_pipeline_write_seq extends ocah_axi_master_sequence;
  `uvm_object_utils(smc_lock_pipeline_write_seq)

  ocah_axi_item ops[$];
  ocah_axi_item result;
  longint unsigned aw_at[$], w_at[$], b_at[$];
  int unsigned hold_cycles;
  bit complete, overlap;
  int unsigned previous_op, next_op;
  string label;
  protected bit watch_ready, watch_stop;
  protected bit channel_match = 1'b1;

  function new(string name = "smc_lock_pipeline_write_seq");
    super.new(name);
  endfunction

  function void add_write(bit [63:0] addr, bit [31:0] value, bit [3:0] strb = 4'hF,
                          int unsigned size = SmcMemSize);
    bit [63:0] word_addr = size == SmcCsrSize ? smc_csr_word_addr(addr) : smc_mem_word_addr(addr);
    ocah_axi_item item = pipeline_write(
        word_addr, smc_csr_to_bus(addr, value), .strb(8'(strb) << smc_csr_lane(addr))
    );
    item.size = size;
    ops.push_back(item);
  endfunction

  protected task watch();
    ocah_axi_master_config cfg = resolve_cfg();
    longint unsigned cycle;
    watch_ready = 1'b1;
    while (!watch_stop) begin
      @(cfg.vif.mon_cb);
      cycle++;
      if (cfg.vif.mon_cb.awvalid === 1'b1 && cfg.vif.mon_cb.awready === 1'b1) begin
        int unsigned index = aw_at.size();
        if (index < ops.size()) begin
          channel_match &= cfg.vif.mon_cb.awaddr === ops[index].address &&
              cfg.vif.mon_cb.awsize === ops[index].size &&
              cfg.vif.mon_cb.awlen === 0 && cfg.vif.mon_cb.awid === 0;
        end else channel_match = 1'b0;
        aw_at.push_back(cycle);
      end
      if (cfg.vif.mon_cb.wvalid === 1'b1 && cfg.vif.mon_cb.wready === 1'b1) begin
        int unsigned index = w_at.size();
        if (index < ops.size()) begin
          channel_match &= cfg.vif.mon_cb.wdata === ops[index].data_words[0] &&
              cfg.vif.mon_cb.wstrb === ops[index].strobes[0] && cfg.vif.mon_cb.wlast === 1'b1;
        end else channel_match = 1'b0;
        w_at.push_back(cycle);
      end
      if (cfg.vif.mon_cb.bvalid === 1'b1 && cfg.vif.mon_cb.bready === 1'b1) begin
        channel_match &= cfg.vif.mon_cb.bid === 0;
        b_at.push_back(cycle);
      end
    end
  endtask

  task body();
    fork
      watch();
      begin
        wait (watch_ready);
        pipeline_result(ops, result, .b_hold_cycles(hold_cycles));
        watch_stop = 1'b1;
      end
    join
    complete = channel_match && !result.timed_out && aw_at.size() == ops.size() &&
        w_at.size() == ops.size() && b_at.size() == ops.size();
    foreach (ops[i]) begin
      complete &= ops[i].is_ok() && !ops[i].any_resp_xz() && ops[i].id_match() &&
          !ops[i].timed_out && ops[i].resp_list.size() == 1;
      if (i < aw_at.size() && i < w_at.size() && i < b_at.size()) begin
        `uvm_info("PLOCK-PIPELINE",
                  $sformatf(
                      "%s op=%0d addr=0x%0h size=%0d strb=0x%02h AW=%0d W=%0d B=%0d response=%s",
                      label, i, ops[i].address, ops[i].size, ops[i].strobes[0], aw_at[i], w_at[i],
                      b_at[i], ops[i].worst_resp().name()), UVM_LOW)
      end
    end
    if (complete && next_op < ops.size() && previous_op < ops.size())
      overlap = aw_at[next_op] < b_at[previous_op] && w_at[next_op] < b_at[previous_op];
    `uvm_info("PLOCK-PIPELINE", $sformatf(
                                    {"%s previous=%0d next=%0d hold=%0d complete=%0b overlap=%0b ",
                                     "channel_match=%0b AW=%0d W=%0d B=%0d"}, label, previous_op,
                                      next_op, hold_cycles, complete, overlap, channel_match,
                                      aw_at.size(), w_at.size(), b_at.size()), UVM_LOW)
  endtask
endclass : smc_lock_pipeline_write_seq
