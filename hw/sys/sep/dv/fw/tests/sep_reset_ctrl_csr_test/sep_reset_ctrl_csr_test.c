/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/*******************************************************************************
 * SEP Reset Controller CSR Sanity Test
 *
 * This test verifies the sep_reset_ctrl CSR is correctly implemented.
 *
 * SW_RESET_N bit layout:
 *   bit 4 = kmac_sw_rst_n  (default 1, released)
 *   bit 3 = hmac_sw_rst_n  (default 1, released)
 *   bit 2 = aes_sw_rst_n   (default 1, released)
 *   bit 1 = otbn_sw_rst_n  (default 1, released)
 *   bit 0 = km_sw_rst_n    (default 0, held in reset)
 *
 * Default value: 0x1E = 0b11110
 *
 * Copyright 2026 Tenstorrent Inc.
 ******************************************************************************/

#include <stdio.h>
#include <stdint.h>
#include "och_sep_common.h"
#include "sep.h" // generated register address/mask/default defines
#include "test_completion.h"
#include "sep_outbound_filter.h"
#include "nmi.h"

void reset_ctrl_nmi_handler(void) {
    uint32_t prev = READ_REG(OCH_SEP_TOP_SEP_SCRATCH_COLD_SCRATCH_BASE_ADDR(6));
    WRITE_REG(OCH_SEP_TOP_SEP_SCRATCH_COLD_SCRATCH_BASE_ADDR(6), prev + 1);

    uint32_t mdseac;
    __asm__ volatile("csrr %0, 0xFC0" : "=r"(mdseac));
    printf("NMI: mdseac = 0x%08x\n", mdseac);

    __asm__ volatile("csrw 0xBC0, zero");
}

int main(void) {
    sep_outbound_filter_init();

    printf("SEP Reset Controller CSR Sanity Test\n");
    printf("====================================\n\n");

    // setup nmi handler
    printf("//Set up NMI handler\n");

    WRITE_REG(OCH_SEP_TOP_SEP_SCRATCH_COLD_SCRATCH_BASE_ADDR(6), 0);
    nmi_register_handler(reset_ctrl_nmi_handler);
    nmi_set_vector_reg();
    nmi_lock_vector_reg();

    printf("SUCCESS: NMI handler set up\n");
    /*
     * Step 1: Read the SW_RESET_N register and print the values
     */
    printf("Reading SW_RESET_N register...\n");
    uint32_t sw_reset_n = READ_REG(OCH_SEP_TOP_SEP_RESET_CTRL_SW_RESET_N_BASE_ADDR);
    printf("SW_RESET_N value: 0x%08x\n", sw_reset_n);

    if (sw_reset_n != 0x1eu) {
        printf("ERROR: SW_RESET_N default is not 0x%08x\n", 0x1eu);
        test_fail(1);
    }

    /*
     * Step 2: Trace each IP's reset wire end-to-end.
     *
     * For each writable reset bit:
     *   a) Write a non-zero value into a R/W register inside the IP
     *      (the "probe" register, default 0).
     *   b) Read it back to confirm the IP accepted the write.
     *   c) Toggle ONLY that bit of SW_RESET_N to assert just this IP's reset.
     *   d) Release the reset by restoring SW_RESET_N to default.
     *   e) Re-read the probe register; it must be 0 again because the IP
     *      saw its rst_ni go low and cleared its internal flops.
     *
     * If the probe still holds the value after the toggle, the reset
     * wire did not actually reach the IP.
     *
     * KM is skipped because it cannot be brought out of reset in this test case.
     */
    struct {
        const char *name;
        uint32_t bit_mask;
        uint32_t probe_addr;
        uint32_t write_val;        // value to write to the probe
        uint32_t expect_after_rst; // probe value expected after reset pulse
    } reset_bits[] = {
        {"otbn", (1u << 1), OCH_SEP_TOP_OTBN_NONE_INTR_ENABLE_BASE_ADDR, 0x00000001,
         OTBN__NONE__INTR_ENABLE__DONE_reset},
        {"aes", (1u << 2), OCH_SEP_TOP_AES_NONE_CTRL_AUX_REGWEN_BASE_ADDR, 0x00000000,
         AES__NONE__CTRL_AUX_REGWEN__CTRL_AUX_REGWEN_reset},
        {"hmac", (1u << 3), OCH_SEP_TOP_HMAC_NONE_INTR_ENABLE_BASE_ADDR, 0x00000007,
         HMAC__NONE__INTR_ENABLE__HMAC_DONE_reset},
        {"kmac", (1u << 4), OCH_SEP_TOP_KMAC_NONE_INTR_ENABLE_BASE_ADDR, 0x00000007,
         KMAC__NONE__INTR_ENABLE__KMAC_DONE_reset},
    };

    for (size_t i = 0; i < sizeof(reset_bits) / sizeof(reset_bits[0]); i++) {
        const char *name = reset_bits[i].name;
        uint32_t bit_mask = reset_bits[i].bit_mask;
        uint32_t probe_addr = reset_bits[i].probe_addr;
        uint32_t write_val = reset_bits[i].write_val;
        uint32_t expect_after_rst = reset_bits[i].expect_after_rst;
        uint32_t asserted = 0x1eu & ~bit_mask;

        printf("Step 2.%u: %s - writing 0x%08x to 0x%08x...\n", (unsigned)i, name, write_val,
               probe_addr);
        WRITE_REG(probe_addr, write_val);
        uint32_t rd_written = READ_REG(probe_addr);
        if (rd_written != write_val) {
            printf("ERROR: %s probe readback - got 0x%08x, expected 0x%08x\n", name, rd_written,
                   write_val);
            test_fail(1);
        }

        printf("Step 2.%u: %s - pulsing reset (SW_RESET_N <- 0x%08x then 0x%08x)...\n", (unsigned)i,
               name, asserted, 0x1eu);
        WRITE_REG(OCH_SEP_TOP_SEP_RESET_CTRL_SW_RESET_N_BASE_ADDR, asserted);
        WRITE_REG(OCH_SEP_TOP_SEP_RESET_CTRL_SW_RESET_N_BASE_ADDR, 0x1eu);

        uint32_t rd_after = READ_REG(probe_addr);
        if (rd_after != expect_after_rst) {
            printf("ERROR: %s probe did not reset - got 0x%08x, expected 0x%08x\n", name, rd_after,
                   expect_after_rst);
            test_fail(1);
        }

        printf("%s reset wire OK\n", name);
    }

    /*
     * Step 3: Sanity-check SW_RESET_N ended at its default
     */
    uint32_t sw_reset_n_restored = READ_REG(OCH_SEP_TOP_SEP_RESET_CTRL_SW_RESET_N_BASE_ADDR);
    printf("Final SW_RESET_N value: 0x%08x\n", sw_reset_n_restored);
    if (sw_reset_n_restored != 0x1eu) {
        printf("ERROR: SW_RESET_N is not at default 0x%08x after test\n", 0x1eu);
        test_fail(1);
    }

    /*
     * Step 4: Probe just past the sep_reset_ctrl window (0x10803008+).
     * The xbar window is 0x8 bytes, so this access should be caught by
     * the xbar's decode-error path.
     */
    const uint32_t bad_addr = OCH_SEP_TOP_SEP_RESET_CTRL_BASE_ADDR + 0x8;

    printf("Step 4: probing unmapped gap at 0x%08x...\n", bad_addr);
    printf("Step 4: WRITE 0xDEADBEEF -> 0x%08x\n", bad_addr);
    WRITE_REG(bad_addr, 0xDEADBEEF);
    printf("Step 4: WRITE returned\n");

    printf("Step 4: READ <- 0x%08x\n", bad_addr);
    uint32_t bad_rd = READ_REG(bad_addr + 0x8);
    printf("Step 4: READ returned 0x%08x\n", bad_rd);

    uint32_t nmi_count = READ_REG(OCH_SEP_TOP_SEP_SCRATCH_COLD_SCRATCH_BASE_ADDR(6));
    printf("Step 4: NMI fired %u times (expected 2 from bad write and read)\n", nmi_count);
    if (nmi_count != 2) {
        printf("ERROR: expected 2 NMI from Step 4, got %u\n", nmi_count);
        test_fail(1);
    }

    printf("\n*** SEP Reset Controller CSR Sanity Test PASSED ***\n");
    test_pass(0);
    // Keep CPU alive after signaling completion.
    while (1) {
        __asm__("wfi");
    }
}
