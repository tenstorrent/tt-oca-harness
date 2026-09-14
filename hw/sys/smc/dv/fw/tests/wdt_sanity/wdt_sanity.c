/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

#include <stdint.h>

#include "metal/interrupt.h"
#include "metal/watchdog.h"
#include "metal/cpu.h"
#include "metal/drivers/riscv_cpu.h"
#include "smc_io.h"
#include "smc_test.h"
#include "virt_console.h"

static int wdog_interrupt_id;

/* Handler progress is published on scratch[7]: 0x1 by the first handler, 0x2 by
 * the stuck handler, 0x3 after the cluster comes back from the 2nd-stage reset. */
#define WDT_FLAG_SCRATCH 7
#define WDT_FLAG_FIRST_IRQ 0x1u
#define WDT_FLAG_REVIVED 0x2u
#define WDT_FLAG_DONE 0x3u
#define WDT_WAIT_BOUND 200000u

/* Failure codes land in scratch[0] so the run is diagnosable from the CSR poll;
 * test_fail() then latches TEST_FAIL over them. */
#define WDT_ERR_BAD_IRQ_ID 0xBAD00D00u
#define WDT_ERR_NO_FIRST_IRQ 0xBAD00D01u
#define WDT_ERR_NO_RESET 0xBAD00D02u
#define WDT_ERR_PLIC_REGISTER 0xBAD00D04u
#define WDT_ERR_PLIC_ENABLE 0xBAD00D05u

static void fail_wdt(uint32_t code, const char *msg) {
    write_scratch(0, code);
    simputs("  ERROR: ");
    simputs(msg);
    simputs("\n");
    test_fail(0);
}

/* A bare `wfi` may return spuriously and is architecturally permitted to be a
 * no-op, so waiting on one and then falling through must never read as success.
 * Every wait in this test is bounded and every fall-through is a failure. */
static bool wait_wdt_flag(uint32_t want, uint32_t bound) {
    uint32_t i;

    for (i = 0; i < bound; i++) {
        if (read_scratch(WDT_FLAG_SCRATCH) == want) {
            return true;
        }
        __asm__("wfi");
    }
    return false;
}

void wdt_interrupt_handler(int id, void *priv) {
    write_scratch(1, id);
    write_scratch(WDT_FLAG_SCRATCH, WDT_FLAG_FIRST_IRQ); // first interrupt handler reached
    metal_watchdog_feed((struct metal_watchdog *)priv);
    metal_watchdog_clear_interrupt((struct metal_watchdog *)priv);
}

void wdt_interrupt_handler_stuck(int id, void *priv) {
    uint32_t useless_count = 0;
    write_scratch(1, id + 0x1000);
    write_scratch(WDT_FLAG_SCRATCH, WDT_FLAG_REVIVED); // second interrupt handler reached

    while (true) { // loop "forever" -- 2nd wdt should hit and reset the cluster
        useless_count++;
        // Add small delay to prevent overwhelming AXI bus and causing queue overflow
        // in AXI4UserYanker. This throttles write rate while still allowing watchdog
        // to trigger reset in a timely manner.
        for (volatile int i = 0; i < 50; i++) {
            __asm__("nop");
        }
    }
}

int main(void) {
    struct metal_interrupt *plic_controller;
    struct metal_cpu *cpu;
    struct metal_interrupt *cpu_controller;
    struct metal_watchdog *wdog, *wdog1, *wdog2, *wdog3;

    uint32_t revived = 0x0;

    revived = read_scratch(WDT_FLAG_SCRATCH);

    if (revived != WDT_FLAG_REVIVED) {
        // get PLIC interrupt controller
        plic_controller = metal_interrupt_get_controller(METAL_PLIC_CONTROLLER, 0);

        cpu = metal_cpu_get(0);
        cpu_controller = metal_cpu_interrupt_controller(cpu);

        write_reg(SMC_TOP_SMC_CPU_CTRL_WDT_TIMEOUT_BASE_ADDR,
                  0x400); // set 2nd stage wdt timeout counter
        write_reg(SMC_TOP_SMC_MISC_WRAP_SCRATCH_COLD_SCRATCH_BASE_ADDR(7), 0xC0FFEE);
        write_reg(SMC_TOP_SMC_MISC_WRAP_SCRATCH_COLD_WARM_SCRATCH_BASE_ADDR(7), 0xC0FFEE);

        // get the all watchdog devices
        wdog = metal_watchdog_get_device(0);
        wdog1 = metal_watchdog_get_device(1);
        wdog2 = metal_watchdog_get_device(2);
        wdog3 = metal_watchdog_get_device(3);

        // get interrupt id for wdog
        wdog_interrupt_id = metal_watchdog_get_interrupt_id(wdog);

        // metal returns 0 when the device lookup misses; a 0 id makes the PLIC calls
        // below no-op.
        if (wdog_interrupt_id <= 0) {
            fail_wdt(WDT_ERR_BAD_IRQ_ID, "watchdog PLIC interrupt id unresolved");
        }

        // enable interrupts in the cpu
        metal_interrupt_init(cpu_controller);
        metal_interrupt_enable(cpu_controller, METAL_INTERRUPT_ID_BASE);

        // register a interrupt handler
        metal_interrupt_register_handler(cpu_controller, METAL_INTERRUPT_ID_EXT,
                                         wdt_interrupt_handler, wdog);

        // set values to other wdogs to disable their interrupts
        metal_watchdog_set_timeout(wdog1, 0x4000);
        metal_watchdog_set_timeout(wdog2, 0x4000);
        metal_watchdog_set_timeout(wdog3, 0x4000);
        metal_watchdog_clear_interrupt(wdog1);
        metal_watchdog_clear_interrupt(wdog2);
        metal_watchdog_clear_interrupt(wdog3);

        // setup watchdog settings
        // - 1.5GHz rate
        // - timeout after 0x4000 cycles
        // - interrupt on timeout
        // - also report reset
        // - clear any existing interrupts
        metal_watchdog_set_rate(wdog, 1500000000);
        metal_watchdog_set_timeout(wdog, 0x4000);
        metal_watchdog_set_result(wdog, METAL_WATCHDOG_INTERRUPT);
        metal_watchdog_set_result(wdog, METAL_WATCHDOG_FULL_RESET);
        metal_watchdog_clear_interrupt(wdog);

        // init the plic and register interrupt handler
        metal_interrupt_init(plic_controller);
        // Both PLIC calls return -1 when the id is out of range for this PLIC
        // (RISCV_NDEV); checking the return does not depend on the WDT source numbering.
        if (metal_interrupt_register_handler(plic_controller, wdog_interrupt_id,
                                             wdt_interrupt_handler, wdog) != 0) {
            fail_wdt(WDT_ERR_PLIC_REGISTER, "PLIC register_handler rejected the WDT id");
        }

        // start wdog
        metal_watchdog_run(wdog, METAL_WATCHDOG_RUN_AWAKE);

        // clear any existing wdt interrupt in the PLIC
        uint32_t read_int_id =
            *(uint32_t *)(uintptr_t)(SMC_TOP_SMC_CLUSTER_PLIC_CORE0_MEIP_CLAIM_COMPLETE_BASE_ADDR);
        *(uint32_t *)(uintptr_t)(SMC_TOP_SMC_CLUSTER_PLIC_CORE0_MEIP_CLAIM_COMPLETE_BASE_ADDR) =
            read_int_id;

        // enable the interrupt for PLIC
        if (metal_interrupt_enable(plic_controller, wdog_interrupt_id) != 0) {
            fail_wdt(WDT_ERR_PLIC_ENABLE, "PLIC enable rejected the WDT id");
        }

        // do some dummy commands
        int dummy_count = 5;
        while (dummy_count > 0) {
            write_scratch(5, dummy_count);
            dummy_count = dummy_count - 1;
        }

        // Wait for the first interrupt. The handler publishes WDT_FLAG_FIRST_IRQ;
        // a `wfi` that returns without it is not evidence the WDT barked.
        if (!wait_wdt_flag(WDT_FLAG_FIRST_IRQ, WDT_WAIT_BOUND)) {
            fail_wdt(WDT_ERR_NO_FIRST_IRQ, "first WDT timeout interrupt never arrived");
        }

        // register new interrupt handler
        metal_interrupt_register_handler(cpu_controller, METAL_INTERRUPT_ID_EXT,
                                         wdt_interrupt_handler_stuck, wdog);

        // do some dummy commands
        dummy_count = 29;
        simputshex32("New commands, count from ", dummy_count);

        while (dummy_count > 0) {
            write_scratch(6, dummy_count);
            dummy_count = dummy_count - 1;
        }

        // Wait for the second interrupt. wdt_interrupt_handler_stuck() never
        // returns, so the 2nd-stage WDT must warm-reset the cluster from inside
        // it and this hart must re-enter main() with scratch[7] == 0x2. Control
        // reaching past this loop means either the interrupt never fired or the
        // escalation never reset the cluster -- both are failures, so there is
        // no fall-through to a verdict here.
        {
            uint32_t i;

            for (i = 0; i < WDT_WAIT_BOUND; i++) {
                __asm__("wfi");
            }
        }
        fail_wdt(WDT_ERR_NO_RESET, "2nd-stage WDT did not reset the cluster");

    } else {
        // Re-entered after the 2nd-stage WDT warm-reset the cluster. This is the
        // only path that may pass: it is reachable only once the bark (first
        // handler) and the bite (escalation to reset) have both been observed.
        write_scratch(WDT_FLAG_SCRATCH, WDT_FLAG_DONE);
        test_pass(0);
    }

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
        /* Ensure that the lock is initialized before any readers of
         * _start_other */
        __asm__("fence rw,w"); /* Release semantics */

        return main();
    } else {
        return other_main(hartid);
    }
}
