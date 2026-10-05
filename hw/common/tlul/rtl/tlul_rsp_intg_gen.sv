// Copyright lowRISC contributors (OpenTitan project).
// Licensed under the Apache License, Version 2.0, see LICENSE for details.
// SPDX-License-Identifier: Apache-2.0

// Generate TL-UL D-channel response integrity bits.
//
// Fill rsp_intg and data_intg in tl_o.d_user:
//
// - When ENABLE_RSP_INTG_GEN is true, generate rsp_intg from the opcode, d_size, and d_error
//   fields via tlul_pkg::extract_d2h_rsp_intg.
// - When ENABLE_DATA_INTG_GEN is true, generate data_intg from d_data.
//
// When ENABLE_RSP_INTG_GEN is false, rsp_intg is zero if RSP_INTG_IN_IS_ZERO is set and taken
// from tl_i otherwise. When ENABLE_DATA_INTG_GEN is false, data_intg is zero if USER_IN_IS_ZERO
// is set and taken from tl_i otherwise.

module tlul_rsp_intg_gen
  import tlul_pkg::*;
#(
  parameter bit ENABLE_RSP_INTG_GEN = 1'b1,               // Generate rsp_intg from
                                                          // opcode/size/error.
  parameter bit ENABLE_DATA_INTG_GEN = 1'b1,              // Generate data_intg from d_data.
  parameter bit USER_IN_IS_ZERO = 1'b0,                   // Zero data_intg when not generated;
                                                          // simulation asserts d_user is zero.
  parameter bit RSP_INTG_IN_IS_ZERO = USER_IN_IS_ZERO     // Zero rsp_intg when not generated;
                                                          // simulation asserts it is zero.
) (
  input  tl_d2h_t tl_i,  // D-channel response before integrity insertion.
  output tl_d2h_t tl_o   // D-channel response with integrity fields filled.
);
  `include "prim_assert.sv"
  `include "ocah_assert.svh"

  logic [D2H_RSP_INTG_WIDTH-1:0] rsp_intg;
  if (ENABLE_RSP_INTG_GEN) begin : gen_rsp_intg
    tl_d2h_rsp_intg_t rsp;
    logic [D2H_RSP_MAX_WIDTH-1:0] unused_payload;

    assign rsp = extract_d2h_rsp_intg(tl_i);

    prim_secded_inv_64_57_enc u_rsp_gen (
      .data_i(D2H_RSP_MAX_WIDTH'(rsp)),
      .data_o({rsp_intg, unused_payload})
    );
  end else if (RSP_INTG_IN_IS_ZERO) begin : gen_zero_rsp_intg
    assign rsp_intg = 0;
  end else begin : gen_passthrough_rsp_intg
    assign rsp_intg = tl_i.d_user.rsp_intg;
  end

  logic [DATA_INTG_WIDTH-1:0] data_intg;
  if (ENABLE_DATA_INTG_GEN) begin : gen_data_intg
    logic [DATA_MAX_WIDTH-1:0] unused_data;
    tlul_data_integ_enc u_tlul_data_integ_enc (
      .data_i(DATA_MAX_WIDTH'(tl_i.d_data)),
      .data_intg_o({data_intg, unused_data})
    );
  end else if (USER_IN_IS_ZERO) begin : gen_zero_data_intg
    assign data_intg = 0;
  end else begin : gen_passthrough_data_intg
    assign data_intg = tl_i.d_user.data_intg;
  end

  always_comb begin
    tl_o = tl_i;
    tl_o.d_user.rsp_intg = rsp_intg;
    tl_o.d_user.data_intg = data_intg;
  end

  logic unused_tl;
  assign unused_tl = ^tl_i;


  `OCAH_OT_ASSERT_INIT(PayLoadWidthCheck, $bits(tl_d2h_rsp_intg_t) <= D2H_RSP_MAX_WIDTH)
  `OCAH_OT_ASSERT_INIT(DataWidthCheck_A, $bits(tl_i.d_data) <= DATA_MAX_WIDTH)

  // the code below is not meant to be synthesized,
  // but it is intended to be used in simulation, emulation and FPV
`ifdef OCAH_DEBUG_LIVE
  always @(tl_i) begin
    `OCAH_OT_ASSERT_I(RspZero_A, tl_i.d_valid & RSP_INTG_IN_IS_ZERO -> ~|tl_i.d_user.rsp_intg)
    `OCAH_OT_ASSERT_I(UserZero_A, tl_i.d_valid & USER_IN_IS_ZERO -> ~|tl_i.d_user)
  end
`endif

endmodule  // tlul_rsp_intg_gen
