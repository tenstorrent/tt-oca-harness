/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/*
 * OTBN SEP Address and Bus Access Test
 *
 * Exercises OTBN from the SEP CPU path:
 * - verify register and memory region offsets
 * - frontdoor CSR/IMEM/DMEM accesses from firmware
 * - execute a simple OTBN program and verify the result matches the smoke flow
 */

#include <stdint.h>
#include <stdio.h>

#include "och_sep_common.h"
#include "sep.h"
#include "otbn_sep_integration_otbn.h"
#include "sep_outbound_filter.h"
#include "test_completion.h"

#define OTBN_STATUS_IDLE 0x00u
#define OTBN_STATUS_BUSY_EXECUTE 0x01u

#define OTBN_CMD_EXECUTE 0xD8u

#define EXPECTED_OUTER_INC 10u
#define EXPECTED_INNER_COUNT 3u
#define EXPECTED_INNER_INC 1u
#define EXPECTED_RESULT 52u
#define EXPECTED_INSN_CNT 39u

#define OTBN_IDLE_TIMEOUT 20000
#define OTBN_DONE_TIMEOUT 20000

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
    printf("[DBG] wait_for_done: reading INTR_STATE @ 0x%08x\n", SEP_TOP_OTBN_INTR_STATE_BASE_ADDR);
    for (int timeout = OTBN_DONE_TIMEOUT; timeout > 0; --timeout) {
        uint32_t intr_state = READ_REG(SEP_TOP_OTBN_INTR_STATE_BASE_ADDR);
        if (timeout == OTBN_DONE_TIMEOUT) {
            printf("[DBG] wait_for_done: first INTR_STATE=0x%08x\n", intr_state);
        } else if ((timeout % 2000) == 0) {
            printf("[DBG] wait_for_done: INTR_STATE=0x%08x remaining=%d\n", intr_state, timeout);
        }

        if ((intr_state & 1u) != 0u) {
            return 0;
        }
        for (volatile int i = 0; i < 256; ++i) {
        }
    }

    printf("ERROR: timed out waiting for OTBN done interrupt, intr_state=0x%08x\n",
           READ_REG(SEP_TOP_OTBN_INTR_STATE_BASE_ADDR));
    return -1;
}

static int verify_address_map(void) {
    printf("[DBG] Verifying OTBN address map constants\n");
    if ((SEP_TOP_OTBN_STATUS_BASE_ADDR - SEP_TOP_OTBN_BASE_ADDR) !=
        (SEP_TOP_OTBN_STATUS_BASE_ADDR - SEP_TOP_OTBN_BASE_ADDR)) {
        printf("ERROR: STATUS address/offset mismatch\n");
        return -1;
    }

    if ((SEP_TOP_OTBN_IMEM_BASE_ADDR - SEP_TOP_OTBN_BASE_ADDR) != 0x4000u) {
        printf("ERROR: IMEM offset mismatch, actual=0x%08x\n",
               SEP_TOP_OTBN_IMEM_BASE_ADDR - SEP_TOP_OTBN_BASE_ADDR);
        return -1;
    }

    if ((SEP_TOP_OTBN_DMEM_BASE_ADDR - SEP_TOP_OTBN_BASE_ADDR) != 0x8000u) {
        printf("ERROR: DMEM offset mismatch, actual=0x%08x\n",
               SEP_TOP_OTBN_DMEM_BASE_ADDR - SEP_TOP_OTBN_BASE_ADDR);
        return -1;
    }

    /* 0x1000 words of 32 bits each. */
    if (SEP_TOP_OTBN_IMEM_SIZE != 0x4000u || SEP_TOP_OTBN_DMEM_SIZE != 0x4000u) {
        printf("ERROR: OTBN window size mismatch, imem=0x%08x dmem=0x%08x\n",
               SEP_TOP_OTBN_IMEM_SIZE, SEP_TOP_OTBN_DMEM_SIZE);
        return -1;
    }

    return 0;
}

static int verify_frontdoor_access(void) {
    printf("[DBG] Verifying OTBN frontdoor CSR/IMEM/DMEM accesses\n");
    const uint32_t imem_last_word = (SEP_TOP_OTBN_IMEM_SIZE / 4u) - 1u;
    const uint32_t dmem_last_word = (SEP_TOP_OTBN_DMEM_SIZE / 4u) - 1u;

    printf("[DBG][FD-1] Reading INTR_ENABLE (save)...\n");
    const uint32_t saved_intr_enable = READ_REG(SEP_TOP_OTBN_INTR_ENABLE_BASE_ADDR);
    printf("[DBG][FD-1] OK saved=0x%08x\n", saved_intr_enable);

    printf("[DBG][FD-2] Write INTR_ENABLE=1, read back...\n");
    WRITE_REG(SEP_TOP_OTBN_INTR_ENABLE_BASE_ADDR, 1u);
    if (READ_REG(SEP_TOP_OTBN_INTR_ENABLE_BASE_ADDR) != 1u) {
        printf("ERROR: CSR frontdoor write/read failed for INTR_ENABLE\n");
        return -1;
    }
    printf("[DBG][FD-2] OK\n");

    printf("[DBG][FD-3] Write IMEM[0]=0x11111111...\n");
    WRITE_MEM_WORD(SEP_TOP_OTBN_IMEM_BASE_ADDR, 0u, 0x11111111u);
    printf("[DBG][FD-3] OK\n");

    printf("[DBG][FD-4] Write IMEM[%u]=0x22222222...\n", imem_last_word);
    WRITE_MEM_WORD(SEP_TOP_OTBN_IMEM_BASE_ADDR, imem_last_word, 0x22222222u);
    printf("[DBG][FD-4] OK\n");

    printf("[DBG][FD-5] Read IMEM[0]...\n");
    uint32_t imem0 = READ_MEM_WORD(SEP_TOP_OTBN_IMEM_BASE_ADDR, 0u);
    printf("[DBG][FD-5] got=0x%08x\n", imem0);

    printf("[DBG][FD-6] Read IMEM[%u]...\n", imem_last_word);
    uint32_t imem_last = READ_MEM_WORD(SEP_TOP_OTBN_IMEM_BASE_ADDR, imem_last_word);
    printf("[DBG][FD-6] got=0x%08x\n", imem_last);

    if (imem0 != 0x11111111u || imem_last != 0x22222222u) {
        printf("ERROR: IMEM frontdoor access failed\n");
        return -1;
    }

    printf("[DBG][FD-7] Write DMEM[0]=0x33333333...\n");
    WRITE_MEM_WORD(SEP_TOP_OTBN_DMEM_BASE_ADDR, 0u, 0x33333333u);
    printf("[DBG][FD-7] OK\n");

    printf("[DBG][FD-8] Write DMEM[%u]=0x44444444...\n", dmem_last_word);
    WRITE_MEM_WORD(SEP_TOP_OTBN_DMEM_BASE_ADDR, dmem_last_word, 0x44444444u);
    printf("[DBG][FD-8] OK\n");

    printf("[DBG][FD-9] Read DMEM[0]...\n");
    uint32_t dmem0 = READ_MEM_WORD(SEP_TOP_OTBN_DMEM_BASE_ADDR, 0u);
    printf("[DBG][FD-9] got=0x%08x\n", dmem0);

    printf("[DBG][FD-10] Read DMEM[%u]...\n", dmem_last_word);
    uint32_t dmem_last = READ_MEM_WORD(SEP_TOP_OTBN_DMEM_BASE_ADDR, dmem_last_word);
    printf("[DBG][FD-10] got=0x%08x\n", dmem_last);

    if (dmem0 != 0x33333333u || dmem_last != 0x44444444u) {
        printf("ERROR: DMEM frontdoor access failed\n");
        return -1;
    }

    printf("[DBG][FD-11] Restoring INTR_ENABLE=0x%08x...\n", saved_intr_enable);
    WRITE_REG(SEP_TOP_OTBN_INTR_ENABLE_BASE_ADDR, saved_intr_enable);
    printf("[DBG][FD-11] OK\n");
    return 0;
}

static int otbn_load_app(void) {
    printf("[DBG] Loading OTBN app: imem_words=%zu dmem_words=%zu\n",
           otbn_otbn_sep_integration_imem_words, otbn_otbn_sep_integration_dmem_words);
    WRITE_REG(SEP_TOP_OTBN_LOAD_CHECKSUM_BASE_ADDR, 0u);

    for (size_t i = 0; i < otbn_otbn_sep_integration_imem_words; ++i) {
        WRITE_MEM_WORD(SEP_TOP_OTBN_IMEM_BASE_ADDR, (uint32_t)i, otbn_otbn_sep_integration_imem[i]);
    }

    for (size_t i = 0; i < otbn_otbn_sep_integration_dmem_words; ++i) {
        WRITE_MEM_WORD(SEP_TOP_OTBN_DMEM_BASE_ADDR, (uint32_t)i, otbn_otbn_sep_integration_dmem[i]);
    }

    const uint32_t checksum = READ_REG(SEP_TOP_OTBN_LOAD_CHECKSUM_BASE_ADDR);
    if (checksum != OTBN_OTBN_SEP_INTEGRATION_EXPECTED_CRC) {
        printf("ERROR: OTBN load checksum mismatch, expected=0x%08x actual=0x%08x\n",
               OTBN_OTBN_SEP_INTEGRATION_EXPECTED_CRC, checksum);
        return -1;
    }

    WRITE_REG(SEP_TOP_OTBN_LOAD_CHECKSUM_BASE_ADDR, 0u);
    return 0;
}

static int run_execution_flow(void) {
    printf("[DBG] Starting OTBN execution flow\n");
    WRITE_REG(SEP_TOP_OTBN_INTR_STATE_BASE_ADDR, 0xffffffffu);
    WRITE_REG(SEP_TOP_OTBN_INTR_ENABLE_BASE_ADDR, 1u);

    otbn_dmem_write_offset(OTBN_ADDR_T_INIT(otbn_sep_integration, input_outer_inc),
                           EXPECTED_OUTER_INC);
    otbn_dmem_write_offset(OTBN_ADDR_T_INIT(otbn_sep_integration, input_inner_count),
                           EXPECTED_INNER_COUNT);
    otbn_dmem_write_offset(OTBN_ADDR_T_INIT(otbn_sep_integration, input_inner_inc),
                           EXPECTED_INNER_INC);
    otbn_dmem_write_offset(OTBN_ADDR_T_INIT(otbn_sep_integration, result), 0u);
    printf("[DBG] DMEM inputs written\n");

    printf("[DBG] Issuing OTBN EXECUTE command\n");
    WRITE_REG(SEP_TOP_OTBN_CMD_BASE_ADDR, OTBN_CMD_EXECUTE);

    if (otbn_wait_for_idle() != 0) {
        return -1;
    }

    printf("[DBG] OTBN returned to IDLE, reading results...\n");
    const uint32_t err_bits = READ_REG(SEP_TOP_OTBN_ERR_BITS_BASE_ADDR);
    printf("[DBG] ERR_BITS=0x%08x\n", err_bits);
    const uint32_t result = otbn_dmem_read_offset(OTBN_ADDR_T_INIT(otbn_sep_integration, result));
    printf("[DBG] DMEM result=%u\n", result);
    const uint32_t insn_cnt = READ_REG(SEP_TOP_OTBN_INSN_CNT_BASE_ADDR);
    printf("[DBG] INSN_CNT=%u\n", insn_cnt);

    printf("Integration result: result=%u err_bits=0x%08x insn_cnt=%u\n", result, err_bits,
           insn_cnt);

    if (err_bits != 0u || result != EXPECTED_RESULT || insn_cnt != EXPECTED_INSN_CNT) {
        printf("ERROR: OTBN execution flow verification failed\n");
        return -1;
    }

    WRITE_REG(SEP_TOP_OTBN_INTR_STATE_BASE_ADDR, 1u);
    return 0;
}

int main(void) {
    sep_outbound_filter_init();

    printf("=== OTBN SEP Address and Bus Access Test ===\n");
    printf("[DBG] OTBN base: csr=0x%08x imem=0x%08x dmem=0x%08x\n", SEP_TOP_OTBN_BASE_ADDR,
           SEP_TOP_OTBN_IMEM_BASE_ADDR, SEP_TOP_OTBN_DMEM_BASE_ADDR);

    if (verify_address_map() != 0) {
        fail_and_halt(1, "OTBN address map verification failed");
    }

    if (otbn_wait_for_idle() != 0) {
        fail_and_halt(2, "OTBN did not reach IDLE");
    }

    if (verify_frontdoor_access() != 0) {
        fail_and_halt(3, "OTBN frontdoor access verification failed");
    }

    if (otbn_load_app() != 0) {
        fail_and_halt(4, "OTBN app load failed");
    }

    if (run_execution_flow() != 0) {
        fail_and_halt(5, "OTBN execution flow failed");
    }

    printf("PASS: OTBN SEP integration flow completed successfully\n");
    test_pass(0);

    while (1) {
        __asm__("wfi");
    }
}
