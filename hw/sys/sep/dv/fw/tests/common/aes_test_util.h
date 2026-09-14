/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/*
 * AES Test Utility Functions
 *
 * Shared helpers for the SEP AES firmware tests.
 *
 * Include after och_sep_common.h and sep.h.
 */

#ifndef AES_TEST_UTIL_H
#define AES_TEST_UTIL_H

#include <stdint.h>
#include <stdio.h>
#include "och_sep_common.h"
#include "sep.h"

#ifndef AES_WAIT_TIMEOUT
#define AES_WAIT_TIMEOUT 1000000
#endif

/* ------------------------------------------------------------------ */
/* Status Polling                                                     */
/* ------------------------------------------------------------------ */

static inline int wait_for_idle(void) {
    int timeout = AES_WAIT_TIMEOUT;
    while (timeout-- > 0) {
        aes__STATUS_t status = {.w = READ_REG(OCH_SEP_TOP_AES_STATUS_BASE_ADDR)};
        if (status.f.IDLE) return 0;
    }
    printf("ERROR: Timeout waiting for AES idle\n");
    return -1;
}

static inline int wait_for_input_ready(void) {
    int timeout = AES_WAIT_TIMEOUT;
    while (timeout-- > 0) {
        aes__STATUS_t status = {.w = READ_REG(OCH_SEP_TOP_AES_STATUS_BASE_ADDR)};
        if (status.f.INPUT_READY) return 0;
    }
    printf("ERROR: Timeout waiting for AES input ready\n");
    return -1;
}

static inline int wait_for_output_valid(void) {
    int timeout = AES_WAIT_TIMEOUT;
    while (timeout-- > 0) {
        aes__STATUS_t status = {.w = READ_REG(OCH_SEP_TOP_AES_STATUS_BASE_ADDR)};
        if (status.f.OUTPUT_VALID) return 0;
    }
    printf("ERROR: Timeout waiting for AES output valid\n");
    return -1;
}

/* ------------------------------------------------------------------ */
/* Status Display & Alert Checking                                    */
/* ------------------------------------------------------------------ */

static inline void print_status(const char *tag) {
    aes__STATUS_t s = {.w = READ_REG(OCH_SEP_TOP_AES_STATUS_BASE_ADDR)};
    printf("%s: STATUS=0x%08x (idle=%u stall=%u input_ready=%u output_valid=%u)\n", tag, s.w,
           s.f.IDLE, s.f.STALL, s.f.INPUT_READY, s.f.OUTPUT_VALID);
}

static inline int check_no_alert(const char *tag) {
    uint32_t val = READ_REG(OCH_SEP_TOP_AES_STATUS_BASE_ADDR);
    if (val & (1u << 5)) {
        printf("ERROR: %s: ALERT_RECOV_CTRL_UPDATE_ERR (STATUS=0x%08x)\n", tag, val);
        return -1;
    }
    if (val & (1u << 6)) {
        printf("ERROR: %s: ALERT_FATAL_FAULT (STATUS=0x%08x)\n", tag, val);
        return -1;
    }
    return 0;
}

/* ------------------------------------------------------------------ */
/* Data I/O                                                           */
/* ------------------------------------------------------------------ */

static inline void write_data_in(const uint32_t in[4]) {
    for (int i = 0; i < 4; i++) WRITE_REG(OCH_SEP_TOP_AES_DATA_IN_BASE_ADDR(i), in[i]);
}

static inline void read_data_out(uint32_t out[4]) {
    for (int i = 0; i < 4; i++) out[i] = READ_REG(OCH_SEP_TOP_AES_DATA_OUT_BASE_ADDR(i));
}

static inline void read_iv_out(uint32_t iv_out[4]) {
    for (int i = 0; i < 4; i++) iv_out[i] = READ_REG(OCH_SEP_TOP_AES_IV_BASE_ADDR(i));
}

static inline void print_block(const char *label, const uint32_t block[4]) {
    printf("  %s: %08x %08x %08x %08x\n", label, block[0], block[1], block[2], block[3]);
}

/* ------------------------------------------------------------------ */
/* Comparison                                                         */
/* ------------------------------------------------------------------ */

static inline int compare_block(const uint32_t got[4], const uint32_t exp[4], const char *tag) {
    for (int i = 0; i < 4; i++) {
        if (got[i] != exp[i]) {
            printf("  ERROR: %s mismatch at word %d: got=0x%08x exp=0x%08x\n", tag, i, got[i],
                   exp[i]);
            return -1;
        }
    }
    return 0;
}

/* ------------------------------------------------------------------ */
/* Configuration                                                      */
/* ------------------------------------------------------------------ */

/*
 * Full-featured AES configuration.
 *
 * @param operation       0x1=ENC, 0x2=DEC
 * @param mode            0x1=ECB, 0x2=CBC, 0x4=CFB, 0x8=OFB, 0x10=CTR
 * @param key_len         0x1=128, 0x2=192, 0x4=256
 * @param key_share0      Key share 0 words
 * @param key_words       Number of key words (4 for AES-128, 6 for AES-192, 8 for AES-256)
 * @param key_share1      Key share 1 (8 words), or NULL for all-zero share1
 * @param iv              IV (4 words)
 * @param manual_operation 0=automatic, 1=manual trigger
 */
static inline int configure_aes_full(uint32_t operation, uint32_t mode, uint32_t key_len,
                                     const uint32_t *key_share0, int key_words,
                                     const uint32_t *key_share1, const uint32_t iv[4],
                                     uint32_t manual_operation) {
    aes__CTRL_SHADOWED_t ctrl = {.w = 0};
    ctrl.f.OPERATION = operation;
    ctrl.f.MODE = mode;
    ctrl.f.KEY_LEN = key_len;
    ctrl.f.SIDELOAD = 0x0;
    ctrl.f.MANUAL_OPERATION = manual_operation;

    WRITE_REG(OCH_SEP_TOP_AES_CTRL_SHADOWED_BASE_ADDR, ctrl.w);
    WRITE_REG(OCH_SEP_TOP_AES_CTRL_SHADOWED_BASE_ADDR, ctrl.w);

    if (wait_for_idle() != 0) return -1;

    for (int i = 0; i < key_words; i++)
        WRITE_REG(OCH_SEP_TOP_AES_KEY_SHARE0_BASE_ADDR(i), key_share0[i]);
    for (int i = key_words; i < 8; i++) WRITE_REG(OCH_SEP_TOP_AES_KEY_SHARE0_BASE_ADDR(i), 0);

    if (key_share1 != NULL) {
        for (int i = 0; i < 8; i++)
            WRITE_REG(OCH_SEP_TOP_AES_KEY_SHARE1_BASE_ADDR(i), key_share1[i]);
    } else {
        for (int i = 0; i < 8; i++) WRITE_REG(OCH_SEP_TOP_AES_KEY_SHARE1_BASE_ADDR(i), 0);
    }

    if (wait_for_idle() != 0) return -1;

    for (int i = 0; i < 4; i++) WRITE_REG(OCH_SEP_TOP_AES_IV_BASE_ADDR(i), iv[i]);

    return 0;
}

/* Convenience: AES-128, automatic mode, zero KEY_SHARE1 */
static inline int configure_aes(uint32_t operation, uint32_t mode, const uint32_t key[4],
                                const uint32_t iv[4]) {
    return configure_aes_full(operation, mode, 0x1, key, 4, NULL, iv, 0x0);
}

/* ------------------------------------------------------------------ */
/* Cleanup                                                            */
/* ------------------------------------------------------------------ */

static inline void cleanup_aes(void) {
    aes__CTRL_SHADOWED_t ctrl = {.w = 0};
    ctrl.f.OPERATION = 0x1;
    ctrl.f.MODE = 0x1;
    ctrl.f.KEY_LEN = 0x1;
    ctrl.f.MANUAL_OPERATION = 0x1;
    WRITE_REG(OCH_SEP_TOP_AES_CTRL_SHADOWED_BASE_ADDR, ctrl.w);
    WRITE_REG(OCH_SEP_TOP_AES_CTRL_SHADOWED_BASE_ADDR, ctrl.w);

    aes__TRIGGER_t trigger = {.w = 0};
    trigger.f.KEY_IV_DATA_IN_CLEAR = 1;
    trigger.f.DATA_OUT_CLEAR = 1;
    WRITE_REG(OCH_SEP_TOP_AES_TRIGGER_BASE_ADDR, trigger.w);
}

#endif /* AES_TEST_UTIL_H */
