/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

#include <stdint.h>

#include "smc_io.h"
#include "smc_test.h"

int main(void) {

    // Expected first/last words of ROM banks 1..3 (preloaded contents scrambled by the efuse
    // values); confirms each bank decodes and the endian flip.
    const uint64_t bank_size = 0x8000;
    const uint64_t start_range_data[4] = {0x1, 0xD19DBAEFCAFED00D, 0xB112AB61F99BCCDD,
                                          0xF0E1D2C3B4A59687};
    const uint64_t end_range_data[4] = {0x1, 0xE4B972C1F03D8A55, 0x790DF15B3C8E2A64,
                                        0x790DF15B3C8E2A64};

    // Bank Decode and Endian Flip Validation:
#ifdef ROM_EFUSE_BITS_SCRATCH_TRACE
    uint32_t top_half, bottom_half;
#endif
    int i;
    // Skip bank 0 because DV Rom Resides in Bank 0 and is already validated
    for (i = 1; i < 4; i++) {
        uint64_t rom_start_bank_data, rom_end_bank_data;

        rom_start_bank_data = read_reg_64(SMC_TOP_SPM_ROM_MEMORY_BASE_ADDR + (bank_size * i));
        rom_end_bank_data =
            read_reg_64(SMC_TOP_SPM_ROM_MEMORY_BASE_ADDR + (bank_size * (i + 1)) - 0x8);

        /* Scratch 0-3 are the framework's own channels, not spare debug space.
         * smc_test.h reserves 0 for the pass/fail verdict (TEST_STATUS_SCRATCH,
         * which monitor_test polls against TEST_PASS/TEST_FAIL), 1 for FW
         * status, 2 for ERROR_STATUS_REG and 3 for ERROR_COUNT_REG/SEED_REG.
         *
         * Publishing DUT-read ROM words into them let the DUT decide the
         * verdict before the compares below ever ran: a bank returning
         * 0xacafaca1 in its top word resolves the gate green, and 0xffffffff --
         * the classic undriven-or-decode-error read -- resolves it as a failure
         * with nothing attributing it. Off by default so the verdict channel
         * carries only the verdict; define ROM_EFUSE_BITS_SCRATCH_TRACE to get
         * the words back for debugging, accepting that hazard. */
#ifdef ROM_EFUSE_BITS_SCRATCH_TRACE
        top_half = (rom_start_bank_data >> 32) & 0xFFFFFFFF; // Top 32 bits
        bottom_half = rom_start_bank_data & 0xFFFFFFFF;      // Bottom 32 bits

        write_scratch(0, top_half);
        write_scratch(1, bottom_half);

        top_half = (rom_end_bank_data >> 32) & 0xFFFFFFFF; // Top 32 bits
        bottom_half = rom_end_bank_data & 0xFFFFFFFF;      // Bottom 32 bits

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
