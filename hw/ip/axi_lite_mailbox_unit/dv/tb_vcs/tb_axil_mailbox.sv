// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

//-----------------------------------------------------------------------------
// Mailbox Testbench
//
//-----------------------------------------------------------------------------

`include "axi/typedef.svh"
`include "axi/assign.svh"

module tb_axil_mailbox #(
  parameter int unsigned NUM_MAILBOXES = 2,
  parameter int unsigned ADDR_WIDTH = 32,
  parameter int unsigned DATA_WIDTH = 64,
  localparam int unsigned STRB_WIDTH = DATA_WIDTH / 8
) (
  input logic clk_i,
  input logic rst_ni,
  input logic test_en_i,

  // AXI4-Lite Interface - always flattened at testbench top level
  input  logic           awvalid,
  output logic           awready,
  input  logic [ADDR_WIDTH-1:0] awaddr,
  input  axi_pkg::prot_t awprot,
  input  logic           wvalid,
  output logic           wready,
  input  logic [DATA_WIDTH-1:0] wdata,
  input  logic [STRB_WIDTH-1:0] wstrb,
  output logic           bvalid,
  input  logic           bready,
  output axi_pkg::resp_t bresp,
  input  logic           arvalid,
  output logic           arready,
  input  logic [ADDR_WIDTH-1:0] araddr,
  input  axi_pkg::prot_t arprot,
  output logic           rvalid,
  input  logic           rready,
  output logic [DATA_WIDTH-1:0] rdata,
  output axi_pkg::resp_t rresp,

  output logic [NUM_MAILBOXES-1:0] inbound_interrupt_o,
  output logic [NUM_MAILBOXES-1:0] outbound_interrupt_o
);

  // Local type definitions
  typedef logic [ADDR_WIDTH-1:0] addr_t;
  typedef logic [DATA_WIDTH-1:0] data_t;
  typedef logic [STRB_WIDTH-1:0] strb_t;

  // Generate AXI-Lite types using standard macro
  `AXI_LITE_TYPEDEF_ALL(axil, addr_t, data_t, strb_t)

  // Import register address constants.
  import axil_mailbox_addrmap_pkg::*;

  /////////
  // DUT //
  /////////

  // Convert flattened signals to struct for DUT
  axil_req_t  mailbox_axi_req;
  axil_resp_t mailbox_axi_resp;

  assign mailbox_axi_req.aw_valid = awvalid;
  assign mailbox_axi_req.aw.addr  = awaddr;
  assign mailbox_axi_req.aw.prot  = awprot;
  assign mailbox_axi_req.w_valid  = wvalid;
  assign mailbox_axi_req.w.data   = wdata;
  assign mailbox_axi_req.w.strb   = wstrb;
  assign mailbox_axi_req.b_ready  = bready;
  assign mailbox_axi_req.ar_valid = arvalid;
  assign mailbox_axi_req.ar.addr  = araddr;
  assign mailbox_axi_req.ar.prot  = arprot;
  assign mailbox_axi_req.r_ready  = rready;
  assign awready = mailbox_axi_resp.aw_ready;
  assign wready  = mailbox_axi_resp.w_ready;
  assign bvalid  = mailbox_axi_resp.b_valid;
  assign bresp   = mailbox_axi_resp.b.resp;
  assign arready = mailbox_axi_resp.ar_ready;
  assign rvalid  = mailbox_axi_resp.r_valid;
  assign rdata   = mailbox_axi_resp.r.data;
  assign rresp   = mailbox_axi_resp.r.resp;

  axil_mailbox #(
    .NUM_MAILBOXES(NUM_MAILBOXES),
    .MAILBOX_DEPTH(8),
    .MAX_TRANS(32),
    .MAILBOX_BASE_ADDR(OUTBOUND_MAILBOX_0_REG_FILE_BASE_ADDR),
    .MAILBOX_SIZE(32'h800),
    .ADDR_WIDTH(ADDR_WIDTH),
    .DATA_WIDTH(DATA_WIDTH),
    .aw_chan_t(axil_aw_chan_t),
    .w_chan_t(axil_w_chan_t),
    .b_chan_t(axil_b_chan_t),
    .ar_chan_t(axil_ar_chan_t),
    .r_chan_t(axil_r_chan_t),
    .axi_req_t(axil_req_t),
    .axi_resp_t(axil_resp_t)
  ) u_axil_mailbox (
    .clk_i(clk_i),
    .rst_ni(rst_ni),
    .test_en_i(test_en_i),

    .mailbox_axi_req_i(mailbox_axi_req),
    .mailbox_axi_resp_o(mailbox_axi_resp),

    .inbound_interrupt_o(inbound_interrupt_o),
    .outbound_interrupt_o(outbound_interrupt_o)
  );


  //////////////////////
  // Waveform Dumping //
  //////////////////////

`ifndef VERILATOR
  initial begin
    if ($test$plusargs("waves")) begin
      $fsdbDumpfile("test.fsdb");
      $fsdbDumpvars(0, tb_axil_mailbox);
      $fsdbDumpvars("+all");
    end
  end
`endif

endmodule
