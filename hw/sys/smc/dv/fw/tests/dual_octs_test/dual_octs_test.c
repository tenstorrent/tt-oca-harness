/* SPDX-License-Identifier: Apache-2.0 */
/* (c) 2026 Tenstorrent USA Inc */

/**
 * @file main.c
 * @brief Dual OCTS Test - DUT as PRIMARY, BFM as SECONDARY
 *
 * DUT acts as PRIMARY timer (generates sync signals)
 * BFM acts as SECONDARY timer (receives and responds to sync signals)
 *
 * Steps:
 *   1. Initialize OCTS PRIMARY mode
 *   2. Set timer preset value
 *   3. Start timer (generates sync_load pulses)
 *   4. Report result to scratch[0]
 */

#include <stdint.h>
#include <stdbool.h>

#include "smc_io.h"
#include "smc_test.h"
#include "virt_console.h"

#define WAIT_CYCLES         50
#define MAX_PRESET_VALUE    0x10000ULL

static void wait_cycles(uint32_t cycles)
{
	for (volatile uint32_t i = 0; i < cycles; i++) {
		__asm__ volatile("nop");
	}
}

static uint64_t timer_get_count(void)
{
	uint32_t count_lo, count_hi;

	count_lo = read_reg(SMC_TOP_SMC_SYSTEM_TIMER_OCTS_TIMER_COUNT_LO_BASE_ADDR);
	count_hi = read_reg(SMC_TOP_SMC_SYSTEM_TIMER_OCTS_TIMER_COUNT_HI_BASE_ADDR);

	return ((uint64_t)count_hi << 32) | count_lo;
}

static uint32_t timer_is_primary(void)
{
	uint32_t status = read_reg(SMC_TOP_SMC_SYSTEM_TIMER_OCTS_STATUS_BASE_ADDR);
	return (status & 0x1) == 0;
}

static void timer_init(void)
{
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

static void timer_start(uint64_t preset_value)
{
	uint32_t preset_lo, preset_hi;
	uint64_t preset_read;

	simputs("Starting OCTS PRIMARY timer\n");

	write_reg(SMC_TOP_SMC_SYSTEM_TIMER_OCTS_TIMER_PRESET_LO_BASE_ADDR, (uint32_t)(preset_value & 0xFFFFFFFF));
	write_reg(SMC_TOP_SMC_SYSTEM_TIMER_OCTS_TIMER_PRESET_HI_BASE_ADDR, (uint32_t)(preset_value >> 32));

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

int main(void)
{
	write_scratch(0, 0xcccccccc);
	simputs("dual_octs_test - DUT PRIMARY mode\n");

	wait_cycles(50);

	timer_init();

	write_scratch(0, 0xebedebe4);

	simputs("Starting Test: Timer Start\n");
	timer_start(0x1000ULL);
	write_scratch(0, 0x01);

	wait_cycles(2000);

	uint64_t final_count1 = timer_get_count();
	simputshex64("Final count check 1: ", final_count1);
	wait_cycles(200);
	uint64_t final_count2 = timer_get_count();
	simputshex64("Final count check 2: ", final_count2);

	if (final_count2 <= final_count1) {
		simputs("ERROR: Counter not incrementing\n");
		write_scratch(0, 0xBAD30005u);
		test_fail(0);
		while (1) {
			__asm__ volatile("nop");
		}
	}

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
