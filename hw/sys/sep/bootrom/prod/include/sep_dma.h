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
