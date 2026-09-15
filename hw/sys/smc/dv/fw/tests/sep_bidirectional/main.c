/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/*
 * SEP Bidirectional Interaction Test
 *
 * Tests both communication directions in alternating phases within the same
 * simulation: SMC firmware initiates Phase A requests to SEP, then SEP
 * initiates Phase B requests to SMC, repeated for N_ROUNDS rounds.
 *
 * Spec basis: OCAH Specification §Crypto Key Manager — the KM→SEP path
 * (key requests) and SEP→KM path (status / crypto results) must coexist
 * without state corruption; this test forces both paths to exercise the same
 * shared scratch bus in strict alternation.
 *
 * Scratch register assignment:
 *   scratch[HANDSHAKE_SCRATCH=1]  FW → TB  (direct RTL wire in TB)
 *   scratch[CTRL_SCRATCH_NUM =5]  dual-use:
 *       Phase A: TB → FW  (SEP writes response)
 *       Phase B: TB → FW  (SEP writes command, then ack)
 *
 * Per-round protocol:
 *
 *   ── Phase A: FW-initiated (SMC requests SEP service) ──────────────
 *   FW: scratch[1]  = FW_REQ_A  | (round << 8) | op_A[round]
 *   TB: detects via dut.scratch_1; computes result; writes scratch[5] = result
 *   FW: polls scratch[5] != 0; verifies result
 *   FW: scratch[1]  = FW_ACK_A  | round
 *   TB: detects ack; writes scratch[5] = 0  (resets channel)
 *   FW: polls scratch[5] == 0
 *
 *   ── Phase B: SEP-initiated (SEP requests SMC service) ─────────────
 *   FW: scratch[1]  = FW_READY_B | round  (FW ready to serve)
 *   TB: detects ready; writes scratch[5] = SEP_CMD | op_B[round]
 *   FW: polls scratch[5] != 0; extracts op_B; computes result_B
 *   FW: scratch[1]  = result_B            (overwrites READY token)
 *   TB: detects scratch_1 ≠ FW_READY_B|round; verifies result_B
 *   TB: writes scratch[5] = SEP_ACK_B | round
 *   FW: polls scratch[5] == SEP_ACK_B | round
 *
 * NOTE: secondary_main is not defined here.  The weak default in crt0.S
 * routes only the boot hart to main(); non-boot harts spin in WFI.
 */

#include <stdint.h>
#include <stdbool.h>

#include "smc_defines.h"
#include "smc_test.h"

#define N_ROUNDS 3

#define HANDSHAKE_SCRATCH 1
#define CTRL_SCRATCH_NUM 5 /* dual-use: SEP response (A) / SEP cmd+ack (B) */

/* Phase A tokens (FW-initiated) — written to scratch[1] by FW */
#define FW_REQ_A_BASE 0xD1D10000U /* | (round << 8) | op_A */
#define FW_ACK_A_BASE 0xD1A10000U /* | round               */

/* Phase B tokens (SEP-initiated) */
#define FW_READY_B_BASE 0xD1B10000U /* | round  (FW→TB via scratch[1])   */
#define SEP_CMD_MAGIC 0xD1C10000U   /* | op_B   (TB→FW via scratch[5])   */
#define SEP_ACK_B_BASE 0xD1E10000U  /* | round  (TB→FW via scratch[5])   */

#define OP_NOT 0x01U
#define OP_XOR_MAGIC 0x02U
#define OP_BYTE_REV 0x03U
#define OP_ROT_L8 0x04U
#define OP_POPCOUNT 0x05U
#define XOR_MAGIC 0xDEADBEEFU

/* Phase A: FW asks SEP to apply op_A[r] to DATA_A[r] */
static const uint8_t OP_A[N_ROUNDS] = {OP_NOT, OP_XOR_MAGIC, OP_BYTE_REV};
static const uint32_t DATA_A[N_ROUNDS] = {0x12345678U, 0xA5A5A5A5U, 0x11223344U};

/*
 * Phase B: SEP asks FW to apply op_B[r] to DATA_B[r].
 * DATA_B models locally held key material in FW — TB agrees on the same
 * constants but never needs to transfer the data over the bus.
 */
static const uint8_t OP_B[N_ROUNDS] = {OP_XOR_MAGIC, OP_POPCOUNT, OP_ROT_L8};
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

        /* ================================================================
         * Phase A: FW-initiated — FW requests SEP to compute a service
         * ================================================================ */

        /* A-1: clear control scratch, signal request to SEP */
        write_scratch(CTRL_SCRATCH_NUM, 0U);
        write_scratch(HANDSHAKE_SCRATCH, FW_REQ_A_BASE | ((r & 0xFFU) << 8) | OP_A[r]);

        /* A-2: wait for SEP response */
        uint32_t resp_a;
        do {
            resp_a = read_scratch(CTRL_SCRATCH_NUM);
        } while (resp_a == 0U);

        /* A-3: verify */
        if (resp_a != compute(OP_A[r], DATA_A[r])) {
            test_fail(0);
            while (true) {
                __asm__("wfi");
            }
        }

        /* A-4: acknowledge */
        write_scratch(HANDSHAKE_SCRATCH, FW_ACK_A_BASE | r);

        /* A-5: wait for SEP to reset control scratch (channel clear) */
        uint32_t ctrl;
        do {
            ctrl = read_scratch(CTRL_SCRATCH_NUM);
        } while (ctrl != 0U);

        /* ================================================================
         * Phase B: SEP-initiated — SEP requests FW to compute a service
         * ================================================================ */

        /* B-1: signal readiness to serve */
        write_scratch(HANDSHAKE_SCRATCH, FW_READY_B_BASE | r);

        /* B-2: wait for SEP's command in CTRL_SCRATCH */
        uint32_t sep_cmd;
        do {
            sep_cmd = read_scratch(CTRL_SCRATCH_NUM);
        } while (sep_cmd == 0U);

        /* B-3: extract op_B and compute result using local key material */
        uint8_t op_b = (uint8_t)(sep_cmd & 0xFFU);
        uint32_t result_b = compute(op_b, DATA_B[r]);

        /* B-4: write result to HANDSHAKE_SCRATCH (TB reads via dut.scratch_1).
         *      This overwrites FW_READY_B_BASE|r — TB detects the change. */
        write_scratch(HANDSHAKE_SCRATCH, result_b);

        /* B-5: wait for SEP to acknowledge */
        uint32_t sep_ack = SEP_ACK_B_BASE | r;
        do {
            ctrl = read_scratch(CTRL_SCRATCH_NUM);
        } while (ctrl != sep_ack);

        /* (Next round Phase A will clear CTRL_SCRATCH at its own step A-1) */
    }

    test_pass(0);

    while (true) {
        __asm__("wfi");
    }
    return 0;
}

/* secondary_main is not defined here: the crt0 weak default routes only the
 * boot hart to main() and parks the other harts in WFI. */
