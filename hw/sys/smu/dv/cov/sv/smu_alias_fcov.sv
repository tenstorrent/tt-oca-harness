// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// SMU SEP-to-SMC alias-window functional coverage, from the INT-ALIAS-XBAR
// scenario of the feature list: the dedicated SEP-to-SMC port that carries
// SEP traffic in SMC's global window, and the crossbar SEP initiator port
// that traffic does not use.
//
// One passive, signal-driven module. The dedicated port and the crossbar SEP
// initiator port exist only in the SEP=1 elaboration, so the bench drives
// these inputs from its own flattened copies.
//
// SEP PRESENCE: the entire point set sits in the `g_sep` generate block, so a
// SEP=0 build carries no unhittable point and one coverage policy can grade
// both elaborations.
//
// The window is SMC's live GLOBAL_BASE / REGION_SIZE, so reprogramming
// either CSR moves it. The bypass points need a transfer plus a measured
// window of crossbar silence.
//
// CONVENTION (see dtp_fcov.sv): every cover-property body and disable-iff
// argument is a single continuous-assign wire; no declaration initializers
// on always_ff-driven variables; declare wires before use. Every register
// carries a reset branch.

`include "ocah_fcov_macros.svh"

module smu_alias_fcov #(
  // 0 on an elaboration without SEP. Every observable of this module -- the
  // dedicated SEP-to-SMC port and the crossbar SEP initiator port --
  // exists only in smu.sv's gen_sep branch, so the whole point set is
  // dropped rather than carried unhittable.
  parameter bit SepPresent = 1'b1
) (
  input wire clk_smu_i,
  input wire rst_primary_smc_clk_ni,

  // SMC's global window, as SEP decodes it onto the dedicated port.
  input wire [55:0] smc_global_base_i,
  input wire [31:0] smc_region_size_i,

  // Dedicated SEP-to-SMC port.
  input wire alias_awvalid_i,
  input wire alias_awready_i,
  input wire [55:0] alias_awaddr_i,
  input wire alias_arvalid_i,
  input wire alias_arready_i,
  input wire [55:0] alias_araddr_i,
  input wire alias_bvalid_i,
  input wire alias_bready_i,
  input wire alias_rvalid_i,
  input wire alias_rready_i,
  input wire alias_rlast_i,

  // Crossbar SEP initiator port, the route the dedicated-port traffic avoids.
  input wire xbar_sep_out_awvalid_i,
  input wire xbar_sep_out_awready_i,
  input wire [55:0] xbar_sep_out_awaddr_i,
  input wire xbar_sep_out_arvalid_i,
  input wire xbar_sep_out_arready_i,
  input wire [55:0] xbar_sep_out_araddr_i
);

  if (SepPresent) begin : g_sep
    localparam logic [7:0] IdleWindow = 8'd63;

    // One bit wider than the address so a window ending at the top of the
    // space does not wrap to zero.
    wire [56:0] alias_end = {1'b0, smc_global_base_i} + {25'd0, smc_region_size_i};

    wire in_reset = (rst_primary_smc_clk_ni !== 1'b1);

    // ------------------------------------------------------------------
    // Accepted transfers on the dedicated port, and the window membership
    // of the address each carried.
    // ------------------------------------------------------------------
    wire alias_aw_hs = (alias_awvalid_i === 1'b1) && (alias_awready_i === 1'b1);
    wire alias_ar_hs = (alias_arvalid_i === 1'b1) && (alias_arready_i === 1'b1);
    wire alias_aw_in_window = (alias_awaddr_i >= smc_global_base_i)
        && ({1'b0, alias_awaddr_i} < alias_end);
    wire alias_ar_in_window = (alias_araddr_i >= smc_global_base_i)
        && ({1'b0, alias_araddr_i} < alias_end);
    wire alias_hit_e = (alias_aw_hs && alias_aw_in_window) || (alias_ar_hs && alias_ar_in_window);

    // ------------------------------------------------------------------
    // Crossbar SEP initiator activity, and the idle run that follows an
    // alias hit.
    // ------------------------------------------------------------------
    wire xbar_aw_hs = (xbar_sep_out_awvalid_i === 1'b1) && (xbar_sep_out_awready_i === 1'b1);
    wire xbar_ar_hs = (xbar_sep_out_arvalid_i === 1'b1) && (xbar_sep_out_arready_i === 1'b1);
    wire xbar_busy = (xbar_sep_out_awvalid_i === 1'b1) || (xbar_sep_out_arvalid_i === 1'b1);

    logic [7:0] idle_cnt_q;
    logic alias_pending_q;
    always_ff @(posedge clk_smu_i) begin
      if (in_reset) begin
        idle_cnt_q <= '0;
        alias_pending_q <= 1'b0;
      end else begin
        if (alias_hit_e) begin
          idle_cnt_q <= '0;
          alias_pending_q <= 1'b1;
        end else if (xbar_busy) begin
          idle_cnt_q <= '0;
          alias_pending_q <= 1'b0;
        end else if (alias_pending_q && (idle_cnt_q != IdleWindow)) begin
          idle_cnt_q <= idle_cnt_q + 8'd1;
        end
      end
    end

    wire alias_response_hs = ((alias_bvalid_i === 1'b1) && (alias_bready_i === 1'b1))
        || ((alias_rvalid_i === 1'b1) && (alias_rready_i === 1'b1) && (alias_rlast_i === 1'b1));

    wire alias_path_bypasses_xbar_e = alias_hit_e && !xbar_busy;
    wire no_xbar_target_activity_during_alias_e =
        alias_pending_q && !xbar_busy && (idle_cnt_q == IdleWindow - 8'd1);
    wire alias_hit_observed_at_smc_and_absent_at_xbar_e =
        alias_response_hs && alias_pending_q && !xbar_busy;
    wire xbar_aw_in_window = (xbar_sep_out_awaddr_i >= smc_global_base_i)
        && ({1'b0, xbar_sep_out_awaddr_i} < alias_end);
    wire xbar_ar_in_window = (xbar_sep_out_araddr_i >= smc_global_base_i)
        && ({1'b0, xbar_sep_out_araddr_i} < alias_end);
    wire sep_access_outside_window_observed_at_xbar_e =
        (xbar_aw_hs && !xbar_aw_in_window) || (xbar_ar_hs && !xbar_ar_in_window);
    `OCAH_FCOV_COVER(c_alias_path_bypasses_xbar, alias_path_bypasses_xbar_e, clk_smu_i, in_reset)
    `OCAH_FCOV_COVER(c_no_xbar_target_activity_during_alias, no_xbar_target_activity_during_alias_e,
                     clk_smu_i, in_reset)
    `OCAH_FCOV_COVER(c_alias_hit_observed_at_smc_and_absent_at_xbar,
                     alias_hit_observed_at_smc_and_absent_at_xbar_e, clk_smu_i, in_reset)
    `OCAH_FCOV_COVER(c_sep_access_outside_window_observed_at_xbar,
                     sep_access_outside_window_observed_at_xbar_e, clk_smu_i, in_reset)

`ifndef VERILATOR
    // ------------------------------------------------------------------
    // Commercial-simulator covergroup: which of the two SEP egress paths
    // carried the transfer, against the window membership of its address.
    // ------------------------------------------------------------------
    covergroup cg_alias_path with function sample (
        logic on_remap_port, logic in_window, logic is_read
    );
      option.per_instance = 1;
      cp_port: coverpoint on_remap_port;
      cp_window: coverpoint in_window;
      cp_is_read: coverpoint is_read;
      x_path: cross cp_port, cp_window, cp_is_read;
    endgroup

    cg_alias_path u_cg_alias_path = new();

    always_ff @(posedge clk_smu_i) begin
      if (!in_reset) begin
        if (alias_aw_hs) u_cg_alias_path.sample(1'b1, alias_aw_in_window, 1'b0);
        if (alias_ar_hs) u_cg_alias_path.sample(1'b1, alias_ar_in_window, 1'b1);
        if (xbar_aw_hs) u_cg_alias_path.sample(1'b0, xbar_aw_in_window, 1'b0);
        if (xbar_ar_hs) u_cg_alias_path.sample(1'b0, xbar_ar_in_window, 1'b1);
      end
    end
`endif
  end

endmodule : smu_alias_fcov
