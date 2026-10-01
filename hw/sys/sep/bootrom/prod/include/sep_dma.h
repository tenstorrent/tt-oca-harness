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

// The engine needs a source address even for a fill, so sep_dma_zero() keeps
// one word that the CPU zeroes and the engine re-reads for every beat. It sits
// at the top of SEP SRAM, and the bytes it occupies belong to no one else.
//
// SEP_SRAM_USABLE_SIZE, not the region size, is what every consumer that hands
// out SEP SRAM must bound itself with: the manifest body and the payload
// (oca_boot.c) and BL1's permitted load span (rom_handoff.c). The CPU writes
// the fill word immediately before each fill, so anything else placed there is
// destroyed part-way through a boot -- and the last such overlap was invisible
// because the only reader of the corrupted bytes was BL1, not the ROM.
#define SEP_SRAM_FILL_RESERVE_BYTES 8u
#define SEP_SRAM_USABLE_SIZE ((uint32_t)SEP_TOP_SEP_SRAM_SIZE - SEP_SRAM_FILL_RESERVE_BYTES)
#define SEP_SRAM_FILL_WORD_ADDR ((uint32_t)SEP_TOP_SEP_SRAM_BASE_ADDR + SEP_SRAM_USABLE_SIZE)

void sep_dma_init(void);
uint32_t sep_dma_copy(uint32_t dest, uint32_t src, size_t len);

// Fill `len` bytes at `dest` with zero.  Needed for ICCM, which the CPU cannot
// store to (ICCM shares VeeR region 0xC with DCCM, so the LSU faults any ICCM
// address); writing it establishes its ECC.
uint32_t sep_dma_zero(uint32_t dest, size_t len);
