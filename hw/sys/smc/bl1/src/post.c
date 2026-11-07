/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

#include "smc_bl1.h"
#include "smc_bl1_layout.h"
#include "smc_status.h"

_Static_assert(SMC_BL1_IMAGE_START == SMU_BL1_IMAGE_WINDOW_START &&
                   SMC_BL1_IMAGE_END == SMU_BL1_IMAGE_WINDOW_END &&
                   SMC_BL1_RW_START == SMU_BL1_RW_WINDOW_START &&
                   SMC_BL1_RW_END == SMU_BL1_RW_WINDOW_END,
               "smc_bl1_layout.h windows match the contract");
_Static_assert(SMC_BL1_SCRATCH_STATUS_TO_SEP == SMU_BL1_SCRATCH_STATUS_TO_SEP &&
                   (1u << SMC_BL1_HART0_PARKED_BIT) == SMU_BL1_STATUS_HART0_PARKED,
               "smc_bl1_layout.h parked bit matches the contract");
_Static_assert(SMC_BL1_FW_ID == SMC_STATUS_FW_ID_SMC_BL1, "SMC BL1 firmware ID");

void smc_bl1_post(uint32_t value) {
    uint32_t type =
        value >= SMC_BL1_ERR_NO_CHALLENGE ? SMC_STATUS_TYPE_ERROR : SMC_STATUS_TYPE_STATUS;

    smc_bl1_wr64(SMU_BL1_SMC_SCRATCH(SMC_BL1_SCRATCH_POST), SMC_BL1_POST_WORD(value));
    smc_bl1_ring_write((type << 24) | (SMC_BL1_FW_ID << 16) | (value & SMC_BL1_POST_VALUE_MASK));
}

#ifdef DEBUG
// The ROM's scratch 2 console: three ASCII bytes above an opcode-0 low byte whose bit 0
// toggles, so the environment sees every write even when two are equal.
static void console_write(uint32_t word) {
    static uint32_t prev;
    if (word == prev) word ^= 1u;
    smc_bl1_wr64(SMU_BL1_SMC_SCRATCH(2), word);
    prev = word;
}

void smc_bl1_puts(const char *str) {
    uint32_t word = 0;
    unsigned int byte = 1;
    while (*str != '\0') {
        word |= (uint32_t)(uint8_t)*str++ << (8u * byte++);
        if (byte == 4) {
            console_write(word);
            word = 0;
            byte = 1;
        }
    }
    if (byte != 1) console_write(word);
}
#endif
