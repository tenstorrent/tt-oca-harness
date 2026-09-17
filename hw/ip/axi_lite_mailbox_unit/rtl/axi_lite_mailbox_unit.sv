// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

module axi_lite_mailbox_unit #(
  parameter int unsigned NUM_MAILBOXES = 2,
  parameter int unsigned MAILBOX_DEPTH = 8,
  parameter int unsigned MAX_TRANS = 32,
  parameter int unsigned MAILBOX_BASE_ADDR = 32'h0,
  parameter bit [31:0] MAILBOX_SIZE = 32'h800,
  // AXI-Lite bus widths
  parameter int unsigned ADDR_WIDTH = 32,
  parameter int unsigned DATA_WIDTH = 64,
  // AXI-Lite type parameters
  parameter type aw_chan_t  = logic,
  parameter type w_chan_t   = logic,
  parameter type b_chan_t   = logic,
  parameter type ar_chan_t  = logic,
  parameter type r_chan_t   = logic,
  parameter type axi_req_t  = logic,
  parameter type axi_resp_t = logic,
  // Derived parameters
  localparam int unsigned STRB_WIDTH = DATA_WIDTH / 8,
  localparam int unsigned MailboxSizeW = $clog2(MAILBOX_SIZE)
) (
  input logic clk_i,
  input logic rst_ni,
  input logic test_en_i,

  input  axi_req_t mailbox_axi_req_i,
  output axi_resp_t mailbox_axi_resp_o,

  output logic [NUM_MAILBOXES-1:0] inbound_interrupt_o,
  output logic [NUM_MAILBOXES-1:0] outbound_interrupt_o
);

  // Local address type for internal use
  typedef logic [ADDR_WIDTH-1:0] addr_t;

  // Struct arrays for demux outputs
  axi_req_t [NUM_MAILBOXES*2-1:0] mst_reqs;
  axi_resp_t [NUM_MAILBOXES*2-1:0] mst_resps;

  axi_req_t mailbox_axi_req_internal;
  axi_resp_t mailbox_axi_resp_internal;

  assign mailbox_axi_req_internal = mailbox_axi_req_i;
  assign mailbox_axi_resp_o = mailbox_axi_resp_internal;

  localparam int unsigned SelectW = $clog2(NUM_MAILBOXES * 2);
  typedef logic [SelectW-1:0] select_t;

  select_t slv_aw_select, slv_ar_select;
  addr_t adj_aw_addr, adj_ar_addr;

  assign adj_aw_addr = mailbox_axi_req_internal.aw.addr - MAILBOX_BASE_ADDR;
  assign adj_ar_addr = mailbox_axi_req_internal.ar.addr - MAILBOX_BASE_ADDR;

  always_comb begin
    slv_aw_select = adj_aw_addr[MailboxSizeW+:SelectW];
    slv_ar_select = adj_ar_addr[MailboxSizeW+:SelectW];
  end

  axi_lite_demux #(
    .aw_chan_t(aw_chan_t),
    .w_chan_t (w_chan_t),
    .b_chan_t (b_chan_t),
    .ar_chan_t(ar_chan_t),
    .r_chan_t (r_chan_t),
    .axi_req_t(axi_req_t),
    .axi_resp_t(axi_resp_t),
    .NoMstPorts(2 * NUM_MAILBOXES),
    .MaxTrans(MAX_TRANS),
    .FallThrough(1'b1),
    .SpillAw(1'b0),
    .SpillW(1'b0),
    .SpillB(1'b0),
    .SpillAr(1'b0),
    .SpillR(1'b0)
  ) u_mailbox_demux (
    .clk_i(clk_i),
    .rst_ni(rst_ni),
    .test_i(test_en_i),

    .slv_req_i(mailbox_axi_req_internal),
    .slv_aw_select_i(slv_aw_select),
    .slv_ar_select_i(slv_ar_select),
    .slv_resp_o(mailbox_axi_resp_internal),

    .mst_reqs_o(mst_reqs),
    .mst_resps_i(mst_resps)
  );

  for (genvar m = 0; m < NUM_MAILBOXES; m++) begin : gen_mailbox
    localparam addr_t [1:0] MailboxBaseAddrs = {
      MAILBOX_BASE_ADDR + MAILBOX_SIZE + (MAILBOX_SIZE * 2 * m), // +1 size to get inbound mailbox base addr
      MAILBOX_BASE_ADDR + (MAILBOX_SIZE * 2 * m)
    };

    axi_req_t inbound_req, outbound_req;
    axi_resp_t inbound_rsp, outbound_rsp;

    // Connect to demux struct arrays
    assign outbound_req = mst_reqs[m*2];
    assign mst_resps[m*2] = outbound_rsp;
    assign inbound_req = mst_reqs[m*2+1];
    assign mst_resps[m*2+1] = inbound_rsp;

    axi_lite_mailbox #(
      .MailboxDepth(MAILBOX_DEPTH),
      .IrqEdgeTrig (1'b0),
      .IrqActHigh  (1'b1),
      .AxiAddrWidth(ADDR_WIDTH),
      .AxiDataWidth(DATA_WIDTH),
      .req_lite_t  (axi_req_t),
      .resp_lite_t (axi_resp_t)
    ) axi_lite_mailbox (
      .clk_i(clk_i),
      .rst_ni(rst_ni),
      .test_i(test_en_i),
      .slv_reqs_i({inbound_req, outbound_req}),
      .slv_resps_o({inbound_rsp, outbound_rsp}),
      .irq_o({inbound_interrupt_o[m], outbound_interrupt_o[m]}),
      .base_addr_i(MailboxBaseAddrs)  // base address for each port
    );
  end

endmodule
