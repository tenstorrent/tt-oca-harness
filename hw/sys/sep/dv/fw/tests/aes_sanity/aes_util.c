/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

// AES library functions
//-----------------------------------------------------------
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include "test_completion.h"
#include "sep.h"
#include "och_sep_common.h"

static int wait_for_idle(void) {
    int timeout = 1000000;
    while (timeout-- > 0) {
        aes__STATUS_t status = {.w = READ_REG(SEP_TOP_AES_STATUS_BASE_ADDR)};
        if (status.f.IDLE) {
            return 0;
        }
    }
    printf("ERROR: Timeout waiting for AES idle\n");
    return -1;
}

static int wait_for_input_ready(void) {
    int timeout = 1000000;
    while (timeout-- > 0) {
        aes__STATUS_t status = {.w = READ_REG(SEP_TOP_AES_STATUS_BASE_ADDR)};
        if (status.f.INPUT_READY) {
            return 0;
        }
    }
    printf("ERROR: Timeout waiting for AES input ready\n");
    return -1;
}

static int wait_for_output_valid(void) {
    int timeout = 1000000;
    while (timeout-- > 0) {
        aes__STATUS_t status = {.w = READ_REG(SEP_TOP_AES_STATUS_BASE_ADDR)};
        if (status.f.OUTPUT_VALID) {
            return 0;
        }
    }
    printf("ERROR: Timeout waiting for AES output valid\n");
    return -1;
}

static void print_status(const char *tag) {
    aes__STATUS_t s = {.w = READ_REG(SEP_TOP_AES_STATUS_BASE_ADDR)};
    printf("%s STATUS=0x%08x idle=%u stall=%u input_ready=%u output_valid=%u\n", tag, s.w, s.f.IDLE,
           s.f.STALL, s.f.INPUT_READY, s.f.OUTPUT_VALID);
}

static uint32_t swap_bytes_uint32(uint32_t val) {
    return ((val << 24) & 0xFF000000) | // byte 0 --> byte 3
           ((val << 8) & 0x00FF0000) |  // byte 1 --> byte 2
           ((val >> 8) & 0x0000FF00) |  // byte 2 --> byte 1
           ((val >> 24) & 0x000000FF);  // byte 3 --> byte 0
}

static void print_registers() {
    uint32_t regval;
    printf("AES CSRs @ 0x%08x -------------------------------\n", SEP_TOP_AES_BASE_ADDR);
    printf("AES_STATUS_REG:                 0x%08x\n", READ_REG(SEP_TOP_AES_STATUS_BASE_ADDR));
    printf("SEP_TOP_AES_CTRL_SHADOWED_BASE_ADDR:     0x%08x\n",
           READ_REG(SEP_TOP_AES_CTRL_SHADOWED_BASE_ADDR));
    printf("SEP_TOP_AES_CTRL_AUX_SHADOWED_BASE_ADDR: 0x%08x\n",
           READ_REG(SEP_TOP_AES_CTRL_AUX_SHADOWED_BASE_ADDR));
    printf("SEP_TOP_AES_CTRL_AUX_REGWEN_BASE_ADDR:   0x%08x\n",
           READ_REG(SEP_TOP_AES_CTRL_AUX_REGWEN_BASE_ADDR));
    printf("SEP_TOP_AES_TRIGGER_BASE_ADDR:           0x%08x\n",
           READ_REG(SEP_TOP_AES_TRIGGER_BASE_ADDR));
    printf("\nINFO: key share registers are write-only access, so expect reads to return "
           "0x00000000\n");
    for (int i = 0; i < 4; i++) {
        regval = READ_REG(SEP_TOP_AES_KEY_SHARE1_BASE_ADDR(0) + 4 * i);
        printf("AES_KEY_SHARE0[%d]:              0x%08x\n", i, regval);
    }
    for (int i = 0; i < 4; i++) {
        regval = READ_REG(SEP_TOP_AES_KEY_SHARE0_BASE_ADDR(0) + 4 * i);
        printf("AES_KEY_SHARE1[%d]:              0x%08x\n", i, regval);
    }
    printf("\n");
    for (int i = 0; i < 4; i++) {
        regval = READ_REG(SEP_TOP_AES_IV_BASE_ADDR(0) + 4 * i);
        printf("AES_IV[%d]:                      0x%08x\n", i, regval);
    }
    printf("\nINFO: data input registers are write-only access, so expect reads to return "
           "0x00000000\n");
    for (int i = 0; i < 4; i++) {
        regval = READ_REG(SEP_TOP_AES_DATA_IN_BASE_ADDR(0) + 4 * i);
        printf("AES_DATA_IN[%d]:                 0x%08x\n", i, regval);
    }
    printf("\n");
    for (int i = 0; i < 4; i++) {
        regval = READ_REG(SEP_TOP_AES_DATA_OUT_BASE_ADDR(0) + 4 * i);
        printf("AES_DATA_OUT[%d]:                0x%08x\n", i, regval);
    }
    printf("DEBUG: byte endian swapped data out\n");
    for (int i = 0; i < 4; i++) {
        regval = READ_REG(SEP_TOP_AES_DATA_OUT_BASE_ADDR(0) + 4 * i);
        printf("AES_DATA_OUT[%d]:                0x%08x\n", i, swap_bytes_uint32(regval));
    }
}
