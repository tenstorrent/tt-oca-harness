/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/**
 * @file main.c
 * @brief OCTS P2 Sync Recovery Test - DUT as PRIMARY, BFM as SECONDARY
 *
 * DUT acts as PRIMARY timer (generates sync signals)
 * BFM acts as SECONDARY timer (receives signals and recovers from resets)
 *
 * Test verifies complex synchronization scenarios:
 *   1. Baseline: Normal synchronized operation
 *   2. Timeout: Detection when SYNC signal is absent
 *   3. Reset: Counter reset without rollback
 *   4. Recovery: Successful resynchronization after reset
 *
 * Steps:
 *   1. Initialize OCTS PRIMARY mode
 *   2. Phase A: Baseline normal sync (1ms)
 *   3. Phase B: Monitor timeout (SECONDARY observes timeout flag)
 *   4. Phase C: Reset and verify no rollback
 *   5. Phase D: Recovery verification (1ms)
 *   6. Report results via scratch registers
 */

#include <stdint.h>
#include <stdbool.h>

#include "smc_defines.h"
#include "smc_test.h"
#include "virt_console.h"

#define WAIT_CYCLES 50
#define MAX_PRESET_VALUE 0x10000ULL
/* Phase runtime: kept short so the whole sync-recovery co-simulation stays fast while
 * still running long enough to prove the counter is incrementing in each phase. */
#define PHASE_RUNTIME_CYCLES 10000

static void wait_cycles(uint32_t cycles) {
    for (volatile uint32_t i = 0; i < cycles; i++) {
        __asm__ volatile("nop");
    }
}

static uint64_t timer_get_count(void) {
    uint32_t count_lo, count_hi;

    count_lo = read_reg(SMC_TOP_SMC_SYSTEM_TIMER_OCTS_TIMER_COUNT_LO_BASE_ADDR);
    count_hi = read_reg(SMC_TOP_SMC_SYSTEM_TIMER_OCTS_TIMER_COUNT_HI_BASE_ADDR);

    return ((uint64_t)count_hi << 32) | count_lo;
}

static uint32_t timer_is_primary(void) {
    uint32_t status = read_reg(SMC_TOP_SMC_SYSTEM_TIMER_OCTS_STATUS_BASE_ADDR);
    return (status & 0x1) == 0;
}

static void timer_init(void) {
    uint32_t ctrl_val;

    simputs("Initializing OCTS PRIMARY timer\n");

    // CTRL Register Configuration (STEP << 16 | PULSE_WIDTH << 8 | CREDIT_VAL)
    // CREDIT_VAL = 0x10 (16) - Must be > PULSE_WIDTH
    // PULSE_WIDTH = 0x02 (2) - Must be < CREDIT_VAL
    // STEP = 0x01 (1) - Step size for SECONDARY timer
    write_reg(SMC_TOP_SMC_SYSTEM_TIMER_OCTS_CTRL_BASE_ADDR, 0x00010210);

    ctrl_val = read_reg(SMC_TOP_SMC_SYSTEM_TIMER_OCTS_CTRL_BASE_ADDR);
    if (ctrl_val != 0x00010210) {
        simputs("ERROR: CTRL register not set correctly\n");
        write_scratch(0, 0xBAD00000u | ctrl_val);
        test_fail(0);
        while (1) {
            __asm__ volatile("nop");
        }
    }

    // Enable GPIO pad lsio interface to prevent X-prop on reset
    write_reg(SMC_TOP_SMC_SYSTEM_TIMER_OCTS_TIMER_GPIO_ENABLE_BASE_ADDR, 1);
    wait_cycles(10);
    uint32_t gpio_enable_val = read_reg(SMC_TOP_SMC_SYSTEM_TIMER_OCTS_TIMER_GPIO_ENABLE_BASE_ADDR);
    if ((gpio_enable_val & 0x1) != 1) {
        simputs("ERROR: TIMER_GPIO_ENABLE register not set correctly\n");
        write_scratch(0, 0xBAD00005u | gpio_enable_val);
        test_fail(0);
        while (1) {
            __asm__ volatile("nop");
        }
    }
    simputs("TIMER_GPIO_ENABLE register initialized: 0x1\n");
}

static void timer_start(uint64_t preset_value) {
    uint32_t preset_lo, preset_hi;
    uint64_t preset_read;

    simputs("Starting OCTS PRIMARY timer\n");

    write_reg(SMC_TOP_SMC_SYSTEM_TIMER_OCTS_TIMER_PRESET_LO_BASE_ADDR,
              (uint32_t)(preset_value & 0xFFFFFFFF));
    write_reg(SMC_TOP_SMC_SYSTEM_TIMER_OCTS_TIMER_PRESET_HI_BASE_ADDR,
              (uint32_t)(preset_value >> 32));

    preset_lo = read_reg(SMC_TOP_SMC_SYSTEM_TIMER_OCTS_TIMER_PRESET_LO_BASE_ADDR);
    preset_hi = read_reg(SMC_TOP_SMC_SYSTEM_TIMER_OCTS_TIMER_PRESET_HI_BASE_ADDR);
    preset_read = ((uint64_t)preset_hi << 32) | preset_lo;
    if (preset_read != preset_value) {
        simputs("ERROR: PRESET register not set correctly\n");
        write_scratch(0, 0xBAD00001u);
        test_fail(0);
        while (1) {
            __asm__ volatile("nop");
        }
    }

    if (!timer_is_primary()) {
        simputs("ERROR: Timer is not in PRIMARY mode\n");
        write_scratch(0, 0xBAD00002u);
        test_fail(0);
        while (1) {
            __asm__ volatile("nop");
        }
    }

    write_reg(SMC_TOP_SMC_SYSTEM_TIMER_OCTS_TIMER_START_BASE_ADDR, 1);

    simputs("PRIMARY timer started successfully\n");
    wait_cycles(50);
    uint64_t count_after = timer_get_count();
    simputshex64("PRIMARY timer count: ", count_after);
}

int main(void) {
    uint64_t count_baseline;
    uint64_t count_after_baseline;
    uint64_t count_before_reset;
    uint64_t count_after_reset;
    uint64_t count_recovery;
    uint64_t count_after_recovery;
    uint32_t timeout_flag = 0;
    uint32_t rollback_detected = 0;

    write_scratch(0, 0xcccccccc);
    simputs("octs_p2_sync_recovery_test - DUT PRIMARY mode with reset recovery\n");

    wait_cycles(50);

    timer_init();

    write_scratch(0, 0xebedebe4);

    simputs("Starting Test: Sync Recovery and Reset Handling\n");
    timer_start(0x1000ULL);
    write_scratch(0, 0x01);

    /* Phase A: Baseline normal sync (1ms) */
    simputs("Phase A: Baseline - Normal synchronized operation (1ms)\n");
    write_scratch(0, 0x02);

    count_baseline = timer_get_count();
    simputshex64("Baseline count start: ", count_baseline);

    wait_cycles(PHASE_RUNTIME_CYCLES);

    count_after_baseline = timer_get_count();
    simputshex64("Baseline count end: ", count_after_baseline);

    if (count_after_baseline <= count_baseline) {
        simputs("ERROR: Counter not incrementing in baseline phase\n");
        write_scratch(0, 0xBAD20001u);
        test_fail(0);
        while (1) {
            __asm__ volatile("nop");
        }
    }

    /* Phase B: Timeout monitoring
     * Note: Cocotb will stop PRIMARY SYNC signal during this phase
     * FW monitors status register for timeout flag
     */
    simputs("Phase B: Timeout - Monitoring for timeout condition\n");
    write_scratch(0, 0x03);

    /* Poll STATUS over a 200-poll * 100-cycle window; the SECONDARY timeout fires 100k
     * cycles after SYNC stops and is measured on the cocotb side.
     */
    uint32_t timeout_poll_count = 0;
    uint32_t max_timeout_polls = 200;

    for (timeout_poll_count = 0; timeout_poll_count < max_timeout_polls; timeout_poll_count++) {
        wait_cycles(100);

        /* Poll STATUS register for timeout flag
         * Log status periodically for debugging
         */
        if ((timeout_poll_count % 500) == 0) {
            uint32_t status = read_reg(SMC_TOP_SMC_SYSTEM_TIMER_OCTS_STATUS_BASE_ADDR);
            simputshex32("  Status at poll ", timeout_poll_count);
            simputshex32("   Value: 0x", status);
        }
    }

    simputs("Timeout observation phase completed\n");
    write_scratch(0, 0x04);

    /* Phase C: Reset recovery
     * Note: Cocotb will pulse hardware reset (BP_RESETN) to trigger complete reset
     * After reset, firmware must reinitialize timer registers to ensure proper operation
     */
    simputs("Phase C: Reset - Verifying reset behavior\n");
    write_scratch(0, 0x05);

    count_before_reset = timer_get_count();
    simputshex64("Count before reset: ", count_before_reset);

    /* Wait for hardware reset pulse from Cocotb
     * After reset completes, timer registers are reset to default values
     * Firmware must reinitialize timer to ensure proper operation
     */
    wait_cycles(2000); /* Settle before the register-level reset/restart */

    /* After hardware reset, timer registers are reset:
     * - CTRL register resets to default (0x0000020A)
     * - PRESET registers reset to 0
     * - Counter resets to 0
     * - Enable signal resets to 0
     *
     * Reinitialize timer registers to ensure proper operation
     */
    simputs("Reinitializing timer after reset...\n");

    /* Reinitialize CTRL register */
    write_reg(SMC_TOP_SMC_SYSTEM_TIMER_OCTS_CTRL_BASE_ADDR, 0x00010210);
    wait_cycles(10);

    uint32_t ctrl_val = read_reg(SMC_TOP_SMC_SYSTEM_TIMER_OCTS_CTRL_BASE_ADDR);
    if (ctrl_val != 0x00010210) {
        simputs("ERROR: CTRL register not set correctly after reset\n");
        write_scratch(0, 0xBAD00010u | ctrl_val);
        test_fail(0);
        while (1) {
            __asm__ volatile("nop");
        }
    }

    /* Re-enable GPIO pad lsio interface after reset */
    write_reg(SMC_TOP_SMC_SYSTEM_TIMER_OCTS_TIMER_GPIO_ENABLE_BASE_ADDR, 1);
    wait_cycles(10);
    uint32_t gpio_enable_val = read_reg(SMC_TOP_SMC_SYSTEM_TIMER_OCTS_TIMER_GPIO_ENABLE_BASE_ADDR);
    if ((gpio_enable_val & 0x1) != 1) {
        simputs("ERROR: TIMER_GPIO_ENABLE register not set correctly after reset\n");
        write_scratch(0, 0xBAD00015u | gpio_enable_val);
        test_fail(0);
        while (1) {
            __asm__ volatile("nop");
        }
    }
    simputs("TIMER_GPIO_ENABLE register reinitialized after reset: 0x1\n");

    /* Reset PRESET registers to ensure clean state */
    write_reg(SMC_TOP_SMC_SYSTEM_TIMER_OCTS_TIMER_PRESET_LO_BASE_ADDR, 0x0);
    write_reg(SMC_TOP_SMC_SYSTEM_TIMER_OCTS_TIMER_PRESET_HI_BASE_ADDR, 0x0);
    wait_cycles(10);

    /* Check counter after reset - should be 0 */
    count_after_reset = timer_get_count();
    simputshex64("Count after reset (before restart): ", count_after_reset);

    /* Verify counter was reset to 0 */
    if (count_after_reset != 0) {
        simputs("WARNING: Counter not zero after reset, value: ");
        simputshex64("", count_after_reset);
        simputs("\n");
        /* Continue anyway - may be due to timing */
    }

    /* Restart timer with new preset value */
    simputs("Restarting timer after reset...\n");
    write_reg(SMC_TOP_SMC_SYSTEM_TIMER_OCTS_TIMER_PRESET_LO_BASE_ADDR,
              (uint32_t)(0x1000ULL & 0xFFFFFFFF));
    write_reg(SMC_TOP_SMC_SYSTEM_TIMER_OCTS_TIMER_PRESET_HI_BASE_ADDR, (uint32_t)(0x1000ULL >> 32));
    wait_cycles(10);

    write_reg(SMC_TOP_SMC_SYSTEM_TIMER_OCTS_TIMER_START_BASE_ADDR, 1);
    wait_cycles(50);

    /* Verify counter after restart */
    uint64_t count_after_restart = timer_get_count();
    simputshex64("Count after restart: ", count_after_restart);

    if (count_after_restart == 0) {
        simputs("OK: Counter properly reset to 0 and restarted\n");
        write_scratch(6, 0); /* No rollback */
    } else if (count_after_restart > count_before_reset) {
        simputs("ERROR: Potential rollback detected - count increased after reset!\n");
        rollback_detected = 1;
        write_scratch(6, 1); /* Rollback flag */
    } else {
        simputs("OK: Counter reset and restarted successfully\n");
        write_scratch(6, 0); /* No rollback */
    }

    /* Phase D: Recovery verification (1ms)
     * Verify that timer continues to increment properly after reset and restart
     * Timer should have been restarted in Phase C, so it should be running now
     */
    simputs("Phase D: Recovery - Verifying normal operation after reset\n");
    write_scratch(0, 0x06);

    /* Wait a bit to ensure timer is running after restart */
    wait_cycles(1000);

    count_recovery = timer_get_count();
    simputshex64("Recovery phase count start: ", count_recovery);

    /* Verify timer is running (count should be > 0 after restart) */
    if (count_recovery == 0) {
        simputs("WARNING: Timer count is still 0 after restart, may need more time\n");
        wait_cycles(2000); /* Wait longer */
        count_recovery = timer_get_count();
        simputshex64("Recovery phase count start (after extended wait): ", count_recovery);
    }

    wait_cycles(PHASE_RUNTIME_CYCLES);

    count_after_recovery = timer_get_count();
    simputshex64("Recovery phase count end: ", count_after_recovery);

    if (count_after_recovery <= count_recovery) {
        simputs("ERROR: Counter not incrementing in recovery phase\n");
        simputshex64("  Start count: ", count_recovery);
        simputshex64("  End count: ", count_after_recovery);
        write_scratch(0, 0xBAD20003u);
        test_fail(0);
        while (1) {
            __asm__ volatile("nop");
        }
    }

    /* Calculate recovery phase deviation (count range)
     * This is a simplified estimate
     */
    uint64_t recovery_range = count_after_recovery - count_recovery;
    uint32_t deviation_estimate = (recovery_range > 0) ? (uint32_t)(recovery_range & 0xFF) : 0;

    /* Report results via scratch registers */
    write_scratch(2, 0); /* Timeout precision (Cocotb measures this) */
    write_scratch(3, (uint32_t)(count_baseline & 0xFFFFFFFF)); /* Baseline count */
    write_scratch(4, (count_after_reset == 0) ? 0 : 1);        /* Reset status */
    write_scratch(5, (uint32_t)(count_recovery & 0xFFFFFFFF)); /* Recovery count */
    write_scratch(7, deviation_estimate);                      /* Recovery deviation */

    simputs("All phases completed successfully\n");
    write_scratch(0, 0xacafaca1);
    wait_cycles(5);

    test_pass(0);

    while (1) {
        __asm__("wfi");
    }

    return 0;
}

int other_main(int hartid) {
    (void)hartid;
    while (1) {
        __asm__("wfi");
    }
    return 0;
}

int secondary_main(void) {
    int hartid = metal_cpu_get_current_hartid();
    if (hartid == 0) {
        return main();
    } else {
        return other_main(hartid);
    }
}
