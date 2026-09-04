// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

//--------------------------------------------------
// Binary to Gray Converter
//
//--------------------------------------------------
module prim_bin2gray #(
  parameter int N = -1
) (
  input  logic [N-1:0] A,
  output logic [N-1:0] Z
);
  assign Z = A ^ (A >> 1);
endmodule
