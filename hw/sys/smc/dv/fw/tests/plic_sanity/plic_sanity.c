/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

#include <stdint.h>

#include "metal/cpu.h"
#include "metal/drivers/riscv_cpu.h"
#include "metal/interrupt.h"
#include "metal/watchdog.h"
#include "smc_io.h"
#include "smc_test.h"
#include "virt_console.h"

/* PLIC source 1, which is cpu_interrupts[0] and therefore ext_interrupts_i[0]:
 * source IDs are the interrupt line plus one because the RISC-V PLIC reserves
 * ID 0, and smc_base.sv:251 puts ext_interrupts at the bottom of the vector.
 *
 * Bit 0 is the only external interrupt this testbench drives: tb_top.sv ties
 * the upper ext_interrupts_i bits to zero and exposes bit 0 as
 * tb_ext_interrupt_0_i.
 */
#define TEST_INTERRUPT_ID 1

/* Bound on the wait for the second delivery, in polls of the claim count. The
 * pin is held high throughout, so once the first claim has been completed the
 * gateway forwards the source again as soon as it is unmasked; the bound only
 * has to outlast that handful of cycles and must expire before the bench's
 * verdict poll does. */
#define SECOND_DELIVERY_POLLS 20000u

static volatile uint32_t claimed_count;
/* The source's priority, read back after registration; a threshold equal to
 * it masks the source for this context. */
static volatile unsigned int mask_threshold;

/* Runs inside __metal_plic0_handler, between its claim read and its complete
 * write. The source is masked here because the pin stays high: returning with
 * it deliverable would re-deliver the interrupt before main can observe the
 * first completion. It is masked through the context threshold and not the
 * enable bit, because the PLIC honours a completion only for a source the
 * context has enabled: clearing the enable here would make the driver's
 * complete write a no-op and leave the gateway in flight. Returning, rather
 * than parking, is what lets the driver reach __metal_plic0_complete_interrupt. */
static void test_interrupt_handler(int id, void *priv) {
    struct metal_interrupt *plic = priv;
    simputshex32("Interrupt fired: ID = ", id);
    if (id != TEST_INTERRUPT_ID) {
        simputs("ERROR: claimed interrupt ID mismatch\n");
        simputshex32("  expected=", TEST_INTERRUPT_ID);
        simputs("\n");
        test_fail(0);
    }
    metal_interrupt_set_threshold(plic, mask_threshold);
    claimed_count++;
}

static void reset_plic_enable_registers() {
    simputs("Clearing PLIC registers\n");
    // this function goes through all the enable resets and clears them to avoid X prop
    for (uint64_t addr = SMC_TOP_SMC_CLUSTER_PLIC_CORE0_MEIP_ENABLE_BASE_ADDR(0);
         addr <= SMC_TOP_SMC_CLUSTER_PLIC_CORE3_SEIP_ENABLE_BASE_ADDR(5); addr += 4) {
        write_reg(addr, 0x0);
    }
    write_reg(SMC_TOP_SMC_CLUSTER_PLIC_CORE0_MEIP_THRESHOLD_BASE_ADDR, 0x0);
    write_reg(SMC_TOP_SMC_CLUSTER_PLIC_CORE0_SEIP_THRESHOLD_BASE_ADDR, 0x1);
    write_reg(SMC_TOP_SMC_CLUSTER_PLIC_CORE1_MEIP_THRESHOLD_BASE_ADDR, 0x2);
    write_reg(SMC_TOP_SMC_CLUSTER_PLIC_CORE1_SEIP_THRESHOLD_BASE_ADDR, 0x3);
    write_reg(SMC_TOP_SMC_CLUSTER_PLIC_CORE2_MEIP_THRESHOLD_BASE_ADDR, 0x4);
    write_reg(SMC_TOP_SMC_CLUSTER_PLIC_CORE2_SEIP_THRESHOLD_BASE_ADDR, 0x5);
    write_reg(SMC_TOP_SMC_CLUSTER_PLIC_CORE3_MEIP_THRESHOLD_BASE_ADDR, 0x6);
    write_reg(SMC_TOP_SMC_CLUSTER_PLIC_CORE3_SEIP_THRESHOLD_BASE_ADDR, 0x7);
}

int main(void) {

    const int hart = metal_cpu_get_current_hartid();
    struct metal_cpu *cpu = metal_cpu_get(hart);
    if (cpu == NULL) {
        simputs("Failed to get CPU\n");
        test_fail(0);
    }
    struct metal_interrupt *cpu_irq_ctrl = metal_cpu_interrupt_controller(cpu);
    if (cpu_irq_ctrl == NULL) {
        simputs("Failed to get CPU interrupt controller\n");
        test_fail(0);
    }

    simputs("Initializing CPU interrupt controller\n");
    metal_interrupt_init(cpu_irq_ctrl);

    simputs("Enabling CPU external interrupt\n");
    metal_interrupt_enable(cpu_irq_ctrl, METAL_INTERRUPT_ID_BASE);

    struct metal_interrupt *plic = metal_interrupt_get_controller(METAL_PLIC_CONTROLLER, hart);
    if (plic == NULL) {
        simputs("Failed to get PLIC controller\n");
        return -1;
    }

    // the interrupt enable function does a read-modify-write, which will break tests
    // that don't initialize registers with a default value
    // -> write zeros to clear all enable registers
    reset_plic_enable_registers();

    simputs("Initializing PLIC\n");
    metal_interrupt_init(plic);

    simputs("Registering PLIC handler\n");
    metal_interrupt_register_handler(plic, TEST_INTERRUPT_ID, test_interrupt_handler, plic);

    simputs("Enabling PLIC interrupt\n");
    metal_interrupt_enable(plic, TEST_INTERRUPT_ID);
    mask_threshold = metal_interrupt_get_priority(plic, TEST_INTERRUPT_ID);
    if (mask_threshold == 0u) {
        simputs("ERROR: source priority reads 0, so no threshold can mask it\n");
        test_fail(0);
    }
    metal_interrupt_set_threshold(plic, 0);

    __metal_interrupt_global_enable();

    write_scratch(0, 0xaaaaaaaa);
    simputs("Entering WFI loop\n");
    while (claimed_count < 1u) {
        __asm__ volatile("wfi");
    }

    /* The handler returned into the driver's complete write. A PLIC gateway
     * forwards no further interrupt for a source until that completion, so
     * with the pin still high a second delivery after unmasking the source is
     * the observable of the complete path; without it the count stays 1. */
    simputs("First claim completed; unmasking the source for a second delivery\n");
    metal_interrupt_set_threshold(plic, 0);
    for (uint32_t poll = 0; poll < SECOND_DELIVERY_POLLS && claimed_count < 2u; poll++) {
        __asm__ volatile("nop");
    }
    if (claimed_count < 2u) {
        simputs("ERROR: no second delivery after the first claim was completed\n");
        test_fail(0);
    }
    simputshex32("Claims completed and re-delivered: ", claimed_count);
    test_pass(0);
}

int other_main(int hartid) {
    while (true) {
        __asm__("wfi");
    }
}

int secondary_main(void) {
    int hartid = metal_cpu_get_current_hartid();
    if (hartid == 0) {
        return main();
    } else {
        return other_main(hartid);
    }
}
