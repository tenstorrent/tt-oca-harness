// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// Buffer raw ATB beats in a FIFO that firmware drains through TELEMETRY_DATA.
//
// Each beat accepted on atvalid_i and atready_o is stored as {atid_i, atdata_i} in a
// BUFFER_DEPTH-entry FIFO. A read of TELEMETRY_DATA returns the oldest beat with VALID set
// and pops it; a read of an empty FIFO returns zero and pops nothing, and a write is
// acknowledged by the register block without reaching the FIFO. atready_o is low while the
// FIFO is full or leaving reset, so no beat is dropped or overwritten. CTRL.TELEMETRY_RX_FLUSH
// empties the FIFO, and CTRL.TELEMETRY_TX_FLUSH drives the AF flush request. The threshold
// interrupt compares the number of queued beats with CTRL.BUFFER_THRESHOLD.
//
// debug_o bits:
//
// - debug_o[0] stall: atvalid_i is high while atready_o is low.
// - debug_o[1] buffer_full.
// - debug_o[2] buffer_empty.
// - debug_o[3] buffer_threshold_intr_req, before INTR_ENABLE.

`include "ocah_registers.svh"

module telemetry_receiver
  import telemetry_receiver_pkg::axil_req_t;
  import telemetry_receiver_pkg::axil_resp_t;
  import telemetry_receiver_pkg::telemetry_data_t;
  import telemetry_receiver_pkg::atb_id_t;
  import telemetry_receiver_pkg::telemetry_entry_t;
#(
  parameter int unsigned BUFFER_DEPTH = 32, // Beat FIFO depth.

  localparam int unsigned DepthWidth = $clog2(BUFFER_DEPTH + 1) // FIFO fill-level width.
) (
  input  logic            clk_i,                            // System clock.
                                                            // All synchronous logic uses the rising
                                                            // edge.
  input  logic            rst_ni,                           // Async reset, active-low.
                                                            // Assert asynchronously; deassert
                                                            // synchronously to clk_i.

  input  axil_req_t       axil_req_i,                       // AXI-Lite CSR request.
  output axil_resp_t      axil_resp_o,                      // AXI-Lite CSR response.

  input  telemetry_data_t atdata_i,                         // ATB data.
                                                            // One 8-bit data beat per transfer.
  input  atb_id_t         atid_i,                           // ATB ID.
                                                            // Identifies the trace source; stored
                                                            // with the beat.
  output logic            atready_o,                        // ATB ready.
                                                            // Low while the FIFO is full or
                                                            // leaving reset.
  input  logic            atvalid_i,                        // ATB valid.
                                                            // High when atdata_i and atid_i are
                                                            // valid.
  output logic            afvalid_o,                        // ATB flush valid.
                                                            // Requests a flush from the source. It
                                                            // is CTRL.TELEMETRY_TX_FLUSH, held
                                                            // until afready_i completes the
                                                            // handshake.
  input  logic            afready_i,                        // ATB flush ready.
                                                            // Acknowledges the flush request and
                                                            // clears CTRL.TELEMETRY_TX_FLUSH.

  output logic            irq_o,                            // Receiver interrupt.
                                                            // Active high, level. Asserted while
                                                            // the FIFO holds more beats than
                                                            // CTRL.BUFFER_THRESHOLD, or while
                                                            // INTR_TEST.BUFFER_THRESHOLD is set,
                                                            // gated by INTR_ENABLE.

  output logic [3:0]      debug_o                           // [0] stall; [1] buffer_full; [2]
                                                            // buffer_empty; [3]
                                                            // buffer_threshold_intr_req.
);

  `include "prim_assert.sv"
  `include "ocah_assert.svh"

  /////////////////////////
  // Signal Declarations //
  /////////////////////////

  telemetry_receiver_reg_pkg::telemetry_receiver__in_t  reg_in;
  telemetry_receiver_reg_pkg::telemetry_receiver__out_t reg_out;

  telemetry_entry_t       buffer_wr_data, buffer_rd_data;
  logic                   buffer_rvalid, buffer_rready, buffer_full;
  logic [DepthWidth-1:0]  buffer_depth;

  logic buffer_threshold_intr_test, buffer_threshold_intr_req;


  /////////////////
  // Beat Buffer //
  /////////////////

  assign buffer_wr_data = '{atid: atid_i, atdata: atdata_i};
  assign buffer_rready  = reg_out.TELEMETRY_DATA.req && !reg_out.TELEMETRY_DATA.req_is_wr;

  prim_fifo_sync #(
    .Width             ($bits(telemetry_entry_t)),
    .Pass              (1'b0),
    .Depth             (BUFFER_DEPTH),
    .OutputZeroIfEmpty (1'b1),
    .NeverClears       (1'b0),
    .Secure            (1'b0)
  ) u_buffer (
    .clk_i,
    .rst_ni,
    .clr_i             (reg_out.CTRL.TELEMETRY_RX_FLUSH.value),
    .wvalid_i          (atvalid_i),
    .wready_o          (atready_o),
    .wdata_i           (buffer_wr_data),
    .rvalid_o          (buffer_rvalid),
    .rready_i          (buffer_rready),
    .rdata_o           (buffer_rd_data),
    .full_o            (buffer_full),
    .depth_o           (buffer_depth),
    .err_o             (/* UNUSED */)
  );


  /////////////////////
  // Interrupt Logic //
  /////////////////////

  localparam int unsigned ThresholdWidth = $bits(
        telemetry_receiver_reg_pkg::telemetry_receiver__CTRL__BUFFER_THRESHOLD__out_t);
  localparam int unsigned CompareWidth   =
        DepthWidth > ThresholdWidth ? DepthWidth : ThresholdWidth;

  assign buffer_threshold_intr_req =
        CompareWidth'(buffer_depth) > CompareWidth'(reg_out.CTRL.BUFFER_THRESHOLD.value) ||
        buffer_threshold_intr_test;
  assign irq_o = buffer_threshold_intr_req && reg_out.INTR_ENABLE.BUFFER_THRESHOLD.value;


  //////////
  // CSRs //
  //////////

  telemetry_receiver_reg u_telemetry_receiver_reg (
    .clk            (clk_i),
    .arst_n         (rst_ni),

    .s_axil_awready (axil_resp_o.aw_ready),
    .s_axil_awvalid (axil_req_i.aw_valid),
    .s_axil_awaddr  (axil_req_i.aw.addr),
    .s_axil_awprot  (axil_req_i.aw.prot),
    .s_axil_wready  (axil_resp_o.w_ready),
    .s_axil_wvalid  (axil_req_i.w_valid),
    .s_axil_wdata   (axil_req_i.w.data),
    .s_axil_wstrb   (axil_req_i.w.strb),
    .s_axil_bready  (axil_req_i.b_ready),
    .s_axil_bvalid  (axil_resp_o.b_valid),
    .s_axil_bresp   (axil_resp_o.b.resp),
    .s_axil_arready (axil_resp_o.ar_ready),
    .s_axil_arvalid (axil_req_i.ar_valid),
    .s_axil_araddr  (axil_req_i.ar.addr),
    .s_axil_arprot  (axil_req_i.ar.prot),
    .s_axil_rready  (axil_req_i.r_ready),
    .s_axil_rvalid  (axil_resp_o.r_valid),
    .s_axil_rdata   (axil_resp_o.r.data),
    .s_axil_rresp   (axil_resp_o.r.resp),

    .hwif_in        (reg_in),
    .hwif_out       (reg_out)
  );

  // CTRL Register
  assign afvalid_o = reg_out.CTRL.TELEMETRY_TX_FLUSH.value;
  assign reg_in.CTRL.TELEMETRY_TX_FLUSH.hwclr = afready_i && afvalid_o;

  // STATUS Register
  assign reg_in.STATUS.BUFFER_EMPTY.next = !buffer_rvalid;
  assign reg_in.STATUS.BUFFER_FULL.next  = buffer_full;

  // INTR_STATUS Register
  assign reg_in.INTR_STATUS.BUFFER_THRESHOLD.next = buffer_threshold_intr_req;

  // INTR_TEST Register
  assign buffer_threshold_intr_test = reg_out.INTR_TEST.BUFFER_THRESHOLD.value;

  // TELEMETRY_DATA Register
  assign reg_in.TELEMETRY_DATA.rd_ack                  = buffer_rready;
  assign reg_in.TELEMETRY_DATA.rd_data.VALID           = buffer_rvalid;
  assign reg_in.TELEMETRY_DATA.rd_data._reserved_30_15 = '0;
  assign reg_in.TELEMETRY_DATA.rd_data.ATID            = buffer_rd_data.atid;
  assign reg_in.TELEMETRY_DATA.rd_data.DATA            = buffer_rd_data.atdata;


  ///////////
  // Debug //
  ///////////

  assign debug_o = {
    buffer_threshold_intr_req, !buffer_rvalid, buffer_full, atvalid_i && !atready_o
  };


  ////////////////
  // Assertions //
  ////////////////

  `OCAH_ASSERT(NoAcceptWhenFull_A, buffer_full |-> !atready_o)
  // The fill level moves by one per accepted beat and one per read of a non-empty FIFO.
  `OCAH_ASSERT(PopOnlyWhenValid_A,
               !reg_out.CTRL.TELEMETRY_RX_FLUSH.value |=>
               buffer_depth == $past(buffer_depth) + DepthWidth'($past(atvalid_i && atready_o)) -
                               DepthWidth'($past(buffer_rready && buffer_rvalid)))

  `OCAH_OT_ASSERT_KNOWN(AxilRespKnownO_A, axil_resp_o)
  `OCAH_OT_ASSERT_KNOWN(AtreadyKnownO_A, atready_o)
  `OCAH_OT_ASSERT_KNOWN(AfvalidKnownO_A, afvalid_o)
  `OCAH_OT_ASSERT_KNOWN(IrqKnownO_A, irq_o)
  `OCAH_OT_ASSERT_KNOWN(DebugKnownO_A, debug_o)

endmodule
