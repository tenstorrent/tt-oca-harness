// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
// Copyright 2026 Tenstorrent Inc.

// Right-rotate data_i by rotate_amt_i.
//
// The rotate amount is reduced modulo DATA_WIDTH for widths 9, 10 and 12 and wraps
// naturally when DATA_WIDTH is a power of two; for any other width an amount of DATA_WIDTH
// or more shifts zeros in instead of rotating.

module scrambler_rotator #(
  parameter int unsigned DATA_WIDTH = 9,                    // Word width to rotate.
  parameter int unsigned ROT_WIDTH = $clog2(DATA_WIDTH)     // Rotate-amount width;
                                                            // clog2(DATA_WIDTH) reaches every
                                                            // rotation.
) (
  input  logic [DATA_WIDTH-1:0]     data_i,                 // Value to rotate.
  input  logic [ROT_WIDTH-1:0]      rotate_amt_i,           // Right-rotate amount.
  output logic [DATA_WIDTH-1:0]     data_o                  // Rotated value.
);
  logic [ROT_WIDTH-1:0] rotate_amt;

  // Compute rotation amount modulo DATA_WIDTH
  assign rotate_amt = (DATA_WIDTH == 9)  ? (rotate_amt_i % 4'd9) :
                        (DATA_WIDTH == 10) ? (rotate_amt_i % 4'd10) :
                        (DATA_WIDTH == 12) ? (rotate_amt_i % 4'd12) :
                        rotate_amt_i;

  logic [2*DATA_WIDTH-1:0] data_data;
  logic [2*DATA_WIDTH-1:0] data_data_ror;
  assign data_data = {data_i, data_i};
  assign data_data_ror = data_data >> rotate_amt;
  assign data_o = data_data_ror[DATA_WIDTH-1:0];
endmodule
