/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/**
 * @file main.c
 * @brief I2C P0 Read-Write Test - Internal I2C Communication
 *
 * =============================================================================
 * Test Configuration: I2C_0 Controller <-> I2C_1 Target
 * =============================================================================
 *
 * Approach: Configure I2C_0 as Controller (Master) and I2C_1 as Target (Slave)
 *           Use i2c_opentitan functions for write/read transactions
 *
 * Steps:
 *   1. Configure I2C_0 Controller settings (speed, address mode)
 *   2. Configure I2C_1 Target settings (address, FIFO thresholds)
 *   3. Write known data pattern from Controller to Target
 *   4. Read back data from Target to Controller
 *   5. Compare written and read data
 *
 * =============================================================================
 * Test Architecture: Two-Level I2C Control
 * =============================================================================
 *
 * LEVEL 1: Wrapper Control (0xC0009E00)
 *   - Controls GPIO pad multiplexing
 *   - Selects I2C mode (Controller/Target)
 *
 * LEVEL 2: IP Control (0xC0009000 + 0x200*idx)
 *   - OpenTitan I2C IP protocol layer
 *   - Handles timing, FIFO, interrupts, transactions
 *
 * =============================================================================
 */

#include <stdint.h>
#include <stdbool.h>

#include "smc_io.h"
#include "smc_test.h"
#include "i2c_opentitan.h"


//=============================================================================
// Helper Functions
//=============================================================================

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

	simputshex32("  Wrapper[", idx);
	simputshex32("] enabled: addr=", wrapper_addr);
	simputs(", mode=");
	simputs(controller_mode ? "Controller" : "Target");
	simputs("\n");
}

//=============================================================================
// Main Test
//=============================================================================

int main(void)
{
	const uint32_t CONTROLLER_IDX = 0;  // I2C_0 as Controller
	const uint32_t TARGET_IDX = 1;      // I2C_1 as Target
	const uint8_t TARGET_ADDR = 0x10;   // Target address (7-bit)
	const uint8_t REG_ADDR = 0x5A;      // Register address for write/read
	const uint16_t TEST_DATA = 0x5A5A;  // Known data pattern to write (2 bytes)
	uint16_t read_value = 0;            // Data read back from register
	int ret;

	//-------------//
	// RESET & PLL //
	//-------------//

	simputs("\n");
	simputs("################################################\n");
	simputs("##   I2C P0 Read-Write Test - Internal I2C    ##\n");
	simputs("################################################\n");
	simputs("\n");

	//=========================================================================
	// Step 1: System Initialization
	//=========================================================================
	write_scratch(1, 0x00000010);
	simputs("Step 1: System Initialization\n");
	simputs("  System ready\n");
	write_scratch(1, 0x00000011);

	//=========================================================================
	// Step 2: LEVEL 1 - Wrapper Control Enable
	//         Enable GPIO pad mux for both Controller and Target
	//=========================================================================
	write_scratch(1, 0x00000020);
	simputs("\nStep 2: LEVEL 1 - Wrapper Control Enable\n");
	simputs("  Enabling I2C_0 Controller (Master mode)...\n");
	i2c_wrapper_enable(CONTROLLER_IDX, true);

	simputs("  Enabling I2C_1 Target (Slave mode)...\n");
	i2c_wrapper_enable(TARGET_IDX, false);

	write_scratch(1, 0x00000021);

	//=========================================================================
	// Step 3: LEVEL 2 - I2C IP Initialization
	//=========================================================================
	write_scratch(1, 0x00000030);
	simputs("\nStep 3: LEVEL 2 - I2C IP Initialization\n");

	// Configure Controller timing
	i2c_timing_physical_t physical_params = {
		.speed = I2C_SPEED_STANDARD,
		.clock_period_nanos = 10,
		.sda_rise_nanos = 300,
		.sda_fall_nanos = 100,
		.scl_period_nanos = 0
	};

	i2c_timing_config_t computed_timing;
	ret = i2c_compute_timing_from_physical(&physical_params, &computed_timing);
	if (ret != I2C_OK) {
		simputs("  WARNING: Physical timing computation failed, using defaults\n");
		i2c_get_default_timing(I2C_SPEED_STANDARD, 100, &computed_timing);
	}

	// Initialize Controller
	simputs("  Initializing I2C_0 Controller...\n");
	i2c_controller_config_t ctrlr_cfg = {
		.timing = computed_timing,
		.fifo = {
			.rx_thresh = I2C_DEFAULT_RX_THRESH,
			.fmt_thresh = I2C_DEFAULT_FMT_THRESH,
			.tx_thresh = 0,
			.acq_thresh = 0
		},
		.enable_interrupts = false,
		.timeout_cycles = 0
	};

	ret = i2c_controller_init(CONTROLLER_IDX, &ctrlr_cfg);
	if (ret != I2C_OK) {
		simputs("  ERROR: Controller init failed\n");
		write_scratch(0, 0xBAD00031);
		test_fail(0);
	}
	simputs("  Controller initialized successfully\n");

	// Initialize Target
	simputs("  Initializing I2C_1 Target...\n");
	i2c_target_config_t tgt_cfg = {
		.address0 = TARGET_ADDR,
		.mask0 = 0x7F,  // Exact match
		.address1 = 0,
		.mask1 = 0,
		.timing = computed_timing,
		.fifo = {
			.tx_thresh = I2C_DEFAULT_TX_THRESH,
			.acq_thresh = I2C_DEFAULT_ACQ_THRESH,
			.rx_thresh = 0,
			.fmt_thresh = 0
		},
		.enable_interrupts = false,
		.ack_ctrl_mode = false,
		.tx_stretch_ctrl = false,  // Automatic TX Stretch mode (hardware auto-manages, no SW intervention needed)
		.timeout_cycles = 0
	};

	ret = i2c_target_init(TARGET_IDX, &tgt_cfg);
	if (ret != I2C_OK) {
		simputs("  ERROR: Target init failed\n");
		write_scratch(0, 0xBAD00032);
		test_fail(0);
	}
	simputs("  Target initialized successfully\n");

	write_scratch(1, 0x00000031);

	// Explicitly set ACQ_START_STOP_EN bit to 1
	uint32_t base = i2c_get_base(TARGET_IDX);
	i2c__CTRL_t ctrl = {
		.w = read_reg(base + (SMC_TOP_SMC_I2C_WRAP_I2C_CTRL_BASE_ADDR(0) - SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)))
	};
	ctrl.w |= (1 << 7);  // Set ACQ_START_STOP_EN bit (bit 7)
	write_reg(base + (SMC_TOP_SMC_I2C_WRAP_I2C_CTRL_BASE_ADDR(0) - SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)), ctrl.w);
	simputs("  Speed: Standard mode (100 kHz)\n");
	simputs("  Address mode: 7-bit addressing\n");

	//=========================================================================
	// Step 4: Write preset data from Controller to Target
	//         Data: 0x5A5A, Register: 0x5A
	//=========================================================================
	write_scratch(1, 0x00000040);
	simputs("\nStep 4: Write Preset Data from Controller to Target\n");
	simputs("  Register address: 0x");
	simputshex32("", REG_ADDR);
	simputs("\n");
	simputs("  Data to write: 0x");
	simputshex32("", TEST_DATA);
	simputs("\n");
	simputs("  Target address: 0x");
	simputshex32("", TARGET_ADDR);
	simputs("\n");

	// Prepare write buffer: register address + data (2 bytes)
	uint8_t write_buffer[3];
	write_buffer[0] = REG_ADDR;              // Register address
	write_buffer[1] = TEST_DATA & 0xFF;      // Data low byte
	write_buffer[2] = (TEST_DATA >> 8) & 0xFF; // Data high byte

	// Controller write transaction (non-blocking to prevent ACQ FIFO overflow)
	// For internal I2C communication, Target must receive immediately after Controller write
	// to prevent ACQ FIFO overflow and SCL stretching
	simputs("  Controller sending write transaction (non-blocking)...\n");
	ret = i2c_controller_write_with_header_nonblock(CONTROLLER_IDX, TARGET_ADDR,
	                                                 write_buffer, 3);
	if (ret != I2C_OK) {
		simputs("  ERROR: Controller write failed with error code ");
		simputshex32("", ret);
		simputs("\n");
		write_scratch(0, 0xBAD00040);
		test_fail(0);
	}

	simputs("  Write command sent to FIFO\n");

	// Target receive transaction immediately (without waiting for Controller idle)
	// This prevents ACQ FIFO overflow which would cause SCL stretching and deadlock
	simputs("  Target receiving transaction (immediate read)...\n");
	uint8_t recv_buffer[256];
	uint32_t received_len = 0;
	ret = i2c_target_receive_transaction(TARGET_IDX, recv_buffer,
	                                     sizeof(recv_buffer), &received_len,
	                                     I2C_TIMEOUT_DEFAULT);
	if (ret != I2C_OK) {
		simputs("  ERROR: Target receive failed\n");
		write_scratch(0, 0xBAD00042);
		test_fail(0);
	}

	// Wait for controller to become idle after target receive completes
	ret = i2c_controller_wait_idle(CONTROLLER_IDX, I2C_TIMEOUT_DEFAULT);
	if (ret != I2C_OK) {
		simputs("  ERROR: Wait for controller idle failed with error code ");
		simputshex32("", ret);
		simputs("\n");
		write_scratch(0, 0xBAD00041);
		test_fail(0);
	}

	simputshex32("  Target received ", received_len);
	simputs(" bytes\n");

	// Verify received data
	simputs("  [VERIFY] Verifying received data:\n");
	simputs("    Expected length: 3 bytes\n");
	simputshex32("    Received length: ", received_len);
	simputs(" bytes\n");
	simputs("    Expected register address: 0x");
	simputshex32("", REG_ADDR);
	simputs("\n");
	simputs("    Received register address: 0x");
	simputshex32("", recv_buffer[0]);
	simputs("\n");
	simputs("    Expected data low byte: 0x");
	simputshex32("", TEST_DATA & 0xFF);
	simputs("\n");
	simputs("    Received data low byte: 0x");
	simputshex32("", recv_buffer[1]);
	simputs("\n");
	simputs("    Expected data high byte: 0x");
	simputshex32("", (TEST_DATA >> 8) & 0xFF);
	simputs("\n");
	simputs("    Received data high byte: 0x");
	simputshex32("", recv_buffer[2]);
	simputs("\n");

	if (received_len != 3) {
		simputs("  ERROR: Target received incorrect length!\n");
		simputshex32("    Expected: 3, Got: ", received_len);
		simputs("\n");
		write_scratch(0, 0xBAD00043);
		test_fail(0);
	}

	if (recv_buffer[0] != REG_ADDR) {
		simputs("  ERROR: Target received incorrect register address!\n");
		simputs("    Expected: 0x");
		simputshex32("", REG_ADDR);
		simputs(", Got: 0x");
		simputshex32("", recv_buffer[0]);
		simputs("\n");
		write_scratch(0, 0xBAD00043);
		test_fail(0);
	}

	uint16_t received_data = recv_buffer[1] | (recv_buffer[2] << 8);
	if (received_data != TEST_DATA) {
		simputs("  ERROR: Target received incorrect data!\n");
		simputs("    Expected: 0x");
		simputshex32("", TEST_DATA);
		simputs(", Got: 0x");
		simputshex32("", received_data);
		simputs("\n");
		write_scratch(0, 0xBAD00043);
		test_fail(0);
	}

	simputs("  [VERIFY] Write verification PASSED!\n");
	simputs("    Register address: 0x");
	simputshex32("", REG_ADDR);
	simputs(" (correct)\n");
	simputs("    Written data: 0x");
	simputshex32("", TEST_DATA);
	simputs(" (correct)\n");
	simputs("  Write transaction completed successfully\n");
	write_scratch(1, 0x00000041);  // Signal to TB: Write complete

	//=========================================================================
	// Step 5: Prepare Target for read operation
	//         Pre-load TX FIFO with data to be read
	//=========================================================================
	write_scratch(1, 0x00000050);
	simputs("\nStep 5: Prepare Target for Read Operation\n");

	// CRITICAL: Follow i2c_target_test.c correct sequence to prevent unhandled_tx_stretch_event
	// Reference: i2c_target_test/src/main.c:418-459, RTL i2c_target_fsm.sv:666-667
	// Correct order per OpenTitan RTL (to avoid unhandled_tx_stretch_event_i = 1):
	// 1. Pre-load TX FIFO FIRST
	// 2. Clear TARGET_EVENTS (clears events from TX FIFO pre-load)
	// 3. Reset ACQ FIFO
	// 4. Verify ACQ FIFO is empty
	// 5. Wait for Target to be idle
	// This sequence ensures unhandled_tx_stretch_event_i = 0 before read request
	simputs("  Preparing Target for read transaction (correct sequence to clear stretch events)...\n");

	// Step 1: Pre-load TX FIFO FIRST
	// CRITICAL: Pre-load TX FIFO BEFORE read request arrives
	// When Controller sends read request, Target FSM immediately reads from TX FIFO
	// If TX FIFO is empty, Target sends 0xFF (default value)
	simputshex32("", TEST_DATA);
	simputs("\n");

	uint8_t tx_data[2];
	tx_data[0] = TEST_DATA & 0xFF;      // Data low byte
	tx_data[1] = (TEST_DATA >> 8) & 0xFF; // Data high byte

	uint32_t tx_bytes = i2c_target_transmit(TARGET_IDX, tx_data, 2);
	if (tx_bytes != 2) {
		simputs("  ERROR: Failed to pre-load Target TX FIFO\n");
		write_scratch(0, 0xBAD00050);
		test_fail(0);
	}

	simputs("  Target TX FIFO pre-loaded with 2 bytes\n");

	// Step 2: Clear TARGET_EVENTS AFTER TX FIFO pre-load
	// CRITICAL: Pre-loading TX FIFO may generate TARGET_EVENTS
	// These must be cleared to prevent unhandled_tx_stretch_event_i = 1
	// Reference: i2c_target_test/src/main.c:434-442
	uint32_t target_events = i2c_get_target_events(TARGET_IDX);
	if (target_events != 0) {
		simputs("  Clearing unhandled TARGET_EVENTS: 0x");
		simputshex32("", target_events);
		simputs("\n");
		i2c_clear_target_events(TARGET_IDX, 0xFFFFFFFF);  // Clear all events
	}
	simputs("  TARGET_EVENTS cleared (unhandled_tx_stretch_event_i = 0)\n");

	// Step 3: Reset ACQ FIFO to ensure it's empty before read request
	// According to OpenTitan RTL, ACQ FIFO depth > 1 will trigger stretch_tx
	// Reference: i2c_target_fsm.sv:666-667
	i2c_reset_fifos(TARGET_IDX, false, false, false, true);  // Reset ACQ FIFO only
	simputs("  ACQ FIFO reset using ACQRST\n");

	// Step 4: Verify ACQ FIFO is empty after reset
	if (!i2c_target_acq_fifo_empty(TARGET_IDX)) {
		simputs("  WARNING: ACQ FIFO not empty after reset, draining...\n");
		uint32_t base = i2c_get_base(TARGET_IDX);
		while (!i2c_target_acq_fifo_empty(TARGET_IDX)) {
			(void)read_reg(base + (SMC_TOP_SMC_I2C_WRAP_I2C_ACQDATA_BASE_ADDR(0) - SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)));
		}
	}
	simputs("  ACQ FIFO confirmed empty\n");

	write_scratch(1, 0x00000051);

	// Step 5: Wait for Target to be idle before read request
	// This ensures Target FSM is ready to handle the read transaction
	// CRITICAL: Target must be in Idle state with SCL released (high) before read request
	uint32_t target_base = i2c_get_base(TARGET_IDX);
	uint32_t idle_wait_count = 0;
	const uint32_t IDLE_WAIT_TIMEOUT = 10000;
	while (idle_wait_count < IDLE_WAIT_TIMEOUT) {
		i2c__STATUS_t status = {
			.w = read_reg(target_base + (SMC_TOP_SMC_I2C_WRAP_I2C_STATUS_BASE_ADDR(0) - SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)))
		};
		if (status.f.TARGETIDLE) {
			// Additional delay to ensure SCL is fully released
			for (volatile int i = 0; i < 500; i++);
			break;
		}
		idle_wait_count++;
		if (idle_wait_count % 1000 == 0) {
			for (volatile int i = 0; i < 100; i++);  // Small delay
		}
	}
	if (idle_wait_count >= IDLE_WAIT_TIMEOUT) {
		simputs("  WARNING: Target did not become idle before read request\n");
	} else {
		simputs("  Target confirmed idle (SCL should be released)\n");
	}

	// Final check: Verify no unhandled TARGET_EVENTS before read request
	target_events = i2c_get_target_events(TARGET_IDX);
	if (target_events != 0) {
		simputs("  WARNING: TARGET_EVENTS not zero before read: 0x");
		simputshex32("", target_events);
		simputs("\n");
		i2c_clear_target_events(TARGET_IDX, 0xFFFFFFFF);
	}
	simputs("  Target ready for read request (all conditions satisfied)\n");

	//=========================================================================
	// Step 6: Read data from Target to Controller
	//=========================================================================
	write_scratch(1, 0x00000060);
	simputs("\nStep 6: Read Data from Target to Controller\n");
	simputs("  Reading from register address: 0x");
	simputshex32("", REG_ADDR);
	simputs("\n");

	// CRITICAL: For write-then-read sequence with OpenTitan I2C
	// 1. Write phase: Controller sends register address -> Target ACQ FIFO
	// 2. Target must process ACQ FIFO (drain register address entry)
	// 3. Read phase: Controller reads data <- Target TX FIFO
	//
	// Use separate i2c_controller_write and i2c_controller_read calls !!!!
	// to allow manual ACQ FIFO processing between phases
	uint8_t reg_addr_byte = REG_ADDR;
	uint8_t read_buffer[2];

	// Start write phase (non-blocking): send register address
	ret = i2c_controller_write(CONTROLLER_IDX, TARGET_ADDR,
	                           &reg_addr_byte, 1, false);  // Write: register address (no STOP)
	if (ret != I2C_OK) {
		simputs("  ERROR: Controller write (register address) failed\n");
		write_scratch(0, 0xBAD00061);
		test_fail(0);
	}

	// CRITICAL: Process ACQ FIFO entry (register address) from Target
	// This ensures Target FSM properly handles the write phase before read phase
	simputs("  Processing register address from Target ACQ FIFO...\n");
	uint32_t acq_wait_count = 0;
	const uint32_t ACQ_WAIT_TIMEOUT = 10000;
	bool found_reg_addr = false;

	// Wait for register address to appear in ACQ FIFO
	// Need to skip START/RESTART signals and only read DATA signals
	while (acq_wait_count < ACQ_WAIT_TIMEOUT && !found_reg_addr) {
		i2c__STATUS_t status = {
			.w = read_reg(target_base + (SMC_TOP_SMC_I2C_WRAP_I2C_STATUS_BASE_ADDR(0) - SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)))
		};
		if (!status.f.ACQEMPTY) {
			// Read ACQ FIFO entry
			i2c__ACQDATA_t acqdata = {
				.w = read_reg(target_base + (SMC_TOP_SMC_I2C_WRAP_I2C_ACQDATA_BASE_ADDR(0) - SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)))
			};
			uint32_t signal = acqdata.f.SIGNAL;
			uint8_t abyte = (uint8_t)acqdata.f.ABYTE;

			// Skip START/RESTART signals, only process DATA signals
			if (signal == 0) {  // I2C_ACQ_SIGNAL_DATA
				simputs("    Received register address from ACQ FIFO: 0x");
				simputshex32("", abyte);
				simputs("\n");
				found_reg_addr = true;
			} else {
				simputs("    Skipped ACQ signal ");
				simputshex32("", signal);
				simputs(", abyte=0x");
				simputshex32("", abyte);
				simputs("\n");
				// Continue to next ACQ entry
			}
		} else {
			acq_wait_count++;
			if (acq_wait_count % 1000 == 0) {
				for (volatile int i = 0; i < 100; i++);  // Small delay
			}
		}
	}
	if (!found_reg_addr) {
		simputs("    WARNING: Register address not received in ACQ FIFO\n");
	}

	// Now perform read phase
	simputs("  Starting read phase...\n");
	ret = i2c_controller_read(CONTROLLER_IDX, TARGET_ADDR,
	                          read_buffer, 2, true);  // Read: 2 bytes data (with STOP)
	if (ret != I2C_OK) {
		simputs("  ERROR: Controller read failed\n");
		write_scratch(0, 0xBAD00062);
		test_fail(0);
	}

	read_value = read_buffer[0] | (read_buffer[1] << 8);

	simputs("  Read completed successfully\n");
	simputs("  [VERIFY] Read data verification:\n");
	simputs("    Read data byte[0] (low): 0x");
	simputshex32("", read_buffer[0]);
	simputs("\n");
	simputs("    Read data byte[1] (high): 0x");
	simputshex32("", read_buffer[1]);
	simputs("\n");
	simputs("    Read data (combined): 0x");
	simputshex32("", read_value);
	simputs("\n");
	write_scratch(1, 0x00000061);

	//=========================================================================
	// Step 7: Compare written and read data
	//=========================================================================
	write_scratch(1, 0x00000070);
	simputs("\nStep 7: Compare Written and Read Data\n");
	simputs("  ========================================\n");
	simputs("  [VERIFY] Final Data Comparison:\n");
	simputs("  ========================================\n");
	simputs("    Written data: 0x");
	simputshex32("", TEST_DATA);
	simputs(" (expected)\n");
	simputs("    Read data:   0x");
	simputshex32("", read_value);
	simputs(" (actual)\n");
	simputs("  ========================================\n");

	if (read_value != TEST_DATA) {
		simputs("  [ERROR] Data mismatch detected!\n");
		simputs("    Expected: 0x");
		simputshex32("", TEST_DATA);
		simputs("\n");
		simputs("    Got:      0x");
		simputshex32("", read_value);
		simputs("\n");
		simputs("    Difference: 0x");
		simputshex32("", TEST_DATA ^ read_value);
		simputs("\n");
		write_scratch(0, 0xBAD00070);
		test_fail(0);
	}

	simputs("  [SUCCESS] Data verification PASSED!\n");
	simputs("    Written and read data match perfectly: 0x");
	simputshex32("", TEST_DATA);
	simputs("\n");
	simputs("  ========================================\n");
	write_scratch(1, 0x00000071);

	//=========================================================================
	// Test Complete - Signal to testbench
	//=========================================================================
	write_scratch(1, 0x00000090);

	write_scratch(1, 0xEBEDEBE4);
	simputs("\n");
	simputs("################################################\n");
	simputs("##           ALL TESTS PASSED                ##\n");
	simputs("################################################\n");
	simputs("\n");
	simputs("Summary:\n");
	simputs("  - I2C_0 (Controller): @ 0xC0009000\n");
	simputs("  - I2C_1 (Target):    @ 0xC0009200, Addr 0x");
	simputshex32("", TARGET_ADDR);
	simputs("\n");
	simputs("  - Register Address:   0x");
	simputshex32("", REG_ADDR);
	simputs("\n");
	simputs("  - Written Data:       0x");
	simputshex32("", TEST_DATA);
	simputs("\n");
	simputs("  - Read Data:          0x");
	simputshex32("", read_value);
	simputs("\n");
	simputs("  - Verification:       PASS\n");
	simputs("\n################################################\n");

	// Set scratch[0] to TEST_PASS before test_pass() to ensure monitor_task can detect it
	write_scratch(0, TEST_PASS);

	test_pass(0);

	simputs("\n=== Test Complete ===\n");

	// Infinite loop to keep CPU in WFI state after test completion
	while (true) {
		__asm__("wfi");
	}

	return 0;
}
