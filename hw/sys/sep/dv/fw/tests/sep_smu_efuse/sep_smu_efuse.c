/*
 * sep_smu_efuse - SMU-level SEP eFuse CSR sanity test.
 *
 * Goal:
 *   Verify SEP-side eFuse control/shim register access path in SMU wrapper by
 *   programming benign control values and checking readback.
 */

#include <stdint.h>

#include "och_sep_common.h"
#include "sep_reg.h"
#include "sep_outbound_filter.h"

static int rw_check32(uint32_t addr, uint32_t value)
{
    WRITE_REG(addr, value);
    return (READ_REG(addr) == value) ? 0 : -1;
}

static int run_efuse_reg_sequence(void)
{
    if (rw_check32(EFUSE_INTERFACE_CTRL_EFUSE_READ_CTRL_REG_ADDR, 0x00001234u) != 0) return -1;
    if (rw_check32(EFUSE_INTERFACE_CTRL_EFUSE_PROGRAM_CTRL_REG_ADDR, 0x00000001u) != 0) return -2;
    if (rw_check32(EFUSE_SHIM_CTRL_EFUSE_TIMING_CTRL_7_REG_ADDR, 0x0000ABCDu) != 0) return -3;
    if (rw_check32(EFUSE_SHIM_CTRL_EFUSE_TIMING_CTRL_8_REG_ADDR, 0x00000020u) != 0) return -4;

    /* Read-only touchpoint to ensure token map access is alive. */
    (void)READ_REG(EFUSE_MMR_TOKEN_EOP_REG_ADDR);
    return 0;
}

__attribute__((used, noinline, noreturn))
void smu_sep_efuse_pass_loop(void)
{
    while (1) {
        __asm__ volatile("wfi");
    }
}

__attribute__((used, noinline, noreturn))
void smu_sep_efuse_fail_loop(void)
{
    while (1) {
        __asm__ volatile("wfi");
    }
}

int main(void)
{
    sep_outbound_filter_init();
    if (run_efuse_reg_sequence() == 0) {
        smu_sep_efuse_pass_loop();
    } else {
        smu_sep_efuse_fail_loop();
    }
}
