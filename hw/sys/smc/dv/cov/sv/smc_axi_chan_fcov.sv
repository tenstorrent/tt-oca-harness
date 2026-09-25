// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// One AXI manager's channel-shape functional coverage: handshakes,
// backpressure, burst shape and response codes. smc_fabric_fcov
// instantiates it once per inbound manager, so each instance contributes
// its own copy of the points under its own instance name -- the policy
// selector is smc_uvm_top.u_smc_fabric_fcov.u_<manager>.c_<point>.
//
// CONVENTION (see dtp_fcov.sv): every cover-property body and disable-iff
// argument is a single continuous-assign wire; no declaration initializers
// on always_ff-driven variables; declare wires before use.
//
// A `define parameter list must stay on one line. Verilator does not register
// the first parameter after a line continuation, and the unsubstituted
// parameter name survives into elaboration as literal text.

`include "ocah_fcov_macros.svh"

module smc_axi_chan_fcov (
  input wire clk_i,
  input wire rst_ni,

  input wire awvalid_i,
  input wire awready_i,
  input wire [7:0] awlen_i,

  input wire wvalid_i,
  input wire wready_i,
  input wire wlast_i,

  input wire bvalid_i,
  input wire bready_i,
  input wire [1:0] bresp_i,

  input wire arvalid_i,
  input wire arready_i,
  input wire [7:0] arlen_i,

  input wire rvalid_i,
  input wire rready_i,
  input wire rlast_i,
  input wire [1:0] rresp_i
);

  wire in_reset = (rst_ni !== 1'b1);

  // Handshake and backpressure. The stall points are what separate a bus
  // that was merely driven from one whose flow control was exercised.
  wire aw_accept_e = (awvalid_i === 1'b1) && (awready_i === 1'b1);
  wire aw_stall_e = (awvalid_i === 1'b1) && (awready_i === 1'b0);
  wire w_accept_e = (wvalid_i === 1'b1) && (wready_i === 1'b1);
  wire w_stall_e = (wvalid_i === 1'b1) && (wready_i === 1'b0);
  wire w_last_e = w_accept_e && (wlast_i === 1'b1);
  `OCAH_FCOV_COVER(c_aw_accept, aw_accept_e, clk_i, in_reset)
  `OCAH_FCOV_COVER(c_aw_stall, aw_stall_e, clk_i, in_reset)
  `OCAH_FCOV_COVER(c_w_accept, w_accept_e, clk_i, in_reset)
  `OCAH_FCOV_COVER(c_w_stall, w_stall_e, clk_i, in_reset)
  `OCAH_FCOV_COVER(c_w_last, w_last_e, clk_i, in_reset)

  wire b_accept_e = (bvalid_i === 1'b1) && (bready_i === 1'b1);
  wire b_stall_e = (bvalid_i === 1'b1) && (bready_i === 1'b0);
  wire ar_accept_e = (arvalid_i === 1'b1) && (arready_i === 1'b1);
  wire ar_stall_e = (arvalid_i === 1'b1) && (arready_i === 1'b0);
  wire r_accept_e = (rvalid_i === 1'b1) && (rready_i === 1'b1);
  wire r_stall_e = (rvalid_i === 1'b1) && (rready_i === 1'b0);
  wire r_last_e = r_accept_e && (rlast_i === 1'b1);
  `OCAH_FCOV_COVER(c_b_accept, b_accept_e, clk_i, in_reset)
  `OCAH_FCOV_COVER(c_b_stall, b_stall_e, clk_i, in_reset)
  `OCAH_FCOV_COVER(c_ar_accept, ar_accept_e, clk_i, in_reset)
  `OCAH_FCOV_COVER(c_ar_stall, ar_stall_e, clk_i, in_reset)
  `OCAH_FCOV_COVER(c_r_accept, r_accept_e, clk_i, in_reset)
  `OCAH_FCOV_COVER(c_r_stall, r_stall_e, clk_i, in_reset)
  `OCAH_FCOV_COVER(c_r_last, r_last_e, clk_i, in_reset)

  // Burst shape.
  wire aw_single_e = aw_accept_e && (awlen_i == 8'd0);
  wire aw_multi_e = aw_accept_e && (awlen_i != 8'd0);
  wire ar_single_e = ar_accept_e && (arlen_i == 8'd0);
  wire ar_multi_e = ar_accept_e && (arlen_i != 8'd0);
  `OCAH_FCOV_COVER(c_aw_single_beat, aw_single_e, clk_i, in_reset)
  `OCAH_FCOV_COVER(c_aw_multi_beat, aw_multi_e, clk_i, in_reset)
  `OCAH_FCOV_COVER(c_ar_single_beat, ar_single_e, clk_i, in_reset)
  `OCAH_FCOV_COVER(c_ar_multi_beat, ar_multi_e, clk_i, in_reset)

  // Response codes. All four encodings get a point so the ones the suite
  // never produces are named holes rather than absent from the model.
  wire bresp_okay_e = b_accept_e && (bresp_i == 2'b00);
  wire bresp_exokay_e = b_accept_e && (bresp_i == 2'b01);
  wire bresp_slverr_e = b_accept_e && (bresp_i == 2'b10);
  wire bresp_decerr_e = b_accept_e && (bresp_i == 2'b11);
  `OCAH_FCOV_COVER(c_bresp_okay, bresp_okay_e, clk_i, in_reset)
  `OCAH_FCOV_COVER(c_bresp_exokay, bresp_exokay_e, clk_i, in_reset)
  `OCAH_FCOV_COVER(c_bresp_slverr, bresp_slverr_e, clk_i, in_reset)
  `OCAH_FCOV_COVER(c_bresp_decerr, bresp_decerr_e, clk_i, in_reset)

  wire rresp_okay_e = r_accept_e && (rresp_i == 2'b00);
  wire rresp_exokay_e = r_accept_e && (rresp_i == 2'b01);
  wire rresp_slverr_e = r_accept_e && (rresp_i == 2'b10);
  wire rresp_decerr_e = r_accept_e && (rresp_i == 2'b11);
  `OCAH_FCOV_COVER(c_rresp_okay, rresp_okay_e, clk_i, in_reset)
  `OCAH_FCOV_COVER(c_rresp_exokay, rresp_exokay_e, clk_i, in_reset)
  `OCAH_FCOV_COVER(c_rresp_slverr, rresp_slverr_e, clk_i, in_reset)
  `OCAH_FCOV_COVER(c_rresp_decerr, rresp_decerr_e, clk_i, in_reset)

`ifndef VERILATOR
  // ------------------------------------------------------------------
  // Commercial-simulator covergroups: burst-length distribution, sampled on
  // the address channel, and response codes, sampled on the response
  // channel.
  //
  // No length-against-response cross: AXI lets the
  // address channel advance while earlier transactions are still
  // outstanding, so awlen at B accept is not the length of the burst being
  // responded to; crossing the two would correlate unrelated values.
  // Building that cross honestly needs the ID-indexed outstanding table this
  // passive module does not keep.
  // ------------------------------------------------------------------
  covergroup cg_axi_burst_len with function sample (logic [7:0] len);
    option.per_instance = 1;
    cp_len: coverpoint len {
      bins single = {0};
      bins short_burst = {[1 : 3]};
      bins mid_burst = {[4 : 15]};
      bins long_burst = default;
    }
  endgroup

  covergroup cg_axi_resp with function sample (logic [1:0] resp);
    option.per_instance = 1;
    cp_resp: coverpoint resp {
      bins okay = {2'b00};
      bins slverr = {2'b10};
      bins decerr = {2'b11};
      // No subordinate behind these ports answers an exclusive access: the
      // memory adapters tie exokay off and the crossbars carry no atomics.
      ignore_bins exokay = {2'b01};
    }
  endgroup

  cg_axi_burst_len u_cg_awlen = new();
  cg_axi_burst_len u_cg_arlen = new();
  cg_axi_resp u_cg_bresp = new();
  cg_axi_resp u_cg_rresp = new();

  always_ff @(posedge clk_i) begin
    if (!in_reset) begin
      if (aw_accept_e) u_cg_awlen.sample(awlen_i);
      if (ar_accept_e) u_cg_arlen.sample(arlen_i);
      if (b_accept_e) u_cg_bresp.sample(bresp_i);
      if (r_accept_e) u_cg_rresp.sample(rresp_i);
    end
  end
`endif

endmodule : smc_axi_chan_fcov
