/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

#include "bl1_handoff.h"

#include "oca_validator.h"
#include "sep_bl1_status.h"

static bl1_result_t fail(uint32_t *detail, uint32_t which) {
    *detail = which;
    return SEP_BL1_ERR_HANDOFF;
}

bl1_result_t bl1_check_handoff(const struct bl0_state *state, const uint8_t *body,
                               uint32_t sram_bytes, struct bl1_handoff *out, uint32_t *detail) {
    if (state->start_magic != BL0_STATE_MAGIC || state->end_magic != BL0_STATE_MAGIC) {
        return fail(detail, BL1_HANDOFF_DETAIL_MAGIC);
    }
    if (state->size != sizeof(*state)) return fail(detail, BL1_HANDOFF_DETAIL_SIZE);
    if (state->error_code != 0u) return fail(detail, BL1_HANDOFF_DETAIL_BL0_ERROR);
    if (state->boot_mode != BOOT_MODE_SPI && state->boot_mode != BOOT_MODE_RECOVERY &&
        state->boot_mode != BOOT_MODE_SECONDARY) {
        return fail(detail, BL1_HANDOFF_DETAIL_BOOT_MODE);
    }
    if (state->sep_sram_manifest_addr != BL1_SEP_SRAM_MANIFEST_ADDR) {
        return fail(detail, BL1_HANDOFF_DETAIL_MANIFEST_ADDR);
    }

    // The SEP ROM stages the payload immediately after the body, 8-byte aligned.
    oca_manifest_peek_t pk;
    if (oca_peek_manifest(body, sram_bytes, &pk) != OCA_OK || pk.body_size > sram_bytes) {
        return fail(detail, BL1_HANDOFF_DETAIL_MANIFEST);
    }
    const uint32_t payload_off = (uint32_t)((pk.body_size + 7u) & ~(size_t)7u);
    if (payload_off >= sram_bytes) return fail(detail, BL1_HANDOFF_DETAIL_PAYLOAD);

    oca_toc_info_t toc;
    if (oca_toc_info(body + payload_off, sram_bytes - payload_off, &toc) != OCA_OK ||
        toc.payload_length > sram_bytes - payload_off) {
        return fail(detail, BL1_HANDOFF_DETAIL_PAYLOAD);
    }

    const uint32_t payload_addr = state->sep_sram_manifest_addr + payload_off;
    const uint32_t payload_len = (uint32_t)toc.payload_length;
    if (state->bl1_image_src_addr < payload_addr ||
        state->bl1_image_src_addr - payload_addr >= payload_len) {
        return fail(detail, BL1_HANDOFF_DETAIL_BL1_SOURCE);
    }

    out->manifest_addr = state->sep_sram_manifest_addr;
    out->payload_addr = payload_addr;
    out->payload_len = payload_len;
    out->payload = body + payload_off;
    return BL1_OK;
}
