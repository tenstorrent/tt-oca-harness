/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/**
 * @file main.c
 * @brief I2C FIFO Full/Empty Status Test
 *
 * Test Approach: Test all four FIFOs (FMT, RX, TX, ACQ) full and empty states
 * without external I2C transmission
 *
 * Test Steps:
 * 1. Test FMT FIFO: Fill to full, check STATUS.FMTFULL, reset to empty, check STATUS.FMTEMPTY
 * 2. Test RX FIFO: Check empty state (requires I2C read, skipped for no-transmission requirement)
 * 3. Test TX FIFO: Fill to full, check STATUS.TXFULL, reset to empty, check STATUS.TXEMPTY
 * 4. Test ACQ FIFO: Check empty state (requires I2C write, skipped for no-transmission requirement)
 */

#include <stdint.h>
#include <stdbool.h>

#include "smc_io.h"
#include "smc_test.h"
#include "i2c_opentitan.h"

// Test parameters
#define CONTROLLER_IDX 0  // I2C_0 for Controller mode (FMT, RX FIFO)
#define TARGET_IDX 1      // I2C_1 for Target mode (TX, ACQ FIFO)
#define FMT_FIFO_DEPTH 64
#define TX_FIFO_DEPTH 64

/**
 * @brief Enable I2C Wrapper Control (LEVEL 1)
 */
static void i2c_wrapper_enable(uint32_t idx, bool controller_mode)
{
	uint32_t wrapper_addr = SMC_TOP_SMC_I2C_WRAP_I2C_CTRL_I2C_CTRL_BASE_ADDR(0) + (idx * 4);

	i2c_ctrl__I2C_CTRL_t ctrl = { .w = 0 };
	ctrl.f.I2C_EN = 1;
	ctrl.f.I2C_CONTROLLER_MODE_EN = controller_mode ? 1 : 0;

	write_reg(wrapper_addr, ctrl.w);
}

/**
 * @brief Test FMT FIFO full and empty states
 */
static int test_fmt_fifo_full_empty(uint32_t idx)
{
	uint32_t base = i2c_get_base(idx);

	simputs("\n=== Test FMT FIFO Full/Empty ===\n");

	// Reset FMT FIFO first
	i2c_reset_fifos(idx, false, true, false, false);
	for (volatile int i = 0; i < 1000; i++);  // Wait for reset to complete

	// Check initial empty state
	i2c__STATUS_t status_initial = {
		.w = read_reg(base + (SMC_TOP_SMC_I2C_WRAP_I2C_STATUS_BASE_ADDR(0) - SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)))
	};
	if (!status_initial.f.FMTEMPTY) {
		simputs("  ERROR: FMT FIFO should be empty after reset\n");
		return I2C_ERROR;
	}
	simputs("  PASS: FMT FIFO is empty after reset\n");

	// Fill FMT FIFO to full
	i2c__FDATA_t fdata = { .w = 0 };
	for (uint32_t i = 0; i < FMT_FIFO_DEPTH + 10; i++) {
		i2c__STATUS_t status_check = {
			.w = read_reg(base + (SMC_TOP_SMC_I2C_WRAP_I2C_STATUS_BASE_ADDR(0) - SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)))
		};
		if (status_check.f.FMTFULL) break;
		fdata.w = 0;
		fdata.f.FBYTE = (uint8_t)(0xAA + i);
		write_reg(base + (SMC_TOP_SMC_I2C_WRAP_I2C_FDATA_BASE_ADDR(0) - SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)), fdata.w);
		if (i >= FMT_FIFO_DEPTH + 5) break;
	}

	// Verify FMT FIFO is full
	i2c__STATUS_t status_full = {
		.w = read_reg(base + (SMC_TOP_SMC_I2C_WRAP_I2C_STATUS_BASE_ADDR(0) - SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)))
	};
	if (!status_full.f.FMTFULL) {
		simputs("  ERROR: FMT FIFO should be full\n");
		return I2C_ERROR;
	}
	simputs("  PASS: FMT FIFO STATUS.FMTFULL is set correctly\n");

	// Reset FMT FIFO to empty
	i2c_reset_fifos(idx, false, true, false, false);
	for (volatile int i = 0; i < 100; i++);

	// Verify FMT FIFO is empty
	i2c__STATUS_t status_empty = {
		.w = read_reg(base + (SMC_TOP_SMC_I2C_WRAP_I2C_STATUS_BASE_ADDR(0) - SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)))
	};
	if (!status_empty.f.FMTEMPTY) {
		simputs("  ERROR: FMT FIFO should be empty after reset\n");
		return I2C_ERROR;
	}
	if (status_empty.f.FMTFULL) {
		simputs("  ERROR: FMT FIFO should not be full after reset\n");
		return I2C_ERROR;
	}
	simputs("  PASS: FMT FIFO STATUS.FMTEMPTY is set correctly after reset\n");

	simputs("  PASS: FMT FIFO test PASSED\n");
	return I2C_OK;
}

/**
 * @brief Test RX FIFO empty state
 * Note: RX FIFO requires I2C read transaction to fill, which is skipped per requirement
 */
static int test_rx_fifo_empty(uint32_t idx)
{
	uint32_t base = i2c_get_base(idx);

	simputs("\n=== Test RX FIFO Empty ===\n");

	// Reset RX FIFO first
	i2c_reset_fifos(idx, true, false, false, false);
	for (volatile int i = 0; i < 100; i++);  // Brief wait for reset to complete

	// Check initial empty state
	i2c__STATUS_t status = {
		.w = read_reg(base + (SMC_TOP_SMC_I2C_WRAP_I2C_STATUS_BASE_ADDR(0) - SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)))
	};
	if (!status.f.RXEMPTY) {
		simputs("  ERROR: RX FIFO should be empty after reset\n");
		return I2C_ERROR;
	}
	if (status.f.RXFULL) {
		simputs("  ERROR: RX FIFO should not be full after reset\n");
		return I2C_ERROR;
	}
	simputs("  PASS: RX FIFO STATUS.RXEMPTY is set correctly\n");

	// Check RX FIFO level
	i2c__HOST_FIFO_STATUS_t fifo_status = {
		.w = read_reg(base + (SMC_TOP_SMC_I2C_WRAP_I2C_HOST_FIFO_STATUS_BASE_ADDR(0) - SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)))
	};
	if (fifo_status.f.RXLVL != 0) {
		simputs("  ERROR: RX FIFO level should be 0 after reset\n");
		return I2C_ERROR;
	}
	simputs("  PASS: RX FIFO empty test PASSED\n");
	return I2C_OK;
}

/**
 * @brief Test TX FIFO full and empty states
 */
static int test_tx_fifo_full_empty(uint32_t idx)
{
	uint32_t base = i2c_get_base(idx);

	simputs("\n=== Test TX FIFO Full/Empty ===\n");

	// Reset TX FIFO first
	i2c_reset_fifos(idx, false, false, true, false);
	for (volatile int i = 0; i < 100; i++);  // Brief wait for reset to complete

	// Check initial empty state
	i2c__STATUS_t status_initial = {
		.w = read_reg(base + (SMC_TOP_SMC_I2C_WRAP_I2C_STATUS_BASE_ADDR(0) - SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)))
	};
	if (!status_initial.f.TXEMPTY) {
		simputs("  ERROR: TX FIFO should be empty after reset\n");
		return I2C_ERROR;
	}
	simputs("  PASS: TX FIFO is empty after reset\n");

	// Fill TX FIFO to full
	i2c__TXDATA_t txdata = { .w = 0 };
	for (uint32_t i = 0; i < TX_FIFO_DEPTH + 10; i++) {
		i2c__STATUS_t status_check = {
			.w = read_reg(base + (SMC_TOP_SMC_I2C_WRAP_I2C_STATUS_BASE_ADDR(0) - SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)))
		};
		if (status_check.f.TXFULL) break;
		txdata.w = 0;
		txdata.f.DATA = (uint8_t)(0xBB + i);
		write_reg(base + (SMC_TOP_SMC_I2C_WRAP_I2C_TXDATA_BASE_ADDR(0) - SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)), txdata.w);
		if (i >= TX_FIFO_DEPTH + 5) break;
	}

	// Verify TX FIFO is full
	i2c__STATUS_t status_full = {
		.w = read_reg(base + (SMC_TOP_SMC_I2C_WRAP_I2C_STATUS_BASE_ADDR(0) - SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)))
	};
	if (!status_full.f.TXFULL) {
		simputs("  ERROR: TX FIFO should be full\n");
		return I2C_ERROR;
	}
	simputs("  PASS: TX FIFO STATUS.TXFULL is set correctly\n");

	// Reset TX FIFO to empty
	i2c_reset_fifos(idx, false, false, true, false);
	for (volatile int i = 0; i < 100; i++);

	// Verify TX FIFO is empty
	i2c__STATUS_t status_empty = {
		.w = read_reg(base + (SMC_TOP_SMC_I2C_WRAP_I2C_STATUS_BASE_ADDR(0) - SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)))
	};
	if (!status_empty.f.TXEMPTY) {
		simputs("  ERROR: TX FIFO should be empty after reset\n");
		return I2C_ERROR;
	}
	if (status_empty.f.TXFULL) {
		simputs("  ERROR: TX FIFO should not be full after reset\n");
		return I2C_ERROR;
	}
	simputs("  PASS: TX FIFO STATUS.TXEMPTY is set correctly after reset\n");

	simputs("  PASS: TX FIFO test PASSED\n");
	return I2C_OK;
}

/**
 * @brief Test ACQ FIFO empty state
 * Note: ACQ FIFO requires I2C write transaction to fill, which is skipped per requirement
 */
static int test_acq_fifo_empty(uint32_t idx)
{
	uint32_t base = i2c_get_base(idx);

	simputs("\n=== Test ACQ FIFO Empty ===\n");

	// Reset ACQ FIFO first
	i2c_reset_fifos(idx, false, false, false, true);
	for (volatile int i = 0; i < 100; i++);  // Brief wait for reset to complete

	// Check initial empty state
	i2c__STATUS_t status = {
		.w = read_reg(base + (SMC_TOP_SMC_I2C_WRAP_I2C_STATUS_BASE_ADDR(0) - SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)))
	};
	if (!status.f.ACQEMPTY) {
		simputs("  ERROR: ACQ FIFO should be empty after reset\n");
		return I2C_ERROR;
	}
	if (status.f.ACQFULL) {
		simputs("  ERROR: ACQ FIFO should not be full after reset\n");
		return I2C_ERROR;
	}
	simputs("  PASS: ACQ FIFO STATUS.ACQEMPTY is set correctly\n");

	// Check ACQ FIFO level
	i2c__TARGET_FIFO_STATUS_t fifo_status = {
		.w = read_reg(base + (SMC_TOP_SMC_I2C_WRAP_I2C_TARGET_FIFO_STATUS_BASE_ADDR(0) - SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)))
	};
	if (fifo_status.f.ACQLVL != 0) {
		simputs("  ERROR: ACQ FIFO level should be 0 after reset\n");
		return I2C_ERROR;
	}
	simputs("  PASS: ACQ FIFO empty test PASSED\n");
	return I2C_OK;
}

int main(void)
{
	int ret;

	// System initialization

	simputs("\n");
	simputs("################################################\n");
	simputs("##      I2C FIFO Full/Empty Status Test       ##\n");
	simputs("################################################\n");
	simputs("\n");

	write_scratch(1, 0x00000010);
	write_scratch(1, 0x00000011);

	// LEVEL 1 - Wrapper Control Enable (Controller Mode for I2C_0)
	write_scratch(1, 0x00000020);
	i2c_wrapper_enable(CONTROLLER_IDX, true);
	write_scratch(1, 0x00000021);

	// LEVEL 2 - I2C IP Initialization (Controller Mode for I2C_0)
	write_scratch(1, 0x00000030);

	// Compute timing parameters
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

	// Initialize I2C as Controller
	i2c_controller_config_t ctrl_cfg = {
		.timing = computed_timing,
		.fifo = {
			.rx_thresh = I2C_DEFAULT_RX_THRESH,
			.fmt_thresh = I2C_DEFAULT_FMT_THRESH
		},
		.enable_interrupts = false
	};

	ret = i2c_controller_init(CONTROLLER_IDX, &ctrl_cfg);
	if (ret != I2C_OK) {
		simputs("  ERROR: Controller init failed\n");
		write_scratch(0, 0xBAD00030);
		test_fail(0);
	}
	write_scratch(1, 0x00000031);

	// LEVEL 1 - Wrapper Control Enable (Target Mode for I2C_1)
	write_scratch(1, 0x00000032);
	i2c_wrapper_enable(TARGET_IDX, false);
	write_scratch(1, 0x00000033);

	// LEVEL 2 - I2C IP Initialization (Target Mode for I2C_1)
	write_scratch(1, 0x00000034);

	// Initialize I2C_1 as Target
	i2c_target_config_t tgt_cfg = {
		.address0 = 0x10,
		.mask0 = 0x7F,
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
		.tx_stretch_ctrl = false,
		.timeout_cycles = 0
	};

	ret = i2c_target_init(TARGET_IDX, &tgt_cfg);
	if (ret != I2C_OK) {
		simputs("  ERROR: Target init failed\n");
		write_scratch(0, 0xBAD00034);
		test_fail(0);
	}
	write_scratch(1, 0x00000035);

	// Explicitly set ACQ_START_STOP_EN bit to 1
	uint32_t base = i2c_get_base(TARGET_IDX);
	i2c__CTRL_t ctrl = {
		.w = read_reg(base + (SMC_TOP_SMC_I2C_WRAP_I2C_CTRL_BASE_ADDR(0) - SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)))
	};
	ctrl.w |= (1 << 7);  // Set ACQ_START_STOP_EN bit (bit 7)
	write_reg(base + (SMC_TOP_SMC_I2C_WRAP_I2C_CTRL_BASE_ADDR(0) - SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)), ctrl.w);

	// Signal setup complete to testbench
	write_scratch(1, 0xEBEDEBE4);

	// Test FMT FIFO
	write_scratch(1, 0x00000040);
	ret = test_fmt_fifo_full_empty(CONTROLLER_IDX);
	if (ret != I2C_OK) {
		simputs("  ERROR: FMT FIFO test failed\n");
		write_scratch(0, 0xBAD00040);
		test_fail(0);
	}
	write_scratch(1, 0x00000041);

	// Test RX FIFO empty
	write_scratch(1, 0x00000050);
	ret = test_rx_fifo_empty(CONTROLLER_IDX);
	if (ret != I2C_OK) {
		simputs("  ERROR: RX FIFO empty test failed\n");
		write_scratch(0, 0xBAD00050);
		test_fail(0);
	}
	write_scratch(1, 0x00000051);

	// Test TX FIFO (on I2C_1)
	write_scratch(1, 0x00000080);
	ret = test_tx_fifo_full_empty(TARGET_IDX);
	if (ret != I2C_OK) {
		simputs("  ERROR: TX FIFO test failed\n");
		write_scratch(0, 0xBAD00080);
		test_fail(0);
	}
	write_scratch(1, 0x00000081);

	// Test ACQ FIFO empty
	write_scratch(1, 0x00000090);
	ret = test_acq_fifo_empty(TARGET_IDX);
	if (ret != I2C_OK) {
		simputs("  ERROR: ACQ FIFO empty test failed\n");
		write_scratch(0, 0xBAD00090);
		test_fail(0);
	}
	write_scratch(1, 0x00000091);

	//=========================================================================
	// Test Complete - Signal to testbench
	//=========================================================================
	write_scratch(1, 0x00000090);

	// NOW signal setup complete to testbench
	write_scratch(1, 0xEBEDEBE4);
	simputs("\n");
	simputs("################################################\n");
	simputs("##           ALL TESTS PASSED                ##\n");
	simputs("################################################\n");
	simputs("\n");

	test_pass(0);

	simputs("\n=== Test Complete ===\n");
	while (true) {
		__asm__("wfi");
	}

	return 0;
}
