// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// Invert a clock, optionally bypassing the inversion in scan mode.
//
// With HasScanMode, scanmode_i high selects the uninverted clock through prim_clock_mux2.
module prim_clock_inv #(
  parameter bit HasScanMode = 1'b1,  // Bypass the inversion while scanmode_i is high.
  parameter bit NoFpgaBufG  = 1'b0  // Unused outside FPGA builds.
) (
  input  logic clk_i,  // Clock to invert.
  input  logic scanmode_i,  // Scan mode; unused without HasScanMode.
  output logic clk_no  // Inverted clock.
);
  logic clk_inv;

  (* dont_touch = "true" *)
  sg13g2_inv_1 u_inv (
    .A       (clk_i),
    .Y       (clk_inv)
  );

  if (HasScanMode) begin : gen_scan
    prim_clock_mux2 #(
      .NoFpgaBufG(NoFpgaBufG)
    ) u_dft_mux (
      .clk0_i(clk_inv),
      .clk1_i(clk_i),
      .sel_i (scanmode_i),
      .clk_o (clk_no)
    );
  end else begin : gen_noscan
    logic unused_scanmode;
    assign unused_scanmode = scanmode_i;
    assign clk_no = clk_inv;
  end
endmodule
