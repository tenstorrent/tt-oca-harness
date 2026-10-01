/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

// SPI parameter TLV used by BL0/ROM SPI init.
//
// Minimal SPI TLV definition for the OCAH SEP ROM bring-up environment
// (freestanding, no libc).
#
// NOTE: This header intentionally does not depend on the broader status
// or logging infrastructure.
#
#pragma once

#include <stdint.h>

#ifndef BIT
#define BIT(n) (1u << (n))
#endif

// TLV structure for SPI parameters.
// `type` is 0x464C ("FL") in little-endian.
#define SPI_PARAM_TLV_TYPE 0x464Cu
#define SPI_PARAM_KEEP_DEFAULT_INIT BIT(0)

struct spi_param_tlv {
    uint16_t type;
    uint16_t length;
    uint8_t flags; // Bit 0: KEEP_DEFAULT_INIT
    uint8_t spi_freq;
    uint8_t unused1;
    uint8_t unused2;
    // SPI configuration register values follow.
    uint32_t discovery_ctrl;
    uint32_t dq_timing;
    uint32_t dqs_timing;
    uint32_t gate_lpbk;
    uint32_t dll_slave;
    uint32_t dll_master;
    uint32_t misc;
    uint32_t rb_valid_time;
};
