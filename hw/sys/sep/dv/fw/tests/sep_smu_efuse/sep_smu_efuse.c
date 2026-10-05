/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/*
 * sep_smu_efuse - SMU-level SEP eFuse CSR sanity test.
 *
 * Writes eFuse control and shim registers with values that start no read or
 * program, and checks that each reads back.
 */

#include <stdint.h>

#include "och_sep_common.h"
#include "sep.h"
#include "sep_outbound_filter.h"

static int rw_check32(uint32_t addr, uint32_t value) {
    WRITE_REG(addr, value);
    return (READ_REG(addr) == value) ? 0 : -1;
}

static int run_efuse_reg_sequence(void) {
    if (rw_check32(SEP_TOP_EFUSE_INTERFACE_CTRL_EFUSE_READ_CTRL_BASE_ADDR, 0x00001234u) != 0)
        return -1;
    if (rw_check32(SEP_TOP_EFUSE_INTERFACE_CTRL_EFUSE_PROGRAM_CTRL_BASE_ADDR, 0x00000001u) != 0)
        return -2;
    /* This check proves only that the external eFuse shim CSR path is
     * read/writable. */
#ifdef SEP_TOP_SEP_EXTERNAL_EFUSE_SHIM_CTRL_EFUSE_TIMING_CTRL_7_BASE_ADDR
    if (rw_check32(SEP_TOP_SEP_EXTERNAL_EFUSE_SHIM_CTRL_EFUSE_TIMING_CTRL_7_BASE_ADDR,
                   0x0000ABCDu) != 0)
        return -3;
    if (rw_check32(SEP_TOP_SEP_EXTERNAL_EFUSE_SHIM_CTRL_EFUSE_TIMING_CTRL_8_BASE_ADDR,
                   0x00000020u) != 0)
        return -4;
#else
    if (rw_check32(SEP_TOP_SEP_EXTERNAL_EFUSE_SHIM_CTRL_EFUSE_BANK_INIT_TIME_BASE_ADDR,
                   0x00000020u) != 0)
        return -3;
#endif

    /* The token map read only has to complete; its value is not checked. */
    (void)READ_REG(SEP_TOP_EFUSE_MMR_TOKEN_EOP_BASE_ADDR);
    return 0;
}

__attribute__((used, noinline, noreturn)) void smu_sep_efuse_pass_loop(void) {
    while (1) {
        __asm__ volatile("wfi");
    }
}

__attribute__((used, noinline, noreturn)) void smu_sep_efuse_fail_loop(void) {
    while (1) {
        __asm__ volatile("wfi");
    }
}

int main(void) {
    sep_outbound_filter_init();
    if (run_efuse_reg_sequence() == 0) {
        smu_sep_efuse_pass_loop();
    } else {
        smu_sep_efuse_fail_loop();
    }
}
