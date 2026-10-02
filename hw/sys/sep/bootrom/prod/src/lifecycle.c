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
    uint32_t reg = mmio_read32(SEP_TOP_SEP_EFUSE_MAP_LC_STATE_BASE_ADDR);
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
    //   0x6-0x7: RMA_CHIPLET (4'b011?)
    //   0x8:     PROD_END
    // Everything else is INVALID to the LCC.
    switch (lc_state) {
    case LC_STATE_TEST_DEV:
    case LC_STATE_PROD:
    case LC_STATE_RMA_SIP_LO:
    case LC_STATE_RMA_SIP_HI:
    case LC_STATE_RMA_CHIPLET_LO:
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
    switch (lc_state) {
    case LC_STATE_RMA_SIP_LO:
    case LC_STATE_RMA_SIP_HI:
    case LC_STATE_RMA_CHIPLET_LO:
    case LC_STATE_RMA_CHIPLET_HI:
        return true;
    default:
        return false;
    }
}

// ---------------------------------------------------------------------------
// Feature control and demotion registers
// ---------------------------------------------------------------------------

uint32_t lc_read_feat_ctrl(uint32_t *hi) {
    // FEAT_CTRL is a 64-bit read-only register.
    // Read low 32 bits, then high 32 bits.
    uint32_t lo = mmio_read32(SEP_TOP_SEP_LIFECYCLE_CTRL_FEAT_CTRL_BASE_ADDR);
    if (hi) {
        *hi = mmio_read32(SEP_TOP_SEP_LIFECYCLE_CTRL_FEAT_CTRL_BASE_ADDR + 4u);
    }
    return lo;
}

void lc_write_demotion(bool demote, bool lock) {
    uint32_t val = 0;
    if (demote) val |= SEP_LIFECYCLE_CTRL__DEMOTE__DEMOTE_bm;
    if (lock) val |= SEP_LIFECYCLE_CTRL__DEMOTE__LOCK_bm;
    mmio_write32(SEP_TOP_SEP_LIFECYCLE_CTRL_DEMOTE_1_BASE_ADDR, val);
}

void lc_write_demotion_2(bool demote, bool lock) {
    uint32_t val = 0;
    if (demote) val |= SEP_LIFECYCLE_CTRL__DEMOTE__DEMOTE_bm;
    if (lock) val |= SEP_LIFECYCLE_CTRL__DEMOTE__LOCK_bm;
    mmio_write32(SEP_TOP_SEP_LIFECYCLE_CTRL_DEMOTE_2_BASE_ADDR, val);
}

// ---------------------------------------------------------------------------
// Full lifecycle policy ([S11])
// ---------------------------------------------------------------------------

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
        uint32_t reset_ctrl = sep_get_smc_base() + SMC_CPU_CTRL_RESET_CTRL_OFFSET;
        uint32_t rst = mmio_read32(reset_ctrl);
        mmio_write32(reset_ctrl, rst & ~SMC_CPU_CTRL_RESET_CTRL_CORE_RESET_N_MASK);
        simputs("SMC_RESET_ON_INVALID_LC\n");
        // Diagnostic only: the halt below happens either way. A core bit that
        // reads back set means that core is still running.
        rst = mmio_read32(reset_ctrl);
        if ((rst & SMC_CPU_CTRL_RESET_CTRL_CORE_RESET_N_MASK) != 0u) {
            simputshex32("SMC_RESET_NOT_HELD=", rst);
        }

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
    case LC_STATE_RMA_CHIPLET_LO:
    case LC_STATE_RMA_CHIPLET_HI:
        simputs("LC=RMA_CHIPLET\n");
        break;
    default:
        break;
    }

    report_status(STATUS_TYPE_INFO, SEP_MSG_LIFECYCLE_VALID);
    return lc_state;
}

// ---------------------------------------------------------------------------
// Secure-boot chicken bit ([S18])
// ---------------------------------------------------------------------------

// Latched by rom_sboot_dis_policy(). Zero-initialised, and zero reports "not
// disabled", so a caller that runs before [S18] enforces secure boot.
static bool g_sboot_dis;

bool sboot_dis_disabled(void) {
    return g_sboot_dis;
}

void rom_sboot_dis_policy(void) {
    uint32_t reg = mmio_read32(SEP_TOP_SEP_EFUSE_MAP_SBOOT_DIS_BASE_ADDR);

    // rsvd[31:1] is hw=rw in the RDL: driven from the fuse array rather than
    // tied off, so it can read non-zero on a real part. On a healthy one it
    // reads zero, and anything else means the array is not what the ROM thinks
    // it is -- a state to stop in, not to interpret.
    if ((reg & SEP_EFUSE_MAP__SBOOT_DIS__RSVD_bm) != 0u) {
        simputshex32("SBOOT_DIS_RSVD=", reg);
        report_status(STATUS_TYPE_ERROR, SEP_MSG_FUSE_SBOOT_DIS_RSVD);
        rom_err_fail_ext(ROM_ERR_SBOOT_DIS_RSVD_SET);
    }

    g_sboot_dis = (reg & SEP_EFUSE_MAP__SBOOT_DIS__DISABLE_SECURE_BOOT_bm) != 0u;
    get_bl0_state()->sboot_dis = g_sboot_dis;

    simputsdec24("FUSE: SBOOT_DIS: ", g_sboot_dis);
    report_status(STATUS_TYPE_INFO, SEP_MSG_FUSE_SBOOT_DIS);
    report_status(STATUS_TYPE_INFO_EXT, g_sboot_dis);
}

// ---------------------------------------------------------------------------
// Chiplet debug lock ([S18])
// ---------------------------------------------------------------------------

// Latched by rom_chiplet_dbg_policy() as "debug open", so that the
// zero-initialised value reads as disabled and a caller that runs before [S18]
// enforces secure boot.
static bool g_chiplet_dbg_open;

bool chiplet_debug_disabled(void) {
    return !g_chiplet_dbg_open;
}

void rom_chiplet_dbg_policy(uint32_t lc_state) {
    // The raw fuse shadows rather than FEAT_CTRL: SEC_DIS and TEST_DEV demotion
    // both force FEAT_CTRL bits to 1, which would read as "debug enabled" on a
    // part whose fuses disable it.
    //
    // A read-locked field returns a sentinel instead of its value, so a lock on
    // either vector means the ROM cannot see that debug is open.
    uint32_t locks = mmio_read32(SEP_TOP_SEP_EFUSE_MAP_LOCKS_BASE_ADDR);
    bool disabled = (locks & (SEP_EFUSE_MAP__LOCKS__SIP_DIS_READ_LOCK_bm |
                              SEP_EFUSE_MAP__LOCKS__SYS_DIS_READ_LOCK_bm)) != 0u;
    if (!disabled) {
        // CHIPLET_DBG is in the low word of each 64-bit vector.
        uint32_t sip = mmio_read32(SEP_TOP_SEP_EFUSE_MAP_SIP_DIS_BASE_ADDR);
        uint32_t sys = mmio_read32(SEP_TOP_SEP_EFUSE_MAP_SYS_DIS_BASE_ADDR);
        disabled = ((sip | sys) & SEP_EFUSE_MAP__LC_DISABLE__CHIPLET_DBG_bm) != 0u;
    }
    g_chiplet_dbg_open = !disabled;

    simputsdec24("FUSE: CHIPLET_DBG_DIS: ", disabled);

    // Reported only where the lock is what the device's enforcement rests on:
    // PROD and PROD_END enforce regardless, and SBOOT_DIS overrides it.
    if (disabled && lc_state == LC_STATE_TEST_DEV && !sboot_dis_disabled()) {
        simputs("SBOOT_DBG_LOCK\n");
        report_status(STATUS_TYPE_INFO, SEP_MSG_SBOOT_DBG_LOCK);
    }
}
