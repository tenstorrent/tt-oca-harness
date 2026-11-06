// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// prim_axil_addr_demux IP-level testbench top for the cocotb flow.
//
// One demux holds five ranges in the 4 KiB page at WindowBase, each an aligned power of two:
// two adjacent ranges, one twice their size, one small and one past a gap. Each range is
// answered by a prim_axi_lite_err_slv set to OKAY whose read data is RangeTag | range index,
// so a read names the range that answered.
// range_aw_count[i] counts the write addresses range i accepts, so a test can tell which
// range a write reached. The demux's AXI-Lite slave port is exposed flattened (axil_*) for
// the shared AXI VIP's master. Clock and reset are driven from cocotb.

`timescale 1ns / 1ps

`include "axi/typedef.svh"

module prim_axil_addr_demux_tb_top #(
  localparam int unsigned NumRanges = 5
) (
  input  wire        clk,
  input  wire        rst_n,

  input  wire        axil_awvalid,
  input  wire [31:0] axil_awaddr,
  input  wire [2:0]  axil_awprot,
  output wire        axil_awready,

  input  wire        axil_wvalid,
  input  wire [31:0] axil_wdata,
  input  wire [3:0]  axil_wstrb,
  output wire        axil_wready,

  input  wire        axil_bready,
  output wire        axil_bvalid,
  output wire [1:0]  axil_bresp,

  input  wire        axil_arvalid,
  input  wire [31:0] axil_araddr,
  input  wire [2:0]  axil_arprot,
  output wire        axil_arready,

  input  wire        axil_rready,
  output wire        axil_rvalid,
  output wire [31:0] axil_rdata,
  output wire [1:0]  axil_rresp,

  output logic [NumRanges-1:0][7:0] range_aw_count
);

  localparam logic [31:0] WindowBase = 32'hC000_C000;
  localparam logic [31:0] RangeTag = 32'h5107_0000;

  localparam logic [31:0] RangeBase[NumRanges] = '{
      WindowBase + 32'h000,
      WindowBase + 32'h080,
      WindowBase + 32'h100,
      WindowBase + 32'h200,
      WindowBase + 32'h800
  };
  localparam logic [31:0] RangeSize[NumRanges] = '{32'h80, 32'h80, 32'h100, 32'h10, 32'h200};

  typedef logic [31:0] addr_t;
  typedef logic [31:0] data_t;
  typedef logic [3:0] strb_t;
  `AXI_LITE_TYPEDEF_ALL(axil, addr_t, data_t, strb_t)

  axil_req_t                  axil_req;
  axil_resp_t                 axil_resp;
  axil_req_t  [NumRanges-1:0] range_reqs;
  axil_resp_t [NumRanges-1:0] range_resps;

  assign axil_req.aw_valid = axil_awvalid;
  assign axil_req.aw.addr  = axil_awaddr;
  assign axil_req.aw.prot  = axil_awprot;
  assign axil_awready      = axil_resp.aw_ready;

  assign axil_req.w_valid  = axil_wvalid;
  assign axil_req.w.data   = axil_wdata;
  assign axil_req.w.strb   = axil_wstrb;
  assign axil_wready       = axil_resp.w_ready;

  assign axil_req.b_ready  = axil_bready;
  assign axil_bvalid       = axil_resp.b_valid;
  assign axil_bresp        = axil_resp.b.resp;

  assign axil_req.ar_valid = axil_arvalid;
  assign axil_req.ar.addr  = axil_araddr;
  assign axil_req.ar.prot  = axil_arprot;
  assign axil_arready      = axil_resp.ar_ready;

  assign axil_req.r_ready  = axil_rready;
  assign axil_rvalid       = axil_resp.r_valid;
  assign axil_rdata        = axil_resp.r.data;
  assign axil_rresp        = axil_resp.r.resp;

  prim_axil_addr_demux #(
    .AXI_ADDR_WIDTH (32),
    .AXI_DATA_WIDTH (32),
    .NUM_RANGES     (NumRanges),
    .RANGE_BASE     (RangeBase),
    .RANGE_SIZE     (RangeSize),
    .MAX_TRANS      (2),
    .aw_chan_t      (axil_aw_chan_t),
    .w_chan_t       (axil_w_chan_t),
    .b_chan_t       (axil_b_chan_t),
    .ar_chan_t      (axil_ar_chan_t),
    .r_chan_t       (axil_r_chan_t),
    .axil_req_t     (axil_req_t),
    .axil_resp_t    (axil_resp_t)
  ) u_dut (
    .clk_i       (clk),
    .rst_ni      (rst_n),
    .test_en_i   (1'b0),
    .slv_req_i   (axil_req),
    .slv_resp_o  (axil_resp),
    .mst_reqs_o  (range_reqs),
    .mst_resps_i (range_resps)
  );

  for (genvar i = 0; i < NumRanges; i++) begin : gen_ranges
    prim_axi_lite_err_slv #(
      .AXI_ADDR_WIDTH (32),
      .AXI_DATA_WIDTH (32),
      .axil_req_t     (axil_req_t),
      .axil_resp_t    (axil_resp_t),
      .RESP           (axi_pkg::RESP_OKAY),
      .RESP_WIDTH     (32),
      .RESP_DATA      (RangeTag | 32'(i)),
      .MAX_TRANS      (2)
    ) u_range (
      .clk_i       (clk),
      .rst_ni      (rst_n),
      .test_en_i   (1'b0),
      .axil_req_i  (range_reqs[i]),
      .axil_resp_o (range_resps[i])
    );

    always_ff @(posedge clk or negedge rst_n) begin
      if (!rst_n) begin
        range_aw_count[i] <= '0;
      end else if (range_reqs[i].aw_valid && range_resps[i].aw_ready) begin
        range_aw_count[i] <= range_aw_count[i] + 8'd1;
      end
    end
  end

endmodule
