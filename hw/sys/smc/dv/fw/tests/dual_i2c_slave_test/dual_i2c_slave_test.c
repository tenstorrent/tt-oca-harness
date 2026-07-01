/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/**
 * @file main.c
 * @brief DUT I2C Master Test - Sends write to BFM I2C Slave
 *
 * This FW test runs on DUT (u_smc_wrapper) and:
 * 1. Initializes I2C_0 as Master immediately
 * 2. Waits for BFM Slave to be ready (scratch[1] = 0x0BFB0000)
 * 3. Sends I2C WRITE transaction to BFM Slave at address 0x10
 * 4. Reports result via scratch[0]
 *
 * The BFM is configured as I2C Slave (address 0x10) waiting to receive data
 */

#include <stdint.h>
#include <stdbool.h>
#include <string.h>
#include "i2c_opentitan.h"
#include "smc_io.h"

#define SCRATCH_REG_OFFSET(n)       SMC_TOP_SMC_CPU_CTRL_SCRATCH_BASE_ADDR(n)
#define SCRATCH_0                   SCRATCH_REG_OFFSET(0)
#define SCRATCH_1                   SCRATCH_REG_OFFSET(1)
#define SCRATCH_2                   SCRATCH_REG_OFFSET(2)

#define TEST_PASS                   0xACFECA01
#define TEST_FAIL                   0xFFFFFFFF
#define TEST_INIT                   0x12345678
#define BFM_READY                   0xEBEDEBE4
#define DUT_START_SIGNAL            0xDDD1C000

#define BFM_SLAVE_ADDR              0x10
#define I2C_CTRL_IDX                0
#define TEST_DATA_LEN               4

static inline void write32(uint32_t addr, uint32_t val) {
    *(volatile uint32_t *)addr = val;
}

static inline uint32_t read32(uint32_t addr) {
    return *(volatile uint32_t *)addr;
}

static void delay_cycles(uint32_t cycles) {
    volatile uint32_t count = cycles;
    while (count--);
}

static void delay_us(uint32_t us) {
    delay_cycles(us * 100);
}

static void set_result(uint32_t result) {
    write32(SCRATCH_0, result);
}

static void i2c_wrapper_enable(uint32_t idx, bool controller_mode) {
    uint32_t wrapper_addr = SMC_TOP_SMC_I2C_WRAP_I2C_CTRL_I2C_CTRL_BASE_ADDR(idx);
    // Build I2C_CTRL register value:
    // bit[0] = i2c_en (1)
    // bit[4] = i2c_controller_mode_en
    // bit[8] = smbus_en (1)
    uint32_t ctrl_val = 0x101;  // i2c_en (bit 0) + smbus_en (bit 8)
    if (controller_mode) {
        ctrl_val |= (1 << 4);   // Set i2c_controller_mode_en (bit 4)
    }
    write32(wrapper_addr, ctrl_val);
}

static bool init_i2c_master(void) {
    i2c_wrapper_enable(I2C_CTRL_IDX, true);
    delay_us(100);

    i2c_controller_config_t config = {
        .timing = {0},
        .enable_interrupts = false,
    };

    int result = i2c_controller_init(I2C_CTRL_IDX, &config);
    return (result == I2C_OK);
}

static bool i2c_master_write_test(uint8_t slave_addr, const uint8_t *data, uint32_t len) {
    int result = i2c_controller_write(I2C_CTRL_IDX, slave_addr, data, len, true);
    return (result == I2C_OK);
}

int main(void) {
    uint32_t timeout_count = 0;
    uint32_t max_timeout = 2000000;
    uint8_t test_data[TEST_DATA_LEN] = {0xCA, 0xFE, 0x5A, 0x5A};

    set_result(TEST_INIT);
    delay_us(1000);

    // Step 1: Initialize I2C Master immediately
    if (!init_i2c_master()) {
        set_result(TEST_FAIL);
        while (1);
    }

    delay_us(1000);

    // Step 2: Wait for BFM to signal readiness via scratch[1]
    // BFM should write 0x0BFB0000 to scratch[1] when ready
    timeout_count = 0;
    while (timeout_count < max_timeout) {
        uint32_t bfm_status = read32(SCRATCH_1);
        if (bfm_status == 0x0BFB0000) {
            break;
        }
        delay_cycles(100);
        timeout_count++;
    }

    if (timeout_count >= max_timeout) {
        set_result(TEST_FAIL);
        while (1);
    }

    delay_us(1000);

    // Step 3: Send I2C Write transaction to BFM Slave
    if (!i2c_master_write_test(BFM_SLAVE_ADDR, test_data, TEST_DATA_LEN)) {
        set_result(TEST_FAIL);
        while (1);
    }

    set_result(TEST_PASS);

    while (1) {
        delay_us(100000);
    }

    return 0;
}

int other_main(int hartid) {
    (void)hartid;
    while (1) {
        __asm__("wfi");
    }
}

int secondary_main(void) {
    int hartid = metal_cpu_get_current_hartid();
    if (hartid == 0) {
        return main();
    } else {
        return other_main(hartid);
    }
}
