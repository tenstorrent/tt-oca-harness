// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// Active AXI4/AXI4-Lite master driver (initiator side).
//
// Executes one ocah_axi_item per sequence handshake: writes run the AW and
// W phases concurrently (AXI permits either arrival order; the item's
// aw/w_valid_delay knobs skew their launch) then B, reads run AR -> R beats
// to RLAST; a single transaction is outstanding at a time. The item's
// b_ready_delay defers the BREADY assert, and a nonzero r_ready_delay holds
// RREADY low after RVALID asserts while the driver samples RDATA/RRESP
// stability into hold_stable. cfg.protocol selects AXI4-Lite (single-beat;
// the driver itself ties the AXI4-only request fields to the adapter
// contract values from ocah_axi_if's header).
//
// Wire contract (the initiator mirror of ocah_axi_slave_driver): the driver
// SAMPLES responder-driven signals through mon_cb (race-free preponed
// values, the same view the passive monitor uses) and DRIVES the
// initiator-side signals (aw*/w*/ar* payloads plus awvalid/wvalid/arvalid/
// bready/rready) procedurally with NBA — so the TB wires only the
// responder-driven direction into this vif and routes the initiator-driven
// signals out to the DUT.
//
// Responses are written into the same item object before item_done
// (resp_list, read data_words, and the live-sampled response ID), so the
// issuing sequence reads results directly after finish_item(). observed_id
// is sampled from the B/R handshake on the completing beat (RLAST for
// reads) — wire truth, never a copy of the issued ID (cross-flow parity
// with the cocotb result contract; see MANUAL "Response-ID observation").
// Each handshake wait is bounded by cfg.timeout_cycles; on expiry the item
// completes with timed_out set and the sequence layer decides severity.
// The driver assumes aresetn stays high while an item is in flight (the
// consuming env/test sequences reset before traffic).

class ocah_axi_master_driver extends uvm_driver #(ocah_axi_item);
  `uvm_component_utils(ocah_axi_master_driver)

  ocah_axi_master_config cfg;

  // Statistics (completed bursts).
  int unsigned write_bursts;
  int unsigned read_bursts;
  int unsigned timeout_count;

  function new(string name = "ocah_axi_master_driver", uvm_component parent = null);
    super.new(name, parent);
  endfunction

  function void build_phase(uvm_phase phase);
    super.build_phase(phase);
    if (!uvm_config_db#(ocah_axi_master_config)::get(this, "", "cfg", cfg) || cfg == null)
      `uvm_fatal(get_type_name(), "ocah_axi_master_config `cfg` not found in uvm_config_db")
    if (cfg.vif == null) `uvm_fatal(get_type_name(), "ocah_axi_master_config.vif is null")
  endfunction

  task run_phase(uvm_phase phase);
    drive_idle();
    wait (cfg.vif.aresetn === 1'b1);
    forever begin
      seq_item_port.get_next_item(req);
      `uvm_info(get_type_name(), {"drive ", req.convert2string()}, UVM_HIGH)
      req.source     = get_full_name();
      req.start_time = $time;
      case (req.direction)
        OCAH_AXI_DIR_WRITE: do_write(req);
        OCAH_AXI_DIR_READ: do_read(req);
        default:
        `uvm_error(get_type_name(), $sformatf("unsupported direction %s", req.direction.name()))
      endcase
      req.end_time = $time;
      if (req.timed_out) timeout_count++;
      seq_item_port.item_done();
    end
  endtask

  protected function void drive_idle();
    cfg.vif.awid     <= '0;
    cfg.vif.awaddr   <= '0;
    cfg.vif.awlen    <= '0;
    cfg.vif.awsize   <= '0;
    cfg.vif.awburst  <= '0;
    cfg.vif.awlock   <= '0;
    cfg.vif.awcache  <= '0;
    cfg.vif.awprot   <= '0;
    cfg.vif.awqos    <= '0;
    cfg.vif.awregion <= '0;
    cfg.vif.awuser   <= '0;
    cfg.vif.awvalid  <= 1'b0;
    cfg.vif.wdata    <= '0;
    cfg.vif.wstrb    <= '0;
    cfg.vif.wlast    <= 1'b0;
    cfg.vif.wuser    <= '0;
    cfg.vif.wvalid   <= 1'b0;
    cfg.vif.bready   <= 1'b0;
    cfg.vif.arid     <= '0;
    cfg.vif.araddr   <= '0;
    cfg.vif.arlen    <= '0;
    cfg.vif.arsize   <= '0;
    cfg.vif.arburst  <= '0;
    cfg.vif.arlock   <= '0;
    cfg.vif.arcache  <= '0;
    cfg.vif.arprot   <= '0;
    cfg.vif.arqos    <= '0;
    cfg.vif.arregion <= '0;
    cfg.vif.aruser   <= '0;
    cfg.vif.arvalid  <= 1'b0;
    cfg.vif.rready   <= 1'b0;
  endfunction

  protected function bit [63:0] mask_data(bit [63:0] value);
    return (cfg.data_width >= 64) ? value : (value & ((64'd1 << cfg.data_width) - 1));
  endfunction

  // Live response-ID capture at the completing handshake (parity contract:
  // wire truth, never an issued-ID echo). Stays invalid on ID-less buses.
  protected function void capture_observed_id(ocah_axi_item it, bit [15:0] raw);
    if (cfg.id_width > 0) begin
      it.observed_id       = cfg.mask_id(raw);
      it.observed_id_valid = 1'b1;
    end
  endfunction

  protected function void flag_timeout(ocah_axi_item it, string phase_s);
    it.timed_out = 1'b1;
    `uvm_info(cfg.name_tag, $sformatf(
              "%s handshake timeout after %0d cycles: %s",
              phase_s,
              cfg.timeout_cycles,
              it.convert2string()
              ), UVM_MEDIUM)
  endfunction

  // ------------------------------------------------------------------
  // Sampled-handshake waits, bounded by cfg.timeout_cycles (0 = unbounded);
  // `timed_out` reports watchdog expiry.
  // ------------------------------------------------------------------

  protected task wait_aw(output bit timed_out);
    int unsigned cycles = 0;
    timed_out = 1'b0;
    forever begin
      @(cfg.vif.mon_cb);
      if (cfg.vif.mon_cb.awvalid === 1'b1 && cfg.vif.mon_cb.awready === 1'b1) return;
      cycles++;
      if (cfg.timeout_cycles != 0 && cycles >= cfg.timeout_cycles) begin
        timed_out = 1'b1;
        return;
      end
    end
  endtask

  protected task wait_w(output bit timed_out);
    int unsigned cycles = 0;
    timed_out = 1'b0;
    forever begin
      @(cfg.vif.mon_cb);
      if (cfg.vif.mon_cb.wvalid === 1'b1 && cfg.vif.mon_cb.wready === 1'b1) return;
      cycles++;
      if (cfg.timeout_cycles != 0 && cycles >= cfg.timeout_cycles) begin
        timed_out = 1'b1;
        return;
      end
    end
  endtask

  protected task wait_b(output bit timed_out);
    int unsigned cycles = 0;
    timed_out = 1'b0;
    forever begin
      @(cfg.vif.mon_cb);
      if (cfg.vif.mon_cb.bvalid === 1'b1 && cfg.vif.mon_cb.bready === 1'b1) return;
      cycles++;
      if (cfg.timeout_cycles != 0 && cycles >= cfg.timeout_cycles) begin
        timed_out = 1'b1;
        return;
      end
    end
  endtask

  protected task wait_ar(output bit timed_out);
    int unsigned cycles = 0;
    timed_out = 1'b0;
    forever begin
      @(cfg.vif.mon_cb);
      if (cfg.vif.mon_cb.arvalid === 1'b1 && cfg.vif.mon_cb.arready === 1'b1) return;
      cycles++;
      if (cfg.timeout_cycles != 0 && cycles >= cfg.timeout_cycles) begin
        timed_out = 1'b1;
        return;
      end
    end
  endtask

  protected task wait_r(output bit timed_out);
    int unsigned cycles = 0;
    timed_out = 1'b0;
    forever begin
      @(cfg.vif.mon_cb);
      if (cfg.vif.mon_cb.rvalid === 1'b1 && cfg.vif.mon_cb.rready === 1'b1) return;
      cycles++;
      if (cfg.timeout_cycles != 0 && cycles >= cfg.timeout_cycles) begin
        timed_out = 1'b1;
        return;
      end
    end
  endtask

  // ------------------------------------------------------------------
  // Transaction execution.
  // ------------------------------------------------------------------

  protected task drive_aw(ocah_axi_item it, int unsigned beats);
    cfg.vif.awaddr <= it.address;
    cfg.vif.awprot <= it.prot;
    if (cfg.protocol == OCAH_AXI_PROTO_AXI4_LITE) begin
      // Adapter-contract ties (see ocah_axi_if's header).
      cfg.vif.awid    <= '0;
      cfg.vif.awlen   <= '0;
      cfg.vif.awsize  <= 3'($clog2(cfg.beat_bytes()));
      cfg.vif.awburst <= 2'(OCAH_AXI_BURST_INCR);
    end else begin
      cfg.vif.awid    <= it.transaction_id;
      cfg.vif.awlen   <= 8'(beats - 1);
      cfg.vif.awsize  <= 3'(it.size);
      cfg.vif.awburst <= 2'(it.burst);
    end
    cfg.vif.awvalid <= 1'b1;
  endtask

  protected task drive_ar(ocah_axi_item it, int unsigned beats);
    cfg.vif.araddr <= it.address;
    cfg.vif.arprot <= it.prot;
    if (cfg.protocol == OCAH_AXI_PROTO_AXI4_LITE) begin
      cfg.vif.arid    <= '0;
      cfg.vif.arlen   <= '0;
      cfg.vif.arsize  <= 3'($clog2(cfg.beat_bytes()));
      cfg.vif.arburst <= 2'(OCAH_AXI_BURST_INCR);
    end else begin
      cfg.vif.arid    <= it.transaction_id;
      cfg.vif.arlen   <= 8'(beats - 1);
      cfg.vif.arsize  <= 3'(it.size);
      cfg.vif.arburst <= 2'(it.burst);
    end
    cfg.vif.arvalid <= 1'b1;
  endtask

  virtual task do_write(ocah_axi_item it);
    int unsigned beats = it.data_words.size();
    bit aw_timed_out, w_timed_out;
    bit timed_out;
    it.resp_list.delete();
    if (beats == 0) begin
      `uvm_error(cfg.name_tag, "write item carries no data beats")
      return;
    end
    if (cfg.protocol == OCAH_AXI_PROTO_AXI4_LITE && beats > 1) begin
      `uvm_error(cfg.name_tag,
                 $sformatf("%0d-beat write on an AXI4-Lite master (single-beat protocol)", beats))
      return;
    end
    // Address and data phases run concurrently; each channel's valid
    // delay skews its launch (both zero = simultaneous assert).
    fork
      begin : aw_phase
        repeat (it.aw_valid_delay) @(cfg.vif.mon_cb);
        drive_aw(it, beats);
        wait_aw(aw_timed_out);
        cfg.vif.awvalid <= 1'b0;
      end
      begin : w_phase
        repeat (it.w_valid_delay) @(cfg.vif.mon_cb);
        for (int unsigned beat = 0; beat < beats; beat++) begin
          cfg.vif.wdata  <= it.data_words[beat];
          cfg.vif.wstrb  <= 8'((beat < it.strobes.size()) ? it.strobes[beat] : cfg.full_strb());
          cfg.vif.wlast  <= (cfg.protocol == OCAH_AXI_PROTO_AXI4_LITE) ? 1'b1 : (beat == beats - 1);
          cfg.vif.wvalid <= 1'b1;
          wait_w(w_timed_out);
          if (w_timed_out) break;
        end
        cfg.vif.wvalid <= 1'b0;
      end
    join
    if (aw_timed_out || w_timed_out) begin
      flag_timeout(it, aw_timed_out ? "AW" : "W");
      return;
    end
    // Response phase: b_ready_delay defers the accept, then sample
    // BRESP/BID on the accepted cycle.
    repeat (it.b_ready_delay) @(cfg.vif.mon_cb);
    cfg.vif.bready <= 1'b1;
    wait_b(timed_out);
    cfg.vif.bready <= 1'b0;
    if (timed_out) begin
      flag_timeout(it, "B");
      return;
    end
    it.resp_list.push_back(ocah_axi_resp_e'(cfg.vif.mon_cb.bresp));
    capture_observed_id(it, cfg.vif.mon_cb.bid);
    write_bursts++;
  endtask

  virtual task do_read(ocah_axi_item it);
    int unsigned beats = (it.expected_beats == 0) ? 1 : it.expected_beats;
    bit timed_out;
    bit last;
    it.data_words.delete();
    it.resp_list.delete();
    if (cfg.protocol == OCAH_AXI_PROTO_AXI4_LITE && beats > 1) begin
      `uvm_error(cfg.name_tag,
                 $sformatf("%0d-beat read on an AXI4-Lite master (single-beat protocol)", beats))
      return;
    end
    // Address phase.
    drive_ar(it, beats);
    wait_ar(timed_out);
    cfg.vif.arvalid <= 1'b0;
    if (timed_out) begin
      flag_timeout(it, "AR");
      return;
    end
    // RREADY-hold window: with a nonzero r_ready_delay, wait for RVALID
    // with RREADY still low, then sample RDATA/RRESP stability across the
    // hold — RVALID must stay asserted with unchanged payload until the
    // accept (hold_stable reports it; the deferred handshake below then
    // consumes the beat normally).
    if (it.r_ready_delay > 0) begin
      bit [63:0]   held_data;
      bit [1:0]    held_resp;
      int unsigned cycles = 0;
      forever begin
        @(cfg.vif.mon_cb);
        if (cfg.vif.mon_cb.rvalid === 1'b1) break;
        cycles++;
        if (cfg.timeout_cycles != 0 && cycles >= cfg.timeout_cycles) begin
          flag_timeout(it, "R");
          return;
        end
      end
      held_data      = cfg.vif.mon_cb.rdata;
      held_resp      = cfg.vif.mon_cb.rresp;
      it.hold_stable = 1'b1;
      repeat (it.r_ready_delay) begin
        @(cfg.vif.mon_cb);
        if (cfg.vif.mon_cb.rvalid !== 1'b1 ||
                    cfg.vif.mon_cb.rdata !== held_data ||
                    cfg.vif.mon_cb.rresp !== held_resp)
          it.hold_stable = 1'b0;
      end
    end
    // Data phase: accumulate beats to RLAST (Lite adapters tie rlast=1,
    // but the protocol itself bounds Lite reads to the single beat).
    cfg.vif.rready <= 1'b1;
    last = 1'b0;
    while (!last) begin
      wait_r(timed_out);
      if (timed_out) break;
      it.data_words.push_back(mask_data(cfg.vif.mon_cb.rdata));
      it.resp_list.push_back(ocah_axi_resp_e'(cfg.vif.mon_cb.rresp));
      last = (cfg.protocol == OCAH_AXI_PROTO_AXI4_LITE) || (cfg.vif.mon_cb.rlast === 1'b1);
      if (last) capture_observed_id(it, cfg.vif.mon_cb.rid);
    end
    cfg.vif.rready <= 1'b0;
    if (timed_out) begin
      flag_timeout(it, "R");
      return;
    end
    read_bursts++;
  endtask

endclass : ocah_axi_master_driver
