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

/* Handler progress is published on a scratch register that survives the
 * second-stage reset, so main() can tell first entry from re-entry. */
#define WDT_FLAG_SCRATCH 7
#define WDT_FLAG_FIRST_IRQ 0x1u
#define WDT_FLAG_REVIVED 0x2u
#define WDT_FLAG_DONE 0x3u
#define WDT_WAIT_BOUND 200000u

/* Failure codes are published before test_fail() so a failing run shows which check failed. */
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

/* A `wfi` may return spuriously, so every wait is bounded and a timeout is a failure. */
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
    write_scratch(WDT_FLAG_SCRATCH, WDT_FLAG_FIRST_IRQ);
    metal_watchdog_feed((struct metal_watchdog *)priv);
    metal_watchdog_clear_interrupt((struct metal_watchdog *)priv);
}

void wdt_interrupt_handler_stuck(int id, void *priv) {
    write_scratch(1, id + 0x1000);
    write_scratch(WDT_FLAG_SCRATCH, WDT_FLAG_REVIVED);

    // Never return, so only the second-stage watchdog reset can end this handler
    while (true) {
        // Throttle the loop to limit bus traffic while waiting for the reset
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
        plic_controller = metal_interrupt_get_controller(METAL_PLIC_CONTROLLER, 0);

        cpu = metal_cpu_get(0);
        cpu_controller = metal_cpu_interrupt_controller(cpu);

        // Second-stage watchdog timeout
        write_reg(SMC_TOP_SMC_CPU_CTRL_WDT_TIMEOUT_BASE_ADDR, 0x400);
        write_reg(SMC_TOP_SMC_MISC_WRAP_SCRATCH_COLD_SCRATCH_BASE_ADDR(7), 0xC0FFEE);
        write_reg(SMC_TOP_SMC_MISC_WRAP_SCRATCH_COLD_WARM_SCRATCH_BASE_ADDR(7), 0xC0FFEE);

        wdog = metal_watchdog_get_device(0);
        wdog1 = metal_watchdog_get_device(1);
        wdog2 = metal_watchdog_get_device(2);
        wdog3 = metal_watchdog_get_device(3);

        wdog_interrupt_id = metal_watchdog_get_interrupt_id(wdog);

        // metal returns 0 when the device lookup misses; a 0 id makes the PLIC calls
        // below no-op.
        if (wdog_interrupt_id <= 0) {
            fail_wdt(WDT_ERR_BAD_IRQ_ID, "watchdog PLIC interrupt id unresolved");
        }

        // Enable CPU interrupts and route external interrupts to wdt_interrupt_handler
        metal_interrupt_init(cpu_controller);
        metal_interrupt_enable(cpu_controller, METAL_INTERRUPT_ID_BASE);

        metal_interrupt_register_handler(cpu_controller, METAL_INTERRUPT_ID_EXT,
                                         wdt_interrupt_handler, wdog);

        // Keep the other watchdogs from interrupting
        metal_watchdog_set_timeout(wdog1, 0x4000);
        metal_watchdog_set_timeout(wdog2, 0x4000);
        metal_watchdog_set_timeout(wdog3, 0x4000);
        metal_watchdog_clear_interrupt(wdog1);
        metal_watchdog_clear_interrupt(wdog2);
        metal_watchdog_clear_interrupt(wdog3);

        // Configure watchdog 0's rate, timeout and timeout result, then clear its interrupt
        metal_watchdog_set_rate(wdog, 1500000000);
        metal_watchdog_set_timeout(wdog, 0x4000);
        metal_watchdog_set_result(wdog, METAL_WATCHDOG_INTERRUPT);
        metal_watchdog_set_result(wdog, METAL_WATCHDOG_FULL_RESET);
        metal_watchdog_clear_interrupt(wdog);

        metal_interrupt_init(plic_controller);
        // Both PLIC calls return -1 when the id is out of range for this PLIC
        // (RISCV_NDEV); checking the return does not depend on the WDT source numbering.
        if (metal_interrupt_register_handler(plic_controller, wdog_interrupt_id,
                                             wdt_interrupt_handler, wdog) != 0) {
            fail_wdt(WDT_ERR_PLIC_REGISTER, "PLIC register_handler rejected the WDT id");
        }

        metal_watchdog_run(wdog, METAL_WATCHDOG_RUN_AWAKE);

        // Claim and complete any interrupt already pending in the PLIC
        uint32_t read_int_id =
            *(uint32_t *)(uintptr_t)(SMC_TOP_SMC_CLUSTER_PLIC_CORE0_MEIP_CLAIM_COMPLETE_BASE_ADDR);
        *(uint32_t *)(uintptr_t)(SMC_TOP_SMC_CLUSTER_PLIC_CORE0_MEIP_CLAIM_COMPLETE_BASE_ADDR) =
            read_int_id;

        if (metal_interrupt_enable(plic_controller, wdog_interrupt_id) != 0) {
            fail_wdt(WDT_ERR_PLIC_ENABLE, "PLIC enable rejected the WDT id");
        }

        // Keep the hart busy with scratch writes while the watchdog counts
        int dummy_count = 5;
        while (dummy_count > 0) {
            write_scratch(5, dummy_count);
            dummy_count = dummy_count - 1;
        }

        // Only the handler's progress flag proves the first interrupt arrived
        if (!wait_wdt_flag(WDT_FLAG_FIRST_IRQ, WDT_WAIT_BOUND)) {
            fail_wdt(WDT_ERR_NO_FIRST_IRQ, "first WDT timeout interrupt never arrived");
        }

        metal_interrupt_register_handler(cpu_controller, METAL_INTERRUPT_ID_EXT,
                                         wdt_interrupt_handler_stuck, wdog);

        dummy_count = 29;
        simputshex32("New commands, count from ", dummy_count);

        while (dummy_count > 0) {
            write_scratch(6, dummy_count);
            dummy_count = dummy_count - 1;
        }

        // The stuck handler never returns, so the second-stage reset must restart
        // main(); reaching the end of this wait is a failure
        {
            uint32_t i;

            for (i = 0; i < WDT_WAIT_BOUND; i++) {
                __asm__("wfi");
            }
        }
        fail_wdt(WDT_ERR_NO_RESET, "2nd-stage WDT did not reset the cluster");

    } else {
        // Re-entry after the second-stage reset is the only passing path
        write_scratch(WDT_FLAG_SCRATCH, WDT_FLAG_DONE);
        test_pass(0);
    }
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
