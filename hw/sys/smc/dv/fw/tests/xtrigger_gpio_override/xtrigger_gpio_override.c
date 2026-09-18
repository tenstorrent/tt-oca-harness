/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/**
 * @file main.c
 * @brief Simple Xtrigger GPIO Hardware Override Test
 *
 * This test enables GPIO hardware override functionality
 * and communicates the result via scratch registers to the CocoTB testbench.
 */

#include <stdint.h>
#include <stdbool.h>

#include "smc_io.h"
#include "smc_test.h"
#include "virt_console.h"

// 15 override channels x 4 = 60 bonded GPIOs (indices 0-59); one xtrigger channel
// sits on a dedicated pad.
#define NUM_GPIOS 60

/**
 * Enable hardware override on a specific GPIO
 */
static uint32_t enable_gpio_hw_override(uint32_t gpio_num) {
    gpio_ctrl__CONTROL_t gpio_ctrl;
    gpio_ctrl.w = read_gpio_shim(
        gpio_num, (SMC_TOP_GPIO_CTRL_CONTROL_BASE_ADDR(0) - SMC_TOP_GPIO_CTRL_BASE_ADDR(0)));
    gpio_ctrl.f.hw2_ovrd = 0x1; // Enable secondary HW function override
    write_gpio_shim(gpio_num,
                    (SMC_TOP_GPIO_CTRL_CONTROL_BASE_ADDR(0) - SMC_TOP_GPIO_CTRL_BASE_ADDR(0)),
                    gpio_ctrl.w);

    // check that enabling worked
    gpio_ctrl.w = read_gpio_shim(
        gpio_num, (SMC_TOP_GPIO_CTRL_CONTROL_BASE_ADDR(0) - SMC_TOP_GPIO_CTRL_BASE_ADDR(0)));
    if (gpio_ctrl.f.hw2_ovrd != 0x1) {
        test_fail(0);
    }

    return gpio_ctrl.f.hw2_ovrd;
}

/**
 * Main test function
 */
int main(void) {
    simputs("=== Xtrigger GPIO Override Simple Test ===\n");

    // Enable HW override on test GPIOs for two xtrigger interfaces
    simputs("Enabling HW override on GPIOs...\n");

    uint32_t enable_count = 0;

    // Enable the override on every bonded GPIO.
    for (int i = 0; i < NUM_GPIOS; i++) {
        enable_count = enable_count + enable_gpio_hw_override(i);
        write_scratch(6, i);
    }

    // Report test result via scratch registers
    if (enable_count == NUM_GPIOS) {
        // Success marker for the testbench
        write_scratch(5, 0xC0FFEE);
        test_pass(0);
    } else {
        // Failure marker for the testbench
        write_scratch(6, 0x1000 + enable_count);
        test_fail(0);
    }

    while (true) {
        __asm__("wfi");
    }

    return 0;
}
