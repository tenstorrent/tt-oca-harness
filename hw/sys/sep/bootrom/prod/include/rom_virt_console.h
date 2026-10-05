/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

// SEP Virtual Console scratch-register protocol.
//
// Encodes text and numeric output into packed 32-bit writes to
// SEP_SCRATCH_COLD_SCRATCH_2.  A cocotb monitor decodes these writes
// and prints them to the simulation log.
//
// Protocol (little-endian):
//   [31:8]  payload
//   [7:4]   reserved (0)
//   [3:1]   opcode: 0=ASCII, 1=HEX16, 2=DEC24
//   [0]     toggle bit (flips when consecutive values are identical)
//
// ASCII:  3 characters packed into payload bytes [15:8], [23:16], [31:24]
// HEX16:  16-bit value in payload [23:8]
// DEC24:  24-bit value in payload [31:8]

#pragma once

#include <stdint.h>

#include "sep.h"
#include "rom_mmio.h"

#ifdef DEBUG

#define VCONSOLE_OP_ASCII (0u << 1)
#define VCONSOLE_OP_HEX16 (1u << 1)
#define VCONSOLE_OP_DEC24 (2u << 1)

static uint32_t g_vconsole_prev_val;

static inline void vconsole_write_scratch2(uint32_t val) {
    if (val == g_vconsole_prev_val) val ^= 1u;
    mmio_write32(SEP_TOP_SEP_SCRATCH_COLD_SCRATCH_BASE_ADDR(2), val);
    g_vconsole_prev_val = val;
}

// ── ASCII string output ──

static inline void simputs(const char *str) {
    uint32_t val = VCONSOLE_OP_ASCII;
    int offset = 1; // byte index: 1=LSB of payload, 3=MSB

    while (*str) {
        val |= ((uint32_t)(uint8_t)*str++) << (8u * (uint32_t)offset++);
        if (offset == 4) {
            vconsole_write_scratch2(val);
            offset = 1;
            val = VCONSOLE_OP_ASCII;
        }
    }
    if (offset != 1) vconsole_write_scratch2(val);
}

// ── Hex output ──

static inline void _simputhex16(uint16_t hexval) {
    uint32_t val = ((uint32_t)hexval << 8) | VCONSOLE_OP_HEX16;
    vconsole_write_scratch2(val);
}

static inline void simputhex16(uint16_t val) {
    simputs("0x");
    _simputhex16(val);
}

static inline void simputhex32(uint32_t val) {
    simputs("0x");
    _simputhex16((uint16_t)(val >> 16));
    _simputhex16((uint16_t)(val & 0xFFFFu));
}

// ── Decimal output ──

static inline void simputdec24(uint32_t decval) {
    uint32_t regval = (decval << 8) | VCONSOLE_OP_DEC24;
    vconsole_write_scratch2(regval);
}

// ── Convenience: message + value + newline ──

static inline void simputshex16(const char *msg, uint16_t val) {
    simputs(msg);
    simputhex16(val);
    simputs("\n");
}

static inline void simputshex32(const char *msg, uint32_t val) {
    simputs(msg);
    simputhex32(val);
    simputs("\n");
}

static inline void simputsdec24(const char *msg, uint32_t val) {
    simputs(msg);
    simputdec24(val);
    simputs("\n");
}

#else

#define simputs(str) ((void)0)
#define simputhex16(val) ((void)0)
#define simputhex32(val) ((void)0)
#define simputdec24(decval) ((void)0)
#define simputshex16(msg, val) ((void)0)
#define simputshex32(msg, val) ((void)0)
#define simputsdec24(msg, val) ((void)0)

#endif

// Status output is now in errors.h (STATUS_OUT / report_status / SEP_MSG_*).
