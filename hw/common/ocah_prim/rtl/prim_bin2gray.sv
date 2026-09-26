// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// Convert an N-bit binary value to Gray code.
//
// Drive each z_o[i] as a_i[i] XOR a_i[i+1], and copy the MSB.
// N must be positive at elaboration.

module prim_bin2gray #(
  parameter int N = -1  // Operand width.
) (
  input  logic [N-1:0] a_i,  // Binary input.
  output logic [N-1:0] z_o  // Gray-coded output.
);
  assign z_o = a_i ^ (a_i >> 1);
endmodule
