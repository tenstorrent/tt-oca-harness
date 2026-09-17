// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

//-----------------------------------------------------------------------------
// Telemetry Receiver Wrapper
//
//-----------------------------------------------------------------------------


module telemetry_receiver_wrap #(
  parameter int unsigned NUM_TELEMETRY_RECEIVERS         = 3,
  parameter int unsigned TELEMETRY_RECEIVER_BUFFER_DEPTH = 8,  // Must be greater than or equal to 2
  parameter int unsigned TELEMETRY_RECEIVER_MAX_NUM_COUNTERS_PER_MESSAGE [NUM_TELEMETRY_RECEIVERS-1:0] = '{default: 4},

  parameter bit [telemetry_receiver_wrap_pkg::REG_ADDR_WIDTH-1:0] TELEMETRY_RECEIVER_0__REG_MAP_BASE_ADDR = 0,
  parameter bit [telemetry_receiver_wrap_pkg::REG_ADDR_WIDTH-1:0] TELEMETRY_RECEIVER_0__REG_MAP_SIZE      = 0,

  localparam int unsigned NUM_REG_MAPS                             = NUM_TELEMETRY_RECEIVERS + 1,  // +1 for error slave
  localparam type         telemetry_receiver_wrap_reg_map_select_t = logic [$clog2(NUM_REG_MAPS)-1:0],

  localparam telemetry_receiver_wrap_reg_map_select_t UNDEFINED_REG_MAP =
        telemetry_receiver_wrap_reg_map_select_t'(NUM_REG_MAPS-1)
) (
  // Global Interface
  input  logic clk_i,
  input  logic rst_ni,

  input  logic clk_telemetry_i,
  input  logic rst_telemetry_ni,

  // AXI4-Lite Register Interface
  input  telemetry_receiver_wrap_pkg::axil_req_t  axil_req_i,
  output telemetry_receiver_wrap_pkg::axil_resp_t axil_resp_o,

  // ATB Telemetry Interface
  input  telemetry_receiver_pkg::telemetry_data_t [NUM_TELEMETRY_RECEIVERS-1:0] atdata_i,
  input  telemetry_receiver_pkg::atb_id_t         [NUM_TELEMETRY_RECEIVERS-1:0] atid_i,
  output logic                                    [NUM_TELEMETRY_RECEIVERS-1:0] atready_o,
  input  logic                                    [NUM_TELEMETRY_RECEIVERS-1:0] atvalid_i,
  output logic                                    [NUM_TELEMETRY_RECEIVERS-1:0] afvalid_o,
  input  logic                                    [NUM_TELEMETRY_RECEIVERS-1:0] afready_i,

  // Interrupt Interface
  output logic [NUM_TELEMETRY_RECEIVERS-1:0] telemetry_receiver_irq_o,

  // Debug Interface (4 bits per receiver: see telemetry_receiver.sv for field definitions)
  output logic [NUM_TELEMETRY_RECEIVERS-1:0][3:0] telemetry_receiver_debug_o
);

  `include "axi/assign.svh"
  `include "prim_assert.sv"

  /////////////////////////
  // Signal Declarations //
  /////////////////////////

  telemetry_receiver_wrap_pkg::axil_req_t  [NUM_REG_MAPS-1:0] axil_reqs;
  telemetry_receiver_wrap_pkg::axil_resp_t [NUM_REG_MAPS-1:0] axil_resps;


  //////////////////////////////
  // AXI4-Lite Register Demux //
  //////////////////////////////

  telemetry_receiver_wrap_reg_map_select_t axil_aw_select, axil_ar_select;

  always_comb begin
    axil_aw_select = UNDEFINED_REG_MAP;
    axil_ar_select = UNDEFINED_REG_MAP;

    for (int i = 0; i < NUM_TELEMETRY_RECEIVERS; i++) begin
      if (axil_req_i.aw.addr >= TELEMETRY_RECEIVER_0__REG_MAP_BASE_ADDR + i * TELEMETRY_RECEIVER_0__REG_MAP_SIZE &&
                axil_req_i.aw.addr <  TELEMETRY_RECEIVER_0__REG_MAP_BASE_ADDR + (i + 1) * TELEMETRY_RECEIVER_0__REG_MAP_SIZE) begin
        axil_aw_select = telemetry_receiver_wrap_reg_map_select_t'(i);
      end
      if (axil_req_i.ar.addr >= TELEMETRY_RECEIVER_0__REG_MAP_BASE_ADDR + i * TELEMETRY_RECEIVER_0__REG_MAP_SIZE &&
                axil_req_i.ar.addr <  TELEMETRY_RECEIVER_0__REG_MAP_BASE_ADDR + (i + 1) * TELEMETRY_RECEIVER_0__REG_MAP_SIZE) begin
        axil_ar_select = telemetry_receiver_wrap_reg_map_select_t'(i);
      end
    end
  end

  axi_lite_demux #(
    .aw_chan_t       (telemetry_receiver_wrap_pkg::axil_aw_chan_t),
    .w_chan_t        (telemetry_receiver_wrap_pkg::axil_w_chan_t),
    .b_chan_t        (telemetry_receiver_wrap_pkg::axil_b_chan_t),
    .ar_chan_t       (telemetry_receiver_wrap_pkg::axil_ar_chan_t),
    .r_chan_t        (telemetry_receiver_wrap_pkg::axil_r_chan_t),
    .axi_req_t       (telemetry_receiver_wrap_pkg::axil_req_t),
    .axi_resp_t      (telemetry_receiver_wrap_pkg::axil_resp_t),
    .NoMstPorts      (NUM_REG_MAPS),
    .MaxTrans        (1),
    .FallThrough     (1'b0),
    .SpillAw         (1'b1),
    .SpillW          (1'b0),
    .SpillB          (1'b0),
    .SpillAr         (1'b1),
    .SpillR          (1'b0)
  ) axi_lite_demux (
    .clk_i,
    .rst_ni,
    .test_i          (1'b0),
    .slv_req_i       (axil_req_i),
    .slv_aw_select_i (axil_aw_select),
    .slv_ar_select_i (axil_ar_select),
    .slv_resp_o      (axil_resp_o),
    .mst_reqs_o      (axil_reqs),
    .mst_resps_i     (axil_resps)
  );

  prim_axi_lite_err_slv #(
    .AXI_ADDR_WIDTH (telemetry_receiver_wrap_pkg::REG_ADDR_WIDTH),
    .AXI_DATA_WIDTH (telemetry_receiver_wrap_pkg::REG_DATA_WIDTH),
    .axil_req_t     (telemetry_receiver_wrap_pkg::axil_req_t),
    .axil_resp_t    (telemetry_receiver_wrap_pkg::axil_resp_t),
    .RESP           (axi_pkg::RESP_DECERR),
    .RESP_WIDTH     (telemetry_receiver_wrap_pkg::REG_DATA_WIDTH),
    .RESP_DATA      (32'hBADCAB1E),
    .MAX_TRANS      (1)
  ) prim_axi_lite_err_slv (
    .clk_i,
    .rst_ni,

    .axil_req_i     (axil_reqs [UNDEFINED_REG_MAP]),
    .axil_resp_o    (axil_resps[UNDEFINED_REG_MAP])
  );


  /////////////////////////
  // Telemetry Receivers //
  /////////////////////////

  for (genvar i = 0; i < NUM_TELEMETRY_RECEIVERS; i++) begin : gen_telemetry_receivers

    /////////////////////////
    // Signal Declarations //
    /////////////////////////

    telemetry_receiver_wrap_pkg::at_req_t at_req_telemetry, at_req;
    logic atready, atvalid;

    logic afready, afvalid;


    ////////////////
    // ATB AT CDC //
    ////////////////

    assign at_req_telemetry.atdata = atdata_i[i];
    assign at_req_telemetry.atid   = atid_i  [i];

    // Depth kept in a localparam so the occupancy-output widths stay in step with
    // the instantiation; prim_fifo_async derives DepthW = $clog2(Depth+1).
    localparam int unsigned AtFifoDepth = 8;
    localparam int unsigned AtFifoDepthW = $clog2(AtFifoDepth + 1);

    logic [AtFifoDepthW-1:0] at_fifo_wdepth;
    logic [AtFifoDepthW-1:0] at_fifo_rdepth;

    prim_fifo_async #(
      .Width               ($bits(telemetry_receiver_wrap_pkg::at_req_t)),
      .Depth               (AtFifoDepth),
      .OutputZeroIfEmpty   (1'b0),
      .OutputZeroIfInvalid (1'b0)
    ) at_req_fifo_async (
      .clk_wr_i            (clk_telemetry_i),
      .rst_wr_ni           (rst_telemetry_ni),
      .wvalid_i            (atvalid_i[i]),
      .wready_o            (atready_o[i]),
      .wdata_i             (at_req_telemetry),
      .wdepth_o            (at_fifo_wdepth),

      .clk_rd_i            (clk_i),
      .rst_rd_ni           (rst_ni),
      .rvalid_o            (atvalid),
      .rready_i            (atready),
      .rdata_o             (at_req),
      .rdepth_o            (at_fifo_rdepth)
    );

    // Tie off unused signals to satisfy lint. Kept in separate reductions because
    // wdepth is in the clk_telemetry_i domain and rdepth is in clk_i.
    logic unused_at_fifo_wdepth;
    logic unused_at_fifo_rdepth;
    assign unused_at_fifo_wdepth = ^at_fifo_wdepth;
    assign unused_at_fifo_rdepth = ^at_fifo_rdepth;


    ////////////////
    // ATB AF CDC //
    ////////////////

    // afready_i arrives from the telemetry clock domain but is consumed by
    // telemetry_receiver on clk_i, so it is synchronized into clk_i.
    prim_sync2r #(
      .WIDTH                  (1),
      .RANDOM_DELAY_GRAY_CODE (1'b0)
    ) afready_sync2r (
      .clk_i                  (clk_i),
      .d_i                    (afready_i[i]),
      .rst_ni                 (rst_ni),
      .q_o                    (afready)
    );

    // afvalid is produced on clk_i and exported to the telemetry clock
    // domain, so it is synchronized into clk_telemetry_i.
    prim_sync2r #(
      .WIDTH                  (1),
      .RANDOM_DELAY_GRAY_CODE (1'b0)
    ) afvalid_sync2r (
      .clk_i                  (clk_telemetry_i),
      .d_i                    (afvalid),
      .rst_ni                 (rst_telemetry_ni),
      .q_o                    (afvalid_o[i])
    );


    ////////////////////////
    // Telemetry Receiver //
    ////////////////////////

    telemetry_receiver_pkg::axil_req_t  telemetry_receiver_axil_req;
    telemetry_receiver_pkg::axil_resp_t telemetry_receiver_axil_resp;

    `AXI_LITE_ASSIGN_REQ_STRUCT(telemetry_receiver_axil_req, axil_reqs[i])
    `AXI_LITE_ASSIGN_RESP_STRUCT(axil_resps[i], telemetry_receiver_axil_resp)

    telemetry_receiver #(
      .BUFFER_DEPTH                 (TELEMETRY_RECEIVER_BUFFER_DEPTH),
      .MAX_NUM_COUNTERS_PER_MESSAGE (TELEMETRY_RECEIVER_MAX_NUM_COUNTERS_PER_MESSAGE[i])
    ) telemetry_receiver (
      // Global Interface
      .clk_i,
      .rst_ni,

      // AXI4-Lite Register Interface
      .axil_req_i                   (telemetry_receiver_axil_req),
      .axil_resp_o                  (telemetry_receiver_axil_resp),

      // ATB Telemetry Interface
      .atdata_i                     (at_req.atdata),
      .atid_i                       (at_req.atid),
      .atready_o                    (atready),
      .atvalid_i                    (atvalid),
      .afready_i                    (afready),
      .afvalid_o                    (afvalid),

      // Interrupt Interface
      .irq_o                        (telemetry_receiver_irq_o[i]),

      // Debug Interface
      .debug_o                      (telemetry_receiver_debug_o[i])
    );

  end


  ////////////////
  // Assertions //
  ////////////////

  `OCAH_OT_ASSERT_INIT(
      paramCheckNumTelemetryReceivers_A,
      NUM_TELEMETRY_RECEIVERS > 0 && NUM_TELEMETRY_RECEIVERS <= telemetry_receiver_wrap_pkg::MAX_NUM_TELEMETRY_RECEIVERS)

  `OCAH_OT_ASSERT_KNOWN(AxilRespKnownO_A, axil_resp_o)
  `OCAH_OT_ASSERT_KNOWN(AtreadyKnownO_A, atready_o)
  `OCAH_OT_ASSERT_KNOWN(AfvalidKnownO_A, afvalid_o)
  `OCAH_OT_ASSERT_KNOWN(TelemetryReceiverIrqKnownO_A, telemetry_receiver_irq_o)
  `OCAH_OT_ASSERT_KNOWN(TelemetryReceiverDebugKnownO_A, telemetry_receiver_debug_o)

endmodule
