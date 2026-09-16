// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

//--------------------------------------------------
// Gray to Binary Converter
//
//--------------------------------------------------
module prim_gray2bin #(
  parameter int N = -1
) (
  input  logic [N-1:0] A,
  output logic [N-1:0] Z
);
  for (genvar i = 0; i < N; i++) assign Z[i] = ^A[N-1:i];
endmodule
