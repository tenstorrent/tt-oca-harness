/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

#include "bl1_secure_state.h"

#include "harden.h"
#include "lifecycle.h"
#include "sep_bl1_status.h"

static bl1_result_t mismatch(uint32_t *detail, uint32_t which) {
    *detail = which;
    return SEP_BL1_ERR_SECURE_STATE_MISMATCH;
}

// The SMC receives the SEP lifecycle as {~lc, lc}; anything else is not a lifecycle.
static int smc_lc_matches(uint32_t raw, uint32_t lc) {
    uint32_t low = raw & 0xFu;
    uint32_t high = (raw >> 4) & 0xFu;
    return (raw >> 8) == 0u && high == (~low & 0xFu) && low == lc;
}

static int lc_enforces_secure_boot(uint32_t lc) {
    return lc == LC_STATE_PROD || lc == LC_STATE_PROD_END;
}

bl1_result_t bl1_check_secure_state(const struct bl1_secure_record *rec,
                                    const struct bl1_secure_live *live, uint32_t *detail,
                                    uint32_t *warnings) {
    if ((live->sboot_dis_word & ~1u) != 0u)
        return mismatch(detail, BL1_SECURE_DETAIL_SBOOT_DIS_RSVD);

    const uint32_t sboot_dis = live->sboot_dis_word & 1u;
    if (sboot_dis != (rec->sboot_dis != 0u) ||
        harden_u32(sboot_dis) != (harden_u32(rec->sboot_dis) != 0u)) {
        return mismatch(detail, BL1_SECURE_DETAIL_SBOOT_DIS);
    }

    if (live->lc_state != rec->lc_state ||
        harden_u32(live->lc_state) != harden_u32(rec->lc_state)) {
        return mismatch(detail, BL1_SECURE_DETAIL_LIFECYCLE);
    }

    if (!smc_lc_matches(live->smc_lc_raw, live->lc_state) ||
        !smc_lc_matches(harden_u32(live->smc_lc_raw), harden_u32(live->lc_state))) {
        return mismatch(detail, BL1_SECURE_DETAIL_SMC_LIFECYCLE);
    }

    // Test for the pattern that selects the less defensive answer, so a corrupted verdict can
    // only read as enforced. Ask twice: the precedence re-reads the device reporters.
    const uint32_t not_secure =
        oca_secure_boot_active(live->manifest_body, live->cb) == OCA_SECURE_FALSE;
    const uint32_t not_secure2 =
        harden_u32(oca_secure_boot_active(live->manifest_body, live->cb)) == OCA_SECURE_FALSE;
    const uint32_t recorded_secure = rec->secure_boot != 0u;
    if (not_secure != not_secure2 || not_secure == recorded_secure ||
        harden_u32(not_secure2) == harden_u32(recorded_secure)) {
        return mismatch(detail, BL1_SECURE_DETAIL_VERDICT);
    }

    if (not_secure) *warnings |= BL1_WARN_NOT_SECURE;
    if (!lc_enforces_secure_boot(live->lc_state)) {
        *warnings |= BL1_WARN_LIFECYCLE;
    } else if ((live->feat_ctrl_lo & BL1_FEAT_CTRL_CHIPLET_DBG) != 0u &&
               (live->feat_ctrl_lo & BL1_FEAT_CTRL_SIP_DEBUG) != 0u) {
        *warnings |= BL1_WARN_DEMOTED;
    }
    return BL1_OK;
}
