/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

#include "metal/interrupt.h"
#include "metal/cpu.h"
#include "metal/drivers/riscv_cpu.h"
#include "smc_io.h"
#include "smc_test.h"
#include "virt_console.h"
#define NUM_SMC_MAILBOXES (32)

int n_interrupts;

void mailbox_interrupt_handler(int id, void *priv) {

    uint32_t mailbox_num = id - MAILBOX_INTERUPT_ID_BASE - 1;
    char debug_msg[50];
    snprintf(debug_msg, sizeof(debug_msg), "Mailbox Interrupt ID: %d, Mailbox #: %d\n", id,
             mailbox_num);
    simputs(debug_msg);

    simputs("Mailbox data validated, flushing mailbox...");
    write_mailbox(mailbox_num, 0,
                  (SMC_TOP_SMC_MAILBOX_OUTBOUND_MAILBOX_0_CTRL_BASE_ADDR -
                   SMC_TOP_SMC_MAILBOX_OUTBOUND_MAILBOX_0_BASE_ADDR),
                  0b11);
    write_mailbox(mailbox_num, 1,
                  (SMC_TOP_SMC_MAILBOX_OUTBOUND_MAILBOX_0_CTRL_BASE_ADDR -
                   SMC_TOP_SMC_MAILBOX_OUTBOUND_MAILBOX_0_BASE_ADDR),
                  0b11);

    simputs("Clearing pending interrupt in mailbox IRQS register...");
    write_mailbox(mailbox_num, 0,
                  (SMC_TOP_SMC_MAILBOX_OUTBOUND_MAILBOX_0_IRQS_BASE_ADDR -
                   SMC_TOP_SMC_MAILBOX_OUTBOUND_MAILBOX_0_BASE_ADDR),
                  0b11);
    write_mailbox(mailbox_num, 1,
                  (SMC_TOP_SMC_MAILBOX_OUTBOUND_MAILBOX_0_IRQS_BASE_ADDR -
                   SMC_TOP_SMC_MAILBOX_OUTBOUND_MAILBOX_0_BASE_ADDR),
                  0b11);

    n_interrupts++;
}

static void reset_plic_enable_registers() {
    simputs("Clearing PLIC registers\n");
    for (uint64_t addr = SMC_TOP_SMC_CLUSTER_PLIC_CORE0_MEIP_ENABLE_BASE_ADDR(0);
         addr <= SMC_TOP_SMC_CLUSTER_PLIC_CORE3_SEIP_ENABLE_BASE_ADDR(5); addr += 4) {
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

int main(void) {

    int hartid = metal_cpu_get_current_hartid();

    struct metal_interrupt *plic_controller;
    struct metal_cpu *cpu;
    struct metal_interrupt *cpu_controller;

    plic_controller = metal_interrupt_get_controller(METAL_PLIC_CONTROLLER, hartid);

    cpu = metal_cpu_get(0);
    cpu_controller = metal_cpu_interrupt_controller(cpu);

    metal_interrupt_init(cpu_controller);
    metal_interrupt_enable(cpu_controller, METAL_INTERRUPT_ID_BASE);

    metal_interrupt_register_handler(cpu_controller, METAL_INTERRUPT_ID_EXT,
                                     mailbox_interrupt_handler, NULL);

    metal_interrupt_init(plic_controller);

    reset_plic_enable_registers();

    for (uint32_t i = 0; i < NUM_SMC_MAILBOXES; i++) {

        int interrupt_id = MAILBOX_INTERUPT_ID_BASE + i + 1;
        metal_interrupt_set_priority(plic_controller, interrupt_id, 1);
        if (metal_interrupt_register_handler(plic_controller, interrupt_id,
                                             mailbox_interrupt_handler, NULL) != 0) {
            simputs("Failed to register interrupt handler\n");
            test_fail(0);
        } else {
            char debug_msg[50];
            snprintf(debug_msg, sizeof(debug_msg), "Got Registered interrupt handler for ID: %d\n",
                     interrupt_id);
            simputs(debug_msg);
        }
        metal_interrupt_enable(plic_controller, interrupt_id);
    }

    __metal_interrupt_global_enable();

    n_interrupts = 0;

    // Tell the testbench that interrupts are armed
    write_scratch(14, 1);

    while (n_interrupts < NUM_SMC_MAILBOXES) {
        __asm__("wfi");

        // Report the handled count to the testbench
        write_scratch(15, n_interrupts);
    }

    test_pass(hartid);

    return 0;
}

int other_main(int hartid) {
    while (true) {
        __asm__("wfi");
    }
}

int secondary_main(void) {
    int hartid = metal_cpu_get_current_hartid();

    if (hartid == 0) {
        __asm__("fence rw,w");

        return main();
    } else {
        return other_main(hartid);
    }
}
