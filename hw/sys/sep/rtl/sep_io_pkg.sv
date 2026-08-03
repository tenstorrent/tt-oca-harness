// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// SEP IO submodule typedefs and parameters

package sep_io_pkg;

    localparam int unsigned ADDR_WIDTH = 32;
    localparam int unsigned DATA_WIDTH = 32;
    localparam int unsigned STRB_WIDTH = DATA_WIDTH / 8;

    typedef logic [ADDR_WIDTH-1:0] addr_t;
    typedef logic [DATA_WIDTH-1:0] data_t;
    typedef logic [STRB_WIDTH-1:0] strb_t;

    `AXI_TYPEDEF_ALL     (axi, addr_t, sep_pkg::sep_io_axi_id_t, data_t, strb_t, sep_pkg::sep_io_axi_user_t)
    `AXI_LITE_TYPEDEF_ALL(axil, addr_t, data_t, strb_t)

    //=========================================================================
    // SPI Interface Types
    // Uses active-low OE/IE (_n suffix) to match tt_sep and smc_padring
    // Cadence PHY has both OE and IE; OpenTitan only has OE (IE generated)
    // Supports up to 8 data lines (Octal SPI) for Cadence xSPI
    // OpenTitan uses only sd[3:0] (Quad SPI)
    //=========================================================================

    typedef struct packed {
        // Clock (directly active)
        logic       sck;
        logic       sck_oe;

        // Chip Select (directly active-low)
        logic       cs_n;
        logic       cs_oe;

        // Data (directly active signals) - 8 lanes for Octal SPI
        // OpenTitan only uses sd[3:0], Cadence uses sd[7:0]
        logic [3:0] sd;
        logic [3:0] sd_oe;

        // Interrupt
        logic       irq;

        // Busy
        logic       busy;

        // DMA trigger
       logic        lsio_trigger;
    } sep_io_spi_req_t;

    typedef struct packed {
        // Data input from pad (8 lanes for Octal SPI)
        logic [3:0] sd;
    } sep_io_spi_rsp_t;

endpackage
