// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// Vendor generic buf name. Instantiates prim_buf so a foundry overlay on that
// module applies here too.
module abr_prim_generic_buf #(
  parameter int Width = 1
) (
  input        [Width-1:0] in_i,
  output logic [Width-1:0] out_o
);

  prim_buf #(
    .Width(Width)
  ) u_buf (
    .in_i (in_i),
    .out_o(out_o)
  );

endmodule
