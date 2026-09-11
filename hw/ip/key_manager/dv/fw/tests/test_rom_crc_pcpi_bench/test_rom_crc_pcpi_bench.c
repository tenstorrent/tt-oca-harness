/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/* Copyright 2026 Tenstorrent Inc. */
/**
 * @file test_rom_crc_pcpi_bench.c
 * @brief Focused CRC software-versus-PCPI cycle benchmark
 *
 * Measures three fixed-count workloads using the same deterministic input stream
 * and loop structure for both the software baseline and the
 * PCPI-accelerated path:
 *   1. CRC-32C word updates
 *   2. CRC-32C byte updates
 *   3. CRC-8/ROHC byte updates
 *
 * Each trial runs exactly 256 update invocations. The measured interval covers
 * only the update loop; table generation, input preparation, and result checks
 * remain outside the timed region. The benchmark enforces the cycle-reduction
 * target for the CRC-32C workloads and records the CRC-8/ROHC measurement for
 * visibility.
 *
 * Run with:
 *   make run_fw FW_TEST=test_rom_crc_pcpi_bench VUART_PRINT=1
 */

#include "test_common.h"

#define BENCH_UPDATES 256u
#define CRC32C_REFLECTED_POLY 0x82F63B78u
#define CRC8_ROHC_REFLECTED_POLY 0xE0u

static uint32_t crc32c_table[256];
static uint8_t crc8_rohc_table[256];

/**
 * @brief Disable boot-time wipe for this focused benchmark image.
 *
 * @return Always 0 to keep the benchmark path focused on CRC measurement.
 */
int rom_boot_wipe_enabled(void) {
    return 0;
}

/**
 * @brief Disable unrecoverable-fault wipe for this focused benchmark image.
 *
 * @return Always 0 to keep the benchmark path focused on CRC measurement.
 */
int rom_unrec_wipe_enabled(void) {
    return 0;
}

/**
 * @brief Build the software CRC-32C lookup table used as the baseline model.
 */
static void init_crc32c_table(void) {
    for (uint32_t i = 0; i < 256u; ++i) {
        uint32_t crc = i;
        for (uint32_t bit = 0; bit < 8u; ++bit) {
            if ((crc & 1u) != 0u) {
                crc = (crc >> 1) ^ CRC32C_REFLECTED_POLY;
            } else {
                crc >>= 1;
            }
        }
        crc32c_table[i] = crc;
    }
}

/**
 * @brief Build the software CRC-8/ROHC lookup table used as the baseline model.
 */
static void init_crc8_rohc_table(void) {
    for (uint32_t i = 0; i < 256u; ++i) {
        uint8_t crc = (uint8_t)i;
        for (uint32_t bit = 0; bit < 8u; ++bit) {
            if ((crc & 1u) != 0u) {
                crc = (uint8_t)((crc >> 1) ^ CRC8_ROHC_REFLECTED_POLY);
            } else {
                crc >>= 1;
            }
        }
        crc8_rohc_table[i] = crc;
    }
}

/**
 * @brief Generate deterministic word and byte inputs for all benchmark loops.
 *
 * @param[out] word_inputs Output array for CRC-32C word-update trials.
 * @param[out] byte_inputs Output array for byte-oriented CRC trials.
 */
static void init_inputs(uint32_t *word_inputs, uint8_t *byte_inputs) {
    uint32_t state = 0x2130C0DEu;

    for (uint32_t i = 0; i < BENCH_UPDATES; ++i) {
        state ^= state << 13;
        state ^= state >> 17;
        state ^= state << 5;

        word_inputs[i] = state ^ (0x9E3779B9u * (i + 1u));
        byte_inputs[i] = (uint8_t)(state >> ((i & 3u) * 8u));
    }
}

/**
 * @brief Apply one software CRC-32C byte update using the table baseline.
 *
 * @param[in] state Current CRC-32C chaining state.
 * @param[in] data Next input byte.
 * @return Updated CRC-32C chaining state.
 */
static uint32_t sw_crc32c_byte_update(uint32_t state, uint8_t data) {
    return (state >> 8) ^ crc32c_table[(state ^ data) & 0xFFu];
}

/**
 * @brief Apply one software CRC-32C word update using little-endian byte order.
 *
 * @param[in] state Current CRC-32C chaining state.
 * @param[in] word Next 32-bit input word.
 * @return Updated CRC-32C chaining state.
 */
static uint32_t sw_crc32c_word_update(uint32_t state, uint32_t word) {
    uint32_t crc = state;

    crc = sw_crc32c_byte_update(crc, (uint8_t)(word >> 0));
    crc = sw_crc32c_byte_update(crc, (uint8_t)(word >> 8));
    crc = sw_crc32c_byte_update(crc, (uint8_t)(word >> 16));
    crc = sw_crc32c_byte_update(crc, (uint8_t)(word >> 24));

    return crc;
}

/**
 * @brief Apply one software CRC-8/ROHC byte update using the table baseline.
 *
 * @param[in] state Current CRC-8/ROHC chaining state.
 * @param[in] data Next input byte.
 * @return Updated CRC-8/ROHC chaining state.
 */
static uint32_t sw_crc8_rohc_byte_update(uint32_t state, uint8_t data) {
    return (uint32_t)crc8_rohc_table[((uint8_t)state) ^ data];
}

/**
 * @brief Execute one benchmark CRC-32C word PCPI instruction directly.
 *
 * @param[in] state Current CRC-32C chaining state.
 * @param[in] word Next 32-bit input word.
 * @return Updated CRC-32C chaining state.
 */
static inline uint32_t bench_pcpi_crc32c_word_update(uint32_t state, uint32_t word) {
    register uint32_t a0 __asm__("a0") = state;
    register uint32_t a1 __asm__("a1") = word;

    __asm__ volatile(".word 0x58B5050B" : "+r"(a0) : "r"(a1) :);
    return a0;
}

/**
 * @brief Execute one benchmark CRC-32C byte PCPI instruction directly.
 *
 * @param[in] state Current CRC-32C chaining state.
 * @param[in] data Next input byte in bits [7:0].
 * @return Updated CRC-32C chaining state.
 */
static inline uint32_t bench_pcpi_crc32c_byte_update(uint32_t state, uint32_t data) {
    register uint32_t a0 __asm__("a0") = state;
    register uint32_t a1 __asm__("a1") = data;

    __asm__ volatile(".word 0x58B5150B" : "+r"(a0) : "r"(a1) :);
    return a0;
}

/**
 * @brief Execute one benchmark CRC-8/ROHC byte PCPI instruction directly.
 *
 * @param[in] state Current CRC-8/ROHC chaining state.
 * @param[in] data Next input byte in bits [7:0].
 * @return Updated CRC-8/ROHC chaining state.
 */
static inline uint32_t bench_pcpi_crc8_rohc_update(uint32_t state, uint32_t data) {
    register uint32_t a0 __asm__("a0") = state;
    register uint32_t a1 __asm__("a1") = data;

    __asm__ volatile(".word 0x58B5250B" : "+r"(a0) : "r"(a1) :);
    return a0;
}

/**
 * @brief Measure the software CRC-32C word-update loop.
 *
 * @param[in] inputs Benchmark word inputs.
 * @param[out] final_state Final CRC-32C chaining state after the loop.
 * @return Elapsed benchmark cycles for the measured loop.
 */
static uint32_t bench_crc32c_word_sw(const uint32_t *inputs, uint32_t *final_state) {
    uint32_t start_cycles;
    uint32_t end_cycles;
    uint32_t state = 0xFFFFFFFFu;

    if (!tb_get_cycle_count(&start_cycles, 1000u)) {
        TEST_FAIL("Failed to snapshot start cycle count (CRC-32C word software)");
    }

    for (uint32_t i = 0; i < BENCH_UPDATES; ++i) {
        state = sw_crc32c_word_update(state, inputs[i]);
    }

    if (!tb_get_cycle_count(&end_cycles, 1000u)) {
        TEST_FAIL("Failed to snapshot end cycle count (CRC-32C word software)");
    }

    *final_state = state;
    return end_cycles - start_cycles;
}

/**
 * @brief Measure the PCPI CRC-32C word-update loop.
 *
 * @param[in] inputs Benchmark word inputs.
 * @param[out] final_state Final CRC-32C chaining state after the loop.
 * @return Elapsed benchmark cycles for the measured loop.
 */
static uint32_t bench_crc32c_word_pcpi(const uint32_t *inputs, uint32_t *final_state) {
    uint32_t start_cycles;
    uint32_t end_cycles;
    uint32_t state = 0xFFFFFFFFu;

    if (!tb_get_cycle_count(&start_cycles, 1000u)) {
        TEST_FAIL("Failed to snapshot start cycle count (CRC-32C word PCPI)");
    }

    for (uint32_t i = 0; i < BENCH_UPDATES; ++i) {
        state = bench_pcpi_crc32c_word_update(state, inputs[i]);
    }

    if (!tb_get_cycle_count(&end_cycles, 1000u)) {
        TEST_FAIL("Failed to snapshot end cycle count (CRC-32C word PCPI)");
    }

    *final_state = state;
    return end_cycles - start_cycles;
}

/**
 * @brief Measure the software CRC-32C byte-update loop.
 *
 * @param[in] inputs Benchmark byte inputs.
 * @param[out] final_state Final CRC-32C chaining state after the loop.
 * @return Elapsed benchmark cycles for the measured loop.
 */
static uint32_t bench_crc32c_byte_sw(const uint8_t *inputs, uint32_t *final_state) {
    uint32_t start_cycles;
    uint32_t end_cycles;
    uint32_t state = 0xFFFFFFFFu;

    if (!tb_get_cycle_count(&start_cycles, 1000u)) {
        TEST_FAIL("Failed to snapshot start cycle count (CRC-32C byte software)");
    }

    for (uint32_t i = 0; i < BENCH_UPDATES; ++i) {
        state = sw_crc32c_byte_update(state, inputs[i]);
    }

    if (!tb_get_cycle_count(&end_cycles, 1000u)) {
        TEST_FAIL("Failed to snapshot end cycle count (CRC-32C byte software)");
    }

    *final_state = state;
    return end_cycles - start_cycles;
}

/**
 * @brief Measure the PCPI CRC-32C byte-update loop.
 *
 * @param[in] inputs Benchmark byte inputs.
 * @param[out] final_state Final CRC-32C chaining state after the loop.
 * @return Elapsed benchmark cycles for the measured loop.
 */
static uint32_t bench_crc32c_byte_pcpi(const uint8_t *inputs, uint32_t *final_state) {
    uint32_t start_cycles;
    uint32_t end_cycles;
    uint32_t state = 0xFFFFFFFFu;

    if (!tb_get_cycle_count(&start_cycles, 1000u)) {
        TEST_FAIL("Failed to snapshot start cycle count (CRC-32C byte PCPI)");
    }

    for (uint32_t i = 0; i < BENCH_UPDATES; ++i) {
        state = bench_pcpi_crc32c_byte_update(state, inputs[i]);
    }

    if (!tb_get_cycle_count(&end_cycles, 1000u)) {
        TEST_FAIL("Failed to snapshot end cycle count (CRC-32C byte PCPI)");
    }

    *final_state = state;
    return end_cycles - start_cycles;
}

/**
 * @brief Measure the software CRC-8/ROHC byte-update loop.
 *
 * @param[in] inputs Benchmark byte inputs.
 * @param[out] final_state Final CRC-8/ROHC chaining state after the loop.
 * @return Elapsed benchmark cycles for the measured loop.
 */
static uint32_t bench_crc8_rohc_byte_sw(const uint8_t *inputs, uint32_t *final_state) {
    uint32_t start_cycles;
    uint32_t end_cycles;
    uint32_t state = 0xFFu;

    if (!tb_get_cycle_count(&start_cycles, 1000u)) {
        TEST_FAIL("Failed to snapshot start cycle count (CRC-8 software)");
    }

    for (uint32_t i = 0; i < BENCH_UPDATES; ++i) {
        state = sw_crc8_rohc_byte_update(state, inputs[i]);
    }

    if (!tb_get_cycle_count(&end_cycles, 1000u)) {
        TEST_FAIL("Failed to snapshot end cycle count (CRC-8 software)");
    }

    *final_state = state;
    return end_cycles - start_cycles;
}

/**
 * @brief Measure the PCPI CRC-8/ROHC byte-update loop.
 *
 * @param[in] inputs Benchmark byte inputs.
 * @param[out] final_state Final CRC-8/ROHC chaining state after the loop.
 * @return Elapsed benchmark cycles for the measured loop.
 */
static uint32_t bench_crc8_rohc_byte_pcpi(const uint8_t *inputs, uint32_t *final_state) {
    uint32_t start_cycles;
    uint32_t end_cycles;
    uint32_t state = 0xFFu;

    if (!tb_get_cycle_count(&start_cycles, 1000u)) {
        TEST_FAIL("Failed to snapshot start cycle count (CRC-8 PCPI)");
    }

    for (uint32_t i = 0; i < BENCH_UPDATES; ++i) {
        state = bench_pcpi_crc8_rohc_update(state, inputs[i]);
    }

    if (!tb_get_cycle_count(&end_cycles, 1000u)) {
        TEST_FAIL("Failed to snapshot end cycle count (CRC-8 PCPI)");
    }

    *final_state = state;
    return end_cycles - start_cycles;
}

/**
 * @brief Compute percent improvement relative to the software baseline.
 *
 * Negative results indicate the PCPI path is slower than the software baseline.
 *
 * @param[in] software_cycles Measured software cycle count.
 * @param[in] pcpi_cycles Measured PCPI cycle count.
 * @return Signed percentage improvement.
 */
static int32_t improvement_pct(uint32_t software_cycles, uint32_t pcpi_cycles) {
    return ((int32_t)software_cycles - (int32_t)pcpi_cycles) * 100 / (int32_t)software_cycles;
}

int main(void) {
    uint32_t word_inputs[BENCH_UPDATES];
    uint8_t byte_inputs[BENCH_UPDATES];

    TEST_INIT();

    if (!tb_set_timeout(1000000u)) {
        TEST_FAIL("Failed to set benchmark timeout");
    }

    init_crc32c_table();
    init_crc8_rohc_table();
    init_inputs(word_inputs, byte_inputs);

    TEST_SUBTEST_START("CRC-32C word benchmark");
    {
        uint32_t sw_state;
        uint32_t pcpi_state;
        uint32_t sw_cycles = bench_crc32c_word_sw(word_inputs, &sw_state);
        uint32_t pcpi_cycles = bench_crc32c_word_pcpi(word_inputs, &pcpi_state);
        int32_t improve = improvement_pct(sw_cycles, pcpi_cycles);

        TEST_ASSERT_EQ(pcpi_state, sw_state, "CRC-32C word final state");
        TEST_ASSERT(sw_cycles > pcpi_cycles, "CRC-32C word expected software=%u > pcpi=%u",
                    sw_cycles, pcpi_cycles);
        TEST_ASSERT(improve >= 50, "CRC-32C word improvement=%d%% (< 50%%)", (int)improve);

        TEST_LOG("CRC-32C word software Cycles: %u", sw_cycles);
        TEST_LOG("CRC-32C word PCPI Cycles: %u", pcpi_cycles);
        TEST_LOG("CRC-32C word improvement: %d%%", (int)improve);
    }
    TEST_SUBTEST_PASS();

    TEST_SUBTEST_START("CRC-32C byte benchmark");
    {
        uint32_t sw_state;
        uint32_t pcpi_state;
        uint32_t sw_cycles = bench_crc32c_byte_sw(byte_inputs, &sw_state);
        uint32_t pcpi_cycles = bench_crc32c_byte_pcpi(byte_inputs, &pcpi_state);
        int32_t improve = improvement_pct(sw_cycles, pcpi_cycles);

        TEST_ASSERT_EQ(pcpi_state, sw_state, "CRC-32C byte final state");
        TEST_ASSERT(sw_cycles > pcpi_cycles, "CRC-32C byte expected software=%u > pcpi=%u",
                    sw_cycles, pcpi_cycles);
        TEST_ASSERT(improve >= 50, "CRC-32C byte improvement=%d%% (< 50%%)", (int)improve);

        TEST_LOG("CRC-32C byte software Cycles: %u", sw_cycles);
        TEST_LOG("CRC-32C byte PCPI Cycles: %u", pcpi_cycles);
        TEST_LOG("CRC-32C byte improvement: %d%%", (int)improve);
    }
    TEST_SUBTEST_PASS();

    TEST_SUBTEST_START("CRC-8/ROHC byte benchmark");
    {
        uint32_t sw_state;
        uint32_t pcpi_state;
        uint32_t sw_cycles = bench_crc8_rohc_byte_sw(byte_inputs, &sw_state);
        uint32_t pcpi_cycles = bench_crc8_rohc_byte_pcpi(byte_inputs, &pcpi_state);
        int32_t improve = improvement_pct(sw_cycles, pcpi_cycles);

        TEST_ASSERT_EQ(pcpi_state, sw_state, "CRC-8 final state");
        TEST_ASSERT_EQ(pcpi_state >> 8, 0u, "CRC-8 zero extension");
        TEST_LOG("CRC-8/ROHC byte software Cycles: %u", sw_cycles);
        TEST_LOG("CRC-8/ROHC byte PCPI Cycles: %u", pcpi_cycles);
        TEST_LOG("CRC-8/ROHC byte improvement: %d%%", (int)improve);
    }
    TEST_SUBTEST_PASS();

    TEST_PASS();
    return 0;
}
