// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// Declare pad and mux types for the SMC padring.
//
// Holds DefaultDirectionMap, the reset-default direction of each GPIO pad (GPIO 62-64
// output, all others input), and pad_enable_e, the active-low LSIO enable encoding
// (ENABLED is 0, DISABLED is 1) used by smc_padring.

package smc_padring_pkg;


  localparam bit IsInput = 1'b1;
  localparam bit IsOutput = 1'b0;

  localparam bit [smc_pkg::NumGpioWraps-1:0] DefaultDirectionMap = {
    IsOutput,  // 64.
    IsOutput,  // 63.
    IsOutput,  // 62.
    IsInput,  // 61.
    IsInput,  // 60.
    IsInput,  // 59.
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

  //////////////////
  // Pad Settings //
  //////////////////

  typedef enum logic {
    DISABLED = 1'b1,
    ENABLED  = 1'b0
  } pad_enable_e;

endpackage
