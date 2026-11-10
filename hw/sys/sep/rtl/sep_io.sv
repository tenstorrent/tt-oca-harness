// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// Route SEP IO register AXI to the SPI controller.
//
// The 64-bit AXI4 slave is downsized to 32 bits and converted to AXI-Lite. A demux passes the
// SPI controller's window, the 2^spi_host_reg_pkg::BlockAw bytes from
// SEP_TOP_SPI_CONTROLLER_BASE_ADDR, to a single-chip-select sep_ot_spi_wrap and answers the
// rest of the page with DECERR and read data 0xBADCAB1E. Inside that window the SPI controller
// answers an access past its registers with SLVERR and read data 0xFFFFFFFF.
// sep_io_spi_req_o / sep_io_spi_rsp_i carry the SPI pad request/response struct, which also
// holds the SPI interrupt and DMA trigger.

`include "axi/assign.svh"
`include "ocah_assert.svh"

module sep_io (
  input  logic                      clk_i,    // System clock.
  input  logic                      rst_ni,   // Active-low reset.

  input  logic                      test_en_i,  // DFT test-enable (scan-enable).

  input  sep_pkg::sep_32_64_6_12_axi_req_t  sep_io_axi_req_i,  // Full AXI4 slave from local
                                                               // crossbar (register access).
  output sep_pkg::sep_32_64_6_12_axi_resp_t sep_io_axi_resp_o,  // Response to the local crossbar.

  output sep_io_pkg::sep_io_spi_req_t  sep_io_spi_req_o,  // SPI pad outputs (clock, chip select, 4
                                                          // data lanes and their output enables),
                                                          // plus the SPI interrupt and DMA trigger.
  input  sep_io_pkg::sep_io_spi_rsp_t  sep_io_spi_rsp_i  // SPI data-lane inputs from the pads.
);

  /////////////////////////
  // Signal Declarations //
  /////////////////////////

  sep_io_pkg::axil_req_t  axil_req;
  sep_io_pkg::axil_resp_t axil_resp;

  sep_io_pkg::axil_req_t  spi_axil_req;
  sep_io_pkg::axil_resp_t spi_axil_resp;

  ////////////////////
  // AXI-Lite Demux //
  ////////////////////

  sep_pkg::sep_32_32_6_12_axi_req_t  axi_req;
  sep_pkg::sep_32_32_6_12_axi_resp_t axi_resp;

  axi_dw_converter #(
    .AxiMaxReads         (16),
    .AxiSlvPortDataWidth (sep_pkg::SEP_32_64_6_12_DATA_WIDTH),  // 64-bit (input from crossbar)
    .AxiMstPortDataWidth (sep_io_pkg::DataWidth),             // 32-bit (output to AXI-Lite)
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
    .AxiAddrWidth    (sep_io_pkg::AddrWidth),
    .AxiDataWidth    (sep_io_pkg::DataWidth),
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

  localparam logic [31:0] SpiWindowBase[1] = '{
      32'(sep_top_addrmap_pkg::SEP_TOP_SPI_CONTROLLER_BASE_ADDR)
  };
  localparam logic [31:0] SpiWindowSize[1] = '{32'(1) << spi_host_reg_pkg::BlockAw};

  prim_axil_addr_demux #(
    .AXI_ADDR_WIDTH (sep_io_pkg::AddrWidth),
    .AXI_DATA_WIDTH (sep_io_pkg::DataWidth),
    .NUM_RANGES     (1),
    .RANGE_BASE     (SpiWindowBase),
    .RANGE_SIZE     (SpiWindowSize),
    .MAX_TRANS      (1),
    .aw_chan_t      (sep_io_pkg::axil_aw_chan_t),
    .w_chan_t       (sep_io_pkg::axil_w_chan_t),
    .b_chan_t       (sep_io_pkg::axil_b_chan_t),
    .ar_chan_t      (sep_io_pkg::axil_ar_chan_t),
    .r_chan_t       (sep_io_pkg::axil_r_chan_t),
    .axil_req_t     (sep_io_pkg::axil_req_t),
    .axil_resp_t    (sep_io_pkg::axil_resp_t)
  ) u_addr_demux (
    .clk_i,
    .rst_ni,
    .test_en_i,
    .slv_req_i   (axil_req),
    .slv_resp_o  (axil_resp),
    .mst_reqs_o  (spi_axil_req),
    .mst_resps_i (spi_axil_resp)
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

    .axil_req_i     (spi_axil_req),
    .axil_resp_o    (spi_axil_resp),

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

  `OCAH_ASSERT_STATIC(
      SpiRegMapFitsWindow_A,
      sep_top_addrmap_pkg::SEP_TOP_SPI_CONTROLLER_SIZE <= (64'd1 << spi_host_reg_pkg::BlockAw),
      "The SPI controller register map is larger than the window its register top decodes")

endmodule
