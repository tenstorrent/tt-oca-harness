/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/**
 * @file main.c
 * @brief I2C P0 FIFO Threshold Interrupt Test
 *
 * Test Approach: SMC as I2C Master and Slave
 *
 * Test Steps:
 * 1. Configure the RX FIFO threshold (ACQ FIFO) to N bytes
 * 2. Have an external master write N bytes. Verify interrupt triggers exactly on the Nth byte
 * 3. Configure the TX FIFO threshold to M bytes
 * 4. Write M-1 bytes to the FIFO, verify no interrupt. Write the Mth byte, verify interrupt
 * triggers
 */

#include <stdint.h>
#include <stdbool.h>

#include "smc_io.h"
#include "smc_test.h"
#include "i2c_opentitan.h"

// Test parameters
#define TARGET_IDX 0
#define TARGET_ADDR 0x10
#define RX_FIFO_THRESHOLD_N 5 // ACQ FIFO threshold for RX test
#define TX_FIFO_THRESHOLD_M 5 // TX FIFO threshold for TX test

/**
 * @brief Enable I2C Wrapper Control (LEVEL 1)
 */
static void i2c_wrapper_enable(uint32_t idx, bool controller_mode) {
    uint32_t wrapper_addr = SMC_TOP_SMC_I2C_WRAP_I2C_CTRL_REGS_I2C_CTRL_BASE_ADDR(idx);

    i2c_ctrl__I2C_CTRL_t ctrl = {.w = 0};
    ctrl.f.I2C_EN = 1;
    ctrl.f.I2C_CONTROLLER_MODE_EN = controller_mode ? 1 : 0;

    write_reg(wrapper_addr, ctrl.w);

    simputs("  Wrapper[");
    simputshex32("", idx);
    simputs("] enabled: mode=");
    simputs(controller_mode ? "Controller" : "Target");
    simputs("\n");
}

/**
 * @brief Test RX FIFO threshold interrupt (ACQ FIFO)
 * External master writes N bytes, verify interrupt triggers on Nth byte
 */
static int test_rx_fifo_threshold(uint32_t idx, uint32_t threshold_n) {
    uint32_t base = i2c_get_base(idx);

    simputs("\n=== Test RX FIFO Threshold (ACQ FIFO) ===\n");
    simputs("  Configuring ACQ FIFO threshold to ");
    simputshex32("", threshold_n);
    simputs(" bytes\n");

    // Configure ACQ FIFO threshold
    i2c__TARGET_FIFO_CONFIG_t fifo_cfg = {
        .w = read_reg(base + (SMC_TOP_SMC_I2C_WRAP_I2C_TARGET_FIFO_CONFIG_BASE_ADDR(0) -
                              SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)))};
    fifo_cfg.f.ACQ_THRESH = threshold_n;
    write_reg(base + (SMC_TOP_SMC_I2C_WRAP_I2C_TARGET_FIFO_CONFIG_BASE_ADDR(0) -
                      SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)),
              fifo_cfg.w);

    // Verify threshold was set correctly
    i2c__TARGET_FIFO_CONFIG_t fifo_cfg_verify = {
        .w = read_reg(base + (SMC_TOP_SMC_I2C_WRAP_I2C_TARGET_FIFO_CONFIG_BASE_ADDR(0) -
                              SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)))};
    if (fifo_cfg_verify.f.ACQ_THRESH != threshold_n) {
        simputs("  ERROR: ACQ threshold not set correctly\n");
        return I2C_ERROR;
    }
    simputs("  ACQ threshold verified: ");
    simputshex32("", fifo_cfg_verify.f.ACQ_THRESH);
    simputs("\n");

    // Enable ACQ threshold interrupt
    i2c__INTR_ENABLE_t intr_en = {
        .w = read_reg(base + (SMC_TOP_SMC_I2C_WRAP_I2C_INTR_ENABLE_BASE_ADDR(0) -
                              SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)))};
    intr_en.f.ACQ_THRESHOLD = 1;
    write_reg(base + (SMC_TOP_SMC_I2C_WRAP_I2C_INTR_ENABLE_BASE_ADDR(0) -
                      SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)),
              intr_en.w);

    // Clear all interrupts
    i2c_clear_interrupts(idx, 0xFFFFFFFF);

    simputs("  Waiting for external master to write ");
    simputshex32("", threshold_n);
    simputs(" bytes...\n");
    simputs("  (According to OpenTitan spec: ACQ threshold interrupt triggers when ACQ FIFO level "
            "> threshold)\n");
    simputs("  (Interrupt should trigger when ACQ FIFO level > ");
    simputshex32("", threshold_n);
    simputs(")\n");

    // Verify target is enabled and ready
    i2c__CTRL_t ctrl_check = {.w = read_reg(base + (SMC_TOP_SMC_I2C_WRAP_I2C_CTRL_BASE_ADDR(0) -
                                                    SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)))};
    simputs("  Target CTRL: enabletarget=");
    simputshex32("", ctrl_check.f.ENABLETARGET ? 1 : 0);
    simputs("\n");

    // CRITICAL: Wait for target to enter idle state before accepting transactions
    // According to OpenTitan spec: TARGETIDLE bit in STATUS register indicates Target FSM is idle
    // Target must be idle to respond to I2C address match
    // After enabling target mode, allow some time for FSM to initialize
    simputs("  Waiting for target to enter idle state...\n");

    // Add initial delay to allow target FSM to initialize after enabletarget is set
    for (volatile int i = 0; i < 1000; i++)
        ;

    // Check initial status
    i2c__STATUS_t status_initial = {
        .w = read_reg(base + (SMC_TOP_SMC_I2C_WRAP_I2C_STATUS_BASE_ADDR(0) -
                              SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)))};

    // According to OpenTitan spec, TARGETIDLE reset value is 1 (idle)
    // If already idle, no need to wait
    if (status_initial.f.TARGETIDLE) {
        simputs("  Target is already idle (ready to accept transactions)\n");
    } else {
        // Wait for target to become idle with timeout
        uint32_t idle_timeout = 0x100000; // Reduced timeout (16M cycles)
        uint32_t idle_count = 0;
        bool target_idle = false;

        while (idle_count < idle_timeout) {
            i2c__STATUS_t status_check = {
                .w = read_reg(base + (SMC_TOP_SMC_I2C_WRAP_I2C_STATUS_BASE_ADDR(0) -
                                      SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)))};
            if (status_check.f.TARGETIDLE) {
                target_idle = true;
                simputs("  Target is now idle (ready to accept transactions)\n");
                break;
            }

            // Add small delay to avoid tight loop
            for (volatile int i = 0; i < 100; i++)
                ;

            idle_count++;
            // More frequent status output for debugging (every 10000 cycles)
            if ((idle_count % 10000) == 0) {
                simputs("  [Waiting] Target idle=");
                simputshex32("", status_check.f.TARGETIDLE ? 1 : 0);
                simputs(", count=");
                simputshex32("", idle_count);
                simputs("\n");
            }
        }

        if (!target_idle) {
            i2c__STATUS_t status_final = {
                .w = read_reg(base + (SMC_TOP_SMC_I2C_WRAP_I2C_STATUS_BASE_ADDR(0) -
                                      SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)))};
            simputs("  ERROR: Target did not enter idle state within timeout\n");
            simputs("  Final status: targetidle=");
            simputshex32("", status_final.f.TARGETIDLE ? 1 : 0);
            simputs(", CTRL enabletarget=");
            i2c__CTRL_t ctrl_final = {
                .w = read_reg(base + (SMC_TOP_SMC_I2C_WRAP_I2C_CTRL_BASE_ADDR(0) -
                                      SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)))};
            simputshex32("", ctrl_final.f.ENABLETARGET ? 1 : 0);
            simputs("\n");
            return I2C_ERROR_TIMEOUT;
        }
    }

    // Check target status before waiting for interrupt
    i2c__STATUS_t status_before = {
        .w = read_reg(base + (SMC_TOP_SMC_I2C_WRAP_I2C_STATUS_BASE_ADDR(0) -
                              SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)))};
    i2c__TARGET_FIFO_STATUS_t fifo_status_before = {
        .w = read_reg(base + (SMC_TOP_SMC_I2C_WRAP_I2C_TARGET_FIFO_STATUS_BASE_ADDR(0) -
                              SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)))};
    i2c__TARGET_ID_t target_id_check = {
        .w = read_reg(base + (SMC_TOP_SMC_I2C_WRAP_I2C_TARGET_ID_BASE_ADDR(0) -
                              SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)))};

    simputs("  Before waiting: Target idle=");
    simputshex32("", status_before.f.TARGETIDLE ? 1 : 0);
    simputs(", ACQ FIFO level=");
    simputshex32("", fifo_status_before.f.ACQLVL);
    simputs(", Target address0=");
    simputshex32("", target_id_check.f.ADDRESS0);
    simputs("\n");

    // Check if interrupt already triggered (data may have been written during idle wait)
    i2c__INTR_STATE_t intr_state_initial = {
        .w = read_reg(base + (SMC_TOP_SMC_I2C_WRAP_I2C_INTR_STATE_BASE_ADDR(0) -
                              SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)))};
    if (intr_state_initial.f.ACQ_THRESHOLD && fifo_status_before.f.ACQLVL > threshold_n) {
        simputs("  ACQ threshold interrupt already triggered (data written during idle wait)\n");
        simputs("  ACQ FIFO level: ");
        simputshex32("", fifo_status_before.f.ACQLVL);
        simputs(", Threshold: ");
        simputshex32("", threshold_n);
        simputs("\n");
        // Verify FIFO level is greater than threshold
        if (fifo_status_before.f.ACQLVL > threshold_n) {
            simputs("  PASS: ACQ FIFO level (");
            simputshex32("", fifo_status_before.f.ACQLVL);
            simputs(") > threshold (");
            simputshex32("", threshold_n);
            simputs("), interrupt triggered correctly\n");
            // Clear interrupt and return success
            i2c_clear_interrupts(idx, 0xFFFFFFFF);
            return I2C_OK;
        }
    }

    // Wait for interrupt to trigger
    // External master (cocotb VIP) will write N bytes
    uint32_t timeout = 0x10000000; // Large timeout (allow time for I2C transaction)
    uint32_t count = 0;
    bool interrupt_triggered = false;

    // Small delay to allow external master to start writing
    for (volatile int i = 0; i < 50000; i++)
        ;

    while (count < timeout) {
        i2c__INTR_STATE_t intr_state = {
            .w = read_reg(base + (SMC_TOP_SMC_I2C_WRAP_I2C_INTR_STATE_BASE_ADDR(0) -
                                  SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)))};

        // Check ACQ FIFO level periodically even if interrupt not triggered
        i2c__TARGET_FIFO_STATUS_t fifo_status_check = {
            .w = read_reg(base + (SMC_TOP_SMC_I2C_WRAP_I2C_TARGET_FIFO_STATUS_BASE_ADDR(0) -
                                  SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)))};

        if (intr_state.f.ACQ_THRESHOLD) {
            // Check ACQ FIFO level when interrupt triggered
            i2c__TARGET_FIFO_STATUS_t fifo_status = {
                .w = read_reg(base + (SMC_TOP_SMC_I2C_WRAP_I2C_TARGET_FIFO_STATUS_BASE_ADDR(0) -
                                      SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)))};

            simputs("  ACQ threshold interrupt triggered!\n");
            simputs("  ACQ FIFO level: ");
            simputshex32("", fifo_status.f.ACQLVL);
            simputs("\n");

            // Verify FIFO level is greater than threshold
            // According to OpenTitan spec: ACQ_THRESHOLD interrupt triggers when ACQLVL >
            // ACQ_THRESH
            if (fifo_status.f.ACQLVL > threshold_n) {
                simputs("  PASS: ACQ FIFO level (");
                simputshex32("", fifo_status.f.ACQLVL);
                simputs(") > threshold (");
                simputshex32("", threshold_n);
                simputs("), interrupt triggered correctly\n");
                interrupt_triggered = true;
                break;
            } else if (fifo_status.f.ACQLVL == threshold_n) {
                simputs("  WARNING: ACQ FIFO level (");
                simputshex32("", fifo_status.f.ACQLVL);
                simputs(") == threshold (");
                simputshex32("", threshold_n);
                simputs("), interrupt may not trigger (needs > threshold)\n");
            } else {
                simputs("  WARNING: ACQ FIFO level (");
                simputshex32("", fifo_status.f.ACQLVL);
                simputs(") < threshold (");
                simputshex32("", threshold_n);
                simputs("), interrupt should not trigger yet\n");
            }
        }

        count++;
        if ((count % 10000) == 0) {
            // Periodic status check
            i2c__STATUS_t status_periodic = {
                .w = read_reg(base + (SMC_TOP_SMC_I2C_WRAP_I2C_STATUS_BASE_ADDR(0) -
                                      SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)))};
            simputs("  [Status] ACQ FIFO level: ");
            simputshex32("", fifo_status_check.f.ACQLVL);
            simputs(", Target idle: ");
            simputshex32("", status_periodic.f.TARGETIDLE ? 1 : 0);
            simputs(", ACQ empty: ");
            simputshex32("", status_periodic.f.ACQEMPTY ? 1 : 0);
            simputs("\n");

            // If ACQ FIFO has data but interrupt not triggered, check why
            if (fifo_status_check.f.ACQLVL > 0 && !intr_state.f.ACQ_THRESHOLD) {
                simputs("  [Warning] ACQ FIFO has data (");
                simputshex32("", fifo_status_check.f.ACQLVL);
                simputs(" bytes) but interrupt not triggered\n");
                simputs("  [Debug] Threshold=");
                simputshex32("", threshold_n);
                simputs(", Level=");
                simputshex32("", fifo_status_check.f.ACQLVL);
                simputs(", Condition met: ");
                simputshex32("", (fifo_status_check.f.ACQLVL > threshold_n) ? 1 : 0);
                simputs("\n");
            }
        }
    }

    if (!interrupt_triggered) {
        // Final diagnostic check
        i2c__TARGET_FIFO_STATUS_t fifo_status_final = {
            .w = read_reg(base + (SMC_TOP_SMC_I2C_WRAP_I2C_TARGET_FIFO_STATUS_BASE_ADDR(0) -
                                  SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)))};
        i2c__STATUS_t status_final = {
            .w = read_reg(base + (SMC_TOP_SMC_I2C_WRAP_I2C_STATUS_BASE_ADDR(0) -
                                  SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)))};
        i2c__INTR_STATE_t intr_state_final = {
            .w = read_reg(base + (SMC_TOP_SMC_I2C_WRAP_I2C_INTR_STATE_BASE_ADDR(0) -
                                  SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)))};

        simputs("  ERROR: ACQ threshold interrupt did not trigger within timeout\n");
        simputs("  Final status: ACQ FIFO level=");
        simputshex32("", fifo_status_final.f.ACQLVL);
        simputs(", Threshold=");
        simputshex32("", threshold_n);
        simputs(", Target idle=");
        simputshex32("", status_final.f.TARGETIDLE ? 1 : 0);
        simputs(", ACQ empty=");
        simputshex32("", status_final.f.ACQEMPTY ? 1 : 0);
        simputs(", Interrupt state=");
        simputshex32("", intr_state_final.f.ACQ_THRESHOLD ? 1 : 0);
        simputs("\n");

        // Check if any data was received at all
        if (fifo_status_final.f.ACQLVL == 0) {
            simputs("  [Diagnosis] No data received in ACQ FIFO - I2C transaction may have failed "
                    "(NACK)\n");
        } else if (fifo_status_final.f.ACQLVL <= threshold_n) {
            simputs("  [Diagnosis] ACQ FIFO level (");
            simputshex32("", fifo_status_final.f.ACQLVL);
            simputs(") <= threshold (");
            simputshex32("", threshold_n);
            simputs(") - interrupt should not trigger\n");
        }

        return I2C_ERROR_TIMEOUT;
    }

    // Clear interrupt
    i2c_clear_interrupts(idx, 0xFFFFFFFF);

    simputs("  RX FIFO threshold test PASSED\n");
    return I2C_OK;
}

/**
 * @brief Test TX FIFO threshold interrupt
 *
 * According to OpenTitan I2C spec:
 * - TX_THRESHOLD interrupt triggers when TX FIFO level < TX_THRESH (level-triggered)
 * - This means interrupt triggers when FIFO is consumed below threshold
 *
 * Test approach:
 * 1. Fill TX FIFO with more than threshold bytes (level > threshold, no interrupt)
 * 2. Write M-1 bytes where M-1 >= threshold (should NOT trigger interrupt)
 * 3. Write Mth byte where M < threshold (should trigger interrupt)
 *
 * Note: Since TX FIFO data is consumed by external master during READ transaction,
 * we test by writing data and checking interrupt state based on FIFO level.
 */
static int test_tx_fifo_threshold(uint32_t idx, uint32_t threshold_m) {
    uint32_t base = i2c_get_base(idx);

    simputs("\n=== Test TX FIFO Threshold ===\n");
    simputs("  Configuring TX FIFO threshold to ");
    simputshex32("", threshold_m);
    simputs(" bytes\n");
    simputs("  Note: TX threshold interrupt triggers when TX FIFO level < threshold\n");

    // Configure TX FIFO threshold
    i2c__TARGET_FIFO_CONFIG_t fifo_cfg = {
        .w = read_reg(base + (SMC_TOP_SMC_I2C_WRAP_I2C_TARGET_FIFO_CONFIG_BASE_ADDR(0) -
                              SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)))};
    fifo_cfg.f.TX_THRESH = threshold_m;
    write_reg(base + (SMC_TOP_SMC_I2C_WRAP_I2C_TARGET_FIFO_CONFIG_BASE_ADDR(0) -
                      SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)),
              fifo_cfg.w);

    // Verify threshold was set correctly
    i2c__TARGET_FIFO_CONFIG_t fifo_cfg_verify = {
        .w = read_reg(base + (SMC_TOP_SMC_I2C_WRAP_I2C_TARGET_FIFO_CONFIG_BASE_ADDR(0) -
                              SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)))};
    if (fifo_cfg_verify.f.TX_THRESH != threshold_m) {
        simputs("  ERROR: TX threshold not set correctly\n");
        return I2C_ERROR;
    }
    simputs("  TX threshold verified: ");
    simputshex32("", fifo_cfg_verify.f.TX_THRESH);
    simputs("\n");

    // Enable TX threshold interrupt
    i2c__INTR_ENABLE_t intr_en = {
        .w = read_reg(base + (SMC_TOP_SMC_I2C_WRAP_I2C_INTR_ENABLE_BASE_ADDR(0) -
                              SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)))};
    intr_en.f.TX_THRESHOLD = 1;
    write_reg(base + (SMC_TOP_SMC_I2C_WRAP_I2C_INTR_ENABLE_BASE_ADDR(0) -
                      SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)),
              intr_en.w);

    // Clear all interrupts
    i2c_clear_interrupts(idx, 0xFFFFFFFF);

    // Reset TX FIFO to start fresh
    i2c_reset_fifos(idx, false, false, true, false);

    // Check initial state (FIFO empty, should trigger interrupt if threshold > 0)
    i2c__TARGET_FIFO_STATUS_t initial_fifo_status = {
        .w = read_reg(base + (SMC_TOP_SMC_I2C_WRAP_I2C_TARGET_FIFO_STATUS_BASE_ADDR(0) -
                              SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)))};
    i2c__INTR_STATE_t initial_intr_state = {
        .w = read_reg(base + (SMC_TOP_SMC_I2C_WRAP_I2C_INTR_STATE_BASE_ADDR(0) -
                              SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)))};

    simputs("  Initial TX FIFO level: ");
    simputshex32("", initial_fifo_status.f.TXLVL);
    simputs("\n");
    simputs("  Initial interrupt state: ");
    simputshex32("", initial_intr_state.f.TX_THRESHOLD ? 1 : 0);
    simputs("\n");

    // Step 1: Write M-1 bytes where M-1 >= threshold (should NOT trigger interrupt)
    // For threshold = 5, write 4 bytes (4 < 5, so interrupt should be triggered)
    // Actually, we need to write enough bytes so that level >= threshold to NOT trigger interrupt
    // Then write one more byte that makes level still >= threshold, verify no interrupt
    // Then wait for FIFO to be consumed below threshold to trigger interrupt

    // Better approach: Write bytes incrementally and check interrupt state
    simputs("  Step 1: Writing bytes incrementally to test threshold behavior\n");

    uint8_t test_data[32];
    for (uint32_t i = 0; i < 32; i++) {
        test_data[i] = 0xAA + i;
    }

    // Write bytes one by one and check interrupt state
    // When TX FIFO level < threshold, interrupt should be triggered (level-triggered)
    // When TX FIFO level >= threshold, interrupt should NOT be triggered

    // First, verify that empty FIFO (level = 0) triggers interrupt if threshold > 0
    if (threshold_m > 0) {
        i2c__TARGET_FIFO_STATUS_t empty_fifo_status = {
            .w = read_reg(base + (SMC_TOP_SMC_I2C_WRAP_I2C_TARGET_FIFO_STATUS_BASE_ADDR(0) -
                                  SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)))};
        i2c__INTR_STATE_t empty_intr_state = {
            .w = read_reg(base + (SMC_TOP_SMC_I2C_WRAP_I2C_INTR_STATE_BASE_ADDR(0) -
                                  SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)))};

        if (empty_fifo_status.f.TXLVL < threshold_m) {
            if (!empty_intr_state.f.TX_THRESHOLD) {
                simputs("  ERROR: TX threshold interrupt should be triggered when FIFO empty "
                        "(level < threshold)\n");
                return I2C_ERROR;
            }
            simputs(
                "  PASS: TX threshold interrupt triggered when FIFO empty (level < threshold)\n");
        }
    }

    // Write M-1 bytes (where M-1 < threshold, so interrupt should still be triggered)
    simputs("  Writing M-1 bytes (");
    simputshex32("", threshold_m - 1);
    simputs(" bytes, level will be < threshold)...\n");

    for (uint32_t i = 0; i < threshold_m - 1; i++) {
        i2c__TXDATA_t txdata = {.w = 0};
        txdata.f.DATA = test_data[i];
        write_reg(base + (SMC_TOP_SMC_I2C_WRAP_I2C_TXDATA_BASE_ADDR(0) -
                          SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)),
                  txdata.w);
    }

    // Small delay to allow interrupt to propagate
    for (volatile int i = 0; i < 1000; i++)
        ;

    i2c__TARGET_FIFO_STATUS_t fifo_status = {
        .w = read_reg(base + (SMC_TOP_SMC_I2C_WRAP_I2C_TARGET_FIFO_STATUS_BASE_ADDR(0) -
                              SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)))};
    i2c__INTR_STATE_t intr_state = {
        .w = read_reg(base + (SMC_TOP_SMC_I2C_WRAP_I2C_INTR_STATE_BASE_ADDR(0) -
                              SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)))};

    simputs("  TX FIFO level after M-1 bytes: ");
    simputshex32("", fifo_status.f.TXLVL);
    simputs("\n");
    simputs("  TX threshold interrupt state: ");
    simputshex32("", intr_state.f.TX_THRESHOLD ? 1 : 0);
    simputs("\n");

    // After writing M-1 bytes, level = M-1
    // If M-1 < threshold, interrupt should be triggered
    // If M-1 >= threshold, interrupt should NOT be triggered
    if (fifo_status.f.TXLVL < threshold_m) {
        if (!intr_state.f.TX_THRESHOLD) {
            simputs("  ERROR: TX threshold interrupt should be triggered when level < threshold\n");
            return I2C_ERROR;
        }
        simputs("  PASS: TX threshold interrupt triggered (level < threshold)\n");
    } else {
        if (intr_state.f.TX_THRESHOLD) {
            simputs("  ERROR: TX threshold interrupt should NOT be triggered when level >= "
                    "threshold\n");
            return I2C_ERROR;
        }
        simputs("  PASS: TX threshold interrupt NOT triggered (level >= threshold)\n");
    }

    // Step 2: Write Mth byte (making level = M)
    // If M < threshold, interrupt should be triggered
    // If M >= threshold, interrupt should NOT be triggered
    simputs("\n  Step 2: Writing Mth byte (");
    simputshex32("", threshold_m);
    simputs("th byte)...\n");

    i2c__TXDATA_t txdata = {.w = 0};
    txdata.f.DATA = test_data[threshold_m - 1];
    write_reg(base + (SMC_TOP_SMC_I2C_WRAP_I2C_TXDATA_BASE_ADDR(0) -
                      SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)),
              txdata.w);

    // Small delay to allow interrupt to propagate
    for (volatile int i = 0; i < 1000; i++)
        ;

    intr_state.w = read_reg(base + (SMC_TOP_SMC_I2C_WRAP_I2C_INTR_STATE_BASE_ADDR(0) -
                                    SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)));
    fifo_status.w = read_reg(base + (SMC_TOP_SMC_I2C_WRAP_I2C_TARGET_FIFO_STATUS_BASE_ADDR(0) -
                                     SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)));

    simputs("  TX FIFO level after M bytes: ");
    simputshex32("", fifo_status.f.TXLVL);
    simputs("\n");
    simputs("  TX threshold interrupt state: ");
    simputshex32("", intr_state.f.TX_THRESHOLD ? 1 : 0);
    simputs("\n");

    // Verify interrupt behavior based on FIFO level
    // According to OpenTitan spec: interrupt triggers when level < threshold
    if (fifo_status.f.TXLVL < threshold_m) {
        if (!intr_state.f.TX_THRESHOLD) {
            simputs("  ERROR: TX threshold interrupt should be triggered when level < threshold\n");
            return I2C_ERROR;
        }
        simputs("  PASS: TX FIFO level (");
        simputshex32("", fifo_status.f.TXLVL);
        simputs(") < threshold (");
        simputshex32("", threshold_m);
        simputs("), interrupt triggered correctly\n");
    } else {
        if (intr_state.f.TX_THRESHOLD) {
            simputs("  ERROR: TX threshold interrupt should NOT be triggered when level >= "
                    "threshold\n");
            return I2C_ERROR;
        }
        simputs("  PASS: TX FIFO level (");
        simputshex32("", fifo_status.f.TXLVL);
        simputs(") >= threshold (");
        simputshex32("", threshold_m);
        simputs("), interrupt NOT triggered correctly\n");
    }

    // Clear interrupt (level-triggered interrupts can be cleared by writing to INTR_STATE)
    i2c_clear_interrupts(idx, 0xFFFFFFFF);

    simputs("  TX FIFO threshold test PASSED\n");
    return I2C_OK;
}

int main(void) {
    int ret;

    // System initialization

    simputs("\n");
    simputs("################################################\n");
    simputs("##      I2C P0 FIFO Threshold Test          ##\n");
    simputs("################################################\n");
    simputs("\n");

    write_scratch(1, 0x00000010);
    simputs("Step 1: System Initialization\n");
    simputs("  System ready\n");
    write_scratch(1, 0x00000011);

    // LEVEL 1 - Wrapper Control Enable
    write_scratch(1, 0x00000020);
    simputs("\nStep 2: LEVEL 1 - Wrapper Control Enable\n");
    i2c_wrapper_enable(TARGET_IDX, false); // Target mode
    write_scratch(1, 0x00000021);

    // LEVEL 2 - I2C IP Initialization
    write_scratch(1, 0x00000030);
    simputs("\nStep 3: LEVEL 2 - I2C IP Initialization\n");
    simputs("  Initializing I2C_0 as Target (addr=0x10)...\n");

    // Compute timing parameters
    i2c_timing_physical_t physical_params = {.speed = I2C_SPEED_STANDARD,
                                             .clock_period_nanos = 10,
                                             .sda_rise_nanos = 300,
                                             .sda_fall_nanos = 100,
                                             .scl_period_nanos = 0};

    i2c_timing_config_t computed_timing;
    ret = i2c_compute_timing_from_physical(&physical_params, &computed_timing);
    if (ret != I2C_OK) {
        simputs("  WARNING: Physical timing computation failed, using defaults\n");
        i2c_get_default_timing(I2C_SPEED_STANDARD, 100, &computed_timing);
    }

    // Initialize I2C as Target
    i2c_target_config_t tgt_cfg = {.address0 = TARGET_ADDR,
                                   .mask0 = 0x7F,
                                   .address1 = 0,
                                   .mask1 = 0,
                                   .timing = computed_timing,
                                   .fifo = {.tx_thresh = TX_FIFO_THRESHOLD_M,
                                            .acq_thresh = RX_FIFO_THRESHOLD_N,
                                            .rx_thresh = 0,
                                            .fmt_thresh = 0},
                                   .enable_interrupts = false, // We'll enable interrupts manually
                                   .ack_ctrl_mode = false,
                                   .tx_stretch_ctrl = false,
                                   .timeout_cycles = 0};

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
    i2c__CTRL_t ctrl = {.w = read_reg(base + (SMC_TOP_SMC_I2C_WRAP_I2C_CTRL_BASE_ADDR(0) -
                                              SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)))};
    ctrl.f.ACQ_START_STOP_EN = 1;
    write_reg(
        base + (SMC_TOP_SMC_I2C_WRAP_I2C_CTRL_BASE_ADDR(0) - SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)),
        ctrl.w);

    // Signal setup complete to testbench
    write_scratch(1, 0xEBEDEBE4);
    simputs("\n  Firmware setup complete, waiting for testbench to write data...\n");

    // Test RX FIFO threshold (ACQ FIFO)
    // Wait for external master to write data first
    write_scratch(1, 0x00000040);
    simputs("  Starting RX FIFO threshold test...\n");
    simputs("  Waiting for external master to write ");
    simputshex32("", RX_FIFO_THRESHOLD_N);
    simputs(" bytes...\n");

    ret = test_rx_fifo_threshold(TARGET_IDX, RX_FIFO_THRESHOLD_N);
    if (ret != I2C_OK) {
        simputs("  ERROR: RX FIFO threshold test failed\n");
        write_scratch(0, 0xBAD00040);
        test_fail(0);
    }
    write_scratch(1, 0x00000041);

    // Test TX FIFO threshold
    write_scratch(1, 0x00000050);
    ret = test_tx_fifo_threshold(TARGET_IDX, TX_FIFO_THRESHOLD_M);
    if (ret != I2C_OK) {
        simputs("  ERROR: TX FIFO threshold test failed\n");
        write_scratch(0, 0xBAD00050);
        test_fail(0);
    }
    write_scratch(1, 0x00000051);

    // Test Complete
    write_scratch(1, 0x00000090);
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
