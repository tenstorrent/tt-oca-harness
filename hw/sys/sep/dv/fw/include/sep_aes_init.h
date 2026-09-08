/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

#ifndef SEP_AES_INIT_H
#define SEP_AES_INIT_H

#include <stdint.h>
#include <stdio.h>
#include "och_sep_common.h"
#include "sep.h"

/**
 * Release AES from software reset.
 *
 * Sets the aes_sw_rst_n bit of sep_reset_ctrl SW_RESET_N, preserving the
 * other reset bits, so the AES module can accept operations.
 *
 * Call this once at the start of main(), after sep_outbound_filter_init().
 *
 * @return 0 on success, -1 if the bit did not stick (bus routing issue).
 */
static inline int sep_aes_sw_reset_release(void) {
    uint32_t val = READ_REG(OCH_SEP_TOP_SEP_RESET_CTRL_SW_RESET_N_BASE_ADDR);
    val |= (uint32_t)SEP_RESET_CTRL__SW_RESET_N__AES_SW_RST_N_bm;
    WRITE_REG(OCH_SEP_TOP_SEP_RESET_CTRL_SW_RESET_N_BASE_ADDR, val);
    __asm__ volatile("fence" ::: "memory");
    if ((READ_REG(OCH_SEP_TOP_SEP_RESET_CTRL_SW_RESET_N_BASE_ADDR) &
         SEP_RESET_CTRL__SW_RESET_N__AES_SW_RST_N_bm) == 0) {
        printf("ERROR: cannot release AES sw reset\n");
        return -1;
    }
    return 0;
}

#endif /* SEP_AES_INIT_H */
