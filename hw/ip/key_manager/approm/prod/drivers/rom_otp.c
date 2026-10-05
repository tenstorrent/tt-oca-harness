/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/* Copyright 2026 Tenstorrent Inc. */
/**
 * @file rom_otp.c
 * @brief OTP readout driver implementation for Key Manager ROM firmware.
 */

#include "rom_otp.h"
#include "rom_defs.h"

/*---------------------------------------------------------------------------
 * Helpers
 *---------------------------------------------------------------------------*/

/**
 * @brief Read 8 value words and 8 complement words from a dual-rail KMCSR
 *        OTP field, verify dual-rail integrity, and copy decoded value.
 *
 * @param val_base  Byte address of VAL_0 register.
 * @param cpl_base  Byte address of CPL_0 register.
 * @param out       Output buffer (8 words).
 * @return 0 on success, -1 on integrity failure.
 */
static int otp_dr_read(uint32_t val_base, uint32_t cpl_base, uint32_t out[ROM_KM_OTP_WORDS]) {
    volatile uint32_t *val_regs = (volatile uint32_t *)val_base;
    volatile uint32_t *cpl_regs = (volatile uint32_t *)cpl_base;
    int ok = 1;

    for (int i = 0; i < ROM_KM_OTP_WORDS; i++) {
        uint32_t v = val_regs[i];
        uint32_t c = cpl_regs[i];
        if (v != ~c) ok = 0;
        out[i] = v;
    }

    if (!ok) {
        for (int i = 0; i < ROM_KM_OTP_WORDS; i++) out[i] = 0;
        return -1;
    }
    return 0;
}

/*---------------------------------------------------------------------------
 * Life-cycle and demotion readers (dual-rail: decode + integrity verify)
 *
 * life_cycle is a 4-bit value differentially encoded into 8 bits
 * ({~lc[3:0], lc[3:0]}); demotion packs two 1-bit values, each differentially
 * encoded into 2 bits ({~d, d}).  These readers decode the value half and
 * verify the complement, mirroring the 256-bit dual-rail readers.
 *---------------------------------------------------------------------------*/

int rom_otp_read_life_cycle(uint8_t *lc_out) {
    km_csr__otp_life_cycle_reg_t r = ROM_OTP_LIFE_CYCLE_REG;
    uint8_t enc = (uint8_t)r.f.value;           /* {~lc[3:0], lc[3:0]} */
    uint8_t lo = enc & 0x0Fu;                   /* lc[3:0]             */
    uint8_t hi = (uint8_t)((enc >> 4) & 0x0Fu); /* ~lc[3:0]            */

    if (hi != ((uint8_t)(~lo) & 0x0Fu)) {
        if (lc_out) *lc_out = 0;
        return -1;
    }
    if (lc_out) *lc_out = lo;
    return 0;
}

int rom_otp_read_demotion(uint8_t *demote_out) {
    km_csr__otp_demotion_state_reg_t r = ROM_OTP_DEMOTION_STATE_REG;
    uint8_t d1_enc = (uint8_t)r.f.demote_1_value; /* {~d1, d1} */
    uint8_t d2_enc = (uint8_t)r.f.demote_2_value; /* {~d2, d2} */
    uint8_t d1 = d1_enc & 0x1u;
    uint8_t d2 = d2_enc & 0x1u;

    /* Each value bit must differ from its complement bit. */
    if (((d1_enc >> 1) & 0x1u) == d1 || ((d2_enc >> 1) & 0x1u) == d2) {
        if (demote_out) *demote_out = 0;
        return -1;
    }
    if (demote_out) *demote_out = (uint8_t)((d2 << 1) | d1);
    return 0;
}

/*---------------------------------------------------------------------------
 * 256-bit dual-rail field readers
 *---------------------------------------------------------------------------*/

int rom_otp_read_chiplet_uid(uint32_t out[ROM_KM_OTP_WORDS]) {
    return otp_dr_read(KEY_MANAGER_KMCSR_OTP_CHIPLET_UID_VAL_0_BASE_ADDR,
                       KEY_MANAGER_KMCSR_OTP_CHIPLET_UID_CPL_0_BASE_ADDR, out);
}

int rom_otp_read_sip_uid(uint32_t out[ROM_KM_OTP_WORDS]) {
    return otp_dr_read(KEY_MANAGER_KMCSR_OTP_SIP_UID_VAL_0_BASE_ADDR,
                       KEY_MANAGER_KMCSR_OTP_SIP_UID_CPL_0_BASE_ADDR, out);
}

int rom_otp_read_sys_uid(uint32_t out[ROM_KM_OTP_WORDS]) {
    return otp_dr_read(KEY_MANAGER_KMCSR_OTP_SYS_UID_VAL_0_BASE_ADDR,
                       KEY_MANAGER_KMCSR_OTP_SYS_UID_CPL_0_BASE_ADDR, out);
}

int rom_otp_read_class_key(uint32_t out[ROM_KM_OTP_WORDS]) {
    return otp_dr_read(KEY_MANAGER_KMCSR_OTP_CLASS_KEY_VAL_0_BASE_ADDR,
                       KEY_MANAGER_KMCSR_OTP_CLASS_KEY_CPL_0_BASE_ADDR, out);
}

int rom_otp_read_sep_chiplet_id(uint32_t out[ROM_KM_OTP_WORDS]) {
    return otp_dr_read(KEY_MANAGER_KMCSR_OTP_SEP_CHIPLET_ID_VAL_0_BASE_ADDR,
                       KEY_MANAGER_KMCSR_OTP_SEP_CHIPLET_ID_CPL_0_BASE_ADDR, out);
}

int rom_otp_read_sep_sip_id(uint32_t out[ROM_KM_OTP_WORDS]) {
    return otp_dr_read(KEY_MANAGER_KMCSR_OTP_SEP_SIP_ID_VAL_0_BASE_ADDR,
                       KEY_MANAGER_KMCSR_OTP_SEP_SIP_ID_CPL_0_BASE_ADDR, out);
}

int rom_otp_read_sep_sys_id(uint32_t out[ROM_KM_OTP_WORDS]) {
    return otp_dr_read(KEY_MANAGER_KMCSR_OTP_SEP_SYS_ID_VAL_0_BASE_ADDR,
                       KEY_MANAGER_KMCSR_OTP_SEP_SYS_ID_CPL_0_BASE_ADDR, out);
}

/*---------------------------------------------------------------------------
 * Read-lock
 *---------------------------------------------------------------------------*/

void rom_otp_set_read_lock(uint32_t lock_bits) {
    /* Triple-write convention: 3 writes ensure the lock commits even under a
     * single-bit glitch.  woset makes repeated writes idempotent; already-set
     * bits are unaffected by re-writing. */
    km_csr__otp_read_lock_reg_t r = {0};
    r.w = lock_bits;
    ROM_OTP_READ_LOCK_REG = r;
    ROM_OTP_READ_LOCK_REG = r;
    ROM_OTP_READ_LOCK_REG = r;
}

void rom_otp_set_read_lock_cold(uint32_t lock_bits) {
    /* Triple-write convention — same rationale as rom_otp_set_read_lock.
     * OTP_READ_LOCK_COLD is cold-reset domain: survives warm reset. */
    km_csr__otp_read_lock_cold_reg_t r = {0};
    r.w = lock_bits;
    ROM_OTP_READ_LOCK_COLD_REG = r;
    ROM_OTP_READ_LOCK_COLD_REG = r;
    ROM_OTP_READ_LOCK_COLD_REG = r;
}

/*---------------------------------------------------------------------------
 * Change status helpers
 *---------------------------------------------------------------------------*/

uint32_t rom_otp_get_change_status(void) {
    km_csr__otp_change_status_reg_t r = ROM_OTP_CHANGE_STATUS_REG;
    return r.w;
}

void rom_otp_clear_change_status(uint32_t mask) {
    km_csr__otp_change_status_reg_t r = {0};
    r.w = mask;
    ROM_OTP_CHANGE_STATUS_REG = r;
}

__attribute__((weak)) void rom_otp_on_change(uint32_t changed_mask) {
    (void)changed_mask;
}
