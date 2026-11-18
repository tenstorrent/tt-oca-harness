/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/*
 * OCCP Park Test - controller half
 *
 * Sends a probe with the short probe timeout, which the live target must answer, then writes
 * one block into target SMC SRAM as the last command before the park, so that it is still
 * dirty in the target's D-cache. It reports to the testbench and waits. The testbench asks
 * the target ROM to park hart 0 and, once it has, releases this image to send the same probe
 * again. A parked target must not answer it.
 *
 * Controller scratch handshake with the testbench:
 *   scratch 5  the second probe's OCCP return code
 *   scratch 6  phase: PARK_PHASE_WRITTEN after the first probe and the write, then
 *              PARK_PHASE_ANSWERED or PARK_PHASE_UNANSWERED after the second probe;
 *              PARK_PHASE_FAILED on any setup failure
 *   scratch 7  the testbench writes PARK_GO to release the second probe
 */

#include "occp_test_common.h"
#include "smc_defines.h"
#include "smc_test.h"

#define PARK_SCRATCH_RESULT 5
#define PARK_SCRATCH_PHASE 6
#define PARK_SCRATCH_GO 7

#define PARK_PHASE_WRITTEN 0x50415231u    /* "PAR1" */
#define PARK_PHASE_ANSWERED 0x50415232u   /* "PAR2" */
#define PARK_PHASE_UNANSWERED 0x50415233u /* "PAR3" */
#define PARK_PHASE_FAILED 0x5041523Fu     /* "PAR?" */
#define PARK_GO 0x474F2121u               /* "GO!!" */

/* Must match smc_rom_park_request_test.py. */
#define PARK_WRITE_ADDR 0xC0080000ULL
#define PARK_WRITE_LEN 256
#define PARK_PROBE_TIMEOUT 2000

static __attribute__((noreturn)) void park_test_fail(const char *why) {
    simputs(why);
    write_scratch(PARK_SCRATCH_PHASE, PARK_PHASE_FAILED);
    test_fail(0);
}

int main(void) {
    static test_context_t ctx = {0};
    static uint8_t block[PARK_WRITE_LEN];
    uint32_t version = 0;

    init_test(0);
    if (!initialize_interface(&ctx)) park_test_fail("FAIL: interface initialization\n");

    if (occp_send_get_version_command(&ctx, ctx.slave_addr, &version) != OCCP_SUCCESS)
        park_test_fail("FAIL: GET_VERSION before the write\n");

    const int command_timeout = ctx.timeout;
    ctx.timeout = PARK_PROBE_TIMEOUT;
    if (occp_send_get_version_command(&ctx, ctx.slave_addr, &version) != OCCP_SUCCESS)
        park_test_fail("FAIL: the live target did not answer within the probe timeout\n");
    ctx.timeout = command_timeout;

    for (int i = 0; i < PARK_WRITE_LEN; i++) block[i] = (uint8_t)(0x11 + i * 0x5B);
    if (occp_send_write_command(&ctx, ctx.slave_addr, PARK_WRITE_ADDR, block, sizeof(block)) !=
        OCCP_SUCCESS)
        park_test_fail("FAIL: OCCP write into target SRAM\n");

    simputs("Write complete; waiting for the testbench to park the target\n");
    write_scratch(PARK_SCRATCH_PHASE, PARK_PHASE_WRITTEN);
    while (read_scratch(PARK_SCRATCH_GO) != PARK_GO) {
    }

    ctx.timeout = PARK_PROBE_TIMEOUT;
    int probe = occp_send_get_version_command(&ctx, ctx.slave_addr, &version);
    simputshex32("Probe after park returned: ", (uint32_t)probe);
    write_scratch(PARK_SCRATCH_RESULT, (uint32_t)probe);
    write_scratch(PARK_SCRATCH_PHASE,
                  probe == OCCP_SUCCESS ? PARK_PHASE_ANSWERED : PARK_PHASE_UNANSWERED);
    for (;;) __asm__ volatile("wfi");
}

int secondary_main(void) {
    if (metal_cpu_get_current_hartid() == 0) return main();
    for (;;) __asm__ volatile("wfi");
}
