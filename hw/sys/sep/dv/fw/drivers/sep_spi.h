// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// SEP OpenTitan SPI-host firmware helpers for the OSS tests. Header-only.
// Addresses and field masks come from generated sep_addr.h / spi_controller.h
// (via sep.h). Do not alias those symbols — call them by their PeakRDL names.

#ifndef SEP_SPI_H
#define SEP_SPI_H

#include <stdint.h>

#include "sep.h"

// CFG: CPOL/CPHA = 0 (Mode 0). CS timing CSNIDLE/TRAIL/LEAD=2 matches the OSS
// flash BFM (composed from generated field positions, not a packed hex constant).
#define SPI_CFG_CSN_TIMING \
    ((2u << SPI_CONTROLLER__CONFIGOPTS__CSNIDLE_bp) | (2u << SPI_CONTROLLER__CONFIGOPTS__CSNTRAIL_bp) | \
     (2u << SPI_CONTROLLER__CONFIGOPTS__CSNLEAD_bp))
#define SPI_CFG_CLKDIV9_CSN (SPI_CFG_CSN_TIMING | 9u)
#define SPI_CFG_CSN(clkdiv) (SPI_CFG_CSN_TIMING | ((uint32_t)(clkdiv)&0xFFFFu))

// CMD.DIRECTION encodings (not named in PeakRDL).
#define SPI_CMD_DIR_RX 1u
#define SPI_CMD_DIR_TX 2u

/*
 * Composed register reset values (OCH_SEP_FIELD_RESET from sep.h).
 * Keep SPI-only reset aggregates here rather than growing common sep.h.
 */
#define SPI_CONTROLLER__INTR_STATE_reset \
    (OCH_SEP_FIELD_RESET(SPI_CONTROLLER__INTR_STATE, ERROR) | \
     OCH_SEP_FIELD_RESET(SPI_CONTROLLER__INTR_STATE, SPI_EVENT))

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
 * ERROR_STATUS field macros are PeakRDL-mangled in blocks/spi_controller.h.
 * Every field resets to 0.
 */
#define SPI_CONTROLLER__ERROR_STATUS_reset 0u

static inline uint32_t spi_rd(uint32_t addr) {
    return *(volatile uint32_t *)addr;
}

static inline void spi_wr(uint32_t addr, uint32_t value) {
    *(volatile uint32_t *)addr = value;
}

static inline int spi_wait_ready(int timeout) {
    /* Bounded so a wedged host surfaces as a firmware timeout. */
    while (timeout-- > 0) {
        if (spi_rd(OCH_SEP_TOP_SPI_CONTROLLER_STATUS_BASE_ADDR) &
            SPI_CONTROLLER__STATUS__READY_bm) {
            return 0;
        }
    }
    return -1;
}

// Spin until the controller is idle (no active segment).
static inline int spi_wait_idle(int timeout) {
    while (timeout-- > 0) {
        if (!(spi_rd(OCH_SEP_TOP_SPI_CONTROLLER_STATUS_BASE_ADDR) &
              SPI_CONTROLLER__STATUS__ACTIVE_bm)) {
            return 0;
        }
    }
    return -1;
}

#endif // SEP_SPI_H
