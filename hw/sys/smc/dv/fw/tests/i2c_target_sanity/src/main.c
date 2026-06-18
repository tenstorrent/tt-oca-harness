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
 *
 * This is LEVEL 1 of the two-level I2C architecture.
 * Must be done BEFORE configuring the I2C IP.
 *
 * @param idx I2C instance (0 or 1)
 * @param controller_mode true for Controller mode, false for Target mode
 */
static void i2c_wrapper_enable(uint32_t idx, bool controller_mode)
{
	uint32_t wrapper_addr = SMC_TOP_SMC_I2C_WRAP_I2C_CTRL_I2C_CTRL_BASE_ADDR(0) + (idx * 4);

	i2c_ctrl__I2C_CTRL_t ctrl = { .w = 0 };
	ctrl.f.I2C_EN = 1;  // Enable GPIO pad mux
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
	const uint32_t TARGET_IDX = 0;      // I2C_0 as Target
	const uint8_t TARGET_ADDR = 0x10;   // Target address (7-bit)
	int ret;

	simputs("\n");
	simputs("################################################\n");
	simputs("##    I2C Target Sanity Test                 ##\n");
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
	//         Enable GPIO pad mux (MUST be done FIRST)
	//=========================================================================
	write_scratch(1, 0x00000020);
	simputs("\nStep 2: LEVEL 1 - Wrapper Control Enable\n");

	// Enable I2C_0 Wrapper (Target mode)
	i2c_wrapper_enable(TARGET_IDX, false);
	write_scratch(1, 0x00000021);

	//=========================================================================
	// Step 3: LEVEL 2 - I2C IP Initialization (Target Mode)
	//=========================================================================
	write_scratch(1, 0x00000030);
	simputs("\nStep 3: LEVEL 2 - I2C Target Initialization\n");

	// Validate I2C target address (7-bit address must be in range 0x08-0x77)
	if (TARGET_ADDR < 0x08 || TARGET_ADDR > 0x77) {
		simputs("  ERROR: Invalid I2C target address\n");
		simputshex32("  Address 0x", TARGET_ADDR);
		simputs(" is outside valid range (0x08-0x77)\n");
		write_scratch(0, 0xBAD00030);
		test_fail(0);
	}

	// Initialize I2C_0 as Target (address 0x10)
	simputshex32("  Initializing I2C_0 Target (addr=0x", TARGET_ADDR);
	simputs(")...\n");

	// Compute optimal timing parameters from physical characteristics
	i2c_timing_physical_t physical_params = {
		.speed = I2C_SPEED_STANDARD,    // 100 kHz
		.clock_period_nanos = 10,       // 100 MHz system clock (1/100MHz = 10ns)
		.sda_rise_nanos = 300,          // Typical for 4.7k pullup
		.sda_fall_nanos = 100,          // Typical fall time
		.scl_period_nanos = 0           // Auto (use minimum for standard mode = 10us)
	};

	i2c_timing_config_t computed_timing;
	ret = i2c_compute_timing_from_physical(&physical_params, &computed_timing);
	if (ret != I2C_OK) {
		simputs("  WARNING: Physical timing computation failed, using defaults\n");
		i2c_get_default_timing(I2C_SPEED_STANDARD, 100, &computed_timing);
	} else {
		simputs("  Using computed timing parameters:\n");
		simputshex32("    THIGH: ", computed_timing.thigh);
		simputshex32("    TLOW:  ", computed_timing.tlow);
		simputshex32("    T_R:   ", computed_timing.t_r);
		simputshex32("    T_F:   ", computed_timing.t_f);
		simputs("\n");
	}

	const uint8_t TARGET_ADDR1 = 0;  // Secondary address (not used in this test)
	i2c_target_config_t tgt_cfg = {
		.address0 = TARGET_ADDR,
		.mask0 = 0x7F,  // Exact match
		.address1 = TARGET_ADDR1,
		.mask1 = 0,
		.timing = computed_timing,
		.fifo = {
			.tx_thresh = 1,  // Set to 1 to ensure target FSM reads TX FIFO immediately
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
		write_scratch(0, 0xBAD00030);
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

	// Reset FIFOs after enabling target mode (OpenTitan best practice)
	i2c_reset_fifos(TARGET_IDX, false, false, true, true);
	simputs("  FIFOs reset after target enable\n");

	// Signal setup done to testbench
	write_scratch(1, 0xEBEDEBE2);
	simputs("  Setup complete - waiting for external master...\n");

	// Test passes - firmware setup is complete
	// The testbench will handle the actual I2C transaction testing
	test_pass(0);

	while (true) {
		__asm__("wfi");
	}

	return 0;
}

int secondary_main(void)
{
	return main();
}
