/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

#include "metal/interrupt.h"
#include "metal/cpu.h"
#include "metal/drivers/riscv_cpu.h"
#include "smc_io.h"
#include "smc_test.h"
#include "atomic.h"
#include <stdio.h>
#include "virt_console.h"

#define MAILBOX_TEST_DATA (0xdeadbeefu)

_Atomic volatile int core_setup_done[4] = {0, 0, 0, 0};
// Sticky proof that mailbox_interrupt_handler ran and validated payload for this hart.
_Atomic volatile int handler_ran[4] = {0, 0, 0, 0};
char debug_msg[100][4];

void mailbox_interrupt_handler(int id, void *priv) {
    int hartid = metal_cpu_get_current_hartid();
    // PLIC source MAILBOX_INTERUPT_ID_BASE + 1 + n is mailbox n.
    int mailbox_id = id - (MAILBOX_INTERUPT_ID_BASE + 1);

    // Inbound WRITE_DATA is consumed on the outbound READ_DATA port.
    uint64_t mailbox_data =
        read_mailbox(mailbox_id, 0,
                     (SMC_TOP_SMC_MAILBOX_OUTBOUND_MAILBOX_0_READ_DATA_BASE_ADDR -
                      SMC_TOP_SMC_MAILBOX_OUTBOUND_MAILBOX_0_BASE_ADDR));

    simputshex16("Core:", hartid);
    simputshex16("Interrupted by Mailbox ID", mailbox_id);
    simputshex32("Mailbox Data:", (uint32_t)mailbox_data);

    // Validate that the interrupt came from the expected mailbox.
    // Hart N expects mailbox (N-1) mod 4 (C0 ← mb3). Use unsigned mod so C0 is 3, not -1.
    if (mailbox_id != (int)(((unsigned)hartid + 3u) % 4u)) {
        simputs("Unexpected mailbox interrupt!");
        simputshex16("hart:", hartid);
        simputshex16("mb:", mailbox_id);
        test_fail(hartid);
    }

    // Exact payload check — empty/wrong-port reads return 0xfeeddead.
    if ((uint32_t)mailbox_data != MAILBOX_TEST_DATA) {
        simputs("Mailbox data mismatch (expected 0xdeadbeef)!");
        simputshex32("Got:", (uint32_t)mailbox_data);
        test_fail(hartid);
    }

    // Flush the mailbox data
    simputs("Mailbox data validated, flushing mailbox...");
    write_mailbox(mailbox_id, 1,
                  (SMC_TOP_SMC_MAILBOX_OUTBOUND_MAILBOX_0_CTRL_BASE_ADDR -
                   SMC_TOP_SMC_MAILBOX_OUTBOUND_MAILBOX_0_BASE_ADDR),
                  0b11);

    // Clear the pending interrupt in the mailbox's IRQS register
    simputs("Clearing pending interrupt in mailbox IRQS register...");
    write_mailbox(mailbox_id, 1,
                  (SMC_TOP_SMC_MAILBOX_OUTBOUND_MAILBOX_0_IRQS_BASE_ADDR -
                   SMC_TOP_SMC_MAILBOX_OUTBOUND_MAILBOX_0_BASE_ADDR),
                  1);

    metal_atomic_swap(&handler_ran[hartid], 1);
}

static void reset_plic_enable_registers() {
    simputs("Clearing PLIC registers\n");
    for (uint64_t addr = SMC_TOP_SMC_CLUSTER_PLIC_CORE0_MEIP_ENABLE_BASE_ADDR(0);
         addr <= SMC_TOP_SMC_CLUSTER_PLIC_CORE3_SEIP_ENABLE_BASE_ADDR(6); addr += 4) {
        write_reg(addr, 0x0);
    }

    write_reg(SMC_TOP_SMC_CLUSTER_PLIC_CORE0_MEIP_THRESHOLD_BASE_ADDR, 0x0);
    write_reg(SMC_TOP_SMC_CLUSTER_PLIC_CORE0_SEIP_THRESHOLD_BASE_ADDR, 0x0);
    write_reg(SMC_TOP_SMC_CLUSTER_PLIC_CORE1_MEIP_THRESHOLD_BASE_ADDR, 0x0);
    write_reg(SMC_TOP_SMC_CLUSTER_PLIC_CORE1_SEIP_THRESHOLD_BASE_ADDR, 0x0);
    write_reg(SMC_TOP_SMC_CLUSTER_PLIC_CORE2_MEIP_THRESHOLD_BASE_ADDR, 0x0);
    write_reg(SMC_TOP_SMC_CLUSTER_PLIC_CORE2_SEIP_THRESHOLD_BASE_ADDR, 0x0);
    write_reg(SMC_TOP_SMC_CLUSTER_PLIC_CORE3_MEIP_THRESHOLD_BASE_ADDR, 0x0);
    write_reg(SMC_TOP_SMC_CLUSTER_PLIC_CORE3_SEIP_THRESHOLD_BASE_ADDR, 0x0);
}

void write_mailbox_int(int mailbox_id) {
    // Set Write Interrupt Request Threshold for mailbox (inbound write side)
    write_mailbox(mailbox_id, 1,
                  (SMC_TOP_SMC_MAILBOX_OUTBOUND_MAILBOX_0_WIRQT_BASE_ADDR -
                   SMC_TOP_SMC_MAILBOX_OUTBOUND_MAILBOX_0_BASE_ADDR),
                  0);

    // Enable write threshold interrupt for mailbox
    write_mailbox(mailbox_id, 1,
                  (SMC_TOP_SMC_MAILBOX_OUTBOUND_MAILBOX_0_IRQEN_BASE_ADDR -
                   SMC_TOP_SMC_MAILBOX_OUTBOUND_MAILBOX_0_BASE_ADDR),
                  1);

    // Write data to inbound WRITE_DATA (peer reads via outbound READ_DATA)
    write_mailbox(mailbox_id, 1,
                  (SMC_TOP_SMC_MAILBOX_OUTBOUND_MAILBOX_0_WRITE_DATA_BASE_ADDR -
                   SMC_TOP_SMC_MAILBOX_OUTBOUND_MAILBOX_0_BASE_ADDR),
                  MAILBOX_TEST_DATA);
}

int main(void) {

    avsbus_controller__AVS_INTERRUPT_MASK_t avsbus_mask_interrupts;
    avsbus_mask_interrupts.w = 0xffffffff;
    write_reg(SMC_TOP_SMC_AVSBUS_CONTROLLER_AVS_INTERRUPT_MASK_BASE_ADDR, avsbus_mask_interrupts.w);

    int hartid = metal_cpu_get_current_hartid();

    write_scratch(1, hartid);

    struct metal_interrupt *plic_controller;
    struct metal_cpu *cpu;
    struct metal_interrupt *cpu_controller;

    plic_controller = metal_interrupt_get_controller(METAL_PLIC_CONTROLLER, hartid);

    cpu = metal_cpu_get(hartid);
    cpu_controller = metal_cpu_interrupt_controller(cpu);

    metal_interrupt_init(cpu_controller);
    metal_interrupt_enable(cpu_controller, METAL_INTERRUPT_ID_BASE);
    metal_interrupt_enable(cpu_controller, METAL_INTERRUPT_ID_EXT);

    // If we are Core 0, set up PLIC, then send an interrupt to mailbox 0
    if (hartid == 0) {
        metal_interrupt_init(plic_controller);

        reset_plic_enable_registers();

        int interrupt_id = MAILBOX_INTERUPT_ID_BASE + 3 + 1; // Mailbox 3 interrupts core 0
        metal_interrupt_set_priority(plic_controller, interrupt_id, 1);
        if (metal_interrupt_register_handler(plic_controller, interrupt_id,
                                             mailbox_interrupt_handler, NULL) != 0) {
            simputs("Failed to register interrupt handler");
            test_fail(0);
        }
        metal_interrupt_enable(plic_controller, interrupt_id);

        __metal_interrupt_global_enable();

        // Atomically store, so other cores can see this setup is done
        metal_atomic_swap(&core_setup_done[0], 1);

        simputs("Core 0: Setup done, waiting for interrupts...");

        // Wait for other cores to set up
        while (metal_atomic_add(&core_setup_done[1], 0) == 0 ||
               metal_atomic_add(&core_setup_done[2], 0) == 0 ||
               metal_atomic_add(&core_setup_done[3], 0) == 0) {
            __asm__ volatile("" ::: "memory");
        }

        write_mailbox_int(0);
        simputs("Sent interrupt to mailbox 0\n");

        // Wait until the mailbox-3 handler has run and validated the payload.
        while (metal_atomic_add(&handler_ran[0], 0) == 0) {
            __asm__ volatile("wfi");
        }

        test_pass(hartid);
    } else {
        while (metal_atomic_add(&core_setup_done[0], 0) == 0) {
            __asm__ volatile("" ::: "memory");
        }

        // Expects an interrupt from mailbox hartid - 1, ie Core 1 expects from mailbox 0 (Core 0)
        int interrupt_id = MAILBOX_INTERUPT_ID_BASE + hartid;

        metal_interrupt_set_priority(plic_controller, interrupt_id, 1);
        if (metal_interrupt_register_handler(plic_controller, interrupt_id,
                                             mailbox_interrupt_handler, NULL) != 0) {
            snprintf(debug_msg[hartid], sizeof(debug_msg[hartid]),
                     "Core %d: Failed to register interrupt handler for mailbox %d\n", hartid,
                     hartid - 1);
            simputs(debug_msg[hartid]);
            test_fail(hartid);
        }
        metal_interrupt_enable(plic_controller, interrupt_id);

        __metal_interrupt_global_enable();

        snprintf(debug_msg[hartid], sizeof(debug_msg[hartid]),
                 "Core %d: Setup done, waiting for interrupt...\n", hartid);
        simputs(debug_msg[hartid]);

        metal_atomic_swap(&core_setup_done[hartid], 1);

        // Wait for this core's inbound mailbox interrupt + data validation.
        while (metal_atomic_add(&handler_ran[hartid], 0) == 0) {
            __asm__ volatile("wfi");
        }

        write_mailbox_int(hartid);
        snprintf(debug_msg[hartid], sizeof(debug_msg[hartid]), "Sent interrupt to mailbox %d\n",
                 hartid);
        simputs(debug_msg[hartid]);

        // Stay alive so the next core in the ring can complete.
        while (1) {
            __asm__ volatile("wfi");
        }
    }
}

int secondary_main(void) {
    return main();
}
