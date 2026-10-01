// Copyright lowRISC contributors (OpenTitan project).
// Licensed under the Apache License, Version 2.0, see LICENSE for details.
// SPDX-License-Identifier: Apache-2.0

// Decode data-plus-integrity and report a data-integrity error.
//
// Check the integrity bits appended to data_intg_i and raise data_err_o when the payload
// does not match.

module tlul_data_integ_dec
  import tlul_pkg::*;
(
  input        [DATA_MAX_WIDTH+DATA_INTG_WIDTH-1:0] data_intg_i,  // Data word with integrity bits.
  output logic                                      data_err_o    // High when data integrity fails.
);
  logic [1:0] data_err;
  prim_secded_inv_39_32_dec u_data_chk (
    .data_i(data_intg_i),
    .data_o(),
    .syndrome_o(),
    .err_o(data_err)
  );

  assign data_err_o = |data_err;

endmodule : tlul_data_integ_dec
