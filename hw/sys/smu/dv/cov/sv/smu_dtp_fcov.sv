// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// SMU debug-port boundary functional coverage, from the SMU-ICRESET and
// SMU-XTRIG-CTP scenarios of the feature list: the external IC_RESET
// override slice and the cross-trigger CTP pad groups.
//
// One passive, signal-driven module shared by tb_top and tb_wrapper_top.
// Every port is a signal both benches expose at their top level.
//
// The CTP width points sample at the primary reset release edge, the first
// moment the pad groups are presented; the inert point needs a full quiet
// window after release, so a channel that twitched once does not count.
//
// CONVENTION (see dtp_fcov.sv): every cover-property body and disable-iff
// argument is a single continuous-assign wire; no declaration initializers
// on always_ff-driven variables; declare wires before use. Every register
// carries a reset branch.

`include "ocah_fcov_macros.svh"

module smu_dtp_fcov (
  input wire clk_smu_i,
  input wire rst_cold_ni,
  input wire rst_primary_smc_clk_ni,

  // External IC_RESET override slice.
  input wire jtag_ic_reset_ext_ovrd_i,
  input wire jtag_ic_reset_ext_ctrl_n_i,

  // CTP pad-group data outputs, with their inputs tied to zero by the bench.
  input wire [dtp_pkg::DEFAULT_NUM_CTP-1:0] ctp_req_out_dout_i,
  input wire [dtp_pkg::DEFAULT_NUM_CTP-1:0] ctp_req_in_dout_i,
  input wire [dtp_pkg::DEFAULT_NUM_CTP-1:0] ctp_ack_in_dout_i,
  input wire [dtp_pkg::DEFAULT_NUM_CTP-1:0] ctp_ack_out_dout_i
);

  localparam logic [7:0] InertWindow = 8'd255;

  wire in_reset = (rst_cold_ni !== 1'b1);

  // ------------------------------------------------------------------
  // IC_RESET override slice: the override enable rising, and the active-low
  // value asserted while the override is in force.
  // ------------------------------------------------------------------
  logic primary_q, ext_ovrd_q;
  always_ff @(posedge clk_smu_i) begin
    if (in_reset) begin
      primary_q <= 1'b0;
      ext_ovrd_q <= 1'b0;
    end else begin
      primary_q <= rst_primary_smc_clk_ni;
      ext_ovrd_q <= jtag_ic_reset_ext_ovrd_i;
    end
  end

  wire primary_rose_e = (rst_primary_smc_clk_ni === 1'b1) && (primary_q === 1'b0);
  wire ovrd_field_present_e = (jtag_ic_reset_ext_ovrd_i === 1'b1) && (ext_ovrd_q === 1'b0);
  wire val_field_active_low_e =
      (jtag_ic_reset_ext_ovrd_i === 1'b1) && (jtag_ic_reset_ext_ctrl_n_i === 1'b0);
  `OCAH_FCOV_COVER(c_ovrd_field_present, ovrd_field_present_e, clk_smu_i, in_reset)
  `OCAH_FCOV_COVER(c_val_field_active_low, val_field_active_low_e, clk_smu_i, in_reset)

  // ------------------------------------------------------------------
  // CTP pad groups: 16 bits presented on each group at release, and the
  // whole set quiet for a window afterwards with the inputs tied to zero.
  // ------------------------------------------------------------------
  wire ctp_req_out_width_16_e =
      primary_rose_e && ($bits(ctp_req_out_dout_i) == 16) && !$isunknown(ctp_req_out_dout_i);
  wire ctp_req_in_width_16_e =
      primary_rose_e && ($bits(ctp_req_in_dout_i) == 16) && !$isunknown(ctp_req_in_dout_i);
  wire ctp_ack_in_width_16_e =
      primary_rose_e && ($bits(ctp_ack_in_dout_i) == 16) && !$isunknown(ctp_ack_in_dout_i);
  wire ctp_ack_out_width_16_e =
      primary_rose_e && ($bits(ctp_ack_out_dout_i) == 16) && !$isunknown(ctp_ack_out_dout_i);
  `OCAH_FCOV_COVER(c_ctp_req_out_width_16, ctp_req_out_width_16_e, clk_smu_i, in_reset)
  `OCAH_FCOV_COVER(c_ctp_req_in_width_16, ctp_req_in_width_16_e, clk_smu_i, in_reset)
  `OCAH_FCOV_COVER(c_ctp_ack_in_width_16, ctp_ack_in_width_16_e, clk_smu_i, in_reset)
  `OCAH_FCOV_COVER(c_ctp_ack_out_width_16, ctp_ack_out_width_16_e, clk_smu_i, in_reset)

  wire ctp_quiet = (ctp_req_out_dout_i === '0) && (ctp_req_in_dout_i === '0)
      && (ctp_ack_in_dout_i === '0) && (ctp_ack_out_dout_i === '0);

  logic [7:0] inert_cnt_q;
  always_ff @(posedge clk_smu_i) begin
    if (in_reset) begin
      inert_cnt_q <= '0;
    end else begin
      if (!ctp_quiet || (rst_primary_smc_clk_ni !== 1'b1)) inert_cnt_q <= '0;
      else if (inert_cnt_q != InertWindow) inert_cnt_q <= inert_cnt_q + 8'd1;
    end
  end

  wire ctp_unused_input_tied_zero_inert_e = ctp_quiet && (inert_cnt_q == InertWindow - 8'd1);
  `OCAH_FCOV_COVER(c_ctp_unused_input_tied_zero_inert, ctp_unused_input_tied_zero_inert_e,
                   clk_smu_i, in_reset)

`ifndef VERILATOR
  // ------------------------------------------------------------------
  // Commercial-simulator covergroup: the override slice as a pair.
  // ------------------------------------------------------------------
  covergroup cg_ic_reset_ext with function sample (logic ovrd, logic ctrl_n);
    option.per_instance = 1;
    cp_ovrd: coverpoint ovrd;
    cp_ctrl_n: coverpoint ctrl_n;
    x_slice: cross cp_ovrd, cp_ctrl_n;
  endgroup

  cg_ic_reset_ext u_cg_ic_reset_ext = new();

  always_ff @(posedge clk_smu_i) begin
    if (!in_reset) u_cg_ic_reset_ext.sample(jtag_ic_reset_ext_ovrd_i, jtag_ic_reset_ext_ctrl_n_i);
  end
`endif

endmodule : smu_dtp_fcov
