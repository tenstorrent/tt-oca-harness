// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

//-----------------------------------------------------------------------------
// Parameterized Right Rotator Module
//
// This module performs a right rotation on an input value by a specified
// amount modulo the data width.
//
// Copyright 2026 Tenstorrent Inc.
//
//-----------------------------------------------------------------------------

module scrambler_rotator #(
  parameter int unsigned DATA_WIDTH = 9,
  parameter int unsigned ROT_WIDTH = $clog2(DATA_WIDTH)
) (
  input  logic [DATA_WIDTH-1:0]     data_i,
  input  logic [ROT_WIDTH-1:0]      rotate_amt_i,
  output logic [DATA_WIDTH-1:0]     data_o
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
