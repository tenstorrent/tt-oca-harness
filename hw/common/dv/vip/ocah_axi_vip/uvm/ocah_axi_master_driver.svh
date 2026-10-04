// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// Active AXI4/AXI4-Lite master driver (initiator side).
//
// Executes one ocah_axi_item per sequence handshake: writes run the AW and
// W phases concurrently (AXI permits either arrival order; the item's
// aw/w_valid_delay knobs skew their launch) then B, reads run AR -> R beats
// to RLAST; a single transaction is outstanding at a time unless the item
// carries a `pair`, whose single-beat AW/W or AR launches as soon as the
// first's is accepted and whose response is collected after the first's,
// while the address channel's stall cycles and stability are sampled into
// ax_stall_cycles / ax_stable, or carries `ops`, single-beat reads and
// writes that run together with each beat launched on its own cycle (see
// do_pipeline). The item's b_ready_delay defers the BREADY assert, and a
// nonzero r_ready_delay holds RREADY low after RVALID asserts while the
// driver samples RDATA/RRESP stability into hold_stable.
// cfg.protocol selects AXI4-Lite (single-beat; the driver itself ties the
// AXI4-only request fields to the adapter contract values from ocah_axi_if's
// header).
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

  // Message ID of the error that rejects an invalid pipeline.
  localparam string PipelineInvalidId = "OCAH_AXI_PIPELINE_INVALID";

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
      if (req.pair != null) begin
        req.pair.source     = req.source;
        req.pair.start_time = req.start_time;
      end
      foreach (req.ops[i]) begin
        req.ops[i].source     = req.source;
        req.ops[i].start_time = req.start_time;
      end
      if (req.ops.size() != 0) do_pipeline(req);
      else
        case (req.direction)
          OCAH_AXI_DIR_WRITE: do_write(req);
          OCAH_AXI_DIR_READ:  do_read(req);
          default: `uvm_error(get_type_name(), $sformatf(
                      "unsupported direction %s", req.direction.name()))
        endcase
      req.end_time = $time;
      if (req.pair != null) req.pair.end_time = req.end_time;
      foreach (req.ops[i]) req.ops[i].end_time = req.end_time;
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
    if (it.pair != null) it.pair.timed_out = 1'b1;
    `uvm_info(cfg.name_tag, $sformatf(
              "%s handshake timeout after %0d cycles: %s",
              phase_s,
              cfg.timeout_cycles,
              it.convert2string()
              ), UVM_MEDIUM)
  endfunction

  // Address-channel observation across a two-outstanding pair, until
  // `handshakes` beats have been accepted: the cycles VALID was held while
  // READY was low, and whether every such stalled beat kept VALID asserted
  // with its address unchanged until READY (IHI 0022 A3.2.1 initiator
  // rule). Bounded by cfg.timeout_cycles.
  protected task watch_ax(ocah_axi_item it, bit is_read, int unsigned handshakes);
    bit          pending = 1'b0;
    bit [63:0]   pending_addr = '0;
    int unsigned seen = 0;
    int unsigned cycles = 0;
    it.ax_stall_cycles = 0;
    it.ax_stable       = 1'b1;
    while (seen < handshakes) begin
      bit valid, ready;
      bit [63:0] addr;
      @(cfg.vif.mon_cb);
      valid = is_read ? (cfg.vif.mon_cb.arvalid === 1'b1) : (cfg.vif.mon_cb.awvalid === 1'b1);
      ready = is_read ? (cfg.vif.mon_cb.arready === 1'b1) : (cfg.vif.mon_cb.awready === 1'b1);
      addr  = is_read ? 64'(cfg.vif.mon_cb.araddr) : 64'(cfg.vif.mon_cb.awaddr);
      if (valid && pending && addr !== pending_addr) it.ax_stable = 1'b0;
      if (valid && !ready) begin
        pending      = 1'b1;
        pending_addr = addr;
        it.ax_stall_cycles++;
      end else begin
        if (valid) seen++;
        else if (pending) it.ax_stable = 1'b0;
        pending = 1'b0;
      end
      cycles++;
      if (cfg.timeout_cycles != 0 && cycles >= cfg.timeout_cycles) return;
    end
  endtask

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

  protected task drive_w_beat(ocah_axi_item it, int unsigned beat, int unsigned beats);
    cfg.vif.wdata  <= it.data_words[beat];
    cfg.vif.wstrb  <= 8'((beat < it.strobes.size()) ? it.strobes[beat] : cfg.full_strb());
    cfg.vif.wlast  <= (cfg.protocol == OCAH_AXI_PROTO_AXI4_LITE) ? 1'b1 : (beat == beats - 1);
    cfg.vif.wvalid <= 1'b1;
  endtask

  // One B handshake into `target`: BRESP/BID sampled on the accepted cycle.
  protected task accept_b(ocah_axi_item target, output bit timed_out);
    wait_b(timed_out);
    if (timed_out) return;
    target.resp_list.push_back(ocah_axi_resp_e'(cfg.vif.mon_cb.bresp));
    capture_observed_id(target, cfg.vif.mon_cb.bid);
    write_bursts++;
  endtask

  virtual task do_write(ocah_axi_item it);
    int unsigned beats = it.data_words.size();
    bit aw_timed_out, w_timed_out, b_timed_out;
    bit first_aw_done, first_w_done;
    it.clear_results();
    if (it.pair != null) it.pair.clear_results();
    if (beats == 0 || (it.pair != null && it.pair.data_words.size() != 1)) begin
      `uvm_error(cfg.name_tag, "write item carries no data beats")
      return;
    end
    if (cfg.protocol == OCAH_AXI_PROTO_AXI4_LITE && beats > 1) begin
      `uvm_error(cfg.name_tag,
                 $sformatf("%0d-beat write on an AXI4-Lite master (single-beat protocol)", beats))
      return;
    end
    // Address and data phases run concurrently; each channel's valid
    // delay skews its launch (both zero = simultaneous assert). A pair's
    // AW and W follow the first's on their channels once accepted. The
    // response phase starts once the first write's request phase is
    // complete: b_ready_delay defers the accept, then BRESP/BID are
    // sampled on each accepted cycle, the pair's after the first's, so a
    // responder that admits one write in flight retires the first B before
    // the pair's W passes.
    fork
      begin : aw_phase
        repeat (it.aw_valid_delay) @(cfg.vif.mon_cb);
        drive_aw(it, beats);
        wait_aw(aw_timed_out);
        first_aw_done = 1'b1;
        if (it.pair != null && !aw_timed_out) begin
          drive_aw(it.pair, 1);
          wait_aw(aw_timed_out);
        end
        cfg.vif.awvalid <= 1'b0;
      end
      begin : w_phase
        repeat (it.w_valid_delay) @(cfg.vif.mon_cb);
        for (int unsigned beat = 0; beat < beats; beat++) begin
          drive_w_beat(it, beat, beats);
          wait_w(w_timed_out);
          if (w_timed_out) break;
        end
        first_w_done = 1'b1;
        if (it.pair != null && !w_timed_out) begin
          drive_w_beat(it.pair, 0, 1);
          wait_w(w_timed_out);
        end
        cfg.vif.wvalid <= 1'b0;
      end
      begin : aw_watch
        if (it.pair != null) watch_ax(it, 1'b0, 2);
      end
      begin : b_phase
        wait (first_aw_done && first_w_done);
        if (!aw_timed_out && !w_timed_out) begin
          repeat (it.b_ready_delay) @(cfg.vif.mon_cb);
          cfg.vif.bready <= 1'b1;
          accept_b(it, b_timed_out);
          if (it.pair != null && !b_timed_out) accept_b(it.pair, b_timed_out);
          cfg.vif.bready <= 1'b0;
        end
      end
    join
    if (aw_timed_out || w_timed_out) flag_timeout(it, aw_timed_out ? "AW" : "W");
    else if (b_timed_out) flag_timeout(it, "B");
  endtask

  // RREADY-hold window: with a nonzero r_ready_delay, wait for RVALID with
  // RREADY still low, then sample RDATA/RRESP stability across the hold —
  // RVALID must stay asserted with unchanged payload until the accept
  // (hold_stable reports it; the deferred handshake then consumes the beat
  // normally).
  protected task hold_r_window(ocah_axi_item it, output bit timed_out);
    bit [63:0]   held_data;
    bit [1:0]    held_resp;
    int unsigned cycles = 0;
    timed_out = 1'b0;
    if (it.r_ready_delay == 0) return;
    forever begin
      @(cfg.vif.mon_cb);
      if (cfg.vif.mon_cb.rvalid === 1'b1) break;
      cycles++;
      if (cfg.timeout_cycles != 0 && cycles >= cfg.timeout_cycles) begin
        timed_out = 1'b1;
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
  endtask

  // Data phase of one read: accumulate beats to RLAST (Lite adapters tie
  // rlast=1, but the protocol itself bounds Lite reads to the single beat).
  protected task collect_r_beats(ocah_axi_item it, output bit timed_out);
    bit last = 1'b0;
    while (!last) begin
      wait_r(timed_out);
      if (timed_out) return;
      it.data_words.push_back(mask_data(cfg.vif.mon_cb.rdata));
      it.resp_list.push_back(ocah_axi_resp_e'(cfg.vif.mon_cb.rresp));
      last = (cfg.protocol == OCAH_AXI_PROTO_AXI4_LITE) || (cfg.vif.mon_cb.rlast === 1'b1);
      if (last) capture_observed_id(it, cfg.vif.mon_cb.rid);
    end
    read_bursts++;
  endtask

  // Response side of a read: the optional hold window, then the beats of
  // `it` and, for a pair, the single beat of `it.pair` behind them.
  protected task read_responses(ocah_axi_item it, output bit timed_out);
    hold_r_window(it, timed_out);
    if (timed_out) return;
    cfg.vif.rready <= 1'b1;
    collect_r_beats(it, timed_out);
    if (it.pair != null && !timed_out) collect_r_beats(it.pair, timed_out);
    cfg.vif.rready <= 1'b0;
  endtask

  virtual task do_read(ocah_axi_item it);
    int unsigned beats = (it.expected_beats == 0) ? 1 : it.expected_beats;
    bit ar_timed_out, r_timed_out;
    it.clear_results();
    if (it.pair != null) it.pair.clear_results();
    if (cfg.protocol == OCAH_AXI_PROTO_AXI4_LITE && beats > 1) begin
      `uvm_error(cfg.name_tag,
                 $sformatf("%0d-beat read on an AXI4-Lite master (single-beat protocol)", beats))
      return;
    end
    if (it.pair == null) begin
      // Address phase, then the response side.
      drive_ar(it, beats);
      wait_ar(ar_timed_out);
      cfg.vif.arvalid <= 1'b0;
      if (ar_timed_out) begin
        flag_timeout(it, "AR");
        return;
      end
      read_responses(it, r_timed_out);
      if (r_timed_out) flag_timeout(it, "R");
      return;
    end
    // Pair: the second AR follows the first's acceptance while the response
    // side holds RREADY, so the responder meets it with the first read
    // open.
    fork
      begin : ar_phase
        drive_ar(it, beats);
        wait_ar(ar_timed_out);
        if (!ar_timed_out) begin
          drive_ar(it.pair, 1);
          wait_ar(ar_timed_out);
        end
        cfg.vif.arvalid <= 1'b0;
      end
      begin : ar_watch
        watch_ax(it, 1'b1, 2);
      end
      begin : r_phase
        read_responses(it, r_timed_out);
      end
    join
    if (ar_timed_out || r_timed_out) flag_timeout(it, ar_timed_out ? "AR" : "R");
  endtask

  // ------------------------------------------------------------------
  // Pipelined operation.
  // ------------------------------------------------------------------

  protected function void set_request_valid(int unsigned chan, bit value);
    case (chan)
      0: cfg.vif.awvalid <= value;
      1: cfg.vif.wvalid <= value;
      default: cfg.vif.arvalid <= value;
    endcase
  endfunction

  protected function bit request_handshake(int unsigned chan);
    case (chan)
      0: return cfg.vif.mon_cb.awvalid === 1'b1 && cfg.vif.mon_cb.awready === 1'b1;
      1: return cfg.vif.mon_cb.wvalid === 1'b1 && cfg.vif.mon_cb.wready === 1'b1;
      default: return cfg.vif.mon_cb.arvalid === 1'b1 && cfg.vif.mon_cb.arready === 1'b1;
    endcase
  endfunction

  // One request channel of a pipeline (0 AW, 1 W, 2 AR): each beat launches
  // once `now`, the sampled cycles since the start, reaches its delay and the
  // beat ahead of it has been accepted, so a due beat follows its
  // predecessor back to back. `accepted` counts the handshakes for the
  // response side; each READY wait is bounded by cfg.timeout_cycles.
  protected task pipe_request(ocah_axi_item beats[$], int unsigned chan, ref int unsigned accepted,
                              ref bit timed_out);
    int unsigned now = 0;
    foreach (beats[i]) begin
      int unsigned due = (chan == 0) ? beats[i].aw_valid_delay :
                         (chan == 1) ? beats[i].w_valid_delay : beats[i].ar_valid_delay;
      int unsigned cycles = 0;
      if (due > now) begin
        set_request_valid(chan, 1'b0);
        while (now < due) begin
          @(cfg.vif.mon_cb);
          now++;
        end
      end
      case (chan)
        0: drive_aw(beats[i], 1);
        1: drive_w_beat(beats[i], 0, 1);
        default: drive_ar(beats[i], 1);
      endcase
      forever begin
        @(cfg.vif.mon_cb);
        now++;
        if (request_handshake(chan)) break;
        cycles++;
        if (cfg.timeout_cycles != 0 && cycles >= cfg.timeout_cycles) begin
          timed_out = 1'b1;
          set_request_valid(chan, 1'b0);
          return;
        end
      end
      accepted++;
    end
    set_request_valid(chan, 1'b0);
  endtask

  // BVALID or RVALID seen, bounded by cfg.timeout_cycles.
  protected task wait_response_valid(bit is_read, output bit timed_out);
    int unsigned cycles = 0;
    timed_out = 1'b0;
    forever begin
      @(cfg.vif.mon_cb);
      if ((is_read ? cfg.vif.mon_cb.rvalid : cfg.vif.mon_cb.bvalid) === 1'b1) return;
      cycles++;
      if (cfg.timeout_cycles != 0 && cycles >= cfg.timeout_cycles) begin
        timed_out = 1'b1;
        return;
      end
    end
  endtask

  // Single-beat reads and writes in flight together. Every request beat
  // launches no earlier than its channel delay and no earlier than the
  // acceptance of the beat ahead of it on its channel; reads and writes run
  // independently. BREADY and RREADY stay low until it.b_ready_delay and
  // it.r_ready_delay cycles after the first BVALID and RVALID, then the
  // responses are collected in list order per direction. An invalid op
  // fails the operation before any signal is driven. A timeout marks the
  // carrier and every op whose final response handshake has not completed
  // timed out; a read keeps the beats it received, the other ops keep their
  // results, and the stall counts cover the cycles up to the timeout.
  virtual task do_pipeline(ocah_axi_item it);
    ocah_axi_item wr[$], rd[$];
    int unsigned aw_acc, w_acc, ar_acc;
    int unsigned b_done, r_done;
    bit aw_to, w_to, ar_to, b_to, r_to, done;
    it.clear_results();
    foreach (it.ops[i]) it.ops[i].clear_results();
    foreach (it.ops[i]) begin
      ocah_axi_item op = it.ops[i];
      string why = "";
      if (op.direction == OCAH_AXI_DIR_WRITE && (op.data_words.size() != 1 || op.strobes.size() > 1))
        why = "a write takes one data word and at most one strobe";
      else if ((op.address >> cfg.addr_width) != 0)
        why = $sformatf("the address exceeds %0d bits", cfg.addr_width);
      if (why != "") begin
        `uvm_error(PipelineInvalidId, $sformatf("pipeline access %0d rejected, %s: %s", i, why,
                                                op.convert2string()))
        return;
      end
      if (op.direction == OCAH_AXI_DIR_WRITE) wr.push_back(op);
      else rd.push_back(op);
    end
    fork
      begin
        fork
          pipe_request(wr, 0, aw_acc, aw_to);
          pipe_request(wr, 1, w_acc, w_to);
          pipe_request(rd, 2, ar_acc, ar_to);
          begin : b_side
            bit released = (it.b_ready_delay == 0);
            cfg.vif.bready <= released;
            foreach (wr[i]) begin
              wait ((aw_acc > i || aw_to) && (w_acc > i || w_to));
              if (aw_acc <= i || w_acc <= i) break;
              if (!released) begin
                wait_response_valid(1'b0, b_to);
                if (b_to) break;
                repeat (it.b_ready_delay) @(cfg.vif.mon_cb);
                cfg.vif.bready <= 1'b1;
                released = 1'b1;
              end
              accept_b(wr[i], b_to);
              if (b_to) break;
              b_done++;
            end
            cfg.vif.bready <= 1'b0;
          end
          begin : r_side
            bit released = (it.r_ready_delay == 0);
            cfg.vif.rready <= released;
            foreach (rd[i]) begin
              wait (ar_acc > i || ar_to);
              if (ar_acc <= i) break;
              if (!released) begin
                wait_response_valid(1'b1, r_to);
                if (r_to) break;
                repeat (it.r_ready_delay) @(cfg.vif.mon_cb);
                cfg.vif.rready <= 1'b1;
                released = 1'b1;
              end
              collect_r_beats(rd[i], r_to);
              if (r_to) break;
              r_done++;
            end
            cfg.vif.rready <= 1'b0;
          end
        join
        done = 1'b1;
      end
      while (!done) begin
        @(cfg.vif.mon_cb);
        if (cfg.vif.mon_cb.awvalid === 1'b1 && cfg.vif.mon_cb.awready !== 1'b1)
          it.aw_stall_cycles++;
        if (cfg.vif.mon_cb.wvalid === 1'b1 && cfg.vif.mon_cb.wready !== 1'b1) it.w_stall_cycles++;
        if (cfg.vif.mon_cb.arvalid === 1'b1 && cfg.vif.mon_cb.arready !== 1'b1)
          it.ar_stall_cycles++;
      end
    join
    if (aw_to || w_to || ar_to || b_to || r_to) begin
      foreach (wr[i]) if (i >= b_done) wr[i].timed_out = 1'b1;
      foreach (rd[i]) if (i >= r_done) rd[i].timed_out = 1'b1;
      flag_timeout(it, aw_to ? "AW" : w_to ? "W" : ar_to ? "AR" : b_to ? "B" : "R");
    end
  endtask

endclass : ocah_axi_master_driver
