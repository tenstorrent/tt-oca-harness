/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/*
 * Drains the ROM status ring once with GetStatus 0x8001 and grades that one drain against the
 * boot mode the testbench selected for the target: every entry carries the SMC BL0 firmware ID
 * and a defined message type, the role and recovery codes match the selection, no forbidden
 * boot code appears, and the boot codes arrive in exactly the order status-coordination.adoc
 * gives. The leaf needs status reporting enabled; a set STATUS_RPT_DISABLE strap fails it.
 */

#include "occp_test_common.h"
#include "smc_defines.h"
#include "smc_test.h"
#include "smc_status.h"

#define SMC_STATUS_ROM_STARTED 0x001
#define SMC_STATUS_BOOT_START 0x010
#define SMC_STATUS_RECOVERY_MODE 0x020
#define SMC_STATUS_PRIMARY_MODE 0x021
#define SMC_STATUS_SECONDARY_MODE 0x022
#define SMC_STATUS_INVALID_SEC_MODE 0x025
#define SMC_STATUS_OCCP_INIT_FAILED 0x030
#define SMC_STATUS_OCCP_READY 0x031
#define SMC_STATUS_COORDINATION_ACTIVE 0x040
#define SMC_STATUS_BOOT_COMPLETE 0x050
#define SMC_STATUS_UNEXPECTED_EXIT 0x0FF
/* Values from 0x100 up are OCCP command reports, which follow the boot codes. */
#define SMC_STATUS_OCCP_FAMILY_BASE 0x100

/* Controller scratch 14 from the testbench; must match smc_occp_dual_defs.py. */
#define STATUS_MODE_SCRATCH 14
#define STATUS_MODE_MAGIC 0x32990000u
#define STATUS_MODE_MAGIC_MASK 0xFFFF0000u
#define STATUS_MODE_PRIMARY 0x1u
#define STATUS_MODE_RECOVERY 0x2u

/* Controller scratch 15 for the testbench: magic, boot-code count, checks, observed codes. */
#define STATUS_SUMMARY_SCRATCH 15
#define STATUS_SUMMARY_MAGIC 0xB5000000u
#define STATUS_CHECK_FORMAT 0x1u
#define STATUS_CHECK_REQUIRED_FORBIDDEN 0x2u
#define STATUS_CHECK_ORDER 0x4u
#define STATUS_SEEN_PRIMARY 0x1u
#define STATUS_SEEN_SECONDARY 0x2u
#define STATUS_SEEN_RECOVERY 0x4u

/* The ring retains 511 entries; a boot leaves fewer than 16. */
#define MAX_RECORDS 64
#define MAX_EXPECTED 8

typedef struct {
    uint32_t raw;
    uint8_t firmware_id;
    uint8_t message_type;
    uint16_t status_code;
} status_record_t;

typedef struct {
    uint16_t status_code;
    uint8_t message_type;
} expected_status_t;

static status_record_t records[MAX_RECORDS];
static uint32_t record_count;

static uint32_t read_selected_mode(void) {
    uint32_t mode = read_scratch(STATUS_MODE_SCRATCH);
    if ((mode & STATUS_MODE_MAGIC_MASK) != STATUS_MODE_MAGIC ||
        (mode & ~(STATUS_MODE_MAGIC_MASK | STATUS_MODE_PRIMARY | STATUS_MODE_RECOVERY)) != 0) {
        simputshex32("FAIL: no boot-mode selection in scratch 14: 0x", mode);
        test_fail(0);
    }
    simputshex32("Selected target mode word: 0x", mode);
    return mode;
}

/* The one drain every later check reads. */
static void drain_status_ring(test_context_t *ctx) {
    record_count = 0;
    for (;;) {
        uint32_t status = 0;
        if (occp_send_get_smc_status_command(ctx, ctx->slave_addr, &status) != OCCP_SUCCESS) {
            simputshex32("FAIL: GetStatus 0x8001 failed after entries: ", record_count);
            test_fail(0);
        }
        if (status == 0) {
            break;
        }
        if (record_count == MAX_RECORDS) {
            simputshex32("FAIL: status ring still not empty after entries: ", record_count);
            test_fail(0);
        }
        status_record_t *rec = &records[record_count++];
        rec->raw = status;
        rec->firmware_id = (uint8_t)((status >> 16) & 0xFF);
        rec->message_type = (uint8_t)((status >> 24) & 0xFF);
        rec->status_code = (uint16_t)(status & 0xFFFF);
        simputshex32("RAW status entry: 0x", status);
    }
    simputshex32("Status entries drained: ", record_count);
}

static uint32_t build_expected(uint32_t mode, expected_status_t *expected) {
    uint32_t n = 0;
    expected[n++] = (expected_status_t){SMC_STATUS_ROM_STARTED, SMC_STATUS_TYPE_STATUS};
    expected[n++] = (expected_status_t){SMC_STATUS_COORDINATION_ACTIVE, SMC_STATUS_TYPE_STATUS};
    expected[n++] = (expected_status_t){SMC_STATUS_ROM_STARTED, SMC_STATUS_TYPE_STATUS};
    expected[n++] = (expected_status_t){(mode & STATUS_MODE_PRIMARY) ? SMC_STATUS_PRIMARY_MODE
                                                                     : SMC_STATUS_SECONDARY_MODE,
                                        SMC_STATUS_TYPE_STATUS};
    if (mode & STATUS_MODE_RECOVERY) {
        expected[n++] = (expected_status_t){SMC_STATUS_RECOVERY_MODE, SMC_STATUS_TYPE_WARNING};
    }
    expected[n++] = (expected_status_t){SMC_STATUS_BOOT_START, SMC_STATUS_TYPE_STATUS};
    expected[n++] = (expected_status_t){SMC_STATUS_OCCP_READY, SMC_STATUS_TYPE_STATUS};
    expected[n++] = (expected_status_t){SMC_STATUS_BOOT_COMPLETE, SMC_STATUS_TYPE_STATUS};
    return n;
}

static bool is_boot_code(const status_record_t *rec) {
    return rec->status_code < SMC_STATUS_OCCP_FAMILY_BASE;
}

static uint32_t count_code(uint16_t code) {
    uint32_t n = 0;
    for (uint32_t i = 0; i < record_count; i++) {
        if (records[i].status_code == code) {
            n++;
        }
    }
    return n;
}

static bool check_format(void) {
    bool ok = true;
    for (uint32_t i = 0; i < record_count; i++) {
        const status_record_t *rec = &records[i];
        bool type_ok = rec->message_type == SMC_STATUS_TYPE_STATUS ||
                       rec->message_type == SMC_STATUS_TYPE_WARNING ||
                       rec->message_type == SMC_STATUS_TYPE_ERROR;
        if (rec->firmware_id != SMC_STATUS_FW_ID_SMC_BL0 || !type_ok) {
            simputshex32("FAIL: entry with a wrong firmware ID or message type: 0x", rec->raw);
            ok = false;
        }
    }
    return ok;
}

static bool check_required_forbidden(uint32_t mode) {
    bool primary = (mode & STATUS_MODE_PRIMARY) != 0;
    bool recovery = (mode & STATUS_MODE_RECOVERY) != 0;
    struct {
        uint16_t code;
        uint32_t count;
    } want[] = {
        {SMC_STATUS_ROM_STARTED, 2},
        {SMC_STATUS_COORDINATION_ACTIVE, 1},
        {SMC_STATUS_PRIMARY_MODE, primary ? 1 : 0},
        {SMC_STATUS_SECONDARY_MODE, primary ? 0 : 1},
        {SMC_STATUS_RECOVERY_MODE, recovery ? 1 : 0},
        {SMC_STATUS_BOOT_START, 1},
        {SMC_STATUS_OCCP_READY, 1},
        {SMC_STATUS_BOOT_COMPLETE, 1},
        {SMC_STATUS_INVALID_SEC_MODE, 0},
        {SMC_STATUS_OCCP_INIT_FAILED, 0},
        {SMC_STATUS_UNEXPECTED_EXIT, 0},
    };
    bool ok = true;
    for (uint32_t i = 0; i < sizeof(want) / sizeof(want[0]); i++) {
        uint32_t seen = count_code(want[i].code);
        if (seen != want[i].count) {
            simputshex32("FAIL: status code 0x", want[i].code);
            simputshex32("  expected occurrences: ", want[i].count);
            simputshex32("  observed occurrences: ", seen);
            ok = false;
        }
    }
    return ok;
}

/* Boot codes in drain order must be exactly the expected list; command reports follow them. */
static bool check_order(const expected_status_t *expected, uint32_t n_expected) {
    uint32_t next = 0;
    bool ok = true;
    for (uint32_t i = 0; i < record_count; i++) {
        const status_record_t *rec = &records[i];
        if (!is_boot_code(rec)) {
            if (next != n_expected) {
                simputshex32("FAIL: command report before BOOT_COMPLETE: 0x", rec->raw);
                ok = false;
            }
            continue;
        }
        if (next == n_expected || rec->status_code != expected[next].status_code ||
            rec->message_type != expected[next].message_type) {
            simputshex32("FAIL: boot entry out of order: 0x", rec->raw);
            simputshex32("  at expected position: ", next);
            ok = false;
            continue;
        }
        next++;
    }
    if (next != n_expected) {
        simputshex32("FAIL: boot sequence ended early at position: ", next);
        ok = false;
    }
    return ok;
}

static uint32_t observed_mode_codes(void) {
    uint32_t seen = 0;
    if (count_code(SMC_STATUS_PRIMARY_MODE)) seen |= STATUS_SEEN_PRIMARY;
    if (count_code(SMC_STATUS_SECONDARY_MODE)) seen |= STATUS_SEEN_SECONDARY;
    if (count_code(SMC_STATUS_RECOVERY_MODE)) seen |= STATUS_SEEN_RECOVERY;
    return seen;
}

static uint32_t count_boot_codes(void) {
    uint32_t n = 0;
    for (uint32_t i = 0; i < record_count; i++) {
        if (is_boot_code(&records[i])) {
            n++;
        }
    }
    return n;
}

static __attribute__((noreturn)) void report_result(test_context_t *ctx, bool passed) {
    uint32_t result_code = passed ? SMC_SCRATCHPAD_SIM_PASS_CODE : SMC_SCRATCHPAD_SIM_FAIL_CODE;
    occp_send_write_command(ctx, ctx->slave_addr, SMC_CPU_CTRL_SCRATCH_0__REG_ADDR,
                            (uint8_t *)&result_code, sizeof(result_code));
    if (passed) {
        simputs("BOOT SEQUENCE STATUS TEST: PASS\n");
        test_pass(0);
    }
    simputs("BOOT SEQUENCE STATUS TEST: FAIL\n");
    test_fail(0);
}

int main(void) {
    static test_context_t ctx = {0};
    expected_status_t expected[MAX_EXPECTED];

    init_test(0);
    simputs("=== OCCP Boot Sequence Status Test ===\n");
    uint32_t mode = read_selected_mode();

    if (!initialize_interface(&ctx)) {
        simputs("FAIL: Interface initialization failed\n");
        test_fail(0);
    }
    if (ctx.status_reporting_disabled) {
        simputs("FAIL: STATUS_RPT_DISABLE is set; this leaf grades the status ring\n");
        test_fail(0);
    }
    ctx.test_base_addr = OCCP_TEST_BASE_ADDR;
    ctx.test_upper_addr_bound = OCCP_TEST_UPPER_ADDR;
    ctx.overall_result = true;

    drain_status_ring(&ctx);
    uint32_t n_expected = build_expected(mode, expected);

    uint32_t checks = 0;
    if (check_format()) checks |= STATUS_CHECK_FORMAT;
    if (check_required_forbidden(mode)) checks |= STATUS_CHECK_REQUIRED_FORBIDDEN;
    if (check_order(expected, n_expected)) checks |= STATUS_CHECK_ORDER;

    write_scratch(STATUS_SUMMARY_SCRATCH, STATUS_SUMMARY_MAGIC | (count_boot_codes() << 16) |
                                              (checks << 8) | observed_mode_codes());

    /* The composite status IDs still answer after the drain. */
    for (int i = 0; i < 10; i++) {
        uint32_t status = 0;
        if (occp_send_get_status_command(&ctx, ctx.slave_addr, &status) != OCCP_SUCCESS) {
            simputshex32("FAIL: GET_STATUS failed at iteration: ", i);
            report_result(&ctx, false);
        }
    }

    report_result(&ctx, checks == (STATUS_CHECK_FORMAT | STATUS_CHECK_REQUIRED_FORBIDDEN |
                                   STATUS_CHECK_ORDER));
}

int other_main(int hartid) {
    (void)hartid;
    while (1) {
        __asm__("wfi");
    }
}

int secondary_main(void) {
    int hartid = metal_cpu_get_current_hartid();
    if (hartid == 0) {
        return main();
    } else {
        return other_main(hartid);
    }
}
