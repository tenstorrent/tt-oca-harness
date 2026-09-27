/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

// Lifecycle controller implementation for OROM.
//
// Reads LC_STATE from efuse shadow register, validates against the
// allowed set defined in RTL (sep_lifecycle_ctrl.sv), and integrates
// with the boot flow.
//
// Also provides demotion register access and FEAT_CTRL reading.

#include "lifecycle.h"

#include <stdbool.h>
#include <stdint.h>

#include "bl0_state.h"
#include "errors.h"
#include "rom_mmio.h"
#include "rom_virt_console.h"
#include "sep.h"
#include "sep_smc_interface.h"

// ---------------------------------------------------------------------------
// LC state read helper.
// ---------------------------------------------------------------------------

uint32_t lc_read_state(void) {
    uint32_t reg = mmio_read32(OCH_SEP_TOP_SEP_EFUSE_MAP_LC_STATE_BASE_ADDR);
    // The eFuse field is 8 bits, differentially encoded by the RTL; the low
    // nibble carries the decoded lifecycle state.
    return ((reg & SEP_EFUSE_MAP__LC_STATE__LC_STATE_bm) >> SEP_EFUSE_MAP__LC_STATE__LC_STATE_bp) &
           0xFu;
}

// ---------------------------------------------------------------------------
// LC state classification
// ---------------------------------------------------------------------------

bool lc_state_is_valid(uint32_t lc_state) {
    // Valid states (from RTL sep_lifecycle_ctrl.sv case statements):
    //   0x0:     TEST_DEV
    //   0x1:     PROD
    //   0x2-0x3: RMA_SiP   (4'b001?)
    //   0x4-0x7: RMA_CHIPLET (4'b01??)
    //   0x8:     PROD_END
    switch (lc_state) {
    case LC_STATE_TEST_DEV:
    case LC_STATE_PROD:
    case LC_STATE_RMA_SIP_LO:
    case LC_STATE_RMA_SIP_HI:
    case LC_STATE_RMA_CHIPLET_LO:
    case 0x5u:
    case 0x6u:
    case LC_STATE_RMA_CHIPLET_HI:
    case LC_STATE_PROD_END:
        return true;
    default:
        return false;
    }
}

bool lc_state_enforces_secure_boot(uint32_t lc_state) {
    // PROD and PROD_END enforce secure boot.
    // TEST_DEV and RMA states do not (debug/manufacturing).
    return (lc_state == LC_STATE_PROD || lc_state == LC_STATE_PROD_END);
}

bool lc_state_is_rma(uint32_t lc_state) {
    return (lc_state >= LC_STATE_RMA_SIP_LO && lc_state <= LC_STATE_RMA_CHIPLET_HI);
}

// ---------------------------------------------------------------------------
// Feature control and demotion registers
// ---------------------------------------------------------------------------

uint32_t lc_read_feat_ctrl(uint32_t *hi) {
    // FEAT_CTRL is a 64-bit read-only register.
    // Read low 32 bits, then high 32 bits.
    uint32_t lo = mmio_read32(OCH_SEP_TOP_SEP_LIFECYCLE_CTRL_FEAT_CTRL_BASE_ADDR);
    if (hi) {
        *hi = mmio_read32(OCH_SEP_TOP_SEP_LIFECYCLE_CTRL_FEAT_CTRL_BASE_ADDR + 4u);
    }
    return lo;
}

void lc_write_demotion(bool demote, bool lock) {
    uint32_t val = 0;
    if (demote) val |= SEP_LIFECYCLE_CTRL__DEMOTE__DEMOTE_bm;
    if (lock) val |= SEP_LIFECYCLE_CTRL__DEMOTE__LOCK_bm;
    mmio_write32(OCH_SEP_TOP_SEP_LIFECYCLE_CTRL_DEMOTE_1_BASE_ADDR, val);
}

void lc_write_demotion_2(bool demote, bool lock) {
    uint32_t val = 0;
    if (demote) val |= SEP_LIFECYCLE_CTRL__DEMOTE__DEMOTE_bm;
    if (lock) val |= SEP_LIFECYCLE_CTRL__DEMOTE__LOCK_bm;
    mmio_write32(OCH_SEP_TOP_SEP_LIFECYCLE_CTRL_DEMOTE_2_BASE_ADDR, val);
}

// ---------------------------------------------------------------------------
// Full lifecycle policy ([S11])
// ---------------------------------------------------------------------------

// Error code for lifecycle validation failure.
#define ROM_ERR_LIFECYCLE_INVALID 0x0000A002u

// Forward declaration (defined in rom_main.c).
__attribute__((noreturn)) extern void rom_err_fail_ext(uint32_t error_code);

uint32_t rom_lifecycle_policy(void) {
    report_status(STATUS_TYPE_INFO, SEP_MSG_FUSE_LC_STATE);

    // ── Step 1: Read LC_STATE from efuse shadow register ──
    // Signal integrity is checked by RTL (prim_diff_decode_multi);
    // firmware just reads the raw 4-bit state.
    uint32_t lc_state = lc_read_state();

    simputshex32("LC_STATE=", lc_state);
    report_status(STATUS_TYPE_INFO_EXT, lc_state);

    // ── Step 2: Validate LC state is in allowed set ──
    if (!lc_state_is_valid(lc_state)) {
        simputshex32("LC_STATE_INVALID=", lc_state);
        report_status(STATUS_TYPE_ERROR, SEP_MSG_LIFECYCLE_INVALID);

        // Put SMC in reset to make the whole SMU inoperative.
        // Invalid LC_STATE may indicate fuse attack or HW fault — do not let
        // SMC continue running in an unknown state.
        uint32_t smc_base = sep_get_smc_base();
        uint32_t rst = mmio_read32(smc_base + SMC_CPU_CTRL_RESET_CTRL_OFFSET);
        rst &= ~(uint32_t)SMC_CPU_CTRL_RESET_CTRL_CORE_MASK;
        mmio_write32(smc_base + SMC_CPU_CTRL_RESET_CTRL_OFFSET, rst);
        simputshex32("SMC_RESET_ON_INVALID_LC=", rst);

        rom_err_fail_ext(ROM_ERR_LIFECYCLE_INVALID);
    }

    // ── Step 4: Record in bl0_state for BL1 consumption ──
    get_bl0_state()->lc_state = lc_state;

    // ── Step 5: Read and report FEAT_CTRL ──
    {
        uint32_t feat_hi = 0;
        uint32_t feat_lo = lc_read_feat_ctrl(&feat_hi);
        get_bl0_state()->feat_ctrl_lo = feat_lo;
        get_bl0_state()->feat_ctrl_hi = feat_hi;
        simputshex32("FEAT_CTRL_LO=", feat_lo);
        simputshex32("FEAT_CTRL_HI=", feat_hi);
    }

    // ── Step 6: Log state name ──
    switch (lc_state) {
    case LC_STATE_TEST_DEV:
        simputs("LC=TEST_DEV\n");
        break;
    case LC_STATE_PROD:
        simputs("LC=PROD\n");
        break;
    case LC_STATE_PROD_END:
        simputs("LC=PROD_END\n");
        break;
    case LC_STATE_RMA_SIP_LO:
    case LC_STATE_RMA_SIP_HI:
        simputs("LC=RMA_SIP\n");
        break;
    default:
        if (lc_state >= LC_STATE_RMA_CHIPLET_LO && lc_state <= LC_STATE_RMA_CHIPLET_HI) {
            simputs("LC=RMA_CHIPLET\n");
        }
        break;
    }

    report_status(STATUS_TYPE_INFO, SEP_MSG_LIFECYCLE_VALID);
    return lc_state;
}
