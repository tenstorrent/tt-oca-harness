// Copyright lowRISC contributors (OpenTitan project).
// Licensed under the Apache License, Version 2.0, see LICENSE for details.
// SPDX-License-Identifier: Apache-2.0

// Wrap the I2C core with AXI-Lite CSRs, SMBus sideband, and DMA ready levels.
//
// Instantiates i2c_core and the i2c_reg register block, both on clk_i.
// The FIFO depth parameters size the controller and target FIFOs; INPUT_DELAY_CYCLES sets
// the external input delay the core allows for.
// debug_o mirrors i2c_core's four debug bits.

module i2c
  import i2c_pkg::*;
#(
  parameter int unsigned CONTROLLER_TX_FIFO_DEPTH = 64,     // Entries in the controller format
                                                            // (FMT) FIFO; 1 to 4095.
  parameter int unsigned CONTROLLER_RX_FIFO_DEPTH = 64,     // Entries in the controller receive
                                                            // (RX) FIFO; 1 to 4095.
  parameter int unsigned TARGET_TX_FIFO_DEPTH     = 64,     // Entries in the target transmit (TX)
                                                            // FIFO; 1 to 4095.
  parameter int unsigned TARGET_RX_FIFO_DEPTH     = 268,    // Entries in the target acquisition
                                                            // (ACQ) FIFO; 1 to 4095.
  parameter int unsigned INPUT_DELAY_CYCLES       = 0       // External SCL/SDA input delay in clk_i
                                                            // cycles; lengthens the
                                                            // interference-detection blanking
                                                            // window after each output change.
) (
  input  logic                             clk_i,           // System clock.
  input  logic                             rst_ni,          // Async reset, active-low.

  input  axil_req_t                        axil_req_i,      // AXI-Lite CSR request.
  output axil_resp_t                       axil_resp_o,     // AXI-Lite CSR response.

  input  logic                             scl_i,           // SCL pad input, synchronized to clk_i
                                                            // inside i2c_core.
  output logic                             scl_o,           // SCL pad output for an open-drain pad;
                                                            // 0 pulls the line low, 1 releases it.
  input  logic                             sda_i,           // SDA pad input, synchronized to clk_i
                                                            // inside i2c_core.
  output logic                             sda_o,           // SDA pad output for an open-drain pad;
                                                            // 0 pulls the line low, 1 releases it.

  input  logic                             smbus_en_i,      // When low, masks smbalert_ni so SMBus
                                                            // ALERT reads as deasserted.
  input  logic                             smbsus_ni,       // SMBus SUS pin in, active-low;
                                                            // synchronized and reported in
                                                            // SMBUS_STATUS.
  output logic                             smbsus_no,       // SMBus SUS pin out, active-low; driven
                                                            // from SMBUS_CTRL.SMBSUS in host mode
                                                            // without line loopback, high
                                                            // otherwise.
  input  logic                             smbalert_ni,     // SMBus ALERT pin in, active-low;
                                                            // synchronized, reported in
                                                            // SMBUS_STATUS and raises the SMBALERT
                                                            // interrupt.
  output logic                             smbalert_no,     // SMBus ALERT pin out, active-low;
                                                            // driven from SMBUS_CTRL.SMBALERT in
                                                            // target mode without loopback, high
                                                            // otherwise.

  output logic                             controller_tx_ready_o, // Controller TX DMA ready; drops
                                                                  // when the FMT FIFO fills and
                                                                  // returns once its level falls
                                                                  // below the FMT threshold.
  output logic                             controller_rx_ready_o, // Controller RX DMA ready; rises
                                                                  // when the RX level exceeds the
                                                                  // RX threshold and stays high
                                                                  // until the FIFO empties.
  output logic                             target_tx_ready_o, // Target TX DMA ready; drops when the
                                                              // TX FIFO fills and returns once its
                                                              // level falls below the TX threshold.
  output logic                             target_rx_ready_o, // Target RX DMA ready; rises when the
                                                              // ACQ level exceeds the ACQ threshold
                                                              // and stays high until the FIFO
                                                              // empties.

  output logic                             irq_o,           // Level interrupt; OR of the INTR_STATE
                                                            // sources masked by INTR_ENABLE.

  output logic [3:0]                       debug_o          // Four-bit debug bus; see i2c_core for
                                                            // field definitions.
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
