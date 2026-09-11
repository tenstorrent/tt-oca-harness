/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

#include <stdint.h>

#include "smc_defines.h"
#include "smc_test.h"
#include "sep_smu_axi_extension_decode_protocol.h"

/*
 * smu_sep_axi_extension_decode -- SMC pad-arm firmware.
 *
 * Cadence xSPI reaches the SMU-TB flash model through smc_ip_integration
 * GPIO 2nd-HW-function override (GPIO 0-10 DQ/CS/CLK/DQS, GPIO 54 mem_rebar).
 * hw2_ovrd resets to 0, so the override is a no-op until this image sets it.
 * Publishes GPIO_OVRD_OK on scratch2 after the bits read back; SEP waits
 * on that token before Cadence init.
 */
void smu_sep_axi_extension_decode_entry(void) __attribute__((naked, section(".init"), used));
void smu_sep_axi_extension_decode_entry(void) {
    __asm__ volatile(".option push\n"
                     ".option norvc\n"
                     "csrr a0, mhartid\n"
                     "bnez a0, 0f\n"
                     "la gp, __global_pointer$\n"
                     "la sp, _sp\n"
                     "andi sp, sp, -16\n"
                     "call main\n"
                     "0:\n"
                     "wfi\n"
                     "j 0b\n"
                     ".option pop\n");
}

static int enable_spi_gpio_override(void) {
    uint32_t g;
    uint32_t a;
    uint32_t v;
    const uint32_t bit = 1u << AXI_EXT_HW2_OVRD_BIT;

    for (g = 0; g <= 10u; g++) {
        a = (uint32_t)SMC_TOP_GPIO_CTRL_CONTROL_BASE_ADDR(g);
        v = read_reg(a) | bit;
        write_reg(a, v);
        __asm__ volatile("fence iorw, iorw" ::: "memory");
        if ((read_reg(a) & bit) == 0u) {
            return -1;
        }
    }
    a = (uint32_t)SMC_TOP_GPIO_CTRL_CONTROL_BASE_ADDR(54u);
    v = read_reg(a) | bit;
    write_reg(a, v);
    __asm__ volatile("fence iorw, iorw" ::: "memory");
    if ((read_reg(a) & bit) == 0u) {
        return -1;
    }
    return 0;
}

int main(void) {
    smu_sep_dv_test_bringup();
    if (enable_spi_gpio_override() != 0) {
        write_scratch(9, AXI_EXT_SMC_FAIL);
        test_fail(0);
    }
    write_scratch(2, AXI_EXT_GPIO_OVRD_OK);
    __asm__ volatile("fence iorw, iorw" ::: "memory");
    test_pass(0);

    while (true) {
        __asm__ volatile("wfi");
    }
    return 0;
}
