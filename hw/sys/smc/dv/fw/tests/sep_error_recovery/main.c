/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/*
 * SEP Error Injection and Recovery Test Firmware
 *
 * Tests that SMC firmware correctly detects invalid operation codes, returns
 * an error indicator in the handshake scratch register, and recovers to handle
 * subsequent valid requests normally.
 *
 * Spec basis: OCAH Specification §Crypto Key Manager — illegal commands trigger
 * an abort/illegal-message response; the protocol must recover and continue
 * handling subsequent valid requests.
 *
 * Protocol (same wire format as sep_service_req):
 *   scratch[HANDSHAKE_SCRATCH] = CMD_READY_TOKEN       (FW signals ready)
 *   scratch[CMD_SCRATCH_NUM]   = {op_code[7:0], seq[15:8], 0[31:16]}
 *   scratch[DATA_SCRATCH_NUM]  = operand data (32-bit)
 *
 *   On SUCCESS (known op_code):
 *     scratch[RESULT_SCRATCH_NUM]= computed result
 *     scratch[STATUS_SCRATCH_NUM]= STATUS_OK
 *     scratch[HANDSHAKE_SCRATCH] = computed result   (TB reads directly)
 *
 *   On ERROR (unknown op_code):
 *     scratch[RESULT_SCRATCH_NUM]= 0
 *     scratch[STATUS_SCRATCH_NUM]= STATUS_UNKNOWN_OP
 *     scratch[HANDSHAKE_SCRATCH] = STATUS_UNKNOWN_OP  (TB reads directly;
 *                                                       distinct from any result)
 *
 *   scratch[CMD_SCRATCH_NUM]   = 0                    (TB acknowledges)
 *   scratch[0]                 = TEST_PASS / TEST_FAIL
 *
 * Operation codes:
 *   OP_NOT       (0x01): result = ~data
 *   OP_XOR_MAGIC (0x02): result = data ^ 0xDEADBEEF
 *   OP_BYTE_REV  (0x03): result = byte-reversed data
 *   OP_ROT_L8    (0x04): result = rotate_left(data, 8)
 *   OP_POPCOUNT  (0x05): result = population count of data
 *   All others         : STATUS_UNKNOWN_OP written to HANDSHAKE_SCRATCH
 *
 * NOTE: secondary_main is not defined here.  The weak default in crt0.S
 * routes only the boot hart to main(); non-boot harts spin in WFI,
 * preventing multi-core write races on the shared scratch registers.
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
        /* Signal ready. DATA_SCRATCH_NUM is not cleared: the testbench writes fresh
         * operand data before writing the CMD scratch. */
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

        write_scratch(RESULT_SCRATCH_NUM, result);
        write_scratch(STATUS_SCRATCH_NUM, status);

        /* Write to HANDSHAKE_SCRATCH last so TB can detect completion.
         * On error, write STATUS_UNKNOWN_OP (distinct sentinel ≠ any valid result
         * and ≠ CMD_READY_TOKEN) so the TB can identify the error path via
         * dut.scratch_1 without any AXI read. */
        if (status == STATUS_OK) {
            write_scratch(HANDSHAKE_SCRATCH, result);
        } else {
            write_scratch(HANDSHAKE_SCRATCH, STATUS_UNKNOWN_OP);
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
