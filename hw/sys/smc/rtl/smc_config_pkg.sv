// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// Configure SMC peripheral instance counts and FIFO depths.
//
// Sets how many I3C, I2C, UART, telemetry, and AVSBus instances the SMC builds.
// FIFO and delay parameters here size those peripheral wrappers. Also sets the CPU
// cluster count for NDM reset requests, the chip ID reported in chip_config, and whether
// the output fabric omits the M-mode and Xvisor remap.

`ifndef SMC_CONFIG_PACKAGE_DEFINED
`define SMC_CONFIG_PACKAGE_DEFINED

package smc_config_pkg;

  ////////////////////
  // I3C Parameters //
  ////////////////////
  localparam int unsigned NumI3c = 6;    // a minimum of 3 is required, [0] for board level communication, [1] and [2] for interchiplet communication.

  ////////////////////
  // I2C Parameters //
  ////////////////////

  localparam int unsigned NumI2c = 3;
  localparam int unsigned I2cControllerTxFifoDepth = 64;
  localparam int unsigned I2cControllerRxFifoDepth = 64;
  localparam int unsigned I2cTargetTxFifoDepth = 64;
  localparam int unsigned I2cTargetRxFifoDepth = 64;
  localparam int unsigned I2cInputDelayCycles = 0; // Round-trip delay for outputs to appear/loopback on the inputs, not including rise time. This is the input delay external to this IP, based on smc clock cycles.

  //////////////////////////
  // Telemetry Parameters //
  //////////////////////////

  localparam int unsigned NumTelemetryReceivers = 3;  // MAX: 16.
  localparam int unsigned TelemetryReceiverBufferDepth = 8;  // must be greater than or equal to 2.
  localparam int unsigned TelemetryReceiverMaxNumCountersPerMessage[NumTelemetryReceivers-1:0] = '{
      default: 4
  };  // # of counters you can receive as telemetry information in one burst.

  /////////////////////
  // UART Parameters //
  /////////////////////

  localparam int unsigned NumUart = 4;
  localparam int unsigned UartTxFifoDepth = 32;
  localparam int unsigned UartRxFifoDepth = 32;
  localparam int unsigned LogEngineFifoDepth = 4;
  localparam bit [NumUart-1:0] GenLogEngines = {NumUart{1'b1}};    // determines which UART instances have a log engine.

  ///////////////////////
  // AVSBus Parameters //
  ///////////////////////

  localparam int unsigned AvsCommandFifoDepth = 8;
  localparam int unsigned AvsReadbackFifoDepth = 8;

  ////////////////////////////
  // CPU Control Parameters //
  ////////////////////////////

  localparam logic [7:0] CpuClusterCount = 4;       // number of CPU clusters in the system for NDM request.

  /////////////////////
  // Misc Parameters //
  /////////////////////

  localparam int unsigned ChipId = 0;        // 32 bit value for you to assign a register to, this val can be read by SW as an chip indiciator.

  /////////////////////////////
  // Output Remap Parameters //
  /////////////////////////////

  localparam bit NoAddrRemap = 1'b0;

endpackage
`endif  // SMC_CONFIG_PACKAGE_DEFINED
