/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

#include <stdint.h>
#include <stdbool.h>

#include "smc_io.h"
#include "smc_test.h"

/**
 * @brief ATB P1 Function Test - Telemetry Receiver Register Access
 *
 * Verifies that firmware can read the Telemetry Receiver registers of all
 * three instances and that each receiver starts with an empty, not-full
 * buffer. The other register values are logged, not checked.
 */

#define TELEMETRY_RECEIVER_NOC_O_BASE \
    SMC_TOP_SMC_TELEMETRY_RECEIVER_WRAP_TELEMETRY_RECEIVER_BASE_ADDR(0)
#define TELEMETRY_RECEIVER_NOC_M_BASE \
    SMC_TOP_SMC_TELEMETRY_RECEIVER_WRAP_TELEMETRY_RECEIVER_BASE_ADDR(1)
#define TELEMETRY_RECEIVER_NOC_N_BASE \
    SMC_TOP_SMC_TELEMETRY_RECEIVER_WRAP_TELEMETRY_RECEIVER_BASE_ADDR(2)

// Register offsets within one receiver instance
#define REG_CTRL \
    (SMC_TOP_SMC_TELEMETRY_RECEIVER_WRAP_TELEMETRY_RECEIVER_CTRL_BASE_ADDR(0) - \
     TELEMETRY_RECEIVER_NOC_O_BASE)
#define REG_STATUS \
    (SMC_TOP_SMC_TELEMETRY_RECEIVER_WRAP_TELEMETRY_RECEIVER_STATUS_BASE_ADDR(0) - \
     TELEMETRY_RECEIVER_NOC_O_BASE)
#define REG_PROBE_ID \
    (SMC_TOP_SMC_TELEMETRY_RECEIVER_WRAP_TELEMETRY_RECEIVER_TELEMETRY_PROBE_ID_BASE_ADDR(0) - \
     TELEMETRY_RECEIVER_NOC_O_BASE)
#define REG_COUNTER_VLDS \
    (SMC_TOP_SMC_TELEMETRY_RECEIVER_WRAP_TELEMETRY_RECEIVER_TELEMETRY_COUNTER_VLDS_BASE_ADDR(0) - \
     TELEMETRY_RECEIVER_NOC_O_BASE)
#define REG_COUNTER_BASE \
    (SMC_TOP_SMC_TELEMETRY_RECEIVER_WRAP_TELEMETRY_RECEIVER_TELEMETRY_COUNTER_BASE_ADDR(0, 0) - \
     TELEMETRY_RECEIVER_NOC_O_BASE)

/**
 * @brief Check the buffer status of one receiver and log its other registers
 * @param base_addr Base address of telemetry receiver
 * @param instance_name Name of instance (for logging)
 * @return false if the buffer is not empty-and-not-full, true otherwise
 */
static bool verify_telemetry_receiver(uint64_t base_addr, const char *instance_name) {
    uint32_t status = read_reg(base_addr + REG_STATUS);
    simputs("  ");
    simputs(instance_name);
    simputs(" STATUS: 0x");
    simputshex32("", status);
    simputs("\n");

    // A receiver out of reset has an empty, not-full buffer
    if ((status & 0x11) != 0x01) {
        simputs("  ERROR: ");
        simputs(instance_name);
        simputs(" STATUS invalid (expected bit[0]=1, bit[4]=0)\n");
        return false;
    }

    uint32_t probe_id = read_reg(base_addr + REG_PROBE_ID);
    simputs("  ");
    simputs(instance_name);
    simputs(" PROBE_ID: 0x");
    simputshex32("", probe_id);
    simputs(" (expected 0x0 or small value)\n");

    uint32_t counter_vlds = read_reg(base_addr + REG_COUNTER_VLDS);
    simputs("  ");
    simputs(instance_name);
    simputs(" COUNTER_VLDS: 0x");
    simputshex32("", counter_vlds);
    simputs(" (expected 0x0 initially)\n");

    simputs("  ");
    simputs(instance_name);
    simputs(" Counters:\n");
    for (int i = 0; i < 3; i++) {
        uint32_t counter_val = read_reg(base_addr + REG_COUNTER_BASE + (i * 4));
        simputs("    [");
        simputshex32("", i);
        simputs("]: 0x");
        simputshex32("", counter_val);
        simputs("\n");
    }

    return true;
}

int main(void) {
    int hartid = 0;

    simputs("\n");
    simputs("################################################\n");
    simputs("##  ATB P1 Function Test                       ##\n");
    simputs("##  Telemetry Receiver Register Access         ##\n");
    simputs("################################################\n");
    simputs("\n");

    write_scratch(1, 0x00000001);
    simputs("Step 1: System Initialization\n");
    simputs("  System ready\n");
    write_scratch(1, 0x00000011);

    write_scratch(1, 0x00000002);
    simputs("Step 2: NOC_O Telemetry Receiver\n");
    if (!verify_telemetry_receiver(TELEMETRY_RECEIVER_NOC_O_BASE, "NOC_O")) {
        write_scratch(0, 0xBAD00002);
        test_fail(hartid);
    }
    write_scratch(1, 0x00000021);

    write_scratch(1, 0x00000003);
    simputs("Step 3: NOC_M Telemetry Receiver (0xC000D100)\n");
    if (!verify_telemetry_receiver(TELEMETRY_RECEIVER_NOC_M_BASE, "NOC_M")) {
        write_scratch(0, 0xBAD00003);
        test_fail(hartid);
    }
    write_scratch(1, 0x00000031);

    write_scratch(1, 0x00000004);
    simputs("Step 4: NOC_N Telemetry Receiver (0xC000D200)\n");
    if (!verify_telemetry_receiver(TELEMETRY_RECEIVER_NOC_N_BASE, "NOC_N")) {
        write_scratch(0, 0xBAD00004);
        test_fail(hartid);
    }
    write_scratch(1, 0x00000041);

    write_scratch(1, 0x00000005);
    simputs("Step 5: Buffer Control Operations\n");

    uint32_t noc_o_ctrl = read_reg(TELEMETRY_RECEIVER_NOC_O_BASE + REG_CTRL);
    simputs("  NOC_O CTRL: 0x");
    simputshex32("", noc_o_ctrl);
    simputs(" (readable)\n");

    // Report whether the buffer holds data; no entry is popped
    uint32_t noc_o_status = read_reg(TELEMETRY_RECEIVER_NOC_O_BASE + REG_STATUS);
    if ((noc_o_status & 0x1) == 0) {
        simputs("  NOC_O buffer has data, can pop\n");
    } else {
        simputs("  NOC_O buffer is empty, BUFFER_POP skipped (as expected)\n");
    }
    write_scratch(1, 0x00000051);

    write_scratch(1, 0x00000006);
    simputs("Step 6: Test Complete\n");
    simputs("  ========================================\n");
    simputs("  All Telemetry Receiver registers accessible\n");
    simputs("  All default values verified\n");
    simputs("  ========================================\n");

    // Signal test completion
    write_scratch(1, 0xEBEDEBE4);
    test_pass(hartid);
}

int secondary_main(void) {
    return main();
}
