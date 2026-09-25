// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// Generated - DO NOT EDIT MANUALLY

// Multi-instance I3C Core wrapper with bus demultiplexer
// Routes bus requests to individual I3C instances based on address

module i3ccore_wrapper
  import i3ccore_wrap_pkg::*;
  import i3c_pkg::*;
#(
  parameter int unsigned NUM_I3C = 2,
  parameter int unsigned I3C_REG_ADDR_WIDTH = i3ccore_wrap_pkg::I3C_REG_ADDR_WIDTH,
  parameter int unsigned BASE_ADDR = 0,
  parameter int unsigned INSTANCE_SPACING = i3ccore_wrap_pkg::I3C_INSTANCE_SPACING,  // Address space per instance

  // I3C Core parameters
  parameter int unsigned DatAw = i3c_pkg::DatAw,
  parameter int unsigned DctAw = i3c_pkg::DctAw,

  parameter int unsigned CsrAddrWidth = I3CCSR_pkg::I3CCSR_MIN_ADDR_WIDTH,
  parameter int unsigned CsrDataWidth = I3CCSR_pkg::I3CCSR_DATA_WIDTH,

  localparam int unsigned SelectWidth = (NUM_I3C > 32'd1) ? $clog2(NUM_I3C) : 32'd1,
  localparam type select_t = logic [SelectWidth-1:0]
) (
  input logic clk_i,
  input logic rst_ni,

  // AXI4-Lite slave interface
  // Write Address Channel
  input  logic           awvalid_i,
  output logic           awready_o,
  input  reg_addr_t      awaddr_i,
  input  logic [2:0]     awprot_i,

  // Write Data Channel
  input  logic           wvalid_i,
  output logic           wready_o,
  input  reg_data_t      wdata_i,
  input  reg_strb_t      wstrb_i,

  // Write Response Channel
  output logic           bvalid_o,
  input  logic           bready_i,
  output logic [1:0]     bresp_o,

  // Read Address Channel
  input  logic           arvalid_i,
  output logic           arready_o,
  input  reg_addr_t      araddr_i,
  input  logic [2:0]     arprot_i,

  // Read Data Channel
  output logic           rvalid_o,
  input  logic           rready_i,
  output reg_data_t      rdata_o,
  output logic [1:0]     rresp_o,

  // Interrupts - one per I3C instance
  output logic [NUM_I3C-1:0] irq_o,

  // I3C bus signals - one set per instance
  input  logic [NUM_I3C-1:0] scl_i,
  input  logic [NUM_I3C-1:0] sda_i,
  output logic [NUM_I3C-1:0] scl_o,
  output logic [NUM_I3C-1:0] sda_o,
  output logic [NUM_I3C-1:0] scl_oe_o,
  output logic [NUM_I3C-1:0] sda_oe_o,
  output logic [NUM_I3C-1:0] sel_od_pp_o,

  // Recovery interface signals
  output logic [NUM_I3C-1:0] recovery_payload_available_o,
  output logic [NUM_I3C-1:0] recovery_image_activated_o,
  output logic [NUM_I3C-1:0] peripheral_reset_o,
  input  logic [NUM_I3C-1:0] peripheral_reset_done_i,
  output logic [NUM_I3C-1:0] escalated_reset_o,

  // I3C DAT/DCT memory interfaces (NUM_I3C instances)
  input  i3c_pkg::dat_mem_src_t  [NUM_I3C-1:0] dat_mem_src_i,
  output i3c_pkg::dat_mem_sink_t [NUM_I3C-1:0] dat_mem_sink_o,
  input  i3c_pkg::dct_mem_src_t  [NUM_I3C-1:0] dct_mem_src_i,
  output i3c_pkg::dct_mem_sink_t [NUM_I3C-1:0] dct_mem_sink_o,

  // I3C RLT (reverse-lookup table) memory interfaces (NUM_I3C instances)
  input  i3c_pkg::rlt_mem_src_t  [NUM_I3C-1:0] rlt_mem_src_i,
  output i3c_pkg::rlt_mem_sink_t [NUM_I3C-1:0] rlt_mem_sink_o
);

  `include "axi/typedef.svh"

  `AXI_LITE_TYPEDEF_ALL(axil, reg_addr_t, reg_data_t, reg_strb_t)

  axil_req_t [NUM_I3C-1:0] axil_req_demuxed;
  axil_resp_t [NUM_I3C-1:0] axil_resp_demuxed;

  axil_req_t axil_req;
  axil_resp_t axil_resp;

  // Pack input signals into request struct
  assign axil_req = '{
    aw: '{addr: awaddr_i, prot: awprot_i},
    aw_valid: awvalid_i,
    w: '{data: wdata_i, strb: wstrb_i},
    w_valid: wvalid_i,
    b_ready: bready_i,
    ar: '{addr: araddr_i, prot: arprot_i},
    ar_valid: arvalid_i,
    r_ready: rready_i
  };

  // Unpack response struct to outputs
  assign awready_o = axil_resp.aw_ready;
  assign wready_o = axil_resp.w_ready;
  assign bvalid_o = axil_resp.b_valid;
  assign bresp_o = axil_resp.b.resp;
  assign arready_o = axil_resp.ar_ready;
  assign rvalid_o = axil_resp.r_valid;
  assign rdata_o = axil_resp.r.data;
  assign rresp_o = axil_resp.r.resp;

  // Calculate instance select from address (use write address if valid, else read address)
  select_t read_select, write_select;
  reg_addr_t read_adjusted_addr, write_adjusted_addr;
  assign read_adjusted_addr = araddr_i - BASE_ADDR;
  assign write_adjusted_addr = awaddr_i - BASE_ADDR;

  // Instance selection based on address range (INSTANCE_SPACING per instance)
  always_comb begin
    read_select = '0;
    for (int i = 0; i < NUM_I3C; i++) begin
      if ((read_adjusted_addr >= i * INSTANCE_SPACING) &&
          (read_adjusted_addr < (i + 1) * INSTANCE_SPACING)) begin
        read_select = select_t'(i);
      end
    end

    write_select = '0;
    for (int i = 0; i < NUM_I3C; i++) begin
      if ((write_adjusted_addr >= i * INSTANCE_SPACING) &&
          (write_adjusted_addr < (i + 1) * INSTANCE_SPACING)) begin
        write_select = select_t'(i);
      end
    end
  end

  // AXI-Lite demultiplexer
  axi_lite_demux #(
    .aw_chan_t(axil_aw_chan_t),
    .w_chan_t(axil_w_chan_t),
    .b_chan_t(axil_b_chan_t),
    .ar_chan_t(axil_ar_chan_t),
    .r_chan_t(axil_r_chan_t),
    .axi_req_t(axil_req_t),
    .axi_resp_t(axil_resp_t),
    .NoMstPorts(NUM_I3C),
    .MaxTrans(8),
    // Zero-latency lite demux deadlocks against the I3C AXI skid
    // (wready only after AW is accepted): W/R can retire on the TB
    // side while the selected slave never sees the beat. Register
    // every channel; FallThrough keeps the select FIFO visible the
    // cycle AW/AR is forwarded.
    .FallThrough(1'b1),
    .SpillAw(1'b1),
    .SpillW(1'b1),
    .SpillB(1'b1),
    .SpillAr(1'b1),
    .SpillR(1'b1)
  ) u_axil_demux (
    .clk_i(clk_i),
    .rst_ni(rst_ni),
    .test_i(1'b0),
    .slv_req_i(axil_req),
    .slv_aw_select_i(write_select),
    .slv_ar_select_i(read_select),
    .slv_resp_o(axil_resp),
    .mst_reqs_o(axil_req_demuxed),
    .mst_resps_i(axil_resp_demuxed)
  );


  // Generate I3C instances
  for (genvar idx = 0; idx < NUM_I3C; idx++) begin : gen_i3c_inst
    reg_data_t rdata;
    logic [1:0] rresp;
    logic [1:0] bresp;

    // Calculate instance-relative addresses by subtracting base offset
    logic [I3C_REG_ADDR_WIDTH-1:0] awaddr_offset;
    logic [I3C_REG_ADDR_WIDTH-1:0] araddr_offset;
    assign awaddr_offset = axil_req_demuxed[idx].aw.addr - idx * INSTANCE_SPACING;
    assign araddr_offset = axil_req_demuxed[idx].ar.addr - idx * INSTANCE_SPACING;

    i3c_wrapper #(
      .AxiLiteAddrWidth(I3C_REG_ADDR_WIDTH),
      .DatAw(DatAw),
      .DctAw(DctAw),
      .CsrAddrWidth(CsrAddrWidth),
      .CsrDataWidth(CsrDataWidth)
    ) u_i3c_wrapper (
      .clk_i(clk_i),
      .rst_ni(rst_ni),

      // AXI4-Lite interface
      .awvalid_i(axil_req_demuxed[idx].aw_valid),
      .awready_o(axil_resp_demuxed[idx].aw_ready),
      .awaddr_i(awaddr_offset),
      .awprot_i(axil_req_demuxed[idx].aw.prot),

      .wvalid_i(axil_req_demuxed[idx].w_valid),
      .wready_o(axil_resp_demuxed[idx].w_ready),
      .wdata_i(axil_req_demuxed[idx].w.data),
      .wstrb_i(axil_req_demuxed[idx].w.strb),

      .bvalid_o(axil_resp_demuxed[idx].b_valid),
      .bready_i(axil_req_demuxed[idx].b_ready),
      .bresp_o(bresp),

      .arvalid_i(axil_req_demuxed[idx].ar_valid),
      .arready_o(axil_resp_demuxed[idx].ar_ready),
      .araddr_i(araddr_offset),
      .arprot_i(axil_req_demuxed[idx].ar.prot),

      .rvalid_o(axil_resp_demuxed[idx].r_valid),
      .rready_i(axil_req_demuxed[idx].r_ready),
      .rdata_o(rdata),
      .rresp_o(rresp),

      // I3C bus signals
      .scl_i(scl_i[idx]),
      .sda_i(sda_i[idx]),
      .scl_o(scl_o[idx]),
      .sda_o(sda_o[idx]),
      .scl_oe_o(scl_oe_o[idx]),
      .sda_oe_o(sda_oe_o[idx]),
      .sel_od_pp_o(sel_od_pp_o[idx]),

      // Recovery interface
      .recovery_payload_available_o(recovery_payload_available_o[idx]),
      .recovery_image_activated_o(recovery_image_activated_o[idx]),
      .peripheral_reset_o(peripheral_reset_o[idx]),
      .peripheral_reset_done_i(peripheral_reset_done_i[idx]),
      .escalated_reset_o(escalated_reset_o[idx]),

      // Interrupt
      .irq_o(irq_o[idx]),

      // DAT/DCT memory interfaces
      .dat_mem_src_i (dat_mem_src_i[idx]),
      .dat_mem_sink_o(dat_mem_sink_o[idx]),
      .dct_mem_src_i (dct_mem_src_i[idx]),
      .dct_mem_sink_o(dct_mem_sink_o[idx]),

      // RLT memory interface
      .rlt_mem_src_i (rlt_mem_src_i[idx]),
      .rlt_mem_sink_o(rlt_mem_sink_o[idx])
    );

    // Response handling
    assign axil_resp_demuxed[idx].b.resp = bresp;
    assign axil_resp_demuxed[idx].r.data = rdata;
    assign axil_resp_demuxed[idx].r.resp = rresp;

  end : gen_i3c_inst

endmodule
