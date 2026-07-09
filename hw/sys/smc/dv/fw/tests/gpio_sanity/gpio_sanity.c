/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

#include <stdint.h>

#include "metal/atomic.h"
#include "metal/lock.h"
#include "smc_io.h"
#include "smc_test.h"

#define BLOCKED_REQUEST 0xbadcab1e
#define PAD2SOC_MASK 0x80000000

#define TOTAL_GPIOS 68

void test_rw_core2pad(void) {

    gpio_intf__DATA_CTRL_t gpio_intf;

    for (int gpio_num = 0; gpio_num < TOTAL_GPIOS; gpio_num++) {

        uint32_t read_data_control = read_gpio(
            gpio_num, (SMC_TOP_GPIO_INTF_DATA_CTRL_BASE_ADDR(0) - SMC_TOP_GPIO_INTF_BASE_ADDR(0)));

        gpio_intf.w = read_data_control;

        if (gpio_num ==
            64) { // this gpio is being used for cool_reset, use 0 as data to avoid resetting itself
            gpio_intf.f.core2pad = 0;
            gpio_intf.f.interface_enable = 0;
        } else {
            gpio_intf.f.core2pad = 1;
            gpio_intf.f.interface_enable = 1;
        }

        write_gpio(gpio_num,
                   (SMC_TOP_GPIO_INTF_DATA_CTRL_BASE_ADDR(0) - SMC_TOP_GPIO_INTF_BASE_ADDR(0)),
                   gpio_intf.w);

        uint32_t read_data_control_updated = read_gpio(
            gpio_num, (SMC_TOP_GPIO_INTF_DATA_CTRL_BASE_ADDR(0) - SMC_TOP_GPIO_INTF_BASE_ADDR(0)));

        write_scratch(1, gpio_num);
        write_scratch(1, gpio_intf.w);
        write_scratch(2, read_data_control_updated);

        // bitwise and to not check bits that are HW writable
        if (gpio_intf.w != (read_data_control_updated & 0x7FFFFFFF)) {
            test_fail(0);
        }
    }
}

void test_read_filter(void) {

    //// Change read permissions on GPIO 0 ////

    gpio_intf__ACCESS_FILTER_t gpio_filter_0;

    gpio_filter_0.w = read_gpio(
        0, (SMC_TOP_GPIO_INTF_ACCESS_FILTER_BASE_ADDR(0) - SMC_TOP_GPIO_INTF_BASE_ADDR(0)));
    gpio_filter_0.f.read_filter_enable = 1;

    gpio_filter_0.f.arprot_requirement = 2; // 3'b010 which is default
    write_gpio(0, (SMC_TOP_GPIO_INTF_ACCESS_FILTER_BASE_ADDR(0) - SMC_TOP_GPIO_INTF_BASE_ADDR(0)),
               gpio_filter_0.w); // set the new filter

    // read back the filter to check it was written correctly
    uint32_t read_filter = read_gpio(
        0, (SMC_TOP_GPIO_INTF_ACCESS_FILTER_BASE_ADDR(0) - SMC_TOP_GPIO_INTF_BASE_ADDR(0)));
    if (read_filter != gpio_filter_0.w) {
        test_fail(0);
    }

    uint32_t read_data_allowed =
        read_gpio(0, (SMC_TOP_GPIO_INTF_DATA_CTRL_BASE_ADDR(0) - SMC_TOP_GPIO_INTF_BASE_ADDR(0)));
    write_scratch(3, read_data_allowed);

    if (read_data_allowed == BLOCKED_REQUEST) {
        test_fail(0);
    }

    // Set prot to be 4
    gpio_filter_0.f.arprot_requirement = 4;
    write_gpio(0, (SMC_TOP_GPIO_INTF_ACCESS_FILTER_BASE_ADDR(0) - SMC_TOP_GPIO_INTF_BASE_ADDR(0)),
               gpio_filter_0.w); // set the new filter

    // read back the filter, it should not be read back as the filter is set
    read_filter = read_gpio(
        0, (SMC_TOP_GPIO_INTF_ACCESS_FILTER_BASE_ADDR(0) - SMC_TOP_GPIO_INTF_BASE_ADDR(0)));
    if (read_filter == gpio_filter_0.w) {
        test_fail(0);
    }

    // Try and read - should be blocked
    uint32_t read_data_blocked =
        read_gpio(0, (SMC_TOP_GPIO_INTF_DATA_CTRL_BASE_ADDR(0) - SMC_TOP_GPIO_INTF_BASE_ADDR(0)));
    write_scratch(4, read_data_blocked);

    if (read_data_blocked != BLOCKED_REQUEST) {
        test_fail(0);
    }
}

void test_write_filter(void) {

    //// Change write permissions on GPIO 1 ////

    for (int i = 0; i < 4; i++) {
        write_scratch(i, 0x22222222);
    }

    gpio_intf__ACCESS_FILTER_t gpio_filter_1;
    gpio_intf__DATA_CTRL_t gpio_intf_1;

    gpio_intf_1.w =
        read_gpio(1, (SMC_TOP_GPIO_INTF_DATA_CTRL_BASE_ADDR(0) - SMC_TOP_GPIO_INTF_BASE_ADDR(0)));
    gpio_filter_1.w = read_gpio(
        1, (SMC_TOP_GPIO_INTF_ACCESS_FILTER_BASE_ADDR(0) - SMC_TOP_GPIO_INTF_BASE_ADDR(0)));
    gpio_filter_1.f.write_filter_enable = 1;
    gpio_filter_1.f.awprot_requirement = 2;

    write_gpio(1, (SMC_TOP_GPIO_INTF_ACCESS_FILTER_BASE_ADDR(0) - SMC_TOP_GPIO_INTF_BASE_ADDR(0)),
               gpio_filter_1.w); // set the new filter with write filter enabled

    // read back the filter to check it was written correctly
    uint32_t read_filter = read_gpio(
        1, (SMC_TOP_GPIO_INTF_ACCESS_FILTER_BASE_ADDR(0) - SMC_TOP_GPIO_INTF_BASE_ADDR(0)));
    if (read_filter != gpio_filter_1.w) {
        test_fail(0);
    }

    gpio_intf_1.f.core2pad = 1;
    gpio_intf_1.f.interface_enable = 1;
    write_gpio(1, (SMC_TOP_GPIO_INTF_DATA_CTRL_BASE_ADDR(0) - SMC_TOP_GPIO_INTF_BASE_ADDR(0)),
               gpio_intf_1.w); // since correct prot (secure transaction), should write
    uint32_t read_data_allowed =
        read_gpio(1, (SMC_TOP_GPIO_INTF_DATA_CTRL_BASE_ADDR(0) - SMC_TOP_GPIO_INTF_BASE_ADDR(0)));

    if (read_data_allowed != gpio_intf_1.w) { // should be equal
        write_scratch(2, gpio_intf_1.w);
        write_scratch(3, read_data_allowed);
        test_fail(0);
    }

    gpio_filter_1.f.awprot_requirement =
        4; // only transactions with prot = 4 should be allowed to write
    write_gpio(1, (SMC_TOP_GPIO_INTF_ACCESS_FILTER_BASE_ADDR(0) - SMC_TOP_GPIO_INTF_BASE_ADDR(0)),
               gpio_filter_1.w); // set the new filter

    // read back the filter to check it was written correctly
    read_filter = read_gpio(
        1, (SMC_TOP_GPIO_INTF_ACCESS_FILTER_BASE_ADDR(0) - SMC_TOP_GPIO_INTF_BASE_ADDR(0)));
    if (read_filter != gpio_filter_1.w) {
        test_fail(0);
    }

    gpio_intf_1.f.core2pad = 0; // try and write a 0
    write_gpio(1, (SMC_TOP_GPIO_INTF_DATA_CTRL_BASE_ADDR(0) - SMC_TOP_GPIO_INTF_BASE_ADDR(0)),
               gpio_intf_1.w);
    uint32_t read_data_unchanged =
        read_gpio(1, (SMC_TOP_GPIO_INTF_DATA_CTRL_BASE_ADDR(0) - SMC_TOP_GPIO_INTF_BASE_ADDR(0)));

    if (read_data_unchanged ==
        gpio_intf_1.w) { // if they are equal then the write occured and the filter did not work
        write_scratch(2, gpio_intf_1.w);
        write_scratch(3, read_data_unchanged);
        test_fail(0);
    }
}

void test_rx_tx(void) {

    for (int i = 0; i < 4; i++) {
        write_scratch(i, 0x33333333);
    }

    // Use UART gpios
    gpio_intf__DATA_CTRL_t gpio_intf_11; // GPIO 11
    gpio_intf__DATA_CTRL_t gpio_intf_24; // GPIO 24

    gpio_intf_11.w =
        read_gpio(11, (SMC_TOP_GPIO_INTF_DATA_CTRL_BASE_ADDR(0) - SMC_TOP_GPIO_INTF_BASE_ADDR(0)));
    gpio_intf_24.w =
        read_gpio(24, (SMC_TOP_GPIO_INTF_DATA_CTRL_BASE_ADDR(0) - SMC_TOP_GPIO_INTF_BASE_ADDR(0)));

    gpio_intf_24.f.enable_rx_tx = 2; // 2'b10: TX enabled - pad2core_en
    gpio_intf_24.f.interface_enable = 1;

    gpio_intf_11.f.enable_rx_tx = 1; // 2'b01: RX enabled - core2pad_en
    gpio_intf_11.f.interface_enable = 1;
    gpio_intf_11.f.core2pad = 0;

    write_gpio(24, (SMC_TOP_GPIO_INTF_DATA_CTRL_BASE_ADDR(0) - SMC_TOP_GPIO_INTF_BASE_ADDR(0)),
               gpio_intf_24.w);
    write_gpio(11, (SMC_TOP_GPIO_INTF_DATA_CTRL_BASE_ADDR(0) - SMC_TOP_GPIO_INTF_BASE_ADDR(0)),
               gpio_intf_11.w);

    uint32_t read_data_24 =
        read_gpio(24, (SMC_TOP_GPIO_INTF_DATA_CTRL_BASE_ADDR(0) -
                       SMC_TOP_GPIO_INTF_BASE_ADDR(
                           0))); // GPIO 24 should see the core2pad = 0 propagate on pad2core

    // Check is the MSB is 1, fail if not
    if ((read_data_24 & PAD2SOC_MASK) == 1) {
        test_fail(0);
    }
}

int main(void) {

    // Test the core2pad value can be set and read properly for all gpios
    test_rw_core2pad();

    // Test the read filter, positive and negative tests by changing the prot value
    test_read_filter();

    // Test the write filter, positive and negative tests by changing the prot value
    test_write_filter();

    // Test the pad2core value by hooking up two GPIOs together
    test_rx_tx();

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