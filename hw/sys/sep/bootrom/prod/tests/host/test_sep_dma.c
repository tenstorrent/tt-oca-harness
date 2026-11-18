/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

// Host tests for the ROM's secure DMA driver: the register programming of copies
// and zero fills, the checks made before the engine starts, and the completion
// handling that turns every engine failure into a non-zero return.

#define _POSIX_C_SOURCE 200809L

#include <stdio.h>
#include <stdlib.h>
#include <sys/wait.h>
#include <unistd.h>

#include "fake_sep_dma.h"
#include "rom_mmio.h"
#include "sep.h"
#include "sep_dma.h"
#include "sep_smc_interface.h"
#include "unit_helpers.h"

int g_unit_total;
int g_unit_failed;
int g_unit_case_failed;

void test_fixture_reset(void) {
    fake_dma_reset();
}

#define SRAM_BASE ((uint32_t)SEP_TOP_SEP_SRAM_BASE_ADDR)
#define SRAM_SIZE ((uint32_t)SEP_TOP_SEP_SRAM_SIZE)
#define ICCM_BASE ((uint32_t)SEP_TOP_SEP_ICCM_BASE_ADDR)
#define ICCM_SIZE ((uint32_t)SEP_TOP_SEP_ICCM_SIZE)
#define DMA_BASE ((uint32_t)SEP_TOP_SECURE_DMA_BASE_ADDR)
#define DMA_SIZE ((uint32_t)SEP_TOP_SECURE_DMA_SIZE)

#define R_SRC_LO SEP_TOP_SECURE_DMA_SRC_ADDR_LO_BASE_ADDR
#define R_SRC_HI SEP_TOP_SECURE_DMA_SRC_ADDR_HI_BASE_ADDR
#define R_DST_LO SEP_TOP_SECURE_DMA_DST_ADDR_LO_BASE_ADDR
#define R_DST_HI SEP_TOP_SECURE_DMA_DST_ADDR_HI_BASE_ADDR
#define R_ASID SEP_TOP_SECURE_DMA_ADDR_SPACE_ID_BASE_ADDR
#define R_BASE SEP_TOP_SECURE_DMA_ENABLED_MEMORY_RANGE_BASE_BASE_ADDR
#define R_LIMIT SEP_TOP_SECURE_DMA_ENABLED_MEMORY_RANGE_LIMIT_BASE_ADDR
#define R_VALID SEP_TOP_SECURE_DMA_RANGE_VALID_BASE_ADDR
#define R_REGWEN SEP_TOP_SECURE_DMA_RANGE_REGWEN_BASE_ADDR
#define R_TOTAL SEP_TOP_SECURE_DMA_TOTAL_DATA_SIZE_BASE_ADDR
#define R_CHUNK SEP_TOP_SECURE_DMA_CHUNK_DATA_SIZE_BASE_ADDR
#define R_WIDTH SEP_TOP_SECURE_DMA_TRANSFER_WIDTH_BASE_ADDR
#define R_CONTROL SEP_TOP_SECURE_DMA_CONTROL_BASE_ADDR
#define R_SRC_CFG SEP_TOP_SECURE_DMA_SRC_CONFIG_BASE_ADDR
#define R_DST_CFG SEP_TOP_SECURE_DMA_DST_CONFIG_BASE_ADDR
#define R_ERROR_CODE SEP_TOP_SECURE_DMA_ERROR_CODE_BASE_ADDR
#define R_REGION_SIZE SEP_TOP_SEP_CPU_CTRL_SEP_REGION_SIZE_BASE_ADDR

#define GO SECURE_DMA__CONTROL__GO_bm
#define INITIAL SECURE_DMA__CONTROL__INITIAL_TRANSFER_bm
#define OPCODE_ZERO 0x4u
#define ST_BUSY SECURE_DMA__STATUS__BUSY_bm
#define ST_DONE SECURE_DMA__STATUS__DONE_bm

static size_t dma_block_writes(void) {
    size_t n = 0, count = 0;
    const fake_write_t *w = fake_writes(&count);
    for (size_t i = 0; i < count; ++i)
        n += (w[i].addr >= DMA_BASE && w[i].addr < DMA_BASE + DMA_SIZE);
    return n;
}

static size_t go_writes(void) {
    size_t n = 0, count = 0;
    const fake_write_t *w = fake_writes(&count);
    for (size_t i = 0; i < count; ++i) n += (w[i].addr == R_CONTROL && (w[i].value & GO));
    return n;
}

// ---------------------------------------------------------------------------
// Copies and the shared start/completion handling
// ---------------------------------------------------------------------------

TEST(copy_programs_registers_as_before) {
    ASSERT_EQ_INT(sep_dma_copy(SRAM_BASE + 0x100u, SRAM_BASE, 64u), 0);
    ASSERT_EQ_INT(fake_reg(R_SRC_LO), SRAM_BASE);
    ASSERT_EQ_INT(fake_reg(R_SRC_HI), 0);
    ASSERT_EQ_INT(fake_reg(R_DST_LO), SRAM_BASE + 0x100u);
    ASSERT_EQ_INT(fake_reg(R_DST_HI), 0);
    ASSERT_EQ_INT(fake_reg(R_ASID), 0x77);
    ASSERT_EQ_INT(fake_reg(R_WIDTH), 2);
    ASSERT_EQ_INT(fake_reg(R_SRC_CFG), SECURE_DMA__SRC_CONFIG__INCREMENT_bm);
    ASSERT_EQ_INT(fake_reg(R_DST_CFG), SECURE_DMA__DST_CONFIG__INCREMENT_bm);
    ASSERT_EQ_INT(fake_reg(R_CHUNK), 64);
    ASSERT_EQ_INT(fake_reg(R_TOTAL), 64);
    ASSERT_EQ_INT(fake_reg(R_CONTROL), GO | INITIAL);
    ASSERT_EQ_INT(fake_go_count(), 1);
}

TEST(copy_refused_while_engine_busy) {
    fake_dma_set_status(ST_BUSY);
    ASSERT_EQ_INT(sep_dma_copy(SRAM_BASE + 0x100u, SRAM_BASE, 64u), SEP_DMA_ERR_TRANSFER);
    ASSERT_EQ_INT(go_writes(), 0);
}

TEST(copy_stale_done_with_dropped_go_is_not_success) {
    fake_dma_set_status(ST_DONE);
    fake_dma_drop_go(1);
    ASSERT_TRUE(sep_dma_copy(SRAM_BASE + 0x100u, SRAM_BASE, 64u) != 0u);
}

TEST(copy_stale_done_that_does_not_clear_is_refused) {
    fake_dma_set_status(ST_DONE);
    fake_dma_ignore_w1c(1);
    ASSERT_EQ_INT(sep_dma_copy(SRAM_BASE + 0x100u, SRAM_BASE, 64u), SEP_DMA_ERR_TRANSFER);
    ASSERT_EQ_INT(go_writes(), 0);
}

TEST(copy_each_error_code_bit_fails) {
    for (unsigned bit = 0; bit < 8; ++bit) {
        test_fixture_reset();
        fake_dma_script(FAKE_DMA_ERROR, 1u, 1u << bit);
        ASSERT_EQ_INT(sep_dma_copy(SRAM_BASE + 0x100u, SRAM_BASE, 64u), SEP_DMA_ERR_TRANSFER);
    }
}

TEST(copy_error_status_without_code_fails) {
    fake_dma_script(FAKE_DMA_ERROR, 1u, 0u);
    ASSERT_EQ_INT(sep_dma_copy(SRAM_BASE + 0x100u, SRAM_BASE, 64u), SEP_DMA_ERR_TRANSFER);
}

TEST(copy_done_with_error_code_fails) {
    fake_mem_set(R_ERROR_CODE, 0x10u);
    ASSERT_EQ_INT(sep_dma_copy(SRAM_BASE + 0x100u, SRAM_BASE, 64u), SEP_DMA_ERR_TRANSFER);
}

TEST(copy_timeout_aborts_and_fails) {
    fake_dma_script(FAKE_DMA_NEVER, 0u, 0u);
    ASSERT_EQ_INT(sep_dma_copy(SRAM_BASE + 0x100u, SRAM_BASE, 64u), SEP_DMA_ERR_TRANSFER);
    ASSERT_TRUE(fake_writes_to(R_CONTROL) >= 2);
    ASSERT_EQ_INT(fake_reg(R_CONTROL), SECURE_DMA__CONTROL__ABORT_bm);
}

TEST(copy_to_iccm_leaves_region_size_alone) {
    ASSERT_EQ_INT(sep_dma_copy(ICCM_BASE, SRAM_BASE, 64u), 0);
    ASSERT_EQ_INT(fake_writes_to(R_REGION_SIZE), 0);
}

// ---------------------------------------------------------------------------
// Zero fills. Each case runs in a child process, so a fill that stores to SEP
// SRAM through a raw pointer, which crashes on the host, counts as a failure
// instead of ending the run.
// ---------------------------------------------------------------------------

static void expect_fill_sequence(uint32_t dest, uint32_t len, uint32_t base, uint32_t limit) {
    ASSERT_EQ_INT(sep_dma_zero(dest, len), 0);
    ASSERT_EQ_INT(fake_reg(R_BASE), base);
    ASSERT_EQ_INT(fake_reg(R_LIMIT), limit);
    ASSERT_EQ_INT(fake_reg(R_VALID), 1);
    ASSERT_EQ_INT(fake_reg(R_SRC_LO), 0);
    ASSERT_EQ_INT(fake_reg(R_SRC_HI), 0);
    ASSERT_EQ_INT(fake_reg(R_ASID), 0x77);
    ASSERT_EQ_INT(fake_reg(R_DST_LO), dest);
    ASSERT_EQ_INT(fake_reg(R_DST_HI), 0);
    ASSERT_EQ_INT(fake_reg(R_WIDTH), 2);
    ASSERT_EQ_INT(fake_reg(R_TOTAL), len);
    ASSERT_EQ_INT(fake_reg(R_CHUNK), len);
    ASSERT_EQ_INT(fake_reg(R_DST_CFG), SECURE_DMA__DST_CONFIG__INCREMENT_bm);
    ASSERT_EQ_INT(fake_reg(R_SRC_CFG), 0);
    ASSERT_EQ_INT(fake_reg(R_CONTROL), GO | INITIAL | OPCODE_ZERO);
    // The window is in place before the engine starts.
    ASSERT_TRUE(fake_write_index(R_LIMIT, 0) < fake_write_index(R_CONTROL, 0));
    ASSERT_TRUE(fake_write_index(R_VALID, 0) < fake_write_index(R_CONTROL, 0));
}

TEST(fill_sram_sequence) {
    expect_fill_sequence(SRAM_BASE + 0x1000u, 256u, SRAM_BASE, SRAM_BASE + SRAM_SIZE - 1u);
}

TEST(fill_iccm_sequence) {
    expect_fill_sequence(ICCM_BASE + 0x200u, 256u, ICCM_BASE, ICCM_BASE + ICCM_SIZE - 1u);
    ASSERT_EQ_INT(fake_writes_to(R_REGION_SIZE), 0);
}

TEST(fill_smc_sram_sequence) {
    const uint32_t smc = sep_get_smc_sram_base();
    expect_fill_sequence(smc + 0x40u, 64u, smc, smc + SMC_SRAM_SIZE_BYTES - 1u);
}

TEST(fill_whole_sram) {
    expect_fill_sequence(SRAM_BASE, SRAM_SIZE, SRAM_BASE, SRAM_BASE + SRAM_SIZE - 1u);
}

static void expect_refused(uint32_t dest, size_t len) {
    test_fixture_reset();
    ASSERT_EQ_INT(sep_dma_zero(dest, len), SEP_DMA_ERR_OUT_OF_RANGE);
    ASSERT_EQ_INT(dma_block_writes(), 0);
}

TEST(fill_refusals_write_no_register) {
    expect_refused(SRAM_BASE, 0u);                                          // empty
    expect_refused(SRAM_BASE + 2u, 64u);                                    // misaligned start
    expect_refused(SRAM_BASE, 62u);                                         // not whole words
    expect_refused(0xFFFFFFFCu, 8u);                                        // wraps
    expect_refused(SEP_TOP_SEP_DCCM_BASE_ADDR, 64u);                        // not a fill region
    expect_refused(SRAM_BASE + SRAM_SIZE - 4u, 8u);                         // runs past SEP SRAM
    expect_refused(ICCM_BASE + ICCM_SIZE - 4u, 8u);                         // runs past ICCM
    expect_refused(SRAM_BASE - 4u, 8u);                                     // starts below SEP SRAM
    expect_refused(sep_get_smc_sram_base() + SMC_SRAM_SIZE_BYTES - 4u, 8u); // runs past SMC SRAM
    if (sizeof(size_t) > sizeof(uint32_t)) {
        expect_refused(SRAM_BASE, (size_t)((((uint64_t)1u) << 32) | 64u)); // truncates to 64
    }
    test_fixture_reset();
    ASSERT_EQ_INT(sep_dma_zero(SRAM_BASE + 2u, 64u), SEP_DMA_ERR_OUT_OF_RANGE);
    ASSERT_TRUE(fake_console_has("DMA_DST="));
    ASSERT_TRUE(fake_console_has("DMA_LEN="));
}

static void expect_readback_refused(uint32_t addr) {
    test_fixture_reset();
    fake_dma_corrupt_on_write(addr, 0x40u);
    ASSERT_EQ_INT(sep_dma_zero(SRAM_BASE + 0x1000u, 256u), SEP_DMA_ERR_OUT_OF_RANGE);
    ASSERT_EQ_INT(go_writes(), 0);
}

TEST(fill_readback_mismatch_refused) {
    expect_readback_refused(R_DST_LO);
    expect_readback_refused(R_TOTAL);
    expect_readback_refused(R_CHUNK);
    expect_readback_refused(R_WIDTH);
    expect_readback_refused(R_DST_CFG);
    expect_readback_refused(R_BASE);
    expect_readback_refused(R_LIMIT);
}

TEST(fill_after_undrained_abort_refused) {
    fake_dma_script(FAKE_DMA_NEVER, 0u, 0u);
    fake_dma_ignore_abort(1);
    ASSERT_EQ_INT(sep_dma_zero(SRAM_BASE + 0x1000u, 256u), SEP_DMA_ERR_TRANSFER);
    const unsigned gos = fake_go_count();
    ASSERT_EQ_INT(sep_dma_zero(SRAM_BASE + 0x1000u, 256u), SEP_DMA_ERR_TRANSFER);
    ASSERT_EQ_INT(fake_go_count(), gos);
}

TEST(fill_second_completion_read_disagrees) {
    fake_dma_error_code_after_reads(1u, 0x10u);
    ASSERT_EQ_INT(sep_dma_zero(SRAM_BASE + 0x1000u, 256u), SEP_DMA_ERR_TRANSFER);
}

TEST(fill_leaves_window_and_regwen_alone_after_start) {
    ASSERT_EQ_INT(sep_dma_zero(SRAM_BASE + 0x1000u, 256u), 0);
    ASSERT_EQ_INT(fake_writes_to(R_REGWEN), 0);
    const size_t go_at = fake_write_index(R_CONTROL, 0);
    size_t count = 0;
    fake_writes(&count);
    ASSERT_EQ_INT(fake_write_index(R_BASE, go_at), count);
    ASSERT_EQ_INT(fake_write_index(R_LIMIT, go_at), count);
    ASSERT_EQ_INT(fake_write_index(R_VALID, go_at), count);
}

TEST(fill_stale_done_with_dropped_go_is_not_success) {
    fake_dma_set_status(ST_DONE);
    fake_dma_drop_go(1);
    ASSERT_TRUE(sep_dma_zero(SRAM_BASE + 0x1000u, 256u) != 0u);
}

TEST(fill_refused_while_engine_busy) {
    fake_dma_set_status(ST_BUSY);
    ASSERT_EQ_INT(sep_dma_zero(SRAM_BASE + 0x1000u, 256u), SEP_DMA_ERR_TRANSFER);
    ASSERT_EQ_INT(go_writes(), 0);
}

TEST(fill_each_error_code_bit_fails) {
    for (unsigned bit = 0; bit < 8; ++bit) {
        test_fixture_reset();
        fake_dma_script(FAKE_DMA_ERROR, 1u, 1u << bit);
        ASSERT_EQ_INT(sep_dma_zero(SRAM_BASE + 0x1000u, 256u), SEP_DMA_ERR_TRANSFER);
    }
}

TEST(fill_timeout_aborts_and_fails) {
    fake_dma_script(FAKE_DMA_NEVER, 0u, 0u);
    ASSERT_EQ_INT(sep_dma_zero(SRAM_BASE + 0x1000u, 256u), SEP_DMA_ERR_TRANSFER);
    ASSERT_EQ_INT(fake_reg(R_CONTROL), SECURE_DMA__CONTROL__ABORT_bm);
}

typedef void (*test_fn)(void);

static void run_forked(const char *name, test_fn fn) {
    fflush(stdout);
    const pid_t pid = fork();
    if (pid == 0) {
        test_fixture_reset();
        g_unit_case_failed = 0;
        fn();
        fflush(stdout);
        _exit(g_unit_case_failed ? 1 : 0);
    }
    int st = 0;
    waitpid(pid, &st, 0);
    ++g_unit_total;
    if (WIFEXITED(st) && WEXITSTATUS(st) == 0) {
        printf("ok   %s\n", name);
    } else {
        ++g_unit_failed;
        if (WIFSIGNALED(st)) printf("  crashed with signal %d\n", WTERMSIG(st));
        printf("FAIL %s\n", name);
    }
}

#define RUN_FORKED(name) run_forked(#name, name)

int main(void) {
    RUN_TEST(copy_programs_registers_as_before);
    RUN_TEST(copy_refused_while_engine_busy);
    RUN_TEST(copy_stale_done_with_dropped_go_is_not_success);
    RUN_TEST(copy_stale_done_that_does_not_clear_is_refused);
    RUN_TEST(copy_each_error_code_bit_fails);
    RUN_TEST(copy_error_status_without_code_fails);
    RUN_TEST(copy_done_with_error_code_fails);
    RUN_TEST(copy_timeout_aborts_and_fails);
    RUN_TEST(copy_to_iccm_leaves_region_size_alone);

    RUN_FORKED(fill_sram_sequence);
    RUN_FORKED(fill_iccm_sequence);
    RUN_FORKED(fill_smc_sram_sequence);
    RUN_FORKED(fill_whole_sram);
    RUN_FORKED(fill_refusals_write_no_register);
    RUN_FORKED(fill_readback_mismatch_refused);
    RUN_FORKED(fill_after_undrained_abort_refused);
    RUN_FORKED(fill_second_completion_read_disagrees);
    RUN_FORKED(fill_leaves_window_and_regwen_alone_after_start);
    RUN_FORKED(fill_stale_done_with_dropped_go_is_not_success);
    RUN_FORKED(fill_refused_while_engine_busy);
    RUN_FORKED(fill_each_error_code_bit_fails);
    RUN_FORKED(fill_timeout_aborts_and_fails);
    return unit_report();
}
