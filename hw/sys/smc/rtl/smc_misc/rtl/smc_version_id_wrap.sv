// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// Generate the SMC version identifier from metal-programmable revision cells.
//
// Eight prim_rev_cell instances each produce one byte, so a metal-only respin can change
// the version; the current ties give 0x00000000_000100A0. The module has no bus
// interface: smc_misc_wrap reports the value through the chip_config VERSION_LO and
// VERSION_HI registers.

module smc_version_id_wrap (
  output logic [63:0] version_id_o      // Version identifier from eight metal-programmable revision
                                        // cells, one byte per cell; read back through the
                                        // chip_config VERSION_LO and VERSION_HI registers.
);

  // rev cell, pulls tie signals to top metal layer to allow for easy re-spin
  // can't put this into a for loop because it needs fine control over the values

  // Integrator must set src_low_i and src_high_i to define the version ID values.
  // The version ID is stored in the chip_config VERSION_LO and VERSION_HI registers

  logic [63:0] low;
  logic [63:0] high;

  prim_rev_cell u_prim_rev_cell_0 (
    .src_low_i(1'b0),
    .src_high_i(1'b1),

    .lo_o(low[7:0]),
    .hi_o(high[7:0]),

    .in_i({high[7], low[6], high[5], low[4], low[3], low[2], low[1], low[0]}), // A0
    .out_o(version_id_o[7:0])
  );

  prim_rev_cell u_prim_rev_cell_1 (
    .src_low_i(1'b0),
    .src_high_i(1'b1),

    .lo_o(low[15:8]),
    .hi_o(high[15:8]),

    .in_i({low[15], low[14], low[13], low[12], low[11], low[10], low[9], low[8]}),    // 00
    .out_o(version_id_o[15:8])
  );

  prim_rev_cell u_prim_rev_cell_2 (
    .src_low_i(1'b0),
    .src_high_i(1'b1),

    .lo_o(low[23:16]),
    .hi_o(high[23:16]),

    .in_i({low[23], low[22], low[21], low[20], low[19], low[18], low[17], high[16]}), // 01
    .out_o(version_id_o[23:16])
  );

  prim_rev_cell u_prim_rev_cell_3 (
    .src_low_i(1'b0),
    .src_high_i(1'b1),

    .lo_o(low[31:24]),
    .hi_o(high[31:24]),

    .in_i({low[31], low[30], low[29], low[28], low[27], low[26], low[25], low[24]}),    // 00
    .out_o(version_id_o[31:24])
  );

  prim_rev_cell u_prim_rev_cell_4 (
    .src_low_i(1'b0),
    .src_high_i(1'b1),

    .lo_o(low[39:32]),
    .hi_o(high[39:32]),

    .in_i({low[39], low[38], low[37], low[36], low[35], low[34], low[33], low[32]}),    // 00
    .out_o(version_id_o[39:32])
  );

  prim_rev_cell u_prim_rev_cell_5 (
    .src_low_i(1'b0),
    .src_high_i(1'b1),

    .lo_o(low[47:40]),
    .hi_o(high[47:40]),

    .in_i({low[47], low[46], low[45], low[44], low[43], low[42], low[41], low[40]}),    // 00
    .out_o(version_id_o[47:40])
  );

  prim_rev_cell u_prim_rev_cell_6 (
    .src_low_i(1'b0),
    .src_high_i(1'b1),

    .lo_o(low[55:48]),
    .hi_o(high[55:48]),

    .in_i({low[55], low[54], low[53], low[52], low[51], low[50], low[49], low[48]}),    // 00
    .out_o(version_id_o[55:48])
  );

  prim_rev_cell u_prim_rev_cell_7 (
    .src_low_i(1'b0),
    .src_high_i(1'b1),

    .lo_o(low[63:56]),
    .hi_o(high[63:56]),

    .in_i({low[63], low[62], low[61], low[60], low[59], low[58], low[57], low[56]}),    // 00
    .out_o(version_id_o[63:56])
  );

endmodule
