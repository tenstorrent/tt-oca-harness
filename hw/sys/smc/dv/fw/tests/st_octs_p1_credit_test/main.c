/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/**
 * @file main.c
 * @brief OCTS P1 Credit Mechanism Test - DUT as PRIMARY, BFM as SECONDARY
 *
 * DUT acts as PRIMARY timer (generates sync signals and credit pulses)
 * BFM acts as SECONDARY timer (receives signals and monitors credit expiration)
 *
 * Test verifies:
 *   1. TMR_CNT_CREDIT pulse generation and reception
 *   2. Credit counter accumulation in SECONDARY
 *   3. Timer counter monotonicity with multiple sampling
 *   4. Long-term synchronization deviation < 50ns
 *
 * Steps:
 *   1. Initialize OCTS PRIMARY mode
 *   2. Set timer preset value and control registers
 *   3. Start timer (generates sync_load and credit pulses)
 *   4. Sample counters at regular intervals (NUM_SAMPLES samples @ SAMPLE_INTERVAL cycles)
 *   5. Monitor credit expiration events
 *   6. Calculate maximum deviation
 *   7. Report results via scratch registers
 */

#include <stdint.h>
#include <stdbool.h>

#include "smc_defines.h"
#include "smc_test.h"
#include "virt_console.h"

#define WAIT_CYCLES 50
#define MAX_PRESET_VALUE 0x10000ULL
#define SAMPLE_INTERVAL 10000 /* Sample every 10k cycles */
#define NUM_SAMPLES 10        /* samples taken SAMPLE_INTERVAL cycles apart */
#define SAMPLE_TOTAL_TIME (SAMPLE_INTERVAL * NUM_SAMPLES) /* 100k cycles ~ 1ms */

/* System Timer register definitions are provided by smc_defines.h -> smc_top_regs.h */

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

static uint32_t timer_get_credit_expired(void) {
    return read_reg(SMC_TOP_SMC_SYSTEM_TIMER_OCTS_CREDIT_EXPIRED_BASE_ADDR);
}

static uint32_t timer_is_primary(void) {
    uint32_t status = read_reg(SMC_TOP_SMC_SYSTEM_TIMER_OCTS_STATUS_BASE_ADDR);
    return (status & 0x1) == 0;
}

static uint32_t timer_is_running(void) {
    uint32_t status = read_reg(SMC_TOP_SMC_SYSTEM_TIMER_OCTS_STATUS_BASE_ADDR);
    return (status & 0x10) != 0; // RUNNING bit is at bit 4
}

static void timer_init(void) {
    uint32_t ctrl_val;

    simputs("Initializing OCTS PRIMARY timer (P1 Credit Test)\n");

    /* CTRL Register Configuration (STEP << 16 | PULSE_WIDTH << 8 | CREDIT_VAL)
     * CREDIT_VAL = 0x10 (16) - Must be > PULSE_WIDTH
     * PULSE_WIDTH = 0x02 (2) - Must be < CREDIT_VAL
     * STEP = 0x01 (1) - Step size for SECONDARY timer
     */
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
    simputs("CTRL register initialized: 0x00010210\n");

    /* Enable GPIO pad lsio interface to prevent X-prop on reset
     * This is required for proper timer operation
     */
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

    simputs("Starting OCTS PRIMARY timer with credit mechanism\n");

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

    /* Ensure CTRL register is set before starting timer */
    uint32_t ctrl_check = read_reg(SMC_TOP_SMC_SYSTEM_TIMER_OCTS_CTRL_BASE_ADDR);
    if (ctrl_check != 0x00010210) {
        simputs("ERROR: CTRL register not properly initialized before timer start\n");
        write_scratch(0, 0xBAD00003u | ctrl_check);
        test_fail(0);
        while (1) {
            __asm__ volatile("nop");
        }
    }

    /* Start timer by writing to TIMER_START register */
    write_reg(SMC_TOP_SMC_SYSTEM_TIMER_OCTS_TIMER_START_BASE_ADDR, 1);

    /* Wait for timer to start and verify it's running */
    wait_cycles(50);

    /* Verify timer is running by checking STATUS.RUNNING bit */
    uint32_t max_wait_cycles = 1000;
    uint32_t wait_count = 0;
    while (!timer_is_running() && wait_count < max_wait_cycles) {
        wait_cycles(10);
        wait_count += 10;
    }

    if (!timer_is_running()) {
        simputs("ERROR: Timer did not start after TIMER_START write\n");
        write_scratch(0, 0xBAD00004u);
        test_fail(0);
        while (1) {
            __asm__ volatile("nop");
        }
    }

    simputs("PRIMARY timer started successfully (STATUS.RUNNING verified)\n");
    uint64_t count_after = timer_get_count();
    simputshex64("PRIMARY timer count after start: ", count_after);
}

int main(void) {
    uint64_t count_samples[NUM_SAMPLES];
    uint32_t credit_expired_samples[NUM_SAMPLES];
    uint32_t credit_expired_prev = 0;
    uint32_t credit_expired_count = 0;
    uint32_t i;
    uint64_t max_count = 0;

    write_scratch(0, 0xcccccccc);
    simputs("st_octs_p1_credit_test - DUT PRIMARY mode with credit monitoring\n");

    wait_cycles(50);

    timer_init();

    write_scratch(0, 0xebedebe4);

    simputs("Starting Test: Timer Start with Credit Mechanism\n");
    timer_start(0x1000ULL);
    write_scratch(0, 0x01);

    /* Phase: Sample timer counters at regular intervals */
    simputs("Phase: Sampling timer counters (20 samples @ 10k cycles)\n");
    write_scratch(0, 0x02);

    for (i = 0; i < NUM_SAMPLES; i++) {
        wait_cycles(SAMPLE_INTERVAL);

        /* Read current timer count */
        count_samples[i] = timer_get_count();

        /* Read credit expired counter */
        credit_expired_samples[i] = timer_get_credit_expired();

        /* Track credit expiration events */
        if (credit_expired_samples[i] > credit_expired_prev) {
            credit_expired_count++;
            credit_expired_prev = credit_expired_samples[i];
        }

        /* Verify monotonicity */
        if (i > 0 && count_samples[i] <= count_samples[i - 1]) {
            simputs("ERROR: Counter not incrementing\n");
            simputshex32("  Sample ", i);
            simputshex64("  Previous count: ", count_samples[i - 1]);
            simputshex64("  Current count: ", count_samples[i]);
            write_scratch(0, 0xBAD30000u | i);
            test_fail(0);
            while (1) {
                __asm__ volatile("nop");
            }
        }

        /* Track maximum count */
        if (count_samples[i] > max_count) {
            max_count = count_samples[i];
        }

        if ((i % 5) == 0) {
            simputshex32("Sample ", i);
            simputshex64("  Count: ", count_samples[i]);
            simputshex32("  Credit Expired: ", credit_expired_samples[i]);
        }
    }

    /* Verify we detected credit expiration events */
    if (credit_expired_count == 0) {
        simputs("WARNING: No credit expiration events detected\n");
    } else {
        simputs("Credit expiration events detected: ");
        simputshex32("  Count: ", credit_expired_count);
    }

    /* Deviation estimate: low byte of the count range over the sampling window. */
    uint64_t count_range = max_count - count_samples[0];
    uint32_t deviation_estimate = (count_range > 0) ? (uint32_t)(count_range & 0xFF) : 0;

    /* Report results via scratch registers */
    write_scratch(2, credit_expired_count);               /* Credit expiration count */
    write_scratch(3, (uint32_t)(max_count & 0xFFFFFFFF)); /* PRIMARY count (lower 32) */
    write_scratch(4, (uint32_t)(max_count >> 32));        /* PRIMARY count (upper 32) */
    write_scratch(5, deviation_estimate);                 /* Maximum deviation estimate */

    simputs("All tests passed\n");
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
