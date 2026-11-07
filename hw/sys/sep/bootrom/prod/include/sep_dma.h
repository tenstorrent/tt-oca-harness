/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

// OCAH SEP ROM DMA API.
//
// Implemented against OCAH's `secure_dma` register block.

#pragma once

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#include "sep.h"

enum {
    SEP_DMA_ERR_OUT_OF_RANGE = 0x00020001u,
    SEP_DMA_ERR_TRANSFER = 0x00020002u,
};

void sep_dma_init(void);
uint32_t sep_dma_copy(uint32_t dest, uint32_t src, size_t len);

// Fills `len` bytes at `dest` with zero using the secure DMA's zero fill, which
// reads no memory. `dest` and `len` must be whole aligned words, `len` non-zero,
// and the span inside one of SEP SRAM, SMC SRAM or ICCM; anything else returns
// SEP_DMA_ERR_OUT_OF_RANGE before the engine is touched. The engine's enabled
// range is left set to that whole region. Returns 0 only when the engine reports
// completion with no error; every other outcome is non-zero.
//
// The secure DMA is the only writer of ICCM, which the CPU cannot store to (ICCM
// shares VeeR region 0xC with DCCM, so the LSU faults any ICCM address). A zero
// fill there establishes the ECC of the words it covers.
uint32_t sep_dma_zero(uint32_t dest, size_t len);
