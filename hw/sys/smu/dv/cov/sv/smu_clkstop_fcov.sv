// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// SMU clock-stop coordination functional coverage, from the SMU-CLKSTOP-REQ
// and SMU-CLKSTOP-OUT scenarios of the feature list: an external clock-stop
// request arriving at the DTP cross-trigger network, a JTAG DEBUG_CONTROL
// request raising dtp_stop_clks_o, and the output releasing again.
//
// One passive, signal-driven module shared by tb_top and tb_wrapper_top. The
// request vector is read where the cross-trigger network receives it (smu.sv
// maps the eight SMU pins onto request bits [8:1] and the CLA status onto
// bit 0), the DEBUG_CONTROL bit where the network receives it, and the halt
// on the SMU output pin.
//
// Every point is an edge on the aggregation's own input or output, so none is
// true in the quiescent state; the release point is additionally qualified by
// a sticky record of the assertion it releases.
//
// CONVENTION (see dtp_fcov.sv): every cover-property body and disable-iff
// argument is a single continuous-assign wire; no declaration initializers
// on always_ff-driven variables; declare wires before use. Every register
// carries a reset branch.

`include "ocah_fcov_macros.svh"

module smu_clkstop_fcov (
  input wire clk_smu_i,
  input wire rst_primary_smc_clk_ni,

  // External clock-stop request slice as the cross-trigger network sees it.
  input wire [7:0] dtp_clk_stop_req_ext_i,
  // DEBUG_CONTROL clock-stop request as the cross-trigger network sees it.
  input wire jtag_clock_stop_i,
  // Aggregated halt at the SMU boundary.
  input wire dtp_stop_clks_i
);

  wire in_reset = (rst_primary_smc_clk_ni !== 1'b1);

  logic [7:0] req_ext_q;
  logic stop_clks_q, stop_clks_seen_q;
  always_ff @(posedge clk_smu_i) begin
    if (in_reset) begin
      req_ext_q <= '0;
      stop_clks_q <= 1'b0;
      stop_clks_seen_q <= 1'b0;
    end else begin
      req_ext_q <= dtp_clk_stop_req_ext_i;
      stop_clks_q <= dtp_stop_clks_i;
      if (dtp_stop_clks_i === 1'b1) stop_clks_seen_q <= 1'b1;
    end
  end

  wire clk_stop_req_delivered_e = (dtp_clk_stop_req_ext_i !== 8'h00) && (req_ext_q === 8'h00);
  wire stop_clks_rose_e = (dtp_stop_clks_i === 1'b1) && (stop_clks_q === 1'b0);
  wire stop_clks_from_debug_control_e = stop_clks_rose_e && (jtag_clock_stop_i === 1'b1);
  wire stop_clks_released_e =
      (dtp_stop_clks_i === 1'b0) && (stop_clks_q === 1'b1) && stop_clks_seen_q;
  `OCAH_FCOV_COVER(c_clk_stop_req_delivered, clk_stop_req_delivered_e, clk_smu_i, in_reset)
  `OCAH_FCOV_COVER(c_stop_clks_from_debug_control, stop_clks_from_debug_control_e, clk_smu_i,
                   in_reset)
  `OCAH_FCOV_COVER(c_stop_clks_released, stop_clks_released_e, clk_smu_i, in_reset)

`ifndef VERILATOR
  // ------------------------------------------------------------------
  // Commercial-simulator covergroup: which source was requesting while the
  // aggregate halt was in whichever state, which a flat point list cannot
  // cross.
  // ------------------------------------------------------------------
  covergroup cg_clk_stop_sources with function sample (
      logic [7:0] req_ext, logic jtag_stop, logic stop
  );
    option.per_instance = 1;
    cp_req_ext: coverpoint req_ext {bins none = {8'h00}; bins requesting = default;}
    cp_jtag_stop: coverpoint jtag_stop;
    cp_stop: coverpoint stop;
    x_source: cross cp_jtag_stop, cp_req_ext, cp_stop;
  endgroup

  cg_clk_stop_sources u_cg_clk_stop_sources = new();

  always_ff @(posedge clk_smu_i) begin
    if (!in_reset) begin
      u_cg_clk_stop_sources.sample(dtp_clk_stop_req_ext_i, jtag_clock_stop_i, dtp_stop_clks_i);
    end
  end
`endif

endmodule : smu_clkstop_fcov
