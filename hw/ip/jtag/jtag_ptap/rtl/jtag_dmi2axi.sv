// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// Give a PTAP DTMCS TDR and DMI TDR access to an AXI4 or AXI4-Lite manager port.
//
// The DMI TDR is the 41-bit RISC-V debug dmi register with abits = 7. It drives tdr2axi, whose
// Debug Module registers and System Bus Access engine issue the AXI transfers. The DTMCS TDR
// is the 32-bit dtmcs register a RISC-V debugger reads before it uses dmi:
//
//   [31:18] zero   [17] dmihardreset (ignored)   [16] dmireset (write 1)   [15] zero
//   [14:12] idle   [11:10] dmistat   [9:4] abits   [3:0] version
//
// A DTMCS update with dmireset set gives tdr2axi one update with op 3, its clear of the sticky
// DMI status. That update carries the address and data tdr2axi currently holds, because
// tdr2axi loads both fields on every update it accepts while idle.
//
// The two TDR cells reset from the scan control; tdr2axi resets from rst_ni only, which it
// synchronizes into each of its clock domains.
//
// security_disable_i steers every request of the bridge to an error slave that completes it
// with DECERR, so no transfer reaches axi_req_o while the bridge is disabled. The select
// changes only while the bridge presents no AW or AR request, which the demultiplexer
// requires; a transfer accepted before the change completes on the port that took it.
//
// AXI4 requests leave with AxBURST INCR. They are single-beat, and tdr2axi marks them FIXED.

module jtag_dmi2axi
  import prim_jtag_pkg::jtag_scan_ctrl_t;
#(
  parameter bit IS_AXI4_LITE = 1'b0,  // 1: AXI4-Lite manager port; 0: AXI4 manager port.
  parameter int unsigned AXI_ID_WIDTH = 1,  // AXI ID width of the manager port; AXI4 only.
  parameter int unsigned AXI_USER_WIDTH = 1,  // AXI user width of the manager port; AXI4 only.
  parameter axi_pkg::prot_t AXI_PROT = 3'b000,  // AxPROT of every transfer.
  parameter axi_pkg::cache_t AXI_CACHE = 4'b0010,  // AxCACHE of every transfer; AXI4 only.
  parameter type axi_req_t = logic,  // Request type of the manager port, built with
                                     // AXI_TYPEDEF_ALL or AXI_LITE_TYPEDEF_ALL. Its data
                                     // width is 32 or 64.
  parameter type axi_resp_t = logic  // Response type of the manager port.
) (
  input  jtag_scan_ctrl_t dtmcs_scan_ctrl_i,  // DR scan control with select for the DTMCS TDR.
  input  jtag_scan_ctrl_t dmi_scan_ctrl_i,  // DR scan control with select for the DMI TDR.
  input  logic            scan_in_i,  // Scan data in (TDI) of both TDRs.
  output logic            dtmcs_scan_out_o,  // Scan data out of the DTMCS TDR.
  output logic            dmi_scan_out_o,  // Scan data out of the DMI TDR.

  input  logic            clk_i,  // AXI clock.
  input  logic            rst_ni,  // Async reset of the bridge, active-low. A system reset
                                   // here also resets the AXI target of the bridge.
  input  logic            test_en_i,  // DFT test mode, active-high; selects scan_rst_ni.
  input  logic            scan_rst_ni,  // Scan reset used in test mode, active-low.

  input  logic            security_disable_i,  // Active-high disable in the clk_i domain;
                                               // requests complete with DECERR.

  output axi_req_t        axi_req_o,  // AXI request to the target.
  input  axi_resp_t       axi_resp_i  // AXI response from the target.
);

  `include "ocah_assert.svh"
  `include "axi/typedef.svh"

  localparam int unsigned DmiWidth = 41;
  localparam int unsigned DtmcsWidth = 32;
  localparam int unsigned DtmcsDmiresetBit = 16;

  localparam logic [3:0] DtmcsVersion = 4'd1;  // Debug specification 0.13 and 1.0.
  localparam logic [5:0] DtmcsAbits = 6'd7;
  // A DMI operation crosses two clock domains in each direction and needs more Run-Test/Idle
  // cycles than the field can state, so the hint is the largest value.
  localparam logic [2:0] DtmcsIdle = 3'd7;
  localparam logic [1:0] DmiOpClear = 2'd3;

  localparam int unsigned DemuxTarget = 0;
  localparam int unsigned DemuxErrSlv = 1;

  localparam int unsigned AddrWidth = $bits(axi_req_o.aw.addr);
  localparam int unsigned DataWidth = $bits(axi_req_o.w.data);

  // tdr2axi and its Debug Module sources accept only these widths.
  `OCAH_ASSERT_STATIC(ValidDataWidth_A, DataWidth == 32 || DataWidth == 64)
  `OCAH_ASSERT_STATIC(ValidAddrWidth_A, AddrWidth >= $unsigned($clog2(DataWidth / 8))
                      && AddrWidth <= 64)

  typedef logic [AddrWidth-1:0] addr_t;
  typedef logic [DataWidth-1:0] data_t;
  typedef logic [DataWidth/8-1:0] strb_t;
  typedef logic [AXI_ID_WIDTH-1:0] bridge_id_t;
  typedef logic [AXI_USER_WIDTH-1:0] bridge_user_t;

  // The bridge types of both port variants are at module scope. Not every simulator lets a
  // struct type declared in a generate block reach another module through a type parameter.
  `AXI_LITE_TYPEDEF_ALL(bridge_lite, addr_t, data_t, strb_t)
  `AXI_TYPEDEF_ALL(bridge_full, addr_t, bridge_id_t, data_t, strb_t, bridge_user_t)

  localparam data_t ErrSlvReadData = data_t'(64'hBADCAB1E_BADCAB1E);

  //--------------------------------------------------------------------------
  // TDR cells (TCK domain)
  //--------------------------------------------------------------------------
  logic [DmiWidth-1:0] dmi_capture, dmi_update, dmi_bridge_tdr;
  logic [DtmcsWidth-1:0] dtmcs_capture, dtmcs_update;
  logic dmi_update_en, dmi_capture_en, dtmcs_dmireset;

  assign dtmcs_capture = {
    14'h0, 1'b0, 1'b0, 1'b0, DtmcsIdle, dmi_capture[1:0], DtmcsAbits, DtmcsVersion
  };

  prim_jtag_scan_reg #(
    .WIDTH(DtmcsWidth)
  ) u_dtmcs_scan_reg (
    .scan_ctrl_i(dtmcs_scan_ctrl_i),
    .scan_in_i  (scan_in_i),
    .scan_out_o (dtmcs_scan_out_o),
    .data_in_i  (dtmcs_capture),
    .data_out_o (dtmcs_update)
  );

  prim_jtag_scan_reg #(
    .WIDTH(DmiWidth)
  ) u_dmi_scan_reg (
    .scan_ctrl_i(dmi_scan_ctrl_i),
    .scan_in_i  (scan_in_i),
    .scan_out_o (dmi_scan_out_o),
    .data_in_i  (dmi_capture),
    .data_out_o (dmi_update)
  );

  // The update registers load on the falling TCK edge inside Update-DR, so each strobe below
  // is high with stable data for the one rising TCK edge that leaves Update-DR.
  assign dmi_capture_en = dmi_scan_ctrl_i.select && dmi_scan_ctrl_i.capture_en;
  assign dmi_update_en = dmi_scan_ctrl_i.select && dmi_scan_ctrl_i.update_en;
  assign dtmcs_dmireset = dtmcs_scan_ctrl_i.select && dtmcs_scan_ctrl_i.update_en &&
                          dtmcs_update[DtmcsDmiresetBit];

  assign dmi_bridge_tdr = dtmcs_dmireset ? {dmi_capture[DmiWidth-1:2], DmiOpClear} : dmi_update;

  logic unused_dtmcs_update;
  assign unused_dtmcs_update = ^{
    dtmcs_update[DtmcsWidth-1:DtmcsDmiresetBit+1], dtmcs_update[DtmcsDmiresetBit-1:0]
  };

  //--------------------------------------------------------------------------
  // Security select (clk_i domain)
  //--------------------------------------------------------------------------
  logic bridge_requesting;
  logic security_select_q;

  always_ff @(posedge clk_i or negedge rst_ni) begin
    if (!rst_ni) begin
      security_select_q <= 1'b1;
    end else if (!bridge_requesting) begin
      security_select_q <= security_disable_i;
    end
  end

  //--------------------------------------------------------------------------
  // Bridge, security demultiplexer and error slave
  //--------------------------------------------------------------------------
  if (IS_AXI4_LITE) begin : gen_axi_lite
    `OCAH_ASSERT_STATIC(ReqTypeMatches_A, $bits(bridge_lite_req_t) == $bits(axi_req_t))
    `OCAH_ASSERT_STATIC(RespTypeMatches_A, $bits(bridge_lite_resp_t) == $bits(axi_resp_t))

    bridge_lite_req_t        bridge_req;
    bridge_lite_resp_t       bridge_resp;
    bridge_lite_req_t  [1:0] demux_req;
    bridge_lite_resp_t [1:0] demux_resp;

    tdr2axi #(
      .USE_AXI_LITE  (1'b1),
      .AXI_ADDR_WIDTH(AddrWidth),
      .AXI_DATA_WIDTH(DataWidth),
      .AXI_PROT      (AXI_PROT),
      .axi_req_t     (bridge_lite_req_t),
      .axi_rsp_t     (bridge_lite_resp_t)
    ) u_tdr2axi (
      .i_clk            (clk_i),
      .i_arst_n         (rst_ni),
      .i_test_mode      (test_en_i),
      .i_arst_scan_n    (scan_rst_ni),
      .i_tck            (dmi_scan_ctrl_i.tck),
      .i_dmi_tdr        (dmi_bridge_tdr),
      .i_dmi_tdr_capture(dmi_capture_en),
      .i_dmi_tdr_update (dmi_update_en || dtmcs_dmireset),
      .o_dmi_tdr        (dmi_capture),
      .o_axi_req        (bridge_req),
      .i_axi_rsp        (bridge_resp)
    );

    assign bridge_requesting = bridge_req.aw_valid || bridge_req.ar_valid;

    axi_lite_demux #(
      .aw_chan_t (bridge_lite_aw_chan_t),
      .w_chan_t  (bridge_lite_w_chan_t),
      .b_chan_t  (bridge_lite_b_chan_t),
      .ar_chan_t (bridge_lite_ar_chan_t),
      .r_chan_t  (bridge_lite_r_chan_t),
      .axi_req_t (bridge_lite_req_t),
      .axi_resp_t(bridge_lite_resp_t),
      .NoMstPorts(2),
      .MaxTrans  (2)
    ) u_security_demux (
      .clk_i          (clk_i),
      .rst_ni         (rst_ni),
      .test_i         (test_en_i),
      .slv_req_i      (bridge_req),
      .slv_aw_select_i(security_select_q),
      .slv_ar_select_i(security_select_q),
      .slv_resp_o     (bridge_resp),
      .mst_reqs_o     (demux_req),
      .mst_resps_i    (demux_resp)
    );

    prim_axi_lite_err_slv #(
      .AXI_ADDR_WIDTH(AddrWidth),
      .AXI_DATA_WIDTH(DataWidth),
      .axil_req_t    (bridge_lite_req_t),
      .axil_resp_t   (bridge_lite_resp_t),
      .RESP          (axi_pkg::RESP_DECERR),
      .RESP_WIDTH    (DataWidth),
      .RESP_DATA     (ErrSlvReadData)
    ) u_security_err_slv (
      .clk_i      (clk_i),
      .rst_ni     (rst_ni),
      .test_en_i  (test_en_i),
      .axil_req_i (demux_req[DemuxErrSlv]),
      .axil_resp_o(demux_resp[DemuxErrSlv])
    );

    assign axi_req_o = axi_req_t'(demux_req[DemuxTarget]);
    assign demux_resp[DemuxTarget] = bridge_lite_resp_t'(axi_resp_i);

    axi_pkg::cache_t unused_axi_cache;
    assign unused_axi_cache = AXI_CACHE;
  end else begin : gen_axi
    `OCAH_ASSERT_STATIC(ReqTypeMatches_A, $bits(bridge_full_req_t) == $bits(axi_req_t))
    `OCAH_ASSERT_STATIC(RespTypeMatches_A, $bits(bridge_full_resp_t) == $bits(axi_resp_t))

    bridge_full_req_t        bridge_req;
    bridge_full_resp_t       bridge_resp;
    bridge_full_req_t  [1:0] demux_req;
    bridge_full_resp_t [1:0] demux_resp;
    bridge_full_req_t        target_req;

    tdr2axi #(
      .USE_AXI_LITE  (1'b0),
      .AXI_ADDR_WIDTH(AddrWidth),
      .AXI_DATA_WIDTH(DataWidth),
      .AXI_PROT      (AXI_PROT),
      .AXI_CACHE     (AXI_CACHE),
      .axi_req_t     (bridge_full_req_t),
      .axi_rsp_t     (bridge_full_resp_t)
    ) u_tdr2axi (
      .i_clk            (clk_i),
      .i_arst_n         (rst_ni),
      .i_test_mode      (test_en_i),
      .i_arst_scan_n    (scan_rst_ni),
      .i_tck            (dmi_scan_ctrl_i.tck),
      .i_dmi_tdr        (dmi_bridge_tdr),
      .i_dmi_tdr_capture(dmi_capture_en),
      .i_dmi_tdr_update (dmi_update_en || dtmcs_dmireset),
      .o_dmi_tdr        (dmi_capture),
      .o_axi_req        (bridge_req),
      .i_axi_rsp        (bridge_resp)
    );

    assign bridge_requesting = bridge_req.aw_valid || bridge_req.ar_valid;

    axi_demux #(
      .AxiIdWidth (AXI_ID_WIDTH),
      .AtopSupport(1'b0),
      .aw_chan_t  (bridge_full_aw_chan_t),
      .w_chan_t   (bridge_full_w_chan_t),
      .b_chan_t   (bridge_full_b_chan_t),
      .ar_chan_t  (bridge_full_ar_chan_t),
      .r_chan_t   (bridge_full_r_chan_t),
      .axi_req_t  (bridge_full_req_t),
      .axi_resp_t (bridge_full_resp_t),
      .NoMstPorts (2),
      .MaxTrans   (2),
      .AxiLookBits(1),
      .UniqueIds  (1'b0)
    ) u_security_demux (
      .clk_i          (clk_i),
      .rst_ni         (rst_ni),
      .test_i         (test_en_i),
      .sel_hash_i     (2'd0),
      .slv_req_i      (bridge_req),
      .slv_aw_select_i(security_select_q),
      .slv_ar_select_i(security_select_q),
      .slv_resp_o     (bridge_resp),
      .mst_reqs_o     (demux_req),
      .mst_resps_i    (demux_resp)
    );

    axi_err_slv #(
      .AxiIdWidth(AXI_ID_WIDTH),
      .axi_req_t (bridge_full_req_t),
      .axi_resp_t(bridge_full_resp_t),
      .Resp      (axi_pkg::RESP_DECERR),
      .RespWidth (DataWidth),
      .RespData  (ErrSlvReadData),
      .ATOPs     (1'b0),
      .MaxTrans  (1)
    ) u_security_err_slv (
      .clk_i     (clk_i),
      .rst_ni    (rst_ni),
      .test_i    (test_en_i),
      .slv_req_i (demux_req[DemuxErrSlv]),
      .slv_resp_o(demux_resp[DemuxErrSlv])
    );

    always_comb begin
      target_req          = demux_req[DemuxTarget];
      target_req.aw.burst = axi_pkg::BURST_INCR;
      target_req.ar.burst = axi_pkg::BURST_INCR;
    end

    assign axi_req_o = axi_req_t'(target_req);
    assign demux_resp[DemuxTarget] = bridge_full_resp_t'(axi_resp_i);
  end

endmodule : jtag_dmi2axi
