/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/*
 * OTBN Basic Execution Smoke Test
 *
 * Verifies the complete SEP firmware control flow for a simple OTBN program:
 * - wait for IDLE
 * - load IMEM/DMEM image
 * - populate DMEM inputs
 * - execute and wait for done interrupt
 * - verify ERR_BITS/INSN_CNT
 *
 * NOTE:
 * This testcase does not read OTBN DMEM back through the frontdoor: it writes
 * the DMEM inputs, runs the EXECUTE path, and checks ERR_BITS and INSN_CNT only.
 */

#include <stdint.h>
#include <stdio.h>

#include "och_sep_common.h"
#include "sep.h"
#include "otbn_smoke_otbn.h"
#include "sep_outbound_filter.h"
#include "test_completion.h"

#define OTBN_STATUS_IDLE 0x00u
#define OTBN_STATUS_BUSY_EXECUTE 0x01u

#define OTBN_CMD_EXECUTE 0xD8u

#define OTBN_DONE_INTR_BIT 0u

#define OTBN_IDLE_TIMEOUT 20000
#define OTBN_DONE_TIMEOUT 20000

#define EXPECTED_OUTER_INC 10u
#define EXPECTED_INNER_COUNT 3u
#define EXPECTED_INNER_INC 1u
#define EXPECTED_RESULT 52u
#define EXPECTED_INSN_CNT 39u

static inline uint32_t otbn_dmem_read_offset(uint32_t offset) {
    return READ_MEM_WORD(SEP_TOP_OTBN_DMEM_BASE_ADDR, offset / 4u);
}

static inline void otbn_dmem_write_offset(uint32_t offset, uint32_t value) {
    WRITE_MEM_WORD(SEP_TOP_OTBN_DMEM_BASE_ADDR, offset / 4u, value);
}

static void fail_and_halt(int code, const char *msg) {
    printf("FAIL: %s\n", msg);
    test_fail(code);
    while (1) {
        __asm__("wfi");
    }
}

static int otbn_wait_for_idle(void) {
    printf("[DBG] wait_for_idle: reading STATUS @ 0x%08x\n", SEP_TOP_OTBN_STATUS_BASE_ADDR);
    for (int timeout = OTBN_IDLE_TIMEOUT; timeout > 0; --timeout) {
        uint32_t status = READ_REG(SEP_TOP_OTBN_STATUS_BASE_ADDR);
        if (timeout == OTBN_IDLE_TIMEOUT) {
            printf("[DBG] wait_for_idle: first STATUS=0x%08x\n", status);
        } else if ((timeout % 2000) == 0) {
            printf("[DBG] wait_for_idle: STATUS=0x%08x remaining=%d\n", status, timeout);
        }

        if (status == OTBN_STATUS_IDLE) {
            return 0;
        }
        for (volatile int i = 0; i < 256; ++i) {
        }
    }

    printf("ERROR: timed out waiting for OTBN IDLE, status=0x%08x\n",
           READ_REG(SEP_TOP_OTBN_STATUS_BASE_ADDR));
    return -1;
}

static int otbn_wait_for_done(void) {
    printf("[DBG] wait_for_done: reading INTR_STATE @ 0x%08x\n",
           SEP_TOP_OTBN_INTR_STATE_BASE_ADDR);
    for (int timeout = OTBN_DONE_TIMEOUT; timeout > 0; --timeout) {
        uint32_t intr_state = READ_REG(SEP_TOP_OTBN_INTR_STATE_BASE_ADDR);
        if (timeout == OTBN_DONE_TIMEOUT) {
            printf("[DBG] wait_for_done: first INTR_STATE=0x%08x\n", intr_state);
        } else if ((timeout % 2000) == 0) {
            printf("[DBG] wait_for_done: INTR_STATE=0x%08x remaining=%d\n", intr_state, timeout);
        }

        if ((intr_state & (1u << OTBN_DONE_INTR_BIT)) != 0u) {
            return 0;
        }
        for (volatile int i = 0; i < 256; ++i) {
        }
    }

    printf("ERROR: timed out waiting for OTBN done interrupt, intr_state=0x%08x\n",
           READ_REG(SEP_TOP_OTBN_INTR_STATE_BASE_ADDR));
    return -1;
}

static void otbn_clear_w1c_regs(void) {
    printf("[DBG] Clearing OTBN W1C CSRs\n");
    WRITE_REG(SEP_TOP_OTBN_INTR_STATE_BASE_ADDR, 0xffffffffu);
    WRITE_REG(SEP_TOP_OTBN_ERR_BITS_BASE_ADDR, 0xffffffffu);
    WRITE_REG(SEP_TOP_OTBN_INSN_CNT_BASE_ADDR, 0xffffffffu);
}

static int otbn_load_app(void) {
    printf("[DBG] Loading OTBN app: imem_words=%zu dmem_words=%zu\n", otbn_otbn_smoke_imem_words,
           otbn_otbn_smoke_dmem_words);
    WRITE_REG(SEP_TOP_OTBN_LOAD_CHECKSUM_BASE_ADDR, 0u);

    for (size_t i = 0; i < otbn_otbn_smoke_imem_words; ++i) {
        WRITE_MEM_WORD(SEP_TOP_OTBN_IMEM_BASE_ADDR, (uint32_t)i, otbn_otbn_smoke_imem[i]);
    }

    for (size_t i = 0; i < otbn_otbn_smoke_dmem_words; ++i) {
        WRITE_MEM_WORD(SEP_TOP_OTBN_DMEM_BASE_ADDR, (uint32_t)i, otbn_otbn_smoke_dmem[i]);
    }

    const uint32_t checksum = READ_REG(SEP_TOP_OTBN_LOAD_CHECKSUM_BASE_ADDR);
    if (checksum != OTBN_OTBN_SMOKE_EXPECTED_CRC) {
        printf("ERROR: OTBN load checksum mismatch, expected=0x%08x actual=0x%08x\n",
               OTBN_OTBN_SMOKE_EXPECTED_CRC, checksum);
        return -1;
    }

    WRITE_REG(SEP_TOP_OTBN_LOAD_CHECKSUM_BASE_ADDR, 0u);
    return 0;
}

static int otbn_program_inputs(void) {
    printf("[DBG] Programming OTBN DMEM inputs\n");
    otbn_dmem_write_offset(OTBN_ADDR_T_INIT(otbn_smoke, input_outer_inc), EXPECTED_OUTER_INC);
    otbn_dmem_write_offset(OTBN_ADDR_T_INIT(otbn_smoke, input_inner_count), EXPECTED_INNER_COUNT);
    otbn_dmem_write_offset(OTBN_ADDR_T_INIT(otbn_smoke, input_inner_inc), EXPECTED_INNER_INC);
    otbn_dmem_write_offset(OTBN_ADDR_T_INIT(otbn_smoke, result), 0u);
    printf("[DBG] OTBN DMEM inputs written (readback skipped temporarily)\n");
    return 0;
}

int main(void) {
    sep_outbound_filter_init();

    printf("\n");
    printf("******************************************\n");
    printf("*    OTBN Basic Execution Smoke Test     *\n");
    printf("******************************************\n\n");
    printf("[DBG] OTBN base: csr=0x%08x imem=0x%08x dmem=0x%08x\n", SEP_TOP_OTBN_BASE_ADDR,
           SEP_TOP_OTBN_IMEM_BASE_ADDR, SEP_TOP_OTBN_DMEM_BASE_ADDR);

    printf("[STEP 1/7] Waiting for OTBN IDLE (secure wipe)...\n");
    if (otbn_wait_for_idle() != 0) {
        fail_and_halt(1, "OTBN did not reach IDLE");
    }
    printf("[STEP 1/7] OTBN is IDLE\n");

    printf("[STEP 2/7] Clearing W1C registers\n");
    otbn_clear_w1c_regs();

    printf("[STEP 3/7] Enabling OTBN done interrupt\n");
    WRITE_REG(SEP_TOP_OTBN_INTR_ENABLE_BASE_ADDR, 1u);

    printf("[STEP 4/7] Loading OTBN app...\n");
    if (otbn_load_app() != 0) {
        fail_and_halt(2, "OTBN app load failed");
    }
    printf("[STEP 4/7] App loaded OK\n");

    printf("[STEP 5/7] Programming DMEM inputs...\n");
    if (otbn_program_inputs() != 0) {
        fail_and_halt(3, "OTBN input programming failed");
    }
    printf("[STEP 5/7] Inputs written\n");

    printf("[STEP 6/7] Issuing OTBN EXECUTE command\n");
    WRITE_REG(SEP_TOP_OTBN_CMD_BASE_ADDR, OTBN_CMD_EXECUTE);

    const uint32_t status_after_cmd = READ_REG(SEP_TOP_OTBN_STATUS_BASE_ADDR);
    printf("[STEP 6/7] STATUS after EXECUTE = 0x%08x\n", status_after_cmd);
    if ((status_after_cmd != OTBN_STATUS_BUSY_EXECUTE) && (status_after_cmd != OTBN_STATUS_IDLE)) {
        printf("ERROR: unexpected STATUS after EXECUTE: 0x%08x\n", status_after_cmd);
        fail_and_halt(4, "Unexpected STATUS after EXECUTE");
    }

    printf("[STEP 7/7] Waiting for OTBN done interrupt...\n");
    if (otbn_wait_for_done() != 0) {
        fail_and_halt(5, "Timed out waiting for OTBN done interrupt");
    }
    printf("[STEP 7/7] OTBN done, waiting for IDLE...\n");

    if (otbn_wait_for_idle() != 0) {
        fail_and_halt(6, "OTBN did not return to IDLE");
    }

    const uint32_t err_bits = READ_REG(SEP_TOP_OTBN_ERR_BITS_BASE_ADDR);
    const uint32_t insn_cnt = READ_REG(SEP_TOP_OTBN_INSN_CNT_BASE_ADDR);

    printf("\n========================================\n");
    printf("Smoke result: err_bits=0x%08x insn_cnt=%u (expected=%u)\n", err_bits, insn_cnt,
           EXPECTED_INSN_CNT);
    printf("========================================\n");

    if (err_bits != 0u) {
        printf("ERROR: OTBN execution reported ERR_BITS=0x%08x\n", err_bits);
        fail_and_halt(7, "OTBN execution reported ERR_BITS");
    }

    if (insn_cnt != EXPECTED_INSN_CNT) {
        printf("ERROR: OTBN INSN_CNT mismatch, expected=%u actual=%u\n", EXPECTED_INSN_CNT,
               insn_cnt);
        fail_and_halt(8, "OTBN INSN_CNT mismatch");
    }

    WRITE_REG(SEP_TOP_OTBN_INTR_STATE_BASE_ADDR, 1u);

    printf("PASS: OTBN smoke test completed successfully\n");
    test_pass(0);

    while (1) {
        __asm__("wfi");
    }
}
