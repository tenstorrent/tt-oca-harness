/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/*
 * SEP Error Injection and Recovery Test
 *
 * Verifies that the firmware's scratch-register service loop, driven by the
 * testbench acting as SEP, answers an unknown operation code with an error
 * status and keeps serving valid requests after it. The testbench checks each
 * response; the firmware itself always reports pass.
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

#define OP_NOT 0x01U
#define OP_XOR_MAGIC 0x02U
#define OP_BYTE_REV 0x03U
#define OP_ROT_L8 0x04U
#define OP_POPCOUNT 0x05U

#define XOR_MAGIC 0xDEADBEEFU

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
        /* The operand scratch is not cleared: the testbench writes a fresh operand
         * before each command. */
        write_scratch(CMD_SCRATCH_NUM, 0U);
        write_scratch(RESULT_SCRATCH_NUM, 0U);
        write_scratch(STATUS_SCRATCH_NUM, 0U);
        write_scratch(HANDSHAKE_SCRATCH, CMD_READY_TOKEN);

        /* Wait for the testbench's command */
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

        write_scratch(RESULT_SCRATCH_NUM, result);
        write_scratch(STATUS_SCRATCH_NUM, status);

        /* The handshake scratch is written last so the testbench sees completion
         * only after result and status are in place. */
        if (status == STATUS_OK) {
            write_scratch(HANDSHAKE_SCRATCH, result);
        } else {
            write_scratch(HANDSHAKE_SCRATCH, STATUS_UNKNOWN_OP);
        }

        /* Wait for the testbench to acknowledge */
        do {
            /* wait */
        } while (read_scratch(CMD_SCRATCH_NUM) != 0U);
    }

    test_pass(0);
}

/* secondary_main is not defined: the crt0 weak default parks non-boot harts in
 * WFI, so only the boot hart drives the scratch handshake. */
