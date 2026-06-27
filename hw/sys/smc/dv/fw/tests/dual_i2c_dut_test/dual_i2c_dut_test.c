/* SPDX-License-Identifier: Apache-2.0 */
/* (c) 2026 Tenstorrent USA Inc */

/**
 * @file main.c
 * @brief Dual I2C FW Test - DUT as I2C Master
 *
 * DUT acts as I2C Master on I2C_0 (Controller)
 * BFM acts as I2C Slave on I2C_0 (Target) at address 0x10
 *
 * Test Flow:
 *   1. Initialize I2C_0 as Controller (Master)
 *   2. Wait for BFM to initialize (check scratch[1] == 0x0BFB0000)
 *   3. Send I2C write transaction to BFM (addr 0x10, data: 0xAA)
 *   4. Send I2C read transaction to BFM (addr 0x10)
 *   5. Verify read data matches expected value
 *   6. Report result to scratch[0]
 */

#include <stdint.h>
#include <stdbool.h>
#include <metal/cpu.h>

#include "smc_io.h"
#include "smc_test.h"
#include "i2c_opentitan.h"

#define BFM_I2C_SLAVE_ADDR  0x10   // BFM Target address (7-bit)
#define TEST_WRITE_DATA     0xAA   // Test data to write
#define TEST_READ_SIZE      1      // Read 1 byte
#define I2C_TIMEOUT_US      100000 // 100ms timeout

int main(void)
{
    simputs("\n");
    simputs("=== Dual I2C FW Test - DUT Master ===\n");

    // ========================================================================
    // Step 1: Initialize system
    // ========================================================================
    simputs("[INIT] System initialization\n");
    write_scratch(1, 0x00000010);

    // ========================================================================
    // Step 2: Initialize I2C_0 as Controller (Master)
    // ========================================================================
    simputs("[INIT] Initializing I2C_0 as Master (Controller)\n");

    // Enable I2C_0 Wrapper in Master mode
    uint32_t wrapper_addr = SMC_TOP_SMC_I2C_WRAP_I2C_CTRL_I2C_CTRL_BASE_ADDR(0);
    i2c_ctrl__I2C_CTRL_t ctrl = { .w = 0 };
    ctrl.f.I2C_EN = 1;
    ctrl.f.I2C_CONTROLLER_MODE_EN = 1;  // Master mode
    write_reg(wrapper_addr, ctrl.w);

    simputs("[INIT] I2C_0 Wrapper enabled in Master mode\n");

    // Initialize I2C_0 Controller with default config
    int ret = i2c_controller_init(0, NULL);
    if (ret != I2C_OK) {
        simputs("[ERROR] I2C_0 Controller initialization failed: 0x");
        simputshex32("", ret);
        simputs("\n");
        write_scratch(0, 0xACEFACA0);  // FAIL
        return -1;
    }

    simputs("[INIT] I2C_0 Controller initialized\n");

    // Enable I2C_0 Controller (returns void)
    i2c_controller_enable(0);

    simputs("[INIT] I2C_0 Controller enabled\n");
    write_scratch(1, 0x00000020);

    // ========================================================================
    // Step 3: Wait for BFM to initialize (check scratch[2] == 0x0BFB0000)
    // ========================================================================
    simputs("[WAIT] Waiting for BFM initialization (~500us)...\n");

    uint32_t wait_timeout = 50000;  // ~500us at typical clock
    uint32_t wait_count = 0;
    bool bfm_ready = false;

    while (wait_count < wait_timeout) {
        uint32_t scratch2 = read_scratch(2);  // Read scratch[2] instead of scratch[1]
        if (scratch2 == 0x0BFB0000) {
            simputs("[READY] BFM Ready signal detected!\n");
            bfm_ready = true;
            break;
        }
        wait_count++;

        // Small delay
        for (volatile int i = 0; i < 10; i++) {
            asm volatile("nop");
        }
    }

    if (!bfm_ready) {
        simputs("[ERROR] BFM initialization timeout\n");
        write_scratch(0, 0xACEFACA0);  // FAIL
        return -1;
    }

    write_scratch(1, 0x00000030);

    // ========================================================================
    // Step 4: I2C Write Transaction (Master -> Slave)
    // ========================================================================
    simputs("[TEST] Sending I2C Write transaction\n");
    simputs("[TEST] Target address: 0x");
    simputshex32("", BFM_I2C_SLAVE_ADDR);
    simputs(", Data: 0x");
    simputshex32("", TEST_WRITE_DATA);
    simputs("\n");

    uint8_t write_data[1] = {TEST_WRITE_DATA};

    ret = i2c_controller_write(0, BFM_I2C_SLAVE_ADDR, write_data, 1, true);
    if (ret != I2C_OK) {
        simputs("[ERROR] I2C Write failed: 0x");
        simputshex32("", ret);
        simputs("\n");
        write_scratch(0, 0xACEFACA0);  // FAIL
        return -1;
    }

    simputs("[SUCCESS] I2C Write completed\n");
    write_scratch(1, 0x00000040);

    // ========================================================================
    // Step 5: Small delay before read
    // ========================================================================
    simputs("[WAIT] Allowing BFM to process write transaction...\n");
    for (volatile int i = 0; i < 5000; i++) {
        asm volatile("nop");
    }

    // ========================================================================
    // Step 6: I2C Read Transaction (Master <- Slave)
    // ========================================================================
    simputs("[TEST] Sending I2C Read transaction\n");
    simputs("[TEST] Target address: 0x");
    simputshex32("", BFM_I2C_SLAVE_ADDR);
    simputs(", Read size: ");
    simputshex32("", TEST_READ_SIZE);
    simputs("\n");

    uint8_t read_data[1] = {0};

    ret = i2c_controller_read(0, BFM_I2C_SLAVE_ADDR, read_data, TEST_READ_SIZE, true);
    if (ret != I2C_OK) {
        simputs("[ERROR] I2C Read failed: 0x");
        simputshex32("", ret);
        simputs("\n");
        write_scratch(0, 0xACEFACA0);  // FAIL
        return -1;
    }

    simputs("[SUCCESS] I2C Read completed\n");
    simputs("[DATA] Read data: 0x");
    simputshex32("", read_data[0]);
    simputs("\n");

    write_scratch(1, 0x00000050);

    // ========================================================================
    // Step 7: Verify read data
    // ========================================================================
    simputs("[VERIFY] Verifying read data...\n");
    if (read_data[0] == TEST_WRITE_DATA) {
        simputs("[SUCCESS] Data verification passed!\n");
        write_scratch(0, 0xACFECA01);  // PASS
        simputs("[RESULT] Setting PASS_CODE to scratch[0]\n");
        simputs("[DONE] Test completed successfully\n");
        return 0;
    } else {
        simputs("[ERROR] Data mismatch! Expected: 0x");
        simputshex32("", TEST_WRITE_DATA);
        simputs(", Got: 0x");
        simputshex32("", read_data[0]);
        simputs("\n");
        write_scratch(0, 0xACEFACA0);  // FAIL
        return -1;
    }
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
