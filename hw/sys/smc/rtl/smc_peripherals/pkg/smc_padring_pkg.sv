// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// Declare pad and mux types for the SMC padring.
//
// Groups pad-control structs the padring and peripheral wrapper share.
// Keeps pad-side widths consistent across I3C, I2C, UART, and GPIO paths.

package smc_padring_pkg;


  localparam bit IS_INPUT = 1'b1;
  localparam bit IS_OUTPUT = 1'b0;

  localparam bit [smc_pkg::NUM_GPIO_WRAPS-1:0] DefaultDirectionMap = {
    IS_OUTPUT,  // 64.
    IS_OUTPUT,  // 63.
    IS_OUTPUT,  // 62.
    IS_INPUT,  // 61.
    IS_INPUT,  // 60.
    IS_INPUT,  // 59.
    IS_INPUT,  // 58.
    IS_INPUT,  // 57.
    IS_INPUT,  // 56.
    IS_INPUT,  // 55.
    IS_INPUT,  // 54.
    IS_INPUT,  // 53.
    IS_INPUT,  // 52.
    IS_INPUT,  // 51.
    IS_INPUT,  // 50.
    IS_INPUT,  // 49.
    IS_INPUT,  // 48.
    IS_INPUT,  // 47.
    IS_INPUT,  // 46.
    IS_INPUT,  // 45.
    IS_INPUT,  // 44.
    IS_INPUT,  // 43.
    IS_INPUT,  // 42.
    IS_INPUT,  // 41.
    IS_INPUT,  // 40.
    IS_INPUT,  // 39.
    IS_INPUT,  // 38.
    IS_INPUT,  // 37.
    IS_INPUT,  // 36.
    IS_INPUT,  // 35.
    IS_INPUT,  // 34.
    IS_INPUT,  // 33.
    IS_INPUT,  // 32.
    IS_INPUT,  // 31.
    IS_INPUT,  // 30.
    IS_INPUT,  // 29.
    IS_INPUT,  // 28.
    IS_INPUT,  // 27.
    IS_INPUT,  // 26.
    IS_INPUT,  // 25.
    IS_INPUT,  // 24.
    IS_INPUT,  // 23.
    IS_INPUT,  // 22.
    IS_INPUT,  // 21.
    IS_INPUT,  // 20.
    IS_INPUT,  // 19.
    IS_INPUT,  // 18.
    IS_INPUT,  // 17.
    IS_INPUT,  // 16.
    IS_INPUT,  // 15.
    IS_INPUT,  // 14.
    IS_INPUT,  // 13.
    IS_INPUT,  // 12.
    IS_INPUT,  // 11.
    IS_INPUT,  // 10.
    IS_INPUT,  //  9.
    IS_INPUT,  //  8.
    IS_INPUT,  //  7.
    IS_INPUT,  //  6.
    IS_INPUT,  //  5.
    IS_INPUT,  //  4.
    IS_INPUT,  //  3.
    IS_INPUT,  //  2.
    IS_INPUT,  //  1.
    IS_INPUT  //  0.
  };

  //////////////////
  // Pad Settings //
  //////////////////

  typedef enum logic {
    DISABLED = 1'b1,
    ENABLED  = 1'b0
  } pad_enable_t;

endpackage
