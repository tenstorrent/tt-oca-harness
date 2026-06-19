#include <stdint.h>
#include <time.h>

#include "smc_io.h"
#include "smc_test.h"
#include "virt_console.h"

// System Timer register definitions are provided by smc_io.h -> smc_top_regs.h

// Test parameters
#define WAIT_CYCLES         100
#define MAX_WAIT_CYCLES     10000
#define CREDIT_TEST_CYCLES  5000

static void wait_cycles(uint32_t cycles)
{
	for (volatile uint32_t i = 0; i < cycles; i++) {
		__asm__ volatile("nop");
	}
}

// Forward declarations
static uint32_t timer_is_running(void);
static uint32_t timer_is_secondary(void);

static void timer_init(void)
{
	uint32_t ctrl_val;

	// Initialize timer control register
	// credit_val can be configured via testbench plusargs
	// Default: credit_val=0x0A, pulse_width=0x02, step=0x01
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
	uint32_t wait_count = 0;

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

	write_reg(SMC_TOP_SMC_SYSTEM_TIMER_OCTS_TIMER_START_BASE_ADDR, 1);

	if (timer_is_secondary()) {
		while (!timer_is_running() && wait_count < MAX_WAIT_CYCLES) {
			wait_cycles(10);
			wait_count++;
		}

		if (!timer_is_running()) {
			simputs("ERROR: Timer not running after start\n");
			write_scratch(0, 0xBAD00002u);
			test_fail(0);
			while (1) {
				__asm__ volatile("nop");
			}
		}
	}
}

static uint64_t timer_get_count(void)
{
	uint32_t count_lo, count_hi;

	count_lo = read_reg(SMC_TOP_SMC_SYSTEM_TIMER_OCTS_TIMER_COUNT_LO_BASE_ADDR);
	count_hi = read_reg(SMC_TOP_SMC_SYSTEM_TIMER_OCTS_TIMER_COUNT_HI_BASE_ADDR);

	return ((uint64_t)count_hi << 32) | count_lo;
}

static uint32_t timer_get_credit_expired(void)
{
	return read_reg(SMC_TOP_SMC_SYSTEM_TIMER_OCTS_CREDIT_EXPIRED_BASE_ADDR);
}

static uint32_t timer_is_running(void)
{
	uint32_t status = read_reg(SMC_TOP_SMC_SYSTEM_TIMER_OCTS_STATUS_BASE_ADDR);
	return (status & 0x10) != 0;
}

static uint32_t timer_is_secondary(void)
{
	uint32_t status = read_reg(SMC_TOP_SMC_SYSTEM_TIMER_OCTS_STATUS_BASE_ADDR);
	return (status & 0x1) != 0;
}

static void test_credit_mechanism(void)
{
	uint64_t count1, count2;
	uint32_t credit_expired1, credit_expired2;
	uint32_t test_cycles = 0;

	simputs("Testing credit mechanism\n");

	if (!timer_is_secondary()) {
		simputs("ERROR: Timer is not in SECONDARY mode\n");
		write_scratch(0, 0xBAD50000u);
		test_fail(0);
		while (1) {
			__asm__ volatile("nop");
		}
	}

	// Read initial credit_expired value
	credit_expired1 = timer_get_credit_expired();
	count1 = timer_get_count();
	simputshex32("Initial credit_expired: ", credit_expired1);
	simputshex64("Initial count: ", count1);

	// Monitor credit_expired over multiple credit periods
	// Testbench should configure credit period and clock ratio via plusargs
	for (test_cycles = 0; test_cycles < CREDIT_TEST_CYCLES; test_cycles += WAIT_CYCLES) {
		wait_cycles(WAIT_CYCLES);
		credit_expired2 = timer_get_credit_expired();
		count2 = timer_get_count();

		// Credit expired should increment when credit expires
		// (credit pulse updates expected_count and resets credit counter)
		if (credit_expired2 > credit_expired1) {
			simputshex32("credit_expired incremented to: ", credit_expired2);
			credit_expired1 = credit_expired2;
		}

		// Verify timer is still running
		if (!timer_is_running()) {
			simputs("ERROR: Timer stopped running\n");
			write_scratch(0, 0xBAD50001u);
			test_fail(0);
			while (1) {
				__asm__ volatile("nop");
			}
		}
	}

	credit_expired2 = timer_get_credit_expired();
	count2 = timer_get_count();
	simputshex32("Final credit_expired: ", credit_expired2);
	simputshex64("Final count: ", count2);
	simputs("Credit mechanism test completed\n");
}

static void test_clock_ratio_compensation(void)
{
	uint64_t count1, count2, count3;
	uint32_t credit_expired1, credit_expired2;

	simputs("Testing clock ratio compensation\n");

	if (!timer_is_secondary()) {
		simputs("ERROR: Timer is not in SECONDARY mode\n");
		write_scratch(0, 0xBAD60000u);
		test_fail(0);
		while (1) {
			__asm__ volatile("nop");
		}
	}

	// Test slow clock compensation (SECONDARY clock slower than PRIMARY)
	// Testbench should configure slow clock ratio via plusargs
	count1 = timer_get_count();
	credit_expired1 = timer_get_credit_expired();
	simputshex64("Count before slow clock test: ", count1);
	simputshex32("credit_expired before: ", credit_expired1);

	wait_cycles(WAIT_CYCLES * 10);
	count2 = timer_get_count();
	credit_expired2 = timer_get_credit_expired();
	simputshex64("Count after wait: ", count2);
	simputshex32("credit_expired after: ", credit_expired2);

	// Verify counter increased
	if (count2 <= count1) {
		simputs("ERROR: Timer count not increasing\n");
		write_scratch(0, 0xBAD60001u);
		test_fail(0);
		while (1) {
			__asm__ volatile("nop");
		}
	}

	// Test fast clock compensation (SECONDARY clock faster than PRIMARY)
	// Testbench should configure fast clock ratio via plusargs
	wait_cycles(WAIT_CYCLES * 10);
	count3 = timer_get_count();
	simputshex64("Count after fast clock test: ", count3);

	if (count3 <= count2) {
		simputs("ERROR: Timer count not increasing\n");
		write_scratch(0, 0xBAD60002u);
		test_fail(0);
		while (1) {
			__asm__ volatile("nop");
		}
	}

	simputs("Clock ratio compensation test completed\n");
}

int main(void)
{
	write_scratch(1, 0xcccccccc);
	simputs("octs_p0_credit_test_start\n");

	// Note: peripherals_out_of_reset() is no longer available
	// peripherals_out_of_reset();
	wait_cycles(100);

	timer_init();

	write_scratch(1, 0xebedebe4);

	// Test 1: Credit mechanism
	simputs("Starting Test 1: Credit Mechanism\n");
	test_credit_mechanism();
	write_scratch(1, 0x01);

	// Test 2: Start timer
	simputs("Starting Test 2: Timer Start\n");
	timer_start(0x1000ULL);
	write_scratch(1, 0x02);

	// Test 3: Clock ratio compensation
	simputs("Starting Test 3: Clock Ratio Compensation\n");
	test_clock_ratio_compensation();
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
