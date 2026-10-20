// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 VNCHIP LABS
//
// Counts single-beat SEP_IN requests and responses across one reset epoch.
class smc_ingress_reset_observer extends uvm_object;
  `uvm_object_utils(smc_ingress_reset_observer)
  virtual ocah_axi_if vif;
  virtual smc_tb_if tb_vif;
  bit ready, stop, stopped, reset_seen, phase_valid, sva_disabled, write_cell;
  bit request_idle, held_response;
  int unsigned aw, w, ar, b, r, write_complete, pending_read;
  int unsigned orphan_b, orphan_r, shape_errors, stale_b, stale_r;
  int unsigned b_valid_with_pending, r_valid_with_pending, held_valid, abandoned;
  string phase_context;

  function new(string name = "smc_ingress_reset_observer");
    super.new(name);
  endfunction

  function int unsigned pending_write();
    int unsigned accepted = aw < w ? aw : w;
    return accepted > write_complete ? accepted - write_complete : 0;
  endfunction

  function void clear_counts();
    aw = 0;
    w = 0;
    ar = 0;
    b = 0;
    r = 0;
    write_complete = 0;
    pending_read = 0;
  endfunction

  protected function void reset_epoch();
    phase_context = $sformatf(
        "request_idle=%0b held_response=%0b aw=%0d w=%0d ar=%0d b=%0d r=%0d held_valid=%0d",
        request_idle, held_response, aw, w, ar, b, r, held_valid);
    phase_valid = request_idle && held_response && b == 0 && r == 0 &&
        (write_cell ? aw == 2 && w == 2 && ar == 0 : ar == 2 && aw == 0 && w == 0);
    abandoned = pending_write() + pending_read;
    clear_counts();
    reset_seen = 1;
  endfunction

  function string counters_context();
    return $sformatf(
        {
          "aw=%0d w=%0d ar=%0d b=%0d r=%0d pending_write=%0d pending_read=%0d ",
          "b_valid_with_pending=%0d r_valid_with_pending=%0d ",
          "stale_b=%0d stale_r=%0d orphan_b=%0d orphan_r=%0d shape_errors=%0d"
        },
        aw,
        w,
        ar,
        b,
        r,
        pending_write(),
        pending_read,
        b_valid_with_pending,
        r_valid_with_pending,
        stale_b,
        stale_r,
        orphan_b,
        orphan_r,
        shape_errors
    );
  endfunction

  protected task sample_path();
    forever begin
      @(vif.mon_cb);
      if (tb_vif.axi_sva_en !== 1'b1) sva_disabled = 1;
      if (vif.aresetn !== 1'b1) continue;
      request_idle = vif.mon_cb.awvalid === 1'b0 && vif.mon_cb.wvalid === 1'b0 &&
          vif.mon_cb.arvalid === 1'b0;
      held_response = write_cell ?
          vif.mon_cb.bvalid === 1'b1 && vif.mon_cb.bready === 1'b0 :
          vif.mon_cb.rvalid === 1'b1 && vif.mon_cb.rready === 1'b0;
      if (!reset_seen && held_response) held_valid++;
      if (reset_seen && vif.mon_cb.bvalid === 1'b1) begin
        if (pending_write() == 0) stale_b++;
        else b_valid_with_pending++;
      end
      if (reset_seen && vif.mon_cb.rvalid === 1'b1) begin
        if (pending_read == 0) stale_r++;
        else r_valid_with_pending++;
      end
      // Responses use only requests accepted before this sample.
      if (vif.mon_cb.bvalid === 1'b1 && vif.mon_cb.bready === 1'b1) begin
        b++;
        if (pending_write() == 0) orphan_b++;
        else write_complete++;
      end
      if (vif.mon_cb.rvalid === 1'b1 && vif.mon_cb.rready === 1'b1) begin
        r++;
        if (pending_read == 0) orphan_r++;
        else pending_read--;
        if (vif.mon_cb.rlast !== 1'b1) shape_errors++;
      end
      if (vif.mon_cb.awvalid === 1'b1 && vif.mon_cb.awready === 1'b1) begin
        aw++;
        if (vif.mon_cb.awlen !== 0) shape_errors++;
      end
      if (vif.mon_cb.wvalid === 1'b1 && vif.mon_cb.wready === 1'b1) begin
        w++;
        if (vif.mon_cb.wlast !== 1'b1) shape_errors++;
      end
      if (vif.mon_cb.arvalid === 1'b1 && vif.mon_cb.arready === 1'b1) begin
        ar++;
        pending_read++;
        if (vif.mon_cb.arlen !== 0) shape_errors++;
      end
    end
  endtask

  task watch();
    ready = 1;
    fork
      sample_path();
      begin
        @(negedge vif.aresetn);
        reset_epoch();
      end
      wait (stop);
    join_any
    if (!stop) wait (stop);
    disable fork;
    stopped = 1;
  endtask
endclass : smc_ingress_reset_observer
