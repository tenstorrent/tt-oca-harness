/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/*
 * OCCP Comprehensive Error Verification Test
 *
 * Drives the SMC OCCP target with the error scenarios the production ROM is
 * specified to reject, and checks two independent things for every one of
 * them:
 *
 *   1. the OCCP response error code the ROM returns, compared exactly through
 *      the shared framework's ctx->exp_response_code hook, and
 *   2. the SMC status ring record the ROM emits, compared against the
 *      OCCP_SPEC_ERROR_* value the ROM source assigns to that scenario.
 *
 * Every deny check is paired with a positive control issued on the same
 * interface in the same phase: a legal WRITE/READ round trip that must succeed
 * and must read back exactly what was written. A phase passes only when both
 * legs held.
 *
 * Expectations are taken from the production ROM, not from this file's own
 * prose:
 *   hw/sys/smc/bootrom/prod/lib/src/occp.c
 *     smc_occp_check_addr_access_allowed()  - access_size == 0, address
 *       arithmetic overflow, the always-protected ROM-owned region
 *       [SMC_SRAM_BASE_ADDR, OCCP_TEST_BASE_ADDR), and the secure-mode-only
 *       [OCCP base, SRAM limit] boundary.
 *     smc_occp_handle_write()   - write_size 0 or > OCCP_MAX_WR_SIZE report
 *       WRITE_OVERFLOW (0x130) with an Invalid_header response; a misaligned
 *       or denied address reports WRITE_ACCESS_DENIED (0x131) with an
 *       Invalid_Address response.
 *     smc_occp_handle_read()    - the same two shapes with READ_OVERFLOW
 *       (0x120) and READ_ACCESS_DENIED (0x121).
 *     smc_occp_handle_jump()    - unsecure mode: NULL / misaligned / denied
 *       address report JUMP_READ_FAILED (0x202) with Invalid_Address; secure
 *       mode: JUMP_SECURITY (0x201) with an Invalid_Msgid response.
 *     smc_occp_handle_validate_boot() - NULL / misaligned / denied manifest
 *       address report VALIDATE_ADDRESS_FAILED (0x141) with Invalid_Address.
 *   hw/sys/smc/bootrom/prod/include/smc_rom_defs.h - the memory map.
 *
 * Two scenarios are NOT presented here, because the OCCP request encoding
 * cannot express them and issuing them anyway only produces a malformed short
 * packet:
 *   - WRITE_OVERFLOW by oversize length. occp_send_write_command() advertises
 *     byte_length + 12 in an 11-bit header field, so a write_size above
 *     MAX_OCCP_WRITE_SIZE (2035) cannot be advertised coherently. The only
 *     reachable WRITE_OVERFLOW trigger is write_size == 0, covered in Test 2.
 *   - READ count multiplication overflow. The read_length field is 11 bits, so
 *     no count above MAX_OCCP_READ_SIZE (2047) reaches the ROM's
 *     OCCP_CHECK_OVERFLOW_MUL path from this interface at all.
 * Both are recorded as coverage gaps rather than claimed as verified.
 */

#include "occp_test_common.h"
#include "smc_defines.h"
#include "smc_test.h"
#include <string.h>
#include "smc_status.h"

/* Memory map, mirrored from the production ROM headers rather than re-guessed.
 * The ROM-owned region is denied to OCCP in BOTH secure and unsecure mode by
 * smc_occp_check_addr_access_allowed(); OCCP_TEST_BASE_ADDR is the first
 * address the ROM will serve. */
#define ROM_PROTECTED_BASE SMC_SRAM_BASE_ADDR /* 0xC0060000 */
#define ROM_PROTECTED_END OCCP_TEST_BASE_ADDR /* 0xC0066400 */

/* Addresses used for the positive controls and the round-trip phases. Both are
 * 8-byte aligned and well inside [OCCP_TEST_BASE_ADDR, safe upper bound). */
#define CONTROL_ADDR (OCCP_TEST_BASE_ADDR + 0x1000ULL)
#define ROUNDTRIP_ADDR (OCCP_TEST_BASE_ADDR + 0x2000ULL)
#define BULK_ADDR (OCCP_TEST_BASE_ADDR + 0x4000ULL)

/* Above the secure-mode upper bound (SMC_SRAM_BASE + 1MB = 0xC0160000) and
 * below UINT64_MAX, so it exercises the secure-mode boundary only. */
#define ABOVE_SRAM_ADDR 0xC0200000ULL

/* Bound on the status-ring drain. The ring is far smaller than this; hitting
 * the bound means the ring never returned 0 and is a failure, not an exit. */
#define MAX_STATUS_BUFFER_READS 200

/* Shared buffers, kept static so the max-size cases do not sit on the stack. */
static uint8_t g_write_buf[MAX_OCCP_WRITE_SIZE];
static uint8_t g_read_buf[MAX_OCCP_READ_SIZE];

typedef struct {
    test_context_t *occp_ctx;
    int total_tests;
    int passed_tests;
    bool overall_result;

    /* Observed activity. */
    int violations_triggered; /* injected violations that answered as specified */
    int positive_controls_ok;
    int status_entries_processed;
    int errors_found;

    /* Stimulus-derived minimums: one expected status record per injected
     * violation. Checked in verify_error_reporting(). */
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

/* The ROM's error paths flush the interface FIFO; the OCCP test family
 * re-latches with a GET_VERSION before continuing. A failed re-latch means the
 * target did not recover and is a test failure. */
static bool relatch(comprehensive_error_test_context_t *ctx) {
    uint32_t version = 0;
    int rc = occp_send_get_version_command(ctx->occp_ctx, ctx->occp_ctx->slave_addr, &version);
    increment_cmd_count(ctx->occp_ctx);
    if (rc != OCCP_SUCCESS) {
        simputs("FAIL: interface did not recover (GET_VERSION failed after error injection)\n");
        return false;
    }
    return true;
}

/*
 * Positive control: a legal WRITE followed by a READ of the same bytes, on the
 * same interface, in the same phase as the deny checks. Proves the interface
 * was alive and the target was serving OCCP at the moment the deny checks were
 * issued, so "the command did not succeed" cannot stand in for "the target
 * refused it".
 */
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

/*
 * Deny helpers. Each arms the framework's exact-expectation hook with the OCCP
 * response error code the ROM is specified to return for this scenario, issues
 * the command, and requires the framework to confirm that exact code.
 * occp_get_response_header() returns OCCP_SUCCESS only when the received error
 * code equals exp_response_code, and returns an error both when a different
 * code came back and when the command was accepted instead of refused.
 */
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

/* ------------------------------------------------------------------------- */

/*
 * Test 1 - READ/WRITE access denied.
 *
 * The ROM-owned region is refused in both security modes. The above-SRAM case
 * is refused in secure mode only: in unsecure mode
 * smc_occp_check_addr_access_allowed() applies no upper bound, so asserting a
 * refusal there would be asserting behaviour the ROM does not implement.
 */
static bool test_memory_access_violations(comprehensive_error_test_context_t *ctx) {
    simputs("\n=== Test 1: READ/WRITE Access Denied ===\n");
    simputs("SPEC: ROM-owned SRAM is refused to OCCP READ and WRITE in both security modes\n");

    bool test_passed = true;
    uint8_t test_data[8] = {0xDE, 0xAD, 0xBE, 0xEF, 0x12, 0x34, 0x56, 0x78};

    const uint64_t denied_addrs[] = {
        ROM_PROTECTED_BASE,          /* first ROM-owned word */
        ROM_PROTECTED_BASE + 0x1000, /* mid ROM-owned region */
        ROM_PROTECTED_END - 8,       /* last ROM-owned word */
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

/*
 * Test 2 - zero-length WRITE and READ.
 *
 * This is the only reachable WRITE_OVERFLOW / READ_OVERFLOW trigger: the ROM
 * reports 0x130 / 0x120 and answers Invalid_header when the request's internal
 * length field is 0.
 */
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

/*
 * Test 3 - JUMP security enforcement.
 *
 * No JUMP is issued to a permitted address: in unsecure mode the ROM would
 * take the branch and never return to the OCCP loop.
 */
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
            0x0ULL,                /* NULL address */
            0xFFFFFFFFFFFFFFFFULL, /* not 4-byte aligned */
            ROM_PROTECTED_BASE,    /* ROM-owned region */
            ROM_PROTECTED_END - 4, /* last ROM-owned word */
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

/*
 * Test 4 - invalid command injection.
 *
 * Uses the shared framework's invalid-header injection rather than a raw byte
 * burst through ctx->drv.i2c_drv: that pointer is a union member, and on the
 * I3C path it holds an I3C_Driver, so a call through it would go through a
 * function pointer read out of the wrong struct.
 */
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
        /* occp_send_invalid_header_command() arms exp_response_code itself from
         * the injection mode and clears it again on success. */
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

/*
 * Test 5 - transfer size boundaries.
 *
 * MAX_OCCP_WRITE_SIZE and MAX_OCCP_READ_SIZE are legal and must succeed with
 * the data intact. One byte past them cannot be advertised in the 11-bit
 * length field, so no oversize case is asserted here; the framework's
 * oversize-body injection covers the transport-level oversize instead.
 */
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

    /* Transport-level oversize body: the ROM answers Oversize_msg and logs
     * CMD_FAILED, which the ring scan deliberately ignores. */
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

/*
 * Test 6 - VALIDATE_AND_BOOT security.
 *
 * No VALIDATE_AND_BOOT is issued to a permitted address: the ROM signals
 * manifest-ready and parks in wfi, which would end the run.
 */
static bool test_validate_boot_security(comprehensive_error_test_context_t *ctx) {
    simputs("\n=== Test 6: VALIDATE_AND_BOOT Security ===\n");
    simputs("SPEC: NULL/misaligned/denied manifest address -> VALIDATE_ADDRESS_FAILED\n");

    bool test_passed = true;

    const uint64_t denied_manifests[] = {
        0x0ULL,                /* NULL manifest address */
        0xFFFFFFFFFFFFFFFFULL, /* not 4-byte aligned */
        ROM_PROTECTED_BASE,    /* ROM-owned region */
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

/*
 * Test 7 - address arithmetic overflow.
 *
 * smc_occp_check_addr_access_allowed() refuses addr > UINT64_MAX - access_size
 * before performing the addition, in both security modes. The unaligned case
 * is refused one check earlier, at the 4-byte alignment gate; both report
 * WRITE_ACCESS_DENIED and answer Invalid_Address.
 *
 * 0x8000000000000000 is deliberately not asserted in unsecure mode: the ROM
 * applies no upper bound there, so it is not a denied address. See the
 * RTL/ROM note in the test report.
 */
static bool test_address_wraparound(comprehensive_error_test_context_t *ctx) {
    simputs("\n=== Test 7: Address Arithmetic Overflow ===\n");
    simputs("SPEC: addr + size overflow and misaligned addresses -> WRITE_ACCESS_DENIED\n");

    bool test_passed = true;
    uint8_t test_data[16] = {0};

    const uint64_t overflow_addrs[] = {
        0xFFFFFFFFFFFFFFF0ULL, /* aligned, 16 bytes overflows */
        0xFFFFFFFFFFFFFFF8ULL, /* aligned, 16 bytes overflows */
        0xFFFFFFFFFFFFFFFCULL, /* aligned, 16 bytes overflows */
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

    /* A misaligned address inside the permitted range: refused by the
     * alignment gate, not by the range check. */
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

/*
 * Test 8 - permitted-range boundary.
 *
 * A transfer that starts one word below OCCP_TEST_BASE_ADDR straddles the ROM
 * boundary and must be refused; a transfer starting exactly at
 * OCCP_TEST_BASE_ADDR must be served. This is the boundary the range check
 * actually implements, checked from both sides.
 */
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

/*
 * Test 9 - byte order preservation.
 *
 * The ROM's WRITE/READ handlers use write64_reg/read64_reg for 8-byte
 * transfers, write_reg/read_reg for 4-byte transfers, and a byte loop
 * otherwise. All three preserve byte order, so a round trip must return the
 * bytes in the order they were sent.
 */
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

/*
 * Test 10 - back-to-back command sequence.
 *
 * Issues writes with no intervening traffic to exercise the interface latch,
 * then reads every one of them back and compares each result.
 */
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

/*
 * Test 11 - status ring verification.
 *
 * Drains the SMC status ring and requires at least one status record per
 * injected violation, in the SPEC-assigned category. The counts are minimums,
 * not equalities, because the ROM emits companion CMD_FAILED records on some
 * paths; CMD_FAILED is counted separately and not scored. Any SMC BL0 error
 * record outside the categories this test's stimulus can produce is a failure.
 */
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
            /* Boot-sequence status/warning records; not this test's subject. */
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
            /* CMD_FAILED (0x110 | internal code) is the companion record the
             * dispatch loop emits after most handlers return an error, so it
             * appears alongside almost every category above. Classified before
             * CMD_UNKNOWN because CMD_UNKNOWN's mask (0xF01) also matches it.
             * Counted for the log, not scored. */
            n_cmd_failed++;
        } else if (occp_status_matches_expected(status, OCCP_FW_ID_SMC_BL0, OCCP_STATUS_MSG_ERROR,
                                                (uint16_t)OCCP_SPEC_ERROR_CMD_UNKNOWN, false)) {
            n_cmd_unknown++;
        } else if (OCCP_STATUS_EXTRACT_VALUE(status) == (uint16_t)OCCP_SPEC_ERROR_CMD_READ) {
            /* Transport-level command read error (occp.c:793). Expected here:
             * the oversize-body injection in Test 5 leaves trailing bytes that
             * the dispatch loop reads as a malformed next command. Logged, not
             * scored. */
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
        /* Invalid-header rejections. The ROM reports them as
         * 0x101 | <randomly drawn rejected ID> (occp.c:713) or
         * 0x110 | <header validation code> (occp.c:679); the drawn ID is not
         * reported back to the test and, for ids with (id & 0xF0) == 0x10, the
         * first form is indistinguishable from the second. The two are
         * therefore scored together as one dispatch-reject family. The exact,
         * per-command proof for these injections is the exp_response_code
         * check in Test 4, which already ran. */
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

/*
 * Completion code for the DUT-side scratch register.
 *
 * This is the OCCP test family's convention: the master writes the verdict
 * into SMC_CPU_CTRL_SCRATCH_0 over a frontdoor OCCP WRITE, and cocotb's
 * monitor_test() polls that net as well as bfm_scratch_0. The write is
 * expected to be refused in secure mode - SCRATCH_0 (0xC0039080) is outside
 * the secure-mode OCCP window - so its result is only folded into the verdict
 * in unsecure mode, where the ROM is specified to serve it.
 */
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

    /* Entry assertion for the bus address every phase uses. On the I3C path the
     * address comes from DAA; the OCCP helpers ignore the address argument on
     * the I2C path, where the target address was programmed into the controller
     * at init time. */
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
        /* Warm-up so a phase failure cannot be a cold-interface artefact. */
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

    /* The shared OCCP framework keeps its own mismatch flag and clears it at 19
     * sites in occp_commands.c when a response violates the protocol. Fold it
     * into the verdict; there is exactly one result from here on. */
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
