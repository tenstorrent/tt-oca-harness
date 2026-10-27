/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

// SMC BL1 image and SMC SRAM zone checks. Every range is SMC-local and half-open, and every
// sum is checked in 64 bits before it is used.

#pragma once

#include <stddef.h>
#include <stdint.h>

#include "bl1_result.h"

// TOC fields of the SMC BL1 entry. entry_point is an offset from load_addr.
struct bl1_image_desc {
    uint64_t load_addr;
    uint64_t length;
    uint64_t entry_point;
    const uint8_t *bytes; // the image in the payload the SEP ROM verified
    const uint8_t *hash;  // its verified SHA-256
};

// Finds the single TOC entry of type SMU_BL1_SMC_IMAGE_TYPE in a validated payload.
// Returns SEP_BL1_ERR_SMC_IMAGE_MISSING or _DUPLICATE when there is not exactly one.
bl1_result_t bl1_find_smc_image(const uint8_t *payload, size_t payload_len,
                                struct bl1_image_desc *out);

// The image range is nonzero, a multiple of 4, below 4 GiB, 8-byte aligned, does not wrap,
// has a 4-byte-aligned entry inside it, and lies inside the SMC BL1 image window.
bl1_result_t bl1_check_smc_image(const struct bl1_image_desc *img);

// Raw coordination scratch values, both halves of each 64-bit register.
struct bl1_smc_zone_regs {
    uint32_t status_lo;    // scratch 9
    uint32_t start_off_lo; // scratch 13: offset from the SMC SRAM base
    uint32_t start_off_hi;
    uint32_t size_lo; // scratch 14
    uint32_t size_hi;
};

// The published SMC zone is valid and contains the SEP zone. Sets BL1_WARN_ZONE_MISMATCH in
// *warnings when the two zones differ.
bl1_result_t bl1_check_smc_zone(const struct bl1_smc_zone_regs *regs, uint32_t *warnings);
