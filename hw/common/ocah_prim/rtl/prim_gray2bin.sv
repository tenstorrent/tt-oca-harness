// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// Convert an N-bit Gray code value to binary.
//
// Drive each z_o bit as the XOR reduction of a_i from that bit through the MSB.
// N must be positive at elaboration.

module prim_gray2bin #(
  parameter int N = -1  // Operand width.
) (
  input  logic [N-1:0] a_i,  // Gray-coded input.
  output logic [N-1:0] z_o  // Binary output.
);
  for (genvar i = 0; i < N; i++) begin : gen_gray2bin
    assign z_o[i] = ^a_i[N-1:i];
  end
endmodule
