// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// Declare pad and mux types for the SMC padring.
//
// Holds DefaultDirectionMap, the reset-default direction of each GPIO pad (GPIO 59-62 and
// 64-66 output, all others input), LsioIdleLevelMap, the level each pad's LSIO input returns
// while no LSIO select is active, and pad_enable_e, the active-low LSIO enable encoding
// (ENABLED is 0, DISABLED is 1) used by smc_padring.

package smc_padring_pkg;


  localparam bit IsInput = 1'b1;
  localparam bit IsOutput = 1'b0;

  localparam bit [smc_pkg::NumGpioWraps-1:0] DefaultDirectionMap = {
    IsOutput,  // 66.
    IsOutput,  // 65.
    IsOutput,  // 64.
    IsInput,  // 63.
    IsOutput,  // 62.
    IsOutput,  // 61.
    IsOutput,  // 60.
    IsOutput,  // 59.
    IsInput,  // 58.
    IsInput,  // 57.
    IsInput,  // 56.
    IsInput,  // 55.
    IsInput,  // 54.
    IsInput,  // 53.
    IsInput,  // 52.
    IsInput,  // 51.
    IsInput,  // 50.
    IsInput,  // 49.
    IsInput,  // 48.
    IsInput,  // 47.
    IsInput,  // 46.
    IsInput,  // 45.
    IsInput,  // 44.
    IsInput,  // 43.
    IsInput,  // 42.
    IsInput,  // 41.
    IsInput,  // 40.
    IsInput,  // 39.
    IsInput,  // 38.
    IsInput,  // 37.
    IsInput,  // 36.
    IsInput,  // 35.
    IsInput,  // 34.
    IsInput,  // 33.
    IsInput,  // 32.
    IsInput,  // 31.
    IsInput,  // 30.
    IsInput,  // 29.
    IsInput,  // 28.
    IsInput,  // 27.
    IsInput,  // 26.
    IsInput,  // 25.
    IsInput,  // 24.
    IsInput,  // 23.
    IsInput,  // 22.
    IsInput,  // 21.
    IsInput,  // 20.
    IsInput,  // 19.
    IsInput,  // 18.
    IsInput,  // 17.
    IsInput,  // 16.
    IsInput,  // 15.
    IsInput,  // 14.
    IsInput,  // 13.
    IsInput,  // 12.
    IsInput,  // 11.
    IsInput,  // 10.
    IsInput,  //  9.
    IsInput,  //  8.
    IsInput,  //  7.
    IsInput,  //  6.
    IsInput,  //  5.
    IsInput,  //  4.
    IsInput,  //  3.
    IsInput,  //  2.
    IsInput,  //  1.
    IsInput  //  0.
  };

  // Level a pad's LSIO input returns to its function while no LSIO select is active: high for
  // the serial inputs that idle high (UART RX and CTS, I2C SCL, SDA and the SMBus ALERT and SUS
  // inputs, I3C SCL and SDA).
  localparam bit IdleHigh = 1'b1;
  localparam bit IdleLow = 1'b0;

  localparam bit [smc_pkg::NumGpioWraps-1:0] LsioIdleLevelMap = {
    IdleHigh,  // 66.
    IdleHigh,  // 65.
    IdleLow,  // 64.
    IdleLow,  // 63.
    IdleLow,  // 62.
    IdleLow,  // 61.
    IdleLow,  // 60.
    IdleLow,  // 59.
    IdleLow,  // 58.
    IdleLow,  // 57.
    IdleLow,  // 56.
    IdleLow,  // 55.
    IdleLow,  // 54.
    IdleLow,  // 53.
    IdleLow,  // 52.
    IdleLow,  // 51.
    IdleLow,  // 50.
    IdleLow,  // 49.
    IdleHigh,  // 48.
    IdleHigh,  // 47.
    IdleHigh,  // 46.
    IdleHigh,  // 45.
    IdleHigh,  // 44.
    IdleHigh,  // 43.
    IdleHigh,  // 42.
    IdleHigh,  // 41.
    IdleHigh,  // 40.
    IdleHigh,  // 39.
    IdleHigh,  // 38.
    IdleHigh,  // 37.
    IdleHigh,  // 36.
    IdleHigh,  // 35.
    IdleHigh,  // 34.
    IdleHigh,  // 33.
    IdleHigh,  // 32.
    IdleHigh,  // 31.
    IdleHigh,  // 30.
    IdleHigh,  // 29.
    IdleHigh,  // 28.
    IdleHigh,  // 27.
    IdleHigh,  // 26.
    IdleLow,  // 25.
    IdleLow,  // 24.
    IdleHigh,  // 23.
    IdleHigh,  // 22.
    IdleLow,  // 21.
    IdleLow,  // 20.
    IdleHigh,  // 19.
    IdleHigh,  // 18.
    IdleLow,  // 17.
    IdleLow,  // 16.
    IdleHigh,  // 15.
    IdleHigh,  // 14.
    IdleLow,  // 13.
    IdleLow,  // 12.
    IdleHigh,  // 11.
    IdleLow,  // 10.
    IdleLow,  //  9.
    IdleLow,  //  8.
    IdleLow,  //  7.
    IdleLow,  //  6.
    IdleLow,  //  5.
    IdleLow,  //  4.
    IdleLow,  //  3.
    IdleLow,  //  2.
    IdleLow,  //  1.
    IdleLow  //  0.
  };

  //////////////////
  // Pad Settings //
  //////////////////

  typedef enum logic {
    DISABLED = 1'b1,
    ENABLED  = 1'b0
  } pad_enable_e;

endpackage
