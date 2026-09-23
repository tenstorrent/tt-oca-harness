/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/*
 * Drives each OCCP error the ROM rejects, checks the exact response code and the matching
 * SMC status ring record, and pairs every deny phase with a legal WRITE/READ round trip.
 * Oversize WRITE and READ count overflow are untested: the 11-bit length cannot encode them.
 */

#include "occp_test_common.h"
#include "smc_defines.h"
#include "smc_test.h"
#include <string.h>
#include "smc_status.h"

#define ROM_PROTECTED_BASE SMC_SRAM_BASE_ADDR
#define ROM_PROTECTED_END OCCP_TEST_BASE_ADDR

/* Must stay 8-byte aligned and below OCCP_TEST_BUFFER_SAFE_UPPER_ADDR. */
#define CONTROL_ADDR (OCCP_TEST_BASE_ADDR + 0x1000ULL)
#define ROUNDTRIP_ADDR (OCCP_TEST_BASE_ADDR + 0x2000ULL)
#define BULK_ADDR (OCCP_TEST_BASE_ADDR + 0x4000ULL)

/* Past the secure-mode SRAM limit, far from UINT64_MAX: only the secure-mode bound denies it. */
#define ABOVE_SRAM_ADDR 0xC0200000ULL

/* Reaching this bound without an empty read is a failure, not a normal exit. */
#define MAX_STATUS_BUFFER_READS 200

/* Shared buffers, kept static so the max-size cases do not sit on the stack. */
static uint8_t g_write_buf[MAX_OCCP_WRITE_SIZE];
static uint8_t g_read_buf[MAX_OCCP_READ_SIZE];

typedef struct {
    test_context_t *occp_ctx;
    int total_tests;
    int passed_tests;
    bool overall_result;

    int violations_triggered;
    int positive_controls_ok;
    int status_entries_processed;
    int errors_found;

    int exp_write_denied;
    int exp_read_denied;
    int exp_write_overflow;
    int exp_read_overflow;
    int exp_jump_failed;
    int exp_jump_security;
    int exp_validate_failed;
    int exp_cmd_unknown;
} comprehensive_error_test_context_t;

static void init_test_context(comprehensive_error_test_context_t *ctx, test_context_t *occp_ctx) {
    memset(ctx, 0, sizeof(*ctx));
    ctx->occp_ctx = occp_ctx;
    ctx->overall_result = true;
}

static void mark_test_result(comprehensive_error_test_context_t *ctx, bool passed,
                             const char *test_name) {
    ctx->total_tests++;
    if (passed) {
        ctx->passed_tests++;
        simputs("PASS: ");
    } else {
        simputs("FAIL: ");
        ctx->overall_result = false;
    }
    simputs(test_name);
    simputs("\n");
}

static bool relatch(comprehensive_error_test_context_t *ctx) {
    uint32_t version = 0;
    /* A valid command clears the ROM's consecutive-error count; five errors unlatch it. */
    int rc = occp_send_get_version_command(ctx->occp_ctx, ctx->occp_ctx->slave_addr, &version);
    increment_cmd_count(ctx->occp_ctx);
    if (rc != OCCP_SUCCESS) {
        simputs("FAIL: interface did not recover (GET_VERSION failed after error injection)\n");
        return false;
    }
    return true;
}

static bool positive_control(comprehensive_error_test_context_t *ctx, uint8_t tag) {
    test_context_t *c = ctx->occp_ctx;
    uint8_t pattern[8];
    uint8_t readback[8];

    for (int i = 0; i < 8; i++) {
        pattern[i] = (uint8_t)(tag + i);
    }
    memset(readback, 0, sizeof(readback));

    int rc = occp_send_write_command(c, c->slave_addr, CONTROL_ADDR, pattern, sizeof(pattern));
    increment_cmd_count(c);
    if (rc != OCCP_SUCCESS) {
        simputs("FAIL: positive control WRITE to a permitted address did not succeed\n");
        return false;
    }

    rc = occp_send_read_command(c, c->slave_addr, CONTROL_ADDR, readback, sizeof(readback));
    increment_cmd_count(c);
    if (rc != OCCP_SUCCESS) {
        simputs("FAIL: positive control READ from a permitted address did not succeed\n");
        return false;
    }
    if (memcmp(pattern, readback, sizeof(pattern)) != 0) {
        simputs("FAIL: positive control read back different bytes than were written\n");
        return false;
    }

    ctx->positive_controls_ok++;
    simputs("positive control: legal WRITE/READ round trip verified\n");
    return true;
}

/* With exp_response_code armed, OCCP_SUCCESS means the ROM refused with exactly that code. */
static bool expect_write_error(comprehensive_error_test_context_t *ctx, uint64_t addr,
                               const uint8_t *data, uint16_t len, occp_error_code_t exp,
                               const char *what) {
    test_context_t *c = ctx->occp_ctx;
    simputs("expecting refusal: ");
    simputs(what);
    simputshex64(" at 0x", addr);

    c->exp_response_code = exp;
    int rc = occp_send_write_command(c, c->slave_addr, addr, data, len);
    increment_cmd_count(c);
    c->exp_response_code = OCCP_ERROR_NONE;

    if (rc != OCCP_SUCCESS) {
        simputs("FAIL: WRITE did not answer with the specified OCCP error: ");
        simputs(what);
        simputs("\n");
        return false;
    }
    ctx->violations_triggered++;
    return true;
}

static bool expect_read_error(comprehensive_error_test_context_t *ctx, uint64_t addr, uint16_t len,
                              occp_error_code_t exp, const char *what) {
    test_context_t *c = ctx->occp_ctx;
    simputs("expecting refusal: ");
    simputs(what);
    simputshex64(" at 0x", addr);

    c->exp_response_code = exp;
    int rc = occp_send_read_command(c, c->slave_addr, addr, g_read_buf, len);
    increment_cmd_count(c);
    c->exp_response_code = OCCP_ERROR_NONE;

    if (rc != OCCP_SUCCESS) {
        simputs("FAIL: READ did not answer with the specified OCCP error: ");
        simputs(what);
        simputs("\n");
        return false;
    }
    ctx->violations_triggered++;
    return true;
}

static bool expect_jump_error(comprehensive_error_test_context_t *ctx, uint64_t addr,
                              occp_error_code_t exp, const char *what) {
    test_context_t *c = ctx->occp_ctx;
    simputs("expecting refusal: ");
    simputs(what);
    simputshex64(" at 0x", addr);

    c->exp_response_code = exp;
    int rc = occp_send_jump_command(c, c->slave_addr, addr);
    increment_cmd_count(c);
    c->exp_response_code = OCCP_ERROR_NONE;

    if (rc != OCCP_SUCCESS) {
        simputs("FAIL: JUMP did not answer with the specified OCCP error: ");
        simputs(what);
        simputs("\n");
        return false;
    }
    ctx->violations_triggered++;
    return true;
}

static bool expect_validate_boot_error(comprehensive_error_test_context_t *ctx, uint64_t addr,
                                       occp_error_code_t exp, const char *what) {
    test_context_t *c = ctx->occp_ctx;
    simputs("expecting refusal: ");
    simputs(what);
    simputshex64(" at 0x", addr);

    c->exp_response_code = exp;
    int rc = occp_send_validate_boot_command(c, c->slave_addr, addr);
    increment_cmd_count(c);
    c->exp_response_code = OCCP_ERROR_NONE;

    if (rc != OCCP_SUCCESS) {
        simputs("FAIL: VALIDATE_AND_BOOT did not answer with the specified OCCP error: ");
        simputs(what);
        simputs("\n");
        return false;
    }
    ctx->violations_triggered++;
    return true;
}

static bool test_memory_access_violations(comprehensive_error_test_context_t *ctx) {
    simputs("\n=== Test 1: READ/WRITE Access Denied ===\n");
    simputs("SPEC: ROM-owned SRAM is refused to OCCP READ and WRITE in both security modes\n");

    bool test_passed = true;
    uint8_t test_data[8] = {0xDE, 0xAD, 0xBE, 0xEF, 0x12, 0x34, 0x56, 0x78};

    const uint64_t denied_addrs[] = {
        ROM_PROTECTED_BASE,
        ROM_PROTECTED_BASE + 0x1000,
        ROM_PROTECTED_END - 8,
    };

    for (int i = 0; i < (int)(sizeof(denied_addrs) / sizeof(denied_addrs[0])); i++) {
        if (!expect_write_error(ctx, denied_addrs[i], test_data, sizeof(test_data),
                                OCCP_INVALID_ADDRESS, "ROM-owned WRITE")) {
            test_passed = false;
        } else {
            ctx->exp_write_denied++;
        }

        if (!expect_read_error(ctx, denied_addrs[i], sizeof(test_data), OCCP_INVALID_ADDRESS,
                               "ROM-owned READ")) {
            test_passed = false;
        } else {
            ctx->exp_read_denied++;
        }
    }

    if (is_secure_mode()) {
        if (!expect_write_error(ctx, ABOVE_SRAM_ADDR, test_data, sizeof(test_data),
                                OCCP_INVALID_ADDRESS, "above-SRAM WRITE (secure mode)")) {
            test_passed = false;
        } else {
            ctx->exp_write_denied++;
        }
        if (!expect_read_error(ctx, ABOVE_SRAM_ADDR, sizeof(test_data), OCCP_INVALID_ADDRESS,
                               "above-SRAM READ (secure mode)")) {
            test_passed = false;
        } else {
            ctx->exp_read_denied++;
        }
    } else {
        simputs("unsecure mode: no upper access bound in the ROM, above-SRAM case not asserted\n");
    }

    if (!relatch(ctx)) test_passed = false;
    if (!positive_control(ctx, 0x10)) test_passed = false;

    mark_test_result(ctx, test_passed, "READ/WRITE Access Denied");
    return test_passed;
}

static bool test_zero_length_rejection(comprehensive_error_test_context_t *ctx) {
    simputs("\n=== Test 2: Zero-Length Command Rejection ===\n");
    simputs("SPEC: zero write_size/read_length -> WRITE_OVERFLOW / READ_OVERFLOW,\n");
    simputs("      answered with Invalid_header\n");

    bool test_passed = true;
    uint8_t dummy = 0;

    if (!expect_write_error(ctx, ROUNDTRIP_ADDR, &dummy, 0, OCCP_INVALID_HEADER,
                            "zero-length WRITE")) {
        test_passed = false;
    } else {
        ctx->exp_write_overflow++;
    }

    if (!expect_read_error(ctx, ROUNDTRIP_ADDR, 0, OCCP_INVALID_HEADER, "zero-length READ")) {
        test_passed = false;
    } else {
        ctx->exp_read_overflow++;
    }

    if (!relatch(ctx)) test_passed = false;
    if (!positive_control(ctx, 0x20)) test_passed = false;

    mark_test_result(ctx, test_passed, "Zero-Length Command Rejection");
    return test_passed;
}

/* Never JUMP to a permitted address: the ROM takes the branch and never returns to OCCP. */
static bool test_jump_security_violations(comprehensive_error_test_context_t *ctx) {
    simputs("\n=== Test 3: JUMP Security Enforcement ===\n");

    bool test_passed = true;

    if (is_secure_mode()) {
        simputs("SPEC: secure mode refuses JUMP outright -> JUMP_SECURITY, Invalid_Msgid\n");
        if (!expect_jump_error(ctx, ROM_PROTECTED_BASE, OCCP_INVALID_MSGID,
                               "JUMP refused in secure mode")) {
            test_passed = false;
        } else {
            ctx->exp_jump_security++;
        }
    } else {
        simputs("SPEC: unsecure mode refuses NULL/misaligned/denied JUMP -> JUMP_READ_FAILED\n");
        const uint64_t denied_jumps[] = {
            0x0ULL,
            0xFFFFFFFFFFFFFFFFULL,
            ROM_PROTECTED_BASE,
            ROM_PROTECTED_END - 4,
        };
        for (int i = 0; i < (int)(sizeof(denied_jumps) / sizeof(denied_jumps[0])); i++) {
            if (!expect_jump_error(ctx, denied_jumps[i], OCCP_INVALID_ADDRESS, "JUMP refused")) {
                test_passed = false;
            } else {
                ctx->exp_jump_failed++;
            }
        }
    }

    if (!relatch(ctx)) test_passed = false;
    if (!positive_control(ctx, 0x30)) test_passed = false;

    mark_test_result(ctx, test_passed, "JUMP Security Enforcement");
    return test_passed;
}

/* Do not call through ctx->drv.i2c_drv here: it is a union holding an I3C_Driver on I3C. */
static bool test_invalid_command_injection(comprehensive_error_test_context_t *ctx) {
    simputs("\n=== Test 4: Invalid Command Injection ===\n");
    simputs("SPEC: unknown AppID/MsgID -> Invalid_AppID/Invalid_MsgID response, CMD_UNKNOWN\n");

    bool test_passed = true;
    test_context_t *c = ctx->occp_ctx;

    const occp_invalid_header_inject_mode_t modes[] = {
        OCCP_INVALID_HDR_INVALID_MSGID,
        OCCP_INVALID_HDR_INVALID_APPID,
        OCCP_INVALID_HDR_INVALID_BOTH,
    };

    for (int i = 0; i < (int)(sizeof(modes) / sizeof(modes[0])); i++) {
        c->invalid_header_inject_mode = modes[i];
        /* The helper arms exp_response_code from the mode but clears it only on success. */
        int rc = occp_send_invalid_header_command(c, c->slave_addr);
        increment_cmd_count(c);
        c->invalid_header_inject_mode = OCCP_INVALID_HDR_INJECT_NONE;
        c->exp_response_code = OCCP_ERROR_NONE;

        if (rc != OCCP_SUCCESS) {
            simputs("FAIL: invalid header was not refused with the specified error code\n");
            test_passed = false;
        } else {
            ctx->violations_triggered++;
            ctx->exp_cmd_unknown++;
        }

        if (!relatch(ctx)) test_passed = false;
    }

    if (!positive_control(ctx, 0x40)) test_passed = false;

    mark_test_result(ctx, test_passed, "Invalid Command Injection");
    return test_passed;
}

static bool test_transfer_size_boundaries(comprehensive_error_test_context_t *ctx) {
    simputs("\n=== Test 5: Transfer Size Boundaries ===\n");
    simputs("SPEC: transfers at the maximum size succeed; oversize bodies -> Oversize_msg\n");

    bool test_passed = true;
    test_context_t *c = ctx->occp_ctx;

    for (int i = 0; i < MAX_OCCP_WRITE_SIZE; i++) {
        g_write_buf[i] = (uint8_t)(i & 0xFF);
    }
    memset(g_read_buf, 0, sizeof(g_read_buf));

    int rc = occp_send_write_command(c, c->slave_addr, BULK_ADDR, g_write_buf,
                                     (uint16_t)MAX_OCCP_WRITE_SIZE);
    increment_cmd_count(c);
    if (rc != OCCP_SUCCESS) {
        simputs("FAIL: WRITE at MAX_OCCP_WRITE_SIZE was refused; the size is legal\n");
        test_passed = false;
    } else {
        rc = occp_send_read_command(c, c->slave_addr, BULK_ADDR, g_read_buf,
                                    (uint16_t)MAX_OCCP_WRITE_SIZE);
        increment_cmd_count(c);
        if (rc != OCCP_SUCCESS) {
            simputs("FAIL: READ back of the maximum-size WRITE was refused\n");
            test_passed = false;
        } else if (memcmp(g_write_buf, g_read_buf, MAX_OCCP_WRITE_SIZE) != 0) {
            simputs("FAIL: maximum-size WRITE did not read back the bytes written\n");
            test_passed = false;
        } else {
            simputs("maximum-size WRITE/READ round trip verified\n");
            ctx->positive_controls_ok++;
        }
    }

    memset(g_read_buf, 0, sizeof(g_read_buf));
    rc = occp_send_read_command(c, c->slave_addr, BULK_ADDR, g_read_buf,
                                (uint16_t)MAX_OCCP_READ_SIZE);
    increment_cmd_count(c);
    if (rc != OCCP_SUCCESS) {
        simputs("FAIL: READ at MAX_OCCP_READ_SIZE was refused; the size is legal\n");
        test_passed = false;
    } else {
        simputs("maximum-size READ accepted\n");
        ctx->positive_controls_ok++;
    }

    c->inject_oversize_body_err = true;
    c->exp_response_code = OCCP_OVERSIZE_MSG;
    rc = occp_send_write_command(c, c->slave_addr, ROUNDTRIP_ADDR, g_write_buf, 8);
    increment_cmd_count(c);
    c->inject_oversize_body_err = false;
    c->exp_response_code = OCCP_ERROR_NONE;
    if (rc != OCCP_SUCCESS) {
        simputs("FAIL: oversize body was not refused with Oversize_msg\n");
        test_passed = false;
    } else {
        ctx->violations_triggered++;
    }

    if (!relatch(ctx)) test_passed = false;
    if (!positive_control(ctx, 0x50)) test_passed = false;

    mark_test_result(ctx, test_passed, "Transfer Size Boundaries");
    return test_passed;
}

/* Never VALIDATE_AND_BOOT a permitted address: the ROM parks in wfi and the run ends. */
static bool test_validate_boot_security(comprehensive_error_test_context_t *ctx) {
    simputs("\n=== Test 6: VALIDATE_AND_BOOT Security ===\n");
    simputs("SPEC: NULL/misaligned/denied manifest address -> VALIDATE_ADDRESS_FAILED\n");

    bool test_passed = true;

    const uint64_t denied_manifests[] = {
        0x0ULL,
        0xFFFFFFFFFFFFFFFFULL,
        ROM_PROTECTED_BASE,
    };

    for (int i = 0; i < (int)(sizeof(denied_manifests) / sizeof(denied_manifests[0])); i++) {
        if (!expect_validate_boot_error(ctx, denied_manifests[i], OCCP_INVALID_ADDRESS,
                                        "VALIDATE_AND_BOOT refused")) {
            test_passed = false;
        } else {
            ctx->exp_validate_failed++;
        }
    }

    if (!relatch(ctx)) test_passed = false;
    if (!positive_control(ctx, 0x60)) test_passed = false;

    mark_test_result(ctx, test_passed, "VALIDATE_AND_BOOT Security");
    return test_passed;
}

static bool test_address_wraparound(comprehensive_error_test_context_t *ctx) {
    simputs("\n=== Test 7: Address Arithmetic Overflow ===\n");
    simputs("SPEC: addr + size overflow and misaligned addresses -> WRITE_ACCESS_DENIED\n");

    bool test_passed = true;
    uint8_t test_data[16] = {0};

    const uint64_t overflow_addrs[] = {
        0xFFFFFFFFFFFFFFF0ULL,
        0xFFFFFFFFFFFFFFF8ULL,
        0xFFFFFFFFFFFFFFFCULL,
    };
    for (int i = 0; i < (int)(sizeof(overflow_addrs) / sizeof(overflow_addrs[0])); i++) {
        if (!expect_write_error(ctx, overflow_addrs[i], test_data, sizeof(test_data),
                                OCCP_INVALID_ADDRESS, "address arithmetic overflow WRITE")) {
            test_passed = false;
        } else {
            ctx->exp_write_denied++;
        }
    }

    if (!expect_write_error(ctx, 0xFFFFFFFFFFFFFFFEULL, test_data, sizeof(test_data),
                            OCCP_INVALID_ADDRESS, "misaligned WRITE")) {
        test_passed = false;
    } else {
        ctx->exp_write_denied++;
    }

    if (!expect_write_error(ctx, ROUNDTRIP_ADDR + 1, test_data, 4, OCCP_INVALID_ADDRESS,
                            "misaligned WRITE inside the permitted range")) {
        test_passed = false;
    } else {
        ctx->exp_write_denied++;
    }

    if (is_secure_mode()) {
        if (!expect_write_error(ctx, 0x8000000000000000ULL, test_data, sizeof(test_data),
                                OCCP_INVALID_ADDRESS, "sign-bit address WRITE (secure mode)")) {
            test_passed = false;
        } else {
            ctx->exp_write_denied++;
        }
    } else {
        simputs("unsecure mode: 0x8000000000000000 is not a denied address in the ROM, skipped\n");
    }

    if (!relatch(ctx)) test_passed = false;
    if (!positive_control(ctx, 0x70)) test_passed = false;

    mark_test_result(ctx, test_passed, "Address Arithmetic Overflow");
    return test_passed;
}

static bool test_permitted_range_boundary(comprehensive_error_test_context_t *ctx) {
    simputs("\n=== Test 8: Permitted Range Boundary ===\n");
    simputs("SPEC: a transfer straddling the ROM boundary is refused;\n");
    simputs("      the first legal word is served\n");

    bool test_passed = true;
    test_context_t *c = ctx->occp_ctx;
    uint8_t pattern[8] = {0xA0, 0xA1, 0xA2, 0xA3, 0xA4, 0xA5, 0xA6, 0xA7};
    uint8_t readback[8];

    if (!expect_write_error(ctx, ROM_PROTECTED_END - 4, pattern, sizeof(pattern),
                            OCCP_INVALID_ADDRESS, "WRITE straddling the ROM boundary")) {
        test_passed = false;
    } else {
        ctx->exp_write_denied++;
    }
    if (!expect_read_error(ctx, ROM_PROTECTED_END - 4, sizeof(pattern), OCCP_INVALID_ADDRESS,
                           "READ straddling the ROM boundary")) {
        test_passed = false;
    } else {
        ctx->exp_read_denied++;
    }

    if (!relatch(ctx)) test_passed = false;

    memset(readback, 0, sizeof(readback));
    int rc =
        occp_send_write_command(c, c->slave_addr, OCCP_TEST_BASE_ADDR, pattern, sizeof(pattern));
    increment_cmd_count(c);
    if (rc != OCCP_SUCCESS) {
        simputs("FAIL: WRITE at the first permitted address was refused\n");
        test_passed = false;
    } else {
        rc = occp_send_read_command(c, c->slave_addr, OCCP_TEST_BASE_ADDR, readback,
                                    sizeof(readback));
        increment_cmd_count(c);
        if (rc != OCCP_SUCCESS) {
            simputs("FAIL: READ at the first permitted address was refused\n");
            test_passed = false;
        } else if (memcmp(pattern, readback, sizeof(pattern)) != 0) {
            simputs("FAIL: first permitted address did not read back the bytes written\n");
            test_passed = false;
        } else {
            ctx->positive_controls_ok++;
        }
    }

    if (!positive_control(ctx, 0x80)) test_passed = false;

    mark_test_result(ctx, test_passed, "Permitted Range Boundary");
    return test_passed;
}

static bool test_byte_order_preservation(comprehensive_error_test_context_t *ctx) {
    simputs("\n=== Test 9: Byte Order Preservation ===\n");
    simputs("SPEC: 1/4/8-byte WRITE then READ returns the bytes in the order written\n");

    bool test_passed = true;
    test_context_t *c = ctx->occp_ctx;
    const uint8_t pattern[8] = {0x12, 0x34, 0x56, 0x78, 0x9A, 0xBC, 0xDE, 0xF0};
    const uint16_t widths[] = {8, 4, 1};
    uint8_t readback[8];

    for (int w = 0; w < (int)(sizeof(widths) / sizeof(widths[0])); w++) {
        uint16_t len = widths[w];
        memset(readback, 0, sizeof(readback));

        int rc = occp_send_write_command(c, c->slave_addr, ROUNDTRIP_ADDR, pattern, len);
        increment_cmd_count(c);
        if (rc != OCCP_SUCCESS) {
            simputshex16("FAIL: legal WRITE refused at width ", len);
            test_passed = false;
            continue;
        }

        rc = occp_send_read_command(c, c->slave_addr, ROUNDTRIP_ADDR, readback, len);
        increment_cmd_count(c);
        if (rc != OCCP_SUCCESS) {
            simputshex16("FAIL: legal READ refused at width ", len);
            test_passed = false;
            continue;
        }

        if (memcmp(pattern, readback, len) != 0) {
            simputshex16("FAIL: byte order not preserved at width ", len);
            test_passed = false;
        } else {
            ctx->positive_controls_ok++;
        }
    }

    mark_test_result(ctx, test_passed, "Byte Order Preservation");
    return test_passed;
}

static bool test_back_to_back_commands(comprehensive_error_test_context_t *ctx) {
    simputs("\n=== Test 10: Back-to-Back Command Sequence ===\n");
    simputs("SPEC: consecutive WRITEs with no gap are all accepted and all land\n");

    bool test_passed = true;
    test_context_t *c = ctx->occp_ctx;
    const int kBursts = 5;
    uint8_t word[4];
    uint8_t readback[4];

    for (int i = 0; i < kBursts; i++) {
        uint64_t addr = ROUNDTRIP_ADDR + (uint64_t)i * 8;
        word[0] = (uint8_t)(0xC0 + i);
        word[1] = (uint8_t)(0xD0 + i);
        word[2] = (uint8_t)(0xE0 + i);
        word[3] = (uint8_t)(0xF0 + i);

        int rc = occp_send_write_command(c, c->slave_addr, addr, word, sizeof(word));
        increment_cmd_count(c);
        if (rc != OCCP_SUCCESS) {
            simputshex32("FAIL: back-to-back WRITE refused at index ", i);
            test_passed = false;
        }
    }

    for (int i = 0; i < kBursts; i++) {
        uint64_t addr = ROUNDTRIP_ADDR + (uint64_t)i * 8;
        word[0] = (uint8_t)(0xC0 + i);
        word[1] = (uint8_t)(0xD0 + i);
        word[2] = (uint8_t)(0xE0 + i);
        word[3] = (uint8_t)(0xF0 + i);
        memset(readback, 0, sizeof(readback));

        int rc = occp_send_read_command(c, c->slave_addr, addr, readback, sizeof(readback));
        increment_cmd_count(c);
        if (rc != OCCP_SUCCESS) {
            simputshex32("FAIL: read back of a back-to-back WRITE refused at index ", i);
            test_passed = false;
        } else if (memcmp(word, readback, sizeof(word)) != 0) {
            simputshex32("FAIL: back-to-back WRITE did not land at index ", i);
            test_passed = false;
        } else {
            ctx->positive_controls_ok++;
        }
    }

    mark_test_result(ctx, test_passed, "Back-to-Back Command Sequence");
    return test_passed;
}

/* Counts are minimums: the ROM logs extra CMD_FAILED records alongside most errors. */
static bool verify_error_reporting(comprehensive_error_test_context_t *ctx) {
    simputs("\n=== Test 11: Error Reporting Verification ===\n");
    simputs("SPEC: every injected violation leaves its SPEC error code in the SMC status ring\n");

    test_context_t *c = ctx->occp_ctx;
    bool test_passed = true;

    if (c->status_reporting_disabled) {
        simputs("STATUS_RPT_DISABLE strap active; skipping SMC status ring validation\n");
        mark_test_result(ctx, test_passed, "Error Reporting Verification (strap-disabled)");
        return test_passed;
    }

    int n_write_denied = 0;
    int n_read_denied = 0;
    int n_write_overflow = 0;
    int n_read_overflow = 0;
    int n_jump_failed = 0;
    int n_jump_security = 0;
    int n_validate_failed = 0;
    int n_cmd_unknown = 0;
    int n_cmd_failed = 0;
    int n_cmd_read = 0;
    int n_unexpected = 0;
    int n_entries = 0;
    bool drained = false;

    for (int i = 0; i < MAX_STATUS_BUFFER_READS; i++) {
        uint32_t status = 0;
        int rc = occp_send_get_smc_status_command(c, c->slave_addr, &status);
        increment_cmd_count(c);
        if (rc != OCCP_SUCCESS) {
            simputs("FAIL: GET_SMC_STATUS failed while draining the status ring\n");
            test_passed = false;
            break;
        }
        if (status == 0) {
            drained = true;
            break;
        }

        n_entries++;
        simputshex32("SMC status entry: 0x", status);

        if (!occp_is_smc_error_code(status)) {
            continue;
        }
        ctx->status_entries_processed++;

        if (occp_status_matches_expected(status, OCCP_FW_ID_SMC_BL0, OCCP_STATUS_MSG_ERROR,
                                         (uint16_t)OCCP_SPEC_ERROR_WRITE_OVERFLOW, false)) {
            n_write_overflow++;
        } else if (occp_status_matches_expected(status, OCCP_FW_ID_SMC_BL0, OCCP_STATUS_MSG_ERROR,
                                                (uint16_t)OCCP_SPEC_ERROR_READ_OVERFLOW, false)) {
            n_read_overflow++;
        } else if (occp_status_matches_expected(status, OCCP_FW_ID_SMC_BL0, OCCP_STATUS_MSG_ERROR,
                                                (uint16_t)OCCP_SPEC_ERROR_WRITE_ACCESS_DENIED,
                                                false)) {
            n_write_denied++;
        } else if (occp_status_matches_expected(status, OCCP_FW_ID_SMC_BL0, OCCP_STATUS_MSG_ERROR,
                                                (uint16_t)OCCP_SPEC_ERROR_READ_ACCESS_DENIED,
                                                false)) {
            n_read_denied++;
        } else if (occp_status_matches_expected(status, OCCP_FW_ID_SMC_BL0, OCCP_STATUS_MSG_ERROR,
                                                (uint16_t)OCCP_SPEC_ERROR_JUMP_READ_FAILED,
                                                false)) {
            n_jump_failed++;
        } else if (occp_status_matches_expected(status, OCCP_FW_ID_SMC_BL0, OCCP_STATUS_MSG_ERROR,
                                                (uint16_t)OCCP_SPEC_ERROR_JUMP_SECURITY, false)) {
            n_jump_security++;
        } else if (occp_status_matches_expected(status, OCCP_FW_ID_SMC_BL0, OCCP_STATUS_MSG_ERROR,
                                                (uint16_t)OCCP_SPEC_ERROR_VALIDATE_ADDRESS_FAILED,
                                                false)) {
            n_validate_failed++;
        } else if (occp_status_matches_expected(status, OCCP_FW_ID_SMC_BL0, OCCP_STATUS_MSG_ERROR,
                                                (uint16_t)OCCP_SPEC_ERROR_CMD_FAILED, false)) {
            /* Must precede the CMD_UNKNOWN match: its 0xF01 mask also matches CMD_FAILED. */
            n_cmd_failed++;
        } else if (occp_status_matches_expected(status, OCCP_FW_ID_SMC_BL0, OCCP_STATUS_MSG_ERROR,
                                                (uint16_t)OCCP_SPEC_ERROR_CMD_UNKNOWN, false)) {
            n_cmd_unknown++;
        } else if (OCCP_STATUS_EXTRACT_VALUE(status) == (uint16_t)OCCP_SPEC_ERROR_CMD_READ) {
            /* Test 5's oversize body leaves trailing bytes that the ROM reads as a bad command. */
            n_cmd_read++;
        } else {
            simputshex32("FAIL: unexpected SMC BL0 error record: 0x", status);
            n_unexpected++;
        }
    }

    ctx->errors_found = n_write_denied + n_read_denied + n_write_overflow + n_read_overflow +
                        n_jump_failed + n_jump_security + n_validate_failed + n_cmd_unknown;

    simputs("\n**ERROR REPORTING RESULTS**:\n");
    simputshex32("Status entries read:        ", n_entries);
    simputshex32("WRITE access denied:        ", n_write_denied);
    simputshex32("READ access denied:         ", n_read_denied);
    simputshex32("WRITE overflow:             ", n_write_overflow);
    simputshex32("READ overflow:              ", n_read_overflow);
    simputshex32("JUMP read failed:           ", n_jump_failed);
    simputshex32("JUMP security:              ", n_jump_security);
    simputshex32("VALIDATE address failed:    ", n_validate_failed);
    simputshex32("CMD unknown:                ", n_cmd_unknown);
    simputshex32("CMD failed (not scored):    ", n_cmd_failed);
    simputshex32("CMD read (not scored):      ", n_cmd_read);
    simputshex32("Unexpected error records:   ", n_unexpected);

    if (!drained) {
        simputs("FAIL: status ring did not drain within the read bound\n");
        test_passed = false;
    }

    struct {
        int observed;
        int expected;
        const char *name;
    } checks[] = {
        {n_write_denied, ctx->exp_write_denied, "WRITE_ACCESS_DENIED"},
        {n_read_denied, ctx->exp_read_denied, "READ_ACCESS_DENIED"},
        {n_write_overflow, ctx->exp_write_overflow, "WRITE_OVERFLOW"},
        {n_read_overflow, ctx->exp_read_overflow, "READ_OVERFLOW"},
        {n_jump_failed, ctx->exp_jump_failed, "JUMP_READ_FAILED"},
        {n_jump_security, ctx->exp_jump_security, "JUMP_SECURITY"},
        {n_validate_failed, ctx->exp_validate_failed, "VALIDATE_ADDRESS_FAILED"},
        /* CMD_UNKNOWN and CMD_FAILED overlap for some rejected IDs, so they are scored together. */
        {n_cmd_unknown + n_cmd_failed, ctx->exp_cmd_unknown,
         "dispatch reject (CMD_UNKNOWN/CMD_FAILED)"},
    };

    for (int i = 0; i < (int)(sizeof(checks) / sizeof(checks[0])); i++) {
        if (checks[i].observed < checks[i].expected) {
            simputs("FAIL: too few status records for ");
            simputs(checks[i].name);
            simputshex32(" - expected at least ", checks[i].expected);
            simputshex32(", observed ", checks[i].observed);
            test_passed = false;
        }
    }

    if (n_unexpected != 0) {
        simputs("FAIL: SMC status ring holds error records this test's stimulus cannot produce\n");
        test_passed = false;
    }

    if (ctx->violations_triggered == 0) {
        simputs("FAIL: no injected violation was confirmed; the test observed nothing\n");
        test_passed = false;
    }
    if (ctx->errors_found == 0) {
        simputs("FAIL: violations were injected but the status ring reported none\n");
        test_passed = false;
    }
    if (ctx->positive_controls_ok == 0) {
        simputs("FAIL: no positive control succeeded; the deny results prove nothing\n");
        test_passed = false;
    }

    mark_test_result(ctx, test_passed, "Error Reporting Verification");
    return test_passed;
}

static bool finalize_comprehensive_results(comprehensive_error_test_context_t *ctx) {
    uint32_t result_code =
        ctx->overall_result ? SMC_SCRATCHPAD_SIM_PASS_CODE : SMC_SCRATCHPAD_SIM_FAIL_CODE;

    int rc = occp_send_write_command(ctx->occp_ctx, ctx->occp_ctx->slave_addr,
                                     SMC_CPU_CTRL_SCRATCH_0__REG_ADDR, (uint8_t *)&result_code,
                                     sizeof(result_code));
    increment_cmd_count(ctx->occp_ctx);

    if (is_secure_mode()) {
        simputs("secure mode: the DUT-side completion write is outside the OCCP window\n");
        return true;
    }
    if (rc != OCCP_SUCCESS) {
        simputs("FAIL: completion-code WRITE to SMC_CPU_CTRL_SCRATCH_0 was not accepted\n");
        return false;
    }
    return true;
}

int main(void) {
    static test_context_t occp_ctx = {0};
    static comprehensive_error_test_context_t test_ctx = {0};

    init_test(0);

    simputs("=== OCCP Comprehensive Error Verification Test ===\n");
    simputs("Mission: check the OCCP response code AND the SMC status record for every\n");
    simputs("         error scenario the production ROM is specified to reject.\n");

    if (!initialize_interface(&occp_ctx)) {
        simputs("FAIL: Interface initialization failed\n");
        test_fail(0);
        while (true) {
            __asm__("wfi");
        }
    }

    occp_ctx.test_base_addr = OCCP_TEST_BASE_ADDR;
    occp_ctx.test_upper_addr_bound = OCCP_TEST_BUFFER_SAFE_UPPER_ADDR;
    occp_ctx.overall_result = true;
    occp_ctx.cmd_count = 0;
    occp_ctx.exp_occp_last_error = 0;
    occp_ctx.exp_response_code = OCCP_ERROR_NONE;

    init_test_context(&test_ctx, &occp_ctx);

    if (occp_ctx.type == DRIVER_TYPE_I3C) {
        simputshex64("Discovered OCCP target dynamic address: 0x", occp_ctx.slave_addr);
        if (occp_ctx.slave_addr == 0 ||
            occp_ctx.slave_addr != occp_ctx.discovered_devices[1].dynamic_addr) {
            simputs("FAIL: slave_addr does not match the address DAA assigned\n");
            test_ctx.overall_result = false;
        }
    } else {
        simputs("I2C path: the target address is held by the controller, not the OCCP helper\n");
    }

    if (test_ctx.overall_result) {
        if (!positive_control(&test_ctx, 0x01)) {
            test_ctx.overall_result = false;
        }

        test_memory_access_violations(&test_ctx);
        test_zero_length_rejection(&test_ctx);
        test_jump_security_violations(&test_ctx);
        test_invalid_command_injection(&test_ctx);
        test_transfer_size_boundaries(&test_ctx);
        test_validate_boot_security(&test_ctx);
        test_address_wraparound(&test_ctx);
        test_permitted_range_boundary(&test_ctx);
        test_byte_order_preservation(&test_ctx);
        test_back_to_back_commands(&test_ctx);

        verify_error_reporting(&test_ctx);
    }

    if (!occp_ctx.overall_result) {
        simputs("FAIL: the shared OCCP framework reported a response-protocol mismatch\n");
        test_ctx.overall_result = false;
    }

    if (!finalize_comprehensive_results(&test_ctx)) {
        test_ctx.overall_result = false;
    }

    simputs("\n=== Comprehensive Error Verification Results Summary ===\n");
    simputshex32("Tests passed: ", test_ctx.passed_tests);
    simputshex32("Tests failed: ", test_ctx.total_tests - test_ctx.passed_tests);
    simputshex32("Total tests: ", test_ctx.total_tests);
    simputshex32("Violations confirmed: ", test_ctx.violations_triggered);
    simputshex32("Positive controls passed: ", test_ctx.positive_controls_ok);
    simputshex32("Error entries found: ", test_ctx.errors_found);
    simputshex32("Status entries processed: ", test_ctx.status_entries_processed);

    if (test_ctx.overall_result) {
        simputs("COMPREHENSIVE OCCP ERROR VERIFICATION: PASS\n");
        test_pass(0);
    } else {
        simputs("COMPREHENSIVE OCCP ERROR VERIFICATION: FAIL\n");
        test_fail(0);
    }

    simputs("Done\n");
    while (true) {
        __asm__("wfi");
    }

    return 0;
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
