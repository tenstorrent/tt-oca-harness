/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/*
 * SEP Service Request Dispatch Test Firmware
 *
 * Tests a service dispatch protocol where the testbench (acting as SEP) sends
 * a structured request containing an operation code and operand data.  SMC
 * firmware dispatches on the operation code and returns the computed result.
 *
 * Spec basis: OCAH Specification §Crypto Key Manager — the KM command message
 * format encodes a function_id[15:8] alongside data, enabling a firmware-
 * defined dispatch table.  This test exercises an analogous dispatch table on
 * the SMC side using scratch registers as the transport.
 *
 * Protocol (scratch registers):
 *   scratch[HANDSHAKE_SCRATCH] = CMD_READY_TOKEN       (FW signals ready)
 *   scratch[CMD_SCRATCH_NUM]   = {op_code[7:0], seq[15:8], data[31:16]}
 *   scratch[DATA_SCRATCH_NUM]  = operand data (32-bit)
 *   scratch[RESULT_SCRATCH_NUM]= computed result                       (backup)
 *   scratch[STATUS_SCRATCH_NUM]= 0 on success, error code on failure
 *   scratch[HANDSHAKE_SCRATCH] = computed result                       (primary; TB reads
 *                                                                        directly as wire)
 *   scratch[CMD_SCRATCH_NUM]   = 0                                     (TB acknowledges)
 *   scratch[0]                 = TEST_PASS / TEST_FAIL
 *
 * Operation codes (op_code in bits [7:0] of CMD scratch):
 *   OP_NOT       (0x01): result = ~data
 *   OP_XOR_MAGIC (0x02): result = data ^ 0xDEADBEEF
 *   OP_BYTE_REV  (0x03): result = byte-reversed data
 *   OP_ROT_L8    (0x04): result = rotate_left(data, 8)
 *   OP_POPCOUNT  (0x05): result = population count (number of 1-bits) of data
 *
 * NUM_REQUESTS requests are dispatched sequentially.  After each request the
 * firmware clears its working scratches and re-signals ready before accepting
 * the next.
 */

#include <stdint.h>
#include <stdbool.h>

#include "smc_defines.h"
#include "smc_test.h"

#define NUM_REQUESTS 5

#define CMD_READY_TOKEN 0xBEEFCAFEU

#define CMD_SCRATCH_NUM 5
#define DATA_SCRATCH_NUM 4
#define RESULT_SCRATCH_NUM 6
#define STATUS_SCRATCH_NUM 7
#define HANDSHAKE_SCRATCH 1

/* Operation codes — must match values in the cocotb test */
#define OP_NOT 0x01U
#define OP_XOR_MAGIC 0x02U
#define OP_BYTE_REV 0x03U
#define OP_ROT_L8 0x04U
#define OP_POPCOUNT 0x05U

#define XOR_MAGIC 0xDEADBEEFU

/* Status codes written to STATUS_SCRATCH_NUM */
#define STATUS_OK 0x00000000U
#define STATUS_UNKNOWN_OP 0xE0000001U

static uint32_t byte_reverse(uint32_t x) {
    return ((x & 0xFFU) << 24) | (((x >> 8) & 0xFFU) << 16) | (((x >> 16) & 0xFFU) << 8) |
           ((x >> 24) & 0xFFU);
}

static uint32_t rotate_left_8(uint32_t x) {
    return (x << 8) | (x >> 24);
}

static uint32_t popcount(uint32_t x) {
    uint32_t count = 0;
    while (x) {
        count += x & 1U;
        x >>= 1;
    }
    return count;
}

int main(void) {
    for (uint32_t req = 0; req < NUM_REQUESTS; req++) {
        /* Signal ready for the next request. DATA_SCRATCH_NUM is not cleared:
         * the testbench writes fresh operand data before writing the CMD
         * scratch. */
        write_scratch(CMD_SCRATCH_NUM, 0U);
        write_scratch(RESULT_SCRATCH_NUM, 0U);
        write_scratch(STATUS_SCRATCH_NUM, 0U);
        write_scratch(HANDSHAKE_SCRATCH, CMD_READY_TOKEN);

        /* Wait for testbench to write the command header */
        uint32_t cmd_hdr;
        do {
            cmd_hdr = read_scratch(CMD_SCRATCH_NUM);
        } while (cmd_hdr == 0U);

        /* Extract operation code (bits [7:0]) and read operand data */
        uint32_t op_code = cmd_hdr & 0xFFU;
        uint32_t data = read_scratch(DATA_SCRATCH_NUM);

        /* Dispatch on operation code */
        uint32_t result = 0U;
        uint32_t status = STATUS_OK;

        switch (op_code) {
        case OP_NOT:
            result = ~data;
            break;
        case OP_XOR_MAGIC:
            result = data ^ XOR_MAGIC;
            break;
        case OP_BYTE_REV:
            result = byte_reverse(data);
            break;
        case OP_ROT_L8:
            result = rotate_left_8(data);
            break;
        case OP_POPCOUNT:
            result = popcount(data);
            break;
        default:
            result = 0U;
            status = STATUS_UNKNOWN_OP;
            break;
        }

        /* Write result and status.
         * Write result to RESULT_SCRATCH_NUM (scratch[6]) as backup,
         * then overwrite HANDSHAKE_SCRATCH (scratch[1]) with the result so
         * the testbench can read it directly via the RTL wire without AXI. */
        write_scratch(RESULT_SCRATCH_NUM, result);
        write_scratch(STATUS_SCRATCH_NUM, status);
        write_scratch(HANDSHAKE_SCRATCH, result);

        /* Wait for testbench to acknowledge (clears CMD scratch) */
        do {
            /* wait */
        } while (read_scratch(CMD_SCRATCH_NUM) != 0U);
    }

    /* All requests handled */
    test_pass(0);

    while (true) {
        __asm__("wfi");
    }
    return 0;
}

/* secondary_main is not defined here: the weak default in crt0.S routes the
 * boot hart to main() and spins non-boot harts, so no second core can write
 * the shared scratch registers used by the test protocol. */
