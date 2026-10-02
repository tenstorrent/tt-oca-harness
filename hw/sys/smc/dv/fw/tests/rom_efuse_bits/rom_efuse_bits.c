/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

#include <stdint.h>

#include "smc_io.h"
#include "smc_test.h"

int main(void) {

    // Expected first and last words of ROM banks 1 to 3; index 0 is unused.
    const uint64_t bank_size = 0x8000;
    const uint64_t start_range_data[4] = {0x1, 0xD19DBAEFCAFED00D, 0xB112AB61F99BCCDD,
                                          0xF0E1D2C3B4A59687};
    const uint64_t end_range_data[4] = {0x1, 0xE4B972C1F03D8A55, 0x790DF15B3C8E2A64,
                                        0x790DF15B3C8E2A64};

#ifdef ROM_EFUSE_BITS_SCRATCH_TRACE
    uint32_t top_half, bottom_half;
#endif
    int i;
    // Bank 0 holds the DV ROM and is not checked here.
    for (i = 1; i < 4; i++) {
        uint64_t rom_start_bank_data, rom_end_bank_data;

        rom_start_bank_data = read_reg_64(SMC_TOP_SPM_ROM_MEMORY_BASE_ADDR + (bank_size * i));
        rom_end_bank_data =
            read_reg_64(SMC_TOP_SPM_ROM_MEMORY_BASE_ADDR + (bank_size * (i + 1)) - 0x8);

        /* Debug only: the trace overwrites the verdict, status and error
         * scratch registers with ROM words, so a ROM word can be taken as the
         * test verdict before the compares below run. */
#ifdef ROM_EFUSE_BITS_SCRATCH_TRACE
        top_half = (rom_start_bank_data >> 32) & 0xFFFFFFFF;
        bottom_half = rom_start_bank_data & 0xFFFFFFFF;

        write_scratch(0, top_half);
        write_scratch(1, bottom_half);

        top_half = (rom_end_bank_data >> 32) & 0xFFFFFFFF;
        bottom_half = rom_end_bank_data & 0xFFFFFFFF;

        write_scratch(2, top_half);
        write_scratch(3, bottom_half);
#endif

        if (rom_start_bank_data != start_range_data[i]) {
            test_fail(0);
        }

        if (rom_end_bank_data != end_range_data[i]) {
            test_fail(0);
        }
    }

    test_pass(0);

    while (true) {
        __asm__("wfi");
    }

    return 0;
}

int secondary_main(void) {

    return main();
}
