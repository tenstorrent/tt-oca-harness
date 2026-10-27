/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

#include "bl1_zones.h"

#include "oca_validator.h"
#include "sep_bl1_status.h"
#include "smu_bl1_contract.h"

static int is_smc_bl1_type(const char type[17]) {
    static const char want[] = SMU_BL1_SMC_IMAGE_TYPE;
    for (unsigned i = 0; i < sizeof want; i++) {
        if (type[i] != want[i]) return 0;
    }
    return 1;
}

bl1_result_t bl1_find_smc_image(const uint8_t *payload, size_t payload_len,
                                struct bl1_image_desc *out) {
    oca_toc_info_t toc;
    if (oca_toc_info(payload, payload_len, &toc) != OCA_OK) return SEP_BL1_ERR_SMC_IMAGE_MISSING;

    uint32_t found = 0;
    for (uint64_t i = 0; i < toc.image_count; i++) {
        oca_image_info_t img;
        if (oca_toc_image_at(payload, payload_len, i, &img) != OCA_OK) {
            return SEP_BL1_ERR_SMC_IMAGE_MISSING;
        }
        if (!is_smc_bl1_type(img.type)) continue;
        if (found++ == 0u) {
            out->load_addr = img.load_addr;
            out->length = img.length;
            out->entry_point = img.entry_point;
            out->bytes = img.bytes;
            out->hash = img.hash;
        }
    }
    if (found == 0u) return SEP_BL1_ERR_SMC_IMAGE_MISSING;
    if (found != 1u) return SEP_BL1_ERR_SMC_IMAGE_DUPLICATE;
    return BL1_OK;
}

bl1_result_t bl1_check_smc_image(const struct bl1_image_desc *img) {
    const uint64_t load = img->load_addr;
    const uint64_t len = img->length;
    const uint64_t entry = img->entry_point;

    if (len == 0u || (len & 3u) != 0u || (load >> 32) != 0u || (load & 7u) != 0u ||
        len > UINT64_MAX - load) {
        return SEP_BL1_ERR_SMC_IMAGE_RANGE;
    }
    if (entry >= len || (entry & 3u) != 0u) return SEP_BL1_ERR_SMC_IMAGE_ENTRY;
    if (load < SMU_BL1_IMAGE_WINDOW_START || load + len > SMU_BL1_IMAGE_WINDOW_END) {
        return SEP_BL1_ERR_SMC_IMAGE_ZONE;
    }
    return BL1_OK;
}

bl1_result_t bl1_check_smc_zone(const struct bl1_smc_zone_regs *regs, uint32_t *warnings) {
    if ((regs->status_lo & SMU_BL1_STATUS_SRAM_INIT) == 0u) {
        return SEP_BL1_ERR_SMC_ZONE_UNPUBLISHED;
    }
    if (regs->start_off_hi != 0u || regs->size_hi != 0u || regs->size_lo == 0u) {
        return SEP_BL1_ERR_SMC_ZONE_INVALID;
    }
    const uint64_t start = (uint64_t)SMU_BL1_SMC_SRAM_BASE + regs->start_off_lo;
    const uint64_t end = start + regs->size_lo;
    if (end > (uint64_t)SMU_BL1_SMC_SRAM_BASE + SMU_BL1_SMC_SRAM_SIZE) {
        return SEP_BL1_ERR_SMC_ZONE_INVALID;
    }
    if (SMU_BL1_SEP_ZONE_START < start || SMU_BL1_SEP_ZONE_END > end) {
        return SEP_BL1_ERR_SMC_ZONE_TOO_SMALL;
    }
    if (start != SMU_BL1_SEP_ZONE_START || end != SMU_BL1_SEP_ZONE_END) {
        *warnings |= BL1_WARN_ZONE_MISMATCH;
    }
    return BL1_OK;
}
