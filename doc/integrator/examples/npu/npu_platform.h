// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

#ifndef OCAH_EXAMPLE_NPU_PLATFORM_H_
#define OCAH_EXAMPLE_NPU_PLATFORM_H_

#include <stdint.h>

// Illustrative adopter assignments; these are not fixed by OCAH.
#define PLATFORM_NPU_CSR_BASE      ((uintptr_t)0x30000000u)
#define PLATFORM_NPU_CSR_SIZE      0x00001000u
#define PLATFORM_NPU_DMA_BASE      ((uintptr_t)0x40000000u)
#define PLATFORM_NPU_DMA_SIZE      0x00080000u
#define PLATFORM_NPU_DONE_IRQ      42u
#define PLATFORM_NPU_ERROR_IRQ     43u

// This example range is required to be mapped uncached.
#define PLATFORM_NPU_DMA_COHERENT  0u

#endif  // OCAH_EXAMPLE_NPU_PLATFORM_H_
