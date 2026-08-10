/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

#ifndef GPIO_SANITY_SEQUENCE_H
#define GPIO_SANITY_SEQUENCE_H

/* GPIO sanity sequence for the cpu_traffic super-loop. */

#include <stdint.h>

#include "metal/atomic.h"
#include "metal/lock.h"
#include "smc_io.h"
#include "smc_test.h"

#define BLOCKED_REQUEST 0xbadcab1e
#define PAD2SOC_MASK 0x80000000

#define GPIO_INTF_DATA_CTRL_OFFSET \
    (SMC_TOP_GPIO_INTF_DATA_CTRL_BASE_ADDR(0) - SMC_TOP_GPIO_INTF_BASE_ADDR(0))
#define GPIO_INTF_ACCESS_FILTER_OFFSET \
    (SMC_TOP_GPIO_INTF_ACCESS_FILTER_BASE_ADDR(0) - SMC_TOP_GPIO_INTF_BASE_ADDR(0))

const uint32_t NUM_GPIOS = 65;       // GPIO_0 through GPIO_64
// GPIO_61 is cool_reset_in, will reset chip if toggled. This was 64 before the GPIO shrink;
// NUM_GPIOS was updated to 65 at the time but the skip index was not, so the sequence was
// toggling cool_reset_in (and needlessly skipping 64, which is now I3C1 SDA).
const uint32_t gpio_skips[1] = {61};
const uint32_t write_filter_skips[9] = {11, 12, 15, 16, 19,
                                        20, 23, 24, 61}; // UART GPIOs cannot be write-locked
                                                         // write-locking them prevents switching
                                                         // back to LSIO interface for UART sequence
const size_t len_gpio_skips = sizeof(gpio_skips) / sizeof(gpio_skips[0]);
const size_t len_write_filter_skips = sizeof(write_filter_skips) / sizeof(write_filter_skips[0]);

struct gpio_sanity_sequence_globals_s {
    uint64_t locked_gpios_63_0;
    uint64_t locked_gpios_127_64;
};

struct gpio_sanity_sequence_globals_s GPIO_SANITY_SEQUENCE_GLOBALS = {.locked_gpios_63_0 = 0,
                                                                      .locked_gpios_127_64 = 0};

bool check_gpio_skip(int hartid, uint32_t gpio_num, uint32_t num_skips, uint32_t *gpio_skips) {
    for (int i = 0; i < num_skips; i++) {
        if (gpio_num == gpio_skips[i]) {
            info_msg_hex32_s(hartid, "Skipping gpio ", gpio_num);
            return true;
        }
    }
    return false;
}

void set_gpio_wr_locked(uint32_t gpio_num) {
    if (gpio_num < 64) {
        GPIO_SANITY_SEQUENCE_GLOBALS.locked_gpios_63_0 |= ((uint64_t)1 << gpio_num);
    } else {
        GPIO_SANITY_SEQUENCE_GLOBALS.locked_gpios_127_64 |= ((uint64_t)1 << (gpio_num - 64));
    }
}

bool is_gpio_wr_locked(uint32_t gpio_num) {
    if (gpio_num < 64) {
        return ((GPIO_SANITY_SEQUENCE_GLOBALS.locked_gpios_63_0 & ((uint64_t)1 << gpio_num)) != 0);
    } else {
        return ((GPIO_SANITY_SEQUENCE_GLOBALS.locked_gpios_127_64 &
                 ((uint64_t)1 << (gpio_num - 64))) != 0);
    }
}

void test_rw_chip2pad(int hartid, uint32_t gpio_num) {

    info_msg_hex32_s(hartid, "test_rw_chip2pad: Testing GPIO: ", gpio_num);

    gpio_intf__DATA_CTRL_t gpio_data_control;

    uint32_t read_data_control = read_gpio(gpio_num, GPIO_INTF_DATA_CTRL_OFFSET);
    gpio_bad_cab1e_check(hartid, gpio_num, read_data_control);

    gpio_data_control.w = read_data_control;
    gpio_data_control.f.interface_enable = get_random_int() & 0x1;
    gpio_data_control.f.core2pad = get_random_int() & 0x1;

    write_gpio(gpio_num, GPIO_INTF_DATA_CTRL_OFFSET, gpio_data_control.w);

    uint32_t read_data_control_updated = read_gpio(gpio_num, GPIO_INTF_DATA_CTRL_OFFSET);
    gpio_bad_cab1e_check(hartid, gpio_num, read_data_control_updated);

    // Setup the expected value
    uint32_t expected_val = gpio_data_control.w;
    if (is_gpio_wr_locked(gpio_num)) {
        info_msg_s(hartid, "test_rw_chip2pad: GPIO is write locked. Expect no change");
        expected_val = read_data_control;
    }
    write_scratch(1, expected_val);
    write_scratch(2, read_data_control_updated);

    if (gpio_num == 74) // TODO update when err slv added
    {
        if (read_data_control_updated != BLOCKED_REQUEST) {
            raise_error_s(hartid, "GPIO index 74 is err slv, should return 0x0badcab1e");
        }
    } else if (expected_val != read_data_control_updated) {
        raise_error_s(hartid, "test_rw_chip2pad: read data control mis-match");
        info_msg_hex32_s(hartid, "Expected: ", expected_val);
        info_msg_hex32_s(hartid, "Actual: ", read_data_control_updated);
    }
}

void test_read_filter(int hartid, uint32_t gpio_num) {

    info_msg_hex32_s(hartid, "test_read_filter: Testing GPIO: ", gpio_num);

    if (is_gpio_wr_locked(gpio_num)) {
        info_msg_s(hartid, "test_read_filter: GPIO is write locked. Skipping");
        return;
    }

    //// Change read permissions on GPIO ////

    gpio_intf__ACCESS_FILTER_t gpio_filter_default;
    gpio_intf__ACCESS_FILTER_t gpio_filter;

    gpio_filter_default.w = read_gpio(gpio_num, GPIO_INTF_ACCESS_FILTER_OFFSET);
    gpio_bad_cab1e_check(hartid, gpio_num, gpio_filter_default.w);

    gpio_filter = gpio_filter_default;
    gpio_filter.f.read_filter_enable = 1;

    gpio_filter.f.arprot_requirement = 2;                                // 3'b010 which is default
    write_gpio(gpio_num, GPIO_INTF_ACCESS_FILTER_OFFSET, gpio_filter.w); // set the new filter

    uint32_t read_data = read_gpio(gpio_num, GPIO_INTF_DATA_CTRL_OFFSET);
    gpio_bad_cab1e_check(hartid, gpio_num, read_data);
    write_scratch(3, read_data);

    if ((read_data == BLOCKED_REQUEST) && (gpio_num != 74)) // TODO update when err slv added
    { // index 74 is dummy "error slv" and is expected to return 0x0badcab1e
        raise_error_s(hartid, "test_read_filter: First Read was blocked");
    }

    // Set prot to be 4
    gpio_filter.f.arprot_requirement = 4;
    write_gpio(gpio_num, GPIO_INTF_ACCESS_FILTER_OFFSET, gpio_filter.w); // set the new filter

    // Try and read - should be blocked
    read_data = read_gpio(gpio_num, GPIO_INTF_DATA_CTRL_OFFSET);
    write_scratch(4, read_data);

    if (read_data != BLOCKED_REQUEST) {
        raise_error_s(hartid, "test_read_filter: Second Read was not blocked");
    }

    // Return gpio_filter to default
    gpio_filter_default.w;
    write_gpio(gpio_num, GPIO_INTF_ACCESS_FILTER_OFFSET, gpio_filter_default.w);

    read_data = read_gpio(gpio_num, GPIO_INTF_ACCESS_FILTER_OFFSET);
    gpio_bad_cab1e_check(hartid, gpio_num, read_data);
    write_scratch(5, read_data);

    if ((gpio_num == 74)) // TODO update when err slv added
    {
        if (read_data != BLOCKED_REQUEST) {
            raise_error_s(hartid, "GPIO index 74 is err slv, should return 0x0badcab1e");
        }
    } else if (read_data != gpio_filter_default.w) {
        raise_error_s(hartid, "test_read_filter: Filter was not re-written back to default");
        info_msg_hex32_s(hartid, "Expected: ", gpio_filter_default.w);
        info_msg_hex32_s(hartid, "Actual: ", read_data);
    }
}

void test_write_filter(int hartid, uint32_t gpio_num) {

    if (is_gpio_wr_locked(gpio_num)) {
        info_msg_s(hartid, "test_write_filter: GPIO is write locked. Skipping");
        return;
    }

    info_msg_hex32_s(hartid, "test_write_filter: Testing GPIO: ", gpio_num);

    gpio_intf__ACCESS_FILTER_t gpio_filter;
    gpio_intf__DATA_CTRL_t gpio_data_control;

    gpio_data_control.w = read_gpio(gpio_num, GPIO_INTF_DATA_CTRL_OFFSET);
    gpio_bad_cab1e_check(hartid, gpio_num, gpio_data_control.w);
    gpio_filter.w = read_gpio(gpio_num, GPIO_INTF_ACCESS_FILTER_OFFSET);
    gpio_bad_cab1e_check(hartid, gpio_num, gpio_filter.w);
    gpio_filter.f.write_filter_enable = 1;
    gpio_filter.f.awprot_requirement = 2;

    write_gpio(gpio_num, GPIO_INTF_ACCESS_FILTER_OFFSET,
               gpio_filter.w); // set the new filter with write filter enabled

    // Read back the filter to check it was written correctly
    uint32_t read_filter = read_gpio(gpio_num, GPIO_INTF_ACCESS_FILTER_OFFSET);
    gpio_bad_cab1e_check(hartid, gpio_num, read_filter);
    if (read_filter != gpio_filter.w) {
        raise_error_s(hartid, "test_write_filter: Filter was not written correctly");
        info_msg_hex32_s(hartid, "Expected: ", gpio_filter.w);
        info_msg_hex32_s(hartid, "Actual: ", read_filter);
    }

    gpio_data_control.f.core2pad = 1;
    gpio_data_control.f.interface_enable = 1;
    write_gpio(gpio_num, GPIO_INTF_DATA_CTRL_OFFSET,
               gpio_data_control.w); // since correct prot (secure transaction), should write
    uint32_t read_data_allowed = read_gpio(gpio_num, GPIO_INTF_DATA_CTRL_OFFSET);
    gpio_bad_cab1e_check(hartid, gpio_num, read_data_allowed);

    if (gpio_num == 74) // TODO update when err slv added
    {
        if (read_data_allowed != BLOCKED_REQUEST) {
            raise_error_s(hartid, "test_write_filter: GPIO index 74 should return 0x0badcab1e");
        }
    } else if (read_data_allowed != gpio_data_control.w) { // should be equal
        raise_error_s(hartid, "test_write_filter: Write was not matching");
    }

    gpio_filter.f.awprot_requirement =
        1; // only transactions with prot = 1 should be allowed to write
    write_gpio(gpio_num, GPIO_INTF_ACCESS_FILTER_OFFSET, gpio_filter.w); // set the new filter

    // Read back the filter to check it was written correctly
    read_filter = read_gpio(gpio_num, GPIO_INTF_ACCESS_FILTER_OFFSET);
    gpio_bad_cab1e_check(hartid, gpio_num, read_filter);
    if (read_filter != gpio_filter.w) {
        raise_error_s(hartid, "test_write_filter: Filter was not written correctly");
        info_msg_hex32_s(hartid, "Expected: ", gpio_filter.w);
        info_msg_hex32_s(hartid, "Actual: ", read_filter);
    }

    gpio_data_control.f.core2pad = 0; // try and write a 0
    write_gpio(gpio_num, GPIO_INTF_DATA_CTRL_OFFSET, gpio_data_control.w);
    uint32_t read_data_unchanged = read_gpio(gpio_num, GPIO_INTF_DATA_CTRL_OFFSET);
    gpio_bad_cab1e_check(hartid, gpio_num, read_data_unchanged);

    if ((gpio_num == 74)) // TODO update when err slv added
    {
        if (read_data_unchanged != BLOCKED_REQUEST) {
            raise_error_s(hartid, "GPIO index 74 is err slv, should return 0x0badcab1e");
        }
    } else if (read_data_unchanged == gpio_data_control.w) {
        raise_error_s(hartid, "test_write_filter: Write was not filtered");
        info_msg_hex32_s(hartid, "Read data: ", read_data_unchanged);
    }

    set_gpio_wr_locked(gpio_num);
}

int gpio_sanity_sequence(int hartid) {
    info_msg_s(hartid, "gpio_sanity_sequence Start");

    uint32_t random_num;
    uint32_t gpio_num;

    gpio_intf__DATA_CTRL_t gpio_data_control;

    // Test the chip2pad value can be set and read properly for all gpios
    do {
        // Randomly pick a GPIO to test, try again if it should be skipped
        random_num = get_random_int();
        gpio_num = random_num % NUM_GPIOS;
    } while (check_gpio_skip(hartid, gpio_num, len_gpio_skips, gpio_skips));

    test_rw_chip2pad(hartid, gpio_num);

    // cleanup by returning to LSIO interface
    gpio_data_control.f.interface_enable = 0x0;
    write_gpio(gpio_num, GPIO_INTF_DATA_CTRL_OFFSET, gpio_data_control.w);

    // Test the read filter, positive and negative tests by changing the prot value
    // Randomly pick a GPIO to test, GPI0 67 (cool_reset_in) can be safely read so no need to check
    // for skip
    random_num = get_random_int();
    gpio_num = random_num % NUM_GPIOS;
    test_read_filter(hartid, gpio_num);

    // cleanup by returning to LSIO interface
    gpio_data_control.f.interface_enable = 0x0;
    write_gpio(gpio_num, GPIO_INTF_DATA_CTRL_OFFSET, gpio_data_control.w);

    // Test the write filter, positive and negative tests by changing the prot value
    do {
        // Randomly pick a GPIO to test, try again if it should be skipped
        random_num = get_random_int();
        gpio_num = random_num % NUM_GPIOS;
    } while (check_gpio_skip(hartid, gpio_num, len_write_filter_skips, write_filter_skips));

    test_write_filter(hartid, gpio_num);

    // cleanup by returning to LSIO interface
    gpio_data_control.f.interface_enable = 0x0;
    write_gpio(gpio_num, GPIO_INTF_DATA_CTRL_OFFSET, gpio_data_control.w);

    info_msg_s(hartid, "gpio_sanity_sequence Done");

    return 0;
}

int gpio_total_sanity_sequence(int hartid) {
    info_msg_s(hartid, "gpio_total_sanity_sequence Start");

    gpio_intf__DATA_CTRL_t gpio_data_control;

    for (int gpio_idx = 0; gpio_idx < NUM_GPIOS; gpio_idx++) {

        if (check_gpio_skip(hartid, gpio_idx, len_gpio_skips, gpio_skips)) {
            continue;
        }

        // Test the chip2pad value can be set and read properly for all gpios
        test_rw_chip2pad(hartid, gpio_idx);

        // Test the read filter, positive and negative tests by changing the prot value
        test_read_filter(hartid, gpio_idx);

        // Test the write filter, positive and negative tests by changing the prot value
        test_write_filter(hartid, gpio_idx);

        // cleanup by returning to LSIO interface
        gpio_data_control.f.interface_enable = 0x0;
        write_gpio(gpio_idx, GPIO_INTF_DATA_CTRL_OFFSET, gpio_data_control.w);
    }

    info_msg_s(hartid, "gpio_total_sanity_sequence Done");

    return 0;
}

#endif /* GPIO_SANITY_SEQUENCE_H */
