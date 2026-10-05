/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/*
 * SEP Firmware-Initiated Request Test
 *
 * Verifies the SMC-initiated request path: the firmware asks the testbench,
 * acting as SEP, to apply each of five operations to fixed data and checks
 * every returned result against its own computation. The data is not sent:
 * both sides hold the same values.
 */

#include <stdint.h>

#include "smc_defines.h"
#include "smc_test.h"

#define NUM_REQUESTS 5

#define HANDSHAKE_SCRATCH 1
#define RESP_SCRATCH_NUM 5 /* SEP writes its response here */

/* Tokens the firmware posts on the handshake scratch */
#define FW_REQ_BASE 0xC0C00000U
#define FW_ACK_BASE 0xC0A00000U

#define OP_NOT 0x01U
#define OP_XOR_MAGIC 0x02U
#define OP_BYTE_REV 0x03U
#define OP_ROT_L8 0x04U
#define OP_POPCOUNT 0x05U
#define XOR_MAGIC 0xDEADBEEFU

/* Operands SEP applies each operation to; the testbench holds the same values. */
static const uint32_t FIXED_DATA[NUM_REQUESTS] = {
    0x12345678U, /* req 0: OP_NOT        */
    0xA5A5A5A5U, /* req 1: OP_XOR_MAGIC  */
    0x11223344U, /* req 2: OP_BYTE_REV   */
    0xAABBCCDDU, /* req 3: OP_ROT_L8     */
    0xDEADBEEFU, /* req 4: OP_POPCOUNT   */
};

static const uint8_t OP_SEQUENCE[NUM_REQUESTS] = {
    OP_NOT, OP_XOR_MAGIC, OP_BYTE_REV, OP_ROT_L8, OP_POPCOUNT,
};

static uint32_t byte_reverse(uint32_t x) {
    return ((x & 0xFFU) << 24) | (((x >> 8) & 0xFFU) << 16) | (((x >> 16) & 0xFFU) << 8) |
           ((x >> 24) & 0xFFU);
}

static uint32_t rotate_left_8(uint32_t x) {
    return (x << 8) | (x >> 24);
}

static uint32_t popcount(uint32_t x) {
    uint32_t n = 0;
    while (x) {
        n += x & 1U;
        x >>= 1;
    }
    return n;
}

static uint32_t compute_expected(uint8_t op, uint32_t data) {
    switch (op) {
    case OP_NOT:
        return ~data;
    case OP_XOR_MAGIC:
        return data ^ XOR_MAGIC;
    case OP_BYTE_REV:
        return byte_reverse(data);
    case OP_ROT_L8:
        return rotate_left_8(data);
    case OP_POPCOUNT:
        return popcount(data);
    default:
        return 0U;
    }
}

int main(void) {
    for (uint32_t i = 0; i < NUM_REQUESTS; i++) {
        uint8_t op = OP_SEQUENCE[i];
        uint32_t data = FIXED_DATA[i];

        /* Clear the response scratch before posting the request */
        write_scratch(RESP_SCRATCH_NUM, 0U);
        write_scratch(HANDSHAKE_SCRATCH, FW_REQ_BASE | ((i & 0xFFU) << 8) | op);

        /* Wait for SEP's response */
        uint32_t resp;
        do {
            resp = read_scratch(RESP_SCRATCH_NUM);
        } while (resp == 0U);

        uint32_t expected = compute_expected(op, data);
        if (resp != expected) {
            test_fail(0);
        }

        write_scratch(HANDSHAKE_SCRATCH, FW_ACK_BASE | i);

        /* Wait for SEP to clear the response scratch */
        do {
            resp = read_scratch(RESP_SCRATCH_NUM);
        } while (resp != 0U);
    }

    test_pass(0);
}

/* secondary_main is not defined: the crt0 weak default parks non-boot harts in
 * WFI, so only the boot hart drives the scratch handshake. */
