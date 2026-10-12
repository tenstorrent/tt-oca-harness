// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// Buffer a clock.
//
// Maps to one sg13g2_buf_1; the FPGA parameters have no effect.
module prim_clock_buf #(
  parameter bit NoFpgaBuf = 1'b0,  // FPGA buffer bypass; unused by the cell.
  parameter bit RegionSel = 1'b0  // FPGA regional buffer select; unused by the cell.
) (
  input  logic clk_i,  // Clock to buffer.
  output logic clk_o  // Buffered clock.
);
  (* dont_touch = "true" *)
  sg13g2_buf_1 u_cell (
    .A       (clk_i),
    .X       (clk_o)
  );
endmodule
