/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

#include <stdint.h>
#include <time.h>

#include "smc_io.h"
#include "smc_test.h"
#include "virt_console.h"

// System Timer register definitions are provided by smc_io.h -> smc_top_regs.h

// Test parameters - Optimized to reduce register reads
#define SYNC_LOAD_CHECK_INTERVAL  2000  // Interval to check for sync_load events (increased from 100)
#define MAX_WAIT_CYCLES     10000  // Maximum cycles to wait for sync_load events
#define SYNC_LOAD_DETECT_COUNT  3  // Number of sync_load events to detect before passing
#define SYNC_LOAD_VERIFY_CYCLES  1000  // Cycles to verify after each sync_load detection (increased from 500)
#define TIMER_START_WAIT_INTERVAL  200  // Wait interval for SECONDARY timer startup (increased from 10)

static void wait_cycles(uint32_t cycles)
{
	for (volatile uint32_t i = 0; i < cycles; i++) {
		__asm__ volatile("nop");
	}
}

// Forward declarations
static uint64_t timer_get_count(void);
static uint32_t timer_is_secondary(void);

static void timer_init(void)
{
	uint32_t ctrl_val;

	// Initialize timer control register
	write_reg(SMC_TOP_SMC_SYSTEM_TIMER_OCTS_CTRL_BASE_ADDR, 0x0001020A);

	ctrl_val = read_reg(SMC_TOP_SMC_SYSTEM_TIMER_OCTS_CTRL_BASE_ADDR);
	if (ctrl_val != 0x0001020A) {
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
}

static void timer_start(uint64_t preset_value)
{
	uint32_t preset_lo, preset_hi;
	uint64_t preset_read;
	uint32_t is_secondary;
	uint64_t count_before, count_after;
	uint32_t retry_count = 0;
	const uint32_t MAX_RETRY = 10;

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

	// Check timer mode once
	is_secondary = timer_is_secondary();

	write_reg(SMC_TOP_SMC_SYSTEM_TIMER_OCTS_TIMER_START_BASE_ADDR, 1);

	if (is_secondary) {
		simputs("SECONDARY timer: waiting for sync_load to start\n");

		// Wait for sync_load and verify timer starts counting
		// Use retry loop with longer wait between checks
		while (retry_count < MAX_RETRY) {
			// Wait for sync_load period (need to wait for at least one sync_load pulse)
			wait_cycles(TIMER_START_WAIT_INTERVAL * 100);

			// Check if timer is counting
			count_before = timer_get_count();
			simputshex64("  Check count before: ", count_before);

			wait_cycles(5000);  // Wait a bit longer for counter to increment

			count_after = timer_get_count();
			simputshex64("  Check count after: ", count_after);

			if (count_after > count_before) {
				// Timer is counting, success!
				simputs("SECONDARY timer started successfully\n");
				simputshex64("  Final count: ", count_after);
				return;
			}

			retry_count++;
			if (retry_count < MAX_RETRY) {
				simputs("  Timer not counting yet, retrying...\n");
			}
		}

		// If we get here, timer failed to start
		simputs("ERROR: Timer counter not incrementing after multiple retries\n");
		simputshex32("Retry count: ", retry_count);
		write_scratch(0, 0xBAD00002u);
		test_fail(0);
		while (1) {
			__asm__ volatile("nop");
		}
	} else {
		simputs("PRIMARY timer started\n");
		// Verify PRIMARY timer started immediately
		wait_cycles(100);
		count_after = timer_get_count();
		simputshex64("PRIMARY timer count: ", count_after);
	}
}

static uint64_t timer_get_count(void)
{
	uint32_t count_lo, count_hi;

	count_lo = read_reg(SMC_TOP_SMC_SYSTEM_TIMER_OCTS_TIMER_COUNT_LO_BASE_ADDR);
	count_hi = read_reg(SMC_TOP_SMC_SYSTEM_TIMER_OCTS_TIMER_COUNT_HI_BASE_ADDR);

	return ((uint64_t)count_hi << 32) | count_lo;
}

static uint32_t timer_is_secondary(void)
{
	uint32_t status = read_reg(SMC_TOP_SMC_SYSTEM_TIMER_OCTS_STATUS_BASE_ADDR);
	return (status & 0x1) != 0;
}

static void test_sync_load_periodic(void)
{
	uint64_t count_samples[SYNC_LOAD_DETECT_COUNT + 2];
	uint32_t sync_load_count = 0;
	uint32_t i;

	simputs("Testing sync_load periodic behavior\n");

	// Single check at start: verify SECONDARY mode
	if (!timer_is_secondary()) {
		simputs("ERROR: Timer is not in SECONDARY mode\n");
		write_scratch(0, 0xBAD30000u);
		test_fail(0);
		while (1) {
			__asm__ volatile("nop");
		}
	}

	// Strategy: Take multiple counter samples at fixed intervals
	// Analyze samples to detect sync_load events (counter decreases)
	simputs("Collecting counter samples...\n");

	for (i = 0; i < (SYNC_LOAD_DETECT_COUNT + 2); i++) {
		// Wait between samples
		wait_cycles(SYNC_LOAD_CHECK_INTERVAL);

		// Take one sample
		count_samples[i] = timer_get_count();
		simputshex64("Sample: ", count_samples[i]);
	}

	// Analyze samples to detect sync_load events
	simputs("Analyzing samples for sync_load events...\n");

	for (i = 1; i < (SYNC_LOAD_DETECT_COUNT + 2); i++) {
		// sync_load detected when counter decreases
		if (count_samples[i] < count_samples[i-1]) {
			sync_load_count++;
			simputs("sync_load event detected between samples\n");
			simputshex64("  Before: ", count_samples[i-1]);
			simputshex64("  After:  ", count_samples[i]);
		}
	}

	// Verify we detected enough sync_load events
	if (sync_load_count < SYNC_LOAD_DETECT_COUNT) {
		simputs("ERROR: Not enough sync_load events detected\n");
		simputshex32("Detected: ", sync_load_count);
		simputshex32("Required: ", SYNC_LOAD_DETECT_COUNT);
		write_scratch(0, 0xBAD30004u);
		test_fail(0);
		while (1) {
			__asm__ volatile("nop");
		}
	}

	// Final verification: Counter is still incrementing
	uint64_t final_count1 = timer_get_count();
	wait_cycles(1000);
	uint64_t final_count2 = timer_get_count();

	if (final_count2 <= final_count1) {
		simputs("ERROR: Counter not incrementing at test end\n");
		write_scratch(0, 0xBAD30005u);
		test_fail(0);
		while (1) {
			__asm__ volatile("nop");
		}
	}

	simputs("sync_load periodic test completed\n");
	simputshex32("sync_load events detected: ", sync_load_count);
	simputshex64("Final count: ", final_count2);
}

static void test_resync_timeout(void)
{
	uint64_t count1, count2;

	simputs("Testing resync timeout behavior\n");

	// Single mode check
	if (!timer_is_secondary()) {
		simputs("ERROR: Timer is not in SECONDARY mode\n");
		write_scratch(0, 0xBAD40000u);
		test_fail(0);
		while (1) {
			__asm__ volatile("nop");
		}
	}

	// Simple test: Wait and verify counter is still incrementing
	// Testbench should stop sync_load pulses to test timeout behavior
	count1 = timer_get_count();
	simputshex64("Count before resync test: ", count1);

	// Wait for extended period
	wait_cycles(SYNC_LOAD_CHECK_INTERVAL * 10);

	// Read counter after wait
	count2 = timer_get_count();
	simputshex64("Count after wait: ", count2);

	// Verify counter increased (timer continues even without sync_load)
	if (count2 <= count1) {
		simputs("ERROR: Timer count not increasing during resync test\n");
		write_scratch(0, 0xBAD40002u);
		test_fail(0);
		while (1) {
			__asm__ volatile("nop");
		}
	}

	simputs("Resync timeout test completed\n");
}

int main(void)
{
	write_scratch(1, 0xcccccccc);
	simputs("octs_p0_sync_load_test_start\n");

	// Note: peripherals_out_of_reset() is no longer available
	// peripherals_out_of_reset();
	wait_cycles(100);

	timer_init();

	write_scratch(1, 0xebedebe4);

	// Test 1: Start timer (must be done before monitoring sync_load)
	simputs("Starting Test 1: Timer Start\n");
	timer_start(0x1000ULL);
	write_scratch(1, 0x01);

	// Test 2: sync_load periodic behavior (monitor sync_load after timer is running)
	simputs("Starting Test 2: sync_load Periodic\n");
	test_sync_load_periodic();
	write_scratch(1, 0x02);

	// Test 3: Resync timeout
	simputs("Starting Test 3: Resync Timeout\n");
	test_resync_timeout();
	write_scratch(1, 0x03);

	simputs("All tests passed\n");
	write_scratch(0, 0xacafaca1);
	wait_cycles(10);

	test_pass(0);

	while (1) {
		__asm__("wfi");
	}

	return 0;
}
