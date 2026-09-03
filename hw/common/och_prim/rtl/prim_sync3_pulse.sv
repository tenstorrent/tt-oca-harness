// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

//--------------------------------------------------
// 3-stage Synchronizer Pulse
//
//--------------------------------------------------
module prim_sync3_pulse (
  input  logic i_src_clk,
  input  logic i_src_pulse,
  input  logic i_src_reset_n,
  input  logic i_dst_clk,
  output logic o_dst_pulse
);

  wire toggle;

  prim_sync3_pulse_src i_src (
    .i_src_clk(i_src_clk),
    .i_src_pulse(i_src_pulse),
    .i_src_reset_n(i_src_reset_n),
    .toggle(toggle)
  );

  prim_sync3_pulse_dest i_dest (
    .i_dst_clk(i_dst_clk),
    .i_src_reset_n(i_src_reset_n),
    .toggle(toggle),
    .o_dst_pulse(o_dst_pulse)
  );

endmodule

module prim_sync3_pulse_src (
  input  logic i_src_clk,
  input  logic i_src_pulse,
  input  logic i_src_reset_n,
  output logic toggle
);

  always_ff @(posedge i_src_clk) begin
    if (~i_src_reset_n) begin
      toggle <= 1'b0;
    end else begin
      toggle <= i_src_pulse ? ~toggle : toggle;
    end
  end

endmodule

module prim_sync3_pulse_dest (
  input  logic i_dst_clk,
  input  logic i_src_reset_n,
  input  logic toggle,
  output logic o_dst_pulse
);

  wire toggle_synced;
  wire src_reset_n_reg_dst_clk;

  prim_flop_3sync_r sync3 (
    .i_CK(i_dst_clk),
    .i_RN (src_reset_n_reg_dst_clk),
    .i_D (toggle),
    .o_Q (toggle_synced)
  );

  prim_sync_reset #(
    .WIDTH(3)
  ) src_reset_n_sync (
    .clk       (i_dst_clk              ),
    .rst_n     (i_src_reset_n          ),
    .test_mode (1'b0                   ),
    .sync_rst_n(src_reset_n_reg_dst_clk),
    .scan_rst_n(1'b0                   )
  );

  reg toggle_synced_d;
  reg toggle_synced_dd;
  always @(posedge i_dst_clk) begin
    if (~src_reset_n_reg_dst_clk) begin
      toggle_synced_d <= 1'b0;
      toggle_synced_dd <= 1'b0;
    end else begin
      toggle_synced_d <= toggle_synced;
      toggle_synced_dd <= toggle_synced_d;
    end
  end

  assign o_dst_pulse = ~src_reset_n_reg_dst_clk ? '0 : toggle_synced_d ^ toggle_synced_dd;

endmodule
