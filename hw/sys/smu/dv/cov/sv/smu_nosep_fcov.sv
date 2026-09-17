// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// SMU SEP=0 composition functional coverage, from the SMU-NOSEP scenarios of
// the feature list: the direct ID-converter path that replaces the crossbar
// when SEP is absent, in each direction and for each channel.
//
// One passive, signal-driven module on the block bench, tb_top, the only
// bench that elaborates SEP=0. sep_present_i states which elaboration the
// instance is in, so a SEP=0 point cannot be credited by a SEP=1 run.
//
// Every point fires on a response handshake, so it needs traffic. The SEP OTP
// error slave of the same build has no master on either elaboration (the
// SEP=0 PTAP ties the OTP request off and turns the instruction into BYPASS),
// so it carries no point here.
//
// CONVENTION (see dtp_fcov.sv): every cover-property body and disable-iff
// argument is a single continuous-assign wire; no declaration initializers
// on always_ff-driven variables; declare wires before use. Every register
// carries a reset branch.

`include "ocah_fcov_macros.svh"

module smu_nosep_fcov (
  input wire clk_smu_i,
  input wire rst_cold_ni,
  input wire sep_present_i,

  // Inbound external SMN port at the SMU boundary (ext -> SMC when SEP=0).
  input wire ext_in_bvalid_i,
  input wire ext_in_bready_i,
  input wire [1:0] ext_in_bresp_i,
  input wire ext_in_rvalid_i,
  input wire ext_in_rready_i,
  input wire ext_in_rlast_i,
  input wire [1:0] ext_in_rresp_i,

  // Outbound external SMN port at the SMU boundary (SMC -> ext when SEP=0).
  input wire axi_out_bvalid_i,
  input wire axi_out_bready_i,
  input wire [1:0] axi_out_bresp_i,
  input wire axi_out_rvalid_i,
  input wire axi_out_rready_i,
  input wire axi_out_rlast_i,
  input wire [1:0] axi_out_rresp_i
);

  localparam logic [1:0] RespOkay = 2'b00;

  wire in_reset = (rst_cold_ni !== 1'b1);
  wire sep_absent = (sep_present_i === 1'b0);

  // ------------------------------------------------------------------
  // Direct ID-converter path: the four completed transfers the SEP=0
  // composition has to carry between SMC and the external SMN port.
  // ------------------------------------------------------------------
  wire ext_in_b_ok = (ext_in_bvalid_i === 1'b1) && (ext_in_bready_i === 1'b1)
      && (ext_in_bresp_i == RespOkay);
  wire ext_in_r_ok = (ext_in_rvalid_i === 1'b1) && (ext_in_rready_i === 1'b1)
      && (ext_in_rlast_i === 1'b1) && (ext_in_rresp_i == RespOkay);
  wire axi_out_b_ok = (axi_out_bvalid_i === 1'b1) && (axi_out_bready_i === 1'b1)
      && (axi_out_bresp_i == RespOkay);
  wire axi_out_r_ok = (axi_out_rvalid_i === 1'b1) && (axi_out_rready_i === 1'b1)
      && (axi_out_rlast_i === 1'b1) && (axi_out_rresp_i == RespOkay);

  wire nosep_ext_to_smc_write_e = sep_absent && ext_in_b_ok;
  wire nosep_ext_to_smc_read_e = sep_absent && ext_in_r_ok;
  wire nosep_smc_to_ext_write_e = sep_absent && axi_out_b_ok;
  wire nosep_smc_to_ext_read_e = sep_absent && axi_out_r_ok;
  `OCAH_FCOV_COVER(c_nosep_ext_to_smc_write, nosep_ext_to_smc_write_e, clk_smu_i, in_reset)
  `OCAH_FCOV_COVER(c_nosep_ext_to_smc_read, nosep_ext_to_smc_read_e, clk_smu_i, in_reset)
  `OCAH_FCOV_COVER(c_nosep_smc_to_ext_write, nosep_smc_to_ext_write_e, clk_smu_i, in_reset)
  `OCAH_FCOV_COVER(c_nosep_smc_to_ext_read, nosep_smc_to_ext_read_e, clk_smu_i, in_reset)

`ifndef VERILATOR
  // ------------------------------------------------------------------
  // Commercial-simulator covergroup: the direction and response code of
  // each completed boundary transfer, against the elaboration it ran in.
  // ------------------------------------------------------------------
  covergroup cg_nosep_boundary with function sample (
      logic sep, logic inbound, logic is_read, logic [1:0] resp
  );
    option.per_instance = 1;
    cp_sep: coverpoint sep;
    cp_direction: coverpoint inbound;
    cp_is_read: coverpoint is_read;
    cp_resp: coverpoint resp {
      bins okay = {2'b00}; bins exokay = {2'b01}; bins slverr = {2'b10}; bins decerr = {2'b11};
    }
    x_transfer: cross cp_sep, cp_direction, cp_is_read;
  endgroup

  cg_nosep_boundary u_cg_nosep_boundary = new();

  always_ff @(posedge clk_smu_i) begin
    if (!in_reset) begin
      if (ext_in_bvalid_i && ext_in_bready_i) begin
        u_cg_nosep_boundary.sample(sep_present_i, 1'b1, 1'b0, ext_in_bresp_i);
      end
      if (ext_in_rvalid_i && ext_in_rready_i && ext_in_rlast_i) begin
        u_cg_nosep_boundary.sample(sep_present_i, 1'b1, 1'b1, ext_in_rresp_i);
      end
      if (axi_out_bvalid_i && axi_out_bready_i) begin
        u_cg_nosep_boundary.sample(sep_present_i, 1'b0, 1'b0, axi_out_bresp_i);
      end
      if (axi_out_rvalid_i && axi_out_rready_i && axi_out_rlast_i) begin
        u_cg_nosep_boundary.sample(sep_present_i, 1'b0, 1'b1, axi_out_rresp_i);
      end
    end
  end
`endif

endmodule : smu_nosep_fcov
