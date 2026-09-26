// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// Pulse dst_pulse_o once for each src_pulse_i across a clock-domain crossing.
//
// Toggle a level on src_clk_i and edge-detect it on dst_clk_i after a 3-flop sync.
// src_rst_ni clears the source toggle state and, synchronized into dst_clk_i, the
// destination synchronizer.
// Each high cycle of src_pulse_i flips the toggle, so the input must be a single-cycle pulse.
// Two source pulses closer together than the destination can resolve cancel each other and
// produce no dst_pulse_o.

module prim_sync3_pulse (
  input  logic src_clk_i,  // Source clock.
  input  logic src_pulse_i,  // Source-domain pulse to forward; high for one src_clk_i cycle.
  input  logic src_rst_ni,  // Active-low reset, sampled synchronously on src_clk_i and
                            // synchronized into dst_clk_i for the destination side.
  input  logic dst_clk_i,  // Destination clock.
  output logic dst_pulse_o  // One-cycle pulse on dst_clk_i.
);

  wire toggle;

  prim_sync3_pulse_src u_src (
    .src_clk_i(src_clk_i),
    .src_pulse_i(src_pulse_i),
    .src_rst_ni(src_rst_ni),
    .toggle_o(toggle)
  );

  prim_sync3_pulse_dest u_dest (
    .dst_clk_i(dst_clk_i),
    .src_rst_ni(src_rst_ni),
    .toggle_i(toggle),
    .dst_pulse_o(dst_pulse_o)
  );

endmodule

module prim_sync3_pulse_src (
  input  logic src_clk_i,  // Source clock.
  input  logic src_pulse_i,  // Each cycle it is high flips toggle_o.
  input  logic src_rst_ni,  // Active-low reset, sampled synchronously; clears toggle_o.
  output logic toggle_o  // Registered level on src_clk_i that changes once per pulse cycle.
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
  input  logic dst_clk_i,  // Destination clock.
  input  logic src_rst_ni,  // Source-domain active-low reset; synchronized into dst_clk_i
                            // through three stages, it clears the synchronizer and holds
                            // dst_pulse_o low.
  input  logic toggle_i,  // Source toggle level, asynchronous to dst_clk_i.
  output logic dst_pulse_o  // One-cycle pulse on dst_clk_i for each synchronized change of
                            // toggle_i.
);

  wire toggle_synced;
  wire src_reset_n_reg_dst_clk;

  prim_flop_3sync_r u_sync3 (
    .clk_i (dst_clk_i),
    .rst_ni(src_reset_n_reg_dst_clk),
    .d_i   (toggle_i),
    .q_o   (toggle_synced)
  );

  prim_sync_reset #(
    .WIDTH(3)
  ) u_src_reset_n_sync (
    .clk_i      (dst_clk_i              ),
    .rst_ni     (src_rst_ni             ),
    .test_mode_i(1'b0                   ),
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
