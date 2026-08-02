/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/* Copyright 2026 Tenstorrent Inc. */
/**
 * @file test_rom_kdf.c
 * @brief SP 800-108r1 counter-mode KDF firmware tests.
 *
 * Run with:
 *   make run_fw FW_TEST=test_rom_kdf
 */

#include <stddef.h>
#include <stdint.h>

#include "test_common.h"
#include "rom_boot.h"
#include "rom_kdf.h"
#include "rom_sha256.h"

#include "kdf_vectors.h"

/* Skip boot/unrecoverable wipe so the test boots quickly. */
int rom_boot_wipe_enabled(void) {
    return 0;
}
int rom_unrec_wipe_enabled(void) {
    return 0;
}

/* Large test buffers live in SRAM rather than the bounded ROM stack. */
static km_kdf_input_t scratch_input;
static uint8_t output[KM_KDF_OUT_MAX_BITS / 8u];
static uint8_t output_a[ROM_SHA256_DIGEST_SIZE];
static uint8_t output_b[ROM_SHA256_DIGEST_SIZE];
static uint8_t scratch_key[ROM_SHA256_DIGEST_SIZE];

static int bytes_equal(const uint8_t *a, const uint8_t *b, uint32_t length) {
    for (uint32_t i = 0u; i < length; i++) {
        if (a[i] != b[i]) return 0;
    }
    return 1;
}

static void initialize_sensitivity_inputs(void) {
    uint8_t *input_bytes = (uint8_t *)&scratch_input;

    for (uint32_t i = 0u; i < (uint32_t)sizeof(scratch_input); i++)
        input_bytes[i] = (uint8_t)(i ^ 0xa5u);

    for (uint32_t i = 0u; i < (uint32_t)sizeof(scratch_key); i++)
        scratch_key[i] = (uint8_t)(i + 1u);
}

int main(void) {
    TEST_INIT();

    if (!tb_set_timeout(30000000u)) TEST_FAIL("Failed to set test timeout");

    TEST_SUBTEST_START("embedded KDF power-on self-test");
    TEST_ASSERT(rom_kdf_selftest() == 1, "KDF self-test failed");
    TEST_SUBTEST_PASS();

    TEST_SUBTEST_START("shared-specification golden vectors");
    for (size_t i = 0u; i < KDF_NUM_VECTORS; i++) {
        const struct kdf_test_vector *vector = &kdf_test_vectors[i];

        TEST_LOG("  %s", vector->name);
        memcpy(&scratch_input, vector->input, sizeof(scratch_input));
        TEST_ASSERT(rom_kdf_800_108(vector->key, vector->key_len, &scratch_input, output,
                                    vector->out_bits) == 0,
                    "%s: KDF returned failure", vector->name);
        TEST_ASSERT(bytes_equal(output, vector->expected, vector->expected_len),
                    "%s: output mismatch", vector->name);
    }
    TEST_SUBTEST_PASS();

    TEST_SUBTEST_START("KDF input structure layout");
    TEST_ASSERT_EQ(sizeof(km_kdf_input_t), KM_KDF_INPUT_BYTES, "km_kdf_input_t size");
    TEST_ASSERT_EQ(offsetof(km_kdf_input_t, label), KM_KDF_HDR_BYTES, "label offset");
    TEST_ASSERT_EQ(offsetof(km_kdf_input_t, context), KM_KDF_HDR_BYTES + KM_KDF_LABEL_BYTES,
                   "context offset");
    TEST_ASSERT_EQ(offsetof(km_kdf_input_t, entropy),
                   KM_KDF_HDR_BYTES + KM_KDF_LABEL_BYTES + KM_KDF_CONTEXT_BYTES, "entropy offset");
    TEST_SUBTEST_PASS();

    TEST_SUBTEST_START("KDF determinism and input sensitivity");
    initialize_sensitivity_inputs();
    TEST_ASSERT(rom_kdf_800_108(scratch_key, (uint32_t)sizeof(scratch_key), &scratch_input,
                                output_a, 256u) == 0,
                "baseline derivation failed");
    TEST_ASSERT(rom_kdf_800_108(scratch_key, (uint32_t)sizeof(scratch_key), &scratch_input,
                                output_b, 256u) == 0,
                "repeat derivation failed");
    TEST_ASSERT(bytes_equal(output_a, output_b, sizeof(output_a)),
                "identical inputs produced different outputs");

    scratch_input.label[0] ^= 1u;
    TEST_ASSERT(rom_kdf_800_108(scratch_key, (uint32_t)sizeof(scratch_key), &scratch_input,
                                output_b, 256u) == 0,
                "label sensitivity derivation failed");
    TEST_ASSERT(!bytes_equal(output_a, output_b, sizeof(output_a)),
                "label change did not change output");
    scratch_input.label[0] ^= 1u;

    scratch_input.context[0] ^= 1u;
    TEST_ASSERT(rom_kdf_800_108(scratch_key, (uint32_t)sizeof(scratch_key), &scratch_input,
                                output_b, 256u) == 0,
                "context sensitivity derivation failed");
    TEST_ASSERT(!bytes_equal(output_a, output_b, sizeof(output_a)),
                "context change did not change output");
    scratch_input.context[0] ^= 1u;

    scratch_input.entropy[0] ^= 1u;
    TEST_ASSERT(rom_kdf_800_108(scratch_key, (uint32_t)sizeof(scratch_key), &scratch_input,
                                output_b, 256u) == 0,
                "entropy sensitivity derivation failed");
    TEST_ASSERT(!bytes_equal(output_a, output_b, sizeof(output_a)),
                "entropy change did not change output");
    scratch_input.entropy[0] ^= 1u;

    scratch_key[0] ^= 1u;
    TEST_ASSERT(rom_kdf_800_108(scratch_key, (uint32_t)sizeof(scratch_key), &scratch_input,
                                output_b, 256u) == 0,
                "key sensitivity derivation failed");
    TEST_ASSERT(!bytes_equal(output_a, output_b, sizeof(output_a)),
                "key change did not change output");
    scratch_key[0] ^= 1u;
    TEST_SUBTEST_PASS();

    TEST_SUBTEST_START("output length is bound into the PRF");
    TEST_ASSERT(rom_kdf_800_108(scratch_key, (uint32_t)sizeof(scratch_key), &scratch_input,
                                output_a, 8u) == 0,
                "8-bit derivation failed");
    TEST_ASSERT(rom_kdf_800_108(scratch_key, (uint32_t)sizeof(scratch_key), &scratch_input,
                                output_b, 256u) == 0,
                "256-bit derivation failed");
    TEST_ASSERT(output_a[0] != output_b[0],
                "different encoded output lengths produced the same prefix");
    TEST_SUBTEST_PASS();

    TEST_SUBTEST_START("invalid arguments are rejected");
    TEST_ASSERT(rom_kdf_800_108(scratch_key, (uint32_t)sizeof(scratch_key), &scratch_input, output,
                                0u) == -1,
                "zero output size was accepted");
    TEST_ASSERT(rom_kdf_800_108(scratch_key, (uint32_t)sizeof(scratch_key), &scratch_input, output,
                                (uint16_t)(KM_KDF_OUT_MAX_BITS + 8u)) == -1,
                "oversized output was accepted");
    TEST_ASSERT(rom_kdf_800_108(NULL, 1u, &scratch_input, output, 256u) == -1,
                "NULL non-empty key was accepted");
    TEST_ASSERT(rom_kdf_800_108(scratch_key, (uint32_t)sizeof(scratch_key), NULL, output, 256u) ==
                    -1,
                "NULL input was accepted");
    TEST_ASSERT(rom_kdf_800_108(scratch_key, (uint32_t)sizeof(scratch_key), &scratch_input, NULL,
                                256u) == -1,
                "NULL output was accepted");
    TEST_SUBTEST_PASS();

    TEST_PASS();
    return 0;
}
