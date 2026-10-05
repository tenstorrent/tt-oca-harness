/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/*
 * SEP Bidirectional Interaction Test
 *
 * Verifies that requests in both directions between SMC firmware and the
 * testbench, acting as SEP, complete correctly when they alternate over the
 * shared scratch registers for several rounds. Each round, the firmware first
 * requests an operation from SEP and checks the result, then performs an
 * operation SEP requests and returns the result.
 */

#include <stdint.h>

#include "smc_defines.h"
#include "smc_test.h"

#define N_ROUNDS 3

#define HANDSHAKE_SCRATCH 1
#define CTRL_SCRATCH_NUM 5 /* dual-use: SEP response (A) / SEP cmd+ack (B) */

/* Tokens the firmware posts on the handshake scratch */
#define FW_REQ_A_BASE 0xD1D10000U
#define FW_ACK_A_BASE 0xD1A10000U
#define FW_READY_B_BASE 0xD1B10000U

/* Acknowledgement SEP posts on the control scratch at the end of Phase B */
#define SEP_ACK_B_BASE 0xD1E10000U

#define OP_NOT 0x01U
#define OP_XOR_MAGIC 0x02U
#define OP_BYTE_REV 0x03U
#define OP_ROT_L8 0x04U
#define OP_POPCOUNT 0x05U
#define XOR_MAGIC 0xDEADBEEFU

/* Phase A: FW asks SEP to apply OP_A[r] to DATA_A[r] */
static const uint8_t OP_A[N_ROUNDS] = {OP_NOT, OP_XOR_MAGIC, OP_BYTE_REV};
static const uint32_t DATA_A[N_ROUNDS] = {0x12345678U, 0xA5A5A5A5U, 0x11223344U};

/*
 * Phase B: SEP asks FW to apply its operation to DATA_B[r]. The data stays
 * local to the firmware; SEP holds the same values to check the result.
 */
static const uint32_t DATA_B[N_ROUNDS] = {0xCAFEBABEU, 0x0F0F0F0FU, 0xF1F2F3F4U};

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

static uint32_t compute(uint8_t op, uint32_t data) {
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
    for (uint32_t r = 0; r < N_ROUNDS; r++) {

        /* Phase A: FW requests a service from SEP */
        write_scratch(CTRL_SCRATCH_NUM, 0U);
        write_scratch(HANDSHAKE_SCRATCH, FW_REQ_A_BASE | ((r & 0xFFU) << 8) | OP_A[r]);

        /* Wait for SEP's result */
        uint32_t resp_a;
        do {
            resp_a = read_scratch(CTRL_SCRATCH_NUM);
        } while (resp_a == 0U);

        if (resp_a != compute(OP_A[r], DATA_A[r])) {
            test_fail(0);
        }

        write_scratch(HANDSHAKE_SCRATCH, FW_ACK_A_BASE | r);

        /* Wait for SEP to clear the channel */
        uint32_t ctrl;
        do {
            ctrl = read_scratch(CTRL_SCRATCH_NUM);
        } while (ctrl != 0U);

        /* Phase B: SEP requests a service from FW */
        write_scratch(HANDSHAKE_SCRATCH, FW_READY_B_BASE | r);

        /* Wait for SEP's command */
        uint32_t sep_cmd;
        do {
            sep_cmd = read_scratch(CTRL_SCRATCH_NUM);
        } while (sep_cmd == 0U);

        uint8_t op_b = (uint8_t)(sep_cmd & 0xFFU);
        uint32_t result_b = compute(op_b, DATA_B[r]);

        /* The result replaces the readiness token; SEP detects the change */
        write_scratch(HANDSHAKE_SCRATCH, result_b);

        /* Wait for SEP's acknowledgement; the next round's request clears it */
        uint32_t sep_ack = SEP_ACK_B_BASE | r;
        do {
            ctrl = read_scratch(CTRL_SCRATCH_NUM);
        } while (ctrl != sep_ack);
    }

    test_pass(0);
}

/* secondary_main is not defined: the crt0 weak default parks non-boot harts in
 * WFI, so only the boot hart drives the scratch handshake. */
