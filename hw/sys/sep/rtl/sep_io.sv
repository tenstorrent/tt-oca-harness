// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// SEP System IO

`include "axi/assign.svh"

module sep_io #(
  parameter  int unsigned NUM_COMPONENTS = 1,
  localparam int unsigned NUM_SLAVES     = NUM_COMPONENTS + 1 // +1 for error slave
) (
  // Global Interface
  input  logic                      clk_i,
  input  logic                      rst_ni,

  // Test/Scan Interface
  input  logic                      test_en_i,

  // Full AXI4 slave from local crossbar (register access)
  input  sep_pkg::sep_32_64_6_12_axi_req_t  sep_io_axi_req_i,
  output sep_pkg::sep_32_64_6_12_axi_resp_t sep_io_axi_resp_o,

  // SPI
  output sep_io_pkg::sep_io_spi_req_t  sep_io_spi_req_o,
  input  sep_io_pkg::sep_io_spi_rsp_t  sep_io_spi_rsp_i
);

  /////////////////////////
  // Signal Declarations //
  /////////////////////////

  sep_io_pkg::axil_req_t  axil_req;
  sep_io_pkg::axil_resp_t axil_resp;

  sep_io_pkg::axil_req_t  [NUM_SLAVES-1:0] axil_reqs;
  sep_io_pkg::axil_resp_t [NUM_SLAVES-1:0] axil_resps;


  ////////////////////
  // AXI-Lite Demux //
  ////////////////////

  sep_pkg::sep_32_32_6_12_axi_req_t  axi_req;
  sep_pkg::sep_32_32_6_12_axi_resp_t axi_resp;

  axi_dw_converter #(
    .AxiMaxReads         (16),
    .AxiSlvPortDataWidth (sep_pkg::SEP_32_64_6_12_DATA_WIDTH),  // 64-bit (input from crossbar)
    .AxiMstPortDataWidth (sep_io_pkg::DATA_WIDTH),             // 32-bit (output to AXI-Lite)
    .AxiAddrWidth        (sep_pkg::SEP_32_64_6_12_ADDR_WIDTH),
    .AxiIdWidth          (sep_pkg::SEP_32_64_6_12_ID_WIDTH),
    .aw_chan_t           (sep_pkg::sep_32_64_6_12_axi_aw_chan_t),
    .mst_w_chan_t        (sep_pkg::sep_32_32_6_12_axi_w_chan_t),        // 32-bit master (output)
    .slv_w_chan_t        (sep_pkg::sep_32_64_6_12_axi_w_chan_t),        // 64-bit slave (input)
    .b_chan_t            (sep_pkg::sep_32_64_6_12_axi_b_chan_t),
    .ar_chan_t           (sep_pkg::sep_32_64_6_12_axi_ar_chan_t),
    .mst_r_chan_t        (sep_pkg::sep_32_32_6_12_axi_r_chan_t),        // 32-bit master (output)
    .slv_r_chan_t        (sep_pkg::sep_32_64_6_12_axi_r_chan_t),        // 64-bit slave (input)
    .axi_mst_req_t       (sep_pkg::sep_32_32_6_12_axi_req_t),           // 32-bit master (output)
    .axi_mst_resp_t      (sep_pkg::sep_32_32_6_12_axi_resp_t),          // 32-bit master (input)
    .axi_slv_req_t       (sep_pkg::sep_32_64_6_12_axi_req_t),           // 64-bit slave (input)
    .axi_slv_resp_t      (sep_pkg::sep_32_64_6_12_axi_resp_t)           // 64-bit slave (output)
  ) u_axi_dw_converter (
    .clk_i,
    .rst_ni,
    .slv_req_i           (sep_io_axi_req_i),
    .slv_resp_o          (sep_io_axi_resp_o),
    .mst_req_o           (axi_req),
    .mst_resp_i          (axi_resp)
  );

  axi_to_axi_lite #(
    .AxiAddrWidth    (sep_io_pkg::ADDR_WIDTH),
    .AxiDataWidth    (sep_io_pkg::DATA_WIDTH),
    .AxiIdWidth      (sep_pkg::SEP_32_32_6_12_ID_WIDTH),
    .AxiUserWidth    (sep_pkg::SEP_32_32_6_12_USER_WIDTH),
    .AxiMaxWriteTxns (16),
    .AxiMaxReadTxns  (16),
    .FullBW          (1'b0),
    .FallThrough     (1'b1),
    .SpillAw         (1'b0),
    .SpillW          (1'b0),
    .SpillB          (1'b0),
    .SpillAr         (1'b0),
    .SpillR          (1'b0),
    .full_req_t      (sep_pkg::sep_32_32_6_12_axi_req_t),
    .full_resp_t     (sep_pkg::sep_32_32_6_12_axi_resp_t),
    .lite_req_t      (sep_io_pkg::axil_req_t),
    .lite_resp_t     (sep_io_pkg::axil_resp_t)
  ) u_axi_to_axi_lite (
    .clk_i,
    .rst_ni,
    .test_i          (test_en_i),
    .slv_req_i       (axi_req),
    .slv_resp_o      (axi_resp),
    .mst_req_o       (axil_req),
    .mst_resp_i      (axil_resp)
  );

  logic [$clog2(NUM_SLAVES)-1:0] axil_aw_select, axil_ar_select;

  // Address decode: SPI or error slave
  always_comb begin
    if (axil_req.aw.addr >= och_sep_top_addrmap_pkg::OCH_SEP_TOP_SPI_CONTROLLER_BASE_ADDR &&
            axil_req.aw.addr < och_sep_top_addrmap_pkg::OCH_SEP_TOP_SPI_CONTROLLER_BASE_ADDR + och_sep_top_addrmap_pkg::OCH_SEP_TOP_SPI_CONTROLLER_SIZE) begin
      axil_aw_select = 1'b0;  // SPI
    end else begin
      axil_aw_select = 1'b1;  // Error slave
    end
  end

  always_comb begin
    if (axil_req.ar.addr >= och_sep_top_addrmap_pkg::OCH_SEP_TOP_SPI_CONTROLLER_BASE_ADDR &&
            axil_req.ar.addr < och_sep_top_addrmap_pkg::OCH_SEP_TOP_SPI_CONTROLLER_BASE_ADDR + och_sep_top_addrmap_pkg::OCH_SEP_TOP_SPI_CONTROLLER_SIZE) begin
      axil_ar_select = 1'b0;  // SPI
    end else begin
      axil_ar_select = 1'b1;  // Error slave
    end
  end

  axi_lite_demux #(
    .aw_chan_t       (sep_io_pkg::axil_aw_chan_t),
    .w_chan_t        (sep_io_pkg::axil_w_chan_t),
    .b_chan_t        (sep_io_pkg::axil_b_chan_t),
    .ar_chan_t       (sep_io_pkg::axil_ar_chan_t),
    .r_chan_t        (sep_io_pkg::axil_r_chan_t),
    .axi_req_t       (sep_io_pkg::axil_req_t),
    .axi_resp_t      (sep_io_pkg::axil_resp_t),
    .NoMstPorts      (NUM_SLAVES),
    .MaxTrans        (1),
    .FallThrough     (1'b0),
    .SpillAw         (1'b1), // Pipeline AW to ease timing and area
    .SpillW          (1'b0),
    .SpillB          (1'b0),
    .SpillAr         (1'b1), // Pipeline AR to ease timing and area
    .SpillR          (1'b0)
  ) u_axi_lite_demux (
    .clk_i,
    .rst_ni,
    .test_i          (test_en_i),
    .slv_req_i       (axil_req),
    .slv_aw_select_i (axil_aw_select),
    .slv_ar_select_i (axil_ar_select),
    .slv_resp_o      (axil_resp),
    .mst_reqs_o      (axil_reqs),
    .mst_resps_i     (axil_resps)
  );

  ////////////////////
  // SPI Subsystem  //
  ////////////////////


  sep_ot_spi_wrap #(
    .NUM_CS(1)
  ) u_sep_ot_spi_wrap (
    .clk_i          (clk_i),
    .rst_ni         (rst_ni),

    .test_en_i      (test_en_i),

    .axil_req_i     (axil_reqs[0]),
    .axil_resp_o    (axil_resps[0]),

    .spi_sck_o      (sep_io_spi_req_o.sck),
    .spi_sck_oe_o   (sep_io_spi_req_o.sck_oe),

    .spi_cs_no      (sep_io_spi_req_o.cs_n),
    .spi_cs_oe_o    (sep_io_spi_req_o.cs_oe),

    .spi_sd_o       (sep_io_spi_req_o.sd),
    .spi_sd_oe_o    (sep_io_spi_req_o.sd_oe),
    .spi_sd_i       (sep_io_spi_rsp_i.sd),

    .irq_o          (sep_io_spi_req_o.irq),
    .lsio_trigger_o (sep_io_spi_req_o.lsio_trigger)
  );

  prim_axil_err_slv #(
    .AXI_DATA_WIDTH (sep_io_pkg::DATA_WIDTH),
    .AXI_ADDR_WIDTH (sep_io_pkg::ADDR_WIDTH),
    .axil_req_t     (sep_io_pkg::axil_req_t),
    .axil_resp_t    (sep_io_pkg::axil_resp_t)
  ) u_axil_err_slv (
    .clk_i,
    .rst_ni,
    .axil_req_i  (axil_reqs [NUM_SLAVES-1]),
    .axil_resp_o (axil_resps[NUM_SLAVES-1])
  );

endmodule
