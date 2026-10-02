// Copyright lowRISC contributors (OpenTitan project).
// Licensed under the Apache License, Version 2.0, see LICENSE for details.
// SPDX-License-Identifier: Apache-2.0

// Encode a data word with bus integrity bits.
//
// Append the computed integrity checkbits to data_i on data_intg_o.

module tlul_data_integ_enc
  import tlul_pkg::*;
(
  input        [DATA_MAX_WIDTH-1:0]                 data_i,      // Raw data word to protect.
  output logic [DATA_MAX_WIDTH+DATA_INTG_WIDTH-1:0] data_intg_o  // Data with generated integrity.
);
  prim_secded_inv_39_32_enc u_data_gen (
    .data_i,
    .data_o(data_intg_o)
  );

endmodule : tlul_data_integ_enc
