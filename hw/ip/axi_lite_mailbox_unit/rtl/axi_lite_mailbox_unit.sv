// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// Expose NUM_MAILBOXES AXI-Lite mailboxes with inbound and outbound IRQs.
//
// Independent mailboxes share one AXI-Lite slave decode sized by MAILBOX_BASE_ADDR and
// MAILBOX_SIZE. Each mailbox is an axi_lite_mailbox with two AXI-Lite ports of MAILBOX_SIZE
// bytes each: mailbox m places its outbound port at MAILBOX_BASE_ADDR + 2 * m *
// MAILBOX_SIZE and its inbound port one MAILBOX_SIZE above it. The axi_lite_demux decodes
// only the base-relative address bits from $clog2(MAILBOX_SIZE) upward that select a port.
// Each mailbox has depth MAILBOX_DEPTH and raises inbound_interrupt_o and
// outbound_interrupt_o as level-sensitive, active-high interrupts.

module axi_lite_mailbox_unit #(
  parameter int unsigned NUM_MAILBOXES = 2,                 // Number of mailboxes, each with an
                                                            // outbound and an inbound port.
  parameter int unsigned MAILBOX_DEPTH = 8,                 // FIFO depth per mailbox.
                                                            // In entries, for each internal message
                                                            // FIFO.
  parameter int unsigned MAX_TRANS = 32,                    // AXI-Lite outstanding capacity.
                                                            // Maximum open AXI-Lite transactions
                                                            // per channel in the port demux.
  parameter int unsigned MAILBOX_BASE_ADDR = 32'h0,         // Byte base of mailbox 0.
                                                            // The aperture decode is relative to
                                                            // it.
  parameter bit [31:0] MAILBOX_SIZE = 32'h800,              // Byte span per mailbox port.
                                                            // Register space of one port of an
                                                            // axi_lite_mailbox; a mailbox spans
                                                            // twice this. Must be a power of two.
  parameter int unsigned ADDR_WIDTH = 32,                   // AXI-Lite address width.
  parameter int unsigned DATA_WIDTH = 64,                   // AXI-Lite data width.
  parameter type aw_chan_t  = logic,                        // AW channel type.
  parameter type w_chan_t   = logic,                        // W channel type.
  parameter type b_chan_t   = logic,                        // B channel type.
  parameter type ar_chan_t  = logic,                        // AR channel type.
  parameter type r_chan_t   = logic,                        // R channel type.
  parameter type axi_req_t  = logic,                        // AXI-Lite request type.
  parameter type axi_resp_t = logic,                        // AXI-Lite response type.
  localparam int unsigned STRB_WIDTH = DATA_WIDTH / 8,      // Write-strobe width.
  localparam int unsigned MailboxSizeW = $clog2(MAILBOX_SIZE) // Lowest address bit of the port
                                                              // select.
) (
  input logic clk_i,                                        // System clock.
                                                            // Clocks all mailbox logic and the
                                                            // AXI-Lite interface; the unit has one
                                                            // clock domain.
  input logic rst_ni,                                       // Async reset, active-low.
                                                            // Initializes all mailbox state.
  input logic test_en_i,                                    // DFT test enable, driven to the demux
                                                            // and mailbox test inputs.

  input  axi_req_t mailbox_axi_req_i,                       // AXI-Lite slave request.
  output axi_resp_t mailbox_axi_resp_o,                     // AXI-Lite slave response.

  output logic [NUM_MAILBOXES-1:0] inbound_interrupt_o,     // Per-mailbox interrupt of the inbound
                                                            // port.
  output logic [NUM_MAILBOXES-1:0] outbound_interrupt_o     // Per-mailbox interrupt of the outbound
                                                            // port.
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
    ) u_axi_lite_mailbox (
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
