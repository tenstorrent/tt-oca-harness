/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/*
 * SEP Firmware-Initiated Request Test
 *
 * Tests the SMC-active communication path: SMC firmware acts as the
 * requester, signalling a crypto service request to the testbench (acting
 * as SEP).  SEP computes the requested operation and writes the result back;
 * SMC verifies the result independently before proceeding.
 *
 * Spec basis: OCAH Specification §Crypto Key Manager — KM can initiate
 * requests upstream for key derivation or crypto primitives.  This test
 * exercises the analogous path where SMC firmware drives the request
 * sequence, reversing the normal TB→FW direction.
 *
 * Protocol (scratch registers):
 *   scratch[HANDSHAKE_SCRATCH] = FW_REQ_BASE | (req_idx << 8) | op_code
 *                                              (FW signals request to SEP)
 *   scratch[RESP_SCRATCH_NUM]  = computed result
 *                                              (SEP/TB writes response; AXI write)
 *   scratch[HANDSHAKE_SCRATCH] = FW_ACK_BASE | req_idx
 *                                              (FW acknowledges receipt)
 *   scratch[RESP_SCRATCH_NUM]  = 0            (SEP/TB resets; signals next-ready)
 *
 * Both sides maintain identical copies of FIXED_DATA[] so no data transfer
 * over the bus is needed — FW specifies only the op_code to apply.  This
 * mirrors a real KM scenario where SEP operates on locally held key material.
 *
 * NOTE: secondary_main is not defined here.  The weak default in crt0.S
 * routes only the boot hart to main(); non-boot harts spin in WFI.
 */

#include <stdint.h>
#include <stdbool.h>

#include "smc_defines.h"
#include "smc_test.h"

#define NUM_REQUESTS 5

#define HANDSHAKE_SCRATCH 1
#define RESP_SCRATCH_NUM 5 /* TB writes response here; FW polls via MMIO */

/* Request token: FW_REQ_BASE | (req_idx << 8) | op_code  (FW → TB via scratch[1]) */
#define FW_REQ_BASE 0xC0C00000U
/* Ack token:     FW_ACK_BASE | req_idx                   (FW → TB via scratch[1]) */
#define FW_ACK_BASE 0xC0A00000U

#define OP_NOT 0x01U
#define OP_XOR_MAGIC 0x02U
#define OP_BYTE_REV 0x03U
#define OP_ROT_L8 0x04U
#define OP_POPCOUNT 0x05U
#define XOR_MAGIC 0xDEADBEEFU

/*
 * Fixed test vectors — must match TB constants exactly.
 * Modelling SEP operating on locally held key material rather than passing
 * raw data over the bus.
 */
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

        /* ----------------------------------------------------------------
         * Step 1: clear response scratch, then signal request to SEP.
         * scratch[1] carries: request type + index + op_code.
         * TB reads this via the direct RTL wire (dut.scratch_1).
         * ---------------------------------------------------------------- */
        write_scratch(RESP_SCRATCH_NUM, 0U);
        write_scratch(HANDSHAKE_SCRATCH, FW_REQ_BASE | ((i & 0xFFU) << 8) | op);

        /* ----------------------------------------------------------------
         * Step 2: poll RESP_SCRATCH_NUM until SEP (TB) writes its result.
         * TB uses AXI write (reliable); FW reads via MMIO (reliable).
         * ---------------------------------------------------------------- */
        uint32_t resp;
        do {
            resp = read_scratch(RESP_SCRATCH_NUM);
        } while (resp == 0U);

        /* ----------------------------------------------------------------
         * Step 3: verify — FW independently computes the expected result
         * and compares against what SEP returned.
         * ---------------------------------------------------------------- */
        uint32_t expected = compute_expected(op, data);
        if (resp != expected) {
            test_fail(0);
            while (true) {
                __asm__("wfi");
            }
        }

        /* ----------------------------------------------------------------
         * Step 4: acknowledge receipt — TB detects via dut.scratch_1.
         * ---------------------------------------------------------------- */
        write_scratch(HANDSHAKE_SCRATCH, FW_ACK_BASE | i);

        /* ----------------------------------------------------------------
         * Step 5: wait for TB to clear RESP_SCRATCH (signals next-ready).
         * ---------------------------------------------------------------- */
        do {
            resp = read_scratch(RESP_SCRATCH_NUM);
        } while (resp != 0U);
    }

    test_pass(0);

    while (true) {
        __asm__("wfi");
    }
    return 0;
}

/* secondary_main is not defined here: the crt0 weak default routes only the
 * boot hart to main() and parks the other harts in WFI. */
