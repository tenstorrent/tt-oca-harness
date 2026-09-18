/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/* Copyright 2026 Tenstorrent Inc. */
/**
 * @file test_drbg_stream_err.c
 * @brief DRBG Sampler AXI-Stream protocol-violation (STREAM_ERR) test
 *
 * When the DRBG source asserts TVALID and then deasserts it before TREADY (an
 * AXI-Stream protocol violation), the sampler MUST:
 *   1. Set STATUS.STREAM_ERR (W1C sticky bit, bit 3)
 *   2. Increment STATUS.COUNT_BAD
 *   3. Pulse drbg_error_o, which sets IRQ_STATUS.DRBG_ERR in KMCSR
 *
 * Subtests:
 *   1. Out-of-band glitch (no active CPU DATA read): verifies the above three
 *      effects and W1C clear of STREAM_ERR.
 *   2. IRQ disabled: glitch fires, STREAM_ERR and DRBG_ERR are set; km_irq_o
 *      is a testbench-level signal and is not checked here.
 *
 * Run with:
 *   make run_fw FW_TEST=test_drbg_stream_err
 */

#include "test_common.h"
#include "irq_common.h"
#include "key_manager_fw.h"
#include "key_manager_addr.h"

/* DRBG Sampler registers */
#define DRBG_DATA_REG \
    (*(volatile km_drbg_sampler__data_reg_t *)KEY_MANAGER_DRBG_SAMPLER_DATA_BASE_ADDR)
#define DRBG_CFG_REG \
    (*(volatile km_drbg_sampler__cfg_reg_t *)KEY_MANAGER_DRBG_SAMPLER_CFG_BASE_ADDR)
#define DRBG_STATUS_REG \
    (*(volatile km_drbg_sampler__status_reg_t *)KEY_MANAGER_DRBG_SAMPLER_STATUS_BASE_ADDR)

/* KMCSR IRQ regs: KMCSR_IRQ_STATUS_REG / KMCSR_IRQ_ENABLE_REG from irq_common.h */

/* Settle cycles for hwset -> STATUS sticky bit -> IRQ propagation through km_csr */
#define SETTLE_CYCLES 64u

/* Number of reads to attempt when waiting for the DRBG to consume the glitch beat
 * in the active-read subtest (the glitch stops the TB; the read will stall until
 * the FSM detects the violation and returns SLVERR). */
#define ACTIVE_READ_STALL_READS 8u

static void clear_stream_err(void) {
    km_drbg_sampler__status_reg_t w1c = {0};
    w1c.f.stream_err = 1;
    DRBG_STATUS_REG.w = w1c.w;
}

static void clear_count_bad(void) {
    km_drbg_sampler__status_reg_t w = {0};
    w.f.count_bad = 1u;
    DRBG_STATUS_REG.w = w.w;
}

static void clear_kmcsr_drbg_err(void) {
    km_csr__irq_status_reg_t w1c = {0};
    w1c.f.drbg_err = 1;
    rom_kmcsr_irq_status_clear(w1c.w);
}

static void enable_drbg_irq(void) {
    km_csr__irq_enable_reg_t en = {.w = rom_kmcsr_irq_enable_read()};
    en.f.drbg_err_en = 1;
    rom_kmcsr_irq_enable_write(en.w);
}

static void disable_drbg_irq(void) {
    km_csr__irq_enable_reg_t en = {.w = rom_kmcsr_irq_enable_read()};
    en.f.drbg_err_en = 0;
    rom_kmcsr_irq_enable_write(en.w);
}

int main(void) {
    TEST_INIT();

    /* 30000 cycles: boot takes ~10000 cycles before firmware runs; glitch is near-instant */
    if (!tb_set_timeout(30000)) {
        TEST_FAIL("tb_set_timeout failed");
    }

    if (!tb_drbg_set_seed(0xDEADBEEFu, 1000)) {
        TEST_FAIL("tb_drbg_set_seed failed");
    }

    /* CFG: prefetch disabled, timeout disabled (avoid timeout masking the stream-error path) */
    DRBG_CFG_REG.w = 0;

    enable_drbg_irq();

    /*--------------------------------------------------------------------------
     * Subtest 1: Out-of-band TVALID-drop-before-TREADY sets STREAM_ERR,
     *            increments COUNT_BAD, and fires IRQ_STATUS.DRBG_ERR.
     *            No active CPU DATA read in flight.
     *--------------------------------------------------------------------------*/
    TEST_SUBTEST_START("Out-of-band TVALID glitch sets STREAM_ERR + COUNT_BAD + DRBG_ERR");

    clear_stream_err();
    clear_count_bad();
    clear_kmcsr_drbg_err();

    if (DRBG_STATUS_REG.f.stream_err != 0u) {
        TEST_FAIL("STATUS.STREAM_ERR not clear at start of subtest 1");
    }
    if (DRBG_STATUS_REG.f.count_bad != 0u) {
        TEST_FAIL("STATUS.COUNT_BAD not zero at start of subtest 1");
    }
    if (KMCSR_IRQ_STATUS_REG.f.drbg_err != 0u) {
        TEST_FAIL("IRQ_STATUS.DRBG_ERR not clear at start of subtest 1");
    }

    /* Quiesce the DRBG driver so there is no ongoing handshake */
    if (!tb_drbg_stop(1000)) {
        TEST_FAIL("tb_drbg_stop failed");
    }

    /* Inject one-shot protocol violation: TVALID high for 1 cycle, then low
     * before TREADY.  The driver remains in stopped state after the glitch. */
    if (!tb_drbg_tvalid_glitch(1000)) {
        TEST_FAIL("tb_drbg_tvalid_glitch failed");
    }

    /* Allow the hwset signal and IRQ pulse to propagate through km_csr registers */
    test_delay(SETTLE_CYCLES);

    /* STREAM_ERR must be set */
    if (DRBG_STATUS_REG.f.stream_err == 0u) {
        TEST_FAIL("STATUS.STREAM_ERR not set after TVALID drop before TREADY");
    }

    /* COUNT_BAD must have incremented */
    if (DRBG_STATUS_REG.f.count_bad == 0u) {
        TEST_FAIL("STATUS.COUNT_BAD not incremented on stream error");
    }

    /* KMCSR IRQ_STATUS.DRBG_ERR must be set */
    if (KMCSR_IRQ_STATUS_REG.f.drbg_err == 0u) {
        TEST_FAIL("IRQ_STATUS.DRBG_ERR not set on stream error");
    }

    /* W1C: clear STREAM_ERR and verify it clears */
    clear_stream_err();
    test_delay(4u);
    if (DRBG_STATUS_REG.f.stream_err != 0u) {
        TEST_FAIL("STATUS.STREAM_ERR did not clear on W1C write");
    }

    TEST_LOG("  STREAM_ERR set, COUNT_BAD=%u, DRBG_ERR set, W1C clear OK",
             (unsigned)DRBG_STATUS_REG.f.count_bad);
    TEST_SUBTEST_PASS();

    /* Resume normal DRBG data flow for the next subtest */
    if (!tb_drbg_start(1000)) {
        TEST_FAIL("tb_drbg_start failed (after subtest 1)");
    }

    /*--------------------------------------------------------------------------
     * Subtest 2: STREAM_ERR with IRQ disabled — status bits still set, but
     *            km_irq_o should not fire (verifiable only at TB level; here
     *            we at least confirm the DRBG_ERR status bit still gets set).
     *--------------------------------------------------------------------------*/
    TEST_SUBTEST_START("STREAM_ERR with IRQ masked still sets DRBG_ERR status");

    disable_drbg_irq();
    clear_stream_err();
    clear_count_bad();
    clear_kmcsr_drbg_err();

    if (DRBG_STATUS_REG.f.stream_err != 0u) {
        TEST_FAIL("STATUS.STREAM_ERR not clear at start of subtest 2");
    }
    if (KMCSR_IRQ_STATUS_REG.f.drbg_err != 0u) {
        TEST_FAIL("IRQ_STATUS.DRBG_ERR not clear at start of subtest 2");
    }

    if (!tb_drbg_stop(1000)) {
        TEST_FAIL("tb_drbg_stop failed (subtest 2)");
    }
    if (!tb_drbg_tvalid_glitch(1000)) {
        TEST_FAIL("tb_drbg_tvalid_glitch failed (subtest 2)");
    }
    test_delay(SETTLE_CYCLES);

    /* IRQ_STATUS.DRBG_ERR is set unconditionally (interrupt enable only gates km_irq_o) */
    if (DRBG_STATUS_REG.f.stream_err == 0u) {
        TEST_FAIL("STATUS.STREAM_ERR not set (masked-IRQ case)");
    }
    if (KMCSR_IRQ_STATUS_REG.f.drbg_err == 0u) {
        TEST_FAIL("IRQ_STATUS.DRBG_ERR not set when IRQ masked");
    }

    TEST_LOG("  STREAM_ERR and DRBG_ERR set correctly with IRQ masked");
    TEST_SUBTEST_PASS();

    TEST_PASS();
    return 0;
}
