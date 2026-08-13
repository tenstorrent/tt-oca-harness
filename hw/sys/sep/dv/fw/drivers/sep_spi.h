// SPDX-License-Identifier: Apache-2.0
//
// SEP OpenTitan SPI-host firmware driver for the OSS tests. Header-only.
// Register addresses and field masks come from generated sep_addr.h /
// spi_controller.h (via sep.h) — do not keep a parallel hand-copied map.

#ifndef SEP_SPI_H
#define SEP_SPI_H

#include <stdint.h>

#include "sep.h"
#include "spi_mux.h"

// OpenTitan SPI host CSR block (generated sep_addr.h aperture).
#define SPI_CTRL_BASE OCH_SEP_TOP_SPI_CONTROLLER_BASE_ADDR
#define SPI_CTRL_REG OCH_SEP_TOP_SPI_CONTROLLER_CTRL_BASE_ADDR
#define SPI_STATUS_REG OCH_SEP_TOP_SPI_CONTROLLER_STATUS_BASE_ADDR
#define SPI_CFG_REG OCH_SEP_TOP_SPI_CONTROLLER_CFG_BASE_ADDR
#define SPI_CSID_REG OCH_SEP_TOP_SPI_CONTROLLER_CSID_BASE_ADDR
#define SPI_CMD_REG OCH_SEP_TOP_SPI_CONTROLLER_CMD_BASE_ADDR
#define SPI_RXDATA_REG OCH_SEP_TOP_SPI_CONTROLLER_RXDATA_BASE_ADDR
#define SPI_TXDATA_REG OCH_SEP_TOP_SPI_CONTROLLER_TXDATA_BASE_ADDR
#define SPI_ERROR_STATUS_REG OCH_SEP_TOP_SPI_CONTROLLER_ERROR_STATUS_BASE_ADDR
#define SPI_EVENT_ENABLE_REG OCH_SEP_TOP_SPI_CONTROLLER_EVENT_ENABLE_BASE_ADDR

// CTRL fields (generated bit positions).
#define SPI_CTRL_RX_WM_SHIFT SPI_CONTROLLER__CTRL__RX_WATERMARK_bp
#define SPI_CTRL_TX_WM_SHIFT SPI_CONTROLLER__CTRL__TX_WATERMARK_bp
#define SPI_CTRL_OUTPUT_EN SPI_CONTROLLER__CTRL__OUTPUT_EN_bm
#define SPI_CTRL_SW_RST SPI_CONTROLLER__CTRL__SW_RST_bm
#define SPI_CTRL_SPIEN SPI_CONTROLLER__CTRL__SPIEN_bm

// CFG: clkdiv in [15:0]; CPOL/CPHA = 0 (Mode 0). CS timing CSNIDLE/TRAIL/LEAD=2
// matches the OSS flash BFM needs (composed from generated field positions).
#define SPI_CFG_CSN_TIMING \
    ((2u << SPI_CONTROLLER__CFG__CSNIDLE_bp) | (2u << SPI_CONTROLLER__CFG__CSNTRAIL_bp) | \
     (2u << SPI_CONTROLLER__CFG__CSNLEAD_bp))
#define SPI_CFG_CLKDIV9_CSN (SPI_CFG_CSN_TIMING | 9u)
#define SPI_CFG_CSN(clkdiv) (SPI_CFG_CSN_TIMING | ((uint32_t)(clkdiv)&0xFFFFu))

// CMD fields.
#define SPI_CMD_LEN_SHIFT SPI_CONTROLLER__CMD__LEN_bp
#define SPI_CMD_CSAAT SPI_CONTROLLER__CMD__CSAAT_bm
#define SPI_CMD_SPEED_SHIFT SPI_CONTROLLER__CMD__SPEED_bp
#define SPI_CMD_DIR_SHIFT SPI_CONTROLLER__CMD__DIRECTION_bp
#define SPI_CMD_DIR_RX 1u
#define SPI_CMD_DIR_TX 2u

// STATUS bits.
#define SPI_STATUS_TXQD_MASK SPI_CONTROLLER__STATUS__TXQD_bm
#define SPI_STATUS_RXQD_SHIFT SPI_CONTROLLER__STATUS__RXQD_bp
#define SPI_STATUS_TXWM SPI_CONTROLLER__STATUS__TXWM_bm
#define SPI_STATUS_ACTIVE SPI_CONTROLLER__STATUS__ACTIVE_bm
#define SPI_STATUS_READY SPI_CONTROLLER__STATUS__READY_bm

// EVENT_ENABLE bits.
#define SPI_EVENT_RXWM SPI_CONTROLLER__EVENT_ENABLE__RXWM_bm
#define SPI_EVENT_TXWM SPI_CONTROLLER__EVENT_ENABLE__TXWM_bm

/*
 * Composed register reset values (OCH_SEP_FIELD_RESET from sep.h).
 * Keep SPI-only reset aggregates here rather than growing common sep.h.
 */
#define SPI_CONTROLLER__INTR_STATUS_reset \
    (OCH_SEP_FIELD_RESET(SPI_CONTROLLER__INTR_STATUS, ERROR) | \
     OCH_SEP_FIELD_RESET(SPI_CONTROLLER__INTR_STATUS, SPI_EVENT))

#define SPI_CONTROLLER__INTR_ENABLE_reset \
    (OCH_SEP_FIELD_RESET(SPI_CONTROLLER__INTR_ENABLE, ERROR) | \
     OCH_SEP_FIELD_RESET(SPI_CONTROLLER__INTR_ENABLE, SPI_EVENT))

#define SPI_CONTROLLER__INTR_TEST_reset \
    (OCH_SEP_FIELD_RESET(SPI_CONTROLLER__INTR_TEST, ERROR) | \
     OCH_SEP_FIELD_RESET(SPI_CONTROLLER__INTR_TEST, SPI_EVENT))

#define SPI_CONTROLLER__CSID_reset (OCH_SEP_FIELD_RESET(SPI_CONTROLLER__CSID, CSID))

#define SPI_CONTROLLER__EVENT_ENABLE_reset \
    (OCH_SEP_FIELD_RESET(SPI_CONTROLLER__EVENT_ENABLE, RXFULL) | \
     OCH_SEP_FIELD_RESET(SPI_CONTROLLER__EVENT_ENABLE, TXEMPTY) | \
     OCH_SEP_FIELD_RESET(SPI_CONTROLLER__EVENT_ENABLE, RXWM) | \
     OCH_SEP_FIELD_RESET(SPI_CONTROLLER__EVENT_ENABLE, TXWM) | \
     OCH_SEP_FIELD_RESET(SPI_CONTROLLER__EVENT_ENABLE, READY) | \
     OCH_SEP_FIELD_RESET(SPI_CONTROLLER__EVENT_ENABLE, IDLE))

/*
 * ERROR_STATUS field macros are PeakRDL-mangled in blocks/spi_controller.h;
 * och_sep_common.h only aliases *_bm. Every field resets to 0, so the
 * aggregate is identically zero (same as the pre-refactor check).
 */
#define SPI_CONTROLLER__ERROR_STATUS_reset 0u

static inline uint32_t spi_rd(uint32_t addr) {
    return *(volatile uint32_t *)addr;
}

static inline void spi_wr(uint32_t addr, uint32_t value) {
    *(volatile uint32_t *)addr = value;
}

// SPI mux control. Out of reset SPI_MUX_CTRL selects the Cadence xSPI controller
// and forces CS# high, so an OT scenario must both point the mux at the OT host
// (spi_sel=1) and release CS# (cs_force_high=0).
static inline void sep_spi_mux_release_cs(void) {
    spi_mux_select_ot();
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
