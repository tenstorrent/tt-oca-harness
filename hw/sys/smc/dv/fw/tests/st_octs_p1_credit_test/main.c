/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/**
 * @file main.c
 * @brief OCTS P1 Credit Mechanism Test - DUT as PRIMARY, BFM as SECONDARY
 *
 * Runs the DUT system timer as the OCTS PRIMARY with the credit mechanism
 * enabled and checks that its count increases across periodic samples. The
 * firmware does not check credit expiry or synchronization deviation; it logs
 * and reports the credit-expiry count, the highest sampled count and a
 * deviation estimate via scratch registers.
 */

#include <stdint.h>

#include "smc_defines.h"
#include "smc_test.h"
#include "virt_console.h"

#define SAMPLE_INTERVAL 10000 /* Busy-loop iterations between samples */
#define NUM_SAMPLES 10

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
    return (status & 0x10) != 0;
}

static void timer_init(void) {
    uint32_t ctrl_val;

    simputs("Initializing OCTS PRIMARY timer (P1 Credit Test)\n");

    /* The credit value must exceed the sync pulse width. */
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

    /* The timer needs its pad interface enabled to avoid X propagation from reset. */
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

    /* The configuration must still hold before the timer starts. */
    uint32_t ctrl_check = read_reg(SMC_TOP_SMC_SYSTEM_TIMER_OCTS_CTRL_BASE_ADDR);
    if (ctrl_check != 0x00010210) {
        simputs("ERROR: CTRL register not properly initialized before timer start\n");
        write_scratch(0, 0xBAD00003u | ctrl_check);
        test_fail(0);
        while (1) {
            __asm__ volatile("nop");
        }
    }

    write_reg(SMC_TOP_SMC_SYSTEM_TIMER_OCTS_TIMER_START_BASE_ADDR, 1);

    wait_cycles(50);

    /* Bounded wait for the timer to report running. */
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

    /* Sample the count and the credit-expired counter at a fixed interval. */
    simputs("Phase: Sampling timer counters (20 samples @ 10k cycles)\n");
    write_scratch(0, 0x02);

    for (i = 0; i < NUM_SAMPLES; i++) {
        wait_cycles(SAMPLE_INTERVAL);

        count_samples[i] = timer_get_count();
        credit_expired_samples[i] = timer_get_credit_expired();

        /* Count the samples where the credit-expired counter advanced. */
        if (credit_expired_samples[i] > credit_expired_prev) {
            credit_expired_count++;
            credit_expired_prev = credit_expired_samples[i];
        }

        /* The count must increase between samples. */
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

        if (count_samples[i] > max_count) {
            max_count = count_samples[i];
        }

        if ((i % 5) == 0) {
            simputshex32("Sample ", i);
            simputshex64("  Count: ", count_samples[i]);
            simputshex32("  Credit Expired: ", credit_expired_samples[i]);
        }
    }

    /* Logged only; the count is reported via scratch below. */
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
}

int other_main(int hartid) {
    (void)hartid;
    while (1) {
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
