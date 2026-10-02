/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/*
 * SEP Firmware-Initiated Notification Test
 *
 * Verifies the firmware-to-testbench notification path: after a testbench trigger, SMC
 * firmware emits a sequence of event tokens through a handshake scratch register, waits for
 * the testbench to acknowledge each one before it emits the next, and then signals done.
 */

#include <stdint.h>

#include "smc_defines.h"
#include "smc_test.h"

#define N_EVENTS 4

#define HANDSHAKE_SCRATCH 1
#define ACK_SCRATCH 2

/* Token values must match the testbench */
#define NOTIFY_READY 0xA5000001U
#define EVENT_BASE 0xA5010000U /* event i is EVENT_BASE + i */
#define TRIGGER 0xFEED0000U    /* the ack for event i is TRIGGER + i + 1 */
#define NOTIFY_DONE 0xA5FFFFFFU

int main(void) {
    /* Signal that the firmware is ready for the trigger */
    write_scratch(ACK_SCRATCH, 0U);
    write_scratch(HANDSHAKE_SCRATCH, NOTIFY_READY);

    /* Wait for the testbench trigger */
    uint32_t expected_ack = TRIGGER;
    uint32_t ack;
    do {
        ack = read_scratch(ACK_SCRATCH);
    } while (ack != expected_ack);

    /* Emit N_EVENTS events, each gated on the previous ack */
    for (uint32_t i = 0; i < N_EVENTS; i++) {
        write_scratch(HANDSHAKE_SCRATCH, EVENT_BASE + i);

        /* Wait for the acknowledge of event i */
        expected_ack = TRIGGER + i + 1U;
        do {
            ack = read_scratch(ACK_SCRATCH);
        } while (ack != expected_ack);
    }

    write_scratch(HANDSHAKE_SCRATCH, NOTIFY_DONE);

    test_pass(0);
}

/* No secondary_main: the crt0.S default runs main() on the boot hart only, so no other hart
 * writes the scratch registers the protocol uses. */
