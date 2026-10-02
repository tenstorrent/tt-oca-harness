/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/*
 * SEP Service Request Dispatch Test
 *
 * Verifies a request/response exchange between SMC firmware and a SEP-side
 * peer over scratch registers: for each request the firmware decodes the
 * operation code, applies the operation (NOT, XOR with a constant, byte
 * reverse, rotate left by 8, population count) to the operand and returns the
 * result. An unknown operation code returns an error status.
 *
 * Only the boot hart runs this test, so no other core writes the shared
 * scratch registers; the other harts park in WFI.
 */

#include <stdint.h>

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

        uint32_t op_code = cmd_hdr & 0xFFU;
        uint32_t data = read_scratch(DATA_SCRATCH_NUM);

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

        /* The handshake register also carries the result, so the peer can
         * read it without a bus access. */
        write_scratch(RESULT_SCRATCH_NUM, result);
        write_scratch(STATUS_SCRATCH_NUM, status);
        write_scratch(HANDSHAKE_SCRATCH, result);

        /* Wait for testbench to acknowledge */
        do {
            /* wait */
        } while (read_scratch(CMD_SCRATCH_NUM) != 0U);
    }

    test_pass(0);
}
