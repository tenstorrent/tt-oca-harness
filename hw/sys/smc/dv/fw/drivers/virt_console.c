/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

#include <stdint.h>
#include <stdlib.h>

#include "virt_console.h"
#include "smc_io.h"

/*
Format of 32-bit writes to scratch2 for virtual console:
Byte order is little endian

Upper 24 bits are payload
Lower 8 bits:
    [7:4] reserved, must be 0
    [3:1] opcode
    [0]   toggle bit, toggles to ensure every write to register is processed by environment

Opcodes:
0x0 : 24-bit payload is ASCII (lowest-order byte is first character)
0x1 : 16-bit hex (little endian), presented as hex
0x2 : 24-bit decimal, presented as decimal (no encoder in this driver)
0x3-0x7 : reserved
*/

static void write_scratch2(uint32_t val) {
    static uint32_t prev_val = 0;
    if (val == prev_val) val ^= 1; // Toggle the lowest bit if same as previous
    write_scratch(2, val);
    prev_val = val;
}

void simputs(const char *str) {
    uint32_t val = 0 << 1; // Start with opcode = 0 (ASCII)
    int offset = 1;        // Offset in payload: 1=LSB of payload, 3=MSB of payload
    while (*str) {
        // Place next char into the payload
        val |= (*str++ & 0xFF) << (8 * offset++);
        if (offset == 4) {
            // Full payload (3 chars), write out
            write_scratch2(val);
            offset = 1;
            val = 0;
        }
    }
    // If there's a partially filled payload, write it out
    if (offset != 1) write_scratch2(val);
}

static inline void _simputhex16(const uint16_t hexval) {
    const uint32_t val = ((uint32_t)hexval << 8) | (1 << 1); // opcode=1
    write_scratch2(val);
}

inline void simputhex16(const uint16_t val) {
    simputs("0x");
    _simputhex16(val);
}

inline void simputhex32(const uint32_t val) {
    simputs("0x");
    _simputhex16((uint16_t)(val >> 16));
    _simputhex16((uint16_t)(val & 0xFFFF));
}

inline void simputhex64(const uint64_t val) {
    simputs("0x");
    _simputhex16((uint16_t)(val >> 48));
    _simputhex16((uint16_t)(val >> 32));
    _simputhex16((uint16_t)(val >> 16));
    _simputhex16((uint16_t)(val & 0xFFFF));
}

void simputshex16(const char *msg, uint16_t val) {
    simputs(msg);
    simputhex16(val);
    simputs("\n");
}

void simputshex32(const char *msg, uint32_t val) {
    simputs(msg);
    simputhex32(val);
    simputs("\n");
}

void simputshex64(const char *msg, uint64_t val) {
    simputs(msg);
    simputhex64(val);
    simputs("\n");
}