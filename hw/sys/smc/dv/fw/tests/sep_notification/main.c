/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/*
 * SEP Firmware-Initiated Notification Test
 *
 * Tests the reverse notification path: SMC firmware acts as the event
 * source and emits a sequence of N event tokens to a handshake scratch
 * register, pausing after each token until the testbench acknowledges.
 *
 * Spec basis: OCAH Specification §Crypto Key Manager — the KM can send
 * asynchronous status/progress notifications upstream.  This test
 * exercises the analogous FW→TB notification path using scratch registers
 * as the transport, verifying that each event is delivered and acknowledged
 * in order before the next is emitted.
 *
 * Protocol (scratch registers):
 *   scratch[HANDSHAKE_SCRATCH] = NOTIFY_READY        (FW signals it is alive)
 *   scratch[ACK_SCRATCH]       = TRIGGER             (TB triggers event sequence)
 *
 *   For each event i in 0 .. N_EVENTS-1:
 *     scratch[HANDSHAKE_SCRATCH] = EVENT_BASE + i    (FW emits event i)
 *     scratch[ACK_SCRATCH]       = TRIGGER + i + 1  (TB acknowledges event i)
 *
 *   scratch[HANDSHAKE_SCRATCH] = NOTIFY_DONE         (FW signals all done)
 *   scratch[0]                 = TEST_PASS           (FW signals test result)
 *
 * NOTE: secondary_main is not defined here.  The weak default in crt0.S
 * routes only the boot hart to main(); non-boot harts spin in WFI.
 */

#include <stdint.h>
#include <stdbool.h>

#include "smc_defines.h"
#include "smc_test.h"

#define N_EVENTS 4

#define HANDSHAKE_SCRATCH 1
#define ACK_SCRATCH 2

/* Token constants — must match testbench */
#define NOTIFY_READY 0xA5000001U
#define EVENT_BASE 0xA5010000U /* event i → EVENT_BASE + i          */
#define TRIGGER 0xFEED0000U    /* TB sends TRIGGER to ACK_SCRATCH    */
                               /* ack for event i → TRIGGER + i + 1 */
#define NOTIFY_DONE 0xA5FFFFFFU

int main(void) {
    /* Signal that firmware is alive and ready for the trigger */
    write_scratch(ACK_SCRATCH, 0U);
    write_scratch(HANDSHAKE_SCRATCH, NOTIFY_READY);

    /* Wait for testbench to write TRIGGER to ACK_SCRATCH */
    uint32_t expected_ack = TRIGGER;
    uint32_t ack;
    do {
        ack = read_scratch(ACK_SCRATCH);
    } while (ack != expected_ack);

    /* Emit N_EVENTS events, each gated on the previous ack */
    for (uint32_t i = 0; i < N_EVENTS; i++) {
        /* Emit event i */
        write_scratch(HANDSHAKE_SCRATCH, EVENT_BASE + i);

        /* Advance to next expected ack and wait */
        expected_ack = TRIGGER + i + 1U;
        do {
            ack = read_scratch(ACK_SCRATCH);
        } while (ack != expected_ack);
    }

    /* Signal completion */
    write_scratch(HANDSHAKE_SCRATCH, NOTIFY_DONE);

    test_pass(0);

    while (true) {
        __asm__("wfi");
    }
    return 0;
}

/* secondary_main is not defined here: the crt0 weak default routes only the
 * boot hart to main() and parks the other harts in WFI. */
