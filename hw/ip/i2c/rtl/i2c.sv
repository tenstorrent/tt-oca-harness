// Copyright lowRISC contributors (OpenTitan project).
// Licensed under the Apache License, Version 2.0, see LICENSE for details.
// SPDX-License-Identifier: Apache-2.0

// Wrap the I2C core with AXI-Lite CSRs, SMBus sideband, and DMA ready strobes.
//
// Instantiates i2c_core and the register block.
// FIFO depths and INPUT_DELAY_CYCLES size the controller and target paths.
// debug_o mirrors i2c_core's four debug bits.

module i2c
  import i2c_pkg::*;
#(
  parameter int unsigned CONTROLLER_TX_FIFO_DEPTH = 64,     // Controller TX FIFO depth.
  parameter int unsigned CONTROLLER_RX_FIFO_DEPTH = 64,     // Controller RX FIFO depth.
  parameter int unsigned TARGET_TX_FIFO_DEPTH     = 64,     // Target TX FIFO depth.
  parameter int unsigned TARGET_RX_FIFO_DEPTH     = 268,    // Target RX FIFO depth.
  parameter int unsigned INPUT_DELAY_CYCLES       = 0       // Extra input-pipeline cycles.
) (
  input  logic                             clk_i,           // System clock.
  input  logic                             rst_ni,          // Async reset, active-low.

  input  axil_req_t                        axil_req_i,      // AXI-Lite CSR request.
  output axil_resp_t                       axil_resp_o,     // AXI-Lite CSR response.

  input  logic                             scl_i,           // SCL pad input.
  output logic                             scl_o,           // SCL pad output (open-drain drive).
  input  logic                             sda_i,           // SDA pad input.
  output logic                             sda_o,           // SDA pad output (open-drain drive).

  input  logic                             smbus_en_i,      // Enable SMBus sideband.
  input  logic                             smbsus_ni,       // SMBus SUS pin in, active-low.
  output logic                             smbsus_no,       // SMBus SUS pin out, active-low.
  input  logic                             smbalert_ni,     // SMBus ALERT pin in, active-low.
  output logic                             smbalert_no,     // SMBus ALERT pin out, active-low.

  output logic                             controller_tx_ready_o, // Controller TX DMA ready.
  output logic                             controller_rx_ready_o, // Controller RX DMA ready.
  output logic                             target_tx_ready_o, // Target TX DMA ready.
  output logic                             target_rx_ready_o, // Target RX DMA ready.

  output logic                             irq_o,           // Combined I2C interrupt.

  output logic [3:0]                       debug_o          // Four-bit debug bus; see i2c_core for field definitions.
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
