// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// Reactive AXI4/AXI4-Lite memory-backed responder driver (device side).
//
// A sparse zero-default
// byte memory answering FIXED/INCR/WRAP single- and multi-beat bursts with
// ID echo, per-beat one-shot error matching and a one-shot missing RLAST
// per read address (via ocah_axi_slave_config), per-channel bounded READY
// backpressure, a one-shot W-before-AW write order, the response USER
// policy, and single-outstanding registered handshakes per
// direction. cfg.protocol
// selects AXI4-Lite (single-beat, no IDs/bursts; the AXI4-only vif fields
// are never sampled).
//
// Wire contract: the driver SAMPLES master-driven signals through mon_cb
// (race-free preponed values, the same view the passive monitor uses) and
// DRIVES the responder-side signals (awready/wready/b*/arready/r*)
// procedurally with NBA — so the TB must wire only the master-driven
// direction into this vif and route the responder-driven signals back to
// the DUT. Reactive: there is no sequencer; tests configure and inspect the
// device through ocah_axi_slave_sequence.

class ocah_axi_slave_driver extends uvm_component;
  `uvm_component_utils(ocah_axi_slave_driver)

  ocah_axi_slave_config cfg;

  // Sparse backing memory: unwritten bytes read as zero.
  protected bit [7:0] m_mem[bit [63:0]];

  // Statistics (completed bursts).
  int unsigned write_bursts;
  int unsigned read_bursts;

  // Reset assertions seen by watch_reset().
  protected int unsigned m_resets;

  function new(string name = "ocah_axi_slave_driver", uvm_component parent = null);
    super.new(name, parent);
  endfunction

  function void build_phase(uvm_phase phase);
    super.build_phase(phase);
    if (cfg == null && !uvm_config_db#(ocah_axi_slave_config)::get(this, "", "slave_cfg", cfg))
      `uvm_fatal(get_type_name(), "ocah_axi_slave_config `slave_cfg` not found")
    if (cfg.vif == null) `uvm_fatal(get_type_name(), "slave cfg.vif is null")
  endfunction

  // ------------------------------------------------------------------
  // Backdoor memory access (test-facing surface is the slave sequence).
  // ------------------------------------------------------------------

  function void mem_write_byte(bit [63:0] addr, bit [7:0] value);
    m_mem[addr%64'(cfg.mem_bytes)] = value;
  endfunction

  function bit [7:0] mem_read_byte(bit [63:0] addr);
    bit [63:0] wrapped = addr % 64'(cfg.mem_bytes);
    return m_mem.exists(wrapped) ? m_mem[wrapped] : 8'h0;
  endfunction

  function void mem_clear();
    m_mem.delete();
  endfunction

  // ------------------------------------------------------------------
  // Reactive pumps.
  // ------------------------------------------------------------------

  task run_phase(uvm_phase phase);
    if (cfg.is_active != UVM_ACTIVE) return;
    drive_idle();
    fork
      watch_reset();
      write_pump();
      read_pump();
    join_none
  endtask

  // BVALID and RVALID go low as ARESETn asserts, not at the next sampled
  // edge (IHI 0022 A3.1.2). A pump compares m_resets with its count at the
  // address handshake, so a reset that ends before the next sampled edge
  // abandons the transfer too.
  protected task watch_reset();
    forever begin
      @(negedge cfg.vif.aresetn);
      m_resets++;
      cfg.vif.bvalid <= 1'b0;
      cfg.vif.rvalid <= 1'b0;
    end
  endtask

  // A reset is asserted, or has been since the pump read `resets`.
  protected function bit reset_since(int unsigned resets);
    return !cfg.vif.aresetn || (m_resets != resets);
  endfunction

  // BUSER (stream 0) or RUSER (stream 1) of the next beat, drawn from the
  // calling pump's process RNG. `epoch` is the randomize_resp_user() call
  // that pump last reseeded from; a later call reseeds it from the seed plus
  // the stream.
  protected function bit [15:0] next_resp_user(int unsigned stream, ref int unsigned epoch);
    process p;
    if (!cfg.resp_user_random()) return '0;
    if (epoch != cfg.resp_user_epoch()) begin
      p = process::self();
      p.srandom(cfg.resp_user_seed() + stream);
      epoch = cfg.resp_user_epoch();
    end
    return 16'($urandom);
  endfunction

  protected function void drive_idle();
    cfg.vif.awready <= 1'b0;
    cfg.vif.wready  <= 1'b0;
    cfg.vif.bid     <= '0;
    cfg.vif.bresp   <= '0;
    cfg.vif.buser   <= '0;
    cfg.vif.bvalid  <= 1'b0;
    cfg.vif.arready <= 1'b0;
    cfg.vif.rid     <= '0;
    cfg.vif.rdata   <= '0;
    cfg.vif.rresp   <= '0;
    cfg.vif.rlast   <= 1'b0;
    cfg.vif.ruser   <= '0;
    cfg.vif.rvalid  <= 1'b0;
  endfunction

  // Next beat address for FIXED/INCR/WRAP (IHI 0022 A3.4.1 arithmetic).
  protected function bit [63:0] next_beat_addr(bit [63:0] cur, bit [63:0] start_addr,
                                               bit [2:0] size, bit [7:0] len, bit [1:0] burst);
    bit [63:0] nxt, transfer, lower_wrap;
    if (burst == 2'(OCAH_AXI_BURST_FIXED)) return cur;
    nxt = cur + (64'h1 << size);
    if (burst == 2'(OCAH_AXI_BURST_WRAP)) begin
      transfer   = (64'(len) + 64'h1) << size;
      lower_wrap = (start_addr / transfer) * transfer;
      if (nxt == lower_wrap + transfer) nxt = lower_wrap;
    end
    return nxt;
  endfunction

  // Channel accept tasks: complete exactly one handshake on the channel,
  // honoring the per-channel bounded READY-stall pattern (cfg.*_stall_cycles
  // nonzero = READY low for N sampled edges, high for one, repeating until
  // the handshake lands — so a pending VALID completes within N+1 cycles).
  // Stall 0 keeps the assert-and-hold behavior. The knob is re-evaluated
  // every sampled edge, so a stall enabled while the responder is already
  // parked waiting for VALID still takes effect before the next handshake,
  // and a stall disabled mid-pattern releases READY on the next edge (the
  // cocotb pause generators likewise apply immediately).
  // All three return at the handshake edge (mon_cb holds that beat's
  // sampled values) or on reset deassertion — callers re-check aresetn.

  protected task accept_aw();
    forever begin
      if (cfg.aw_stall_cycles == 0) begin
        cfg.vif.awready <= 1'b1;
        @(cfg.vif.mon_cb);
        if (!cfg.vif.aresetn) begin
          cfg.vif.awready <= 1'b0;
          return;
        end
        if (cfg.vif.mon_cb.awvalid && cfg.vif.mon_cb.awready) begin
          cfg.vif.awready <= 1'b0;
          return;
        end
      end else begin
        cfg.vif.awready <= 1'b0;
        for (int unsigned n = 0; n < cfg.aw_stall_cycles; n++) begin
          @(cfg.vif.mon_cb);
          if (!cfg.vif.aresetn) return;
        end
        cfg.vif.awready <= 1'b1;
        @(cfg.vif.mon_cb);
        cfg.vif.awready <= 1'b0;
        if (!cfg.vif.aresetn) return;
        if (cfg.vif.mon_cb.awvalid && cfg.vif.mon_cb.awready) return;
      end
    end
  endtask

  protected task accept_ar();
    forever begin
      if (cfg.ar_stall_cycles == 0) begin
        cfg.vif.arready <= 1'b1;
        @(cfg.vif.mon_cb);
        if (!cfg.vif.aresetn) begin
          cfg.vif.arready <= 1'b0;
          return;
        end
        if (cfg.vif.mon_cb.arvalid && cfg.vif.mon_cb.arready) begin
          cfg.vif.arready <= 1'b0;
          return;
        end
      end else begin
        cfg.vif.arready <= 1'b0;
        for (int unsigned n = 0; n < cfg.ar_stall_cycles; n++) begin
          @(cfg.vif.mon_cb);
          if (!cfg.vif.aresetn) return;
        end
        cfg.vif.arready <= 1'b1;
        @(cfg.vif.mon_cb);
        cfg.vif.arready <= 1'b0;
        if (!cfg.vif.aresetn) return;
        if (cfg.vif.mon_cb.arvalid && cfg.vif.mon_cb.arready) return;
      end
    end
  endtask

  // One W beat. With stall 0, WREADY stays asserted across beats (the
  // caller lowers it after the last beat); with a stall pattern, each
  // beat gets its own low-for-N / high-for-one window.
  protected task accept_w();
    forever begin
      if (cfg.w_stall_cycles == 0) begin
        cfg.vif.wready <= 1'b1;
        @(cfg.vif.mon_cb);
        if (!cfg.vif.aresetn) return;
        if (cfg.vif.mon_cb.wvalid && cfg.vif.mon_cb.wready) return;
      end else begin
        cfg.vif.wready <= 1'b0;
        for (int unsigned n = 0; n < cfg.w_stall_cycles; n++) begin
          @(cfg.vif.mon_cb);
          if (!cfg.vif.aresetn) return;
        end
        cfg.vif.wready <= 1'b1;
        @(cfg.vif.mon_cb);
        if (!cfg.vif.aresetn) return;
        if (cfg.vif.mon_cb.wvalid && cfg.vif.mon_cb.wready) return;
      end
    end
  endtask

  protected task write_pump();
    bit [63:0] addr, start_addr, wdata, unused_rdata;
    bit [15:0] id, bid_out, corrupt_mask;
    bit [7:0] len, wstrb;
    bit [2:0] size;
    bit [1:0] burst;
    ocah_axi_resp_e resp, beat_resp;
    bit armed, w_early, aw_taken, wlast;
    int unsigned beats, lanes, resets, user_epoch;
    forever begin
      @(cfg.vif.mon_cb);
      if (!cfg.vif.aresetn) begin
        cfg.vif.awready <= 1'b0;
        cfg.vif.wready  <= 1'b0;
        cfg.vif.bvalid  <= 1'b0;
        continue;
      end
      // Address phase. With cfg.w_before_aw armed before or during the AW
      // wait, the first data beat is taken alongside it, its fields held
      // from its own handshake edge.
      w_early = cfg.w_before_aw;
      if (!w_early) begin
        aw_taken = 1'b0;
        fork
          begin
            accept_aw();
            take_aw(id, size, len, burst, start_addr);
            aw_taken = 1'b1;
          end
          wait (cfg.w_before_aw);
        join_any
        disable fork;
        w_early = !aw_taken;
        if (w_early) cfg.vif.awready <= 1'b0;
      end
      if (w_early) begin
        cfg.w_before_aw = 1'b0;
        fork
          begin
            accept_aw();
            take_aw(id, size, len, burst, start_addr);
          end
          begin
            accept_w();
            cfg.vif.wready <= 1'b0;
            take_w(wdata, wstrb, wlast);
          end
        join
      end
      if (!cfg.vif.aresetn) continue;
      resets = m_resets;
      addr  = (start_addr >> size) << size;
      beats = int'(len) + 1;
      resp  = OCAH_AXI_RESP_OKAY;
      // Data phase.
      for (int unsigned beat = 0; beat < beats; beat++) begin
        if (!(w_early && beat == 0)) begin
          accept_w();
          if (!cfg.vif.aresetn) break;
          take_w(wdata, wstrb, wlast);
        end
        beat_resp = cfg.consume_injected(addr, OCAH_AXI_DIR_WRITE, armed, unused_rdata);
        if (armed) begin
          if (beat_resp > resp) resp = beat_resp;
        end else begin
          lanes = cfg.beat_bytes();
          for (int unsigned lane = 0; lane < lanes; lane++) begin
            if (wstrb[lane]) mem_write_byte(cfg.beat_align(addr) + 64'(lane), wdata[8*lane+:8]);
          end
        end
        if (cfg.protocol == OCAH_AXI_PROTO_AXI4 && wlast != (beat == beats - 1))
          `uvm_error(get_type_name(), $sformatf(
                     "%s: WLAST=%0d at beat %0d/%0d", cfg.name_tag, wlast, beat + 1, beats))
        addr = next_beat_addr(addr, start_addr, size, len, burst);
      end
      cfg.vif.wready <= 1'b0;
      if (reset_since(resets)) continue;
      // Response phase. One-shot armed BID corruption answers a wrong
      // response ID (data path and BRESP stay untouched).
      bid_out = id;
      if (cfg.consume_id_corruption(OCAH_AXI_DIR_WRITE, corrupt_mask)) begin
        bid_out = cfg.mask_id(id ^ corrupt_mask);
        `uvm_info(get_type_name(), $sformatf(
                                       "%s: corrupting BID awid=0x%0h -> bid=0x%0h (mask=0x%0h)",
                                       cfg.name_tag, id, bid_out, corrupt_mask), UVM_LOW)
      end
      cfg.vif.bid    <= bid_out;
      cfg.vif.bresp  <= resp;
      cfg.vif.buser  <= next_resp_user(0, user_epoch);
      cfg.vif.bvalid <= 1'b1;
      do
      @(cfg.vif.mon_cb);
      while (cfg.vif.aresetn && m_resets == resets &&
             !(cfg.vif.mon_cb.bvalid && cfg.vif.mon_cb.bready));
      cfg.vif.bvalid <= 1'b0;
      if (reset_since(resets)) continue;
      write_bursts++;
    end
  endtask

  // The AW fields of the handshake on this edge.
  protected function void take_aw(output bit [15:0] id, output bit [2:0] size, output bit [7:0] len,
                                  output bit [1:0] burst, output bit [63:0] start_addr);
    id    = cfg.vif.mon_cb.awid;
    size  = (cfg.protocol == OCAH_AXI_PROTO_AXI4_LITE)
                  ? 3'($clog2(cfg.beat_bytes())) : cfg.vif.mon_cb.awsize;
    len   = (cfg.protocol == OCAH_AXI_PROTO_AXI4_LITE)
                  ? 8'h0 : cfg.vif.mon_cb.awlen;
    burst = (cfg.protocol == OCAH_AXI_PROTO_AXI4_LITE)
                  ? 2'(OCAH_AXI_BURST_INCR) : cfg.vif.mon_cb.awburst;
    start_addr = cfg.vif.mon_cb.awaddr;
  endfunction

  // The W fields of the handshake on this edge.
  protected function void take_w(output bit [63:0] wdata, output bit [7:0] wstrb, output bit wlast);
    wdata = cfg.vif.mon_cb.wdata;
    wstrb = cfg.vif.mon_cb.wstrb;
    wlast = cfg.vif.mon_cb.wlast;
  endfunction

  protected task read_pump();
    bit [63:0] addr, start_addr;
    bit [15:0] id, rid_out, corrupt_mask, ruser;
    bit [7:0]       len;
    bit [2:0]       size;
    bit [1:0]       burst;
    int unsigned beats, resets, user_epoch;
    bit drop_last;
    forever begin
      @(cfg.vif.mon_cb);
      if (!cfg.vif.aresetn) begin
        cfg.vif.arready <= 1'b0;
        cfg.vif.rvalid  <= 1'b0;
        continue;
      end
      // Address phase.
      accept_ar();
      if (!cfg.vif.aresetn) continue;
      resets = m_resets;
      id    = cfg.vif.mon_cb.arid;
      size  = (cfg.protocol == OCAH_AXI_PROTO_AXI4_LITE)
                    ? 3'($clog2(cfg.beat_bytes())) : cfg.vif.mon_cb.arsize;
      len   = (cfg.protocol == OCAH_AXI_PROTO_AXI4_LITE)
                    ? 8'h0 : cfg.vif.mon_cb.arlen;
      burst = (cfg.protocol == OCAH_AXI_PROTO_AXI4_LITE)
                    ? 2'(OCAH_AXI_BURST_INCR) : cfg.vif.mon_cb.arburst;
      start_addr = cfg.vif.mon_cb.araddr;
      addr  = (start_addr >> size) << size;
      beats = int'(len) + 1;
      // One-shot armed RID corruption applies to every beat of this one
      // transaction (data path and RRESP stay untouched).
      rid_out = id;
      if (cfg.consume_id_corruption(OCAH_AXI_DIR_READ, corrupt_mask)) begin
        rid_out = cfg.mask_id(id ^ corrupt_mask);
        `uvm_info(get_type_name(), $sformatf(
                                       "%s: corrupting RID arid=0x%0h -> rid=0x%0h (mask=0x%0h)",
                                       cfg.name_tag, id, rid_out, corrupt_mask), UVM_LOW)
      end
      // An armed missing RLAST keeps the final beat's RLAST low; the pump
      // then idles, so the master waits for a beat that never comes.
      drop_last = cfg.consume_missing_rlast(start_addr);
      // Data phase: one beat per accepted cycle.
      for (int unsigned beat = 0; beat < beats; beat++) begin
        ruser = next_resp_user(1, user_epoch);
        load_read_beat(addr, rid_out, (beat == beats - 1) && !drop_last, ruser);
        cfg.vif.rvalid <= 1'b1;
        do
        @(cfg.vif.mon_cb);
        while (cfg.vif.aresetn && m_resets == resets &&
               !(cfg.vif.mon_cb.rvalid && cfg.vif.mon_cb.rready));
        if (reset_since(resets)) break;
        addr = next_beat_addr(addr, start_addr, size, len, burst);
      end
      cfg.vif.rvalid <= 1'b0;
      if (reset_since(resets)) continue;
      read_bursts++;
    end
  endtask

  protected function void load_read_beat(bit [63:0] addr, bit [15:0] id, bit last, bit [15:0] user);
    ocah_axi_resp_e resp;
    bit             armed;
    bit [63:0]      data;
    resp = cfg.consume_injected(addr, OCAH_AXI_DIR_READ, armed, data);
    if (!armed) begin
      for (int unsigned lane = 0; lane < cfg.beat_bytes(); lane++)
      data[8*lane+:8] = mem_read_byte(cfg.beat_align(addr) + 64'(lane));
    end
    cfg.vif.rid   <= id;
    cfg.vif.rdata <= data;
    cfg.vif.rresp <= armed ? resp : OCAH_AXI_RESP_OKAY;
    cfg.vif.rlast <= last;
    cfg.vif.ruser <= user;
  endfunction

endclass : ocah_axi_slave_driver
