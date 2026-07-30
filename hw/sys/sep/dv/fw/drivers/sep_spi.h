// SPDX-License-Identifier: Apache-2.0
//
// SEP OpenTitan SPI-host firmware driver for the OSS tests. Header-only,
// self-contained (register addresses + field positions are SEP fabric facts,
// matching the OpenTitan spi_host CSRs at the SEP-local 0x10B0_0000 aperture /
// och_sep_top_reg). Covers the controller-init + command-issue path the
// spi_ot_dma_rx test drives; the Cadence xSPI controller is out of the OSS DUT.

#ifndef SEP_SPI_H
#define SEP_SPI_H

#include <stdint.h>

// OpenTitan SPI host CSR block (SEP local fabric @ 0x10B0_0000).
#define SPI_CTRL_BASE 0x10B00000u
#define SPI_CTRL_REG (SPI_CTRL_BASE + 0x010)
#define SPI_STATUS_REG (SPI_CTRL_BASE + 0x014)
#define SPI_CFG_REG (SPI_CTRL_BASE + 0x018)
#define SPI_CSID_REG (SPI_CTRL_BASE + 0x01C)
#define SPI_CMD_REG (SPI_CTRL_BASE + 0x020)
#define SPI_RXDATA_REG (SPI_CTRL_BASE + 0x024)
#define SPI_TXDATA_REG (SPI_CTRL_BASE + 0x028)
#define SPI_ERROR_STATUS_REG (SPI_CTRL_BASE + 0x030)
#define SPI_EVENT_ENABLE_REG (SPI_CTRL_BASE + 0x034)

// CTRL fields.
#define SPI_CTRL_RX_WM_SHIFT 0
#define SPI_CTRL_TX_WM_SHIFT 8
#define SPI_CTRL_OUTPUT_EN (1u << 29)
#define SPI_CTRL_SW_RST (1u << 30)
#define SPI_CTRL_SPIEN (1u << 31)

// CFG: clkdiv in [15:0]; CPOL/CPHA = 0 (Mode 0). The csnidle/csnlead/csntrail
// timing in [31:16] gives the device CS setup/hold the OSS flash BFM needs.
#define SPI_CFG_CLKDIV9_CSN 0x02220009u

// CMD fields.
#define SPI_CMD_LEN_SHIFT 0     // LEN = (#bytes - 1)
#define SPI_CMD_CSAAT (1u << 9) // keep CS asserted after this segment
#define SPI_CMD_SPEED_SHIFT 10  // 0 = standard (single)
#define SPI_CMD_DIR_SHIFT 12
#define SPI_CMD_DIR_RX 1u
#define SPI_CMD_DIR_TX 2u

// STATUS bits (byte-spread spi_controller layout).
#define SPI_STATUS_TXQD_MASK 0x000000FFu // TX FIFO depth (entries)
#define SPI_STATUS_RXQD_SHIFT 8
#define SPI_STATUS_TXWM (1u << 26) // TX FIFO below TX_WATERMARK
#define SPI_STATUS_ACTIVE (1u << 30)
#define SPI_STATUS_READY (1u << 31)

// EVENT_ENABLE bits (byte-spread in the SEP spi_controller reg map).
#define SPI_EVENT_RXWM (1u << 8)  // RX watermark event (drives lsio_trigger)
#define SPI_EVENT_TXWM (1u << 12) // TX watermark event (drives lsio_trigger)

static inline uint32_t spi_rd(uint32_t addr) {
    return *(volatile uint32_t *)addr;
}

static inline void spi_wr(uint32_t addr, uint32_t value) {
    *(volatile uint32_t *)addr = value;
}

// SPI mux control (extension aperture, offset 0). In the sep_wrapper DUT the
// och_sep_spi_mux_ctrl_ot register resets SPI_MUX_CTRL.cs_force_high=1, holding the
// SPI chip-select deasserted; a flash scenario must clear it so CS can toggle. On
// bare sep this aperture was tied off (the write was a no-op), so it is harmless in
// either build.
#define SEP_SPI_MUX_CTRL 0x20000000u

static inline void sep_spi_mux_release_cs(void) {
    spi_wr(SEP_SPI_MUX_CTRL, 0u); // clear cs_force_high (bit 0)
}

// Spin until the controller can accept a new command (bounded so a wedged host
// surfaces as a firmware timeout rather than an infinite loop).
static inline int spi_wait_ready(int timeout) {
    while (timeout-- > 0) {
        if (spi_rd(SPI_STATUS_REG) & SPI_STATUS_READY) {
            return 0;
        }
    }
    return -1;
}

// Spin until the controller is idle (no active segment).
static inline int spi_wait_idle(int timeout) {
    while (timeout-- > 0) {
        if (!(spi_rd(SPI_STATUS_REG) & SPI_STATUS_ACTIVE)) {
            return 0;
        }
    }
    return -1;
}

#endif // SEP_SPI_H
