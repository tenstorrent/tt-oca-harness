/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

#include <stdint.h>

#include "smc_io.h"
#include "smc_test.h"

int main(void) {

    // Expected first/middle/last words of the preloaded boot ROM image.

    const uint64_t first_addr = 0xC0040000;
    const uint64_t first_data = 0x000005177c105073;

    const uint64_t middle_addr = 0xC0048008;
    const uint64_t middle_data = 0xab6d7208e711165a;

    const uint64_t last_addr = 0xC005FFF8;
    const uint64_t last_data = 0xabcd123456789fc4;

    uint64_t rom_data_first;

    rom_data_first = read_reg_64(first_addr);

    uint32_t top_half = (rom_data_first >> 32) & 0xFFFFFFFF;
    uint32_t bottom_half = rom_data_first & 0xFFFFFFFF;

    write_scratch(0, top_half);
    write_scratch(1, bottom_half);

    if (rom_data_first != first_data) {
        test_fail(0);
    }

    uint64_t rom_data_middle;

    rom_data_middle = read_reg_64(middle_addr);

    top_half = (rom_data_middle >> 32) & 0xFFFFFFFF;
    bottom_half = rom_data_middle & 0xFFFFFFFF;

    write_scratch(2, top_half);
    write_scratch(3, bottom_half);

    if (rom_data_middle != middle_data) {
        test_fail(0);
    }

    uint64_t rom_data_last;

    rom_data_last = read_reg_64(last_addr);

    top_half = (rom_data_last >> 32) & 0xFFFFFFFF;
    bottom_half = rom_data_last & 0xFFFFFFFF;

    write_scratch(2, top_half);
    write_scratch(3, bottom_half);

    if (rom_data_last != last_data) {
        test_fail(0);
    }

    test_pass(0);
}

int secondary_main(void) {

    return main();
}
