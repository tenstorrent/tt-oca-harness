// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// Cross-trigger functional coverage (ctp_cg, ctm_cg).
//
// One instance in the shared tb_top serves both flows. Every bin derives
// from the flattened cross-trigger pins, the XTRIG CSR AXI-Lite write
// channel, and each CTP's CONFIG.INVERT field in the system-clock domain:
// CTP mode/inversion/stretch classes decode the CSR writes, the P2P phases
// and the CTM source/destination index bins follow the GPIO and matrix
// handshake pins.
//
// CONVENTION (see dtp_fcov.sv): every cover-property body and disable-iff
// argument is a single continuous-assign wire; no declaration initializers
// on always_ff-driven variables; declare wires before use.

`include "ocah_fcov_macros.svh"

module dtp_xtrig_fcov (
  input wire        clk_i,
  input wire        rst_ni,

  // XTRIG CSR AXI-Lite write channel (shared ocah_axi_vip master, both flows)
  input wire [31:0] axil_awaddr_i,
  input wire        axil_awvalid_i,
  input wire        axil_awready_i,
  input wire [31:0] axil_wdata_i,
  input wire [3:0]  axil_wstrb_i,
  input wire        axil_wvalid_i,
  input wire        axil_wready_i,

  // Cross-trigger matrix and CTP GPIO pins
  input wire [9:0]  ctm_src_req_i,
  input wire [9:0]  ctm_dst_req_i,
  input wire [15:0] ctp_req_out_dout_i,
  input wire [15:0] ctp_req_out_dout_en_i,
  input wire [15:0] ctp_req_out_din_en_i,
  input wire [15:0] ctp_ct_dst_i,
  input wire [15:0] ctp_ack_in_din_i,

  // CONFIG.INVERT of each CTP, from its register field
  input wire [15:0] ctp_invert_i
);

  import cross_trigger_network_addrmap_pkg::*;

  // CSR windows of the cross-trigger network (generated address map).
  localparam logic [31:0] CtpBase = 32'(CROSS_TRIGGER_NETWORK_CTP_BASE_ADDR(0));
  localparam int unsigned CtpStride = int'(CROSS_TRIGGER_NETWORK_CTP_STRIDE);
  localparam int unsigned NumCtp = int'(CROSS_TRIGGER_NETWORK_CTP_NUM);
  localparam logic [31:0] CtpEnd = CtpBase + 32'(NumCtp * CtpStride);
  // CONFIG and STRETCH_MULT offsets inside a CTP window. Verible explodes the
  // argument list of a call in a wrapped declaration.
  // verilog_format: off
  localparam logic [31:0] CtpConfigOff =
      32'(CROSS_TRIGGER_NETWORK_CTP_CONFIG_BASE_ADDR(0)) - CtpBase;
  localparam logic [31:0] CtpStretchOff =
      32'(CROSS_TRIGGER_NETWORK_CTP_STRETCH_MULT_BASE_ADDR(0)) - CtpBase;
  // verilog_format: on

  wire in_reset = (rst_ni !== 1'b1);

  // ------------------------------------------------------------------
  // CSR write decode. AXI4-Lite pairs the n-th W with the n-th AW, so each
  // queue holds the beats that await their partner and a write is classified
  // from the queue heads in the cycle after its later beat.
  // ------------------------------------------------------------------
  localparam int unsigned WrQueueDepth = 4;
  localparam int unsigned WrIdxW = $clog2(WrQueueDepth);
  localparam int unsigned WrCntW = $clog2(WrQueueDepth + 1);
  logic [31:0] aw_addr_q[WrQueueDepth];
  logic [31:0] w_data_q[WrQueueDepth];
  logic [3:0] w_strb_q[WrQueueDepth];
  logic [WrCntW-1:0] aw_count_q, w_count_q;
  wire aw_hs = axil_awvalid_i && axil_awready_i;
  wire w_hs = axil_wvalid_i && axil_wready_i;
  wire wr_pair = (aw_count_q != '0) && (w_count_q != '0);
  wire [WrIdxW-1:0] aw_push_idx = WrIdxW'(aw_count_q - WrCntW'(wr_pair));
  wire [WrIdxW-1:0] w_push_idx = WrIdxW'(w_count_q - WrCntW'(wr_pair));
  wire [31:0] wr_addr = aw_addr_q[0];
  wire [31:0] wr_data = w_data_q[0];
  wire [3:0] wr_strb = w_strb_q[0];
  always_ff @(posedge clk_i) begin
    if (in_reset) begin
      aw_count_q <= '0;
      w_count_q <= '0;
    end else begin
      if (wr_pair) begin
        for (int i = 0; i < WrQueueDepth - 1; i++) begin
          aw_addr_q[i] <= aw_addr_q[i+1];
          w_data_q[i] <= w_data_q[i+1];
          w_strb_q[i] <= w_strb_q[i+1];
        end
      end
      if (aw_hs) aw_addr_q[aw_push_idx] <= axil_awaddr_i;
      if (w_hs) begin
        w_data_q[w_push_idx] <= axil_wdata_i;
        w_strb_q[w_push_idx] <= axil_wstrb_i;
      end
      aw_count_q <= aw_count_q + WrCntW'(aw_hs) - WrCntW'(wr_pair);
      w_count_q <= w_count_q + WrCntW'(w_hs) - WrCntW'(wr_pair);
    end
  end

`ifdef SIMULATION
  // A full queue has no slot for the next beat.
  always_ff @(posedge clk_i) begin
    if (!in_reset && ((aw_count_q >= WrCntW'(WrQueueDepth)) ||
                      (w_count_q >= WrCntW'(WrQueueDepth)))) begin
      $fatal(1, "dtp_xtrig_fcov: CSR write queue full (aw_count=%0d w_count=%0d)", aw_count_q,
             w_count_q);
    end
  end
`endif  // SIMULATION

  // The CSR word a write addresses. Every AXI4-Lite access uses the full
  // 32-bit data bus (AMBA AXI protocol specification, AXI4-Lite), so the
  // address selects the word that contains it and WSTRB the bytes within it.
  wire [31:0] aw_word_addr = {wr_addr[31:2], 2'b00};
  wire ctp_csr_write = wr_pair && (aw_word_addr >= CtpBase) && (aw_word_addr < CtpEnd);
  wire [31:0] ctp_csr_off = (aw_word_addr - CtpBase) % CtpStride;
  wire ctp_config_write = ctp_csr_write && (ctp_csr_off == CtpConfigOff);
  wire ctp_stretch_write = ctp_csr_write && (ctp_csr_off == CtpStretchOff);
  // CONFIG.MODE, INVERT, and RESET sit in byte 0 and STRETCH_MULT in bytes 0
  // and 1 (cross_trigger_port.rdl), so a field is written only under the
  // strobes of its bytes.
  wire ctp_config_fields_write = ctp_config_write && wr_strb[0];
  wire ctp_stretch_field_write = ctp_stretch_write && (&wr_strb[1:0]);

  // CONFIG.INVERT per CTP one clock behind the field, the clock at which the
  // port core's registered pad outputs apply it.
  logic [NumCtp-1:0] ctp_invert_q;
  always_ff @(posedge clk_i) ctp_invert_q <= ctp_invert_i[NumCtp-1:0];

  // A CTP asserting its CT_Req_out (CONFIG.INVERT, cross_trigger_port.rdl): in
  // wire-OR mode, where the pad input is enabled, the port drives its wire only
  // while asserting; in point-to-point mode it drives the request level, high
  // unless inverted.
  wire [15:0] ctp_out_asserted = (ctp_req_out_din_en_i & ctp_req_out_dout_en_i)
      | (~ctp_req_out_din_en_i & ctp_req_out_dout_en_i & (ctp_req_out_dout_i ^ ctp_invert_q));

  // ------------------------------------------------------------------
  // ctp_cg — mode, inversion, stretch classes, and P2P phases.
  // ------------------------------------------------------------------
  wire ctp_mode_wire_or_e = ctp_config_fields_write && !wr_data[0];
  wire ctp_mode_p2p_e = ctp_config_fields_write && wr_data[0];
  wire ctp_inversion_normal_e = ctp_config_fields_write && !wr_data[1];
  wire ctp_inversion_inverted_e = ctp_config_fields_write && wr_data[1];
  wire ctp_csr_reset_e = ctp_config_fields_write && wr_data[2];
  wire [15:0] stretch_val = wr_data[15:0];
  wire ctp_stretch_min_e = ctp_stretch_field_write && (stretch_val == 16'd0);
  wire ctp_stretch_max_e = ctp_stretch_field_write && (stretch_val >= 16'd15);
  wire ctp_stretch_mid_e = ctp_stretch_field_write && (stretch_val != 16'd0)
      && (stretch_val < 16'd15);
  `OCAH_FCOV_COVER(c_ctp_mode_wire_or, ctp_mode_wire_or_e, clk_i, in_reset)
  `OCAH_FCOV_COVER(c_ctp_mode_p2p, ctp_mode_p2p_e, clk_i, in_reset)
  `OCAH_FCOV_COVER(c_ctp_inversion_normal, ctp_inversion_normal_e, clk_i, in_reset)
  `OCAH_FCOV_COVER(c_ctp_inversion_inverted, ctp_inversion_inverted_e, clk_i, in_reset)
  `OCAH_FCOV_COVER(c_ctp_stretch_min, ctp_stretch_min_e, clk_i, in_reset)
  `OCAH_FCOV_COVER(c_ctp_stretch_mid, ctp_stretch_mid_e, clk_i, in_reset)
  `OCAH_FCOV_COVER(c_ctp_stretch_max, ctp_stretch_max_e, clk_i, in_reset)

  // Point-to-point request and acknowledge per CTP (pad input disabled), each
  // at the port's CONFIG.INVERT polarity.
  wire [15:0] ctp_p2p_req_out = ctp_out_asserted & ~ctp_req_out_din_en_i;
  wire [15:0] ctp_p2p_ack_in = (ctp_ack_in_din_i ^ ctp_invert_q) & ~ctp_req_out_din_en_i;
  wire any_req_out = |ctp_p2p_req_out;
  wire any_ack_in = |ctp_p2p_ack_in;
  logic [15:0] ctp_p2p_req_out_q;
  wire any_req_out_rise = |(ctp_p2p_req_out & ~ctp_p2p_req_out_q);
  logic had_req_out_q, csr_reset_pending_q;
  always_ff @(posedge clk_i) begin
    ctp_p2p_req_out_q <= ctp_p2p_req_out;
    if (any_req_out) had_req_out_q <= 1'b1;
    if (ctp_csr_reset_e) csr_reset_pending_q <= 1'b1;
    else if (any_req_out_rise) csr_reset_pending_q <= 1'b0;
  end
  wire ctp_p2p_request_e = any_req_out;
  wire ctp_p2p_ack_e = |(ctp_p2p_req_out & ctp_p2p_ack_in);
  wire ctp_p2p_idle_e = !any_req_out && !any_ack_in && had_req_out_q;
  // Recovery is a request rising after a CONFIG.RESET write: a request held
  // on the pad when the reset is written is the one the reset clears.
  wire ctp_p2p_reset_recovery_e = any_req_out_rise && csr_reset_pending_q;
  `OCAH_FCOV_COVER(c_ctp_p2p_state_request_phase, ctp_p2p_request_e, clk_i, in_reset)
  `OCAH_FCOV_COVER(c_ctp_p2p_state_acknowledge_phase, ctp_p2p_ack_e, clk_i, in_reset)
  `OCAH_FCOV_COVER(c_ctp_p2p_state_idle, ctp_p2p_idle_e, clk_i, in_reset)
  `OCAH_FCOV_COVER(c_ctp_p2p_state_reset_recovery, ctp_p2p_reset_recovery_e, clk_i, in_reset)

  // Wire-OR receive: a port in wire-OR mode (pad input enabled) delivers a
  // trigger. Its pad data rests at the asserted level of its sense, so the
  // data pin tells the sense apart: 0 for INVERT=0, 1 for INVERT=1. Two or
  // more ports delivering in one cycle heard the same shared wire.
  logic [15:0] ctp_ct_dst_q;
  always_ff @(posedge clk_i) ctp_ct_dst_q <= ctp_ct_dst_i;
  wire [15:0] ctp_wire_or_rx_rise = ctp_ct_dst_i & ~ctp_ct_dst_q & ctp_req_out_din_en_i;
  wire ctp_wire_or_rx_normal_e = |(ctp_wire_or_rx_rise & ~ctp_req_out_dout_i);
  wire ctp_wire_or_rx_inverted_e = |(ctp_wire_or_rx_rise & ctp_req_out_dout_i);
  wire ctp_wire_or_rx_shared_e = $countones(ctp_wire_or_rx_rise) >= 2;
  `OCAH_FCOV_COVER(c_ctp_wire_or_rx_normal, ctp_wire_or_rx_normal_e, clk_i, in_reset)
  `OCAH_FCOV_COVER(c_ctp_wire_or_rx_inverted, ctp_wire_or_rx_inverted_e, clk_i, in_reset)
  `OCAH_FCOV_COVER(c_ctp_wire_or_rx_shared, ctp_wire_or_rx_shared_e, clk_i, in_reset)

  // ------------------------------------------------------------------
  // ctm_cg — source/destination types, fanout classes, and the per-port
  // index bins. Source events: a CTP delivering a trigger into the matrix
  // (ct_dst rise, either mode) or an internal CT request (ctm_dst_req rise).
  // Destination events: a CTP starting to assert its CT_Req_out or an
  // internal CT request from the matrix (ctm_src_req rise).
  // ------------------------------------------------------------------
  logic [15:0] ctp_out_asserted_q;
  logic [9:0] ctm_dst_req_q, ctm_src_req_q;
  always_ff @(posedge clk_i) begin
    ctp_out_asserted_q <= ctp_out_asserted;
    ctm_dst_req_q <= ctm_dst_req_i;
    ctm_src_req_q <= ctm_src_req_i;
  end
  wire [15:0] ctp_src_rise = ctp_ct_dst_i & ~ctp_ct_dst_q;
  wire [15:0] ctp_dst_rise = ctp_out_asserted & ~ctp_out_asserted_q;
  wire [9:0] int_src_rise = ctm_dst_req_i & ~ctm_dst_req_q;
  wire [9:0] int_dst_rise = ctm_src_req_i & ~ctm_src_req_q;

  wire ctm_source_ctp_e = |ctp_src_rise;
  wire ctm_source_internal_e = |int_src_rise;
  wire ctm_dest_ctp_e = |ctp_dst_rise;
  wire ctm_dest_internal_e = |int_dst_rise;
  `OCAH_FCOV_COVER(c_ctm_source_type_ctp, ctm_source_ctp_e, clk_i, in_reset)
  `OCAH_FCOV_COVER(c_ctm_source_type_internal, ctm_source_internal_e, clk_i, in_reset)
  `OCAH_FCOV_COVER(c_ctm_dest_type_ctp, ctm_dest_ctp_e, clk_i, in_reset)
  `OCAH_FCOV_COVER(c_ctm_dest_type_internal, ctm_dest_internal_e, clk_i, in_reset)

  // Fanout classes: destinations active simultaneously; "none" is a source
  // event whose window closes with no destination response.
  wire [5:0] dest_active_count =
      6'($countones(ctp_out_asserted)) + 6'($countones(ctm_src_req_i));
  logic [6:0] src_window_q;
  logic dest_seen_q;
  wire any_source_rise = ctm_source_ctp_e || ctm_source_internal_e;
  wire any_dest_active = (dest_active_count != 6'd0);
  always_ff @(posedge clk_i) begin
    if (any_source_rise) begin
      src_window_q <= 7'd100;
      dest_seen_q <= 1'b0;
    end else if (src_window_q != 7'd0) begin
      src_window_q <= src_window_q - 7'd1;
      if (any_dest_active) dest_seen_q <= 1'b1;
    end
  end
  wire ctm_fanout_single_e = (dest_active_count == 6'd1);
  wire ctm_fanout_multicast_e = (dest_active_count >= 6'd2);
  wire ctm_fanout_none_e = (src_window_q == 7'd1) && !dest_seen_q
      && !any_dest_active;
  `OCAH_FCOV_COVER(c_ctm_fanout_single, ctm_fanout_single_e, clk_i, in_reset)
  `OCAH_FCOV_COVER(c_ctm_fanout_multicast, ctm_fanout_multicast_e, clk_i, in_reset)
  `OCAH_FCOV_COVER(c_ctm_fanout_none, ctm_fanout_none_e, clk_i, in_reset)

  // Per-port source/destination index bins (16 CTP + 10 internal each way).
  wire ctm_src_ctp0_e = ctp_src_rise[0];
  `OCAH_FCOV_COVER(c_ctm_source_index_ctp0, ctm_src_ctp0_e, clk_i, in_reset)
  wire ctm_src_ctp1_e = ctp_src_rise[1];
  `OCAH_FCOV_COVER(c_ctm_source_index_ctp1, ctm_src_ctp1_e, clk_i, in_reset)
  wire ctm_src_ctp2_e = ctp_src_rise[2];
  `OCAH_FCOV_COVER(c_ctm_source_index_ctp2, ctm_src_ctp2_e, clk_i, in_reset)
  wire ctm_src_ctp3_e = ctp_src_rise[3];
  `OCAH_FCOV_COVER(c_ctm_source_index_ctp3, ctm_src_ctp3_e, clk_i, in_reset)
  wire ctm_src_ctp4_e = ctp_src_rise[4];
  `OCAH_FCOV_COVER(c_ctm_source_index_ctp4, ctm_src_ctp4_e, clk_i, in_reset)
  wire ctm_src_ctp5_e = ctp_src_rise[5];
  `OCAH_FCOV_COVER(c_ctm_source_index_ctp5, ctm_src_ctp5_e, clk_i, in_reset)
  wire ctm_src_ctp6_e = ctp_src_rise[6];
  `OCAH_FCOV_COVER(c_ctm_source_index_ctp6, ctm_src_ctp6_e, clk_i, in_reset)
  wire ctm_src_ctp7_e = ctp_src_rise[7];
  `OCAH_FCOV_COVER(c_ctm_source_index_ctp7, ctm_src_ctp7_e, clk_i, in_reset)
  wire ctm_src_ctp8_e = ctp_src_rise[8];
  `OCAH_FCOV_COVER(c_ctm_source_index_ctp8, ctm_src_ctp8_e, clk_i, in_reset)
  wire ctm_src_ctp9_e = ctp_src_rise[9];
  `OCAH_FCOV_COVER(c_ctm_source_index_ctp9, ctm_src_ctp9_e, clk_i, in_reset)
  wire ctm_src_ctp10_e = ctp_src_rise[10];
  `OCAH_FCOV_COVER(c_ctm_source_index_ctp10, ctm_src_ctp10_e, clk_i, in_reset)
  wire ctm_src_ctp11_e = ctp_src_rise[11];
  `OCAH_FCOV_COVER(c_ctm_source_index_ctp11, ctm_src_ctp11_e, clk_i, in_reset)
  wire ctm_src_ctp12_e = ctp_src_rise[12];
  `OCAH_FCOV_COVER(c_ctm_source_index_ctp12, ctm_src_ctp12_e, clk_i, in_reset)
  wire ctm_src_ctp13_e = ctp_src_rise[13];
  `OCAH_FCOV_COVER(c_ctm_source_index_ctp13, ctm_src_ctp13_e, clk_i, in_reset)
  wire ctm_src_ctp14_e = ctp_src_rise[14];
  `OCAH_FCOV_COVER(c_ctm_source_index_ctp14, ctm_src_ctp14_e, clk_i, in_reset)
  wire ctm_src_ctp15_e = ctp_src_rise[15];
  `OCAH_FCOV_COVER(c_ctm_source_index_ctp15, ctm_src_ctp15_e, clk_i, in_reset)
  wire ctm_src_int0_e = int_src_rise[0];
  `OCAH_FCOV_COVER(c_ctm_source_index_int0, ctm_src_int0_e, clk_i, in_reset)
  wire ctm_src_int1_e = int_src_rise[1];
  `OCAH_FCOV_COVER(c_ctm_source_index_int1, ctm_src_int1_e, clk_i, in_reset)
  wire ctm_src_int2_e = int_src_rise[2];
  `OCAH_FCOV_COVER(c_ctm_source_index_int2, ctm_src_int2_e, clk_i, in_reset)
  wire ctm_src_int3_e = int_src_rise[3];
  `OCAH_FCOV_COVER(c_ctm_source_index_int3, ctm_src_int3_e, clk_i, in_reset)
  wire ctm_src_int4_e = int_src_rise[4];
  `OCAH_FCOV_COVER(c_ctm_source_index_int4, ctm_src_int4_e, clk_i, in_reset)
  wire ctm_src_int5_e = int_src_rise[5];
  `OCAH_FCOV_COVER(c_ctm_source_index_int5, ctm_src_int5_e, clk_i, in_reset)
  wire ctm_src_int6_e = int_src_rise[6];
  `OCAH_FCOV_COVER(c_ctm_source_index_int6, ctm_src_int6_e, clk_i, in_reset)
  wire ctm_src_int7_e = int_src_rise[7];
  `OCAH_FCOV_COVER(c_ctm_source_index_int7, ctm_src_int7_e, clk_i, in_reset)
  wire ctm_src_int8_e = int_src_rise[8];
  `OCAH_FCOV_COVER(c_ctm_source_index_int8, ctm_src_int8_e, clk_i, in_reset)
  wire ctm_src_int9_e = int_src_rise[9];
  `OCAH_FCOV_COVER(c_ctm_source_index_int9, ctm_src_int9_e, clk_i, in_reset)
  wire ctm_dst_ctp0_e = ctp_dst_rise[0];
  `OCAH_FCOV_COVER(c_ctm_dest_index_ctp0, ctm_dst_ctp0_e, clk_i, in_reset)
  wire ctm_dst_ctp1_e = ctp_dst_rise[1];
  `OCAH_FCOV_COVER(c_ctm_dest_index_ctp1, ctm_dst_ctp1_e, clk_i, in_reset)
  wire ctm_dst_ctp2_e = ctp_dst_rise[2];
  `OCAH_FCOV_COVER(c_ctm_dest_index_ctp2, ctm_dst_ctp2_e, clk_i, in_reset)
  wire ctm_dst_ctp3_e = ctp_dst_rise[3];
  `OCAH_FCOV_COVER(c_ctm_dest_index_ctp3, ctm_dst_ctp3_e, clk_i, in_reset)
  wire ctm_dst_ctp4_e = ctp_dst_rise[4];
  `OCAH_FCOV_COVER(c_ctm_dest_index_ctp4, ctm_dst_ctp4_e, clk_i, in_reset)
  wire ctm_dst_ctp5_e = ctp_dst_rise[5];
  `OCAH_FCOV_COVER(c_ctm_dest_index_ctp5, ctm_dst_ctp5_e, clk_i, in_reset)
  wire ctm_dst_ctp6_e = ctp_dst_rise[6];
  `OCAH_FCOV_COVER(c_ctm_dest_index_ctp6, ctm_dst_ctp6_e, clk_i, in_reset)
  wire ctm_dst_ctp7_e = ctp_dst_rise[7];
  `OCAH_FCOV_COVER(c_ctm_dest_index_ctp7, ctm_dst_ctp7_e, clk_i, in_reset)
  wire ctm_dst_ctp8_e = ctp_dst_rise[8];
  `OCAH_FCOV_COVER(c_ctm_dest_index_ctp8, ctm_dst_ctp8_e, clk_i, in_reset)
  wire ctm_dst_ctp9_e = ctp_dst_rise[9];
  `OCAH_FCOV_COVER(c_ctm_dest_index_ctp9, ctm_dst_ctp9_e, clk_i, in_reset)
  wire ctm_dst_ctp10_e = ctp_dst_rise[10];
  `OCAH_FCOV_COVER(c_ctm_dest_index_ctp10, ctm_dst_ctp10_e, clk_i, in_reset)
  wire ctm_dst_ctp11_e = ctp_dst_rise[11];
  `OCAH_FCOV_COVER(c_ctm_dest_index_ctp11, ctm_dst_ctp11_e, clk_i, in_reset)
  wire ctm_dst_ctp12_e = ctp_dst_rise[12];
  `OCAH_FCOV_COVER(c_ctm_dest_index_ctp12, ctm_dst_ctp12_e, clk_i, in_reset)
  wire ctm_dst_ctp13_e = ctp_dst_rise[13];
  `OCAH_FCOV_COVER(c_ctm_dest_index_ctp13, ctm_dst_ctp13_e, clk_i, in_reset)
  wire ctm_dst_ctp14_e = ctp_dst_rise[14];
  `OCAH_FCOV_COVER(c_ctm_dest_index_ctp14, ctm_dst_ctp14_e, clk_i, in_reset)
  wire ctm_dst_ctp15_e = ctp_dst_rise[15];
  `OCAH_FCOV_COVER(c_ctm_dest_index_ctp15, ctm_dst_ctp15_e, clk_i, in_reset)
  wire ctm_dst_int0_e = int_dst_rise[0];
  `OCAH_FCOV_COVER(c_ctm_dest_index_int0, ctm_dst_int0_e, clk_i, in_reset)
  wire ctm_dst_int1_e = int_dst_rise[1];
  `OCAH_FCOV_COVER(c_ctm_dest_index_int1, ctm_dst_int1_e, clk_i, in_reset)
  wire ctm_dst_int2_e = int_dst_rise[2];
  `OCAH_FCOV_COVER(c_ctm_dest_index_int2, ctm_dst_int2_e, clk_i, in_reset)
  wire ctm_dst_int3_e = int_dst_rise[3];
  `OCAH_FCOV_COVER(c_ctm_dest_index_int3, ctm_dst_int3_e, clk_i, in_reset)
  wire ctm_dst_int4_e = int_dst_rise[4];
  `OCAH_FCOV_COVER(c_ctm_dest_index_int4, ctm_dst_int4_e, clk_i, in_reset)
  wire ctm_dst_int5_e = int_dst_rise[5];
  `OCAH_FCOV_COVER(c_ctm_dest_index_int5, ctm_dst_int5_e, clk_i, in_reset)
  wire ctm_dst_int6_e = int_dst_rise[6];
  `OCAH_FCOV_COVER(c_ctm_dest_index_int6, ctm_dst_int6_e, clk_i, in_reset)
  wire ctm_dst_int7_e = int_dst_rise[7];
  `OCAH_FCOV_COVER(c_ctm_dest_index_int7, ctm_dst_int7_e, clk_i, in_reset)
  wire ctm_dst_int8_e = int_dst_rise[8];
  `OCAH_FCOV_COVER(c_ctm_dest_index_int8, ctm_dst_int8_e, clk_i, in_reset)
  wire ctm_dst_int9_e = int_dst_rise[9];
  `OCAH_FCOV_COVER(c_ctm_dest_index_int9, ctm_dst_int9_e, clk_i, in_reset)

`ifndef VERILATOR
  // ------------------------------------------------------------------
  // Commercial-simulator covergroups mirroring the cover-property bins.
  // ------------------------------------------------------------------
  // One port index space for both CTM index coverpoints: CTP ports occupy
  // 0-15 and internal CTs 16-25, one bin per port as in the c_ctm_*_index_*
  // cover properties.
  localparam int unsigned IntPortBase = 16;

  // The mode and inversion bins sample a CONFIG write that strobes byte 0,
  // the stretch bins a STRETCH_MULT write that strobes both field bytes.
  covergroup cg_ctp with function sample (
      logic config_write,
      logic mode_p2p,
      logic inverted,
      logic stretch_write,
      logic [1:0] stretch_class
  );
    option.per_instance = 1;
    cp_mode: coverpoint mode_p2p iff (config_write);
    cp_inversion: coverpoint inverted iff (config_write);
    cp_stretch: coverpoint stretch_class iff (stretch_write) {
      bins stretch_min = {2'd0}; bins stretch_mid = {2'd1}; bins stretch_max = {2'd2};
    }
  endgroup

  // Wire-OR receive events: the sense of the wire the trigger came from and
  // how many ports delivered it in the same cycle.
  covergroup cg_ctp_wire_or_rx with function sample (logic inverted, logic shared);
    option.per_instance = 1;
    cp_sense: coverpoint inverted {bins normal = {1'b0}; bins inverted = {1'b1};}
    cp_listeners: coverpoint shared {bins one = {1'b0}; bins shared_wire = {1'b1};}
  endgroup

  covergroup cg_ctm with function sample (
      logic src_event,
      logic src_is_ctp,
      logic [4:0] src_idx,
      logic dst_event,
      logic dst_is_ctp,
      logic [4:0] dst_idx
  );
    option.per_instance = 1;
    cp_source_type: coverpoint src_is_ctp iff (src_event);
    cp_dest_type: coverpoint dst_is_ctp iff (dst_event);
    cp_source_index: coverpoint src_idx iff (src_event) {
      bins ctp[] = {[0 : 15]}; bins internal[] = {[IntPortBase : IntPortBase + 9]};
    }
    cp_dest_index: coverpoint dst_idx iff (dst_event) {
      bins ctp[] = {[0 : 15]}; bins internal[] = {[IntPortBase : IntPortBase + 9]};
    }
  endgroup

  // Routes the matrix carried: a destination rise credited to the one source
  // that rose within RouteWindowCycles and that the destination's
  // CT_SRC[destination] CONFIG_0 CT_DST_SELECT mask, shadowed from the CSR
  // writes under their byte strobes, selects; a rise with two such sources
  // credits no route. The crosses cover CLA-to-CTP and CTP-to-CLA routes.
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

  localparam int unsigned CtmPorts = int'(CROSS_TRIGGER_NETWORK_CTM_CT_SRC_NUM);
  localparam int unsigned CtmStride = int'(CROSS_TRIGGER_NETWORK_CTM_CT_SRC_STRIDE);
  localparam logic [31:0] CtmBase = 32'(CROSS_TRIGGER_NETWORK_CTM_BASE_ADDR);
  localparam int unsigned RouteWindowCycles = 32;

  wire [31:0] ctm_csr_off = aw_word_addr - CtmBase;
  wire ctm_select_write = wr_pair && (ctm_csr_off < 32'(CtmPorts * CtmStride))
      && ((ctm_csr_off % CtmStride) == 0);
  wire [31:0] wr_biten = {{8{wr_strb[3]}}, {8{wr_strb[2]}}, {8{wr_strb[1]}}, {8{wr_strb[0]}}};
  wire [CtmPorts-1:0] route_src_rise = {int_src_rise, ctp_src_rise};
  wire [CtmPorts-1:0] route_dst_rise = {int_dst_rise, ctp_dst_rise};
  logic [CtmPorts-1:0] ctm_select_q[CtmPorts];
  logic [5:0] route_src_age_q[CtmPorts];

  always_ff @(posedge clk_i) begin
    for (int s = 0; s < CtmPorts; s++) begin
      if (in_reset) begin
        ctm_select_q[s] <= '0;
        route_src_age_q[s] <= '0;
      end else begin
        if (ctm_select_write && (ctm_csr_off / CtmStride == s))
          ctm_select_q[s] <= (ctm_select_q[s] & ~wr_biten[CtmPorts-1:0])
              | (wr_data[CtmPorts-1:0] & wr_biten[CtmPorts-1:0]);
        if (route_src_rise[s]) route_src_age_q[s] <= 6'(RouteWindowCycles);
        else if (route_src_age_q[s] != 6'd0) route_src_age_q[s] <= route_src_age_q[s] - 6'd1;
      end
    end
  end

  // The one recent source destination `d` selects, or -1 for none or several.
  function automatic int route_source(int d);
    int src = -1;
    for (int s = 0; s < CtmPorts; s++) begin
      if ((route_src_age_q[s] != 6'd0) && ctm_select_q[d][s]) begin
        if (src >= 0) return -1;
        src = s;
      end
    end
    return src;
  endfunction

  cg_ctp u_cg_ctp = new();
  cg_ctp_wire_or_rx u_cg_ctp_wire_or_rx = new();
  cg_ctm u_cg_ctm = new();
  cg_ctm_route u_cg_ctm_route = new();

  always_ff @(posedge clk_i) begin
    if (ctp_config_fields_write) begin
      u_cg_ctp.sample(1'b1, wr_data[0], wr_data[1], 1'b0, 2'd0);
    end
    if (!in_reset) begin
      for (int i = 0; i < 16; i++) begin
        if (ctp_wire_or_rx_rise[i]) begin
          u_cg_ctp_wire_or_rx.sample(ctp_req_out_dout_i[i], ctp_wire_or_rx_shared_e);
        end
      end
    end
    if (ctp_stretch_field_write) begin
      u_cg_ctp.sample(1'b0, 1'b0, 1'b0, 1'b1,
                      (stretch_val == 16'd0) ? 2'd0 : ((stretch_val >= 16'd15) ? 2'd2 : 2'd1));
    end
    // A destination rises one or more clocks after its source: the matrix
    // registers its output and the CTP core adds synchroniser and handshake
    // stages, so no single edge carries both ends of a route.
    if (!in_reset) begin
      for (int i = 0; i < 16; i++) begin
        if (ctp_src_rise[i]) u_cg_ctm.sample(1'b1, 1'b1, 5'(i), 1'b0, 1'b0, 5'd0);
        if (ctp_dst_rise[i]) u_cg_ctm.sample(1'b0, 1'b0, 5'd0, 1'b1, 1'b1, 5'(i));
      end
      for (int i = 0; i < 10; i++) begin
        if (int_src_rise[i]) begin
          u_cg_ctm.sample(1'b1, 1'b0, 5'(IntPortBase + i), 1'b0, 1'b0, 5'd0);
        end
        if (int_dst_rise[i]) begin
          u_cg_ctm.sample(1'b0, 1'b0, 5'd0, 1'b1, 1'b0, 5'(IntPortBase + i));
        end
      end
      for (int d = 0; d < CtmPorts; d++) begin
        if (route_dst_rise[d] && (route_source(d) >= 0)) begin
          u_cg_ctm_route.sample(5'(route_source(d)), 5'(d));
        end
      end
    end
  end
`endif

endmodule : dtp_xtrig_fcov
