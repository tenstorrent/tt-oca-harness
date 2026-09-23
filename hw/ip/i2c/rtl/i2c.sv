//-----------------------------------------------------------------------------
// I2C
//
//-----------------------------------------------------------------------------

// Copyright lowRISC contributors (OpenTitan project).
// Licensed under the Apache License, Version 2.0, see LICENSE for details.
// SPDX-License-Identifier: Apache-2.0
//
// Description: I2C top level wrapper file


module i2c
  import i2c_pkg::*;
#(
  parameter int unsigned CONTROLLER_TX_FIFO_DEPTH = 64,
  parameter int unsigned CONTROLLER_RX_FIFO_DEPTH = 64,
  parameter int unsigned TARGET_TX_FIFO_DEPTH     = 64,
  parameter int unsigned TARGET_RX_FIFO_DEPTH     = 268,
  parameter int unsigned INPUT_DELAY_CYCLES       = 0
) (
  // Global Interface
  input  logic                             clk_i,
  input  logic                             rst_ni,

  // AXI4-Lite Register Interface
  input  axil_req_t                        axil_req_i,
  output axil_resp_t                       axil_resp_o,

  // I2C Interface
  input  logic                             scl_i,
  output logic                             scl_o,
  input  logic                             sda_i,
  output logic                             sda_o,

  // SMBus Interface
  input  logic                             smbus_en_i,
  input  logic                             smbsus_ni,
  output logic                             smbsus_no,
  input  logic                             smbalert_ni,
  output logic                             smbalert_no,

  // DMA Interface
  output logic                             controller_tx_ready_o,
  output logic                             controller_rx_ready_o,
  output logic                             target_tx_ready_o,
  output logic                             target_rx_ready_o,

  // Interrupt Interface
  output logic                             irq_o,

  // Debug Interface (see i2c_core.sv for field definitions)
  output logic [3:0]                       debug_o
);

  `include "prim_assert.sv"

  /////////////////////////
  // Signal Declarations //
  /////////////////////////

  i2c_reg_pkg::i2c__in_t  reg_in;
  i2c_reg_pkg::i2c__out_t reg_out;


  //////////////
  // I2C Core //
  //////////////

  i2c_core #(
    .CONTROLLER_TX_FIFO_DEPTH (CONTROLLER_TX_FIFO_DEPTH),
    .CONTROLLER_RX_FIFO_DEPTH (CONTROLLER_RX_FIFO_DEPTH),
    .TARGET_TX_FIFO_DEPTH     (TARGET_TX_FIFO_DEPTH),
    .TARGET_RX_FIFO_DEPTH     (TARGET_RX_FIFO_DEPTH),
    .INPUT_DELAY_CYCLES       (INPUT_DELAY_CYCLES)
  ) u_i2c_core (
    // Global Interface
    .clk_i,
    .rst_ni,

    // Register Interface
    .reg_out_i                (reg_out),
    .reg_in_o                 (reg_in),

    // I2C Interface
    .scl_i,
    .scl_o,
    .sda_i,
    .sda_o,

    // SMBus Interface
    .smbus_en_i,
    .smbsus_ni,
    .smbsus_no,
    .smbalert_ni,
    .smbalert_no,

    // DMA Interface
    .controller_tx_ready_o,
    .controller_rx_ready_o,
    .target_tx_ready_o,
    .target_rx_ready_o,

    // Interrupt Interface
    .irq_o,

    // Debug Interface
    .debug_o
  );


  //////////
  // CSRs //
  //////////

  i2c_reg u_i2c_reg (
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


  ////////////////
  // Assertions //
  ////////////////

  `OCAH_OT_ASSERT_KNOWN(AxilRespKnownO_A, axil_resp_o)
  `OCAH_OT_ASSERT_KNOWN(SclKnownO_A, scl_o)
  `OCAH_OT_ASSERT_KNOWN(SdaKnownO_A, sda_o)
  `OCAH_OT_ASSERT_KNOWN(SmbsusKnownO_A, smbsus_no)
  `OCAH_OT_ASSERT_KNOWN(SmbalertKnownO_A, smbalert_no)
  `OCAH_OT_ASSERT_KNOWN(ControllerTxReadyKnown_A, controller_tx_ready_o)
  `OCAH_OT_ASSERT_KNOWN(ControllerRxReadyKnown_A, controller_rx_ready_o)
  `OCAH_OT_ASSERT_KNOWN(TargetTxReadyKnown_A, target_tx_ready_o)
  `OCAH_OT_ASSERT_KNOWN(TargetRxReadyKnown_A, target_rx_ready_o)
  `OCAH_OT_ASSERT_KNOWN(IrqKnownO_A, irq_o)
  `OCAH_OT_ASSERT_KNOWN(DebugKnownO_A, debug_o)

endmodule
