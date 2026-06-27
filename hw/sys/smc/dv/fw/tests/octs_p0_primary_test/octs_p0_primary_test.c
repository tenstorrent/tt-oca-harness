/* SPDX-License-Identifier: Apache-2.0 */
/* (c) 2026 Tenstorrent USA Inc */

#include <stdint.h>
#include <time.h>

#include "smc_io.h"
#include "smc_test.h"
#include "virt_console.h"

// Test parameters
#define WAIT_CYCLES         100
#define MAX_PRESET_VALUE    0x10000ULL  // Maximum preset value for random selection

// Random preset values for testing
#define PRESET_VALUES_COUNT 4
static const uint64_t preset_values[PRESET_VALUES_COUNT] = {
    0x0ULL,           // Start from 0
    0x1000ULL,        // Small preset
    0x10000ULL,       // Medium preset
    0x100000ULL       // Large preset
};

static void wait_cycles(uint32_t cycles)
{
	for (volatile uint32_t i = 0; i < cycles; i++) {
		__asm__ volatile("nop");
	}
}

// Simple random number generator using timer as seed
static uint32_t simple_rand(uint32_t *seed)
{
	*seed = (*seed * 1103515245 + 12345) & 0x7FFFFFFF;
	return *seed;
}

static void timer_init(void)
{
	uint32_t ctrl_val;

	// Initialize timer control register
	// Default: credit_val=0x0A, pulse_width=0x02, step=0x01
	write_reg(SMC_TOP_SMC_SYSTEM_TIMER_OCTS_CTRL_BASE_ADDR, 0x0001020A);

	// Read it back immediately
	ctrl_val = read_reg(SMC_TOP_SMC_SYSTEM_TIMER_OCTS_CTRL_BASE_ADDR);
	if (ctrl_val != 0x0001020A) {
		simputs("ERROR: CTRL register not set correctly\n");
		simputshex32("Expected: 0x0001020A, Got: ", ctrl_val);
		write_scratch(0, 0xBAD00000u | ctrl_val);
		test_fail(0);
		// Stop test execution on error
		while (1) {
			__asm__ volatile("nop");
		}
	}

	// Enable GPIO pad lsio interface to prevent X-prop on reset
	// This is required for proper timer operation
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

	// Set preset value
	write_reg(SMC_TOP_SMC_SYSTEM_TIMER_OCTS_TIMER_PRESET_LO_BASE_ADDR, (uint32_t)(preset_value & 0xFFFFFFFF));
	write_reg(SMC_TOP_SMC_SYSTEM_TIMER_OCTS_TIMER_PRESET_HI_BASE_ADDR, (uint32_t)(preset_value >> 32));

	// Read it back immediately
	preset_lo = read_reg(SMC_TOP_SMC_SYSTEM_TIMER_OCTS_TIMER_PRESET_LO_BASE_ADDR);
	preset_hi = read_reg(SMC_TOP_SMC_SYSTEM_TIMER_OCTS_TIMER_PRESET_HI_BASE_ADDR);
	preset_read = ((uint64_t)preset_hi << 32) | preset_lo;
	if (preset_read != preset_value) {
		simputs("ERROR: PRESET register not set correctly\n");
		simputshex64("Expected: ", preset_value);
		simputshex64("Got: ", preset_read);
		write_scratch(0, 0xBAD00001u);
		test_fail(0);
		// Stop test execution on error
		while (1) {
			__asm__ volatile("nop");
		}
	}

	// Start timer
	write_reg(SMC_TOP_SMC_SYSTEM_TIMER_OCTS_TIMER_START_BASE_ADDR, 1);
}

static uint64_t timer_get_count(void)
{
	uint32_t count_lo, count_hi;

	count_lo = read_reg(SMC_TOP_SMC_SYSTEM_TIMER_OCTS_TIMER_COUNT_LO_BASE_ADDR);
	count_hi = read_reg(SMC_TOP_SMC_SYSTEM_TIMER_OCTS_TIMER_COUNT_HI_BASE_ADDR);

	return ((uint64_t)count_hi << 32) | count_lo;
}

static uint32_t timer_is_running(void)
{
	uint32_t status = read_reg(SMC_TOP_SMC_SYSTEM_TIMER_OCTS_STATUS_BASE_ADDR);
	return (status & 0x10) != 0;  // Bit 4 indicates running status
}

static void test_preset_register(void)
{
	uint32_t preset_lo, preset_hi;
	uint64_t preset_value, preset_read;
	uint32_t seed = 0x12345678;  // Random seed
	uint32_t rand_val;

	// Randomly select whether to use preset or not
	rand_val = simple_rand(&seed);
	uint32_t use_preset = (rand_val & 0x1);  // 50% chance

	if (use_preset) {
		// Randomly select a preset value
		rand_val = simple_rand(&seed);
		uint32_t preset_idx = rand_val % PRESET_VALUES_COUNT;
		preset_value = preset_values[preset_idx];
		simputs("Test: Using PRESET register\n");
		simputshex64("Preset value: ", preset_value);
	} else {
		preset_value = 0x0ULL;
		simputs("Test: Starting from 0 (no preset)\n");
	}

	// Write preset value
	write_reg(SMC_TOP_SMC_SYSTEM_TIMER_OCTS_TIMER_PRESET_LO_BASE_ADDR, (uint32_t)(preset_value & 0xFFFFFFFF));
	write_reg(SMC_TOP_SMC_SYSTEM_TIMER_OCTS_TIMER_PRESET_HI_BASE_ADDR, (uint32_t)(preset_value >> 32));

	// Read it back
	preset_lo = read_reg(SMC_TOP_SMC_SYSTEM_TIMER_OCTS_TIMER_PRESET_LO_BASE_ADDR);
	preset_hi = read_reg(SMC_TOP_SMC_SYSTEM_TIMER_OCTS_TIMER_PRESET_HI_BASE_ADDR);
	preset_read = ((uint64_t)preset_hi << 32) | preset_lo;

	if (preset_read != preset_value) {
		simputs("ERROR: PRESET register readback mismatch\n");
		simputshex64("Expected: ", preset_value);
		simputshex64("Got: ", preset_read);
		write_scratch(0, 0xBAD10000u);
		test_fail(0);
		// Stop test execution on error
		while (1) {
			__asm__ volatile("nop");
		}
	}

	simputs("PRESET register test passed\n");
}

static void test_counter_monotonicity(void)
{
	uint64_t count1, count2, count3;
	uint32_t status;

	// Verify timer is running
	status = read_reg(SMC_TOP_SMC_SYSTEM_TIMER_OCTS_STATUS_BASE_ADDR);
	if ((status & 0x10) == 0) {
		simputs("ERROR: Timer not running\n");
		write_scratch(0, 0xBAD20000u);
		test_fail(0);
		// Stop test execution on error
		while (1) {
			__asm__ volatile("nop");
		}
	}

	// Read counter value immediately after PoR/start
	wait_cycles(WAIT_CYCLES);
	count1 = timer_get_count();

	// Verify count1 is valid
	if (count1 == 0xFFFFFFFFFFFFFFFFULL) {
		simputs("ERROR: Failed to read timer count\n");
		write_scratch(0, 0xBAD20001u);
		test_fail(0);
		// Stop test execution on error
		while (1) {
			__asm__ volatile("nop");
		}
	}

	simputshex64("Count1: ", count1);

	// Wait and read second count
	wait_cycles(WAIT_CYCLES * 2);
	count2 = timer_get_count();

	if (count2 == 0xFFFFFFFFFFFFFFFFULL) {
		simputs("ERROR: Failed to read timer count\n");
		write_scratch(0, 0xBAD20002u);
		test_fail(0);
		// Stop test execution on error
		while (1) {
			__asm__ volatile("nop");
		}
	}

	simputshex64("Count2: ", count2);

	// Verify monotonicity: count2 must be greater than count1
	if (count2 <= count1) {
		simputs("ERROR: Timer count not increasing (monotonicity violation)\n");
		simputshex64("Count1: ", count1);
		simputshex64("Count2: ", count2);
		write_scratch(0, 0xBAD20003u);
		test_fail(0);
		// Stop test execution on error
		while (1) {
			__asm__ volatile("nop");
		}
	}

	// Read third count for additional verification
	wait_cycles(WAIT_CYCLES * 2);
	count3 = timer_get_count();

	if (count3 == 0xFFFFFFFFFFFFFFFFULL) {
		simputs("ERROR: Failed to read timer count\n");
		write_scratch(0, 0xBAD20004u);
		test_fail(0);
		// Stop test execution on error
		while (1) {
			__asm__ volatile("nop");
		}
	}

	simputshex64("Count3: ", count3);

	// Verify monotonicity: count3 must be greater than count2
	if (count3 <= count2) {
		simputs("ERROR: Timer count not increasing (monotonicity violation)\n");
		simputshex64("Count2: ", count2);
		simputshex64("Count3: ", count3);
		write_scratch(0, 0xBAD20005u);
		test_fail(0);
		// Stop test execution on error
		while (1) {
			__asm__ volatile("nop");
		}
	}

	simputs("Counter monotonicity test passed\n");
}

int main(void)
{
	//-------------//
	// RESET & PLL //
	//-------------//
	write_scratch(1, 0xcccccccc);
	simputs("octs_p0_primary_test_start\n");

	// Release timer from reset
	// Note: peripherals_out_of_reset() is no longer available
	// simputs("Calling peripherals_out_of_reset()\n");
	// peripherals_out_of_reset();
	// simputs("peripherals_out_of_reset() completed\n");

	// Wait for reset to propagate
	wait_cycles(100);
	simputs("Reset propagation wait completed\n");

	// Initialize timer
	simputs("Initializing timer\n");
	timer_init();
	simputs("Timer initialization completed\n");

	// Signal setup done to testbench
	simputs("Signaling setup complete to testbench\n");
	write_scratch(1, 0xebedebe4);
	simputs("Setup complete signal sent\n");

	//-------------------//
	// Run Test Suite    //
	//-------------------//

	// Test 1: PRESET Register Test
	simputs("Starting Test 1: PRESET Register\n");
	test_preset_register();
	simputs("Test 1 completed\n");
	write_scratch(1, 0x01);

	// Test 2: Start timer (with or without preset based on random selection)
	simputs("Starting Test 2: Timer Start\n");
	uint32_t seed = 0x12345678;
	uint32_t rand_val = seed;
	uint32_t use_preset = (simple_rand(&rand_val) & 0x1);
	uint64_t preset_value = use_preset ? preset_values[simple_rand(&rand_val) % PRESET_VALUES_COUNT] : 0x0ULL;

	if (use_preset) {
		simputs("Starting timer with preset\n");
		simputshex64("Preset: ", preset_value);
	} else {
		simputs("Starting timer from 0\n");
	}

	timer_start(preset_value);
	wait_cycles(WAIT_CYCLES);
	simputs("Test 2 completed\n");
	write_scratch(1, 0x02);

	// Test 3: Counter Monotonicity Test
	simputs("Starting Test 3: Counter Monotonicity\n");
	test_counter_monotonicity();
	simputs("Test 3 completed\n");
	write_scratch(1, 0x03);

	// All tests passed
	simputs("All tests passed\n");
	write_scratch(0, 0xacafaca1);  // TEST_PASS value
	wait_cycles(10);

	test_pass(0);

	while (1) {
		__asm__("wfi");
	}

	return 0;
}
