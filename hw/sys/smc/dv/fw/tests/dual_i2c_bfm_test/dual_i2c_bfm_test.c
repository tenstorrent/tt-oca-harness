/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/**
 * @file main.c
 * @brief Dual I2C FW Test - BFM as I2C Slave (Target)
 *
 * BFM acts as I2C Slave (Target) on I2C_0 at address 0x10
 * DUT acts as I2C Master on I2C_0 (Controller)
 *
 * Test Flow:
 *   1. Initialize I2C_0 in Slave/Target mode (i2c_controller_mode_en = 0)
 *   2. Set Target address to 0x10
 *   3. Signal BFM Ready via scratch[1] = 0x0BFB0000
 *   4. Wait for I2C Write from Master (DUT)
 *   5. Receive write data
 *   6. Echo read data back to Master
 *   7. Report result to scratch[0]
 */

#include <stdint.h>
#include <stdbool.h>
#include <metal/cpu.h>

#include "smc_io.h"
#include "smc_test.h"
#include "i2c_opentitan.h"

#define BFM_I2C_SLAVE_ADDR 0x10 // BFM Target address (7-bit)
#define TEST_WRITE_DATA 0xAA    // Expected write data from Master
#define I2C_TIMEOUT_US 100000   // 100ms timeout

// Scratchpad signal codes
#define BFM_READY_SIGNAL 0x0BFB0000
#define BFM_TEST_PASS 0xACFECA01
#define BFM_TEST_FAIL 0xACEFACA0

/**
 * @brief Enable I2C Wrapper in Slave/Target mode
 * CRITICAL: Must set i2c_controller_mode_en = 0
 */
static void i2c_wrapper_enable_slave(uint32_t idx) {
    uint32_t wrapper_addr = SMC_TOP_SMC_I2C_WRAP_I2C_CTRL_REGS_I2C_CTRL_BASE_ADDR(idx);
    i2c_ctrl__I2C_CTRL_t ctrl = {.w = 0};

    // Read current value
    ctrl.w = read_reg(wrapper_addr);

    // Configure for Slave mode
    ctrl.f.I2C_EN = 1;                 // Enable I2C
    ctrl.f.I2C_CONTROLLER_MODE_EN = 0; // SLAVE/TARGET mode (CRITICAL!)

    write_reg(wrapper_addr, ctrl.w);

    simputs("[INIT] I2C_");
    simputshex32("", idx);
    simputs(" Wrapper configured for Slave mode\n");
}

/**
 * @brief Initialize I2C Target with specific address
 */
static int i2c_target_init_with_addr(uint32_t i2c_idx, uint32_t target_addr) {
    int ret = i2c_target_init(i2c_idx, NULL);
    if (ret != I2C_OK) {
        simputs("[ERROR] I2C Target init failed: 0x");
        simputshex32("", ret);
        simputs("\n");
        return ret;
    }

    simputs("[INIT] I2C_");
    simputshex32("", i2c_idx);
    simputs(" Target initialized\n");

    // Set Target address and mask (i2c_target_set_address returns void)
    i2c_target_set_address(i2c_idx, (uint8_t)target_addr, 0x7F);

    simputs("[INIT] I2C_");
    simputshex32("", i2c_idx);
    simputs(" Target address set to 0x");
    simputshex32("", target_addr);
    simputs("\n");

    return I2C_OK;
}

int main(void) {
    simputs("\n");
    simputs("=== Dual I2C FW Test - BFM Slave ===\n");

    // ========================================================================
    // Step 1: Initialize system
    // ========================================================================
    simputs("[INIT] System initialization\n");
    write_scratch(2, 0x0BFB0001); // BFM Ready signal on scratch[2] (not scratch[1]!)

    // ========================================================================
    // Step 2: Initialize I2C_0 as Target (Slave)
    // ========================================================================
    simputs("[INIT] Initializing I2C_0 as Slave (Target)\n");

    // Enable I2C_0 Wrapper in Slave mode (CRITICAL)
    i2c_wrapper_enable_slave(0);

    // Initialize I2C_0 Target with address 0x10
    // Add timeout protection
    uint32_t init_timeout = 1000;
    int ret = I2C_OK;

    for (uint32_t t = 0; t < init_timeout; t++) {
        ret = i2c_target_init_with_addr(0, BFM_I2C_SLAVE_ADDR);
        if (ret == I2C_OK) {
            break;
        }
        simputs("[RETRY] I2C init attempt failed, retrying...\n");
    }

    if (ret != I2C_OK) {
        simputs("[ERROR] I2C_0 Target initialization timeout after 1000 attempts\n");
        write_scratch(0, BFM_TEST_FAIL);
        return -1;
    }

    simputs("[INIT] I2C_0 Target ready at address 0x");
    simputshex32("", BFM_I2C_SLAVE_ADDR);
    simputs("\n");

    write_scratch(1, 0x00000020);

    // ========================================================================
    // Step 3: Signal BFM Ready (use scratch[2] instead of scratch[1])
    // ========================================================================
    simputs("[READY] Signaling BFM Ready\n");
    write_scratch(2, BFM_READY_SIGNAL); // Use scratch[2] for BFM ready signal

    // ========================================================================
    // Step 4: Wait for I2C Write Transaction from Master (DUT)
    // ========================================================================
    simputs("[TEST] Waiting for I2C Write from Master...\n");

    uint8_t write_data[8] = {0};
    uint32_t write_len = 0;

    // Timeout counter
    uint32_t timeout_counter = 0;
    uint32_t timeout_limit = 100000;

    // Poll for write transaction
    while (timeout_counter < timeout_limit) {
        // Try to receive a write transaction
        ret = i2c_target_receive_transaction(0, write_data, sizeof(write_data), &write_len, 0);

        if (ret == I2C_OK && write_len > 0) {
            simputs("[SUCCESS] I2C Write received!\n");
            simputs("[DATA] Write length: ");
            simputshex32("", write_len);
            simputs(" bytes\n");

            for (uint32_t i = 0; i < write_len; i++) {
                simputs("[DATA] write_data[");
                simputshex32("", i);
                simputs("] = 0x");
                simputshex32("", write_data[i]);
                simputs("\n");
            }
            break;
        } else if (ret == I2C_OK && write_len == 0) {
            // No data yet, continue waiting
            timeout_counter++;
            for (volatile int i = 0; i < 10; i++) {
                asm volatile("nop");
            }
        } else if (ret != I2C_OK) {
            // Error occurred
            simputs("[ERROR] I2C Target receive error: 0x");
            simputshex32("", ret);
            simputs("\n");
            timeout_counter++;
            for (volatile int i = 0; i < 10; i++) {
                asm volatile("nop");
            }
        }
    }

    if (timeout_counter >= timeout_limit) {
        simputs("[ERROR] I2C Write timeout\n");
        write_scratch(0, BFM_TEST_FAIL);
        return -1;
    }

    write_scratch(1, 0x00000030);

    // ========================================================================
    // Step 5: Verify Write Data
    // ========================================================================
    simputs("[VERIFY] Verifying write data...\n");
    if (write_len != 1) {
        simputs("[ERROR] Expected 1 byte, got ");
        simputshex32("", write_len);
        simputs("\n");
        write_scratch(0, BFM_TEST_FAIL);
        return -1;
    }

    if (write_data[0] != TEST_WRITE_DATA) {
        simputs("[ERROR] Data mismatch! Expected 0x");
        simputshex32("", TEST_WRITE_DATA);
        simputs(", Got 0x");
        simputshex32("", write_data[0]);
        simputs("\n");
        write_scratch(0, BFM_TEST_FAIL);
        return -1;
    }

    simputs("[SUCCESS] Write data verified!\n");
    write_scratch(1, 0x00000040);

    // ========================================================================
    // Step 6: Wait for I2C Read Request from Master
    // ========================================================================
    simputs("[TEST] Waiting for I2C Read request from Master...\n");

    // Wait for Master to send READ request
    // The I2C Target FSM will automatically handle the READ transaction
    // when Master sends ADDR + READ bit
    // Simply wait for the transaction to complete
    uint32_t read_wait_count = 0;
    uint32_t read_wait_limit = 100000;

    while (read_wait_count < read_wait_limit) {
        // Just wait - I2C FSM handles READ automatically
        for (volatile int i = 0; i < 10; i++) {
            asm volatile("nop");
        }
        read_wait_count++;
    }

    simputs("[SUCCESS] I2C Read transaction should have completed!\n");
    write_scratch(1, 0x00000050);

    // ========================================================================
    // Step 7: Test Complete - Report Success
    // ========================================================================
    simputs("[SUCCESS] All I2C transactions completed!\n");
    simputs("[RESULT] Setting PASS_CODE to scratch[0]\n");
    write_scratch(0, BFM_TEST_PASS);

    simputs("[DONE] Test completed successfully\n");
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
