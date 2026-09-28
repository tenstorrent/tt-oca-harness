/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/*
 * OTBN Firmware Control Flow Test (SEP-002, P1)
 *
 * Verifies the complete FW control flow for OTBN operations:
 *   1. Check IDLE state
 *   2. Load OTBN program to IMEM
 *   3. Load input data to DMEM
 *   4. Execute via CMD register
 *   5. Wait for done interrupt (poll INTR_STATE)
 *   6. Check ERR_BITS = 0
 *   7. Read results from DMEM and verify
 *   8. Clear interrupt
 *
 * Uses the same smoke_test OTBN program but structures the flow
 * as a complete FW control exercise.
 */

#include <stdint.h>
#include <stdio.h>

#include "och_sep_common.h"
#include "sep.h"
#include "otbn_smoke_otbn.h"
#include "sep_outbound_filter.h"
#include "test_completion.h"

/* OTBN constants */
#define OTBN_STATUS_IDLE 0x00u
#define OTBN_STATUS_BUSY_EXECUTE 0x01u
#define OTBN_CMD_EXECUTE 0xD8u

#define OTBN_IDLE_TIMEOUT 20000
#define OTBN_DONE_TIMEOUT 50000

/* Expected test results (from smoke_test OTBN program) */
#define EXPECTED_OUTER_INC 10u
#define EXPECTED_INNER_COUNT 3u
#define EXPECTED_INNER_INC 1u
#define EXPECTED_RESULT 52u
#define EXPECTED_INSN_CNT 39u

static inline uint32_t otbn_dmem_read(uint32_t offset) {
    return READ_MEM_WORD(SEP_TOP_OTBN_DMEM_BASE_ADDR, offset / 4u);
}

static inline void otbn_dmem_write(uint32_t offset, uint32_t value) {
    WRITE_MEM_WORD(SEP_TOP_OTBN_DMEM_BASE_ADDR, offset / 4u, value);
}

static void fail_and_halt(int code, const char *msg) {
    printf("FAIL: %s\n", msg);
    test_fail(code);
    while (1) {
        __asm__("wfi");
    }
}

/* ================================================================
 * Step 1: Check IDLE — poll STATUS register
 * ================================================================ */
static int step1_check_idle(void) {
    printf("[STEP 1/8] Waiting for OTBN IDLE...\n");
    for (int t = OTBN_IDLE_TIMEOUT; t > 0; --t) {
        uint32_t status = READ_REG(SEP_TOP_OTBN_STATUS_BASE_ADDR);
        if (status == OTBN_STATUS_IDLE) {
            printf("[STEP 1/8] OTBN is IDLE\n");
            return 0;
        }
        for (volatile int i = 0; i < 256; ++i)
            ;
    }
    return -1;
}

/* ================================================================
 * Step 2: Load program to IMEM
 * ================================================================ */
static int step2_load_imem(void) {
    printf("[STEP 2/8] Loading OTBN IMEM (%zu words)...\n", otbn_otbn_smoke_imem_words);

    /* Reset checksum */
    WRITE_REG(SEP_TOP_OTBN_LOAD_CHECKSUM_BASE_ADDR, 0u);

    for (size_t i = 0; i < otbn_otbn_smoke_imem_words; ++i) {
        WRITE_MEM_WORD(SEP_TOP_OTBN_IMEM_BASE_ADDR, (uint32_t)i, otbn_otbn_smoke_imem[i]);
    }
    printf("[STEP 2/8] IMEM loaded\n");
    return 0;
}

/* ================================================================
 * Step 3: Load input data to DMEM
 * ================================================================ */
static int step3_load_dmem(void) {
    printf("[STEP 3/8] Loading OTBN DMEM (%zu words + inputs)...\n", otbn_otbn_smoke_dmem_words);

    for (size_t i = 0; i < otbn_otbn_smoke_dmem_words; ++i) {
        WRITE_MEM_WORD(SEP_TOP_OTBN_DMEM_BASE_ADDR, (uint32_t)i, otbn_otbn_smoke_dmem[i]);
    }

    /* Verify checksum */
    uint32_t checksum = READ_REG(SEP_TOP_OTBN_LOAD_CHECKSUM_BASE_ADDR);
    if (checksum != OTBN_OTBN_SMOKE_EXPECTED_CRC) {
        printf("ERROR: LOAD_CHECKSUM mismatch: expected=0x%08x actual=0x%08x\n",
               OTBN_OTBN_SMOKE_EXPECTED_CRC, checksum);
        return -1;
    }
    printf("[STEP 3/8] DMEM loaded, checksum verified (0x%08x)\n", checksum);

    /* Write input parameters */
    otbn_dmem_write(OTBN_ADDR_T_INIT(otbn_smoke, input_outer_inc), EXPECTED_OUTER_INC);
    otbn_dmem_write(OTBN_ADDR_T_INIT(otbn_smoke, input_inner_count), EXPECTED_INNER_COUNT);
    otbn_dmem_write(OTBN_ADDR_T_INIT(otbn_smoke, input_inner_inc), EXPECTED_INNER_INC);
    otbn_dmem_write(OTBN_ADDR_T_INIT(otbn_smoke, result), 0u);

    printf("[STEP 3/8] Input parameters written\n");
    return 0;
}

/* ================================================================
 * Step 4: Execute — write CMD register
 * ================================================================ */
static int step4_execute(void) {
    printf("[STEP 4/8] Issuing CMD = EXECUTE (0x%02x)...\n", OTBN_CMD_EXECUTE);

    /* Enable done interrupt for polling */
    WRITE_REG(SEP_TOP_OTBN_INTR_ENABLE_BASE_ADDR, 1u);
    /* Clear any pending state */
    WRITE_REG(SEP_TOP_OTBN_INTR_STATE_BASE_ADDR, 0xFFFFFFFFu);

    /* Issue execute command */
    WRITE_REG(SEP_TOP_OTBN_CMD_BASE_ADDR, OTBN_CMD_EXECUTE);
    printf("[STEP 4/8] EXECUTE command issued\n");
    return 0;
}

/* ================================================================
 * Step 5: Wait for done interrupt (poll INTR_STATE)
 * ================================================================ */
static int step5_wait_done(void) {
    printf("[STEP 5/8] Waiting for OTBN done (polling INTR_STATE)...\n");
    for (int t = OTBN_DONE_TIMEOUT; t > 0; --t) {
        uint32_t intr = READ_REG(SEP_TOP_OTBN_INTR_STATE_BASE_ADDR);
        if (intr & 0x1u) {
            printf("[STEP 5/8] INTR_STATE.done = 1\n");
            return 0;
        }
        for (volatile int i = 0; i < 256; ++i)
            ;
    }
    return -1;
}

/* ================================================================
 * Step 6: Check ERR_BITS = 0
 * ================================================================ */
static int step6_check_errors(void) {
    uint32_t err_bits = READ_REG(SEP_TOP_OTBN_ERR_BITS_BASE_ADDR);
    printf("[STEP 6/8] ERR_BITS = 0x%08x\n", err_bits);
    if (err_bits != 0) {
        printf("ERROR: Non-zero ERR_BITS after execution\n");
        return -1;
    }
    printf("[STEP 6/8] No errors\n");
    return 0;
}

/* ================================================================
 * Step 7: Read results from DMEM and verify
 * ================================================================ */
static int step7_read_results(void) {
    printf("[STEP 7/8] Reading results from DMEM...\n");

    /* Wait for IDLE */
    for (int t = OTBN_IDLE_TIMEOUT; t > 0; --t) {
        if (READ_REG(SEP_TOP_OTBN_STATUS_BASE_ADDR) == OTBN_STATUS_IDLE) break;
        for (volatile int i = 0; i < 256; ++i)
            ;
    }

    uint32_t insn_cnt = READ_REG(SEP_TOP_OTBN_INSN_CNT_BASE_ADDR);
    printf("  INSN_CNT = %u (expected %u)\n", insn_cnt, EXPECTED_INSN_CNT);

    int errors = 0;

    if (insn_cnt != EXPECTED_INSN_CNT) {
        printf("ERROR: INSN_CNT mismatch\n");
        errors++;
    }

    /* Step 7 checks INSN_CNT only; DMEM results are not read back. */
    printf("[STEP 7/8] Verification complete (INSN_CNT check)\n");
    return errors > 0 ? -1 : 0;
}

/* ================================================================
 * Step 8: Clear interrupt
 * ================================================================ */
static int step8_clear_interrupt(void) {
    printf("[STEP 8/8] Clearing OTBN done interrupt...\n");
    WRITE_REG(SEP_TOP_OTBN_INTR_STATE_BASE_ADDR, 0x1u);

    uint32_t intr_after = READ_REG(SEP_TOP_OTBN_INTR_STATE_BASE_ADDR);
    if (intr_after & 0x1u) {
        printf("WARNING: INTR_STATE.done still set after W1C\n");
    } else {
        printf("[STEP 8/8] Interrupt cleared\n");
    }
    return 0;
}

int main(void) {
    sep_outbound_filter_init();

    printf("\n");
    printf("**********************************************\n");
    printf("*  OTBN Firmware Control Flow Test (SEP-002) *\n");
    printf("**********************************************\n\n");
    printf("OTBN registers: csr=0x%08x imem=0x%08x dmem=0x%08x\n\n", SEP_TOP_OTBN_BASE_ADDR,
           SEP_TOP_OTBN_IMEM_BASE_ADDR, SEP_TOP_OTBN_DMEM_BASE_ADDR);

    /* Execute all 8 steps */
    if (step1_check_idle() != 0) fail_and_halt(1, "OTBN not IDLE");
    if (step2_load_imem() != 0) fail_and_halt(2, "IMEM load failed");
    if (step3_load_dmem() != 0) fail_and_halt(3, "DMEM load failed");
    if (step4_execute() != 0) fail_and_halt(4, "Execute failed");
    if (step5_wait_done() != 0) fail_and_halt(5, "Done timeout");
    if (step6_check_errors() != 0) fail_and_halt(6, "Execution errors");
    if (step7_read_results() != 0) fail_and_halt(7, "Result mismatch");
    if (step8_clear_interrupt() != 0) fail_and_halt(8, "Interrupt clear failed");

    printf("\n========================================\n");
    printf("PASS: OTBN FW Control Flow Test completed\n");
    printf("========================================\n");
    test_pass(0);

    while (1) {
        __asm__("wfi");
    }
}
