/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

// OCAH SEP ROM DMA API.
//
// Implemented against OCAH's `secure_dma` register block.

#pragma once

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

void sep_dma_init(void);
uint32_t sep_dma_copy(uint32_t dest, uint32_t src, size_t len);

// Fill `len` bytes at `dest` with zero.  Needed for ICCM, which the CPU cannot
// store to (ICCM shares VeeR region 0xC with DCCM, so the LSU faults any ICCM
// address); writing it establishes its ECC.
uint32_t sep_dma_zero(uint32_t dest, size_t len);
