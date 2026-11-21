/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

// The challenge and confirmation on SEP mailbox 0's inbound port, reached through the SEP
// aperture. Only an SMC outbound-filter entry is programmed: the SMC inbound filter, DMA and
// log engine stay at reset.

#include "axil_mailbox.h"
#include "filter_ctrl.h"
#include "sep_addr.h"
#include "smc_addr.h"
#include "smc_bl1.h"

#define SEP_VIA_APERTURE(sep_addr) ((uintptr_t)SMU_BL1_SEP_APERTURE + (sep_addr))
#define MBOX_WRITE_DATA \
    SEP_VIA_APERTURE(SEP_TOP_AXIL_MAILBOX_INBOUND_MAILBOX_0_WRITE_DATA_BASE_ADDR)
#define MBOX_READ_DATA SEP_VIA_APERTURE(SEP_TOP_AXIL_MAILBOX_INBOUND_MAILBOX_0_READ_DATA_BASE_ADDR)
#define MBOX_STATUS SEP_VIA_APERTURE(SEP_TOP_AXIL_MAILBOX_INBOUND_MAILBOX_0_STATUS_BASE_ADDR)

#define OUTBOUND_FILTER_ENTRY 0
#define OUTBOUND_FILTER_START \
    SMC_TOP_SMC_OUTBOUND_FILTER_CTRL_WRAP_FILTER_CTRL_START_ADDR_BASE_ADDR(OUTBOUND_FILTER_ENTRY)
#define OUTBOUND_FILTER_END \
    SMC_TOP_SMC_OUTBOUND_FILTER_CTRL_WRAP_FILTER_CTRL_END_ADDR_BASE_ADDR(OUTBOUND_FILTER_ENTRY)
#define OUTBOUND_FILTER_CONFIG_REG \
    SMC_TOP_SMC_OUTBOUND_FILTER_CTRL_WRAP_FILTER_CTRL_FILTER_CONFIG_BASE_ADDR(OUTBOUND_FILTER_ENTRY)
#define OUTBOUND_FILTER_SRC_ID 3u
#define OUTBOUND_FILTER_CONFIG \
    (FILTER_CTRL__FILTER_CONFIG__READ_ALLOWED_bm | FILTER_CTRL__FILTER_CONFIG__WRITE_ALLOWED_bm | \
     FILTER_CTRL__FILTER_CONFIG__ENTRY_ENABLED_bm | \
     ((uint64_t)FILTER_CTRL__FILTER_CONFIG__DATA_BUS_WIDTH_reset \
      << FILTER_CTRL__FILTER_CONFIG__DATA_BUS_WIDTH_bp) | \
     ((uint64_t)OUTBOUND_FILTER_SRC_ID << FILTER_CTRL__FILTER_CONFIG__SRC_ID_bp))

// The SEP pushes the challenge right after it releases hart 0, so the wait is short; the
// bound only stops a missing SEP from hanging hart 0 before it parks.
#define MBOX_POLL_LIMIT 1000000u

static void open_path(void) {
    // The window bounds go in before the configuration enables the entry.
    smc_bl1_wr64(OUTBOUND_FILTER_START, SEP_VIA_APERTURE(SMU_BL1_MBOX_INBOUND));
    smc_bl1_wr64(OUTBOUND_FILTER_END, SEP_VIA_APERTURE(SMU_BL1_MBOX_INBOUND_END) - 1u);
    smc_bl1_wr64(OUTBOUND_FILTER_CONFIG_REG, OUTBOUND_FILTER_CONFIG);
    __asm__ volatile("fence" ::: "memory");
}

static int pop(uint32_t *word) {
    for (uint32_t i = 0; i < MBOX_POLL_LIMIT; ++i) {
        if ((smc_bl1_rd32(MBOX_STATUS) & AXIL_MAILBOX__STATUS__EMPTY_bm) == 0u) {
            *word = smc_bl1_rd32(MBOX_READ_DATA);
            return 1;
        }
    }
    return 0;
}

static uint32_t take_challenge(uint32_t challenge[2]) {
    uint32_t tag;

    if (!pop(&tag)) return SMC_BL1_ERR_NO_CHALLENGE;
    if (tag != SMU_BL1_TAG_SEP) return SMC_BL1_ERR_BAD_TAG;
    if (!pop(&challenge[0]) || !pop(&challenge[1])) return SMC_BL1_ERR_NO_CHALLENGE;
    return 0;
}

uint32_t smc_bl1_receive_challenge(uint32_t challenge[2]) {
    smc_bl1_ring_init();
    smc_bl1_post(SMC_BL1_STARTED);
    open_path();
    smc_bl1_post(SMC_BL1_PATH_OK);
    uint32_t err = take_challenge(challenge);
    smc_bl1_post(err != 0u ? err : SMC_BL1_CHALLENGE_OK);
    return err;
}

void smc_bl1_send_confirmation(uint32_t tag, const uint32_t challenge[2]) {
    smc_bl1_wr32(MBOX_WRITE_DATA, tag);
    smc_bl1_wr32(MBOX_WRITE_DATA, challenge[0]);
    smc_bl1_wr32(MBOX_WRITE_DATA, challenge[1]);
    __asm__ volatile("fence" ::: "memory");
}
