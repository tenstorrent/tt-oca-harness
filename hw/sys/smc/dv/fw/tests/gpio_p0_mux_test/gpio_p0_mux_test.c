/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

#include <stdint.h>

#include "metal/atomic.h"
#include "metal/lock.h"
#include "smc_io.h"
#include "smc_test.h"

#define TOTAL_GPIOS 64          // BP_GPIO array only has 64 GPIOs (indices 0-63)
#define GPIO_SKIP_COOL_RESET 64 // GPIO_64 is cool_reset_in, will reset chip if toggled
#define PAD2SOC_MASK 0x80000000

// Test Register Interface Mode functionality
void test_register_interface_mode(uint32_t gpio_num) {
    gpio_intf__DATA_CTRL_t gpio_control;

    // Read current register value
    gpio_control.w = read_gpio(
        gpio_num, (SMC_TOP_GPIO_INTF_DATA_CTRL_BASE_ADDR(0) - SMC_TOP_GPIO_INTF_BASE_ADDR(0)));

    // Configure for Register Interface Mode
    gpio_control.f.interface_enable = 1;
    gpio_control.f.enable_rx_tx = 1; // 2'b01: TX enabled - core2pad_en
    gpio_control.f.core2pad = 1;
    gpio_control.f.lsio_select = 0;
    gpio_control.f.lsio_disable = 0;

    write_gpio(gpio_num,
               (SMC_TOP_GPIO_INTF_DATA_CTRL_BASE_ADDR(0) - SMC_TOP_GPIO_INTF_BASE_ADDR(0)),
               gpio_control.w);

    // Read back and verify
    uint32_t read_data = read_gpio(
        gpio_num, (SMC_TOP_GPIO_INTF_DATA_CTRL_BASE_ADDR(0) - SMC_TOP_GPIO_INTF_BASE_ADDR(0)));
    write_scratch(1, (gpio_num << 16) | 0x0001);
    write_scratch(2, read_data);

    gpio_control.w = read_data;
    if (gpio_control.f.interface_enable != 1 || gpio_control.f.core2pad != 1) {
        write_scratch(1, (gpio_num << 16) | 0xDEAD);
        test_fail(0);
    }

    // Test core2pad = 0
    gpio_control.w = read_gpio(
        gpio_num, (SMC_TOP_GPIO_INTF_DATA_CTRL_BASE_ADDR(0) - SMC_TOP_GPIO_INTF_BASE_ADDR(0)));
    gpio_control.f.core2pad = 0;
    write_gpio(gpio_num,
               (SMC_TOP_GPIO_INTF_DATA_CTRL_BASE_ADDR(0) - SMC_TOP_GPIO_INTF_BASE_ADDR(0)),
               gpio_control.w);

    read_data = read_gpio(
        gpio_num, (SMC_TOP_GPIO_INTF_DATA_CTRL_BASE_ADDR(0) - SMC_TOP_GPIO_INTF_BASE_ADDR(0)));
    write_scratch(1, (gpio_num << 16) | 0x0002);
    write_scratch(2, read_data);

    gpio_control.w = read_data;
    if (gpio_control.f.interface_enable != 1 || gpio_control.f.core2pad != 0) {
        write_scratch(1, (gpio_num << 16) | 0xDEAD);
        test_fail(0);
    }
}

// Test LSIO Interface Mode functionality (via lsio_select register bit)
void test_lsio_select_mode(uint32_t gpio_num) {
    gpio_intf__DATA_CTRL_t gpio_control;

    // Read current register value
    gpio_control.w = read_gpio(
        gpio_num, (SMC_TOP_GPIO_INTF_DATA_CTRL_BASE_ADDR(0) - SMC_TOP_GPIO_INTF_BASE_ADDR(0)));

    // Configure for LSIO Interface Mode via lsio_select
    gpio_control.f.interface_enable = 0; // Disable register interface
    gpio_control.f.lsio_select = 1;      // Enable LSIO select
    gpio_control.f.lsio_disable = 0;     // Don't disable LSIO

    write_gpio(gpio_num,
               (SMC_TOP_GPIO_INTF_DATA_CTRL_BASE_ADDR(0) - SMC_TOP_GPIO_INTF_BASE_ADDR(0)),
               gpio_control.w);

    // Read back and verify
    uint32_t read_data = read_gpio(
        gpio_num, (SMC_TOP_GPIO_INTF_DATA_CTRL_BASE_ADDR(0) - SMC_TOP_GPIO_INTF_BASE_ADDR(0)));
    write_scratch(1, (gpio_num << 16) | 0x0003);
    write_scratch(2, read_data);

    gpio_control.w = read_data;
    if (gpio_control.f.interface_enable != 0 || gpio_control.f.lsio_select != 1) {
        write_scratch(1, (gpio_num << 16) | 0xDEAD);
        test_fail(0);
    }

    // Test disabling LSIO select
    gpio_control.f.lsio_select = 0;
    write_gpio(gpio_num,
               (SMC_TOP_GPIO_INTF_DATA_CTRL_BASE_ADDR(0) - SMC_TOP_GPIO_INTF_BASE_ADDR(0)),
               gpio_control.w);

    read_data = read_gpio(
        gpio_num, (SMC_TOP_GPIO_INTF_DATA_CTRL_BASE_ADDR(0) - SMC_TOP_GPIO_INTF_BASE_ADDR(0)));
    write_scratch(1, (gpio_num << 16) | 0x0004);
    write_scratch(2, read_data);

    gpio_control.w = read_data;
    if (gpio_control.f.lsio_select != 0) {
        write_scratch(1, (gpio_num << 16) | 0xDEAD);
        test_fail(0);
    }
}

// Test mux priority: interface_enable should override lsio_select
void test_mux_priority(uint32_t gpio_num) {
    gpio_intf__DATA_CTRL_t gpio_control;

    // Read current register value
    gpio_control.w = read_gpio(
        gpio_num, (SMC_TOP_GPIO_INTF_DATA_CTRL_BASE_ADDR(0) - SMC_TOP_GPIO_INTF_BASE_ADDR(0)));

    // Set both interface_enable and lsio_select
    // interface_enable should have priority
    gpio_control.f.interface_enable = 1;
    gpio_control.f.lsio_select = 1;
    gpio_control.f.core2pad = 1;
    gpio_control.f.enable_rx_tx = 1;

    write_gpio(gpio_num,
               (SMC_TOP_GPIO_INTF_DATA_CTRL_BASE_ADDR(0) - SMC_TOP_GPIO_INTF_BASE_ADDR(0)),
               gpio_control.w);

    // Read back and verify interface_enable takes priority
    uint32_t read_data = read_gpio(
        gpio_num, (SMC_TOP_GPIO_INTF_DATA_CTRL_BASE_ADDR(0) - SMC_TOP_GPIO_INTF_BASE_ADDR(0)));
    write_scratch(1, (gpio_num << 16) | 0x0005);
    write_scratch(2, read_data);

    gpio_control.w = read_data;
    // When interface_enable = 1, register interface should be active
    // lsio_select can still be set but won't take effect
    if (gpio_control.f.interface_enable != 1) {
        write_scratch(1, (gpio_num << 16) | 0xDEAD);
        test_fail(0);
    }
}

// Test lsio_disable functionality
void test_lsio_disable(uint32_t gpio_num) {
    gpio_intf__DATA_CTRL_t gpio_control;

    // Read current register value
    gpio_control.w = read_gpio(
        gpio_num, (SMC_TOP_GPIO_INTF_DATA_CTRL_BASE_ADDR(0) - SMC_TOP_GPIO_INTF_BASE_ADDR(0)));

    // Test lsio_disable = 1 should block LSIO interface
    gpio_control.f.interface_enable = 0;
    gpio_control.f.lsio_select = 1;
    gpio_control.f.lsio_disable = 1; // Disable LSIO

    write_gpio(gpio_num,
               (SMC_TOP_GPIO_INTF_DATA_CTRL_BASE_ADDR(0) - SMC_TOP_GPIO_INTF_BASE_ADDR(0)),
               gpio_control.w);

    // Read back and verify
    uint32_t read_data = read_gpio(
        gpio_num, (SMC_TOP_GPIO_INTF_DATA_CTRL_BASE_ADDR(0) - SMC_TOP_GPIO_INTF_BASE_ADDR(0)));
    write_scratch(1, (gpio_num << 16) | 0x0006);
    write_scratch(2, read_data);

    gpio_control.w = read_data;
    if (gpio_control.f.lsio_disable != 1) {
        write_scratch(1, (gpio_num << 16) | 0xDEAD);
        test_fail(0);
    }

    // Test disabling lsio_disable
    gpio_control.f.lsio_disable = 0;
    write_gpio(gpio_num,
               (SMC_TOP_GPIO_INTF_DATA_CTRL_BASE_ADDR(0) - SMC_TOP_GPIO_INTF_BASE_ADDR(0)),
               gpio_control.w);

    read_data = read_gpio(
        gpio_num, (SMC_TOP_GPIO_INTF_DATA_CTRL_BASE_ADDR(0) - SMC_TOP_GPIO_INTF_BASE_ADDR(0)));
    write_scratch(1, (gpio_num << 16) | 0x0007);
    write_scratch(2, read_data);

    gpio_control.w = read_data;
    if (gpio_control.f.lsio_disable != 0) {
        write_scratch(1, (gpio_num << 16) | 0xDEAD);
        test_fail(0);
    }
}

// Test mux switching between Register and LSIO modes
void test_mux_switching(uint32_t gpio_num) {
    gpio_intf__DATA_CTRL_t gpio_control;

    // Step 1: Start with Register Interface Mode
    gpio_control.w = read_gpio(
        gpio_num, (SMC_TOP_GPIO_INTF_DATA_CTRL_BASE_ADDR(0) - SMC_TOP_GPIO_INTF_BASE_ADDR(0)));
    gpio_control.f.interface_enable = 1;
    gpio_control.f.lsio_select = 0;
    gpio_control.f.core2pad = 1;
    gpio_control.f.enable_rx_tx = 1;
    write_gpio(gpio_num,
               (SMC_TOP_GPIO_INTF_DATA_CTRL_BASE_ADDR(0) - SMC_TOP_GPIO_INTF_BASE_ADDR(0)),
               gpio_control.w);

    uint32_t read_data = read_gpio(
        gpio_num, (SMC_TOP_GPIO_INTF_DATA_CTRL_BASE_ADDR(0) - SMC_TOP_GPIO_INTF_BASE_ADDR(0)));
    write_scratch(1, (gpio_num << 16) | 0x0008);
    write_scratch(2, read_data);

    gpio_control.w = read_data;
    if (gpio_control.f.interface_enable != 1) {
        write_scratch(1, (gpio_num << 16) | 0xDEAD);
        test_fail(0);
    }

    // Step 2: Switch to LSIO Interface Mode
    gpio_control.w = read_gpio(
        gpio_num, (SMC_TOP_GPIO_INTF_DATA_CTRL_BASE_ADDR(0) - SMC_TOP_GPIO_INTF_BASE_ADDR(0)));
    gpio_control.f.interface_enable = 0;
    gpio_control.f.lsio_select = 1;
    gpio_control.f.lsio_disable = 0;
    write_gpio(gpio_num,
               (SMC_TOP_GPIO_INTF_DATA_CTRL_BASE_ADDR(0) - SMC_TOP_GPIO_INTF_BASE_ADDR(0)),
               gpio_control.w);

    read_data = read_gpio(
        gpio_num, (SMC_TOP_GPIO_INTF_DATA_CTRL_BASE_ADDR(0) - SMC_TOP_GPIO_INTF_BASE_ADDR(0)));
    write_scratch(1, (gpio_num << 16) | 0x0009);
    write_scratch(2, read_data);

    gpio_control.w = read_data;
    if (gpio_control.f.interface_enable != 0 || gpio_control.f.lsio_select != 1) {
        write_scratch(1, (gpio_num << 16) | 0xDEAD);
        test_fail(0);
    }

    // Step 3: Switch back to Register Interface Mode
    gpio_control.w = read_gpio(
        gpio_num, (SMC_TOP_GPIO_INTF_DATA_CTRL_BASE_ADDR(0) - SMC_TOP_GPIO_INTF_BASE_ADDR(0)));
    gpio_control.f.interface_enable = 1;
    gpio_control.f.lsio_select = 0;
    write_gpio(gpio_num,
               (SMC_TOP_GPIO_INTF_DATA_CTRL_BASE_ADDR(0) - SMC_TOP_GPIO_INTF_BASE_ADDR(0)),
               gpio_control.w);

    read_data = read_gpio(
        gpio_num, (SMC_TOP_GPIO_INTF_DATA_CTRL_BASE_ADDR(0) - SMC_TOP_GPIO_INTF_BASE_ADDR(0)));
    write_scratch(1, (gpio_num << 16) | 0x000A);
    write_scratch(2, read_data);

    gpio_control.w = read_data;
    if (gpio_control.f.interface_enable != 1) {
        write_scratch(1, (gpio_num << 16) | 0xDEAD);
        test_fail(0);
    }
}

// Test all mux functionality for a single GPIO
void test_gpio_mux_functionality(uint32_t gpio_num) {
    // Test Register Interface Mode
    test_register_interface_mode(gpio_num);

    // Test LSIO Select Mode
    test_lsio_select_mode(gpio_num);

    // Test Mux Priority
    test_mux_priority(gpio_num);

    // Test LSIO Disable
    test_lsio_disable(gpio_num);

    // Test Mux Switching
    test_mux_switching(gpio_num);
}

int main(void) {
    // Initialize peripherals
    // peripherals_out_of_reset();  // Function is not available

    // Test all GPIOs (0-63), skipping GPIO 64 (cool_reset_in) which is out of range
    for (uint32_t gpio_num = 0; gpio_num < TOTAL_GPIOS; gpio_num++) {
        if (gpio_num == GPIO_SKIP_COOL_RESET) {
            // Skip GPIO 64 as it is cool_reset_in and will reset chip if toggled
            // Note: GPIO 64 is already out of range for BP_GPIO array
            continue;
        }

        // Test all mux functionality for this GPIO
        test_gpio_mux_functionality(gpio_num);
    }

    test_pass(0);

    while (true) {
        __asm__("wfi");
    }

    return 0;
}

int other_main(int hartid) {
    while (true) {
        __asm__("wfi");
    }
}

int secondary_main(void) {
    int hartid = metal_cpu_get_current_hartid();

    if (hartid == 0) {
        return main();
    } else {
        return other_main(hartid);
    }
}
