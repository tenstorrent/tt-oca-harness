// SPDX-License-Identifier: Apache-2.0
// (c) 2026 Tenstorrent USA Inc

//-----------------------------------------------------------------------------
// Efuse typedefs and parameters
//
//-----------------------------------------------------------------------------

package efuse_pkg;

    `include "axi/typedef.svh"

    `include "apb/typedef.svh"
    `include "efuse_typedef.svh"

    localparam int unsigned LOCK_FIELD_BIT_WIDTH = 64;
    localparam int unsigned EFUSE_FIELD_MAP_IDX_WIDTH = $clog2(LOCK_FIELD_BIT_WIDTH/2);

    //////////////////////////////
    // Register Map Definitions //
    //////////////////////////////

    localparam int unsigned NUM_END_POINTS_DECODE = 2;
    typedef enum logic [$clog2(NUM_END_POINTS_DECODE)-1:0] {
        INTERFACE_SEL         = 1'd0,
        SHIM_SEL              = 1'd1
    } efuse_req_decode_select_e;

    localparam int unsigned NUM_END_POINTS_REG = 4;
    typedef enum logic [$clog2(NUM_END_POINTS_REG)-1:0] {
        SHADOW_REG_MAP              = 2'd0,
        EFUSE_CSR_REG_MAP           = 2'd1,
        EFUSE_MMR_REG_MAP           = 2'd2,
        ERR_DECODE                  = 2'd3
    } efuse_reg_map_e;

    //////////////////////////////
    // JTAG Tap Parameters      //
    //////////////////////////////

    localparam int unsigned TDR_WIDTH = 32;
    typedef logic [TDR_WIDTH-1:0] tdr_t;

    //////////////////////////////
    // LC State Encoding        //
    //////////////////////////////

    localparam int unsigned LC_STATE_RAW_WIDTH = 4;

    typedef enum logic [LC_STATE_RAW_WIDTH-1:0] {
        LC_TEST_DEV    = 4'b0000,
        LC_PROD        = 4'b0001,
        LC_RMA_SIP_0   = 4'b0010,
        LC_RMA_SIP_1   = 4'b0011,
        LC_RMA_CHIP_0  = 4'b0110,
        LC_RMA_CHIP_1  = 4'b0111,
        LC_PROD_END    = 4'b1000
    } lc_state_raw_e;

    // Returns 1 iff s is a valid LC_STATE encoding per OCAH spec (0x0, 0x1, 0x2, 0x3, 0x6, 0x7, 0x8).
    function automatic logic is_valid_lc_state(logic [LC_STATE_RAW_WIDTH-1:0] s);
        return s inside {LC_TEST_DEV, LC_PROD, LC_RMA_SIP_0, LC_RMA_SIP_1,
                         LC_RMA_CHIP_0, LC_RMA_CHIP_1, LC_PROD_END};
    endfunction

    //////////////////////////////
    // Shadow Register Indices  //
    //////////////////////////////

    localparam int unsigned SHADOW_IDX_LC_STATE         = 2;
    localparam int unsigned SHADOW_IDX_TRANSIENT_RMA_EN = 4;

    //////////////////////////////
    // Fuse Command Parameters  //
    //////////////////////////////

    typedef enum logic [1:0] {
        FUSE_COMMAND_READ = 2'b00,
        FUSE_COMMAND_PROGRAM = 2'b01,
        FUSE_COMMAND_PROGRAM_READ_BACK = 2'b10
    } fuse_command_e;

    typedef struct packed {
      logic [EFUSE_FIELD_MAP_IDX_WIDTH - 1:0] idx;
      logic [3:0] lock;
      logic [31:0] start_addr;
      logic [31:0] end_addr;
    } rule_t;

endpackage
