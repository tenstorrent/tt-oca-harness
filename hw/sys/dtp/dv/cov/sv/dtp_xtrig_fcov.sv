// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// Cross-trigger functional coverage: the CTPs, the CTM, and the XTRIG CSR
// port.
//
// One instance in the shared tb_top serves both flows. Every bin derives
// from the flattened cross-trigger pins, the configuration register fields
// of each CTP, the XTRIG CSR AXI-Lite port, and the tb_top models behind
// them (the spill registers and crossbar demux of that port, the CT_Req_out
// wires), all in the system-clock domain. A CTP bin samples the
// configuration the port runs with when it acts; the CTM route bins follow
// a shadow of the CT_SRC selects that the CSR writes program.
//
// CONVENTION: no declaration initializers on always_ff-driven variables,
// which VCS rejects (initializer_driver_checks); declare wires before use.

module dtp_xtrig_fcov (
  input wire        clk_i,
  input wire        rst_ni,

  // XTRIG CSR AXI-Lite port (shared ocah_axi_vip master, both flows)
  input wire [31:0] axil_awaddr_i,
  input wire        axil_awvalid_i,
  input wire        axil_awready_i,
  input wire [31:0] axil_wdata_i,
  input wire [3:0]  axil_wstrb_i,
  input wire        axil_wvalid_i,
  input wire        axil_wready_i,
  input wire [1:0]  axil_bresp_i,
  input wire        axil_bvalid_i,
  input wire        axil_bready_i,
  input wire [31:0] axil_araddr_i,
  input wire        axil_arvalid_i,
  input wire        axil_arready_i,
  input wire [31:0] axil_rdata_i,
  input wire [1:0]  axil_rresp_i,
  input wire        axil_rvalid_i,
  input wire        axil_rready_i,

  // CSR port spill registers and the crossbar demux behind them
  input wire        axil_aw_spill_full_i,  // the AW spill register holds two beats
  input wire        axil_w_spill_full_i,   // the W spill register holds two beats
  input wire        axil_ar_spill_full_i,  // the AR spill register holds two beats
  input wire        axil_r_spill_full_i,   // the R spill register holds two responses
  input wire        demux_aw_held_i,       // the demux holds an AW while a write is owed its W
  input wire        demux_ar_held_i,       // the demux holds an AR while a read is owed its R
  input wire        demux_aw_lock_i,       // the demux holds an AW its subordinate refused

  // Cross-trigger matrix and CTP GPIO pins
  input wire [9:0]  ctm_src_req_i,
  input wire [9:0]  ctm_dst_req_i,
  input wire [15:0] ctp_req_out_dout_i,
  input wire [15:0] ctp_req_out_dout_en_i,
  input wire [15:0] ctp_req_out_din_en_i,
  input wire [15:0] ctp_ack_in_din_i,
  input wire [15:0] ctp_ack_out_dout_i,
  input wire [15:0] ctp_ct_dst_i,
  // CTPs whose CT_Req_out pads sit on the one wire they share; every other
  // pad has a wire of its own
  input wire [15:0] ctp_wire_group_i,

  // Configuration of each CTP, from its register fields
  input wire [15:0]       ctp_mode_p2p_i,   // CONFIG.MODE
  input wire [15:0]       ctp_invert_i,     // CONFIG.INVERT
  input wire [15:0]       ctp_cfg_reset_i,  // CONFIG.RESET
  input wire [15:0][15:0] ctp_stretch_i     // STRETCH_MULT
);

  import cross_trigger_network_addrmap_pkg::*;

  localparam int unsigned NumCtp = int'(CROSS_TRIGGER_NETWORK_CTP_NUM);
  localparam int unsigned CtmPorts = int'(CROSS_TRIGGER_NETWORK_CTM_CT_SRC_NUM);
  // One port index space for the CTM: CTP ports occupy 0-15 and internal CTs
  // 16-25.
  localparam int unsigned IntPortBase = NumCtp;

  // CSR windows of the cross-trigger network (generated address map).
  localparam logic [31:0] CtmBase = 32'(CROSS_TRIGGER_NETWORK_CTM_BASE_ADDR);
  localparam int unsigned CtmStride = int'(CROSS_TRIGGER_NETWORK_CTM_CT_SRC_STRIDE);
  localparam int unsigned CtSrcSize = int'(CROSS_TRIGGER_NETWORK_CTM_CT_SRC_SIZE);
  localparam logic [31:0] CtmRegEnd = CtmBase + 32'(CROSS_TRIGGER_NETWORK_CTM_SIZE);
  localparam logic [31:0] CtpBase = 32'(CROSS_TRIGGER_NETWORK_CTP_BASE_ADDR(0));
  localparam int unsigned CtpStride = int'(CROSS_TRIGGER_NETWORK_CTP_STRIDE);
  localparam logic [31:0] CtpEnd = CtpBase + 32'(NumCtp * CtpStride);
  localparam int unsigned CsrWords = int'(CROSS_TRIGGER_NETWORK_SIZE) / 4;
  // Register offsets inside a CTP window. Verible explodes the argument list
  // of a call in a wrapped declaration.
  // verilog_format: off
  localparam logic [31:0] CtpConfigOff =
      32'(CROSS_TRIGGER_NETWORK_CTP_CONFIG_BASE_ADDR(0)) - CtpBase;
  localparam logic [31:0] CtpStatusOff =
      32'(CROSS_TRIGGER_NETWORK_CTP_STATUS_BASE_ADDR(0)) - CtpBase;
  localparam logic [31:0] CtpStretchOff =
      32'(CROSS_TRIGGER_NETWORK_CTP_STRETCH_MULT_BASE_ADDR(0)) - CtpBase;
  // verilog_format: on

  // CSR word classes of the network memory map. The mapped classes answer
  // OKAY; the matrix aperture past its register extent and every word past
  // the last CTP window answer DECERR.
  localparam logic [2:0] RegionCtmSelect = 3'd0;
  localparam logic [2:0] RegionCtmHole = 3'd1;
  localparam logic [2:0] RegionCtpConfig = 3'd2;
  localparam logic [2:0] RegionCtpStatus = 3'd3;
  localparam logic [2:0] RegionCtpStretch = 3'd4;
  localparam logic [2:0] RegionCtpHole = 3'd5;
  localparam logic [2:0] RegionCtmUnmapped = 3'd6;
  localparam logic [2:0] RegionUnmapped = 3'd7;

  localparam logic [1:0] RespOkay = 2'b00;
  localparam logic [1:0] RespExOkay = 2'b01;
  localparam logic [1:0] RespSlvErr = 2'b10;
  localparam logic [1:0] RespDecErr = 2'b11;

  // Which of a write's AW and W beats the CSR port took first.
  localparam logic [1:0] OrderSameCycle = 2'd0;
  localparam logic [1:0] OrderAwFirst = 2'd1;
  localparam logic [1:0] OrderWFirst = 2'd2;

  // STATUS field bits (cross_trigger_port.rdl).
  localparam logic [7:0] StatusBusy = 8'h01;
  localparam logic [7:0] StatusReqOut = 8'h10;
  localparam logic [7:0] StatusAckIn = 8'h20;
  localparam logic [7:0] StatusReqIn = 8'h40;
  localparam logic [7:0] StatusAckOut = 8'h80;

  wire in_reset = (rst_ni !== 1'b1);

  function automatic logic [2:0] csr_region(logic [31:0] addr);
    logic [31:0] word;
    word = {addr[31:2], 2'b00};
    if (word < CtmRegEnd) begin
      return (((word - CtmBase) % CtmStride) < CtSrcSize) ? RegionCtmSelect : RegionCtmHole;
    end
    if (word < CtpBase) return RegionCtmUnmapped;
    if (word >= CtpEnd) return RegionUnmapped;
    case ((word - CtpBase) % CtpStride)
      CtpConfigOff: return RegionCtpConfig;
      CtpStatusOff: return RegionCtpStatus;
      CtpStretchOff: return RegionCtpStretch;
      default: return RegionCtpHole;
    endcase
  endfunction

  // ------------------------------------------------------------------
  // CSR write decode. AXI4-Lite pairs the n-th W with the n-th AW, so each
  // queue holds the beats that await their partner and a write is classified
  // from the queue heads in the cycle after its later beat. Each beat carries
  // the cycle the port took it.
  // ------------------------------------------------------------------
  localparam int unsigned WrQueueDepth = 8;
  localparam int unsigned WrIdxW = $clog2(WrQueueDepth);
  localparam int unsigned WrCntW = $clog2(WrQueueDepth + 1);
  logic [15:0] cycle_q;
  logic [31:0] aw_addr_q[WrQueueDepth];
  logic [15:0] aw_cycle_q[WrQueueDepth];
  logic [31:0] w_data_q[WrQueueDepth];
  logic [3:0] w_strb_q[WrQueueDepth];
  logic [15:0] w_cycle_q[WrQueueDepth];
  logic [WrCntW-1:0] aw_count_q, w_count_q;
  wire aw_hs = axil_awvalid_i && axil_awready_i;
  wire w_hs = axil_wvalid_i && axil_wready_i;
  wire b_hs = axil_bvalid_i && axil_bready_i;
  wire ar_hs = axil_arvalid_i && axil_arready_i;
  wire r_hs = axil_rvalid_i && axil_rready_i;
  wire wr_pair = (aw_count_q != '0) && (w_count_q != '0);
  wire [WrIdxW-1:0] aw_push_idx = WrIdxW'(aw_count_q - WrCntW'(wr_pair));
  wire [WrIdxW-1:0] w_push_idx = WrIdxW'(w_count_q - WrCntW'(wr_pair));
  wire [31:0] wr_addr = aw_addr_q[0];
  wire [31:0] wr_data = w_data_q[0];
  wire [3:0] wr_strb = w_strb_q[0];
  wire [15:0] wr_skew = aw_cycle_q[0] - w_cycle_q[0];
  wire [1:0] wr_order = (wr_skew == 16'd0) ? OrderSameCycle
      : (wr_skew[15] ? OrderAwFirst : OrderWFirst);
  always_ff @(posedge clk_i) begin
    if (in_reset) begin
      cycle_q <= '0;
      aw_count_q <= '0;
      w_count_q <= '0;
    end else begin
      cycle_q <= cycle_q + 16'd1;
      if (wr_pair) begin
        for (int i = 0; i < WrQueueDepth - 1; i++) begin
          aw_addr_q[i] <= aw_addr_q[i+1];
          aw_cycle_q[i] <= aw_cycle_q[i+1];
          w_data_q[i] <= w_data_q[i+1];
          w_strb_q[i] <= w_strb_q[i+1];
          w_cycle_q[i] <= w_cycle_q[i+1];
        end
      end
      if (aw_hs) begin
        aw_addr_q[aw_push_idx] <= axil_awaddr_i;
        aw_cycle_q[aw_push_idx] <= cycle_q;
      end
      if (w_hs) begin
        w_data_q[w_push_idx] <= axil_wdata_i;
        w_strb_q[w_push_idx] <= axil_wstrb_i;
        w_cycle_q[w_push_idx] <= cycle_q;
      end
      aw_count_q <= aw_count_q + WrCntW'(aw_hs) - WrCntW'(wr_pair);
      w_count_q <= w_count_q + WrCntW'(w_hs) - WrCntW'(wr_pair);
    end
  end

  // The CSR word a write addresses. Every AXI4-Lite access uses the full
  // 32-bit data bus (AMBA AXI protocol specification, AXI4-Lite), so the
  // address selects the word that contains it and WSTRB the bytes within it.
  wire [31:0] aw_word_addr = {wr_addr[31:2], 2'b00};
  wire [2:0] wr_region = csr_region(wr_addr);

  // Writes and reads awaiting their response, in issue order: the B and R
  // channels answer in the order the port took the requests.
  localparam int unsigned RspQueueDepth = 8;
  localparam int unsigned RspIdxW = $clog2(RspQueueDepth);
  localparam int unsigned RspCntW = $clog2(RspQueueDepth + 1);
  logic [2:0] bq_region_q[RspQueueDepth];
  logic [3:0] bq_strb_q[RspQueueDepth];
  logic [1:0] bq_order_q[RspQueueDepth];
  logic [RspIdxW-1:0] bq_wr_q, bq_rd_q;
  logic [RspCntW-1:0] bq_count_q;
  logic [2:0] rq_region_q[RspQueueDepth];
  logic [7:0] rq_word_q[RspQueueDepth];
  logic [RspIdxW-1:0] rq_wr_q, rq_rd_q;
  logic [RspCntW-1:0] rq_count_q;
  wire [2:0] b_region = bq_region_q[bq_rd_q];
  wire [3:0] b_strb = bq_strb_q[bq_rd_q];
  wire [1:0] b_order = bq_order_q[bq_rd_q];
  wire [2:0] r_region = rq_region_q[rq_rd_q];
  wire [7:0] r_word = rq_word_q[rq_rd_q];
  wire [7:0] r_status = axil_rdata_i[7:0];

  // A response held: VALID high with READY low in the cycle before its
  // handshake.
  logic b_held_q, r_held_q;
  // Words written since the last system reset.
  logic [CsrWords-1:0] csr_written_q;
  wire r_reset_value = (r_word < 8'(CsrWords)) && !csr_written_q[r_word];
  // Requests the port accepted that their W (writes) or R (reads) beat has
  // not matched.
  int wr_open_q, rd_open_q;
  always_ff @(posedge clk_i) begin
    if (in_reset) begin
      bq_wr_q <= '0;
      bq_rd_q <= '0;
      bq_count_q <= '0;
      rq_wr_q <= '0;
      rq_rd_q <= '0;
      rq_count_q <= '0;
      b_held_q <= 1'b0;
      r_held_q <= 1'b0;
      csr_written_q <= '0;
      wr_open_q <= 0;
      rd_open_q <= 0;
    end else begin
      if (wr_pair) begin
        bq_region_q[bq_wr_q] <= wr_region;
        bq_strb_q[bq_wr_q] <= wr_strb;
        bq_order_q[bq_wr_q] <= wr_order;
        bq_wr_q <= bq_wr_q + RspIdxW'(1);
        if (aw_word_addr < 32'(CROSS_TRIGGER_NETWORK_SIZE)) begin
          csr_written_q[aw_word_addr[9:2]] <= 1'b1;
        end
      end
      if (b_hs) bq_rd_q <= bq_rd_q + RspIdxW'(1);
      bq_count_q <= bq_count_q + RspCntW'(wr_pair) - RspCntW'(b_hs);
      if (ar_hs) begin
        rq_region_q[rq_wr_q] <= csr_region(axil_araddr_i);
        rq_word_q[rq_wr_q] <= axil_araddr_i[9:2];
        rq_wr_q <= rq_wr_q + RspIdxW'(1);
      end
      if (r_hs) rq_rd_q <= rq_rd_q + RspIdxW'(1);
      rq_count_q <= rq_count_q + RspCntW'(ar_hs) - RspCntW'(r_hs);
      b_held_q <= axil_bvalid_i && !axil_bready_i;
      r_held_q <= axil_rvalid_i && !axil_rready_i;
      wr_open_q <= wr_open_q + int'(aw_hs) - int'(w_hs);
      rd_open_q <= rd_open_q + int'(ar_hs) - int'(r_hs);
    end
  end

`ifdef SIMULATION
  // A full queue has no slot for the next beat or request.
  always_ff @(posedge clk_i) begin
    if (!in_reset && ((aw_count_q >= WrCntW'(WrQueueDepth)) ||
                      (w_count_q >= WrCntW'(WrQueueDepth)) ||
                      (bq_count_q >= RspCntW'(RspQueueDepth)) ||
                      (rq_count_q >= RspCntW'(RspQueueDepth)))) begin
      $fatal(1, "dtp_xtrig_fcov: CSR queue full (aw=%0d w=%0d b=%0d r=%0d)", aw_count_q, w_count_q,
             bq_count_q, rq_count_q);
    end
  end
`endif  // SIMULATION

  // ------------------------------------------------------------------
  // CSR port flow (cg_xtrig_axil_flow): a second request taken while the
  // first is open, a spill register holding two beats, the crossbar demux
  // holding a request behind an open one, and the demux holding an AW its
  // subordinate refused. The port serves one access at a time behind spill
  // registers that hold two beats each (cross_trigger_network, Address Map).
  // ------------------------------------------------------------------
  localparam logic [3:0] FlowAwAcceptOpen = 4'd0;
  localparam logic [3:0] FlowArAcceptOpen = 4'd1;
  localparam logic [3:0] FlowWSpillFull = 4'd2;
  localparam logic [3:0] FlowRSpillFull = 4'd3;
  localparam logic [3:0] FlowDemuxAwHeld = 4'd4;
  localparam logic [3:0] FlowDemuxArHeld = 4'd5;
  localparam logic [3:0] FlowAwSpillFull = 4'd6;
  localparam logic [3:0] FlowArSpillFull = 4'd7;
  localparam logic [3:0] FlowDemuxAwLock = 4'd8;
  localparam int unsigned NumFlow = 9;
  wire axil_aw_accept_open_e = aw_hs && ((wr_open_q - int'(w_hs)) > 0);
  wire axil_ar_accept_open_e = ar_hs && ((rd_open_q - int'(r_hs)) > 0);
  wire [NumFlow-1:0] axil_flow = {demux_aw_lock_i, axil_ar_spill_full_i, axil_aw_spill_full_i,
      demux_ar_held_i, demux_aw_held_i, axil_r_spill_full_i, axil_w_spill_full_i,
      axil_ar_accept_open_e, axil_aw_accept_open_e};
  logic [NumFlow-1:0] axil_flow_q;
  always_ff @(posedge clk_i) axil_flow_q <= in_reset ? '0 : axil_flow;
  wire [NumFlow-1:0] axil_flow_rise = axil_flow & ~axil_flow_q;

  // ------------------------------------------------------------------
  // CTP configuration in force: each field one clock behind its register,
  // the clock at which the port core's registered pad outputs apply it.
  // ------------------------------------------------------------------
  logic [NumCtp-1:0] ctp_mode_q, ctp_invert_q, ctp_cfg_reset_q;
  logic [NumCtp-1:0][15:0] ctp_stretch_q;
  always_ff @(posedge clk_i) begin
    ctp_mode_q <= ctp_mode_p2p_i[NumCtp-1:0];
    ctp_invert_q <= ctp_invert_i[NumCtp-1:0];
    ctp_cfg_reset_q <= ctp_cfg_reset_i[NumCtp-1:0];
    ctp_stretch_q <= ctp_stretch_i[NumCtp-1:0];
  end
  logic [NumCtp-1:0] ctp_stretch_min, ctp_stretch_max;
  always_comb begin
    for (int i = 0; i < NumCtp; i++) begin
      ctp_stretch_min[i] = (ctp_stretch_q[i] == 16'h0000);
      ctp_stretch_max[i] = (ctp_stretch_q[i] == 16'hFFFF);
    end
  end

  // A CTP asserting its CT_Req_out (CONFIG.INVERT, cross_trigger_port.rdl): in
  // wire-OR mode, where the pad input is enabled, the port drives its wire only
  // while asserting; in point-to-point mode it drives the request level, high
  // unless inverted.
  wire [15:0] ctp_out_asserted = (ctp_req_out_din_en_i & ctp_req_out_dout_en_i)
      | (~ctp_req_out_din_en_i & ctp_req_out_dout_en_i & (ctp_req_out_dout_i ^ ctp_invert_q));
  logic [15:0] ctp_out_asserted_q, ctp_ct_dst_q;
  always_ff @(posedge clk_i) begin
    ctp_out_asserted_q <= ctp_out_asserted;
    ctp_ct_dst_q <= ctp_ct_dst_i;
  end
  // A CTP transmits when it starts to assert CT_Req_out and receives when it
  // delivers a trigger on ct_dst.
  wire [15:0] ctp_tx_rise = ctp_out_asserted & ~ctp_out_asserted_q;
  wire [15:0] ctp_rx_rise = ctp_ct_dst_i & ~ctp_ct_dst_q;

  // ------------------------------------------------------------------
  // cg_ctp_p2p: the four-phase handshake of every point-to-point CTP (pad
  // input disabled), each pad at the port's CONFIG.INVERT polarity. The
  // sender asserts CT_Req_out, sees CT_Ack_in, drops CT_Req_out, and is idle
  // once CT_Ack_in drops; the receiver asserts CT_Ack_out on CT_Req_in and
  // drops it after CT_Req_in drops.
  // ------------------------------------------------------------------
  wire [15:0] ctp_p2p_pad = ~ctp_req_out_din_en_i & ctp_req_out_dout_en_i;
  wire [15:0] ctp_p2p_req_out = ctp_p2p_pad & (ctp_req_out_dout_i ^ ctp_invert_q);
  wire [15:0] ctp_p2p_ack_in = ctp_p2p_pad & (ctp_ack_in_din_i ^ ctp_invert_q);
  wire [15:0] ctp_p2p_ack_out = ctp_p2p_pad & (ctp_ack_out_dout_i ^ ctp_invert_q);
  logic [15:0] ctp_p2p_req_out_q, ctp_p2p_ack_in_q, ctp_p2p_ack_out_q;
  always_ff @(posedge clk_i) begin
    ctp_p2p_req_out_q <= ctp_p2p_req_out;
    ctp_p2p_ack_in_q <= ctp_p2p_ack_in;
    ctp_p2p_ack_out_q <= ctp_p2p_ack_out;
  end
  wire [15:0] ctp_p2p_tx_request = ctp_p2p_req_out & ~ctp_p2p_req_out_q;
  wire [15:0] ctp_p2p_tx_acknowledge = ctp_p2p_req_out & ctp_p2p_ack_in
      & ~(ctp_p2p_req_out_q & ctp_p2p_ack_in_q);
  wire [15:0] ctp_p2p_tx_request_drop = ctp_p2p_req_out_q & ~ctp_p2p_req_out & ctp_p2p_ack_in;
  wire [15:0] ctp_p2p_tx_idle = ctp_p2p_ack_in_q & ~ctp_p2p_ack_in & ~ctp_p2p_req_out;
  wire [15:0] ctp_p2p_rx_acknowledge = ctp_p2p_ack_out & ~ctp_p2p_ack_out_q;
  wire [15:0] ctp_p2p_rx_idle = ctp_p2p_ack_out_q & ~ctp_p2p_ack_out;

  // ------------------------------------------------------------------
  // cg_ctp_reset: a reset landing on live CTP state, and the first
  // transmission after it. CONFIG.RESET acts on the point-to-point sender
  // alone and leaves the receiver running (cross_trigger_port.rdl); the
  // system reset clears both and every wire-OR pulse. A system reset is
  // credited when it releases, after the state it landed on.
  // ------------------------------------------------------------------
  wire [15:0] ctp_wire_or_pulse = ctp_req_out_din_en_i & ctp_req_out_dout_en_i;
  wire [15:0] ctp_cfg_reset_rise = ctp_cfg_reset_i[NumCtp-1:0] & ~ctp_cfg_reset_q;
  logic in_reset_q;
  // Live state of the last cycle out of reset.
  logic live_tx_pending_q, live_rx_held_q, live_wire_or_pulse_q;
  // The live state the current or last system reset landed on.
  logic sys_reset_tx_pending_q, sys_reset_rx_held_q, sys_reset_wire_or_pulse_q;
  // A transmission after a reset that landed on live state is its recovery.
  logic sys_recovery_q;
  logic [15:0] cfg_recovery_q;
  wire sys_reset_release = !in_reset && (in_reset_q === 1'b1);
  wire [15:0] ctp_cfg_reset_tx_pending = ctp_cfg_reset_rise & ctp_p2p_req_out;
  wire [15:0] ctp_cfg_reset_rx_held = ctp_cfg_reset_rise & ctp_p2p_ack_out;
  always_ff @(posedge clk_i) begin
    in_reset_q <= in_reset;
    if (!in_reset) begin
      live_tx_pending_q <= |ctp_p2p_req_out;
      live_rx_held_q <= |ctp_p2p_ack_out;
      live_wire_or_pulse_q <= |ctp_wire_or_pulse;
    end
    if (in_reset && (in_reset_q !== 1'b1)) begin
      sys_reset_tx_pending_q <= (live_tx_pending_q === 1'b1);
      sys_reset_rx_held_q <= (live_rx_held_q === 1'b1);
      sys_reset_wire_or_pulse_q <= (live_wire_or_pulse_q === 1'b1);
      sys_recovery_q <= 1'b0;
      cfg_recovery_q <= '0;
    end else if (sys_reset_release) begin
      sys_reset_tx_pending_q <= 1'b0;
      sys_reset_rx_held_q <= 1'b0;
      sys_reset_wire_or_pulse_q <= 1'b0;
      sys_recovery_q <= sys_reset_tx_pending_q || sys_reset_rx_held_q
          || sys_reset_wire_or_pulse_q;
    end else if (!in_reset) begin
      if (|ctp_tx_rise) sys_recovery_q <= 1'b0;
      cfg_recovery_q <= (cfg_recovery_q & ~(ctp_tx_rise & ctp_mode_q)) | ctp_cfg_reset_tx_pending;
    end
  end
  wire ctp_reset_system_tx_pending_e = sys_reset_release && sys_reset_tx_pending_q;
  wire ctp_reset_system_rx_held_e = sys_reset_release && sys_reset_rx_held_q;
  wire ctp_reset_system_wire_or_pulse_e = sys_reset_release && sys_reset_wire_or_pulse_q;
  wire ctp_reset_config_tx_pending_e = |ctp_cfg_reset_tx_pending;
  wire ctp_reset_config_rx_held_e = |ctp_cfg_reset_rx_held;
  wire [15:0] ctp_cfg_recovered = cfg_recovery_q & ctp_tx_rise & ctp_mode_q;
  wire ctp_recovery_config_e = |ctp_cfg_recovered;
  wire ctp_recovery_system_wire_or_e = sys_recovery_q && |(ctp_tx_rise & ~ctp_mode_q);
  wire ctp_recovery_system_p2p_e = sys_recovery_q && |(ctp_tx_rise & ctp_mode_q);

  // ------------------------------------------------------------------
  // cg_ctp_wire_or_rx: a port in wire-OR mode (pad input enabled) delivers a
  // trigger. Its pad data rests at the asserted level of its sense, so the
  // data pin tells the sense apart: 0 for INVERT=0, 1 for INVERT=1. A port
  // on a wire two or more CTPs share hears every member's pull. A port hears
  // its own pull of the wire RxLatency clocks after its output enable pulls
  // it (two synchronizer stages and the registered ct_dst).
  // ------------------------------------------------------------------
  localparam int unsigned RxLatency = 3;
  logic [15:0] ctp_wire_or_pull_q[RxLatency];
  always_ff @(posedge clk_i) begin
    ctp_wire_or_pull_q[0] <= ctp_wire_or_pulse;
    for (int k = 1; k < RxLatency; k++) ctp_wire_or_pull_q[k] <= ctp_wire_or_pull_q[k-1];
  end
  wire [15:0] ctp_wire_or_rx_rise = ctp_rx_rise & ctp_req_out_din_en_i;
  wire [15:0] ctp_wire_or_rx_own = ctp_wire_or_rx_rise & ctp_wire_or_pull_q[RxLatency-1];
  wire [15:0] ctp_shared_wire = ($countones(ctp_wire_group_i) >= 2) ? ctp_wire_group_i : '0;

  // ------------------------------------------------------------------
  // cg_ctm: source and destination types and the per-port index bins.
  // Source events: a CTP delivering a trigger into the matrix (ct_dst rise,
  // either mode) or an internal CT request (ctm_dst_req rise). Destination
  // events: a CTP starting to assert its CT_Req_out or an internal CT
  // request from the matrix (ctm_src_req rise).
  // ------------------------------------------------------------------
  logic [9:0] ctm_dst_req_q, ctm_src_req_q;
  always_ff @(posedge clk_i) begin
    ctm_dst_req_q <= ctm_dst_req_i;
    ctm_src_req_q <= ctm_src_req_i;
  end
  wire [15:0] ctp_src_rise = ctp_rx_rise;
  wire [15:0] ctp_dst_rise = ctp_tx_rise;
  wire [9:0] int_src_rise = ctm_dst_req_i & ~ctm_dst_req_q;
  wire [9:0] int_dst_rise = ctm_src_req_i & ~ctm_src_req_q;

  // ------------------------------------------------------------------
  // Route attribution (cg_ctm fan-in, cg_ctm_route, cg_ctm_fanout). A
  // destination rise is credited to the one source that rose within
  // RouteWindowCycles and that the destination's CT_SRC CONFIG_0
  // CT_DST_SELECT mask, shadowed from the CSR writes under their byte
  // strobes, selects; two or more such sources merge into it and credit no
  // route. A source event closes when its window ends: its fanout is the
  // number of destinations credited to it, by class, and an event that
  // merged into any destination has none.
  // ------------------------------------------------------------------
  localparam int unsigned RouteWindowCycles = 32;
  wire [31:0] ctm_csr_off = aw_word_addr - CtmBase;
  wire ctm_select_write = wr_pair && (ctm_csr_off < 32'(CtmPorts * CtmStride))
      && ((ctm_csr_off % CtmStride) == 0);
  wire [31:0] wr_biten = {{8{wr_strb[3]}}, {8{wr_strb[2]}}, {8{wr_strb[1]}}, {8{wr_strb[0]}}};
  wire [CtmPorts-1:0] route_src_rise = {int_src_rise, ctp_src_rise};
  wire [CtmPorts-1:0] route_dst_rise = {int_dst_rise, ctp_dst_rise};
  logic [CtmPorts-1:0] ctm_select_q[CtmPorts];
  logic [5:0] route_age_q[CtmPorts];
  logic [5:0] route_ctp_dst_q[CtmPorts];
  logic [5:0] route_int_dst_q[CtmPorts];
  logic [CtmPorts-1:0] route_merged_q;

  logic [CtmPorts-1:0] route_live;
  logic [CtmPorts-1:0] route_fanin_single, route_merged_now;
  logic [4:0] route_src_of[CtmPorts];
  logic [4:0] route_sources[CtmPorts];
  logic [5:0] route_ctp_inc[CtmPorts];
  logic [5:0] route_int_inc[CtmPorts];
  always_comb begin
    route_fanin_single = '0;
    route_merged_now = '0;
    for (int s = 0; s < CtmPorts; s++) begin
      route_live[s] = (route_age_q[s] != 6'd0);
      route_ctp_inc[s] = 6'd0;
      route_int_inc[s] = 6'd0;
    end
    for (int d = 0; d < CtmPorts; d++) begin
      route_src_of[d] = 5'd0;
      route_sources[d] = 5'($countones(route_live & ctm_select_q[d]));
      if (route_dst_rise[d] && (route_sources[d] == 5'd1)) begin
        route_fanin_single[d] = 1'b1;
        for (int s = 0; s < CtmPorts; s++) begin
          if (route_live[s] && ctm_select_q[d][s]) begin
            route_src_of[d] = 5'(s);
            if (d < NumCtp) route_ctp_inc[s] = route_ctp_inc[s] + 6'd1;
            else route_int_inc[s] = route_int_inc[s] + 6'd1;
          end
        end
      end else if (route_dst_rise[d] && (route_sources[d] > 5'd1)) begin
        route_merged_now = route_merged_now | (route_live & ctm_select_q[d]);
      end
    end
  end

  logic [CtmPorts-1:0] route_close;
  logic [5:0] route_ctp_total[CtmPorts];
  logic [5:0] route_int_total[CtmPorts];
  logic [CtmPorts-1:0] route_fanout_none, route_fanout_single, route_fanout_multicast;
  always_comb begin
    for (int s = 0; s < CtmPorts; s++) begin
      route_close[s] = (route_age_q[s] == 6'd1) && !route_src_rise[s]
          && !route_merged_q[s] && !route_merged_now[s];
      route_ctp_total[s] = route_ctp_dst_q[s] + route_ctp_inc[s];
      route_int_total[s] = route_int_dst_q[s] + route_int_inc[s];
      route_fanout_none[s] = route_close[s]
          && ((route_ctp_total[s] + route_int_total[s]) == 6'd0);
      route_fanout_single[s] = route_close[s]
          && ((route_ctp_total[s] + route_int_total[s]) == 6'd1);
      route_fanout_multicast[s] = route_close[s]
          && ((route_ctp_total[s] + route_int_total[s]) > 6'd1);
    end
  end

  always_ff @(posedge clk_i) begin
    for (int s = 0; s < CtmPorts; s++) begin
      if (in_reset) begin
        ctm_select_q[s] <= '0;
        route_age_q[s] <= '0;
        route_ctp_dst_q[s] <= '0;
        route_int_dst_q[s] <= '0;
        route_merged_q[s] <= 1'b0;
      end else begin
        if (ctm_select_write && (ctm_csr_off / CtmStride == s)) begin
          ctm_select_q[s] <= (ctm_select_q[s] & ~wr_biten[CtmPorts-1:0])
              | (wr_data[CtmPorts-1:0] & wr_biten[CtmPorts-1:0]);
        end
        if (route_src_rise[s]) begin
          route_age_q[s] <= 6'(RouteWindowCycles);
          route_ctp_dst_q[s] <= '0;
          route_int_dst_q[s] <= '0;
          route_merged_q[s] <= 1'b0;
        end else if (route_age_q[s] != 6'd0) begin
          route_age_q[s] <= route_age_q[s] - 6'd1;
          route_ctp_dst_q[s] <= route_ctp_total[s];
          route_int_dst_q[s] <= route_int_total[s];
          route_merged_q[s] <= route_merged_q[s] | route_merged_now[s];
        end
      end
    end
  end

  // ------------------------------------------------------------------
  // Covergroups, under the cross rules dtp_fcov.sv states.
  // ------------------------------------------------------------------
  localparam logic [1:0] StretchMin = 2'd0;
  localparam logic [1:0] StretchMid = 2'd1;
  localparam logic [1:0] StretchMax = 2'd2;

  localparam logic [2:0] PhaseTxRequest = 3'd0;
  localparam logic [2:0] PhaseTxAcknowledge = 3'd1;
  localparam logic [2:0] PhaseTxRequestDrop = 3'd2;
  localparam logic [2:0] PhaseTxIdle = 3'd3;
  localparam logic [2:0] PhaseRxAcknowledge = 3'd4;
  localparam logic [2:0] PhaseRxIdle = 3'd5;

  localparam logic [1:0] ResetSystem = 2'd0;
  localparam logic [1:0] ResetConfig = 2'd1;
  localparam logic [1:0] ResetRecovery = 2'd2;
  localparam logic [1:0] LiveTxPending = 2'd0;
  localparam logic [1:0] LiveRxHeld = 2'd1;
  localparam logic [1:0] LiveWireOrPulse = 2'd2;
  localparam logic [1:0] RecoveryConfig = 2'd0;
  localparam logic [1:0] RecoverySystemWireOr = 2'd1;
  localparam logic [1:0] RecoverySystemP2p = 2'd2;

  // Every CTP transmission and reception with the configuration the port
  // runs with.
  covergroup cg_ctp with function sample (
      logic transmit, logic mode_p2p, logic inverted, logic [1:0] stretch_class
  );
    option.per_instance = 1;
    cp_direction: coverpoint transmit {bins receive = {1'b0}; bins transmit = {1'b1};}
    cp_mode: coverpoint mode_p2p {bins wire_or = {1'b0}; bins p2p = {1'b1};}
    cp_inversion: coverpoint inverted {bins normal = {1'b0}; bins inverted = {1'b1};}
    // STRETCH_MULT shapes the wire-OR pulse a port transmits and nothing else.
    cp_stretch: coverpoint stretch_class iff (transmit && !mode_p2p) {
      bins min = {StretchMin}; bins mid = {StretchMid}; bins max = {StretchMax};
    }
    x_direction_mode_inversion: cross cp_direction, cp_mode, cp_inversion;
    x_inversion_stretch: cross cp_inversion, cp_stretch;
  endgroup

  // The phases of the point-to-point handshake at each pad polarity.
  covergroup cg_ctp_p2p with function sample (logic [2:0] phase, logic inverted);
    option.per_instance = 1;
    cp_phase: coverpoint phase {
      bins tx_request = {PhaseTxRequest};
      bins tx_acknowledge = {PhaseTxAcknowledge};
      bins tx_request_drop = {PhaseTxRequestDrop};
      bins tx_idle = {PhaseTxIdle};
      bins rx_acknowledge = {PhaseRxAcknowledge};
      bins rx_idle = {PhaseRxIdle};
    }
    cp_inversion: coverpoint inverted {bins normal = {1'b0}; bins inverted = {1'b1};}
    x_phase_inversion: cross cp_phase, cp_inversion;
  endgroup

  // Resets landing on live CTP state and the transmissions that recover from
  // them.
  covergroup cg_ctp_reset with function sample (logic [1:0] kind, logic [1:0] state);
    option.per_instance = 1;
    cp_system_reset: coverpoint state iff (kind == ResetSystem) {
      bins tx_pending = {LiveTxPending};
      bins rx_held = {LiveRxHeld};
      bins wire_or_pulse = {LiveWireOrPulse};
    }
    // CONFIG.RESET leaves a wire-OR port's pulse stretcher running.
    cp_config_reset: coverpoint state iff (kind == ResetConfig) {
      bins tx_pending = {LiveTxPending}; bins rx_held = {LiveRxHeld};
    }
    cp_recovery: coverpoint state iff (kind == ResetRecovery) {
      bins after_config_reset = {RecoveryConfig};
      bins after_system_reset_wire_or = {RecoverySystemWireOr};
      bins after_system_reset_p2p = {RecoverySystemP2p};
    }
  endgroup

  // Wire-OR receive events: the sense of the wire the trigger came from,
  // whether other CTPs share that wire, and whether the port heard its own
  // pull.
  covergroup cg_ctp_wire_or_rx with function sample (logic inverted, logic shared, logic own);
    option.per_instance = 1;
    cp_sense: coverpoint inverted {bins normal = {1'b0}; bins inverted = {1'b1};}
    cp_listeners: coverpoint shared {bins one = {1'b0}; bins shared_wire = {1'b1};}
    cp_origin: coverpoint own {bins other_pull = {1'b0}; bins own_pull = {1'b1};}
    x_sense_listeners: cross cp_sense, cp_listeners;
    x_sense_origin: cross cp_sense, cp_origin;
  endgroup

  covergroup cg_ctm with function sample (
      logic src_event,
      logic src_is_ctp,
      logic [4:0] src_idx,
      logic dst_event,
      logic dst_is_ctp,
      logic [4:0] dst_idx,
      logic [4:0] dst_sources
  );
    option.per_instance = 1;
    cp_source_type: coverpoint src_is_ctp iff (src_event) {
      bins internal = {1'b0}; bins ctp = {1'b1};
    }
    cp_dest_type: coverpoint dst_is_ctp iff (dst_event) {bins internal = {1'b0}; bins ctp = {1'b1};}
    cp_source_index: coverpoint src_idx iff (src_event) {
      bins ctp[] = {[0 : 15]}; bins internal[] = {[IntPortBase : IntPortBase + 9]};
    }
    cp_dest_index: coverpoint dst_idx iff (dst_event) {
      bins ctp[] = {[0 : 15]}; bins internal[] = {[IntPortBase : IntPortBase + 9]};
    }
    // Sources the destination selects that rose within the route window.
    cp_dest_fanin: coverpoint dst_sources iff (dst_event) {
      bins single = {5'd1}; bins merged = {[5'd2 : 5'd31]};
    }
  endgroup

  // Routes the matrix carried, credited as in the route attribution above.
  // The crosses cover CLA-to-CTP and CTP-to-CLA routes.
  covergroup cg_ctm_route with function sample (logic [4:0] src_idx, logic [4:0] dst_idx);
    option.per_instance = 1;
    cp_cla_src: coverpoint src_idx iff (src_idx >= IntPortBase) {
      bins cla[] = {[IntPortBase : IntPortBase + 9]};
    }
    cp_ctp_src: coverpoint src_idx iff (src_idx < IntPortBase) {bins ctp[] = {[0 : 15]};}
    cp_cla_dst: coverpoint dst_idx iff (dst_idx >= IntPortBase) {
      bins cla[] = {[IntPortBase : IntPortBase + 9]};
    }
    cp_ctp_dst: coverpoint dst_idx iff (dst_idx < IntPortBase) {bins ctp[] = {[0 : 15]};}
    x_cla_to_ctp: cross cp_cla_src, cp_ctp_dst;
    x_ctp_to_cla: cross cp_ctp_src, cp_cla_dst;
  endgroup

  // Every closed source event once per destination class it reached, with
  // the number of destinations the matrix carried it to; an event that
  // reached none is sampled once.
  covergroup cg_ctm_fanout with function sample (
      logic src_is_ctp, logic dst_is_ctp, logic [5:0] fanout
  );
    option.per_instance = 1;
    cp_source_type: coverpoint src_is_ctp {bins internal = {1'b0}; bins ctp = {1'b1};}
    cp_dest_type: coverpoint dst_is_ctp iff (fanout != 6'd0) {
      bins internal = {1'b0}; bins ctp = {1'b1};
    }
    cp_unrouted: coverpoint fanout {bins none = {6'd0};}
    // An event that reaches no destination has no destination class, so the
    // cross takes the routed fanouts only.
    cp_fanout: coverpoint fanout {
      bins single = {6'd1}; bins multicast = {[6'd2 : 6'd63]};
    }
    x_source_dest_fanout: cross cp_source_type, cp_dest_type, cp_fanout;
  endgroup

  // Every completed CSR write.
  covergroup cg_xtrig_csr_write with function sample (
      logic [2:0] region, logic [3:0] strb, logic [1:0] order, logic [1:0] resp, logic resp_held
  );
    option.per_instance = 1;
    cp_region: coverpoint region {
      bins ctm_select = {RegionCtmSelect};
      bins ctm_hole = {RegionCtmHole};
      bins ctp_config = {RegionCtpConfig};
      bins ctp_status = {RegionCtpStatus};
      bins ctp_stretch = {RegionCtpStretch};
      bins ctp_hole = {RegionCtpHole};
      bins ctm_unmapped = {RegionCtmUnmapped};
      bins unmapped = {RegionUnmapped};
    }
    // The byte lanes of the read-write registers.
    cp_rw_register: coverpoint region {
      bins ctm_select = {RegionCtmSelect};
      bins ctp_config = {RegionCtpConfig};
      bins ctp_stretch = {RegionCtpStretch};
    }
    cp_strobe: coverpoint strb iff (region inside {RegionCtmSelect, RegionCtpConfig,
                                                   RegionCtpStretch}) {
      bins byte0 = {4'h1};
      bins byte1 = {4'h2};
      bins byte2 = {4'h4};
      bins byte3 = {4'h8};
      bins full = {4'hF};
    }
    x_register_strobe: cross cp_rw_register, cp_strobe;
    cp_order: coverpoint order {
      bins same_cycle = {OrderSameCycle};
      bins aw_first = {OrderAwFirst};
      bins w_first = {OrderWFirst};
    }
    cp_resp: coverpoint resp {
      bins okay = {RespOkay};
      bins decerr = {RespDecErr};
      // The network's register blocks answer OKAY and its crossbar DECERR.
      illegal_bins other = {RespExOkay, RespSlvErr};
    }
    // A mapped word answers OKAY and an unmapped one DECERR.
    cp_region_resp: coverpoint {
      region, resp
    } {
      bins ctm_select_okay = {{RegionCtmSelect, RespOkay}};
      bins ctm_hole_okay = {{RegionCtmHole, RespOkay}};
      bins ctp_config_okay = {{RegionCtpConfig, RespOkay}};
      bins ctp_status_okay = {{RegionCtpStatus, RespOkay}};
      bins ctp_stretch_okay = {{RegionCtpStretch, RespOkay}};
      bins ctp_hole_okay = {{RegionCtpHole, RespOkay}};
      bins ctm_unmapped_decerr = {{RegionCtmUnmapped, RespDecErr}};
      bins unmapped_decerr = {{RegionUnmapped, RespDecErr}};
      illegal_bins mapped_decerr = {
        {RegionCtmSelect, RespDecErr},
        {RegionCtmHole, RespDecErr},
        {RegionCtpConfig, RespDecErr},
        {RegionCtpStatus, RespDecErr},
        {RegionCtpStretch, RespDecErr},
        {RegionCtpHole, RespDecErr}
      };
      illegal_bins unmapped_okay = {{RegionCtmUnmapped, RespOkay}, {RegionUnmapped, RespOkay}};
    }
    cp_wait: coverpoint resp_held {bins ready = {1'b0}; bins held = {1'b1};}
  endgroup

  // Every completed CSR read.
  covergroup cg_xtrig_csr_read with function sample (
      logic [2:0] region, logic [1:0] resp, logic resp_held, logic reset_value, logic [7:0] status
  );
    option.per_instance = 1;
    cp_region: coverpoint region {
      bins ctm_select = {RegionCtmSelect};
      bins ctm_hole = {RegionCtmHole};
      bins ctp_config = {RegionCtpConfig};
      bins ctp_status = {RegionCtpStatus};
      bins ctp_stretch = {RegionCtpStretch};
      bins ctp_hole = {RegionCtpHole};
      bins ctm_unmapped = {RegionCtmUnmapped};
      bins unmapped = {RegionUnmapped};
    }
    cp_resp: coverpoint resp {
      bins okay = {RespOkay};
      bins decerr = {RespDecErr};
      // The network's register blocks answer OKAY and its crossbar DECERR.
      illegal_bins other = {RespExOkay, RespSlvErr};
    }
    // A mapped word answers OKAY and an unmapped one DECERR.
    cp_region_resp: coverpoint {
      region, resp
    } {
      bins ctm_select_okay = {{RegionCtmSelect, RespOkay}};
      bins ctm_hole_okay = {{RegionCtmHole, RespOkay}};
      bins ctp_config_okay = {{RegionCtpConfig, RespOkay}};
      bins ctp_status_okay = {{RegionCtpStatus, RespOkay}};
      bins ctp_stretch_okay = {{RegionCtpStretch, RespOkay}};
      bins ctp_hole_okay = {{RegionCtpHole, RespOkay}};
      bins ctm_unmapped_decerr = {{RegionCtmUnmapped, RespDecErr}};
      bins unmapped_decerr = {{RegionUnmapped, RespDecErr}};
      illegal_bins mapped_decerr = {
        {RegionCtmSelect, RespDecErr},
        {RegionCtmHole, RespDecErr},
        {RegionCtpConfig, RespDecErr},
        {RegionCtpStatus, RespDecErr},
        {RegionCtpStretch, RespDecErr},
        {RegionCtpHole, RespDecErr}
      };
      illegal_bins unmapped_okay = {{RegionCtmUnmapped, RespOkay}, {RegionUnmapped, RespOkay}};
    }
    cp_wait: coverpoint resp_held {bins ready = {1'b0}; bins held = {1'b1};}
    // A register read before any write reaches it after the system reset.
    cp_reset_value: coverpoint region iff (reset_value) {
      bins ctm_select = {RegionCtmSelect};
      bins ctp_config = {RegionCtpConfig};
      bins ctp_status = {RegionCtpStatus};
      bins ctp_stretch = {RegionCtpStretch};
    }
    // STATUS read in each phase of a transfer: idle, a wire-OR pulse, a
    // point-to-point request awaiting and then holding its acknowledge, and a
    // received request.
    cp_status: coverpoint status iff (region == RegionCtpStatus) {
      bins idle = {8'h00};
      bins pulse = {StatusBusy};
      bins tx_request = {StatusBusy | StatusReqOut};
      bins tx_acknowledge = {StatusBusy | StatusAckIn};
      bins rx_acknowledge = {StatusBusy | StatusReqIn | StatusAckOut};
    }
  endgroup

  covergroup cg_xtrig_axil_flow with function sample (logic [3:0] flow);
    option.per_instance = 1;
    cp_flow: coverpoint flow {
      bins aw_accept_open = {FlowAwAcceptOpen};
      bins ar_accept_open = {FlowArAcceptOpen};
      bins w_spill_full = {FlowWSpillFull};
      bins r_spill_full = {FlowRSpillFull};
      bins demux_aw_held = {FlowDemuxAwHeld};
      bins demux_ar_held = {FlowDemuxArHeld};
      bins aw_spill_full = {FlowAwSpillFull};
      bins ar_spill_full = {FlowArSpillFull};
      bins demux_aw_lock = {FlowDemuxAwLock};
    }
  endgroup

  cg_ctp u_cg_ctp = new();
  cg_ctp_p2p u_cg_ctp_p2p = new();
  cg_ctp_reset u_cg_ctp_reset = new();
  cg_ctp_wire_or_rx u_cg_ctp_wire_or_rx = new();
  cg_ctm u_cg_ctm = new();
  cg_ctm_route u_cg_ctm_route = new();
  cg_ctm_fanout u_cg_ctm_fanout = new();
  cg_xtrig_csr_write u_cg_xtrig_csr_write = new();
  cg_xtrig_csr_read u_cg_xtrig_csr_read = new();
  cg_xtrig_axil_flow u_cg_xtrig_axil_flow = new();

  function automatic logic [1:0] ctp_stretch_class(int unsigned ctp);
    if (ctp_stretch_min[ctp]) return StretchMin;
    if (ctp_stretch_max[ctp]) return StretchMax;
    return StretchMid;
  endfunction

  always_ff @(posedge clk_i) begin
    if (!in_reset) begin
      if (b_hs) u_cg_xtrig_csr_write.sample(b_region, b_strb, b_order, axil_bresp_i, b_held_q);
      if (r_hs) begin
        u_cg_xtrig_csr_read.sample(r_region, axil_rresp_i, r_held_q, r_reset_value, r_status);
      end
      for (int f = 0; f < NumFlow; f++) begin
        if (axil_flow_rise[f]) u_cg_xtrig_axil_flow.sample(4'(f));
      end
      for (int i = 0; i < NumCtp; i++) begin
        if (ctp_tx_rise[i]) begin
          u_cg_ctp.sample(1'b1, ctp_mode_q[i], ctp_invert_q[i], ctp_stretch_class(i));
        end
        if (ctp_rx_rise[i]) u_cg_ctp.sample(1'b0, ctp_mode_q[i], ctp_invert_q[i], StretchMin);
        if (ctp_p2p_tx_request[i]) u_cg_ctp_p2p.sample(PhaseTxRequest, ctp_invert_q[i]);
        if (ctp_p2p_tx_acknowledge[i]) u_cg_ctp_p2p.sample(PhaseTxAcknowledge, ctp_invert_q[i]);
        if (ctp_p2p_tx_request_drop[i]) u_cg_ctp_p2p.sample(PhaseTxRequestDrop, ctp_invert_q[i]);
        if (ctp_p2p_tx_idle[i]) u_cg_ctp_p2p.sample(PhaseTxIdle, ctp_invert_q[i]);
        if (ctp_p2p_rx_acknowledge[i]) u_cg_ctp_p2p.sample(PhaseRxAcknowledge, ctp_invert_q[i]);
        if (ctp_p2p_rx_idle[i]) u_cg_ctp_p2p.sample(PhaseRxIdle, ctp_invert_q[i]);
        if (ctp_wire_or_rx_rise[i]) begin
          u_cg_ctp_wire_or_rx.sample(ctp_req_out_dout_i[i], ctp_shared_wire[i],
                                     ctp_wire_or_rx_own[i]);
        end
      end
      if (ctp_reset_system_tx_pending_e) u_cg_ctp_reset.sample(ResetSystem, LiveTxPending);
      if (ctp_reset_system_rx_held_e) u_cg_ctp_reset.sample(ResetSystem, LiveRxHeld);
      if (ctp_reset_system_wire_or_pulse_e) u_cg_ctp_reset.sample(ResetSystem, LiveWireOrPulse);
      if (ctp_reset_config_tx_pending_e) u_cg_ctp_reset.sample(ResetConfig, LiveTxPending);
      if (ctp_reset_config_rx_held_e) u_cg_ctp_reset.sample(ResetConfig, LiveRxHeld);
      if (ctp_recovery_config_e) u_cg_ctp_reset.sample(ResetRecovery, RecoveryConfig);
      if (ctp_recovery_system_wire_or_e) begin
        u_cg_ctp_reset.sample(ResetRecovery, RecoverySystemWireOr);
      end
      if (ctp_recovery_system_p2p_e) u_cg_ctp_reset.sample(ResetRecovery, RecoverySystemP2p);
      // A destination rises one or more clocks after its source: the matrix
      // registers its output and the CTP core adds synchroniser and handshake
      // stages, so no single edge carries both ends of a route.
      for (int p = 0; p < CtmPorts; p++) begin
        if (route_src_rise[p]) begin
          u_cg_ctm.sample(1'b1, (p < NumCtp), 5'(p), 1'b0, 1'b0, 5'd0, 5'd0);
        end
        if (route_dst_rise[p]) begin
          u_cg_ctm.sample(1'b0, 1'b0, 5'd0, 1'b1, (p < NumCtp), 5'(p), route_sources[p]);
        end
        if (route_fanin_single[p]) u_cg_ctm_route.sample(route_src_of[p], 5'(p));
        if (route_fanout_none[p]) u_cg_ctm_fanout.sample((p < NumCtp), 1'b0, 6'd0);
        if (route_ctp_total[p] != 6'd0 && (route_fanout_single[p] || route_fanout_multicast[p]))
        begin
          u_cg_ctm_fanout.sample((p < NumCtp), 1'b1, route_ctp_total[p] + route_int_total[p]);
        end
        if (route_int_total[p] != 6'd0 && (route_fanout_single[p] || route_fanout_multicast[p]))
        begin
          u_cg_ctm_fanout.sample((p < NumCtp), 1'b0, route_ctp_total[p] + route_int_total[p]);
        end
      end
    end
  end

endmodule : dtp_xtrig_fcov
