// Copyright lowRISC contributors (OpenTitan project).
// Licensed under the Apache License, Version 2.0, see LICENSE for details.
// SPDX-License-Identifier: Apache-2.0

// Generate TL-UL D-channel response integrity bits.
//
// Fill rsp_intg and data_intg in tl_o.d_user:
//
// - When EnableRspIntgGen is true, generate rsp_intg from the opcode, d_size, and d_error
//   fields via tlul_pkg::extract_d2h_rsp_intg.
// - When EnableDataIntgGen is true, generate data_intg from d_data.
//
// When EnableRspIntgGen is false, rsp_intg is zero if RspIntgInIsZero is set and taken
// from tl_i otherwise. When EnableDataIntgGen is false, data_intg is zero if UserInIsZero
// is set and taken from tl_i otherwise.

module tlul_rsp_intg_gen
  import tlul_pkg::*;
#(
  parameter bit EnableRspIntgGen = 1'b1,           // Generate rsp_intg from opcode/size/error.
  parameter bit EnableDataIntgGen = 1'b1,          // Generate data_intg from d_data.
  parameter bit UserInIsZero = 1'b0,               // Zero data_intg when not generated;
                                                   // simulation asserts d_user is zero.
  parameter bit RspIntgInIsZero = UserInIsZero     // Zero rsp_intg when not generated;
                                                   // simulation asserts it is zero.
) (
  input  tl_d2h_t tl_i,  // D-channel response before integrity insertion.
  output tl_d2h_t tl_o   // D-channel response with integrity fields filled.
);
  `include "prim_assert.sv"
  `include "ocah_assert.svh"

  logic [D2HRspIntgWidth-1:0] rsp_intg;
  if (EnableRspIntgGen) begin : gen_rsp_intg
    tl_d2h_rsp_intg_t rsp;
    logic [D2HRspMaxWidth-1:0] unused_payload;

    assign rsp = extract_d2h_rsp_intg(tl_i);

    prim_secded_inv_64_57_enc u_rsp_gen (
      .data_i(D2HRspMaxWidth'(rsp)),
      .data_o({rsp_intg, unused_payload})
    );
  end else if (RspIntgInIsZero) begin : gen_zero_rsp_intg
    assign rsp_intg = 0;
  end else begin : gen_passthrough_rsp_intg
    assign rsp_intg = tl_i.d_user.rsp_intg;
  end

  logic [DataIntgWidth-1:0] data_intg;
  if (EnableDataIntgGen) begin : gen_data_intg
    logic [DataMaxWidth-1:0] unused_data;
    tlul_data_integ_enc u_tlul_data_integ_enc (
      .data_i(DataMaxWidth'(tl_i.d_data)),
      .data_intg_o({data_intg, unused_data})
    );
  end else if (UserInIsZero) begin : gen_zero_data_intg
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


  `OCAH_OT_ASSERT_INIT(PayLoadWidthCheck, $bits(tl_d2h_rsp_intg_t) <= D2HRspMaxWidth)
  `OCAH_OT_ASSERT_INIT(DataWidthCheck_A, $bits(tl_i.d_data) <= DataMaxWidth)

  // the code below is not meant to be synthesized,
  // but it is intended to be used in simulation, emulation and FPV
`ifdef OCAH_DEBUG_LIVE
  always @(tl_i) begin
    `OCAH_OT_ASSERT_I(RspZero_A, tl_i.d_valid & RspIntgInIsZero -> ~|tl_i.d_user.rsp_intg)
    `OCAH_OT_ASSERT_I(UserZero_A, tl_i.d_valid & UserInIsZero -> ~|tl_i.d_user)
  end
`endif

endmodule  // tlul_rsp_intg_gen
