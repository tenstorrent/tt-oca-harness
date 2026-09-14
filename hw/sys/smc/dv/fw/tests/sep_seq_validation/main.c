/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/*
 * SEP Sequence Number Validation Test Firmware
 *
 * Tests that SMC firmware validates the sequence number field in each
 * service request and rejects out-of-order or replayed requests with a
 * STATUS_SEQ_ERROR sentinel, while continuing to handle subsequent correctly-
 * sequenced requests.
 *
 * Spec basis: OCAH Specification §Crypto Key Manager — the KM command message
 * format encodes a sequence_number[7:0] in the header, enabling detection of
 * replayed or lost messages.  This test exercises analogous sequence-number
 * enforcement on the SMC side using scratch registers as the transport.
 *
 * Protocol (same wire format as sep_service_req):
 *   scratch[HANDSHAKE_SCRATCH] = CMD_READY_TOKEN          (FW signals ready)
 *   scratch[CMD_SCRATCH_NUM]   = {op_code[7:0], seq[15:8], 0[31:16]}
 *   scratch[DATA_SCRATCH_NUM]  = operand data
 *
 *   On correct sequence number:
 *     scratch[HANDSHAKE_SCRATCH] = computed result        (FW signals done)
 *
 *   On wrong sequence number (skipped or replayed):
 *     scratch[HANDSHAKE_SCRATCH] = STATUS_SEQ_ERROR       (error sentinel)
 *     expected_seq is NOT advanced — TB must retry with the correct seq
 *
 *   scratch[CMD_SCRATCH_NUM]   = 0                        (TB acknowledges)
 *
 * NOTE: secondary_main is not defined here.  The weak default in crt0.S
 * routes only the boot hart to main(); non-boot harts spin in WFI.
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

#define OP_NOT 0x01U
#define OP_XOR_MAGIC 0x02U
#define OP_BYTE_REV 0x03U
#define OP_ROT_L8 0x04U
#define OP_POPCOUNT 0x05U

#define XOR_MAGIC 0xDEADBEEFU

#define STATUS_OK 0x00000000U
#define STATUS_UNKNOWN_OP 0xE0000001U
#define STATUS_SEQ_ERROR 0xE0000002U

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
    uint32_t expected_seq = 0U; /* monotonically increasing, wraps mod 256 */

    for (uint32_t req = 0; req < NUM_REQUESTS; req++) {
        /* Signal ready for the next request */
        write_scratch(CMD_SCRATCH_NUM, 0U);
        write_scratch(RESULT_SCRATCH_NUM, 0U);
        write_scratch(STATUS_SCRATCH_NUM, 0U);
        write_scratch(HANDSHAKE_SCRATCH, CMD_READY_TOKEN);

        /* Wait for testbench to write the command header */
        uint32_t cmd_hdr;
        do {
            cmd_hdr = read_scratch(CMD_SCRATCH_NUM);
        } while (cmd_hdr == 0U);

        /* Extract fields from command header */
        uint32_t op_code = cmd_hdr & 0xFFU;
        uint32_t seq = (cmd_hdr >> 8) & 0xFFU;
        uint32_t data = read_scratch(DATA_SCRATCH_NUM);

        /* Validate sequence number */
        if (seq != (expected_seq & 0xFFU)) {
            /* Sequence error: reject request, do NOT advance expected_seq.
             * Write STATUS_SEQ_ERROR to both STATUS scratch and HANDSHAKE
             * scratch so the TB can detect the error via dut.scratch_1. */
            write_scratch(RESULT_SCRATCH_NUM, 0U);
            write_scratch(STATUS_SCRATCH_NUM, STATUS_SEQ_ERROR);
            write_scratch(HANDSHAKE_SCRATCH, STATUS_SEQ_ERROR);
        } else {
            /* Correct sequence: dispatch and advance counter */
            expected_seq++;

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

            if (status == STATUS_OK) {
                write_scratch(HANDSHAKE_SCRATCH, result);
            } else {
                write_scratch(HANDSHAKE_SCRATCH, STATUS_UNKNOWN_OP);
            }
        }

        /* Wait for testbench to acknowledge */
        do {
            /* wait */
        } while (read_scratch(CMD_SCRATCH_NUM) != 0U);
    }

    test_pass(0);

    while (true) {
        __asm__("wfi");
    }
    return 0;
}

/* secondary_main is not defined here: the crt0 weak default routes only the
 * boot hart to main() and parks the other harts in WFI. */
