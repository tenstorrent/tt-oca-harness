// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// SRAM interface struct defines
`define CHIPYARD_MEM_REQ_T(TYPE_NAME, ADDR_WIDTH, DATA_WIDTH, MASK_WIDTH) \
typedef struct packed { \
    logic                      clk; \
    logic                      en; \
    logic [ADDR_WIDTH-1:0]     addr; \
    logic [DATA_WIDTH-1:0]     wdata; \
    logic                      wmode; \
    logic [MASK_WIDTH-1:0]     wmask; \
} TYPE_NAME;

`define CHIPYARD_MEM_RSP_T(TYPE_NAME, DATA_WIDTH) \
typedef struct packed { \
    logic [DATA_WIDTH-1:0]     rdata; \
} TYPE_NAME;

// ROM interface struct defines
`define CHIPYARD_ROM_REQ_T(TYPE_NAME, ADDR_WIDTH, SOURCE_WIDTH) \
typedef struct packed { \
    logic                      clock; \
    logic                      reset; \
    logic                      a_valid; \
    logic [1:0]                a_bits_size; \
    logic [SOURCE_WIDTH-1:0]   a_bits_source; \
    logic [ADDR_WIDTH-1:0]     a_bits_address; \
    logic                      d_ready; \
} TYPE_NAME;

`define CHIPYARD_ROM_RSP_T(TYPE_NAME, DATA_WIDTH, SOURCE_WIDTH) \
typedef struct packed { \
    logic                      a_ready; \
    logic                      d_valid; \
    logic [1:0]                d_bits_size; \
    logic [SOURCE_WIDTH-1:0]   d_bits_source; \
    logic [DATA_WIDTH-1:0]     d_bits_data; \
} TYPE_NAME;
