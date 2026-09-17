// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// Cross-trigger functional coverage (ctp_cg, ctm_cg).
//
// One instance in the shared tb_top serves both flows. Every bin derives
// from the flattened cross-trigger pins and the XTRIG CSR AXI-Lite write
// channel in the system-clock domain: CTP mode/inversion/stretch classes
// decode the CSR writes, the P2P phases and the CTM source/destination
// index bins follow the GPIO and matrix handshake pins.
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
  input wire        axil_wvalid_i,
  input wire        axil_wready_i,

  // Cross-trigger matrix and CTP GPIO pins
  input wire [9:0]  ctm_src_req_i,
  input wire [9:0]  ctm_dst_req_i,
  input wire [15:0] ctp_req_out_dout_i,
  input wire [15:0] ctp_req_out_dout_en_i,
  input wire [15:0] ctp_req_in_din_i,
  input wire [15:0] ctp_ack_in_din_i
);

  // CSR windows of the cross-trigger network (cross_trigger_network_pkg).
  localparam logic [31:0] CtpBase = 32'(cross_trigger_network_pkg::CSR_ADDR_CTM_SIZE);
  localparam int unsigned CtpStride = cross_trigger_network_pkg::CSR_ADDR_CTP_SIZE;
  localparam int unsigned NumCtp = 16;
  localparam logic [31:0] CtpEnd = CtpBase + 32'(NumCtp * CtpStride);

  wire in_reset = (rst_ni !== 1'b1);

  // ------------------------------------------------------------------
  // CSR write decode: capture AW address, classify at the W handshake.
  // ------------------------------------------------------------------
  logic [31:0] awaddr_q;
  logic aw_seen_q;
  wire aw_hs = axil_awvalid_i && axil_awready_i;
  wire w_hs = axil_wvalid_i && axil_wready_i;
  always_ff @(posedge clk_i) begin
    if (aw_hs) begin
      awaddr_q <= axil_awaddr_i;
      aw_seen_q <= 1'b1;
    end else if (w_hs) begin
      aw_seen_q <= 1'b0;
    end
  end
  wire ctp_csr_write = w_hs && aw_seen_q && (awaddr_q >= CtpBase)
      && (awaddr_q < CtpEnd);
  wire [3:0] ctp_csr_off = awaddr_q[3:0];
  wire ctp_config_write = ctp_csr_write && (ctp_csr_off == 4'h0);
  wire ctp_stretch_write = ctp_csr_write && (ctp_csr_off == 4'h8);

  // ------------------------------------------------------------------
  // ctp_cg — mode, inversion, stretch classes, and P2P phases.
  // ------------------------------------------------------------------
  wire ctp_mode_wire_or_e = ctp_config_write && !axil_wdata_i[0];
  wire ctp_mode_p2p_e = ctp_config_write && axil_wdata_i[0];
  wire ctp_inversion_normal_e = ctp_config_write && !axil_wdata_i[1];
  wire ctp_inversion_inverted_e = ctp_config_write && axil_wdata_i[1];
  wire ctp_csr_reset_e = ctp_config_write && axil_wdata_i[2];
  wire [15:0] stretch_val = axil_wdata_i[15:0];
  wire ctp_stretch_min_e = ctp_stretch_write && (stretch_val == 16'd0);
  wire ctp_stretch_max_e = ctp_stretch_write && (stretch_val >= 16'd15);
  wire ctp_stretch_mid_e = ctp_stretch_write && (stretch_val != 16'd0)
      && (stretch_val < 16'd15);
  `OCAH_FCOV_COVER(c_ctp_mode_wire_or, ctp_mode_wire_or_e, clk_i, in_reset)
  `OCAH_FCOV_COVER(c_ctp_mode_p2p, ctp_mode_p2p_e, clk_i, in_reset)
  `OCAH_FCOV_COVER(c_ctp_inversion_normal, ctp_inversion_normal_e, clk_i, in_reset)
  `OCAH_FCOV_COVER(c_ctp_inversion_inverted, ctp_inversion_inverted_e, clk_i, in_reset)
  `OCAH_FCOV_COVER(c_ctp_stretch_min, ctp_stretch_min_e, clk_i, in_reset)
  `OCAH_FCOV_COVER(c_ctp_stretch_mid, ctp_stretch_mid_e, clk_i, in_reset)
  `OCAH_FCOV_COVER(c_ctp_stretch_max, ctp_stretch_max_e, clk_i, in_reset)

  wire [15:0] ctp_req_out_active = ctp_req_out_dout_i & ctp_req_out_dout_en_i;
  wire any_req_out = |ctp_req_out_active;
  wire any_ack_in = |ctp_ack_in_din_i;
  logic had_req_out_q, csr_reset_pending_q;
  always_ff @(posedge clk_i) begin
    if (any_req_out) had_req_out_q <= 1'b1;
    if (ctp_csr_reset_e) csr_reset_pending_q <= 1'b1;
    else if (any_req_out) csr_reset_pending_q <= 1'b0;
  end
  wire ctp_p2p_request_e = any_req_out;
  wire ctp_p2p_ack_e = any_ack_in && any_req_out;
  wire ctp_p2p_idle_e = !any_req_out && !any_ack_in && had_req_out_q;
  wire ctp_p2p_reset_recovery_e = any_req_out && csr_reset_pending_q;
  `OCAH_FCOV_COVER(c_ctp_p2p_state_request_phase, ctp_p2p_request_e, clk_i, in_reset)
  `OCAH_FCOV_COVER(c_ctp_p2p_state_acknowledge_phase, ctp_p2p_ack_e, clk_i, in_reset)
  `OCAH_FCOV_COVER(c_ctp_p2p_state_idle, ctp_p2p_idle_e, clk_i, in_reset)
  `OCAH_FCOV_COVER(c_ctp_p2p_state_reset_recovery, ctp_p2p_reset_recovery_e, clk_i, in_reset)

  // ------------------------------------------------------------------
  // ctm_cg — source/destination types, fanout classes, and the per-port
  // index bins. Source events: an external CTP request arriving
  // (ctp_req_in_din rise) or an internal CT request (ctm_dst_req rise).
  // Destination events: the matrix driving a CTP output (req_out rise) or
  // an internal CT (ctm_src_req rise).
  // ------------------------------------------------------------------
  logic [15:0] ctp_req_in_q, ctp_req_out_q;
  logic [9:0] ctm_dst_req_q, ctm_src_req_q;
  always_ff @(posedge clk_i) begin
    ctp_req_in_q <= ctp_req_in_din_i;
    ctp_req_out_q <= ctp_req_out_active;
    ctm_dst_req_q <= ctm_dst_req_i;
    ctm_src_req_q <= ctm_src_req_i;
  end
  wire [15:0] ctp_src_rise = ctp_req_in_din_i & ~ctp_req_in_q;
  wire [15:0] ctp_dst_rise = ctp_req_out_active & ~ctp_req_out_q;
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
      6'($countones(ctp_req_out_active)) + 6'($countones(ctm_src_req_i));
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

  covergroup cg_ctp with function sample (
      logic mode_p2p, logic inverted, logic [1:0] stretch_class
  );
    option.per_instance = 1;
    cp_mode: coverpoint mode_p2p;
    cp_inversion: coverpoint inverted;
    cp_stretch: coverpoint stretch_class {
      bins stretch_min = {2'd0}; bins stretch_mid = {2'd1}; bins stretch_max = {2'd2};
    }
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

  cg_ctp u_cg_ctp = new();
  cg_ctm u_cg_ctm = new();

  always_ff @(posedge clk_i) begin
    if (ctp_config_write) begin
      u_cg_ctp.sample(axil_wdata_i[0], axil_wdata_i[1], 2'd1);
    end
    if (ctp_stretch_write) begin
      u_cg_ctp.sample(1'b0, 1'b0,
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
    end
  end
`endif

endmodule : dtp_xtrig_fcov
