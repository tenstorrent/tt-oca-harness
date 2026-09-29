/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

#include <stdint.h>

#include "i2c_wrap.h"
#include "metal/cpu.h"
#include "metal/drivers/riscv_cpu.h"
#include "metal/interrupt.h"
#include "metal/watchdog.h"
#include "smc_io.h"
#include "smc_test.h"
#include "virt_console.h"

/* PLIC source 1, which is cpu_interrupts[0] and therefore ext_interrupts_i[0]:
 * the SMC interrupt-vector map (doc/interrupts.adoc, "SMC CPU Interrupt Vector
 * Map") places the external interrupts at the bottom of the vector and
 * defines the PLIC source ID as the vector bit index plus one, because the
 * PLIC reserves ID 0 for "no interrupt". */
#define TEST_INTERRUPT_ID 1
/* The bench drives ext_interrupts_i[16:0] together, PLIC sources 1-17. */
#define EXT_SOURCE_COUNT 17u
/* I2C controller 0 is peripheral_interrupts_o[23], cpu_interrupts[279], so
 * PLIC source 280: a source the firmware raises itself through INTR_TEST. */
#define I2C0_SOURCE 280
#define I2C0_INDEX 0
/* Priorities and thresholds are three bits wide: threshold 7 masks every
 * source, and every threshold below it passes a source at priority 7. */
#define THRESHOLD_MASK_ALL 7u
#define THRESHOLD_MAX_CLAIMABLE 6u
#define MAX_PRIORITY 7u
/* Bound on the wait for a delivery, in polls of the claim count. The pins are
 * held high throughout, so once a source is enabled the gateway forwards it
 * within a few cycles; the bound only exists so a broken path fails instead
 * of hanging, and 20000 polls (~ms) is far past any real latency. */
#define DELIVERY_POLLS 20000u

static volatile uint32_t claimed_count;
static volatile int last_claimed_id;
/* Bit n set once source n has been claimed (n <= 17); bit 31 for I2C0. */
#define I2C0_CLAIMED_BIT (1u << 31)
static volatile uint32_t claimed_mask;
/* The one source the handler may see; 0 accepts any registered source. */
static volatile int expected_id;

/* The metal driver caps priorities below the maximum, so the register is
 * written directly to reach the top value the hardware carries. */
static void set_priority(int id, uint32_t priority) {
    write_reg(SMC_TOP_SMC_CLUSTER_PLIC_PRIORITY_BASE_ADDR(id), priority);
}

static int registered(int id) {
    return (id >= 1 && id <= (int)EXT_SOURCE_COUNT) || id == I2C0_SOURCE;
}

/* Runs inside __metal_plic0_handler, between its claim read and its complete
 * write. The pins stay high, so the source is masked here by raising the
 * threshold rather than disabled: the PLIC ignores a completion for a source
 * that is disabled when the completion arrives, and the gateway would then
 * never forward the source again. main lowers the threshold when it is ready
 * for the next claim. */
static void test_interrupt_handler(int id, void *priv) {
    struct metal_interrupt *plic = priv;
    if (!registered(id) || (expected_id != 0 && id != expected_id)) {
        simputshex32("ERROR: unexpected claimed interrupt ID ", id);
        simputshex32(" expected=", (uint32_t)expected_id);
        simputs("\n");
        test_fail(0);
    }
    metal_interrupt_set_threshold(plic, THRESHOLD_MASK_ALL);
    claimed_mask |= (id == I2C0_SOURCE) ? I2C0_CLAIMED_BIT : (1u << id);
    last_claimed_id = id;
    claimed_count++;
}

static void reset_plic_enable_registers(void) {
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

static void wait_claims(uint32_t target, const char *what) {
    for (uint32_t poll = 0; poll < DELIVERY_POLLS && claimed_count < target; poll++) {
        __asm__ volatile("nop");
    }
    if (claimed_count < target) {
        simputs("ERROR: no delivery for ");
        simputs(what);
        simputs("\n");
        test_fail(0);
    }
}

/* One claim of `id`, the only enabled source, with the context threshold at
 * `threshold` and the source at priority 7. The source is disabled again only
 * after the handler has returned, so its completion is honoured. */
static void claim_one(struct metal_interrupt *plic, int id, uint32_t threshold) {
    uint32_t before = claimed_count;
    expected_id = id;
    set_priority(id, MAX_PRIORITY);
    metal_interrupt_set_threshold(plic, (unsigned int)threshold);
    metal_interrupt_enable(plic, id);
    wait_claims(before + 1u, "the single enabled source above the threshold");
    metal_interrupt_disable(plic, id);
}

/* A claim read with nothing pending returns source 0 and needs no completion. */
static void claim_none(uint32_t threshold) {
    write_reg(SMC_TOP_SMC_CLUSTER_PLIC_CORE0_MEIP_THRESHOLD_BASE_ADDR, threshold);
    uint32_t id = read_reg(SMC_TOP_SMC_CLUSTER_PLIC_CORE0_MEIP_CLAIM_COMPLETE_BASE_ADDR);
    if (id != 0u) {
        simputshex32("ERROR: idle claim read returned source ", id);
        simputs("\n");
        test_fail(0);
    }
}

int main(void) {

    const int hart = metal_cpu_get_current_hartid();
    struct metal_cpu *cpu = metal_cpu_get(hart);
    if (cpu == NULL) {
        simputs("Failed to get CPU handle\n");
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
    expected_id = TEST_INTERRUPT_ID;
    metal_interrupt_enable(plic, TEST_INTERRUPT_ID);
    if (metal_interrupt_get_priority(plic, TEST_INTERRUPT_ID) == 0u) {
        simputs("ERROR: source priority reads 0, so no threshold can pass it\n");
        test_fail(0);
    }
    metal_interrupt_set_threshold(plic, 0);
    __metal_interrupt_global_enable();

    write_scratch(0, 0xaaaaaaaa);
    simputs("Entering WFI loop\n");
    while (claimed_count < 1u) {
        __asm__ volatile("wfi");
    }
    simputshex32("Interrupt fired: ID = ", (uint32_t)last_claimed_id);

    /* The handler returned into the driver's complete write. A PLIC gateway
     * forwards no further interrupt for a source until that completion, so
     * with the pin still high a second delivery after unmasking the source is
     * the observable of the complete path; without it the count stays 1. */
    simputs("First claim completed; unmasking the source for a second delivery\n");
    metal_interrupt_set_threshold(plic, 0);
    wait_claims(2u, "the second delivery of source 1");
    metal_interrupt_disable(plic, TEST_INTERRUPT_ID);
    simputshex32("Claims completed and re-delivered: ", claimed_count);

    /* Every external source the bench drives, at distinct priorities so the
     * PLIC hands them over in non-increasing priority order, plus the I2C0
     * source the firmware raises through INTR_TEST at the top priority: each
     * must arrive once under its own ID. */
    simputs("Enabling sources 2-17 and the I2C0 source\n");
    expected_id = 0;
    for (int id = 2; id <= (int)EXT_SOURCE_COUNT; id++) {
        metal_interrupt_register_handler(plic, id, test_interrupt_handler, plic);
        set_priority(id, 1u + ((uint32_t)id % MAX_PRIORITY));
        metal_interrupt_enable(plic, id);
    }
    write_reg(SMC_TOP_SMC_I2C_WRAP_I2C_CTRL_REGS_I2C_CTRL_BASE_ADDR(I2C0_INDEX),
              I2C_CTRL__I2C_CTRL__I2C_EN_bm);
    write_reg(SMC_TOP_SMC_I2C_WRAP_I2C_INTR_ENABLE_BASE_ADDR(I2C0_INDEX),
              I2C__INTR_ENABLE__RX_OVERFLOW_bm);
    write_reg(SMC_TOP_SMC_I2C_WRAP_I2C_INTR_TEST_BASE_ADDR(I2C0_INDEX),
              I2C__INTR_TEST__RX_OVERFLOW_bm);
    metal_interrupt_register_handler(plic, I2C0_SOURCE, test_interrupt_handler, plic);
    set_priority(I2C0_SOURCE, MAX_PRIORITY);
    metal_interrupt_enable(plic, I2C0_SOURCE);
    uint32_t last_priority = MAX_PRIORITY;
    for (uint32_t n = 0; n < EXT_SOURCE_COUNT; n++) {
        uint32_t before = claimed_count;
        metal_interrupt_set_threshold(plic, 0);
        wait_claims(before + 1u, "the next enabled source in priority order");
        int id = last_claimed_id;
        uint32_t priority = metal_interrupt_get_priority(plic, id);
        if (priority > last_priority) {
            simputshex32("ERROR: source claimed out of priority order: ", (uint32_t)id);
            simputs("\n");
            test_fail(0);
        }
        last_priority = priority;
        metal_interrupt_disable(plic, id);
    }
    if (claimed_mask != (I2C0_CLAIMED_BIT | ((1u << (EXT_SOURCE_COUNT + 1u)) - 2u))) {
        simputshex32("ERROR: claimed source mask ", claimed_mask);
        simputs("\n");
        test_fail(0);
    }
    simputshex32("Every registered source claimed once, in priority order: ", claimed_count);

    /* Each claimable threshold with each source alone above it, and an idle
     * claim read at every threshold including the one that masks everything. */
    for (uint32_t threshold = 1u; threshold <= THRESHOLD_MASK_ALL; threshold++) {
        if (threshold <= THRESHOLD_MAX_CLAIMABLE) {
            for (int id = 1; id <= (int)EXT_SOURCE_COUNT; id++) {
                claim_one(plic, id, threshold);
            }
            claim_one(plic, I2C0_SOURCE, threshold);
        }
        claim_none(threshold);
    }
    claim_none(0);
    write_reg(SMC_TOP_SMC_I2C_WRAP_I2C_INTR_STATE_BASE_ADDR(I2C0_INDEX),
              I2C__INTR_STATE__RX_OVERFLOW_bm);
    write_reg(SMC_TOP_SMC_I2C_WRAP_I2C_INTR_ENABLE_BASE_ADDR(I2C0_INDEX), 0u);
    simputshex32("Claims across the threshold sweep: ", claimed_count);
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
