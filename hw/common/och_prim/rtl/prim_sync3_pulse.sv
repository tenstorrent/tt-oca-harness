// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

//--------------------------------------------------
// 3-stage Synchronizer Pulse
//
//--------------------------------------------------
module prim_sync3_pulse (
  input  logic src_clk_i,
  input  logic src_pulse_i,
  input  logic src_rst_ni,
  input  logic dst_clk_i,
  output logic dst_pulse_o
);

  wire toggle;

  prim_sync3_pulse_src i_src (
    .src_clk_i(src_clk_i),
    .src_pulse_i(src_pulse_i),
    .src_rst_ni(src_rst_ni),
    .toggle_o(toggle)
  );

  prim_sync3_pulse_dest i_dest (
    .dst_clk_i(dst_clk_i),
    .src_rst_ni(src_rst_ni),
    .toggle_i(toggle),
    .dst_pulse_o(dst_pulse_o)
  );

endmodule

module prim_sync3_pulse_src (
  input  logic src_clk_i,
  input  logic src_pulse_i,
  input  logic src_rst_ni,
  output logic toggle_o
);

  always_ff @(posedge src_clk_i) begin
    if (~src_rst_ni) begin
      toggle_o <= 1'b0;
    end else begin
      toggle_o <= src_pulse_i ? ~toggle_o : toggle_o;
    end
  end

endmodule

module prim_sync3_pulse_dest (
  input  logic dst_clk_i,
  input  logic src_rst_ni,
  input  logic toggle_i,
  output logic dst_pulse_o
);

  wire toggle_synced;
  wire src_reset_n_reg_dst_clk;

  prim_flop_3sync_r sync3 (
    .clk_i(dst_clk_i),
    .rst_ni (src_reset_n_reg_dst_clk),
    .d_i (toggle_i),
    .q_o (toggle_synced)
  );

  prim_sync_reset #(
    .WIDTH(3)
  ) src_reset_n_sync (
    .clk_i       (dst_clk_i              ),
    .rst_ni     (src_rst_ni          ),
    .test_mode_i (1'b0                   ),
    .sync_rst_no(src_reset_n_reg_dst_clk),
    .scan_rst_ni(1'b0                   )
  );

  reg toggle_synced_d;
  reg toggle_synced_dd;
  always @(posedge dst_clk_i) begin
    if (~src_reset_n_reg_dst_clk) begin
      toggle_synced_d <= 1'b0;
      toggle_synced_dd <= 1'b0;
    end else begin
      toggle_synced_d <= toggle_synced;
      toggle_synced_dd <= toggle_synced_d;
    end
  end

  assign dst_pulse_o = ~src_reset_n_reg_dst_clk ? '0 : toggle_synced_d ^ toggle_synced_dd;

endmodule
