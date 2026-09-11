/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/*******************************************************************************
 * SEP Reset Controller CSR Sanity Test
 *
 * This test verifies the sep_reset_ctrl CSR and the sw-reset isolation
 * sequencing through the AXI-Lite isolates in sep_crypto_axi_interconnect.
 * For each accelerator (OTBN, AES, HMAC, KMAC):
 *
 *   a) Probe write/readback proves the port is open and the IP is alive.
 *   b) Assert only that IP's SW_RESET_N bit and HOLD it.
 *   c) Access the IP while held in reset: the isolate must terminate the
 *      write and the read with SLVERR (one bus-error NMI each) instead of
 *      hanging the fabric.
 *   d) While held in reset, read a different accelerator's register to
 *      prove the other ports are unaffected.
 *   e) Release the reset, then read the probe register back: the port
 *      must reopen (no NMI) and the probe must be at its reset default,
 *      proving the reset wire reached the IP.
 *
 * SW_RESET_N bit layout:
 *   bit 5 = trng_sw_rst_n  (default 1, released)
 *   bit 4 = kmac_sw_rst_n  (default 1, released)
 *   bit 3 = hmac_sw_rst_n  (default 1, released)
 *   bit 2 = aes_sw_rst_n   (default 1, released)
 *   bit 1 = otbn_sw_rst_n  (default 1, released)
 *   bit 0 = km_sw_rst_n    (default 0, held in reset)
 *
 * Default value: 0x3E = 0b111110
 *
 * KM is skipped because it cannot be brought out of reset in this test case.
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

#define SW_RESET_N_DEFAULT 0x3eu
#define SW_RESET_N_TRNG_BIT (1u << 5)

void reset_ctrl_nmi_handler(void) {
    uint32_t prev = READ_REG(OCH_SEP_TOP_SEP_SCRATCH_COLD_SCRATCH_BASE_ADDR(6));
    WRITE_REG(OCH_SEP_TOP_SEP_SCRATCH_COLD_SCRATCH_BASE_ADDR(6), prev + 1);

    uint32_t mdseac;
    __asm__ volatile("csrr %0, 0xFC0" : "=r"(mdseac));
    printf("NMI: mdseac = 0x%08x\n", mdseac);

    __asm__ volatile("csrw 0xBC0, zero");
}

static uint32_t nmi_count(void) {
    return READ_REG(OCH_SEP_TOP_SEP_SCRATCH_COLD_SCRATCH_BASE_ADDR(6));
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

    if (sw_reset_n != SW_RESET_N_DEFAULT) {
        printf("ERROR: SW_RESET_N default is not 0x%08x\n", SW_RESET_N_DEFAULT);
        test_fail(1);
    }

    /*
     * Step 2: Per-accelerator isolate/reset/release sequence (see header).
     *
     * cross_addr is a register in a DIFFERENT accelerator, read while this
     * one is held in reset to prove the other ports stay open. It is chosen
     * as the previous entry's probe register, which at that point in the
     * sequence is back at its reset default.
     */
    struct {
        const char *name;
        uint32_t bit_mask;
        uint32_t probe_addr;
        uint32_t write_val;     // value to write to the probe
        uint32_t probe_default; // probe value after reset
        uint32_t cross_addr;    // other accelerator, must stay live
        uint32_t cross_default;
    } accels[] = {
        {"otbn", (1u << 1), OCH_SEP_TOP_OTBN_INTR_ENABLE_BASE_ADDR, 0x00000001,
         OTBN__INTR_ENABLE__DONE_reset, OCH_SEP_TOP_KMAC_INTR_ENABLE_BASE_ADDR,
         KMAC__INTR_ENABLE__KMAC_DONE_reset},
        {"aes", (1u << 2), OCH_SEP_TOP_AES_CTRL_AUX_REGWEN_BASE_ADDR, 0x00000000,
         AES__CTRL_AUX_REGWEN__CTRL_AUX_REGWEN_reset, OCH_SEP_TOP_OTBN_INTR_ENABLE_BASE_ADDR,
         OTBN__INTR_ENABLE__DONE_reset},
        {"hmac", (1u << 3), OCH_SEP_TOP_HMAC_INTR_ENABLE_BASE_ADDR, 0x00000007,
         HMAC__INTR_ENABLE__HMAC_DONE_reset, OCH_SEP_TOP_AES_CTRL_AUX_REGWEN_BASE_ADDR,
         AES__CTRL_AUX_REGWEN__CTRL_AUX_REGWEN_reset},
        {"kmac", (1u << 4), OCH_SEP_TOP_KMAC_INTR_ENABLE_BASE_ADDR, 0x00000007,
         KMAC__INTR_ENABLE__KMAC_DONE_reset, OCH_SEP_TOP_HMAC_INTR_ENABLE_BASE_ADDR,
         HMAC__INTR_ENABLE__HMAC_DONE_reset},
    };

    uint32_t expected_nmi = 0;

    for (size_t i = 0; i < sizeof(accels) / sizeof(accels[0]); i++) {
        const char *name = accels[i].name;
        uint32_t bit_mask = accels[i].bit_mask;
        uint32_t asserted = SW_RESET_N_DEFAULT & ~bit_mask;

        /*
         * 2a: probe write/readback - port open, IP alive
         */
        printf("Step 2.%u.a: %s - writing 0x%08x to 0x%08x...\n", (unsigned)i, name,
               accels[i].write_val, accels[i].probe_addr);
        WRITE_REG(accels[i].probe_addr, accels[i].write_val);
        uint32_t rd_written = READ_REG(accels[i].probe_addr);
        if (rd_written != accels[i].write_val) {
            printf("ERROR: %s probe readback - got 0x%08x, expected 0x%08x\n", name, rd_written,
                   accels[i].write_val);
            test_fail(1);
        }

        /*
         * 2b: assert and HOLD this accelerator's reset. The isolate FSM
         * drains the (idle) port, then asserts the wrapper reset. The
         * SW_RESET_N readback gives the sequencing time to complete.
         */
        printf("Step 2.%u.b: %s - asserting reset (SW_RESET_N <- 0x%08x)...\n", (unsigned)i, name,
               asserted);
        WRITE_REG(OCH_SEP_TOP_SEP_RESET_CTRL_SW_RESET_N_BASE_ADDR, asserted);
        uint32_t rd_rst = READ_REG(OCH_SEP_TOP_SEP_RESET_CTRL_SW_RESET_N_BASE_ADDR);
        if (rd_rst != asserted) {
            printf("ERROR: SW_RESET_N readback - got 0x%08x, expected 0x%08x\n", rd_rst, asserted);
            test_fail(1);
        }

        /*
         * 2c: access the held-in-reset accelerator. The isolate must
         * terminate the write and the read with SLVERR (one bus-error NMI
         * each) instead of hanging the fabric. D-bus errors are IMPRECISE
         * on VeeR: the NMI lands many cycles after the access, so the two
         * accesses are spaced by prints and the count is checked after
         * each, not back-to-back.
         */
        printf("Step 2.%u.c: %s - poking isolated port (expect 2 NMIs)...\n", (unsigned)i, name);
        WRITE_REG(accels[i].probe_addr, accels[i].write_val);
        printf("Step 2.%u.c: %s - isolated WRITE returned\n", (unsigned)i, name);
        expected_nmi++;
        uint32_t count_wr = nmi_count();
        if (count_wr != expected_nmi) {
            printf("ERROR: %s isolated-write NMI count - got %u, expected %u\n", name, count_wr,
                   expected_nmi);
            test_fail(1);
        }

        uint32_t rd_isolated = READ_REG(accels[i].probe_addr);
        printf("Step 2.%u.c: %s - isolated READ returned 0x%08x\n", (unsigned)i, name, rd_isolated);
        expected_nmi++;
        uint32_t count_rd = nmi_count();
        if (count_rd != expected_nmi) {
            printf("ERROR: %s isolated-read NMI count - got %u, expected %u\n", name, count_rd,
                   expected_nmi);
            test_fail(1);
        }

        /*
         * 2d: other accelerator ports must stay live while this one is held
         * in reset (correct read value, no NMI).
         */
        printf("Step 2.%u.d: %s - cross-checking live port at 0x%08x...\n", (unsigned)i, name,
               accels[i].cross_addr);
        uint32_t cross_rd = READ_REG(accels[i].cross_addr);
        if (cross_rd != accels[i].cross_default) {
            printf("ERROR: %s cross-check read - got 0x%08x, expected 0x%08x\n", name, cross_rd,
                   accels[i].cross_default);
            test_fail(1);
        }
        if (nmi_count() != expected_nmi) {
            printf("ERROR: %s cross-check raised an unexpected NMI\n", name);
            test_fail(1);
        }

        /*
         * 2e: release the reset. The SW_RESET_N readback covers the
         * StRelease hold-off before the port reopens. The probe must read
         * its default (reset reached the IP) without an NMI (port reopened).
         */
        printf("Step 2.%u.e: %s - releasing reset...\n", (unsigned)i, name);
        WRITE_REG(OCH_SEP_TOP_SEP_RESET_CTRL_SW_RESET_N_BASE_ADDR, SW_RESET_N_DEFAULT);
        (void)READ_REG(OCH_SEP_TOP_SEP_RESET_CTRL_SW_RESET_N_BASE_ADDR);

        uint32_t rd_after = READ_REG(accels[i].probe_addr);
        if (rd_after != accels[i].probe_default) {
            printf("ERROR: %s probe after reset - got 0x%08x, expected 0x%08x\n", name, rd_after,
                   accels[i].probe_default);
            test_fail(1);
        }
        if (nmi_count() != expected_nmi) {
            printf("ERROR: %s post-release access raised an unexpected NMI\n", name);
            test_fail(1);
        }

        printf("%s isolate/reset/release OK\n", name);
    }

    /*
     * Step 3: the shared TRNG reset coordinates all three CSR ports. Seed a
     * writable register on each port, hold reset, prove every new access gets
     * SLVERR, prove an unrelated AES port stays alive, then release and prove
     * all three registers were reset.
     */
    struct {
        const char *name;
        uint32_t probe_addr;
        uint32_t write_val;
    } trng_ports[] = {
        {"esrc", OCH_SEP_TOP_ENTROPY_SOURCE_DEBUG_CTRL_BASE_ADDR, 0x00000001u},
        {"csrng", OCH_SEP_TOP_CSRNG_INTR_ENABLE_BASE_ADDR, 0x00000001u},
        {"edn", OCH_SEP_TOP_EDN_INTR_ENABLE_BASE_ADDR, 0x00000001u},
    };

    for (size_t i = 0; i < sizeof(trng_ports) / sizeof(trng_ports[0]); i++) {
        WRITE_REG(trng_ports[i].probe_addr, trng_ports[i].write_val);
        uint32_t rd = READ_REG(trng_ports[i].probe_addr);
        if (rd != trng_ports[i].write_val) {
            printf("ERROR: TRNG %s pre-reset probe got 0x%08x, expected 0x%08x\n",
                   trng_ports[i].name, rd, trng_ports[i].write_val);
            test_fail(1);
        }
    }

    uint32_t trng_asserted = SW_RESET_N_DEFAULT & ~SW_RESET_N_TRNG_BIT;
    WRITE_REG(OCH_SEP_TOP_SEP_RESET_CTRL_SW_RESET_N_BASE_ADDR, trng_asserted);
    (void)READ_REG(OCH_SEP_TOP_SEP_RESET_CTRL_SW_RESET_N_BASE_ADDR);

    uint32_t aes_live = READ_REG(OCH_SEP_TOP_AES_CTRL_AUX_REGWEN_BASE_ADDR);
    if (aes_live != AES__CTRL_AUX_REGWEN__CTRL_AUX_REGWEN_reset || nmi_count() != expected_nmi) {
        printf("ERROR: AES sibling was affected by TRNG-only reset\n");
        test_fail(1);
    }

    for (size_t i = 0; i < sizeof(trng_ports) / sizeof(trng_ports[0]); i++) {
        WRITE_REG(trng_ports[i].probe_addr, trng_ports[i].write_val);
        printf("TRNG %s isolated WRITE returned\n", trng_ports[i].name);
        expected_nmi++;
        if (nmi_count() != expected_nmi) {
            printf("ERROR: TRNG %s isolated write did not raise NMI\n", trng_ports[i].name);
            test_fail(1);
        }

        (void)READ_REG(trng_ports[i].probe_addr);
        printf("TRNG %s isolated READ returned\n", trng_ports[i].name);
        expected_nmi++;
        if (nmi_count() != expected_nmi) {
            printf("ERROR: TRNG %s isolated read did not raise NMI\n", trng_ports[i].name);
            test_fail(1);
        }
    }

    WRITE_REG(OCH_SEP_TOP_SEP_RESET_CTRL_SW_RESET_N_BASE_ADDR, SW_RESET_N_DEFAULT);
    (void)READ_REG(OCH_SEP_TOP_SEP_RESET_CTRL_SW_RESET_N_BASE_ADDR);
    for (size_t i = 0; i < sizeof(trng_ports) / sizeof(trng_ports[0]); i++) {
        uint32_t rd = READ_REG(trng_ports[i].probe_addr);
        if (rd != 0u || nmi_count() != expected_nmi) {
            printf("ERROR: TRNG %s did not reopen at reset default (0x%08x)\n", trng_ports[i].name,
                   rd);
            test_fail(1);
        }
    }
    printf("TRNG three-port isolate/reset/release OK\n");

    /*
     * Step 4: Sanity-check SW_RESET_N ended at its default
     */
    uint32_t sw_reset_n_restored = READ_REG(OCH_SEP_TOP_SEP_RESET_CTRL_SW_RESET_N_BASE_ADDR);
    printf("Final SW_RESET_N value: 0x%08x\n", sw_reset_n_restored);
    if (sw_reset_n_restored != SW_RESET_N_DEFAULT) {
        printf("ERROR: SW_RESET_N is not at default 0x%08x after test\n", SW_RESET_N_DEFAULT);
        test_fail(1);
    }

    /*
     * Step 5: Probe just past the sep_reset_ctrl window (0x10803008+).
     * The xbar window is 0x8 bytes, so this access should be caught by
     * the xbar's decode-error path.
     */
    const uint32_t bad_addr = OCH_SEP_TOP_SEP_RESET_CTRL_BASE_ADDR + 0x8;

    printf("Step 5: probing unmapped gap at 0x%08x...\n", bad_addr);
    printf("Step 5: WRITE 0xDEADBEEF -> 0x%08x\n", bad_addr);
    WRITE_REG(bad_addr, 0xDEADBEEF);
    printf("Step 5: WRITE returned\n");

    printf("Step 5: READ <- 0x%08x\n", bad_addr);
    uint32_t bad_rd = READ_REG(bad_addr + 0x8);
    printf("Step 5: READ returned 0x%08x\n", bad_rd);

    expected_nmi += 2;
    uint32_t final_count = nmi_count();
    printf("Step 5: NMI count %u (expected %u: 2 per isolated accelerator/TRNG port + 2 from "
           "bad write and read)\n",
           final_count, expected_nmi);
    if (final_count != expected_nmi) {
        printf("ERROR: expected %u NMIs total, got %u\n", expected_nmi, final_count);
        test_fail(1);
    }

    printf("\n*** SEP Reset Controller CSR Sanity Test PASSED ***\n");
    test_pass(0);
    // Keep CPU alive after signaling completion.
    while (1) {
        __asm__("wfi");
    }
}
