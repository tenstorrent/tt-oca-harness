/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

// Host tests for the SEP SRAM clears: the optional boot-time scrub and the clear
// between SPI manifest slots. Built once per SRAM_SCRUB_BYTES the Makefile names,
// so the cases that depend on the scrub length check that build's own value.

#include <stdio.h>

#include "fake_sep_dma.h"
#include "oca_boot.h"
#include "rom_mmio.h"
#include "sep.h"
#include "sep_dma.h"
#include "status_values.h"
#include "unit_helpers.h"

int g_unit_total;
int g_unit_failed;
int g_unit_case_failed;

void test_fixture_reset(void) {
    fake_dma_reset();
}

#define SRAM_BASE ((uint32_t)SEP_TOP_SEP_SRAM_BASE_ADDR)
#define SRAM_SIZE ((uint32_t)SEP_TOP_SEP_SRAM_SIZE)
#define R_DST_LO SEP_TOP_SECURE_DMA_DST_ADDR_LO_BASE_ADDR
#define R_TOTAL SEP_TOP_SECURE_DMA_TOTAL_DATA_SIZE_BASE_ADDR
#define R_CONTROL SEP_TOP_SECURE_DMA_CONTROL_BASE_ADDR

#ifndef SRAM_SCRUB_BYTES
#define SRAM_SCRUB_BYTES 0
#endif

#if SRAM_SCRUB_BYTES > 0
#define EXPECT_SCRUB_LEN \
    ((uint32_t)SRAM_SCRUB_BYTES > SRAM_SIZE ? SRAM_SIZE : (uint32_t)SRAM_SCRUB_BYTES)
#endif

// ---------------------------------------------------------------------------
// Boot-time scrub
// ---------------------------------------------------------------------------

#if SRAM_SCRUB_BYTES == 0
TEST(scrub_disabled_skips) {
    ASSERT_EQ_INT(rom_clear_ext_sram(), 0);
    ASSERT_TRUE(fake_console_has("SRAM_CLR_SKIP"));
    ASSERT_EQ_INT(fake_writes_to(R_CONTROL), 0);
    ASSERT_TRUE(fake_status_has(SEP_MSG_EXT_SRAM_CLEAR_START));
    ASSERT_TRUE(fake_status_has(SEP_MSG_EXT_SRAM_CLEAR_DONE));
}
#else
TEST(scrub_fills_from_sram_base) {
    ASSERT_EQ_INT(rom_clear_ext_sram(), 0);
    ASSERT_EQ_INT(fake_go_count(), 1);
    ASSERT_EQ_INT(fake_reg(R_DST_LO), SRAM_BASE);
    ASSERT_EQ_INT(fake_reg(R_TOTAL), EXPECT_SCRUB_LEN);
    ASSERT_TRUE(fake_console_has("SRAM_CLR_OK"));
    ASSERT_TRUE(!fake_console_has("SRAM_CLR_PROG"));
    ASSERT_TRUE(fake_status_has(SEP_MSG_EXT_SRAM_CLEAR_DONE));
}

TEST(scrub_engine_error_fails) {
    fake_dma_script(FAKE_DMA_ERROR, 1u, 0x10u);
    ASSERT_TRUE(rom_clear_ext_sram() != 0u);
    ASSERT_TRUE(fake_console_has("SRAM_CLR_FAIL"));
    ASSERT_TRUE(!fake_console_has("SRAM_CLR_OK"));
}

TEST(scrub_nonzero_readback_fails) {
    fake_mem_set(SRAM_BASE + EXPECT_SCRUB_LEN - 4u, 0x1u);
    ASSERT_TRUE(rom_clear_ext_sram() != 0u);
    ASSERT_TRUE(fake_console_has("SRAM_CLR_FAIL"));
    ASSERT_TRUE(fake_status_has(SEP_MSG_DMA_ERROR));
}

TEST(scrub_nonzero_first_word_fails) {
    fake_mem_set(SRAM_BASE, 0x1u);
    ASSERT_TRUE(rom_clear_ext_sram() != 0u);
    ASSERT_TRUE(fake_console_has("SRAM_CLR_FAIL"));
}
#endif

// ---------------------------------------------------------------------------
// Clear between SPI manifest slots
// ---------------------------------------------------------------------------

TEST(retry_clear_fills_all_of_sram) {
    ASSERT_EQ_INT(rom_clear_sram_for_retry(), 0);
    ASSERT_EQ_INT(fake_go_count(), 1);
    ASSERT_EQ_INT(fake_reg(R_DST_LO), SRAM_BASE);
    ASSERT_EQ_INT(fake_reg(R_TOTAL), SRAM_SIZE);
}

TEST(retry_clear_engine_error_fails) {
    fake_dma_script(FAKE_DMA_ERROR, 1u, 0x10u);
    ASSERT_EQ_INT(rom_clear_sram_for_retry(), OCA_BOOT_ERR_DMA);
    ASSERT_TRUE(fake_console_has("SRAM_RETRY_CLR_FAIL"));
}

TEST(retry_clear_nonzero_readback_fails) {
    fake_mem_set(SRAM_BASE + SRAM_SIZE / 2u, 0x1u);
    ASSERT_EQ_INT(rom_clear_sram_for_retry(), OCA_BOOT_ERR_DMA);
    ASSERT_TRUE(fake_console_has("SRAM_RETRY_CLR_FAIL"));
}

TEST(retry_clear_busy_engine_fails) {
    fake_dma_set_status(SECURE_DMA__STATUS__BUSY_bm);
    ASSERT_EQ_INT(rom_clear_sram_for_retry(), OCA_BOOT_ERR_DMA);
    ASSERT_EQ_INT(fake_go_count(), 0);
}

int main(void) {
    printf("SRAM_SCRUB_BYTES=0x%x\n", (unsigned)SRAM_SCRUB_BYTES);
#if SRAM_SCRUB_BYTES == 0
    RUN_TEST(scrub_disabled_skips);
#else
    RUN_TEST(scrub_fills_from_sram_base);
    RUN_TEST(scrub_engine_error_fails);
    RUN_TEST(scrub_nonzero_readback_fails);
    RUN_TEST(scrub_nonzero_first_word_fails);
#endif
    RUN_TEST(retry_clear_fills_all_of_sram);
    RUN_TEST(retry_clear_engine_error_fails);
    RUN_TEST(retry_clear_nonzero_readback_fails);
    RUN_TEST(retry_clear_busy_engine_fails);
    return unit_report();
}
