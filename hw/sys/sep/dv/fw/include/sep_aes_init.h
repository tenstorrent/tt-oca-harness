#ifndef SEP_AES_INIT_H
#define SEP_AES_INIT_H

#include <stdint.h>
#include <stdio.h>
#include "och_sep_common.h"
#include "och_sep_top_reg.h"

/**
 * Release AES from software reset.
 *
 * The sep_reset_ctrl SW_RESET_N register defaults to 0 (all IPs held in
 * software reset). This function writes 1 to the aes_sw_rst_n bit to
 * release the AES module so it can accept operations.
 *
 * Call this once at the start of main(), after sep_outbound_filter_init().
 *
 * @return 0 on success, -1 if the bit did not stick (bus routing issue).
 */
static inline int sep_aes_sw_reset_release(void) {
    uint32_t val = READ_REG(SEP_RESET_CTRL_SW_RESET_N_REG_ADDR);
    val |= (uint32_t)SEP_RESET_CTRL_SW_RESET_N_AES_SW_RST_N_MASK;
    WRITE_REG(SEP_RESET_CTRL_SW_RESET_N_REG_ADDR, val);
    __asm__ volatile("fence" ::: "memory");
    if ((READ_REG(SEP_RESET_CTRL_SW_RESET_N_REG_ADDR) &
         SEP_RESET_CTRL_SW_RESET_N_AES_SW_RST_N_MASK) == 0) {
        printf("ERROR: cannot release AES sw reset\n");
        return -1;
    }
    return 0;
}

#endif /* SEP_AES_INIT_H */
