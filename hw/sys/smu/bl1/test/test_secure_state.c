/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

#include <stdint.h>
#include <string.h>

#include "bl1_secure_state.h"
#include "lifecycle.h"
#include "oca_layout.h"
#include "sep_bl1_status.h"
#include "unit.h"

// Device reporters for the validator's secure-boot precedence.
static oca_secure_bool_t fake_active;
static oca_secure_bool_t fake_disabled;
static oca_secure_bool_t report_active(void) {
    return fake_active;
}
static oca_secure_bool_t report_disabled(void) {
    return fake_disabled;
}

static uint8_t body[1024];
static oca_callbacks_t cb;

static uint32_t smc_lc(uint32_t lc) {
    return ((~lc & 0xFu) << 4) | (lc & 0xFu);
}

struct scenario {
    int manifest_enforced;
    oca_secure_bool_t active, disabled;
    struct bl1_secure_record rec;
    struct bl1_secure_live live;
};

static bl1_result_t run(struct scenario *s, uint32_t *detail, uint32_t *warn) {
    memset(body, 0, sizeof body);
    body[OCA_OFF_SECURE_BOOT_CONTROL] = s->manifest_enforced ? OCA_SECURE_BOOT_ENFORCED_BIT : 0u;
    memset(&cb, 0, sizeof cb);
    cb.is_secure_boot_active = report_active;
    cb.is_secure_boot_disabled = report_disabled;
    fake_active = s->active;
    fake_disabled = s->disabled;
    s->live.manifest_body = body;
    s->live.cb = &cb;
    *detail = 0;
    *warn = 0;
    return bl1_check_secure_state(&s->rec, &s->live, detail, warn);
}

static struct scenario prod_secure(void) {
    struct scenario s = {
        .manifest_enforced = 1,
        .active = OCA_SECURE_TRUE,
        .disabled = OCA_SECURE_FALSE,
        .rec = {.secure_boot = 1, .sboot_dis = 0, .lc_state = LC_STATE_PROD},
        .live = {.sboot_dis_word = 0,
                 .lc_state = LC_STATE_PROD,
                 .smc_lc_raw = smc_lc(LC_STATE_PROD),
                 .feat_ctrl_lo = 0},
    };
    return s;
}

static struct scenario test_dev_open(void) {
    struct scenario s = {
        .manifest_enforced = 0,
        .active = OCA_SECURE_FALSE,
        .disabled = OCA_SECURE_FALSE,
        .rec = {.secure_boot = 0, .sboot_dis = 0, .lc_state = LC_STATE_TEST_DEV},
        .live = {.sboot_dis_word = 0,
                 .lc_state = LC_STATE_TEST_DEV,
                 .smc_lc_raw = smc_lc(LC_STATE_TEST_DEV),
                 .feat_ctrl_lo = BL1_FEAT_CTRL_CHIPLET_DBG | BL1_FEAT_CTRL_SIP_DEBUG},
    };
    return s;
}

void test_secure_state(void) {
    uint32_t detail, warn;
    struct scenario s;

    s = prod_secure();
    CHECK_EQ(run(&s, &detail, &warn), BL1_OK);
    CHECK_EQ(warn, 0u);

    s = test_dev_open();
    CHECK_EQ(run(&s, &detail, &warn), BL1_OK);
    CHECK_EQ(warn, BL1_WARN_NOT_SECURE | BL1_WARN_LIFECYCLE);

    s = prod_secure();
    s.live.feat_ctrl_lo = BL1_FEAT_CTRL_CHIPLET_DBG | BL1_FEAT_CTRL_SIP_DEBUG;
    CHECK_EQ(run(&s, &detail, &warn), BL1_OK);
    CHECK_EQ(warn, BL1_WARN_DEMOTED);

    // SBOOT_DIS in PROD, with a manifest that does not enforce secure boot.
    s = prod_secure();
    s.manifest_enforced = 0;
    s.disabled = OCA_SECURE_TRUE;
    s.rec.secure_boot = 0;
    s.rec.sboot_dis = 1;
    s.live.sboot_dis_word = 1;
    CHECK_EQ(run(&s, &detail, &warn), BL1_OK);
    CHECK_EQ(warn, BL1_WARN_NOT_SECURE);

    // Each input disagreeing in turn.
    s = prod_secure();
    s.rec.secure_boot = 0;
    CHECK_EQ(run(&s, &detail, &warn), SEP_BL1_ERR_SECURE_STATE_MISMATCH);
    CHECK_EQ(detail, BL1_SECURE_DETAIL_VERDICT);

    s = test_dev_open();
    s.rec.secure_boot = 1;
    CHECK_EQ(run(&s, &detail, &warn), SEP_BL1_ERR_SECURE_STATE_MISMATCH);
    CHECK_EQ(detail, BL1_SECURE_DETAIL_VERDICT);

    s = prod_secure();
    s.live.sboot_dis_word = 1;
    CHECK_EQ(run(&s, &detail, &warn), SEP_BL1_ERR_SECURE_STATE_MISMATCH);
    CHECK_EQ(detail, BL1_SECURE_DETAIL_SBOOT_DIS);

    s = prod_secure();
    s.live.sboot_dis_word = 0x2;
    CHECK_EQ(run(&s, &detail, &warn), SEP_BL1_ERR_SECURE_STATE_MISMATCH);
    CHECK_EQ(detail, BL1_SECURE_DETAIL_SBOOT_DIS_RSVD);

    s = prod_secure();
    s.live.lc_state = LC_STATE_PROD_END;
    CHECK_EQ(run(&s, &detail, &warn), SEP_BL1_ERR_SECURE_STATE_MISMATCH);
    CHECK_EQ(detail, BL1_SECURE_DETAIL_LIFECYCLE);

    s = prod_secure();
    s.live.smc_lc_raw = smc_lc(LC_STATE_TEST_DEV);
    CHECK_EQ(run(&s, &detail, &warn), SEP_BL1_ERR_SECURE_STATE_MISMATCH);
    CHECK_EQ(detail, BL1_SECURE_DETAIL_SMC_LIFECYCLE);

    s = prod_secure();
    s.live.smc_lc_raw = 0x11; // not a valid differential encoding
    CHECK_EQ(run(&s, &detail, &warn), SEP_BL1_ERR_SECURE_STATE_MISMATCH);
    CHECK_EQ(detail, BL1_SECURE_DETAIL_SMC_LIFECYCLE);

    // A reporter answering with an unrecognised value leaves secure boot enforced.
    s = test_dev_open();
    s.active = 0x12345678u;
    CHECK_EQ(run(&s, &detail, &warn), SEP_BL1_ERR_SECURE_STATE_MISMATCH);
    CHECK_EQ(detail, BL1_SECURE_DETAIL_VERDICT);
}
