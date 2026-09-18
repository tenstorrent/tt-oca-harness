// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

//----------------------------------------------------------
// SMC Peripherals CDC
//
// Clock domain crossing module for SMC peripherals.
// Centralizes all CDC crossings related to peripheral subsystems
// (SMCCLK, PERIPHERALCLK, REFCLK, TELEMETRYCLK).
//
//----------------------------------------------------------

module smc_peripherals_cdc #(
  parameter int unsigned SYNC_STAGES = 3  // 2 for sync2, 3 for sync3
) (
  // Clock inputs
  input  logic clk_smc_i,
  input  logic clk_periph_i,
  input  logic clk_ref_i,
  input  logic clk_telemetry_i,

  // Reset inputs
  input  logic rst_smc_clk_ni,
  input  logic rst_periph_clk_ni,

  // AVSBus AXI-Lite CDC (SMC -> Periph)
  input  smc_pkg::smc_axil_32_32_req_t  axil_avsbus_req_smc_clk_i,
  output smc_pkg::smc_axil_32_32_resp_t axil_avsbus_resp_smc_clk_o,
  output smc_pkg::smc_axil_32_32_req_t  axil_avsbus_req_periph_clk_o,
  input  smc_pkg::smc_axil_32_32_resp_t axil_avsbus_resp_periph_clk_i,

  // I2C AXI-Lite CDC (SMC -> Periph)
  input  smc_pkg::smc_axil_32_32_req_t  axil_i2c_req_smc_clk_i,
  output smc_pkg::smc_axil_32_32_resp_t axil_i2c_resp_smc_clk_o,
  output smc_pkg::smc_axil_32_32_req_t  axil_i2c_req_periph_clk_o,
  input  smc_pkg::smc_axil_32_32_resp_t axil_i2c_resp_periph_clk_i,

  // I2C Interrupts CDC (Periph -> SMC)
  output logic [smc_config_pkg::NUM_I2C-1:0] i2c_enable_smc_clk_o,
  input  logic [smc_config_pkg::NUM_I2C-1:0] i2c_enable_periph_clk_i,
  output logic [smc_config_pkg::NUM_I2C-1:0] i2c_irqs_smc_clk_o,
  input  logic [smc_config_pkg::NUM_I2C-1:0] i2c_irqs_periph_clk_i,

  // I2C Debug Bus CDC (Periph -> SMC). Visibility-only path consumed by the
  // SMC debug bus mux. Per-bit sync is acceptable; coherency across bits is
  // not required for debug observation.
  input  logic [smc_config_pkg::NUM_I2C-1:0][3:0] i2c_debug_periph_clk_i,
  output logic [smc_config_pkg::NUM_I2C-1:0][3:0] i2c_debug_smc_clk_o,

  // UART AXI-Lite CDC (SMC -> Periph)
  input  smc_pkg::smc_axil_32_32_req_t  axil_uart_req_smc_clk_i,
  output smc_pkg::smc_axil_32_32_resp_t axil_uart_resp_smc_clk_o,
  output smc_pkg::smc_axil_32_32_req_t  axil_uart_req_periph_clk_o,
  input  smc_pkg::smc_axil_32_32_resp_t axil_uart_resp_periph_clk_i,

  // Log Engine AXI-Lite CDC (Periph -> SMC)
  output smc_pkg::smc_axil_56_64_req_t  axil_log_engine_req_smc_clk_o,
  input  smc_pkg::smc_axil_56_64_resp_t axil_log_engine_resp_smc_clk_i,
  input  smc_pkg::smc_axil_56_64_req_t  axil_log_engine_req_periph_clk_i,
  output smc_pkg::smc_axil_56_64_resp_t axil_log_engine_resp_periph_clk_o,

  // UART Interrupts CDC (Periph -> SMC)
  output logic [smc_config_pkg::NUM_UART-1:0] uart_enable_smc_clk_o,
  input  logic [smc_config_pkg::NUM_UART-1:0] uart_enable_periph_clk_i,

  output logic [smc_config_pkg::NUM_UART-1:0] uart_irq_combined_smc_clk_o,
  input  logic [smc_config_pkg::NUM_UART-1:0] uart_err_periph_clk_i,
  input  logic [smc_config_pkg::NUM_UART-1:0] uart_irq_periph_clk_i,
  input  logic [smc_config_pkg::NUM_UART-1:0] log_engine_irq_periph_clk_i,

  // I3C AXI-Lite CDC (SMC -> Periph)
  input  smc_pkg::smc_axil_32_32_req_t  axil_i3c_req_smc_clk_i,
  output smc_pkg::smc_axil_32_32_resp_t axil_i3c_resp_smc_clk_o,
  output smc_pkg::smc_axil_32_32_req_t  axil_i3c_req_periph_clk_o,
  input  smc_pkg::smc_axil_32_32_resp_t axil_i3c_resp_periph_clk_i,

  // I3C Interrupts CDC (Periph -> SMC)
  output logic [smc_config_pkg::NUM_I3C-1:0] i3c_irqs_smc_clk_o,
  input  logic [smc_config_pkg::NUM_I3C-1:0] i3c_irqs_periph_clk_i,

  // AVSBus Interrupt CDC (Periph -> SMC)
  input  logic avsbus_irq_periph_clk_i,
  output logic avsbus_irq_smc_clk_o,

  // Clock gate enable CDC (SMC clk -> Periph clk)
  input  logic i2c_cg_en_smc_clk_i,
  output logic i2c_cg_en_periph_clk_o,
  input  logic uart_cg_en_smc_clk_i,
  output logic uart_cg_en_periph_clk_o,
  input  logic avs_cg_en_smc_clk_i,
  output logic avs_cg_en_periph_clk_o,
  input  logic i3c_cg_en_smc_clk_i,
  output logic i3c_cg_en_periph_clk_o,

  // Clock gate enable CDC (SMC clk -> Ref clk)
  output logic avs_cg_en_ref_clk_o,

  // Clock gate enable CDC (SMC clk -> Telemetry clk)
  input  logic tel_cg_en_smc_clk_i,
  output logic tel_cg_en_telemetry_clk_o,

  // NDM Reset Request CDC (top level input -> SMC clk)
  input  logic [smc_config_pkg::CPU_CLUSTER_COUNT-1:0] ndmreset_request_i,
  output logic [smc_config_pkg::CPU_CLUSTER_COUNT-1:0] ndmreset_request_smc_clk_o,

  input  logic [16:0] avsbus_cur_state_debug_i,
  output logic [16:0] avsbus_cur_state_debug_o
);

  ///////////////////////
  // Parameter Check   //
  ///////////////////////

  if (SYNC_STAGES != 2 && SYNC_STAGES != 3) begin : gen_invalid_sync_stages
    $fatal(1, "SYNC_STAGES must be 2 or 3, got %0d", SYNC_STAGES);
  end

  //////////////////////////
  // AVSBus AXI-Lite CDC   //
  // SMC clk -> Periph clk //
  //////////////////////////

  axi_cdc #(
    .aw_chan_t  (smc_pkg::smc_axil_32_32_aw_chan_t),
    .w_chan_t   (smc_pkg::smc_axil_32_32_w_chan_t),
    .b_chan_t   (smc_pkg::smc_axil_32_32_b_chan_t),
    .ar_chan_t  (smc_pkg::smc_axil_32_32_ar_chan_t),
    .r_chan_t   (smc_pkg::smc_axil_32_32_r_chan_t),
    .axi_req_t  (smc_pkg::smc_axil_32_32_req_t),
    .axi_resp_t (smc_pkg::smc_axil_32_32_resp_t),
    .LogDepth   (1),
    .SyncStages (SYNC_STAGES)
  ) u_avsbus_axi_cdc (
    // Source side (SMC clock domain)
    .src_clk_i  (clk_smc_i),
    .src_rst_ni (rst_smc_clk_ni),
    .src_req_i  (axil_avsbus_req_smc_clk_i),
    .src_resp_o (axil_avsbus_resp_smc_clk_o),
    // Destination side (Periph clock domain)
    .dst_clk_i  (clk_periph_i),
    .dst_rst_ni (rst_periph_clk_ni),
    .dst_req_o  (axil_avsbus_req_periph_clk_o),
    .dst_resp_i (axil_avsbus_resp_periph_clk_i)
  );

  //////////////////////////
  // I2C AXI-Lite CDC     //
  // SMC clk -> Periph clk //
  //////////////////////////

  axi_cdc #(
    .aw_chan_t  (smc_pkg::smc_axil_32_32_aw_chan_t),
    .w_chan_t   (smc_pkg::smc_axil_32_32_w_chan_t),
    .b_chan_t   (smc_pkg::smc_axil_32_32_b_chan_t),
    .ar_chan_t  (smc_pkg::smc_axil_32_32_ar_chan_t),
    .r_chan_t   (smc_pkg::smc_axil_32_32_r_chan_t),
    .axi_req_t  (smc_pkg::smc_axil_32_32_req_t),
    .axi_resp_t (smc_pkg::smc_axil_32_32_resp_t),
    .LogDepth   (1),
    .SyncStages (SYNC_STAGES)
  ) u_i2c_axi_cdc (
    // Source side (SMC clock domain)
    .src_clk_i  (clk_smc_i),
    .src_rst_ni (rst_smc_clk_ni),
    .src_req_i  (axil_i2c_req_smc_clk_i),
    .src_resp_o (axil_i2c_resp_smc_clk_o),
    // Destination side (Periph clock domain)
    .dst_clk_i  (clk_periph_i),
    .dst_rst_ni (rst_periph_clk_ni),
    .dst_req_o  (axil_i2c_req_periph_clk_o),
    .dst_resp_i (axil_i2c_resp_periph_clk_i)
  );

  ///////////////////////////
  // UART AXI-Lite CDC     //
  // SMC clk -> Periph clk //
  ///////////////////////////

  axi_cdc #(
    .aw_chan_t  (smc_pkg::smc_axil_32_32_aw_chan_t),
    .w_chan_t   (smc_pkg::smc_axil_32_32_w_chan_t),
    .b_chan_t   (smc_pkg::smc_axil_32_32_b_chan_t),
    .ar_chan_t  (smc_pkg::smc_axil_32_32_ar_chan_t),
    .r_chan_t   (smc_pkg::smc_axil_32_32_r_chan_t),
    .axi_req_t  (smc_pkg::smc_axil_32_32_req_t),
    .axi_resp_t (smc_pkg::smc_axil_32_32_resp_t),
    .LogDepth   (1),
    .SyncStages (SYNC_STAGES)
  ) u_uart_axi_cdc (
    // Source side (SMC clock domain)
    .src_clk_i  (clk_smc_i),
    .src_rst_ni (rst_smc_clk_ni),
    .src_req_i  (axil_uart_req_smc_clk_i),
    .src_resp_o (axil_uart_resp_smc_clk_o),
    // Destination side (Periph clock domain)
    .dst_clk_i  (clk_periph_i),
    .dst_rst_ni (rst_periph_clk_ni),
    .dst_req_o  (axil_uart_req_periph_clk_o),
    .dst_resp_i (axil_uart_resp_periph_clk_i)
  );

  /////////////////////////////////
  // Log Engine AXI-Lite CDC     //
  // Periph clk -> SMC clk       //
  /////////////////////////////////

  axi_cdc #(
    .aw_chan_t  (smc_pkg::smc_axil_56_64_aw_chan_t),
    .w_chan_t   (smc_pkg::smc_axil_56_64_w_chan_t),
    .b_chan_t   (smc_pkg::smc_axil_56_64_b_chan_t),
    .ar_chan_t  (smc_pkg::smc_axil_56_64_ar_chan_t),
    .r_chan_t   (smc_pkg::smc_axil_56_64_r_chan_t),
    .axi_req_t  (smc_pkg::smc_axil_56_64_req_t),
    .axi_resp_t (smc_pkg::smc_axil_56_64_resp_t),
    .LogDepth   (1),
    .SyncStages (SYNC_STAGES)
  ) u_log_engine_axi_cdc (
    // Source side (Periph clock domain)
    .src_clk_i  (clk_periph_i),
    .src_rst_ni (rst_periph_clk_ni),
    .src_req_i  (axil_log_engine_req_periph_clk_i),
    .src_resp_o (axil_log_engine_resp_periph_clk_o),
    // Destination side (SMC clock domain)
    .dst_clk_i  (clk_smc_i),
    .dst_rst_ni (rst_smc_clk_ni),
    .dst_req_o  (axil_log_engine_req_smc_clk_o),
    .dst_resp_i (axil_log_engine_resp_smc_clk_i)
  );

  //////////////////////////
  // I3C AXI-Lite CDC     //
  // SMC clk -> Periph clk //
  //////////////////////////

  axi_cdc #(
    .aw_chan_t  (smc_pkg::smc_axil_32_32_aw_chan_t),
    .w_chan_t   (smc_pkg::smc_axil_32_32_w_chan_t),
    .b_chan_t   (smc_pkg::smc_axil_32_32_b_chan_t),
    .ar_chan_t  (smc_pkg::smc_axil_32_32_ar_chan_t),
    .r_chan_t   (smc_pkg::smc_axil_32_32_r_chan_t),
    .axi_req_t  (smc_pkg::smc_axil_32_32_req_t),
    .axi_resp_t (smc_pkg::smc_axil_32_32_resp_t),
    .LogDepth   (1),
    .SyncStages (SYNC_STAGES)
  ) u_i3c_axi_cdc (
    // Source side (SMC clock domain)
    .src_clk_i  (clk_smc_i),
    .src_rst_ni (rst_smc_clk_ni),
    .src_req_i  (axil_i3c_req_smc_clk_i),
    .src_resp_o (axil_i3c_resp_smc_clk_o),
    // Destination side (Periph clock domain)
    .dst_clk_i  (clk_periph_i),
    .dst_rst_ni (rst_periph_clk_ni),
    .dst_req_o  (axil_i3c_req_periph_clk_o),
    .dst_resp_i (axil_i3c_resp_periph_clk_i)
  );

  // NDM Request: async top-level input, each bit is an independent per-cluster request
  prim_sync3 #(
    .WIDTH(smc_config_pkg::CPU_CLUSTER_COUNT)
  ) u_ndmreset_request_sync (
    .clk_i (clk_smc_i),
    .d_i   (ndmreset_request_i),
    .q_o   (ndmreset_request_smc_clk_o)
  );

  // AVSBus Controller State Debug: periph clk -> SMC clk (already synced from avs_clk to periph inside avsbus_controller)
  prim_sync_data_autohs #(
    .WIDTH(17),
    .DEPTH(3)
  ) u_avsbus_cur_state_debug_sync (
    .clk_src_i  (clk_periph_i),
    .rst_src_ni (rst_periph_clk_ni),
    .data_i     (avsbus_cur_state_debug_i),
    .clk_dst_i  (clk_smc_i),
    .rst_dst_ni (rst_smc_clk_ni),
    .data_o     (avsbus_cur_state_debug_o)
  );


  ////////////////////////////
  // Interrupt Synchronizers //
  // Periph clk -> SMC clk   //
  ////////////////////////////

  // Note: for RDC analysis, these not having a reset condition right create unnessasry errors

  // For MTBF (mean time between failures) calculation to hold true, inputs to synchronizers should be void of combinational logic
  // This is motivated by NON_STATIC_COMBO_IN_CROSSING from CDC Violations report
  logic [smc_config_pkg::NUM_I2C-1:0]  i2c_enable_periph_clk_flopped;
  logic [smc_config_pkg::NUM_I2C-1:0]  i2c_irqs_periph_clk_flopped;
  logic [smc_config_pkg::NUM_I3C-1:0]  i3c_irqs_periph_clk_flopped;
  logic [smc_config_pkg::NUM_UART-1:0] uart_enable_periph_clk_flopped;
  // UART eventually combines: uart_irq_smc_clk | uart_err_smc_clk | log_engine_irq_smc_clk into one interrupt line.
  logic [smc_config_pkg::NUM_UART-1:0] uart_irq_combined_periph_clk_flopped;
  logic                                avsbus_irq_periph_clk_flopped;
  logic [smc_config_pkg::NUM_I2C-1:0][3:0]                          i2c_debug_periph_clk_flopped;

  always_ff @(posedge clk_periph_i) begin
    i2c_enable_periph_clk_flopped <= i2c_enable_periph_clk_i;
    i2c_irqs_periph_clk_flopped <= i2c_irqs_periph_clk_i;
    i3c_irqs_periph_clk_flopped <= i3c_irqs_periph_clk_i;
    uart_enable_periph_clk_flopped <= uart_enable_periph_clk_i;

    uart_irq_combined_periph_clk_flopped <= uart_irq_periph_clk_i | uart_err_periph_clk_i | log_engine_irq_periph_clk_i;
    avsbus_irq_periph_clk_flopped <= avsbus_irq_periph_clk_i;
    i2c_debug_periph_clk_flopped <= i2c_debug_periph_clk_i;
  end

  ///////////////////////////////////////////
  // Clock Gate Enable Synchronizers       //
  // SMC clk -> Periph clk (ungated)       //
  ///////////////////////////////////////////

  logic i2c_cg_en_smc_clk_flopped;
  logic uart_cg_en_smc_clk_flopped;
  logic avs_cg_en_smc_clk_flopped;
  logic i3c_cg_en_smc_clk_flopped;
  logic tel_cg_en_smc_clk_flopped;

  always_ff @(posedge clk_smc_i) begin
    i2c_cg_en_smc_clk_flopped  <= i2c_cg_en_smc_clk_i;
    uart_cg_en_smc_clk_flopped <= uart_cg_en_smc_clk_i;
    avs_cg_en_smc_clk_flopped  <= avs_cg_en_smc_clk_i;
    i3c_cg_en_smc_clk_flopped  <= i3c_cg_en_smc_clk_i;
    tel_cg_en_smc_clk_flopped  <= tel_cg_en_smc_clk_i;
  end

  generate
    if (SYNC_STAGES == 2) begin : gen_sync2

      // I2C Enable
      prim_sync2 #(
        .WIDTH(smc_config_pkg::NUM_I2C)
      ) u_i2c_enable_sync (
        .clk_i (clk_smc_i),
        .d_i   (i2c_enable_periph_clk_flopped),
        .q_o   (i2c_enable_smc_clk_o)
      );
      // I2C Interrupts
      prim_sync2 #(
        .WIDTH(smc_config_pkg::NUM_I2C)
      ) u_i2c_irq_sync (
        .clk_i (clk_smc_i),
        .d_i   (i2c_irqs_periph_clk_flopped),
        .q_o   (i2c_irqs_smc_clk_o)
      );

      // I2C Debug Bus (per-bit sync; visibility-only path)
      prim_sync2 #(
        .WIDTH(smc_config_pkg::NUM_I2C * 4)
      ) u_i2c_debug_sync (
        .clk_i (clk_smc_i),
        .d_i   (i2c_debug_periph_clk_flopped),
        .q_o   (i2c_debug_smc_clk_o)
      );

      // UART Enable
      prim_sync2 #(
        .WIDTH(smc_config_pkg::NUM_UART)
      ) u_uart_enable_sync (
        .clk_i (clk_smc_i),
        .d_i   (uart_enable_periph_clk_flopped),
        .q_o   (uart_enable_smc_clk_o)
      );

      // UART Combined Interrupts
      prim_sync2 #(
        .WIDTH(smc_config_pkg::NUM_UART)
      ) u_uart_combined_irq_sync (
        .clk_i (clk_smc_i),
        .d_i   (uart_irq_combined_periph_clk_flopped),
        .q_o   (uart_irq_combined_smc_clk_o)
      );

      // I3C Interrupts
      prim_sync2 #(
        .WIDTH(smc_config_pkg::NUM_I3C)
      ) u_i3c_irq_sync (
        .clk_i (clk_smc_i),
        .d_i   (i3c_irqs_periph_clk_flopped),
        .q_o   (i3c_irqs_smc_clk_o)
      );

      // AVSBus Interrupt
      prim_sync2 u_avsbus_irq_sync (
        .clk_i (clk_smc_i),
        .d_i   (avsbus_irq_periph_clk_flopped),
        .q_o   (avsbus_irq_smc_clk_o)
      );

      // Clock gate enables (SMC -> Periph, synced to ungated clk_periph_i)
      prim_sync2 u_i2c_cg_en_sync (
        .clk_i (clk_periph_i),
        .d_i   (i2c_cg_en_smc_clk_flopped),
        .q_o   (i2c_cg_en_periph_clk_o)
      );
      prim_sync2 u_uart_cg_en_sync (
        .clk_i (clk_periph_i),
        .d_i   (uart_cg_en_smc_clk_flopped),
        .q_o   (uart_cg_en_periph_clk_o)
      );
      prim_sync2 u_avs_cg_en_periph_sync (
        .clk_i (clk_periph_i),
        .d_i   (avs_cg_en_smc_clk_flopped),
        .q_o   (avs_cg_en_periph_clk_o)
      );
      prim_sync2 u_i3c_cg_en_sync (
        .clk_i (clk_periph_i),
        .d_i   (i3c_cg_en_smc_clk_flopped),
        .q_o   (i3c_cg_en_periph_clk_o)
      );

      // Clock gate enable (SMC -> Ref, synced to ungated clk_ref_i)
      prim_sync2 u_avs_cg_en_ref_sync (
        .clk_i (clk_ref_i),
        .d_i   (avs_cg_en_smc_clk_flopped),
        .q_o   (avs_cg_en_ref_clk_o)
      );

      // Clock gate enable (SMC -> Telemetry, synced to ungated clk_telemetry_i)
      prim_sync2 u_tel_cg_en_sync (
        .clk_i (clk_telemetry_i),
        .d_i   (tel_cg_en_smc_clk_flopped),
        .q_o   (tel_cg_en_telemetry_clk_o)
      );
    end else begin : gen_sync3
      // I2C Enable
      prim_sync3 #(
        .WIDTH(smc_config_pkg::NUM_I2C)
      ) u_i2c_enable_sync (
        .clk_i (clk_smc_i),
        .d_i   (i2c_enable_periph_clk_flopped),
        .q_o   (i2c_enable_smc_clk_o)
      );
      // I2C Interrupts
      prim_sync3 #(
        .WIDTH(smc_config_pkg::NUM_I2C)
      ) u_i2c_irq_sync (
        .clk_i (clk_smc_i),
        .d_i   (i2c_irqs_periph_clk_flopped),
        .q_o   (i2c_irqs_smc_clk_o)
      );

      // I2C Debug Bus (per-bit sync; visibility-only path)
      prim_sync3 #(
        .WIDTH(smc_config_pkg::NUM_I2C * 4)
      ) u_i2c_debug_sync (
        .clk_i (clk_smc_i),
        .d_i   (i2c_debug_periph_clk_flopped),
        .q_o   (i2c_debug_smc_clk_o)
      );

      // UART Enable
      prim_sync3 #(
        .WIDTH(smc_config_pkg::NUM_UART)
      ) u_uart_enable_sync (
        .clk_i (clk_smc_i),
        .d_i   (uart_enable_periph_clk_flopped),
        .q_o   (uart_enable_smc_clk_o)
      );

      // UART Combined Interrupts
      prim_sync3 #(
        .WIDTH(smc_config_pkg::NUM_UART)
      ) u_uart_combined_irq_sync (
        .clk_i (clk_smc_i),
        .d_i   (uart_irq_combined_periph_clk_flopped),
        .q_o   (uart_irq_combined_smc_clk_o)
      );

      // I3C Interrupts
      prim_sync3 #(
        .WIDTH(smc_config_pkg::NUM_I3C)
      ) u_i3c_irq_sync (
        .clk_i (clk_smc_i),
        .d_i   (i3c_irqs_periph_clk_flopped),
        .q_o   (i3c_irqs_smc_clk_o)
      );

      // AVSBus Interrupt
      prim_sync3 u_avsbus_irq_sync (
        .clk_i (clk_smc_i),
        .d_i   (avsbus_irq_periph_clk_flopped),
        .q_o   (avsbus_irq_smc_clk_o)
      );

      // Clock gate enables (SMC -> Periph, synced to ungated clk_periph_i)
      prim_sync3 u_i2c_cg_en_sync (
        .clk_i (clk_periph_i),
        .d_i   (i2c_cg_en_smc_clk_flopped),
        .q_o   (i2c_cg_en_periph_clk_o)
      );
      prim_sync3 u_uart_cg_en_sync (
        .clk_i (clk_periph_i),
        .d_i   (uart_cg_en_smc_clk_flopped),
        .q_o   (uart_cg_en_periph_clk_o)
      );
      prim_sync3 u_avs_cg_en_periph_sync (
        .clk_i (clk_periph_i),
        .d_i   (avs_cg_en_smc_clk_flopped),
        .q_o   (avs_cg_en_periph_clk_o)
      );
      prim_sync3 u_i3c_cg_en_sync (
        .clk_i (clk_periph_i),
        .d_i   (i3c_cg_en_smc_clk_flopped),
        .q_o   (i3c_cg_en_periph_clk_o)
      );

      // Clock gate enable (SMC -> Ref, synced to ungated clk_ref_i)
      prim_sync3 u_avs_cg_en_ref_sync (
        .clk_i (clk_ref_i),
        .d_i   (avs_cg_en_smc_clk_flopped),
        .q_o   (avs_cg_en_ref_clk_o)
      );

      // Clock gate enable (SMC -> Telemetry, synced to ungated clk_telemetry_i)
      prim_sync3 u_tel_cg_en_sync (
        .clk_i (clk_telemetry_i),
        .d_i   (tel_cg_en_smc_clk_flopped),
        .q_o   (tel_cg_en_telemetry_clk_o)
      );
    end
  endgenerate

endmodule
