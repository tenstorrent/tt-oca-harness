// Copyright lowRISC contributors (OpenTitan project).
// Licensed under the Apache License, Version 2.0, see LICENSE for details.
// SPDX-License-Identifier: Apache-2.0

// Generate TL-UL A-channel command integrity.
//
// Copy tl_i to tl_o and fill in a_user.cmd_intg. When EnableDataIntgGen is set, also
// generate a_user.data_intg from a_data; otherwise pass it through from tl_i.

module tlul_cmd_intg_gen
  import tlul_pkg::*;
#(
  parameter bit EnableDataIntgGen = 1'b1  // Generate data_intg; clear passes it through.
) (
  input  tl_h2d_t tl_i,  // A-channel request before integrity insertion.
  output tl_h2d_t tl_o   // A-channel request with integrity fields filled.
);
  `include "prim_assert.sv"

tl_h2d_cmd_intg_t cmd;
  assign cmd = extract_h2d_cmd_intg(tl_i);
  logic [H2DCmdMaxWidth-1:0] unused_cmd_payload;

  logic [H2DCmdIntgWidth-1:0] cmd_intg;
  prim_secded_inv_64_57_enc u_cmd_gen (
    .data_i(H2DCmdMaxWidth'(cmd)),
    .data_o({cmd_intg, unused_cmd_payload})
  );

  logic [top_pkg::TL_DW-1:0] data_final;
  logic [DataIntgWidth-1:0] data_intg;

  if (EnableDataIntgGen) begin : gen_data_intg
    assign data_final = tl_i.a_data;

    logic [DataMaxWidth-1:0] unused_data;
    prim_secded_inv_39_32_enc u_data_gen (
      .data_i(DataMaxWidth'(data_final)),
      .data_o({data_intg, unused_data})
    );
  end else begin : gen_passthrough_data_intg
    assign data_final = tl_i.a_data;
    assign data_intg = tl_i.a_user.data_intg;
  end

  always_comb begin
    tl_o = tl_i;
    tl_o.a_data = data_final;
    tl_o.a_user.cmd_intg = cmd_intg;
    tl_o.a_user.data_intg = data_intg;
  end


  logic unused_tl;
  assign unused_tl = ^tl_i;

  `OCAH_OT_ASSERT_INIT(PayMaxWidthCheck_A, $bits(tl_h2d_cmd_intg_t) <= H2DCmdMaxWidth)

endmodule : tlul_cmd_intg_gen
