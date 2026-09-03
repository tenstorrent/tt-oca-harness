// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

//-----------------------------------------------------------------------------
// System Management Controller Configuration Package
//
//-----------------------------------------------------------------------------

`ifndef SMC_CONFIG_PACKAGE_DEFINED
`define SMC_CONFIG_PACKAGE_DEFINED
package smc_config_pkg;

  ////////////////////
  // I3C Parameters //
  ////////////////////
  localparam int unsigned NUM_I3C = 6;    // a minimum of 3 is required, [0] for board level communication, [1] and [2] for interchiplet communication

  ////////////////////
  // I2C Parameters //
  ////////////////////

  localparam int unsigned NUM_I2C = 3;
  localparam int unsigned I2C_CONTROLLER_TX_FIFO_DEPTH = 64;
  localparam int unsigned I2C_CONTROLLER_RX_FIFO_DEPTH = 64;
  localparam int unsigned I2C_TARGET_TX_FIFO_DEPTH = 64;
  localparam int unsigned I2C_TARGET_RX_FIFO_DEPTH = 64;
  localparam int unsigned I2C_INPUT_DELAY_CYCLES = 0; // Round-trip delay for outputs to appear/loopback on the inputs, not including rise time. This is the input delay external to this IP, based on smc clock cycles

  //////////////////////////
  // Telemetry Parameters //
  //////////////////////////

  localparam int unsigned NUM_TELEMETRY_RECEIVERS = 3;  // MAX: 16
  localparam int unsigned TELEMETRY_RECEIVER_BUFFER_DEPTH = 8;    // must be greater than or equal to 2
  localparam int unsigned TELEMETRY_RECEIVER_MAX_NUM_COUNTERS_PER_MESSAGE [NUM_TELEMETRY_RECEIVERS-1:0] = '{
      default: 4
  };  // # of counters you can receive as telemetry information in one burst

  /////////////////////
  // UART Parameters //
  /////////////////////

  localparam int unsigned NUM_UART = 4;
  localparam int unsigned UART_TX_FIFO_DEPTH = 32;
  localparam int unsigned UART_RX_FIFO_DEPTH = 32;
  localparam int unsigned LOG_ENGINE_FIFO_DEPTH = 4;
  localparam bit [NUM_UART-1:0] GEN_LOG_ENGINES = {NUM_UART{1'b1}};    // determines which UART instances have a log engine

  ///////////////////////
  // AVSBus Parameters //
  ///////////////////////

  localparam int unsigned AVS_COMMAND_FIFO_DEPTH = 8;
  localparam int unsigned AVS_READBACK_FIFO_DEPTH = 8;

  ////////////////////////////
  // CPU Control Parameters //
  ////////////////////////////

  localparam logic [7:0] CPU_CLUSTER_COUNT = 4;       // number of CPU clusters in the system for NDM request

  /////////////////////
  // Misc Parameters //
  /////////////////////

  localparam int unsigned CHIP_ID = 0;        // 32 bit value for you to assign a register to, this val can be read by SW as an chip indiciator

  /////////////////////////////
  // Output Remap Parameters //
  /////////////////////////////

  localparam bit NO_ADDR_REMAP = 1'b0;

endpackage
`endif  // SMC_CONFIG_PACKAGE_DEFINED
