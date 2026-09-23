// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

//--------------------------------------------------
// Clock Gater with Hysteresis
//
//--------------------------------------------------
module prim_clk_gater_hysteresis #(
  parameter int unsigned HYST_WIDTH = 6
) (
  input logic clk_i,
  input logic rst_ni,

  input logic busy_i,
  input logic enable_i,
  input logic kick_i,
  input logic test_clk_en_i,

  input logic [HYST_WIDTH-1:0] hysteresis_i,

  output logic clk_active_o,
  output logic gated_clk_o
);
  logic sticky_kick_en;
  logic load_hyst;
  logic dec_hyst;
  logic nz_hyst;
  logic busy_seen_d;
  logic busy_seen_q;
  logic [HYST_WIDTH  :0] hyst_cnt_nxt;
  logic [HYST_WIDTH-1:0] hyst_cnt_d;
  logic [HYST_WIDTH-1:0] hyst_cnt_q;
  logic run;

  always_comb begin
    sticky_kick_en = &hysteresis_i;

    load_hyst = kick_i | busy_i;
    nz_hyst = (|hyst_cnt_q);

    dec_hyst  = enable_i & ~busy_i & (busy_seen_q | ~sticky_kick_en) & nz_hyst;

    hyst_cnt_nxt = hyst_cnt_q - dec_hyst;
    hyst_cnt_d = load_hyst ? hysteresis_i : hyst_cnt_nxt[HYST_WIDTH-1:0];

    busy_seen_d = (busy_i | ~enable_i) | (busy_seen_q & ~kick_i);

    run = ~rst_ni | kick_i | nz_hyst | ~enable_i;
    clk_active_o = run;
  end

  always_ff @(posedge clk_i) begin
    if (~rst_ni) begin
      busy_seen_q <= '0;
      hyst_cnt_q  <= '1;
    end else begin
      busy_seen_q <= busy_seen_d;
      hyst_cnt_q  <= hyst_cnt_d;
    end
  end

  prim_clkgater u_clkgater (
    .clk_i(clk_i),
    .en_i (run),
    .te_i (test_clk_en_i),
    .clk_o(gated_clk_o)
  );

  wire __unused = hyst_cnt_nxt[HYST_WIDTH]; // Since we block the decrement when hyst_cnt_q is already 0, no need to capture carry-out

`ifdef SIMULATION
`ifdef GATER_CHK
  `export_dpi_get(int, gater, rst_ni)
  `export_dpi_get(int, gater, enable_i)
  `export_dpi_get(int, gater, kick_i)
  `export_dpi_get(int, gater, hyst_cnt_q)


  reg [31:0] i_clk_cnts, o_clk_cnts;
  initial begin
    i_clk_cnts = 0;
    o_clk_cnts = 0;
  end

  always @(posedge clk_i) begin
    i_clk_cnts <= i_clk_cnts + 1;
  end

  always @(posedge gated_clk_o) begin
    o_clk_cnts <= o_clk_cnts + 1;
  end

  `export_dpi_get(int, gater, i_clk_cnts)
  `export_dpi_get(int, gater, o_clk_cnts)
`endif
`endif

endmodule
