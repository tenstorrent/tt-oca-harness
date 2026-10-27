/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

// Re-derivation of the secure-boot state, compared against what the SEP ROM recorded.

#pragma once

#include <stdint.h>

#include "bl1_result.h"
#include "oca_validator.h"

// What the SEP ROM recorded in bl0_state, widened to words.
struct bl1_secure_record {
    uint32_t secure_boot;
    uint32_t sboot_dis;
    uint32_t lc_state;
};

// Live inputs. cb supplies the device reporters the manifest validator's precedence consults;
// the remaining fields are raw register values.
struct bl1_secure_live {
    const uint8_t *manifest_body; // the validated manifest in SEP SRAM
    const oca_callbacks_t *cb;
    uint32_t sboot_dis_word; // SBOOT_DIS fuse shadow, whole word
    uint32_t lc_state;       // SEP lifecycle state, 4-bit
    uint32_t smc_lc_raw;     // SMC CHIP_CONFIG.LC_STATE, 8-bit differential encoding
    uint32_t feat_ctrl_lo;   // SEP FEAT_CTRL[31:0]
};

// Which input disagreed, reported as the detail of SEP_BL1_ERR_SECURE_STATE_MISMATCH.
enum {
    BL1_SECURE_DETAIL_VERDICT = 1u,
    BL1_SECURE_DETAIL_SBOOT_DIS = 2u,
    BL1_SECURE_DETAIL_SBOOT_DIS_RSVD = 3u,
    BL1_SECURE_DETAIL_LIFECYCLE = 4u,
    BL1_SECURE_DETAIL_SMC_LIFECYCLE = 5u,
};

// FEAT_CTRL bits that together leave the SMC JTAG-to-AXI bridge open.
#define BL1_FEAT_CTRL_CHIPLET_DBG (1u << 1)
#define BL1_FEAT_CTRL_SIP_DEBUG (1u << 24)

// Returns BL1_OK when every live input agrees with the record, otherwise
// SEP_BL1_ERR_SECURE_STATE_MISMATCH with *detail naming the input. On BL1_OK, sets
// BL1_WARN_NOT_SECURE, BL1_WARN_LIFECYCLE and BL1_WARN_DEMOTED in *warnings as they apply.
bl1_result_t bl1_check_secure_state(const struct bl1_secure_record *rec,
                                    const struct bl1_secure_live *live, uint32_t *detail,
                                    uint32_t *warnings);
