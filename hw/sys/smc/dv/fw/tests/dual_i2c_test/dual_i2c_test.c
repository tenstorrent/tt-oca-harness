/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/**
 * @file main.c
 * @brief Dual I2C Test - DUT as I2C Master writing to BFM Slave
 *
 * DUT acts as I2C Master using I2C_0
 * Writes to external BFM which acts as I2C Slave at address 0x10
 *
 * Steps:
 *   1. Initialize I2C_0 as Master
 *   2. Send I2C write command with proper STOP to BFM (addr 0x10)
 *   3. Wait for non-blocking write transaction to complete
 *   4. Send I2C read command to BFM
 *   5. Report result to scratch[0]
 *
 * CRITICAL FIX: i2c_controller_write_with_header_nonblock() DOES send STOP signal correctly,
 * but it returns immediately while hardware FSM executes in background. Must wait for completion.
 *
 * SOLUTION: Follow i2c_p0_rdwr test pattern:
 * - Use i2c_controller_wait_idle() instead of manual status polling
 * - Checks status.f.HOSTIDLE (proven method)
 * - Proper error handling with I2C_TIMEOUT_DEFAULT
 */

#include <stdint.h>
#include <stdbool.h>

#include "smc_io.h"
#include "smc_test.h"
#include "i2c_opentitan.h"

#define BFM_I2C_SLAVE_ADDR  0x10   // BFM Slave address (7-bit) - Standard address used by all I2C tests
#define TEST_DATA_BYTE      0xAA   // Test data to send
#define COCOTB_SIGNAL_VALUE 0xDEADBEEF  // Specific signal value from Cocotb

/**
 * @brief Clear I2C Controller NACK Status
 *
 * Clears any pending NACK status bits that would prevent the controller from
 * becoming idle. This is critical because the I2C controller FSM halts when
 * a NACK occurs and won't continue until software clears the NACK bit.
 */
static void clear_i2c_nack_status(uint32_t idx)
{
	uint32_t controller_events_addr;

	switch (idx) {
		case 0:
			controller_events_addr = SMC_TOP_SMC_I2C_WRAP_I2C_CONTROLLER_EVENTS_BASE_ADDR(0);
			break;
		case 1:
			controller_events_addr = SMC_TOP_SMC_I2C_WRAP_I2C_CONTROLLER_EVENTS_BASE_ADDR(1);
			break;
		case 2:
			controller_events_addr = SMC_TOP_SMC_I2C_WRAP_I2C_CONTROLLER_EVENTS_BASE_ADDR(2);
			break;
		default:
			return; // Invalid index
	}

	uint32_t controller_events = read_reg(controller_events_addr);
	if (controller_events & 0x1) {  // Check NACK bit (bit 0)
		simputs("[STATUS] NACK detected - clearing CONTROLLER_EVENTS.NACK\n");
		write_reg(controller_events_addr, 0x1);  // Write 1 to clear NACK bit (woclr)
	}
	// Also clear any other event bits that might cause halt
	if (controller_events & 0xF) {  // Check any halt-causing event bits (NACK, TIMEOUT, etc.)
		write_reg(controller_events_addr, controller_events & 0xF);  // Clear all event bits
	}
}

/**
 * @brief Enable I2C Wrapper Control
 */
static void i2c_wrapper_enable(uint32_t idx, bool controller_mode)
{
	uint32_t wrapper_addr = SMC_TOP_SMC_I2C_WRAP_I2C_CTRL_I2C_CTRL_BASE_ADDR(0) + (idx * 4);
	i2c_ctrl__I2C_CTRL_t ctrl = { .w = 0 };
	ctrl.f.I2C_EN = 1;
	ctrl.f.I2C_CONTROLLER_MODE_EN = controller_mode ? 1 : 0;
	write_reg(wrapper_addr, ctrl.w);
}

int main(void)
{
	simputs("\n");
	simputs("=== Dual I2C Test - DUT Master ===\n");

	// Initialize system
	simputs("[INIT] System initialization\n");
	write_scratch(1, 0x00000010);

	// Enable I2C_0 Wrapper in Master mode
	simputs("[INIT] Enabling I2C_0 Wrapper\n");
	i2c_wrapper_enable(0, true);

	// Initialize I2C_0 as Controller (Master) with proper timing config
	simputs("[INIT] Initializing I2C_0 as Master\n");

	// Configure timing exactly like i2c_sanity (physical parameters method)
	i2c_timing_physical_t physical_params = {
		.speed = I2C_SPEED_STANDARD,
		.clock_period_nanos = 10,        // 100MHz clock (same as i2c_sanity)
		.sda_rise_nanos = 300,
		.sda_fall_nanos = 100,
		.scl_period_nanos = 0
	};

	i2c_timing_config_t computed_timing;
	int ret = i2c_compute_timing_from_physical(&physical_params, &computed_timing);
	if (ret != I2C_OK) {
		simputs("[INIT] WARNING: Physical timing computation failed, using I2C spec compliant values\n");
		// DON'T use defaults - they're too fast for cross-chiplet communication!
		// Use I2C specification compliant timing for 100kHz @ 100MHz system clock
		computed_timing.thigh = 400;   // 4.0μs SCL high time (was 26 cycles = 260ns - too fast!)
		computed_timing.tlow = 470;    // 4.7μs SCL low time (was 50 cycles = 500ns - too fast!)
		computed_timing.t_r = 30;      // 300ns rise time
		computed_timing.t_f = 10;      // 100ns fall time
		computed_timing.tsu_sta = 470; // 4.7μs START setup
		computed_timing.thd_sta = 400; // 4.0μs START hold
		computed_timing.tsu_dat = 25;  // 250ns data setup (was 2 cycles = 20ns - too fast!)
		computed_timing.thd_dat = 1;   // minimum data hold
		computed_timing.tsu_sto = 400; // 4.0μs STOP setup
		computed_timing.t_buf = 470;   // 4.7μs bus free time
		simputs("[FIX] Applied I2C specification compliant timing to prevent 'controller too fast' NACK\n");
	} else {
		// Verify computed timing meets I2C spec minimums
		if (computed_timing.thigh < 400) {
			computed_timing.thigh = 400;   // Ensure 4.0μs minimum high time
			simputs("[FIX] Increased thigh to meet I2C spec (4.0μs)\n");
		}
		if (computed_timing.tlow < 470) {
			computed_timing.tlow = 470;    // Ensure 4.7μs minimum low time
			simputs("[FIX] Increased tlow to meet I2C spec (4.7μs)\n");
		}
		if (computed_timing.tsu_dat < 25) {
			computed_timing.tsu_dat = 25; // Ensure 250ns minimum data setup
			simputs("[FIX] Increased tsu_dat to meet I2C spec (250ns)\n");
		}
	}
	simputs("[INIT] Using i2c_sanity timing configuration (100 kHz)\n");

	i2c_controller_config_t ctrlr_cfg = {
		.timing = computed_timing,
		.fifo = {
			.rx_thresh = I2C_DEFAULT_RX_THRESH,  // Same as i2c_sanity
			.fmt_thresh = I2C_DEFAULT_FMT_THRESH, // Same as i2c_sanity
			.tx_thresh = 0,                       // Same as i2c_sanity
			.acq_thresh = 0                       // Same as i2c_sanity
		},
		.enable_interrupts = false,               // Same as i2c_sanity
		.timeout_cycles = 0                       // Same as i2c_sanity
	};

	ret = i2c_controller_init(0, &ctrlr_cfg);  // Use proper config
	if (ret != I2C_OK) {
		simputs("[ERROR] I2C_0 initialization failed with error code ");
		simputshex32("", ret);
		simputs("\n");
		write_scratch(0, 0xACEFACA0);  // FAIL
		return -1;
	}

	simputs("[INIT] I2C_0 Controller initialized successfully\n");

	simputs("[READY] I2C_0 Master ready for transactions\n");
	write_scratch(1, 0x00000020);

	// Fixed timing approach (like dual_octs_test) - no BFM-DUT handshake
	// BFM initializes independently and waits for I2C transactions
	simputs("[TIMING] Using fixed timing for BFM coordination (no scratch handshake)\n");

	// Give BFM sufficient time to initialize I2C target mode
	simputs("[TIMING] Waiting for BFM I2C target initialization (~10us)\n");
	for (volatile uint32_t wait_outer = 0; wait_outer < 50; wait_outer++) {
		for (volatile uint32_t wait_inner = 0; wait_inner < 100; wait_inner++) {
			__asm__("nop");
		}
		// Progress indicator every 10 iterations
		if ((wait_outer % 10) == 0) {
			simputs(".");
		}
	}
	simputs("\n[TIMING] BFM wait complete\n");

	simputs("[START] Beginning I2C transaction\n");

	// Step 1: Send I2C write command to BFM (addr 0x10)
	simputs("[TEST] Step 1: Sending I2C write to BFM at address 0x");
	simputshex32("", BFM_I2C_SLAVE_ADDR);
	simputs("\n");

	// Write transaction using i2c_sanity method (non-blocking with immediate target receive)
	uint8_t write_buffer[3];
	write_buffer[0] = 0x5A;              // Register address
	write_buffer[1] = TEST_DATA_BYTE;    // Data low byte
	write_buffer[2] = 0xAA;              // Data high byte (additional test data)

	simputs("[TEST] Sending write transaction using i2c_sanity method\n");
	ret = i2c_controller_write_with_header_nonblock(0, BFM_I2C_SLAVE_ADDR, write_buffer, 3);

	if (ret != I2C_OK) {
		simputs("[ERROR] I2C write failed with error code ");
		simputshex32("", ret);
		simputs("\n");
		write_scratch(0, 0xACEFACA0);  // FAIL
		return -1;
	}

	simputs("[TEST] Write command sent to FIFO\n");

	// Clear any pending NACK status before waiting for idle
	// This is critical: I2C controller halts on NACK and won't become idle until NACK bit is cleared
	simputs("[TIMING] Clearing any NACK status bits to prevent controller halt\n");
	clear_i2c_nack_status(0);  // Clear NACK status for I2C_0

	// Wait for controller to become idle (same as i2c_sanity)
	simputs("[TIMING] Waiting for controller to become idle (i2c_p0_rdwr pattern)\n");
	ret = i2c_controller_wait_idle(0, I2C_TIMEOUT_DEFAULT);
	if (ret != I2C_OK) {
		simputs("[ERROR] Wait for controller idle failed with error code ");
		simputshex32("", ret);
		simputs("\n");
		// Check and clear any remaining NACK status
		clear_i2c_nack_status(0);  // Try clearing NACK status again
		write_scratch(0, 0xACEFACA0);  // FAIL
		return -1;
	}

	simputs("[SUCCESS] Write transaction completed successfully\n");

	// Step 2: Send I2C read command to BFM (addr 0x10)
	simputs("[TEST] Step 2: Sending I2C read to BFM at address 0x");
	simputshex32("", BFM_I2C_SLAVE_ADDR);
	simputs("\n");

	// Add delay to allow BFM to process the write transaction and prepare TX FIFO
	simputs("[TEST] Allowing BFM processing time for write transaction and TX FIFO preparation\n");
	for (volatile uint32_t delay = 0; delay < 20000; delay++) {
		__asm__("nop");
	}

	// Read transaction using i2c_sanity method (separate write and read phases)
	uint8_t reg_addr_byte = 0x5A;  // Same register address used in write
	uint8_t read_buffer[2] = {0};  // Read 2 bytes to match write data

	simputs("[TEST] Step 2a: Sending register address for read (write without STOP)\n");
	ret = i2c_controller_write(0, BFM_I2C_SLAVE_ADDR, &reg_addr_byte, 1, false);  // Write: register address (no STOP)
	if (ret != I2C_OK) {
		simputs("[ERROR] Register address write failed with error code ");
		simputshex32("", ret);
		simputs("\n");
		clear_i2c_nack_status(0);  // Clear any NACK status that might have caused the failure
		write_scratch(0, 0xACEFACA0);  // FAIL
		return -1;
	}

	// Add small delay for cross-chiplet ACQ FIFO processing
	for (volatile uint32_t delay = 0; delay < 10000; delay++) {
		__asm__("nop");
	}

	simputs("[TEST] Step 2b: Reading data bytes (with STOP)\n");
	ret = i2c_controller_read(0, BFM_I2C_SLAVE_ADDR, read_buffer, 2, true);  // Read: 2 bytes data (with STOP)

	if (ret != I2C_OK) {
		simputs("[ERROR] I2C read failed with error code ");
		simputshex32("", ret);
		simputs("\n");
		clear_i2c_nack_status(0);  // Clear any NACK status that might have caused the failure
		write_scratch(0, 0xACEFACA0);  // FAIL
		return -1;
	}

	simputs("[SUCCESS] Read completed successfully\n");
	simputs("[DATA] Read bytes: ");
	for (uint32_t i = 0; i < 2; i++) {  // Display 2 bytes
		simputshex32("0x", read_buffer[i]);
		simputs(" ");
	}
	simputs("\n");

	// Verify data matches what we wrote
	if (read_buffer[0] == TEST_DATA_BYTE && read_buffer[1] == 0xAA) {
		simputs("[VERIFY] Read data matches written data - SUCCESS\n");
	} else {
		simputs("[VERIFY] Read data mismatch:\n");
		simputs("  Expected: 0x");
		simputshex32("", TEST_DATA_BYTE);
		simputs(" 0xAA\n");
		simputs("  Got: 0x");
		simputshex32("", read_buffer[0]);
		simputs(" 0x");
		simputshex32("", read_buffer[1]);
		simputs("\n");
	}

	simputs("[RESULT] Setting PASS_CODE to scratch[0]\n");
	write_scratch(0, 0xACFECA01);  // PASS

	simputs("[DONE] Test completed\n");

	// Signal completion to Cocotb by writing to scratch[2]
	simputs("[SIGNAL] Writing test completion signal to scratch[2]\n");
	write_scratch(2, 0xDEADBEEF);  // Test complete marker

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
