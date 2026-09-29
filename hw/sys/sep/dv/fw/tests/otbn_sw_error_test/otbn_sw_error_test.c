/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/*
 * OTBN Software Error Handling Test
 *
 * Runs the OTBN software error scenarios from SEP firmware:
 * - recoverable mode (CTRL.software_errs_fatal = 0):
 *   BAD_DATA_ADDR, BAD_INSN_ADDR, ILLEGAL_INSN, CALL_STACK, LOOP
 * - fatal mode (CTRL.software_errs_fatal = 1):
 *   ILLEGAL_INSN promoted to LOCKED + fatal_software alert cause
 */

#include <stddef.h>
#include <stdint.h>
#include <stdio.h>

#include "bad_data_addr_otbn.h"
#include "bad_insn_addr_otbn.h"
#include "call_stack_otbn.h"
#include "illegal_insn_otbn.h"
#include "loop_error_otbn.h"
#include "och_sep_common.h"
#include "sep.h"
#include "sep_outbound_filter.h"
#include "test_completion.h"

#define OTBN_STATUS_IDLE 0x00u
#define OTBN_STATUS_BUSY_EXECUTE 0x01u
#define OTBN_STATUS_LOCKED 0xffu

#define OTBN_CMD_EXECUTE 0xD8u
#define OTBN_CTRL_SW_ERRS_FATAL 0x1u

#define OTBN_STATUS_TIMEOUT 20000

#define ARRAY_SIZE(a) (sizeof(a) / sizeof((a)[0]))

typedef struct {
    const char *name;
    const uint32_t *imem;
    size_t imem_words;
    const uint32_t *dmem;
    size_t dmem_words;
    uint32_t expected_crc;
    uint32_t expected_err_bits;
} otbn_error_app_t;

static void init_recoverable_cases(otbn_error_app_t cases[5]) {
    cases[0] = (otbn_error_app_t){
        .name = "BAD_DATA_ADDR",
        .imem = otbn_bad_data_addr_imem,
        .imem_words = otbn_bad_data_addr_imem_words,
        .dmem = otbn_bad_data_addr_dmem,
        .dmem_words = otbn_bad_data_addr_dmem_words,
        .expected_crc = OTBN_BAD_DATA_ADDR_EXPECTED_CRC,
        .expected_err_bits = OTBN__ERR_BITS__BAD_DATA_ADDR_bm,
    };

    cases[1] = (otbn_error_app_t){
        .name = "BAD_INSN_ADDR",
        .imem = otbn_bad_insn_addr_imem,
        .imem_words = otbn_bad_insn_addr_imem_words,
        .dmem = otbn_bad_insn_addr_dmem,
        .dmem_words = otbn_bad_insn_addr_dmem_words,
        .expected_crc = OTBN_BAD_INSN_ADDR_EXPECTED_CRC,
        .expected_err_bits = OTBN__ERR_BITS__BAD_INSN_ADDR_bm,
    };

    cases[2] = (otbn_error_app_t){
        .name = "ILLEGAL_INSN",
        .imem = otbn_illegal_insn_imem,
        .imem_words = otbn_illegal_insn_imem_words,
        .dmem = otbn_illegal_insn_dmem,
        .dmem_words = otbn_illegal_insn_dmem_words,
        .expected_crc = OTBN_ILLEGAL_INSN_EXPECTED_CRC,
        .expected_err_bits = OTBN__ERR_BITS__ILLEGAL_INSN_bm,
    };

    cases[3] = (otbn_error_app_t){
        .name = "CALL_STACK",
        .imem = otbn_call_stack_imem,
        .imem_words = otbn_call_stack_imem_words,
        .dmem = otbn_call_stack_dmem,
        .dmem_words = otbn_call_stack_dmem_words,
        .expected_crc = OTBN_CALL_STACK_EXPECTED_CRC,
        .expected_err_bits = OTBN__ERR_BITS__CALL_STACK_bm,
    };

    cases[4] = (otbn_error_app_t){
        .name = "LOOP",
        .imem = otbn_loop_error_imem,
        .imem_words = otbn_loop_error_imem_words,
        .dmem = otbn_loop_error_dmem,
        .dmem_words = otbn_loop_error_dmem_words,
        .expected_crc = OTBN_LOOP_ERROR_EXPECTED_CRC,
        .expected_err_bits = OTBN__ERR_BITS__LOOP_bm,
    };
}

static void spin_delay(void) {
    for (volatile int i = 0; i < 256; ++i) {
    }
}

static void fail_and_halt(int code, const char *msg) {
    printf("FAIL: %s\n", msg);
    test_fail(code);
    while (1) {
        __asm__("wfi");
    }
}

static int otbn_wait_for_status(uint32_t expected_status, const char *status_name) {
    for (int timeout = OTBN_STATUS_TIMEOUT; timeout > 0; --timeout) {
        uint32_t status = READ_REG(SEP_TOP_OTBN_STATUS_BASE_ADDR);
        if (timeout == OTBN_STATUS_TIMEOUT) {
            printf("[DBG] wait_for_%s: first STATUS=0x%08x\n", status_name, status);
        } else if ((timeout % 2000) == 0) {
            printf("[DBG] wait_for_%s: STATUS=0x%08x remaining=%d\n", status_name, status, timeout);
        }

        if (status == expected_status) {
            return 0;
        }
        spin_delay();
    }

    printf("ERROR: timed out waiting for OTBN %s, STATUS=0x%08x\n", status_name,
           READ_REG(SEP_TOP_OTBN_STATUS_BASE_ADDR));
    return -1;
}

static void otbn_clear_w1c_regs(void) {
    WRITE_REG(SEP_TOP_OTBN_INTR_STATE_BASE_ADDR, 0xffffffffu);
    WRITE_REG(SEP_TOP_OTBN_ERR_BITS_BASE_ADDR, 0xffffffffu);
    WRITE_REG(SEP_TOP_OTBN_INSN_CNT_BASE_ADDR, 0xffffffffu);
}

static int otbn_load_app(const otbn_error_app_t *app) {
    printf("[DBG] Loading app %-14s imem_words=%zu dmem_words=%zu\n", app->name, app->imem_words,
           app->dmem_words);

    WRITE_REG(SEP_TOP_OTBN_LOAD_CHECKSUM_BASE_ADDR, 0u);

    for (size_t i = 0; i < app->imem_words; ++i) {
        WRITE_MEM_WORD(SEP_TOP_OTBN_IMEM_BASE_ADDR, (uint32_t)i, app->imem[i]);
    }

    for (size_t i = 0; i < app->dmem_words; ++i) {
        WRITE_MEM_WORD(SEP_TOP_OTBN_DMEM_BASE_ADDR, (uint32_t)i, app->dmem[i]);
    }

    uint32_t checksum = READ_REG(SEP_TOP_OTBN_LOAD_CHECKSUM_BASE_ADDR);
    if (checksum != app->expected_crc) {
        printf("ERROR: app %s checksum mismatch, expected=0x%08x actual=0x%08x\n", app->name,
               app->expected_crc, checksum);
        return -1;
    }

    WRITE_REG(SEP_TOP_OTBN_LOAD_CHECKSUM_BASE_ADDR, 0u);
    return 0;
}

static int otbn_set_sw_errs_fatal(uint32_t value) {
    WRITE_REG(SEP_TOP_OTBN_CTRL_BASE_ADDR, value);
    uint32_t ctrl = READ_REG(SEP_TOP_OTBN_CTRL_BASE_ADDR) & OTBN_CTRL_SW_ERRS_FATAL;
    printf("[DBG] CTRL.software_errs_fatal programmed to %u, readback=%u\n",
           value & OTBN_CTRL_SW_ERRS_FATAL, ctrl);
    return ctrl == (value & OTBN_CTRL_SW_ERRS_FATAL) ? 0 : -1;
}

static int otbn_clear_recoverable_state(void) {
    otbn_clear_w1c_regs();

    uint32_t err_bits = READ_REG(SEP_TOP_OTBN_ERR_BITS_BASE_ADDR);
    uint32_t intr_state = READ_REG(SEP_TOP_OTBN_INTR_STATE_BASE_ADDR);
    uint32_t insn_cnt = READ_REG(SEP_TOP_OTBN_INSN_CNT_BASE_ADDR);

    if (err_bits != 0u || intr_state != 0u || insn_cnt != 0u) {
        printf("ERROR: OTBN W1C clear failed err_bits=0x%08x intr_state=0x%08x insn_cnt=0x%08x\n",
               err_bits, intr_state, insn_cnt);
        return -1;
    }

    return 0;
}

static int run_recoverable_case(const otbn_error_app_t *app) {
    if (otbn_wait_for_status(OTBN_STATUS_IDLE, "IDLE") != 0) {
        return -1;
    }

    if (otbn_set_sw_errs_fatal(0u) != 0) {
        printf("ERROR: failed to clear CTRL.software_errs_fatal before %s\n", app->name);
        return -1;
    }

    if (otbn_clear_recoverable_state() != 0) {
        return -1;
    }

    if (otbn_load_app(app) != 0) {
        return -1;
    }

    printf("[DBG] Executing recoverable case %s\n", app->name);
    WRITE_REG(SEP_TOP_OTBN_INTR_ENABLE_BASE_ADDR, 1u);
    WRITE_REG(SEP_TOP_OTBN_CMD_BASE_ADDR, OTBN_CMD_EXECUTE);

    uint32_t status_after_cmd = READ_REG(SEP_TOP_OTBN_STATUS_BASE_ADDR);
    if ((status_after_cmd != OTBN_STATUS_BUSY_EXECUTE) && (status_after_cmd != OTBN_STATUS_IDLE)) {
        printf("ERROR: unexpected STATUS after EXECUTE for %s: 0x%08x\n", app->name,
               status_after_cmd);
        return -1;
    }

    if (otbn_wait_for_status(OTBN_STATUS_IDLE, "IDLE") != 0) {
        return -1;
    }

    uint32_t status = READ_REG(SEP_TOP_OTBN_STATUS_BASE_ADDR);
    uint32_t err_bits = READ_REG(SEP_TOP_OTBN_ERR_BITS_BASE_ADDR);
    uint32_t fatal_alert = READ_REG(SEP_TOP_OTBN_FATAL_ALERT_CAUSE_BASE_ADDR);
    uint32_t intr_state = READ_REG(SEP_TOP_OTBN_INTR_STATE_BASE_ADDR);

    printf("[DBG] %-14s status=0x%08x err_bits=0x%08x intr_state=0x%08x fatal_alert=0x%08x\n",
           app->name, status, err_bits, intr_state, fatal_alert);

    if (status != OTBN_STATUS_IDLE) {
        printf("ERROR: %s did not return to IDLE\n", app->name);
        return -1;
    }

    if (err_bits != app->expected_err_bits) {
        printf("ERROR: %s err_bits mismatch, expected=0x%08x actual=0x%08x\n", app->name,
               app->expected_err_bits, err_bits);
        return -1;
    }

    if (fatal_alert != 0u) {
        printf("ERROR: %s unexpectedly asserted fatal alert cause 0x%08x\n", app->name,
               fatal_alert);
        return -1;
    }

    if (otbn_clear_recoverable_state() != 0) {
        printf("ERROR: %s err_bits clear verification failed\n", app->name);
        return -1;
    }

    return 0;
}

static int run_fatal_case(const otbn_error_app_t *app) {
    if (otbn_wait_for_status(OTBN_STATUS_IDLE, "IDLE") != 0) {
        return -1;
    }

    if (otbn_clear_recoverable_state() != 0) {
        return -1;
    }

    if (otbn_set_sw_errs_fatal(OTBN_CTRL_SW_ERRS_FATAL) != 0) {
        printf("ERROR: failed to set CTRL.software_errs_fatal before fatal phase\n");
        return -1;
    }

    if (otbn_load_app(app) != 0) {
        return -1;
    }

    printf("[DBG] Executing fatal-mode case %s\n", app->name);
    WRITE_REG(SEP_TOP_OTBN_INTR_ENABLE_BASE_ADDR, 1u);
    WRITE_REG(SEP_TOP_OTBN_CMD_BASE_ADDR, OTBN_CMD_EXECUTE);

    if (otbn_wait_for_status(OTBN_STATUS_LOCKED, "LOCKED") != 0) {
        return -1;
    }

    uint32_t status = READ_REG(SEP_TOP_OTBN_STATUS_BASE_ADDR);
    uint32_t err_bits = READ_REG(SEP_TOP_OTBN_ERR_BITS_BASE_ADDR);
    uint32_t fatal_alert = READ_REG(SEP_TOP_OTBN_FATAL_ALERT_CAUSE_BASE_ADDR);

    printf("[DBG] fatal %-8s status=0x%08x err_bits=0x%08x fatal_alert=0x%08x\n", app->name, status,
           err_bits, fatal_alert);

    if (status != OTBN_STATUS_LOCKED) {
        printf("ERROR: fatal-mode %s did not reach LOCKED\n", app->name);
        return -1;
    }

    if ((err_bits & app->expected_err_bits) == 0u) {
        printf("ERROR: fatal-mode %s missing base software error bit 0x%08x\n", app->name,
               app->expected_err_bits);
        return -1;
    }

    if ((err_bits & OTBN__ERR_BITS__FATAL_SOFTWARE_bm) == 0u) {
        printf("ERROR: fatal-mode %s missing FATAL_SOFTWARE bit\n", app->name);
        return -1;
    }

    if ((fatal_alert & OTBN__FATAL_ALERT_CAUSE__FATAL_SOFTWARE_bm) == 0u) {
        printf("ERROR: fatal-mode %s missing fatal_software alert cause\n", app->name);
        return -1;
    }

    return 0;
}

int main(void) {
    otbn_error_app_t recoverable_cases[5];

    sep_outbound_filter_init();
    init_recoverable_cases(recoverable_cases);

    printf("=== OTBN Software Error Handling Test ===\n");
    printf("[DBG] OTBN base: csr=0x%08x imem=0x%08x dmem=0x%08x\n", SEP_TOP_OTBN_BASE_ADDR,
           SEP_TOP_OTBN_IMEM_BASE_ADDR, SEP_TOP_OTBN_DMEM_BASE_ADDR);

    if (otbn_wait_for_status(OTBN_STATUS_IDLE, "IDLE") != 0) {
        fail_and_halt(1, "OTBN did not reach IDLE");
    }

    for (size_t i = 0; i < ARRAY_SIZE(recoverable_cases); ++i) {
        if (run_recoverable_case(&recoverable_cases[i]) != 0) {
            printf("ERROR: recoverable phase failed for %s\n", recoverable_cases[i].name);
            fail_and_halt(2 + (int)i, "Recoverable software error phase failed");
        }
    }

    if (run_fatal_case(&recoverable_cases[2]) != 0) {
        fail_and_halt(16, "Fatal software error phase failed");
    }

    printf("PASS: OTBN software error handling completed successfully\n");
    test_pass(0);

    while (1) {
        __asm__("wfi");
    }
}
