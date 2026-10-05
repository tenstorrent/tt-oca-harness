/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

// Minimal MMIO helpers for ROM bring-up (freestanding).
// Keep this header C/C++ friendly and usable from tiny ROM code.

#pragma once

#include <stdint.h>

static inline void mmio_write8(uint32_t addr, uint8_t value) {
    *(volatile uint8_t *)addr = value;
}

static inline void mmio_write32(uint32_t addr, uint32_t value) {
    *(volatile uint32_t *)addr = value;
}

static inline void mmio_write64(uint32_t addr, uint64_t value) {
    *(volatile uint64_t *)addr = value;
}

static inline uint32_t mmio_read32(uint32_t addr) {
    return *(volatile uint32_t *)addr;
}
