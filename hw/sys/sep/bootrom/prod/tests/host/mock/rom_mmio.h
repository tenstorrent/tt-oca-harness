/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

// Host stand-in for the ROM's rom_mmio.h: every access goes to the fake register
// file of the test binary (fake_abr.c or fake_sep_dma.c), which records it.
// Narrow and wide accesses are recorded as violations, since the registers the
// drivers touch take 32-bit accesses only. It shares include/rom_mmio.h's
// include guard, and a test build force-includes it, so it defines the accessors
// whichever header a source includes.

#ifndef ROM_MMIO_H
#define ROM_MMIO_H

#include <stdint.h>

uint32_t fake_mmio_read32(uint32_t addr);
void fake_mmio_write32(uint32_t addr, uint32_t value);
void fake_mmio_bad_width(uint32_t addr);
void fake_mmio_fence(void);

static inline void mmio_write8(uint32_t addr, uint8_t value) {
    (void)value;
    fake_mmio_bad_width(addr);
}

static inline void mmio_write32(uint32_t addr, uint32_t value) {
    fake_mmio_write32(addr, value);
}

static inline void mmio_write64(uint32_t addr, uint64_t value) {
    (void)value;
    fake_mmio_bad_width(addr);
}

static inline uint32_t mmio_read32(uint32_t addr) {
    return fake_mmio_read32(addr);
}

static inline void mmio_fence(void) {
    fake_mmio_fence();
}

#endif // ROM_MMIO_H
