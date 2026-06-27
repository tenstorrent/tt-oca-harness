// SPDX-License-Identifier: Apache-2.0
// (c) 2026 Tenstorrent USA Inc

//-----------------------------------------------------------------------------
// Entropy Source Package
//
//-----------------------------------------------------------------------------


package entropy_source_pkg;

    localparam int unsigned REG_ADDR_WIDTH = entropy_source_reg_pkg::ENTROPY_SOURCE_REG_MIN_ADDR_WIDTH;
    localparam int unsigned REG_DATA_WIDTH = 32;
    localparam int unsigned REG_STRB_WIDTH = REG_DATA_WIDTH / 8;

    typedef logic [REG_ADDR_WIDTH-1:0] reg_addr_t;
    typedef logic [REG_DATA_WIDTH-1:0] reg_data_t;
    typedef logic [REG_STRB_WIDTH-1:0] reg_strb_t;

    localparam int unsigned NRINGS = 12;

endpackage
