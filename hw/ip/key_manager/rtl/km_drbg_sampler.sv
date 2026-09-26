// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// Copyright 2026 Tenstorrent Inc.

// DRBG sampler that bridges KM CPU AXI4-Lite reads to a DRBG AXI-Stream.
//
// Mapped at base 0x0001_5000. A CPU read of DATA either returns a prefetched
// random word or starts a new AXI-Stream request; CFG.TIMEOUT guards stalls
// and CFG.PREFETCH can hold one word ready. STATUS reports ready, prefetch,
// timeout, stream-error, and good/bad beat counts; drbg_error_o pulses on
// timeout or stream protocol violations.

module km_drbg_sampler
  import km_intf_pkg::*;
  import axi_pkg::*;
  import km_drbg_sampler_reg_pkg::*;
  import km_drbg_sampler_addrmap_pkg::*;
#(
  parameter type axil_req_t  = km_axil_req_t,   // AXI-Lite request struct type
  parameter type axil_resp_t = km_axil_resp_t   // AXI-Lite response struct type
) (
  input  logic               clk_i,            // System clock
  input  logic               cold_rst_ni,      // Cold reset (AASD)
  input  logic               warm_rst_ni,      // Warm reset, synchronous to clk_i
  input  axil_req_t          axil_req_i,       // AXI-Lite slave request from the crossbar
  output axil_resp_t         axil_resp_o,      // AXI-Lite slave response to the crossbar
  input  km_drbg_axis_req_t  drbg_axis_req_i,  // DRBG AXI-Stream request (KM is slave)
  output km_drbg_axis_resp_t drbg_axis_resp_o, // DRBG AXI-Stream response (TREADY)
  output logic               drbg_error_o      // Aggregated error pulse to KMCSR
);

  `include "prim_assert.sv"

  // Register block address width, from the generated register map.
  localparam int unsigned ADDR_W = KM_DRBG_SAMPLER_REG_MIN_ADDR_WIDTH;

  //--------------------------------------------------------------------------
  // Register block AXI (flat) and hwif
  //--------------------------------------------------------------------------
  logic reg_awready, reg_awvalid;
  logic [ADDR_W-1:0] reg_awaddr;
  logic [2:0] reg_awprot;
  logic reg_wready, reg_wvalid;
  logic [31:0] reg_wdata;
  logic [3:0] reg_wstrb;
  logic reg_bready, reg_bvalid;
  logic [1:0] reg_bresp;
  logic reg_arready, reg_arvalid;
  logic [ADDR_W-1:0] reg_araddr;
  logic [2:0] reg_arprot;
  logic reg_rready, reg_rvalid;
  logic [31:0] reg_rdata;
  logic [1:0] reg_rresp;

  km_drbg_sampler__in_t  hwif_in;
  km_drbg_sampler__out_t hwif_out;

  //--------------------------------------------------------------------------
  // Single in-flight read: slot for one response (DATA or reg block)
  //--------------------------------------------------------------------------
  logic slot_valid;       // We have an outstanding read not yet responded
  logic slot_is_data;     // Slot is for DATA read (we provide R)
  logic [31:0] slot_rdata;
  logic [1:0] slot_rresp;
  logic slot_done;        // Response is ready to send

  // Only accept AR when no outstanding read
  logic ar_accept;
  logic is_data_read;
  assign is_data_read = (axil_req_i.ar.addr[ADDR_W-1:0] == KM_DRBG_SAMPLER_DATA_BASE_ADDR[ADDR_W-1:0]);
  assign ar_accept = axil_req_i.ar_valid && !slot_valid;

  // Forward to reg block: writes always; reads only when not DATA (we handle DATA ourselves)
  logic forward_ar;
  assign forward_ar = ar_accept && !is_data_read;
  assign reg_awvalid = axil_req_i.aw_valid;
  assign reg_awaddr  = axil_req_i.aw.addr[ADDR_W-1:0];
  assign reg_awprot  = axil_req_i.aw.prot;
  assign reg_wvalid  = axil_req_i.w_valid;
  assign reg_wdata   = axil_req_i.w.data;
  assign reg_wstrb   = axil_req_i.w.strb;
  assign reg_bready  = axil_req_i.b_ready;
  assign reg_arvalid = forward_ar;
  assign reg_araddr  = axil_req_i.ar.addr[ADDR_W-1:0];
  assign reg_arprot  = axil_req_i.ar.prot;
  assign reg_rready  = axil_req_i.r_ready;

  assign axil_resp_o.aw_ready = reg_awready;
  assign axil_resp_o.w_ready  = reg_wready;
  assign axil_resp_o.b.resp   = reg_bresp;
  assign axil_resp_o.b_valid  = reg_bvalid;
  assign axil_resp_o.ar_ready = ar_accept;
  assign axil_resp_o.r.data   = slot_is_data ? slot_rdata : reg_rdata;
  assign axil_resp_o.r.resp   = slot_is_data ? slot_rresp : reg_rresp;
  assign axil_resp_o.r_valid  = slot_valid && (slot_is_data ? slot_done : reg_rvalid);

  logic r_consume;
  assign r_consume = axil_resp_o.r_valid && axil_req_i.r_ready;

  // DATA read FSM outputs (used in slot always_ff below; full FSM declared later)
  logic data_read_done;
  logic [31:0] data_read_rdata;
  logic [1:0] data_read_rresp;

  // Slot state: slot_valid, slot_is_data, slot_done, slot_rresp are control and are reset.
  // slot_rdata is datapath (holds random/response data) and must NOT be reset.
  always_ff @(posedge clk_i or negedge cold_rst_ni) begin
    if (!cold_rst_ni) begin
      slot_valid <= 1'b0;
      slot_is_data <= 1'b0;
      slot_rresp <= 2'b00;
      slot_done <= 1'b0;
    end else if (!warm_rst_ni) begin
      slot_valid <= 1'b0;
      slot_is_data <= 1'b0;
      slot_rresp <= 2'b00;
      slot_done <= 1'b0;
    end else begin
      if (ar_accept) begin
        slot_valid <= 1'b1;
        slot_is_data <= is_data_read;
        slot_rresp <= 2'b00;
        slot_done <= 1'b0;
      end else if (r_consume) begin
        slot_valid <= 1'b0;
        slot_done <= 1'b0;
      end
      if (slot_valid && slot_is_data && data_read_done) begin
        slot_rdata <= data_read_rdata;
        slot_rresp <= data_read_rresp;
        slot_done <= 1'b1;
      end
    end
  end

  //--------------------------------------------------------------------------
  // DATA read FSM and DRBG request
  //--------------------------------------------------------------------------
  // DATA-read FSM states for the DRBG sampler request path.
  typedef enum logic [2:0] {
    StIdle,
    StRequest,
    StByteAssembly,
    StRespond,
    StTimeout,
    StStreamErr  // AXI-Stream protocol violation: TVALID dropped before TREADY
  } state_e;
  state_e state_q, state_d;

  logic [31:0] word_reg;            // Assembled word (active DATA-read path)
  logic [2:0]  data_bytes_collected; // 0..4 bytes packed so far (active path)
  logic [15:0] timeout_cnt;        // Timeout counter (active read only)
  logic [7:0] count_bad;
  logic [15:0] count_good;
  logic timeout_en;               // CFG.TIMEOUT != 0
  logic timeout_hit;

  assign timeout_en = (hwif_out.CFG.timeout.value != 16'h0);
  // The timeout fires exactly when the active wait budget is
  // exhausted (counter reaches 0).  The counter is loaded with
  // CFG.TIMEOUT-1 outside the active states (see always_ff below) and
  // decrements saturatingly inside, so it visits exactly CFG.TIMEOUT
  // distinct values (CFG.TIMEOUT-1 .. 0) before transitioning.  Combined
  // with the saturating decrement in always_ff, this guarantees:
  //   - StTimeout is entered after exactly CFG.TIMEOUT active cycles.
  //   - timeout_cnt never underflows past 0.
  assign timeout_hit = timeout_en && (timeout_cnt == 16'h0);

  // PeakRDL presents the written COUNT field in .value the cycle after wr_swacc.
  logic status_wr;
  logic status_wr_q;
  assign status_wr = hwif_out.STATUS.count_good.wr_swacc;
  always_ff @(posedge clk_i or negedge cold_rst_ni) begin
    if (!cold_rst_ni) status_wr_q <= 1'b0;
    else if (!warm_rst_ni) status_wr_q <= 1'b0;
    else status_wr_q <= status_wr;
  end

  // Prefetch: one word when CFG.PREFETCH=1; declared before DRBG handshake (used in tready)
  logic prefetched_valid;
  logic [31:0] prefetch_data_reg;
  logic [31:0] prefetch_word_acc;     // Compaction accumulator (not visible to CPU; no-reset)
  logic [2:0]  prefetch_bytes_collected; // 0..4 bytes packed so far (prefetch path)
  logic prefetch_pending;
  state_e prefetch_state_q, prefetch_state_d;
  logic prefetch_tready;

  // DRBG handshake
  logic tvalid, tready;
  logic [31:0] tdata;
  logic [3:0] tstrb;
  assign tvalid = drbg_axis_req_i.tvalid;
  assign tdata  = drbg_axis_req_i.tdata;
  assign tstrb  = drbg_axis_req_i.tstrb;
  // TREADY: from DATA read FSM or from prefetch FSM (only one active at a time)
  assign drbg_axis_resp_o.tready = tready | prefetch_tready;

  //--------------------------------------------------------------------------
  // Compaction packer: pack TSTRB-valid bytes from src_data into dest_word
  // starting at dest_pos, walking source lanes 0..3 in order.
  // Source may assert any combination of TSTRB bits per beat,
  // including always-same-lane (e.g. tstrb=0x1 every beat).  Compaction
  // guarantees 4 valid bytes are assembled regardless of lane pattern.
  // Byte order is not significant — bytes arrive in beat
  // order and are packed from lane 0 upward.
  //--------------------------------------------------------------------------
  function automatic void pack_bytes(input logic [31:0] dest_word_in, input logic [2:0] dest_pos_in,
                                     input logic [31:0] src_data, input logic [3:0] src_strb,
                                     output logic [31:0] dest_word_out,
                                     output logic [2:0] dest_pos_out);
    logic [31:0] w;
    logic [2:0]  pos;
    w   = dest_word_in;
    pos = dest_pos_in;
    for (int j = 0; j < 4; j++) begin
      if (src_strb[j] && pos < 3'd4) begin
        w[8*pos +: 8] = src_data[8*j +: 8];
        pos = pos + 3'd1;
      end
    end
    dest_word_out = w;
    dest_pos_out  = pos;
  endfunction

  //--------------------------------------------------------------------------
  // AXI-Stream protocol violation detection
  // AXI-Stream rule: once TVALID is asserted the source must not deassert it
  // before TREADY.  Detect this by sampling the previous-cycle TVALID and the
  // combined TREADY output, then checking whether TVALID has fallen without
  // a handshake having occurred.
  //--------------------------------------------------------------------------
  logic tvalid_q;       // TVALID registered: 1 cycle delayed
  logic drbg_tready_q;  // Combined TREADY output registered: 1 cycle delayed

  always_ff @(posedge clk_i or negedge cold_rst_ni) begin
    if (!cold_rst_ni) begin
      tvalid_q      <= 1'b0;
      drbg_tready_q <= 1'b0;
    end else if (!warm_rst_ni) begin
      tvalid_q      <= 1'b0;
      drbg_tready_q <= 1'b0;
    end else begin
      tvalid_q      <= tvalid;
      drbg_tready_q <= drbg_axis_resp_o.tready;
    end
  end

  // stream_err_pulse: fires the cycle after a TVALID-without-TREADY drop.
  // Previous cycle: TVALID=1, combined TREADY=0 (no handshake).
  // This cycle:     TVALID=0 (illegal withdrawal).
  logic stream_err_pulse;
  assign stream_err_pulse = tvalid_q && !drbg_tready_q && !tvalid;

  // Compaction packer outputs (next-cycle values from the function)
  logic [31:0] data_word_next;
  logic [2:0]  data_bytes_next;
  logic [31:0] prefetch_word_next;
  logic [2:0]  prefetch_bytes_next;

  // FSM and counters are control and are reset. word_reg / prefetch_word_acc are datapath
  // (hold DRBG data) and must NOT be reset.
  always_ff @(posedge clk_i or negedge cold_rst_ni) begin
    if (!cold_rst_ni) begin
      state_q              <= StIdle;
      data_bytes_collected <= 3'd0;
      timeout_cnt          <= 16'h0;
      count_bad            <= 8'h0;
      count_good           <= 16'h0;
    end else if (!warm_rst_ni) begin
      state_q              <= StIdle;
      data_bytes_collected <= 3'd0;
      timeout_cnt          <= 16'h0;
      count_bad            <= 8'h0;
      count_good           <= 16'h0;
    end else begin
      state_q <= state_d;
      if (state_q == StRequest || state_q == StByteAssembly) begin
        // Saturating decrement: stop at 0 so the counter cannot
        // underflow past zero on the cycle the FSM transitions to
        // StTimeout.
        if (timeout_en && (timeout_cnt != 16'h0)) timeout_cnt <= timeout_cnt - 1'b1;
        if (tvalid && tready) begin
          word_reg             <= data_word_next;
          data_bytes_collected <= data_bytes_next;
        end
      end else begin
        // Load CFG.TIMEOUT-1 (when timeout_en) so that the active
        // states observe exactly CFG.TIMEOUT distinct counter values
        // (CFG.TIMEOUT-1 .. 0) before timeout_hit fires.  When the
        // timeout is disabled (CFG.TIMEOUT==0) the counter is held at
        // 0 and cannot fire because timeout_en gates timeout_hit.
        if (timeout_en) timeout_cnt <= hwif_out.CFG.timeout.value - 16'h1;
        else timeout_cnt <= 16'h0;
        // Reset byte counter when leaving assembly states
        if (state_q == StRespond || state_q == StTimeout || state_q == StStreamErr)
          data_bytes_collected <= 3'd0;
      end
      // Hold increment for the decode cycle so .value is the write data.
      if (status_wr || status_wr_q) begin
        if (status_wr_q) begin
          if (hwif_out.STATUS.count_good.value != 16'h0) count_good <= 16'h0;
          if (hwif_out.STATUS.count_bad.value != 8'h0) count_bad <= 8'h0;
        end
      end else begin
        if (state_q == StRespond && slot_valid && slot_is_data && data_read_rresp == 2'b00) begin
          if (count_good != 16'hFFFF) count_good <= count_good + 1'b1;
        end else if (state_q == StTimeout || stream_err_pulse) begin
          // Timeout error OR AXI-Stream protocol violation (covers both in-flight and
          // out-of-band stream errors; stream_err_pulse is a 1-cycle combinational pulse).
          if (count_bad != 8'hFF) count_bad <= count_bad + 1'b1;
        end
      end
    end
  end

  always_comb begin
    state_d = state_q;
    tready = 1'b0;
    data_read_done = 1'b0;
    data_read_rdata = word_reg;
    data_read_rresp = 2'b00;

    // Compute next packer state for active DATA-read path
    pack_bytes(word_reg, data_bytes_collected, tdata, tstrb, data_word_next, data_bytes_next);

    case (state_q)
      StIdle: begin
        if (slot_valid && slot_is_data && !slot_done) begin
          if (prefetched_valid) begin
            data_read_rdata = prefetch_data_reg;
            data_read_rresp = 2'b00;
            data_read_done = 1'b1;
            state_d = StIdle;
          end else state_d = StRequest;
        end
      end
      StRequest: begin
        tready = 1'b1;
        if (stream_err_pulse) begin
          state_d = StStreamErr;
        end else if (timeout_hit) begin
          state_d = StTimeout;
        end else if (tvalid && tready) begin
          if (data_bytes_next == 3'd4) state_d = StRespond;
          else state_d = StByteAssembly;
        end
      end
      StByteAssembly: begin
        tready = 1'b1;
        if (stream_err_pulse) begin
          state_d = StStreamErr;
        end else if (timeout_hit) begin
          state_d = StTimeout;
        end else if (tvalid && tready && data_bytes_next == 3'd4) state_d = StRespond;
      end
      StRespond: begin
        data_read_rdata = word_reg;
        data_read_rresp = 2'b00;
        data_read_done = 1'b1;
        state_d = StIdle;
      end
      StTimeout: begin
        data_read_rdata = 32'h0;
        data_read_rresp = 2'b10;  // SLVERR
        data_read_done = 1'b1;
        state_d = StIdle;
      end
      StStreamErr: begin
        // AXI-Stream protocol violation: respond SLVERR/RDATA=0, return to idle
        data_read_rdata = 32'h0;
        data_read_rresp = 2'b10;  // SLVERR
        data_read_done = 1'b1;
        state_d = StIdle;
      end
      default: state_d = StIdle;
    endcase
  end

  // Consume prefetch when used for DATA read (single use)
  logic prefetch_consumed;
  assign prefetch_consumed = slot_valid && slot_is_data && prefetched_valid &&
                               state_q == StIdle && state_d == StIdle;

  // Prefetch FSM: prefetch_state_q, prefetched_valid, prefetch_pending, prefetch_bytes_collected
  // are control and are reset.  prefetch_data_reg and prefetch_word_acc are datapath and must
  // NOT be reset.
  always_ff @(posedge clk_i or negedge cold_rst_ni) begin
    if (!cold_rst_ni) begin
      prefetched_valid         <= 1'b0;
      prefetch_pending         <= 1'b0;
      prefetch_state_q         <= StIdle;
      prefetch_bytes_collected <= 3'd0;
    end else if (!warm_rst_ni) begin
      prefetched_valid         <= 1'b0;
      prefetch_pending         <= 1'b0;
      prefetch_state_q         <= StIdle;
      prefetch_bytes_collected <= 3'd0;
    end else begin
      if (!hwif_out.CFG.prefetch.value) begin
        prefetch_data_reg        <= 32'h0;
        prefetched_valid         <= 1'b0;
        prefetch_pending         <= 1'b0;
        prefetch_state_q         <= StIdle;
        prefetch_bytes_collected <= 3'd0;
      end else if (stream_err_pulse && prefetch_state_q != StIdle) begin
        // AXI-Stream protocol violation: discard any in-progress prefetch transfer.
        // prefetch_data_reg / prefetch_word_acc are datapath; NOT cleared.
        prefetched_valid         <= 1'b0;
        prefetch_pending         <= 1'b0;
        prefetch_state_q         <= StIdle;
        prefetch_bytes_collected <= 3'd0;
      end else if (prefetch_consumed) begin
        prefetched_valid <= 1'b0;
        prefetch_state_q <= prefetch_state_d;
        // prefetch_pending / prefetch_bytes_collected updated below
      end else begin
        prefetch_state_q <= prefetch_state_d;
        if ((prefetch_state_q == StRequest || prefetch_state_q == StByteAssembly) &&
                        tvalid && prefetch_tready) begin
          prefetch_word_acc        <= prefetch_word_next;
          prefetch_bytes_collected <= prefetch_bytes_next;
          if (prefetch_bytes_next == 3'd4) begin
            prefetch_data_reg <= prefetch_word_next;
            prefetched_valid  <= 1'b1;
            prefetch_pending  <= 1'b0;
            prefetch_bytes_collected <= 3'd0;
          end
        end else if (prefetch_state_q == StIdle && !prefetched_valid && !prefetch_pending) begin
          prefetch_pending         <= 1'b1;
          prefetch_bytes_collected <= 3'd0;
        end
      end
    end
  end

  always_comb begin
    // Compute next packer state for prefetch path
    pack_bytes(prefetch_word_acc, prefetch_bytes_collected, tdata, tstrb, prefetch_word_next,
               prefetch_bytes_next);

    prefetch_state_d = prefetch_state_q;
    if (prefetch_state_q == StIdle && prefetch_pending && hwif_out.CFG.prefetch.value) begin
      prefetch_state_d = StRequest;
    end else if ((prefetch_state_q == StRequest || prefetch_state_q == StByteAssembly) &&
                     tvalid && prefetch_tready) begin
      if (prefetch_bytes_next == 3'd4) prefetch_state_d = StIdle;
      else prefetch_state_d = StByteAssembly;
    end
  end

  // prefetch_tready: accept beats during StRequest and StByteAssembly,
  // but not while the active DATA-read FSM is also consuming (only one user at a time).
  assign prefetch_tready = (prefetch_state_q == StRequest || prefetch_state_q == StByteAssembly) &&
                             !(slot_valid && slot_is_data);  // Don't compete with DATA read

  // Error output to KMCSR: pulses for one cycle on timeout or any stream error.
  // stream_err_pulse covers both in-flight reads (where state_d also goes to StStreamErr)
  // and out-of-band protocol violations (FSM stays idle; only stream_err_pulse fires).
  assign drbg_error_o = (state_d == StTimeout) || (state_d == StStreamErr) || stream_err_pulse;

  // SVA: AXI-Stream protocol — TVALID must not fall while TREADY is low.
  // This assertion fires on genuine protocol violations and on deliberate glitch injection
  // during stream-error testing; RTL detection logic handles both correctly.
  `OCAH_OT_ASSERT_NEVER(KmDrbgTvalidStability_A, tvalid_q && !drbg_tready_q && !tvalid, clk_i,
                        !cold_rst_ni)

  //--------------------------------------------------------------------------
  // hwif_in: drive DATA, STATUS, PREFETCH_DATA from hardware
  //--------------------------------------------------------------------------
  assign hwif_in.DATA.data.next = word_reg;  // For reg block readback when DATA read completes

  assign hwif_in.STATUS.drbg_ready.next = tvalid;
  assign hwif_in.STATUS.prefetched.next = prefetched_valid;
  assign hwif_in.STATUS.timeout_err.next = 1'b0;
  assign hwif_in.STATUS.timeout_err.hwset = (state_d == StTimeout);
  assign hwif_in.STATUS.stream_err.next = 1'b0;
  assign hwif_in.STATUS.stream_err.hwset = stream_err_pulse;
  assign hwif_in.STATUS.count_bad.next = count_bad;
  assign hwif_in.STATUS.count_good.next = count_good;

  assign hwif_in.PREFETCH_DATA.data.next = prefetch_data_reg;

  // Drive warm reset into the regblock via hwif_in struct field
  assign hwif_in.WARM_RST_N = warm_rst_ni;

  //--------------------------------------------------------------------------
  // Register block instance (flat AXI; cold reset via arst_n, warm via hwif_in.WARM_RST_N)
  //--------------------------------------------------------------------------
  km_drbg_sampler_reg u_reg (
    .clk           (clk_i),
    .arst_n        (cold_rst_ni),
    .s_axil_awready(reg_awready),
    .s_axil_awvalid(reg_awvalid),
    .s_axil_awaddr (reg_awaddr),
    .s_axil_awprot (reg_awprot),
    .s_axil_wready (reg_wready),
    .s_axil_wvalid (reg_wvalid),
    .s_axil_wdata  (reg_wdata),
    .s_axil_wstrb  (reg_wstrb),
    .s_axil_bready (reg_bready),
    .s_axil_bvalid (reg_bvalid),
    .s_axil_bresp  (reg_bresp),
    .s_axil_arready(reg_arready),
    .s_axil_arvalid(reg_arvalid),
    .s_axil_araddr (reg_araddr),
    .s_axil_arprot (reg_arprot),
    .s_axil_rready (reg_rready),
    .s_axil_rvalid (reg_rvalid),
    .s_axil_rdata  (reg_rdata),
    .s_axil_rresp  (reg_rresp),
    .hwif_in       (hwif_in),
    .hwif_out      (hwif_out)
  );

endmodule : km_drbg_sampler
