/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/* Copyright 2026 Tenstorrent Inc. */
/**
 * @file test_common.h
 * @brief Common test infrastructure for firmware-driven testing
 *
 * Also provides static helpers and constants for programmable KMCSR IRQ entry
 * (`IRQ_ENTRY_ADDR` / `IRQ_ENTRY_LOCK`) used by IRQ-entry firmware tests.
 *
 * This header defines a standardized protocol for firmware tests to report
 * results to the cocotb testbench. All firmware tests should use these
 * macros and functions to ensure consistent behavior.
 *
 * Protocol:
 *   - Firmware writes results to dedicated KMCSR test protocol registers
 *   - Testbench probes these registers for completion and commands
 *   - VUART output is captured for debugging/logging
 *
 * Register Locations (KMCSR base 0xE000):
 *   - TB_RESULT    @ 0xE110 - Test result (0=fail, 1=pass)
 *   - TB_SIGNATURE @ 0xE114 - Completion signature
 *   - TB_ERRCODE   @ 0xE118 - Error code
 *   - TB_SUBTEST   @ 0xE11C - Current subtest number
 *   - TB_CMD       @ 0xE120 - Command from FW to TB
 *   - TB_CMD_ARG   @ 0xE124 - Command argument
 *   - TB_CMD_STATUS@ 0xE128 - Status from TB to FW
 *   - TB_CMD_RESULT@ 0xE12C - Result from TB to FW
 *
 * Usage:
 *   #include "test_common.h"
 *
 *   int main(void) {
 *       TEST_INIT();
 *
 *       // Run tests...
 *       if (some_condition_failed) {
 *           TEST_FAIL("Condition failed: expected %d, got %d", expected, actual);
 *       }
 *
 *       TEST_PASS();
 *       return 0;
 *   }
 */

#ifndef TEST_COMMON_H
#define TEST_COMMON_H

#include <stdint.h>
#include <stddef.h>
#include "vuart.h"
#include "key_manager_fw.h"
#include "rom_boot.h"
#include "rom_picorv32.h"
#include "rom_kmcsr.h"
#include "irq_common.h"

/* OTP/eFuse window addresses come from key_manager_addr.h (PeakRDL). */
#ifndef ROM_KM_OTP_BASE
#define ROM_KM_OTP_BASE KEY_MANAGER_OTP_EFUSE_MAP_BASE_ADDR
#endif

/* Expected KMCSR VERSION word. The generator emits per-field reset values but no
 * register-level default, so compose it from the fields rather than restating the
 * version in every test that reads it. */
#define KMCSR_VERSION_RESET \
    ((KM_CSR__VERSION_REG__MAJOR_reset << KM_CSR__VERSION_REG__MAJOR_bp) | \
     (KM_CSR__VERSION_REG__MINOR_reset << KM_CSR__VERSION_REG__MINOR_bp) | \
     (KM_CSR__VERSION_REG__PATCH_reset << KM_CSR__VERSION_REG__PATCH_bp))

/* SEP-side mailbox registers are not reachable from the KM CPU; these types only
 * build the bit patterns handed to the tb_sep_mbox_* commands. Alias the generated
 * types so a layout here cannot drift from the RDL the hardware decodes. */
typedef km_mailbox_sep__ctrl_reg_t KM_MAILBOX_SEP_CTRL_REG_reg_u;
typedef km_mailbox_sep__status_reg_t KM_MAILBOX_SEP_STATUS_REG_reg_u;
typedef km_mailbox_sep__irq_status_reg_t KM_MAILBOX_SEP_IRQ_STATUS_REG_reg_u;
typedef km_mailbox_sep__irq_enable_reg_t KM_MAILBOX_SEP_IRQ_ENABLE_REG_reg_u;

/*===========================================================================
 * Memory Map - Test Result Locations (KMCSR Registers)
 *===========================================================================*/

/* Register access macros using struct types */
#define TEST_RESULT_REG (*(volatile km_csr__tb_result_reg_t *)KEY_MANAGER_KMCSR_TB_RESULT_BASE_ADDR)
#define TEST_SIGNATURE_REG \
    (*(volatile km_csr__tb_signature_reg_t *)KEY_MANAGER_KMCSR_TB_SIGNATURE_BASE_ADDR)
#define TEST_ERRCODE_REG \
    (*(volatile km_csr__tb_errcode_reg_t *)KEY_MANAGER_KMCSR_TB_ERRCODE_BASE_ADDR)
#define TEST_SUBTEST_REG \
    (*(volatile km_csr__tb_subtest_reg_t *)KEY_MANAGER_KMCSR_TB_SUBTEST_BASE_ADDR)
#define TB_CMD_REG (*(volatile km_csr__tb_cmd_reg_t *)KEY_MANAGER_KMCSR_TB_CMD_BASE_ADDR)
#define TB_CMD_ARG_REG \
    (*(volatile km_csr__tb_cmd_arg_reg_t *)KEY_MANAGER_KMCSR_TB_CMD_ARG_BASE_ADDR)
#define TB_CMD_STATUS_REG \
    (*(volatile km_csr__tb_cmd_status_reg_t *)KEY_MANAGER_KMCSR_TB_CMD_STATUS_BASE_ADDR)
#define TB_CMD_RESULT_REG \
    (*(volatile km_csr__tb_cmd_result_reg_t *)KEY_MANAGER_KMCSR_TB_CMD_RESULT_BASE_ADDR)

/* SRAM base */
#define SRAM_BASE 0x00004000

/* ROM region */
#define ROM_BASE 0x00000000
#define ROM_TEST_OFFSET 0x00000100 /* Offset used for ROM read/write tests */

/* Signatures */
#define TEST_PASS_SIGNATURE 0x600D600D /* "GOOD GOOD" */
#define TEST_FAIL_SIGNATURE 0xBADBADBA /* "BAD BAD" */
#define TEST_RUNNING_SIG 0x52554E4E    /* "RUNN" */

/* Testbench commands */
#define TB_CMD_NOP 0x00000000                 /* No operation */
#define TB_CMD_ROM_PARITY_EN 0x00000001       /* Enable ROM parity error injection */
#define TB_CMD_ROM_PARITY_DIS 0x00000002      /* Disable ROM parity error injection */
#define TB_CMD_SRAM_PARITY_EN 0x00000003      /* Enable SRAM parity error injection */
#define TB_CMD_SRAM_PARITY_DIS 0x00000004     /* Disable SRAM parity error injection */
#define TB_CMD_SRAM_READ_RAW 0x00000005       /* Read raw SRAM data (before descrambling) */
#define TB_CMD_SEP_MBOX_WRITE 0x00000006      /* Write data to SEP mailbox inbound FIFO */
#define TB_CMD_MONITOR_EN 0x00000007          /* Enable CPU/memory monitoring */
#define TB_CMD_MONITOR_DIS 0x00000008         /* Disable CPU/memory monitoring */
#define TB_CMD_SEP_MBOX_IRQ_ENABLE 0x00000009 /* Enable/disable SEP mailbox IRQ */
#define TB_CMD_SEP_MBOX_READ 0x0000000A       /* Read data from SEP mailbox outbound FIFO */
#define TB_CMD_SEP_MBOX_IRQ_CHECK 0x0000000B  /* Check SEP mailbox IRQ status */
#define TB_CMD_SEP_MBOX_WRITE_WITH_RESP \
    0x0000000C /* Write to SEP mailbox and return AXI response */
#define TB_CMD_KM_MBOX_READ_WITH_RESP \
    0x0000000D                        /* Read from KM mailbox and return AXI response \
                                       */
#define TB_CMD_TIMEOUT_SET 0x0000000E /* Set testbench timeout value (cycles) */
#define TB_CMD_SEP_MBOX_READ_WITH_RESP \
    0x0000000F                                  /* Read from SEP mailbox and return AXI response */
#define TB_CMD_SEP_MBOX_STATUS_READ 0x00000010  /* Read SEP mailbox STATUS register */
#define TB_CMD_SEP_MBOX_STATUS_WRITE 0x00000011 /* Write SEP mailbox STATUS register */
#define TB_CMD_SEP_MBOX_CTRL_WRITE 0x00000012   /* Write SEP mailbox CTRL register */
#define TB_CMD_VUART_VERIFY \
    0x00000013 /* Verify VUART received expected string (arg = SRAM byte address of \
                  null-terminated string) */
#define TB_CMD_SEP_MBOX_IRQ_STATUS_READ 0x00000014 /* Read SEP mailbox IRQ_STATUS register */
#define TB_CMD_SEP_MBOX_IRQ_STATUS_WRITE \
    0x00000015 /* Write SEP mailbox IRQ_STATUS register (W1C) */
#define TB_CMD_DRBG_SET_NEXT_VALUE \
    0x0000001A /* Override next value from DRBG (arg = value); TB normally returns random; result \
                  = 1 */
#define TB_CMD_DRBG_GET_NEXT_VALUE \
    0x0000001B /* Get value scheduled next from DRBG (random or overridden by SET); result = \
                  32-bit value */
#define TB_CMD_DRBG_SET_SEED \
    0x0000001C /* Set seed for deterministic DRBG (arg = 32-bit seed); result = 1 */
#define TB_CMD_DRBG_STOP \
    0x0000001D /* Stop sending DRBG data after current beat (TVALID held until TREADY); result = 1 \
                */
#define TB_CMD_DRBG_START 0x0000001E /* Resume sending DRBG data; result = 1 */
#define TB_CMD_CHECK_RECOVERABLE_ERR \
    0x0000001F /* Testbench samples recoverable_err; result = 1 if set, 0 if clear */
#define TB_CMD_CHECK_UNRECOVERABLE_RESTART \
    0x00000020 /* Ask TB: was CPU restarted due to unrecoverable fault? result = 1 if yes, 0 if no \
                */
#define TB_CMD_OTP_WRITE \
    0x00000021 /* TB drives otp_data_i port with known pattern (read-through); result = 1 */
#define TB_CMD_WIPE_TRIGGER 0x00000022 /* TB asserts wipe_state_i for one cycle; result = 1 */
#define TB_CMD_SEP_MBOX_WRITE_SEPARATOR_WRITE \
    0x00000023 /* Write SEP mailbox WRITE_SEPARATOR register */
#define TB_CMD_KEY_SHARE_READ \
    0x00000024 /* Read key share word via hwif_out; arg=[11:8]=engine,[4]=share,[3:0]=word */
#define TB_CMD_GET_UNRECOVERABLE_FAULT_CODE \
    0x00000025 /* Get fault code captured from SEP mailbox before unrecoverable reset */
#define TB_CMD_INJECT_SPURIOUS_IRQ \
    0x00000026 /* Force a spurious IRQ bit into PicoRV32 (arg = bitmask); result = 1 */
#define TB_CMD_UNRECOVERABLE_WATCH_CTRL \
    0x00000027 /* Arm/disarm unrecoverable watch (arg=1 arm, 0 disarm); result = 1 */
#define TB_CMD_GET_CYCLE_COUNT \
    0x00000028 /* Snapshot current testbench cycle counter; result = cycles */
#define TB_CMD_KM_ASYNC_RESET \
    0x00000029 /* Assert top-level cold_rst_n pulse (external cold/async reset); result = 1 */
#define TB_CMD_DRBG_TVALID_GLITCH \
    0x0000002A /* One-shot: assert TVALID for 1 cycle then drop without TREADY (AXI-Stream \
                  protocol violation for STREAM_ERR testing); result = 1 */
#define TB_CMD_DRBG_QUEUE_BEAT \
    0x0000002B /* Queue one DRBG beat: arg[3:0]=TSTRB; tdata taken from last \
                  TB_CMD_DRBG_SET_NEXT_VALUE; beat is sent before next default-random beat; result \
                  = 1 */
#define TB_CMD_KM_WARM_RESET 0x0000002C /* Pulse warm_rst_n input for 22+ cycles; result = 1 */
#define TB_CMD_OTP_WRITE_CHANGED \
    0x0000002D /* Drive changed OTP pattern (different 256-bit values); result = 1 */
#define TB_CMD_OTP_WRITE_SIGINT \
    0x0000002E /* Drive a corrupted dual-rail on chiplet_uid (value != ~cpl); result = 1 */
#define TB_CMD_SEP_MBOX_DRAIN_CTRL \
    0x0000002F /* Arm/disarm autonomous SEP outbound-FIFO drainer (models SEP draining KM->SEP); \
                  arg=1 arm, 0 disarm; result = 1 */
#define TB_CMD_ABR_SK_LOAD \
    0x00000030 /* Inject ABR shared-key word or pulse hwset: arg=word_idx(0-7) loads word from \
                  last DRBG_SET_NEXT_VALUE; arg=0xFF pulses hwset; result = 1 */
#define TB_CMD_ABR_SK_IRQ_STATUS_READ \
    0x00000031 /* Read abr_mlkem_sharedkey_irq level; result = 0 or 1 */

/* Testbench command status */
#define TB_STATUS_IDLE 0x00000000 /* Ready for command */
#define TB_STATUS_ACK 0x00000001  /* Command acknowledged */
#define TB_STATUS_ERR 0xFFFFFFFF  /* Command error */

/* Convenience macros for test results */
#define TEST_RESULT TEST_RESULT_REG.w
#define TEST_SIGNATURE TEST_SIGNATURE_REG.w
#define TEST_ERRCODE TEST_ERRCODE_REG.w
#define TEST_SUBTEST TEST_SUBTEST_REG.w

/* Convenience macros for testbench commands */
#define TB_CMD TB_CMD_REG.w
#define TB_CMD_ARG TB_CMD_ARG_REG.w
#define TB_CMD_STATUS TB_CMD_STATUS_REG.w
#define TB_CMD_RESULT TB_CMD_RESULT_REG.w

/*===========================================================================
 * Programmable IRQ entry (KMCSR IRQ_ENTRY_ADDR / IRQ_ENTRY_LOCK)
 *===========================================================================*/

/** @brief VROM PC for `.text.alt_irq`; must match `link/modes/vrom.ld`. */
#define IRQ_ENTRY_ALT_VROM_PC 0x10000100u

/** @brief Iterations to busy-wait after IRQ_SET before observing handler effects. */
#define IRQ_ENTRY_SETTLE_LOOPS 800u

/**
 * @brief Bitmask of KMCSR IRQ_STATUS fields cleared by IRQ-entry tests.
 *
 * @return Word suitable for `rom_kmcsr_irq_status_clear()`.
 */
static inline uint32_t irq_entry_test_all_status_mask(void) {
    km_csr__irq_status_reg_t mask = {0};
    mask.f.rom_parity_err = 1;
    mask.f.sram_parity_err = 1;
    mask.f.rom_write_err = 1;
    mask.f.sram_write_lock_err = 1;
    mask.f.axi_slverr = 1;
    mask.f.axi_decerr = 1;
    mask.f.drbg_err = 1;
    mask.f.wipe_state = 1;
    return mask.w;
}

/**
 * @brief IRQ_SET register value to assert sticky ROM parity error.
 *
 * @return Word suitable for `rom_kmcsr_irq_set()`.
 */
static inline uint32_t irq_entry_irq_set_rom_parity(void) {
    km_csr__irq_set_reg_t set_val = {0};
    set_val.f.rom_parity_err_set = 1;
    return set_val.w;
}

/**
 * @brief Read `IRQ_ENTRY_ADDR`.
 *
 * @return Current programmed IRQ entry address (`addr` field).
 */
static inline uint32_t irq_entry_addr_read(void) {
    volatile km_csr__irq_entry_addr_reg_t *reg =
        (volatile km_csr__irq_entry_addr_reg_t *)KEY_MANAGER_KMCSR_IRQ_ENTRY_ADDR_BASE_ADDR;
    return reg->f.addr;
}

/**
 * @brief Write `IRQ_ENTRY_ADDR` (ignored when lock is set).
 *
 * @param v Entry address to program.
 */
static inline void irq_entry_addr_write(uint32_t v) {
    volatile km_csr__irq_entry_addr_reg_t *reg =
        (volatile km_csr__irq_entry_addr_reg_t *)KEY_MANAGER_KMCSR_IRQ_ENTRY_ADDR_BASE_ADDR;
    km_csr__irq_entry_addr_reg_t w = {0};
    w.f.addr = v;
    reg->w = w.w;
}

/**
 * @brief Read `IRQ_ENTRY_LOCK.lock`.
 *
 * @return Non-zero if the lock bit is set.
 */
static inline uint32_t irq_entry_lock_read(void) {
    volatile km_csr__irq_entry_lock_reg_t *reg =
        (volatile km_csr__irq_entry_lock_reg_t *)KEY_MANAGER_KMCSR_IRQ_ENTRY_LOCK_BASE_ADDR;
    return reg->f.lock;
}

/** @brief Write 1 to `IRQ_ENTRY_LOCK` (sticky until reset). */
static inline void irq_entry_lock_write1(void) {
    volatile km_csr__irq_entry_lock_reg_t *reg =
        (volatile km_csr__irq_entry_lock_reg_t *)KEY_MANAGER_KMCSR_IRQ_ENTRY_LOCK_BASE_ADDR;
    km_csr__irq_entry_lock_reg_t w = {0};
    w.f.lock = 1;
    reg->w = w.w;
}

/**
 * @brief Arm KMCSR ROM parity IRQ, unmask CPU IRQs, and pulse IRQ_SET.
 *
 * Clears IRQ status, enables ROM parity in IRQ_ENABLE, unmasks the CPU, then
 * sets the sticky ROM parity bit. The caller must implement `rom_irq()` to
 * W1C-clear IRQ_STATUS as needed.
 */
static inline void irq_entry_fire_kmcsr_rom_parity(void) {
    rom_kmcsr_irq_status_clear(irq_entry_test_all_status_mask());
    {
        km_csr__irq_enable_reg_t en = {0};
        en.f.rom_parity_en = 1;
        rom_kmcsr_irq_enable_write(en.w);
    }
    (void)rom_picorv32_maskirq(0u);
    rom_kmcsr_irq_set(irq_entry_irq_set_rom_parity());
    __asm__ volatile("fence" ::: "memory");
    for (volatile uint32_t i = 0; i < IRQ_ENTRY_SETTLE_LOOPS; i++) {
        __asm__ volatile("nop");
    }
}

/*===========================================================================
 * Test Macros
 *===========================================================================*/

/**
 * Initialize test infrastructure.
 * Call this at the start of main().
 */
#define TEST_INIT() \
    do { \
        TEST_RESULT = 0; \
        TEST_SIGNATURE = TEST_RUNNING_SIG; \
        TEST_ERRCODE = 0; \
        TEST_SUBTEST = 0; \
        TB_CMD = TB_CMD_NOP; \
        TB_CMD_ARG = 0; \
        TB_CMD_STATUS = TB_STATUS_IDLE; \
        /* TB_CMD_RESULT is read-only (testbench writes, firmware reads); do not write */ \
        printf("=== Test Started ===\n"); \
    } while (0)

/**
 * Mark test as passed and halt.
 */
#define TEST_PASS() \
    do { \
        printf("=== Test PASSED ===\n"); \
        TEST_RESULT = 1; \
        TEST_SIGNATURE = TEST_PASS_SIGNATURE; \
        test_halt(); \
    } while (0)

/**
 * Mark test as failed with a message and halt.
 * @param fmt Printf-style format string
 * @param ... Format arguments
 */
#define TEST_FAIL(...) \
    do { \
        printf("FAIL: "); \
        printf(__VA_ARGS__); \
        printf("\n"); \
        printf("=== Test FAILED ===\n"); \
        TEST_RESULT = 0; \
        TEST_SIGNATURE = TEST_FAIL_SIGNATURE; \
        test_halt(); \
    } while (0)

/**
 * Assert a condition, fail if false.
 * @param cond Condition to check
 * @param fmt Error message format if condition fails
 * @param ... Format arguments
 */
#define TEST_ASSERT(cond, ...) \
    do { \
        if (!(cond)) { \
            printf("FAIL: Assertion failed: "); \
            printf(__VA_ARGS__); \
            printf("\n"); \
            printf("=== Test FAILED ===\n"); \
            TEST_RESULT = 0; \
            TEST_SIGNATURE = TEST_FAIL_SIGNATURE; \
            test_halt(); \
        } \
    } while (0)

/**
 * Assert two values are equal.
 */
#define TEST_ASSERT_EQ(actual, expected, name) \
    do { \
        uint32_t _a = (uint32_t)(actual); \
        uint32_t _e = (uint32_t)(expected); \
        if (_a != _e) { \
            TEST_FAIL("%s: expected 0x%08X, got 0x%08X", name, _e, _a); \
        } \
    } while (0)

/**
 * Assert two values are not equal.
 */
#define TEST_ASSERT_NE(actual, not_expected, name) \
    do { \
        uint32_t _a = (uint32_t)(actual); \
        uint32_t _ne = (uint32_t)(not_expected); \
        if (_a == _ne) { \
            TEST_FAIL("%s: should not be 0x%08X", name, _ne); \
        } \
    } while (0)

/**
 * Log a message (appears in VUART output).
 */
#define TEST_LOG(...) \
    do { \
        printf(__VA_ARGS__); \
        printf("\n"); \
    } while (0)

/**
 * Start a named subtest.
 */
#define TEST_SUBTEST_START(name) \
    do { \
        TEST_SUBTEST++; \
        printf("[%d] %s...\n", TEST_SUBTEST, name); \
    } while (0)

/**
 * Mark current subtest as passed.
 */
#define TEST_SUBTEST_PASS() printf("  OK\n")

/**
 * Set an error code (for debugging).
 */
#define TEST_SET_ERROR(code) (TEST_ERRCODE = (code))

/*===========================================================================
 * Helper Functions
 *===========================================================================*/

/**
 * Halt the CPU in a low-power wait loop.
 * Called automatically by TEST_PASS() and TEST_FAIL().
 */
static inline void test_halt(void) {
    while (1) {
        rom_picorv32_waitirq();
    }
}

/**
 * Simple delay loop.
 * @param cycles Approximate number of loop iterations
 */
static inline void test_delay(uint32_t cycles) {
    for (volatile uint32_t i = 0; i < cycles; i++) {
        __asm__ volatile("nop");
    }
}

/**
 * Read a 32-bit value from an address.
 */
static inline uint32_t test_read32(uint32_t addr) {
    return *(volatile uint32_t *)addr;
}

/**
 * Write a 32-bit value to an address.
 */
static inline void test_write32(uint32_t addr, uint32_t value) {
    *(volatile uint32_t *)addr = value;
}

/*===========================================================================
 * Testbench Command Interface
 *===========================================================================
 * These functions allow firmware to send commands to the testbench for
 * operations like error injection that require testbench control.
 *
 * Protocol:
 *   1. Firmware writes command to TB_CMD (with optional arg in TB_CMD_ARG)
 *   2. Testbench monitors TB_CMD, executes command when non-zero
 *   3. Testbench writes TB_STATUS_ACK and clears TB_CMD
 *   4. Firmware polls TB_CMD_STATUS for acknowledgment
 *   5. Firmware clears TB_CMD_STATUS before next command
 */

/**
 * Send a command to the testbench and wait for acknowledgment.
 * @param cmd Command code (TB_CMD_*)
 * @param arg Optional argument (0 if not needed)
 * @param timeout_cycles Maximum cycles to wait for ack
 * @return 1 if acknowledged, 0 if timeout/error
 */
static inline int tb_send_cmd(uint32_t cmd, uint32_t arg, uint32_t timeout_cycles) {
    /* Clear any previous status */
    TB_CMD_STATUS = TB_STATUS_IDLE;

    /* Set argument and command */
    TB_CMD_ARG = arg;
    TB_CMD = cmd;

    /* Wait for testbench to acknowledge */
    for (uint32_t i = 0; i < timeout_cycles; i++) {
        if (TB_CMD_STATUS == TB_STATUS_ACK) {
            /* Clear status for next command */
            TB_CMD_STATUS = TB_STATUS_IDLE;
            return 1;
        }
        if (TB_CMD_STATUS == TB_STATUS_ERR) {
            return 0;
        }
        __asm__ volatile("nop");
    }

    return 0; /* Timeout */
}

/**
 * Enable ROM parity error injection.
 * After this, ROM reads will have corrupted parity.
 */
static inline int tb_rom_parity_inject_enable(void) {
    return tb_send_cmd(TB_CMD_ROM_PARITY_EN, 0, 1000);
}

/**
 * Disable ROM parity error injection.
 */
static inline int tb_rom_parity_inject_disable(void) {
    return tb_send_cmd(TB_CMD_ROM_PARITY_DIS, 0, 1000);
}

/**
 * Enable SRAM parity error injection.
 * After this, SRAM reads will have corrupted parity.
 */
static inline int tb_sram_parity_inject_enable(void) {
    return tb_send_cmd(TB_CMD_SRAM_PARITY_EN, 0, 1000);
}

/**
 * Disable SRAM parity error injection.
 */
static inline int tb_sram_parity_inject_disable(void) {
    return tb_send_cmd(TB_CMD_SRAM_PARITY_DIS, 0, 1000);
}

/**
 * Ask testbench to drive OTP port with known pattern (read-through, no strobe).
 * OTP registers reflect port values immediately after return.
 * @return 1 if acknowledged, 0 if timeout/error (call TEST_FAIL on 0)
 */
static inline int tb_otp_write(void) {
    if (!tb_send_cmd(TB_CMD_OTP_WRITE, 0, 5000u)) {
        TEST_FAIL("TB_CMD_OTP_WRITE failed (timeout or TB_STATUS_ERR)");
    }
    return 1;
}

/**
 * Ask testbench to drive OTP port with a CHANGED pattern (different 256-bit
 * values than TB_CMD_OTP_WRITE), to trigger the OTP_CHANGE interrupt.
 * Life_cycle and demotion state are also changed.
 * @return 1 if acknowledged, 0 if timeout/error (call TEST_FAIL on 0)
 */
static inline int tb_otp_write_changed(void) {
    if (!tb_send_cmd(TB_CMD_OTP_WRITE_CHANGED, 0, 5000u)) {
        TEST_FAIL("TB_CMD_OTP_WRITE_CHANGED failed (timeout or TB_STATUS_ERR)");
    }
    return 1;
}

/**
 * Ask testbench to drive OTP port with a CORRUPTED dual-rail encoding on
 * chiplet_uid (value != ~complement on one word), to trigger OTP_SIGINT.
 * All other fields remain validly dual-rail encoded.
 * @return 1 if acknowledged, 0 if timeout/error (call TEST_FAIL on 0)
 */
static inline int tb_otp_write_sigint(void) {
    if (!tb_send_cmd(TB_CMD_OTP_WRITE_SIGINT, 0, 5000u)) {
        TEST_FAIL("TB_CMD_OTP_WRITE_SIGINT failed (timeout or TB_STATUS_ERR)");
    }
    return 1;
}

/**
 * Trigger wipe: ask testbench to assert wipe_state_i for one cycle.
 * Result = 1 on success. Use for test_wipe_state.
 */
static inline int tb_wipe_trigger(uint32_t timeout_cycles) {
    if (!tb_send_cmd(TB_CMD_WIPE_TRIGGER, 0, timeout_cycles)) {
        return 0;
    }
    return (TB_CMD_RESULT == 1u) ? 1 : 0;
}

/**
 * PRESENT sbox4 lookup table (for address scrambling).
 * Matches PRESENT standard (ISO/IEC 29192-2:2019).
 * This is the only function that MUST match the PRESENT standard.
 */
static const uint8_t sbox4_table[16] = {0xC, 0x5, 0x6, 0xB, 0x9, 0x0, 0xA, 0xD,
                                        0x3, 0xE, 0xF, 0x8, 0x4, 0x7, 0x1, 0x2};

/**
 * Apply perm12 permutation (for address scrambling).
 * Implements bijective permutation for 12-bit blocks.
 * This function matches the scrambler IP's permutation implementation
 * (hw/ip/scrambler/rtl/scrambler_pkg.sv) for test verification purposes.
 * The exact permutation pattern is defined by the scrambler IP, not by PRESENT formulas.
 * The only requirement is that it is bijective (one-to-one mapping).
 * @param d 12-bit input value
 * @return Permuted 12-bit value
 */
static inline uint32_t perm12(uint32_t d) {
    /* Permutation mapping: output[i] = input[perm12_map[i]] */
    /* This matches the scrambler IP's permutation pattern (scrambler_pkg.sv perm12 function) */
    /* Hardware: return {d[1], d[4], d[7], d[10], d[2], d[5], d[8], d[11], d[0], d[6], d[9], d[3]}
     */
    /* In Verilog concatenation, leftmost is MSB (bit 11), rightmost is LSB (bit 0) */
    /* So: output[11]=d[1], output[10]=d[4], ..., output[1]=d[9], output[0]=d[3] */
    static const uint8_t perm12_map[12] = {3, 9, 6, 0, 11, 8, 5, 2, 10, 7, 4, 1};
    uint32_t result = 0;
    for (int i = 0; i < 12; i++) {
        if ((d >> perm12_map[i]) & 1) {
            result |= (1U << i);
        }
    }
    return result & 0xFFF;
}

/**
 * Scramble a 12-bit address using the scrambler algorithm:
 * XOR with key, sbox4 substitution, perm12 permutation.
 * This function matches the scrambler IP's implementation (hw/ip/scrambler) for test
 * verification purposes. The permutation functions are defined by the scrambler IP.
 * @param addr 12-bit logical address (0-4095)
 * @param key 32-bit scrambler key (uses bits [11:0])
 * @return Scrambled 12-bit address
 */
static inline uint32_t addr_scramble12(uint32_t addr, uint32_t key) {
    /* Step 1: XOR address with key[11:0] */
    uint32_t key12 = key & 0xFFF;
    uint32_t ark = (addr ^ key12) & 0xFFF;

    /* Step 2: Split into 3 nibbles and apply sbox4 */
    uint32_t nibble0 = sbox4_table[(ark >> 8) & 0xF];
    uint32_t nibble1 = sbox4_table[(ark >> 4) & 0xF];
    uint32_t nibble2 = sbox4_table[ark & 0xF];
    uint32_t sb = (nibble0 << 8) | (nibble1 << 4) | nibble2;

    /* Step 3: Apply perm12 permutation */
    return perm12(sb);
}

/**
 * Compute address-tweaked round key for data scrambling.
 * Expands a 12-bit address to 32 bits and XORs with key.
 * This matches the scrambler IP's addr_tweak implementation.
 * @param addr 12-bit address
 * @param key 32-bit scrambler key
 * @return 32-bit round key
 */
static inline uint32_t addr_tweak12(uint32_t addr, uint32_t key) {
    /* Expand 12-bit address to 32 bits: {addr, addr, addr[11:4]} */
    uint32_t expanded_addr = (addr << 20) | (addr << 8) | ((addr >> 4) & 0xFF);
    return expanded_addr ^ key;
}

/**
 * Apply player permutation (for data scrambling).
 * This matches the scrambler IP's player function (scrambler_pkg.sv).
 * Verilog concatenation {d[0], d[8], ...} means MSB first, so:
 * output[31] = d[0], output[30] = d[8], output[29] = d[16], etc.
 * @param d 32-bit input value
 * @return Permuted 32-bit value
 */
static inline uint32_t player(uint32_t d) {
    /* Player permutation: {d[0], d[8], d[16], d[24], d[1], d[9], d[17], d[25], ...} */
    uint32_t result = 0;
    result |= ((d >> 0) & 1) << 31;  /* d[0] -> output[31] */
    result |= ((d >> 8) & 1) << 30;  /* d[8] -> output[30] */
    result |= ((d >> 16) & 1) << 29; /* d[16] -> output[29] */
    result |= ((d >> 24) & 1) << 28; /* d[24] -> output[28] */
    result |= ((d >> 1) & 1) << 27;  /* d[1] -> output[27] */
    result |= ((d >> 9) & 1) << 26;  /* d[9] -> output[26] */
    result |= ((d >> 17) & 1) << 25; /* d[17] -> output[25] */
    result |= ((d >> 25) & 1) << 24; /* d[25] -> output[24] */
    result |= ((d >> 2) & 1) << 23;  /* d[2] -> output[23] */
    result |= ((d >> 10) & 1) << 22; /* d[10] -> output[22] */
    result |= ((d >> 18) & 1) << 21; /* d[18] -> output[21] */
    result |= ((d >> 26) & 1) << 20; /* d[26] -> output[20] */
    result |= ((d >> 3) & 1) << 19;  /* d[3] -> output[19] */
    result |= ((d >> 11) & 1) << 18; /* d[11] -> output[18] */
    result |= ((d >> 19) & 1) << 17; /* d[19] -> output[17] */
    result |= ((d >> 27) & 1) << 16; /* d[27] -> output[16] */
    result |= ((d >> 4) & 1) << 15;  /* d[4] -> output[15] */
    result |= ((d >> 12) & 1) << 14; /* d[12] -> output[14] */
    result |= ((d >> 20) & 1) << 13; /* d[20] -> output[13] */
    result |= ((d >> 28) & 1) << 12; /* d[28] -> output[12] */
    result |= ((d >> 5) & 1) << 11;  /* d[5] -> output[11] */
    result |= ((d >> 13) & 1) << 10; /* d[13] -> output[10] */
    result |= ((d >> 21) & 1) << 9;  /* d[21] -> output[9] */
    result |= ((d >> 29) & 1) << 8;  /* d[29] -> output[8] */
    result |= ((d >> 6) & 1) << 7;   /* d[6] -> output[7] */
    result |= ((d >> 14) & 1) << 6;  /* d[14] -> output[6] */
    result |= ((d >> 22) & 1) << 5;  /* d[22] -> output[5] */
    result |= ((d >> 30) & 1) << 4;  /* d[30] -> output[4] */
    result |= ((d >> 7) & 1) << 3;   /* d[7] -> output[3] */
    result |= ((d >> 15) & 1) << 2;  /* d[15] -> output[2] */
    result |= ((d >> 23) & 1) << 1;  /* d[23] -> output[1] */
    result |= ((d >> 31) & 1) << 0;  /* d[31] -> output[0] */
    return result;
}

/**
 * Scramble 32-bit data using the scrambler algorithm.
 * Implements: XOR with round_key, sbox4 substitution, player permutation.
 * This matches the scrambler IP's implementation for test verification.
 * @param data 32-bit input data
 * @param addr 12-bit address (for round key computation)
 * @param key 32-bit scrambler key
 * @return Scrambled 32-bit data
 */
static inline uint32_t data_scramble(uint32_t data, uint32_t addr, uint32_t key) {
    /* Step 1: Compute round key from address and key */
    uint32_t round_key = addr_tweak12(addr, key);

    /* Step 2: XOR data with round key */
    uint32_t after_key_xor = data ^ round_key;

    /* Step 3: Apply sbox4 to each of 8 nibbles */
    uint32_t after_sbox = 0;
    after_sbox |= ((uint32_t)sbox4_table[(after_key_xor >> 28) & 0xF]) << 28;
    after_sbox |= ((uint32_t)sbox4_table[(after_key_xor >> 24) & 0xF]) << 24;
    after_sbox |= ((uint32_t)sbox4_table[(after_key_xor >> 20) & 0xF]) << 20;
    after_sbox |= ((uint32_t)sbox4_table[(after_key_xor >> 16) & 0xF]) << 16;
    after_sbox |= ((uint32_t)sbox4_table[(after_key_xor >> 12) & 0xF]) << 12;
    after_sbox |= ((uint32_t)sbox4_table[(after_key_xor >> 8) & 0xF]) << 8;
    after_sbox |= ((uint32_t)sbox4_table[(after_key_xor >> 4) & 0xF]) << 4;
    after_sbox |= ((uint32_t)sbox4_table[after_key_xor & 0xF]) << 0;

    /* Step 4: Apply player permutation */
    return player(after_sbox);
}

/**
 * Read raw SRAM data (before descrambling).
 * This allows firmware to verify that data was actually scrambled.
 *
 * NOTE: Firmware must calculate the scrambled address if scrambler is enabled.
 * Use addr_scramble12() to compute the physical address before calling this.
 *
 * @param physical_word_addr Physical SRAM word address (scrambled if scrambler enabled)
 * @return Raw data value from SRAM, or 0 on error
 */
static inline uint32_t tb_sram_read_raw(uint32_t physical_word_addr) {
    /* Send command with physical word address as argument */
    if (!tb_send_cmd(TB_CMD_SRAM_READ_RAW, physical_word_addr, 1000)) {
        return 0; /* Error */
    }
    /* Read result from TB_CMD_RESULT */
    return TB_CMD_RESULT;
}

/**
 * Write data to SEP mailbox inbound FIFO (SEP->KM direction).
 * This allows firmware to test mailbox functionality by having the testbench
 * simulate SEP-side writes.
 *
 * @param data 32-bit data word to write to SEP mailbox
 * @param timeout_cycles Maximum cycles to wait for acknowledgment
 * @return 1 if successful, 0 on error/timeout
 */
static inline int tb_sep_mbox_write(uint32_t data, uint32_t timeout_cycles) {
    /* Send command with data as argument */
    if (!tb_send_cmd(TB_CMD_SEP_MBOX_WRITE, data, timeout_cycles)) {
        return 0; /* Error */
    }
    /* Command successful if acknowledged */
    return 1;
}

/**
 * Enable or disable SEP mailbox IRQ.
 * This allows firmware to control SEP mailbox IRQ enable register.
 *
 * @param enable_value IRQ enable value (bit 0 = outbound_read_data_avail_en)
 * @param timeout_cycles Maximum cycles to wait for acknowledgment
 * @return 1 if successful, 0 on error/timeout
 */
static inline int tb_sep_mbox_irq_enable(uint32_t enable_value, uint32_t timeout_cycles) {
    /* Send command with enable value as argument */
    if (!tb_send_cmd(TB_CMD_SEP_MBOX_IRQ_ENABLE, enable_value, timeout_cycles)) {
        return 0; /* Error */
    }
    /* Command successful if acknowledged */
    return 1;
}

/**
 * Read data from SEP mailbox outbound FIFO (KM->SEP direction).
 * This allows firmware to test mailbox functionality by having the testbench
 * simulate SEP-side reads.
 *
 * @param data_out Pointer to store read data
 * @param timeout_cycles Maximum cycles to wait for acknowledgment
 * @return 1 if successful, 0 on error/timeout
 */
static inline int tb_sep_mbox_read(uint32_t *data_out, uint32_t timeout_cycles) {
    /* Send command */
    if (!tb_send_cmd(TB_CMD_SEP_MBOX_READ, 0, timeout_cycles)) {
        return 0; /* Error */
    }
    /* Read result from TB_CMD_RESULT */
    *data_out = TB_CMD_RESULT;
    return 1;
}

/**
 * Arm or disarm the testbench's autonomous SEP outbound-FIFO drainer.
 *
 * When armed, the testbench continuously consumes any word the KM writes to
 * the outbound (KM->SEP) FIFO, modelling a SEP that promptly reads responses.
 * Handover tests arm this just before dispatching a firmware-load command so
 * that rom_handover_finish()'s wait-for-outbound-drain step can complete: the
 * single test CPU is stuck spinning inside the handover and cannot issue the
 * usual TB_CMD-driven reads itself.
 *
 * @param enable 1 to arm the drainer, 0 to disarm
 * @param timeout_cycles Maximum cycles to wait for acknowledgment
 * @return 1 if successful, 0 on error/timeout
 */
static inline int tb_sep_mbox_drain_enable(uint32_t enable, uint32_t timeout_cycles) {
    return tb_send_cmd(TB_CMD_SEP_MBOX_DRAIN_CTRL, enable, timeout_cycles) ? 1 : 0;
}

/**
 * Check SEP mailbox IRQ status.
 * This allows firmware to verify that SEP IRQ is asserted/deasserted.
 *
 * @param irq_status_out Pointer to store IRQ status (1=asserted, 0=deasserted)
 * @param timeout_cycles Maximum cycles to wait for acknowledgment
 * @return 1 if successful, 0 on error/timeout
 */
static inline int tb_sep_mbox_irq_check(uint32_t *irq_status_out, uint32_t timeout_cycles) {
    /* Send command */
    if (!tb_send_cmd(TB_CMD_SEP_MBOX_IRQ_CHECK, 0, timeout_cycles)) {
        return 0; /* Error */
    }
    /* Read result from TB_CMD_RESULT */
    *irq_status_out = TB_CMD_RESULT;
    return 1;
}

/**
 * Read data from SEP mailbox outbound FIFO and get AXI response code.
 * This allows firmware to test underflow conditions by checking response codes.
 *
 * @param data_out Pointer to store read data
 * @param resp_out Pointer to store AXI response code (0=OKAY, 2=SLVERR, 3=DECERR)
 * @param timeout_cycles Maximum cycles to wait for acknowledgment
 * @return 1 if successful, 0 on error/timeout
 */
static inline int tb_sep_mbox_read_with_resp(uint32_t *data_out, uint32_t *resp_out,
                                             uint32_t timeout_cycles) {
    /* Send command */
    if (!tb_send_cmd(TB_CMD_SEP_MBOX_READ_WITH_RESP, 0, timeout_cycles)) {
        return 0; /* Error */
    }
    /* Response code is in lower 8 bits, data in upper 24 bits of TB_CMD_RESULT */
    /* Format: [31:8] = data, [7:0] = response code */
    uint32_t result = TB_CMD_RESULT;
    *resp_out = result & 0xFF;            /* Response in lower 8 bits */
    *data_out = (result >> 8) & 0xFFFFFF; /* Data in upper 24 bits */
    return 1;
}

/**
 * Write data to SEP mailbox inbound FIFO and get AXI response code.
 * This allows firmware to test overflow conditions by checking response codes.
 *
 * @param data 32-bit data word to write to SEP mailbox
 * @param resp_out Pointer to store AXI response code (0=OKAY, 2=SLVERR, 3=DECERR)
 * @param timeout_cycles Maximum cycles to wait for acknowledgment
 * @return 1 if successful, 0 on error/timeout
 */
static inline int tb_sep_mbox_write_with_resp(uint32_t data, uint32_t *resp_out,
                                              uint32_t timeout_cycles) {
    /* Send command with data as argument */
    if (!tb_send_cmd(TB_CMD_SEP_MBOX_WRITE_WITH_RESP, data, timeout_cycles)) {
        return 0; /* Error */
    }
    /* Read response code from TB_CMD_RESULT */
    *resp_out = TB_CMD_RESULT;
    return 1;
}

/**
 * Read SEP mailbox STATUS register.
 * This allows firmware to read SEP-side mailbox STATUS register via testbench interface.
 *
 * @param status_out Pointer to store STATUS register value
 * @param timeout_cycles Maximum cycles to wait for acknowledgment
 * @return 1 if successful, 0 on error/timeout
 */
static inline int tb_sep_mbox_status_read(uint32_t *status_out, uint32_t timeout_cycles) {
    /* Send command */
    if (!tb_send_cmd(TB_CMD_SEP_MBOX_STATUS_READ, 0, timeout_cycles)) {
        return 0; /* Error */
    }
    /* Read result from TB_CMD_RESULT */
    *status_out = TB_CMD_RESULT;
    return 1;
}

/**
 * Write SEP mailbox STATUS register.
 * This allows firmware to write SEP-side mailbox STATUS register via testbench interface.
 * Used primarily for clearing status bits (write-1-to-clear).
 *
 * @param status_value Value to write to STATUS register
 * @param timeout_cycles Maximum cycles to wait for acknowledgment
 * @return 1 if successful, 0 on error/timeout
 */
static inline int tb_sep_mbox_status_write(uint32_t status_value, uint32_t timeout_cycles) {
    /* Send command with status value as argument */
    if (!tb_send_cmd(TB_CMD_SEP_MBOX_STATUS_WRITE, status_value, timeout_cycles)) {
        return 0; /* Error */
    }
    /* Command successful if acknowledged */
    return 1;
}

/**
 * Write SEP mailbox CTRL register.
 * This allows firmware to write SEP-side mailbox CTRL register via testbench interface.
 * Used for configuring underflow/overflow response behavior.
 *
 * @param ctrl_value Value to write to CTRL register
 * @param timeout_cycles Maximum cycles to wait for acknowledgment
 * @return 1 if successful, 0 on error/timeout
 */
static inline int tb_sep_mbox_ctrl_write(uint32_t ctrl_value, uint32_t timeout_cycles) {
    /* Send command with CTRL value as argument */
    if (!tb_send_cmd(TB_CMD_SEP_MBOX_CTRL_WRITE, ctrl_value, timeout_cycles)) {
        return 0; /* Error */
    }
    /* Command successful if acknowledged */
    return 1;
}

/**
 * Write SEP mailbox WRITE_SEPARATOR register.
 * This allows firmware to set the message separator on the SEP side via testbench interface.
 *
 * @param value Value to write to WRITE_SEPARATOR register (bit 0 = set separator)
 * @param timeout_cycles Maximum cycles to wait for acknowledgment
 * @return 1 if successful, 0 on error/timeout
 */
static inline int tb_sep_mbox_write_separator_write(uint32_t value, uint32_t timeout_cycles) {
    if (!tb_send_cmd(TB_CMD_SEP_MBOX_WRITE_SEPARATOR_WRITE, value, timeout_cycles)) {
        return 0;
    }
    return 1;
}

/**
 * Read SEP mailbox IRQ_STATUS register.
 * This allows firmware to read SEP-side mailbox IRQ_STATUS (e.g. FLUSHED_BY_KM) via testbench.
 *
 * @param irq_status_out Pointer to store IRQ_STATUS register value
 * @param timeout_cycles Maximum cycles to wait for acknowledgment
 * @return 1 if successful, 0 on error/timeout
 */
static inline int tb_sep_mbox_irq_status_read(uint32_t *irq_status_out, uint32_t timeout_cycles) {
    if (!tb_send_cmd(TB_CMD_SEP_MBOX_IRQ_STATUS_READ, 0, timeout_cycles)) {
        return 0;
    }
    *irq_status_out = TB_CMD_RESULT;
    return 1;
}

/**
 * Write SEP mailbox IRQ_STATUS register (W1C).
 * This allows firmware to clear SEP-side IRQ status bits (e.g. FLUSHED_BY_KM) via testbench.
 *
 * @param irq_status_value Value to write (bits to clear, W1C)
 * @param timeout_cycles Maximum cycles to wait for acknowledgment
 * @return 1 if successful, 0 on error/timeout
 */
static inline int tb_sep_mbox_irq_status_write(uint32_t irq_status_value, uint32_t timeout_cycles) {
    if (!tb_send_cmd(TB_CMD_SEP_MBOX_IRQ_STATUS_WRITE, irq_status_value, timeout_cycles)) {
        return 0;
    }
    return 1;
}

/**
 * Read data from KM mailbox inbound FIFO and get AXI response code.
 * This allows firmware to test underflow conditions by checking response codes.
 *
 * @param data_out Pointer to store read data
 * @param resp_out Pointer to store AXI response code (0=OKAY, 2=SLVERR, 3=DECERR)
 * @param timeout_cycles Maximum cycles to wait for acknowledgment
 * @return 1 if successful, 0 on error/timeout
 */
static inline int tb_km_mbox_read_with_resp(uint32_t *data_out, uint32_t *resp_out,
                                            uint32_t timeout_cycles) {
    /* Send command */
    if (!tb_send_cmd(TB_CMD_KM_MBOX_READ_WITH_RESP, 0, timeout_cycles)) {
        return 0; /* Error */
    }
    /* Response code is in lower 8 bits of TB_CMD_RESULT */
    /* For underflow testing, we only need the response code, not the data */
    *resp_out = TB_CMD_RESULT & 0xFF; /* Response in lower 8 bits */
    *data_out = 0;                    /* Data not meaningful for underflow (SLVERR case) */
    return 1;
}

/**
 * Set the testbench timeout value.
 * This allows firmware tests to dynamically adjust the timeout based on their needs.
 *
 * @param timeout_cycles New timeout value in cycles (must be > 0)
 * @return 1 if successful, 0 on error/timeout
 */
static inline int tb_set_timeout(uint32_t timeout_cycles) {
    if (timeout_cycles == 0) {
        return 0; /* Invalid timeout value */
    }
    /* Send command with timeout value as argument */
    return tb_send_cmd(TB_CMD_TIMEOUT_SET, timeout_cycles, 1000);
}

/**
 * Snapshot the current testbench cycle counter.
 * This is intended for focused firmware microbenchmarks that need to compare
 * multiple code paths within one test while reusing the testbench's cycle
 * accounting.
 *
 * @param cycle_count_out Pointer to store the current cycle count
 * @param timeout_cycles Maximum cycles to wait for acknowledgment
 * @return 1 if successful, 0 on error/timeout
 */
static inline int tb_get_cycle_count(uint32_t *cycle_count_out, uint32_t timeout_cycles) {
    if (!tb_send_cmd(TB_CMD_GET_CYCLE_COUNT, 0, timeout_cycles)) {
        return 0;
    }
    *cycle_count_out = TB_CMD_RESULT;
    return 1;
}

/**
 * Verify that VUART received the expected string.
 * The expected string must be stored in SRAM as a null-terminated string.
 *
 * @param sram_byte_addr SRAM byte address where expected null-terminated string is stored
 * @param timeout_cycles Maximum cycles to wait for acknowledgment
 * @return 1 if verification passed (string found in VUART output), 0 on failure/timeout
 */
static inline int tb_vuart_verify(uint32_t sram_byte_addr, uint32_t timeout_cycles) {
    /* Send command with SRAM byte address as argument */
    if (!tb_send_cmd(TB_CMD_VUART_VERIFY, sram_byte_addr, timeout_cycles)) {
        return 0; /* Error or timeout */
    }
    /* Result is in TB_CMD_RESULT: 1 = verification passed, 0 = failed */
    return TB_CMD_RESULT != 0;
}

/**
 * Override the next 32-bit value the testbench will send on the DRBG AXI-Stream.
 * The testbench normally returns random data; this overrides the next value (e.g. for
 * verification). After each handshake the TB refills with random unless overridden again.
 *
 * @param value 32-bit value to present on next DRBG handshake
 * @param timeout_cycles Maximum cycles to wait for acknowledgment
 * @return 1 if successful, 0 on error/timeout
 */
static inline int tb_drbg_set_next_value(uint32_t value, uint32_t timeout_cycles) {
    if (!tb_send_cmd(TB_CMD_DRBG_SET_NEXT_VALUE, value, timeout_cycles)) {
        return 0;
    }
    return TB_CMD_RESULT != 0;
}

/**
 * Get the value scheduled to come next from the DRBG (random or overridden by SET).
 * For verification: SET(override), GET(&expected), then read DRBG DATA and compare to expected.
 *
 * @param value_out Pointer to store the 32-bit value
 * @param timeout_cycles Maximum cycles to wait for acknowledgment
 * @return 1 if successful, 0 on error/timeout
 */
static inline int tb_drbg_get_next_value(uint32_t *value_out, uint32_t timeout_cycles) {
    if (!tb_send_cmd(TB_CMD_DRBG_GET_NEXT_VALUE, 0, timeout_cycles)) {
        return 0;
    }
    *value_out = TB_CMD_RESULT;
    return 1;
}

/**
 * Set the seed for the testbench's deterministic DRBG. Subsequent "random" values
 * are reproducible for the same seed.
 *
 * @param seed 32-bit seed value
 * @param timeout_cycles Maximum cycles to wait for acknowledgment
 * @return 1 if successful, 0 on error/timeout
 */
static inline int tb_drbg_set_seed(uint32_t seed, uint32_t timeout_cycles) {
    if (!tb_send_cmd(TB_CMD_DRBG_SET_SEED, seed, timeout_cycles)) {
        return 0;
    }
    return TB_CMD_RESULT != 0;
}

/**
 * Stop the testbench from sending DRBG data. The TB will complete the current
 * beat (TVALID held until TREADY) then deassert TVALID. Use for timeout tests.
 *
 * @param timeout_cycles Maximum cycles to wait for acknowledgment
 * @return 1 if successful, 0 on error/timeout
 */
static inline int tb_drbg_stop(uint32_t timeout_cycles) {
    if (!tb_send_cmd(TB_CMD_DRBG_STOP, 0, timeout_cycles)) {
        return 0;
    }
    return TB_CMD_RESULT != 0;
}

/**
 * Resume the testbench sending DRBG data after a stop.
 *
 * @param timeout_cycles Maximum cycles to wait for acknowledgment
 * @return 1 if successful, 0 on error/timeout
 */
static inline int tb_drbg_start(uint32_t timeout_cycles) {
    if (!tb_send_cmd(TB_CMD_DRBG_START, 0, timeout_cycles)) {
        return 0;
    }
    return TB_CMD_RESULT != 0;
}

/**
 * Inject a one-shot AXI-Stream protocol violation: assert TVALID for exactly
 * one clock cycle then deassert it before TREADY is seen, triggering the
 * STREAM_ERR detection path in km_drbg_sampler.
 *
 * The TB driver is quiesced after the glitch; call tb_drbg_start() to
 * resume normal DRBG data flow afterwards.
 *
 * @param timeout_cycles Maximum cycles to wait for acknowledgment
 * @return 1 if successful, 0 on error/timeout
 */
static inline int tb_drbg_tvalid_glitch(uint32_t timeout_cycles) {
    if (!tb_send_cmd(TB_CMD_DRBG_TVALID_GLITCH, 0, timeout_cycles)) {
        return 0;
    }
    return TB_CMD_RESULT != 0;
}

/**
 * Queue one DRBG beat with explicit TSTRB.
 *
 * The data value for the beat is taken from the most recent call to
 * tb_drbg_set_next_value().  The queued beat is driven on the DRBG
 * AXI-Stream interface ahead of the normal deterministic-random stream.
 * Multiple queued beats are driven in the order they were enqueued.
 *
 * Usage pattern for TSTRB assembly tests:
 *   tb_drbg_set_next_value(0xAABBCCDD, 1000);  // set data for beat
 *   tb_drbg_queue_beat(0x3, 1000);              // enqueue beat (TSTRB=0x3)
 *   tb_drbg_set_next_value(0xEEFF1122, 1000);  // set data for next beat
 *   tb_drbg_queue_beat(0xC, 1000);              // enqueue beat (TSTRB=0xC)
 *   read_val = DRBG_DATA_REG.f.DATA;            // assembled word = 0xEEFFCCDD
 *
 * @param tstrb_4b     4-bit TSTRB value for this beat (bits 3:0)
 * @param timeout_cycles Maximum cycles to wait for acknowledgment
 * @return 1 if successful, 0 on error/timeout
 */
static inline int tb_drbg_queue_beat(uint32_t tstrb_4b, uint32_t timeout_cycles) {
    if (!tb_send_cmd(TB_CMD_DRBG_QUEUE_BEAT, tstrb_4b & 0xFu, timeout_cycles)) {
        return 0;
    }
    return TB_CMD_RESULT != 0;
}

/**
 * Ask the testbench to sample the recoverable error signal and return its value.
 * Firmware should set or clear KMCSR RECOVERABLE_ERR before calling this.
 *
 * @param timeout_cycles Maximum cycles to wait for acknowledgment
 * @return 1 if recoverable_err was high, 0 if low or on error/timeout
 */
static inline int tb_check_recoverable_err(uint32_t timeout_cycles) {
    if (!tb_send_cmd(TB_CMD_CHECK_RECOVERABLE_ERR, 0, timeout_cycles)) {
        return 0;
    }
    return (TB_CMD_RESULT != 0) ? 1 : 0;
}

/**
 * Ask the testbench whether the CPU was restarted due to an unrecoverable fault.
 * Used by unrecoverable-fault tests that intentionally trigger a trap and rely
 * on testbench reset before checking post-reset behavior.
 *
 * @param timeout_cycles Maximum cycles to wait for acknowledgment
 * @return 1 if restarted due to unrecoverable fault, 0 otherwise or on error/timeout
 */
static inline int tb_check_unrecoverable_restart(uint32_t timeout_cycles) {
    if (!tb_send_cmd(TB_CMD_CHECK_UNRECOVERABLE_RESTART, 0, timeout_cycles)) {
        return 0;
    }
    return (TB_CMD_RESULT != 0) ? 1 : 0;
}

/**
 * Arm or disarm the testbench unrecoverable watcher. When armed, the testbench
 * captures the unrecoverable fault frame, resets the DUT, and records restart
 * state for tb_check_unrecoverable_restart().
 *
 * @param enable 1 to arm, 0 to disarm
 * @param timeout_cycles Maximum cycles to wait for acknowledgment
 * @return 1 if successful, 0 on error/timeout
 */
static inline int tb_set_unrecoverable_watch(int enable, uint32_t timeout_cycles) {
    if (!tb_send_cmd(TB_CMD_UNRECOVERABLE_WATCH_CTRL, enable ? 1u : 0u, timeout_cycles)) {
        return 0;
    }
    return (TB_CMD_RESULT != 0) ? 1 : 0;
}

/**
 * Get the unrecoverable fault code that the testbench captured from the SEP
 * outbound mailbox before resetting the DUT.  Must be called after
 * tb_check_unrecoverable_restart() returns 1.
 *
 * @param timeout_cycles Maximum cycles to wait for acknowledgment
 * @param fault_code_out Pointer to store the 32-bit fault code (sign-extended)
 * @return 1 if successful, 0 on error/timeout
 */
static inline int tb_get_unrecoverable_fault_code(uint32_t timeout_cycles,
                                                  uint32_t *fault_code_out) {
    if (!tb_send_cmd(TB_CMD_GET_UNRECOVERABLE_FAULT_CODE, 0, timeout_cycles)) {
        return 0;
    }
    *fault_code_out = TB_CMD_RESULT;
    return 1;
}

/**
 * Read a key share word from the crypto engine key register block via the
 * testbench (bypasses the write-only register restriction by reading hwif_out).
 *
 * @param engine Engine index (0=HMAC, 1=KMAC, 2=AES, 3=OTBN, 4=ABR_MLDSA_SEED,
 *               5=ABR_MLKEM_SEED_D, 6=ABR_MLKEM_SEED_Z, 7=ABR_MLKEM_MSG)
 * @param share  Share number (0=SHARE0, 1=SHARE1)
 * @param word   Word index within the share
 * @param value_out Pointer to store the 32-bit value
 * @return 1 if successful, 0 on error/timeout
 */
static inline int tb_key_share_read(uint8_t engine, uint8_t share, uint8_t word,
                                    uint32_t *value_out) {
    uint32_t arg =
        ((uint32_t)(engine & 0xF) << 8) | ((uint32_t)(share & 0x1) << 4) | ((uint32_t)(word & 0xF));
    if (!tb_send_cmd(TB_CMD_KEY_SHARE_READ, arg, 1000)) {
        return 0;
    }
    *value_out = TB_CMD_RESULT;
    return 1;
}

/**
 * Ask the testbench to inject a spurious IRQ into the PicoRV32 IRQ vector.
 * The injected bits are OR'd with the real IRQ sources and held until the
 * testbench clears them (typically on unrecoverable-error reset).
 *
 * @param irq_bits Bitmask of IRQ bits to inject (use bits outside 1-4)
 * @param timeout_cycles Maximum cycles to wait for acknowledgment
 * @return 1 if successful, 0 on error/timeout
 */
static inline int tb_inject_spurious_irq(uint32_t irq_bits, uint32_t timeout_cycles) {
    if (!tb_send_cmd(TB_CMD_INJECT_SPURIOUS_IRQ, irq_bits, timeout_cycles)) {
        return 0;
    }
    return (TB_CMD_RESULT != 0) ? 1 : 0;
}

/**
 * @brief Ask the testbench to pulse warm_rst_n (synchronous warm reset).
 *
 * The testbench holds warm_rst_n low for 22 cycles, which is enough for
 * the km_reset_conditioner's MIN_RESET_CYCLES counter to latch the event
 * and propagate rst_warm_sync_no.  After this call returns the KM CPU and
 * all warm-resettable state are in the reset state; ROM firmware will restart
 * from the reset vector.
 *
 * Because warm reset causes the KM CPU to restart, this function should be
 * the very last action before the firmware test halts.  The cocotb test must
 * then wait for firmware to complete a second boot and check the post-reset
 * state from the outside (via register probing).
 *
 * @param timeout_cycles Maximum cycles to wait for TB acknowledgment.
 * @return 1 if acknowledged, 0 on timeout/error.
 */
static inline int tb_km_warm_reset(uint32_t timeout_cycles) {
    if (!tb_send_cmd(TB_CMD_KM_WARM_RESET, 0, timeout_cycles)) {
        return 0;
    }
    return (TB_CMD_RESULT != 0) ? 1 : 0;
}

/**
 * @brief Read BOOT_STATUS.COLD_BOOT_DONE from the KMCSR.
 *
 * This is a thin firmware-side wrapper for verification in warm-reset tests.
 * It delegates directly to the ROM KMCSR driver function.
 *
 * @return 1 if COLD_BOOT_DONE is set (ROM has completed cold boot), 0 otherwise.
 */
static inline uint8_t tb_cold_boot_done_read(void) {
    return rom_kmcsr_cold_boot_done_read();
}

/* Simple memcpy implementation for bare-metal firmware */
/* Note: Must be a non-inline function because the compiler generates calls
 * to memcpy() for array initialization before seeing any inline definition.
 * The linker needs an actual function symbol to resolve these calls. */
void *memcpy(void *dest, const void *src, size_t n);

/**
 * Ask the testbench to load one word of the ABR ML-KEM shared key into
 * tb_abr_sk_load_data[word_idx].  The value used is the last one set via
 * tb_drbg_set_next_value().  Call for each word 0-7 in sequence, then call
 * tb_abr_sk_assert_valid() to pulse hwset and transfer the full key into the
 * abr_wrapper_key reg block.
 *
 * @param word_idx  Word index (0-7)
 * @param timeout_cycles Maximum cycles to wait for acknowledgment
 * @return 1 if successful, 0 on error/timeout
 */
static inline int tb_abr_sk_load_word(uint8_t word_idx, uint32_t timeout_cycles) {
    if (!tb_send_cmd(TB_CMD_ABR_SK_LOAD, (uint32_t)(word_idx & 0x7), timeout_cycles)) {
        return 0;
    }
    return (TB_CMD_RESULT != 0) ? 1 : 0;
}

/**
 * Ask the testbench to pulse tb_abr_sk_load_valid, which drives hwset=1 on
 * KEY_CTRL.KEY_VALID and we=1 on all KEY[*].data for one clock cycle.  Must
 * be called after all 8 words have been loaded via tb_abr_sk_load_word().
 *
 * @param timeout_cycles Maximum cycles to wait for acknowledgment
 * @return 1 if successful, 0 on error/timeout
 */
static inline int tb_abr_sk_assert_valid(uint32_t timeout_cycles) {
    if (!tb_send_cmd(TB_CMD_ABR_SK_LOAD, 0xFF, timeout_cycles)) {
        return 0;
    }
    return (TB_CMD_RESULT != 0) ? 1 : 0;
}

/**
 * Read the current level of abr_mlkem_sharedkey_irq from the testbench.
 *
 * @param timeout_cycles Maximum cycles to wait for acknowledgment
 * @return 1 if IRQ asserted, 0 if deasserted (or on error/timeout)
 */
static inline int tb_abr_sk_irq_status_read(uint32_t timeout_cycles) {
    if (!tb_send_cmd(TB_CMD_ABR_SK_IRQ_STATUS_READ, 0, timeout_cycles)) {
        return 0;
    }
    return (int)TB_CMD_RESULT;
}

#endif /* TEST_COMMON_H */
