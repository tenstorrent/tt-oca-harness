/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

// Validation of the state the SEP ROM hands to SEP BL1.

#pragma once

#include <stdint.h>

#include "bl0_state.h"
#include "bl1_result.h"

// SEP SRAM base, where the SEP ROM stages the validated manifest.
#define BL1_SEP_SRAM_MANIFEST_ADDR 0x10000000u

struct bl1_handoff {
    uint32_t manifest_addr;
    uint32_t payload_addr;
    uint32_t payload_len;
    const uint8_t *payload;
};

// Which check failed, reported as the detail of SEP_BL1_ERR_HANDOFF.
enum {
    BL1_HANDOFF_DETAIL_MAGIC = 1u,
    BL1_HANDOFF_DETAIL_SIZE = 2u,
    BL1_HANDOFF_DETAIL_BL0_ERROR = 3u,
    BL1_HANDOFF_DETAIL_BOOT_MODE = 4u,
    BL1_HANDOFF_DETAIL_MANIFEST_ADDR = 5u,
    BL1_HANDOFF_DETAIL_MANIFEST = 6u,
    BL1_HANDOFF_DETAIL_PAYLOAD = 7u,
    BL1_HANDOFF_DETAIL_BL1_SOURCE = 8u,
};

// body holds the bytes at state->sep_sram_manifest_addr, and sram_bytes is how many bytes
// from there to the end of usable SEP SRAM. On BL1_OK, *out locates the payload.
bl1_result_t bl1_check_handoff(const struct bl0_state *state, const uint8_t *body,
                               uint32_t sram_bytes, struct bl1_handoff *out, uint32_t *detail);
