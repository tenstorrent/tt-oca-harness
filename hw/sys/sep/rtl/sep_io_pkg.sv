// SPDX-License-Identifier: Apache-2.0
// (c) 2026 Tenstorrent USA Inc

//-----------------------------------------------------------------------------
// SEP IO submodule typedefs and parameters
//
//-----------------------------------------------------------------------------

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
    // Uses explicit OE signals at the open wrapper boundary.
    // Adopter overlays are responsible for any pad-specific polarity conversion.
    // The open OpenTitan SPI path uses sd[3:0] (Quad SPI).
    //=========================================================================

    typedef struct packed {
        // Clock (directly active)
        logic       sck;
        logic       sck_oe;

        // Chip Select (directly active-low)
        logic       cs_n;
        logic       cs_oe;

        // Data signals for the open Quad SPI path
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
