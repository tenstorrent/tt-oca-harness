/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/*
 * sep_smu_aes - SMU-level SEP AES functional smoke test.
 *
 * Runs a single AES-128 ECB encryption known-answer test, then parks in
 * pass/fail loops for cocotb PC classification.
 */

#include <stdint.h>

#include "sep_outbound_filter.h"
#include "sep_aes_init.h"
#include "sep_entropy.h"
#include "aes_test_util.h"

static const uint32_t k_key[4] = {0x16157e2bu, 0xa6d2ae28u, 0x8815f7abu, 0x3c4fcf09u};

static const uint32_t k_iv[4] = {0, 0, 0, 0};

static const uint32_t k_plaintext[4] = {0xe2bec16bu, 0x969f402eu, 0x117e3de9u, 0x2a179373u};

static const uint32_t k_ciphertext[4] = {0xb47bd73au, 0x60367a0du, 0xf3ca9ea8u, 0x97ef6624u};

static int run_aes_ecb_kat(void) {
    uint32_t out[4];

    if (sep_aes_sw_reset_release() != 0) return -1;
    if (wait_for_idle() != 0) return -2;
    if (configure_aes(0x1u, 0x1u, k_key, k_iv) != 0) return -3;
    if (wait_for_input_ready() != 0) return -4;

    write_data_in(k_plaintext);
    if (wait_for_output_valid() != 0) return -5;
    read_data_out(out);

    if (compare_block(out, k_ciphertext, "smu_aes_ecb_128") != 0) return -6;
    if (check_no_alert("smu_aes_ecb_128") != 0) return -7;

    cleanup_aes();
    return 0;
}

__attribute__((used, noinline, noreturn)) void smu_sep_aes_pass_loop(void) {
    while (1) {
        __asm__ volatile("wfi");
    }
}

__attribute__((used, noinline, noreturn)) void smu_sep_aes_fail_loop(void) {
    while (1) {
        __asm__ volatile("wfi");
    }
}

/* Separate from the AES fail loop: an entropy bring-up that never completed is a
 * missing prerequisite, not an AES defect, and the testbench classifies the run
 * by which loop the CPU parks in. */
__attribute__((used, noinline, noreturn)) void smu_sep_aes_fail_entropy_loop(void) {
    while (1) {
        __asm__ volatile("wfi");
        __asm__ volatile("nop");
    }
}

int main(void) {
    sep_outbound_filter_init();

    /* OpenTitan AES reseeds its masking PRNG from crypto-EDN, so wait_for_idle()
     * never clears unless the entropy stack is up. sep_entropy_bringup() skips
     * itself when the boot gate is already open, so this is safe under
     * hw/sys/sep/dv, where a cocotb sequence may have done the bring-up first. */
    if (sep_entropy_bringup() != SEP_ENTROPY_OK) {
        smu_sep_aes_fail_entropy_loop();
    }

    if (run_aes_ecb_kat() == 0) {
        smu_sep_aes_pass_loop();
    } else {
        smu_sep_aes_fail_loop();
    }
}
