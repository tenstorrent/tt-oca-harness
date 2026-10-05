/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/**
 * @file i2c_opentitan.h
 * @brief OpenTitan I2C Driver Function Library
 *
 * Complete I2C driver library for OpenTitan I2C IP
 * Supports Controller Mode, Target Mode, and Hybrid Mode
 *
 * @note Based on OpenTitan I2C IP specification
 */

#ifndef I2C_OPENTITAN_H
#define I2C_OPENTITAN_H

#include <stdint.h>
#include <stdbool.h>
#include <stddef.h>

#ifdef __cplusplus
extern "C" {
#endif

// ============================================================================
// Constants and Macros
// ============================================================================

// I2C Instance IDs
#define I2C_INSTANCE_0 0
#define I2C_INSTANCE_1 1

// I2C Speed Modes
#define I2C_SPEED_STANDARD 0  // 100 kHz
#define I2C_SPEED_FAST 1      // 400 kHz
#define I2C_SPEED_FAST_PLUS 2 // 1 MHz

// I2C Status Codes
#define I2C_OK 0
#define I2C_ERROR -1
#define I2C_ERROR_TIMEOUT -2
#define I2C_ERROR_NACK -3
#define I2C_ERROR_OVERFLOW -4
#define I2C_ERROR_BUSY -5
#define I2C_ERROR_INVALID -6
#define I2C_ERROR_FIFO_FULL -7

// ACQDATA Signal Types (Target Mode)
#define I2C_ACQ_SIGNAL_DATA 0       // Normal data byte (ACKed)
#define I2C_ACQ_SIGNAL_START 1      // START + address byte
#define I2C_ACQ_SIGNAL_STOP 2       // STOP condition
#define I2C_ACQ_SIGNAL_RESTART 3    // Repeated START + address
#define I2C_ACQ_SIGNAL_NACK 4       // NACKed data byte
#define I2C_ACQ_SIGNAL_NACK_START 5 // NACK Start (address ACKed, data NACKed)
#define I2C_ACQ_SIGNAL_NACK_STOP 6  // NACK Stop (transaction error)

// Default FIFO Thresholds
#define I2C_DEFAULT_RX_THRESH 29
#define I2C_DEFAULT_FMT_THRESH 5
#define I2C_DEFAULT_TX_THRESH 5
#define I2C_DEFAULT_ACQ_THRESH 29

// Timeout values (in system clock cycles)
/* Default poll bound for driver waits, in loop iterations.
 *
 * Finite by design: a bound that cannot expire inside a simulation lets every
 * driver wait -- controller read, controller write completion, wait_idle --
 * end only when the harness kills the run, which makes the NACK /
 * arbitration-lost / bus-timeout diagnostics behind those waits, and the
 * callers' failure branches, unreachable.
 *
 * Derived, not guessed: a poll iteration costs ~1.15 us of simulation (measured
 * over the instruction trace), and the longest legitimate single I2C operation
 * observed in this testbench is the 62-byte standard-mode fill in
 * i2c_acq_fifo_stretch_reset at 5.58 ms. 20000 iterations is ~23 ms, roughly
 * 4x that worst case, and finite.
 */
/* SMC I2C FIFO depths, transcribed from the specification: the OpenTitan I2C
 * parameter list that hw/ip/i2c/doc/index.adoc adopts (FifoDepth 64 for the
 * FMT, RX and TX FIFOs, AcqFifoDepth 268) and the SMC integration override
 * table (hw/sys/smc/doc/periphs.adoc, I2cTargetRxFifoDepth 268 -> 64). No
 * generated C export carries them, so keep this table in step with those two
 * documents; the IP default of 268 must not be assumed at the SMC level. */
#define I2C_CONTROLLER_TX_FIFO_DEPTH 64u
#define I2C_CONTROLLER_RX_FIFO_DEPTH 64u
#define I2C_TARGET_TX_FIFO_DEPTH 64u
#define I2C_TARGET_RX_FIFO_DEPTH 64u

/* Sized against the worst legitimate wait, which is not a plain transfer.
 * Several tests here deliberately provoke clock stretching, where the target
 * holds SCL for as long as software leaves its ACQ FIFO full, so the bound must
 * clear a stretched transaction rather than just a 62-byte standard-mode fill
 * (5.58 ms in i2c_acq_fifo_stretch_reset). A first attempt at 20000 iterations
 * (~23 ms) measured too tight: it failed i2c_p0_stretch, i2c_rw, i2c_p1_dma and
 * i2c_acq_fifo_stretch_reset, each mid-fill.
 *
 * 200000 is ~90-230 ms of simulation at the 0.44-1.15 us/iteration measured
 * across these tests -- ~20x the longest legitimate operation seen, and ~200x
 * smaller than the 0xFFFFFFFF it replaces (~38.6 s, which no run reaches).
 * Finite and reachable is the property that matters; the multiple is margin. */
#define I2C_TIMEOUT_DEFAULT 200000u
#define I2C_TIMEOUT_INFINITE 0xFFFFFFFF

// Minimum cycles for clock stretching detection
#define I2C_MIN_SCL_CYCLES 4

// SMBus Special Addresses
#define SMBUS_ADDR_ARA 0x0C            // Alert Response Address
#define SMBUS_ADDR_DEVICE_DEFAULT 0x61 // SMBus Device Default Address
#define SMBUS_ADDR_HOST 0x08           // SMBus Host Address

// SMBus/PMBus Commands
#define SMBUS_CMD_QUICK 0x00            // Quick Command
#define PMBUS_CMD_PAGE 0x00             // PMBus PAGE command
#define PMBUS_CMD_OPERATION 0x01        // PMBus OPERATION command
#define PMBUS_CMD_ON_OFF_CONFIG 0x02    // PMBus ON_OFF_CONFIG
#define PMBUS_CMD_CLEAR_FAULTS 0x03     // PMBus CLEAR_FAULTS
#define PMBUS_CMD_WRITE_PROTECT 0x10    // PMBus WRITE_PROTECT
#define PMBUS_CMD_VOUT_MODE 0x20        // PMBus VOUT_MODE
#define PMBUS_CMD_VOUT_COMMAND 0x21     // PMBus VOUT_COMMAND
#define PMBUS_CMD_VOUT_MAX 0x24         // PMBus VOUT_MAX
#define PMBUS_CMD_STATUS_BYTE 0x78      // PMBus STATUS_BYTE
#define PMBUS_CMD_STATUS_WORD 0x79      // PMBus STATUS_WORD
#define PMBUS_CMD_READ_VOUT 0x8B        // PMBus READ_VOUT
#define PMBUS_CMD_READ_IOUT 0x8C        // PMBus READ_IOUT
#define PMBUS_CMD_READ_TEMPERATURE 0x8D // PMBus READ_TEMPERATURE
#define PMBUS_CMD_READ_VIN 0x88         // PMBus READ_VIN
#define PMBUS_CMD_MFR_ID 0x99           // PMBus Manufacturer ID
#define PMBUS_CMD_MFR_MODEL 0x9A        // PMBus Manufacturer Model
#define PMBUS_CMD_MFR_REVISION 0x9B     // PMBus Manufacturer Revision
#define PMBUS_CMD_MFR_SERIAL 0x9E       // PMBus Manufacturer Serial

// SMBus Protocol Types
#define SMBUS_PROTOCOL_QUICK 0      // Quick Command
#define SMBUS_PROTOCOL_BYTE 1       // Send/Receive Byte
#define SMBUS_PROTOCOL_BYTE_DATA 2  // Read/Write Byte
#define SMBUS_PROTOCOL_WORD_DATA 3  // Read/Write Word
#define SMBUS_PROTOCOL_PROC_CALL 4  // Process Call
#define SMBUS_PROTOCOL_BLOCK 5      // Block Read/Write
#define SMBUS_PROTOCOL_BLOCK_PROC 6 // Block Process Call

// PMBus Protocol Types
#define PMBUS_PROTOCOL_SEND_BYTE 1   // Send Byte (write command only)
#define PMBUS_PROTOCOL_WRITE_BYTE 2  // Write Byte (command + 1 byte)
#define PMBUS_PROTOCOL_WRITE_WORD 3  // Write Word (command + 2 bytes)
#define PMBUS_PROTOCOL_READ_BYTE 4   // Read Byte (command, then read 1)
#define PMBUS_PROTOCOL_READ_WORD 5   // Read Word (command, then read 2)
#define PMBUS_PROTOCOL_BLOCK_WRITE 6 // Block Write (cmd + count + data)
#define PMBUS_PROTOCOL_BLOCK_READ 7  // Block Read (cmd, then read count+data)
#define PMBUS_PROTOCOL_BLOCK_WR_RD 8 // Block Write-Read Process Call

// PEC (Packet Error Code) - CRC-8
#define SMBUS_PEC_POLYNOMIAL 0x07 // x^8 + x^2 + x + 1

// ============================================================================
// Data Structures
// ============================================================================

/**
 * @brief I2C Physical Timing Parameters
 *
 * High-level timing configuration based on physical characteristics.
 * Use this to compute timing parameters automatically based on I2C specification.
 */
typedef struct {
    uint8_t speed;               // I2C_SPEED_STANDARD, FAST, or FAST_PLUS
    uint32_t clock_period_nanos; // System clock period in nanoseconds
    uint32_t sda_rise_nanos;     // SDA rise time in nanoseconds (typical: 300ns)
    uint32_t sda_fall_nanos;     // SDA fall time in nanoseconds (typical: 100ns)
    uint32_t scl_period_nanos;   // Desired SCL period (0 = use minimum for speed)
} i2c_timing_physical_t;

/**
 * @brief I2C Timing Configuration
 *
 * Low-level timing configuration in clock cycles.
 * Can be computed from physical parameters using i2c_compute_timing_from_physical().
 */
typedef struct {
    uint16_t thigh;   // SCL high period (cycles)
    uint16_t tlow;    // SCL low period (cycles)
    uint16_t t_r;     // Rise time (cycles)
    uint16_t t_f;     // Fall time (cycles)
    uint16_t tsu_sta; // START setup time (cycles)
    uint16_t thd_sta; // START hold time (cycles)
    uint16_t tsu_dat; // Data setup time (cycles)
    uint16_t thd_dat; // Data hold time (cycles)
    uint16_t tsu_sto; // STOP setup time (cycles)
    uint16_t t_buf;   // Bus free time (cycles)
} i2c_timing_config_t;

/**
 * @brief I2C FIFO Configuration
 */
typedef struct {
    uint16_t rx_thresh;  // RX FIFO threshold
    uint16_t fmt_thresh; // FMT FIFO threshold
    uint16_t tx_thresh;  // TX FIFO threshold
    uint16_t acq_thresh; // ACQ FIFO threshold
} i2c_fifo_config_t;

/**
 * @brief I2C Controller Configuration
 */
typedef struct {
    i2c_timing_config_t timing;
    i2c_fifo_config_t fifo;
    bool enable_interrupts;
    uint32_t timeout_cycles;
} i2c_controller_config_t;

/**
 * @brief I2C Target Configuration
 */
typedef struct {
    uint8_t address0; // Primary 7-bit address
    uint8_t mask0;    // Address mask (0x7F for exact match)
    uint8_t address1; // Secondary address (optional)
    uint8_t mask1;    // Secondary address mask
    i2c_timing_config_t timing;
    i2c_fifo_config_t fifo;
    bool enable_interrupts;
    bool ack_ctrl_mode;   // Software ACK control
    bool tx_stretch_ctrl; // TX stretch control
    uint32_t timeout_cycles;
} i2c_target_config_t;

/**
 * @brief I2C Transaction Data (for Target Mode receive)
 */
typedef struct {
    uint8_t signal; // Signal type
    uint8_t data;   // Data byte
    bool is_write;  // true = write, false = read
    bool is_start;  // START condition
    bool is_stop;   // STOP condition
    /* NACKed entry: signal is NACK, NACK_START or NACK_STOP.
     *
     * is_start/is_stop alone do not describe an ACQ entry. The classifier maps
     * NACK (4) and NACK_START (5) onto its default leg, which leaves BOTH of
     * them false -- so the common filter `if (e.is_start || e.is_stop) continue;`
     * accepts a byte the target NACKed as ordinary payload and feeds it into a
     * comparison buffer. Found while fixing i2c_p1_dma, where exactly that
     * happened. Check this flag, or switch on `signal`, before treating an entry
     * as data. NACK_STOP additionally sets is_stop, as it always did. */
    bool is_nack;
} i2c_acq_entry_t;

/**
 * @brief SMBus/PMBus Transaction Data
 */
typedef struct {
    uint8_t device_addr; // 7-bit device address
    uint8_t command;     // Command code
    uint8_t *data;       // Data buffer
    uint16_t data_len;   // Data length
    uint8_t pec;         // Packet Error Code (CRC-8)
    bool use_pec;        // Enable PEC
    bool read_not_write; // true = read, false = write
} smbus_transaction_t;

/**
 * @brief PMBus Linear Data Format (LINEAR11)
 */
typedef struct {
    int16_t mantissa; // 11-bit mantissa (signed)
    int8_t exponent;  // 5-bit exponent (signed)
} pmbus_linear11_t;

/**
 * @brief PMBus Linear Data Format (LINEAR16)
 */
typedef struct {
    uint16_t mantissa; // 16-bit mantissa
    int8_t exponent;   // Exponent (from VOUT_MODE)
} pmbus_linear16_t;

// ============================================================================
// Basic Functions
// ============================================================================

/**
 * @brief Get I2C instance base address
 * @param idx I2C instance index (0, 1, ...)
 * @return Base address of the I2C instance
 */
uint32_t i2c_get_base(uint32_t idx);

/**
 * @brief Get default timing configuration for specified speed
 * @param speed I2C_SPEED_STANDARD, I2C_SPEED_FAST, or I2C_SPEED_FAST_PLUS
 * @param sys_clk_mhz System clock frequency in MHz
 * @param config Pointer to timing configuration structure (output)
 */
void i2c_get_default_timing(uint8_t speed, uint32_t sys_clk_mhz, i2c_timing_config_t *config);

/**
 * @brief Compute timing configuration from physical parameters
 *
 * This function computes optimal I2C timing parameters based on physical
 * characteristics of the system (clock frequency, rise/fall times, etc.)
 * according to I2C specification Table 10.
 *
 * Inspired by OpenTitan's dif_i2c_compute_timing() implementation.
 *
 * @param physical Pointer to physical timing parameters
 * @param config Pointer to timing configuration structure (output)
 * @return I2C_OK on success, negative error code otherwise
 *
 * Example usage:
 * @code
 *   i2c_timing_physical_t physical = {
 *       .speed = I2C_SPEED_STANDARD,
 *       .clock_period_nanos = 5, // 200 MHz peripheral clock
 *       .sda_rise_nanos = 300,         // Typical for 4.7k pullup
 *       .sda_fall_nanos = 100,         // Typical
 *       .scl_period_nanos = 0          // Auto (10us for standard mode)
 *   };
 *   i2c_timing_config_t timing;
 *   i2c_compute_timing_from_physical(&physical, &timing);
 * @endcode
 */
int i2c_compute_timing_from_physical(const i2c_timing_physical_t *physical,
                                     i2c_timing_config_t *config);

/**
 * @brief Configure I2C timing parameters
 * @param idx I2C instance index
 * @param config Pointer to timing configuration
 */
void i2c_config_timing(uint32_t idx, const i2c_timing_config_t *config);

/**
 * @brief Reset I2C FIFOs
 * @param idx I2C instance index
 * @param reset_rx Reset RX FIFO (Controller mode)
 * @param reset_fmt Reset FMT FIFO (Controller mode)
 * @param reset_tx Reset TX FIFO (Target mode)
 * @param reset_acq Reset ACQ FIFO (Target mode)
 */
void i2c_reset_fifos(uint32_t idx, bool reset_rx, bool reset_fmt, bool reset_tx, bool reset_acq);

/* Non-zero if the most recent i2c_reset_fifos() call had to drain the ACQ FIFO
 * by hand because the ACQRST hardware reset left entries behind. Reset at the
 * top of every call, so read it immediately after the reset under test to tell a
 * working ACQRST from one the helper papered over. */
extern uint32_t g_i2c_acq_reset_needed_drain;
/* Both drain loops are bounded. These carry the last level the loop actually
 * read, so an expired bound is reported as a failure naming the level it gave
 * up at, rather than as an unbounded spin that can only end in a simulator
 * timeout with no cause attached. */
extern uint32_t g_i2c_acq_reset_residual; /* ACQLVL left when the drain gave up */
/* Entries the drain removed: near the pre-reset level means ACQRST did nothing,
 * a small count means it worked and a live controller refilled the FIFO. */
extern uint32_t g_i2c_acq_reset_drained;
extern uint32_t g_i2c_rx_reset_needed_drain;  /* RXRST needed a software drain */
extern uint32_t g_i2c_rx_reset_residual;      /* RXLVL left when the drain gave up */
extern uint32_t g_i2c_fmt_reset_needed_retry; /* FMTRST needed a second attempt */
extern uint32_t g_i2c_fmt_reset_residual;     /* FMTLVL after that second attempt */
extern uint32_t g_i2c_tx_reset_needed_retry;  /* TXRST needed a second attempt */
extern uint32_t g_i2c_tx_reset_residual;      /* TXLVL after that second attempt */

/* i2c_reset_fifos() fails the test outright when a reset does not take and it
 * has to repair the FIFO in software, because the "level is 0 after reset"
 * post-condition every caller depends on would otherwise be the repair's doing
 * rather than the hardware's. Set this to 1 only around a reset a test expects
 * to need repair, and only when that test inspects the flags above itself;
 * restore it to 0 immediately afterwards. */
extern uint32_t g_i2c_reset_repair_allowed;

// ============================================================================
// Controller Mode Functions
// ============================================================================

/**
 * @brief Initialize I2C in Controller mode
 * @param idx I2C instance index
 * @param config Pointer to controller configuration (NULL for defaults)
 * @return I2C_OK on success, negative error code otherwise
 */
int i2c_controller_init(uint32_t idx, const i2c_controller_config_t *config);

/**
 * @brief Disable I2C Controller mode
 * @param idx I2C instance index
 */
void i2c_controller_disable(uint32_t idx);

/**
 * @brief Enable I2C Controller mode
 * @param idx I2C instance index
 */
void i2c_controller_enable(uint32_t idx);

/**
 * @brief Check if Controller is idle
 * @param idx I2C instance index
 * @return true if idle, false otherwise
 */
bool i2c_controller_is_idle(uint32_t idx);

/**
 * @brief Wait for Controller to become idle
 * @param idx I2C instance index
 * @param timeout_cycles Maximum cycles to wait (0 = infinite)
 * @return I2C_OK if idle, I2C_ERROR_TIMEOUT if timeout
 */
int i2c_controller_wait_idle(uint32_t idx, uint32_t timeout_cycles);

/**
 * @brief Controller write transaction
 * @param idx I2C instance index
 * @param target_addr 7-bit target address
 * @param data Pointer to data buffer
 * @param len Number of bytes to write
 * @param send_stop true to send STOP, false for repeated START
 * @return I2C_OK on success, negative error code otherwise
 */
int i2c_controller_write(uint32_t idx, uint8_t target_addr, const uint8_t *data, uint32_t len,
                         bool send_stop);

/**
 * @brief Controller read transaction
 * @param idx I2C instance index
 * @param target_addr 7-bit target address
 * @param data Pointer to receive buffer
 * @param len Number of bytes to read
 * @param send_stop true to send STOP, false for repeated START
 * @return I2C_OK on success, negative error code otherwise
 */
int i2c_controller_read(uint32_t idx, uint8_t target_addr, uint8_t *data, uint32_t len,
                        bool send_stop);

/**
 * @brief Controller write-then-read transaction (combined format)
 * @param idx I2C instance index
 * @param target_addr 7-bit target address
 * @param write_data Pointer to write data buffer
 * @param write_len Number of bytes to write
 * @param read_data Pointer to read data buffer
 * @param read_len Number of bytes to read
 * @return I2C_OK on success, negative error code otherwise
 */
int i2c_controller_write_read(uint32_t idx, uint8_t target_addr, const uint8_t *write_data,
                              uint32_t write_len, uint8_t *read_data, uint32_t read_len);

/**
 * @brief Controller write with length header (protocol used in i2c_sanity test)
 * @param idx I2C instance index
 * @param target_addr 7-bit target address
 * @param data Pointer to data buffer
 * @param len Number of bytes to write
 * @return I2C_OK on success, negative error code otherwise
 */
int i2c_controller_write_with_header(uint32_t idx, uint8_t target_addr, const uint8_t *data,
                                     uint32_t len);

/**
 * @brief Non-blocking controller write with length header
 *
 * This function writes all data to FDATA FIFO and returns immediately.
 * It does NOT wait for the I2C bus transaction to complete.
 * The hardware FSM will execute the transaction in the background.
 *
 * @param idx I2C instance index
 * @param target_addr 7-bit target address
 * @param data Pointer to data buffer
 * @param len Number of bytes to send
 * @return I2C_OK on success, negative error code otherwise
 */
int i2c_controller_write_with_header_nonblock(uint32_t idx, uint8_t target_addr,
                                              const uint8_t *data, uint32_t len);

/**
 * @brief Get Controller FIFO status
 * @param idx I2C instance index
 * @param fmt_level Output: FMT FIFO level (can be NULL)
 * @param rx_level Output: RX FIFO level (can be NULL)
 */
void i2c_controller_get_fifo_status(uint32_t idx, uint32_t *fmt_level, uint32_t *rx_level);

/**
 * @brief Wait for FMT FIFO to have available space
 *
 * This function helps prevent FIFO overflow by waiting for space to become
 * available before writing to the FMT FIFO.
 *
 * @param idx I2C instance index
 * @param required_space Number of entries needed in FIFO
 * @param timeout_cycles Maximum cycles to wait (0 = infinite)
 * @return I2C_OK if space available, I2C_ERROR_TIMEOUT if timeout
 */
int i2c_controller_wait_fmt_fifo_space(uint32_t idx, uint32_t required_space,
                                       uint32_t timeout_cycles);

/**
 * @brief Wait for RX FIFO to have data available
 *
 * @param idx I2C instance index
 * @param required_entries Number of entries needed in FIFO
 * @param timeout_cycles Maximum cycles to wait (0 = infinite)
 * @return I2C_OK if data available, I2C_ERROR_TIMEOUT if timeout
 */
int i2c_controller_wait_rx_fifo_data(uint32_t idx, uint32_t required_entries,
                                     uint32_t timeout_cycles);

/**
 * @brief Wait for ACQ FIFO to have data available (Target mode)
 *
 * @param idx I2C instance index
 * @param required_entries Number of entries needed in FIFO
 * @param timeout_cycles Maximum cycles to wait (0 = infinite)
 * @return I2C_OK if data available, I2C_ERROR_TIMEOUT if timeout
 */
int i2c_target_wait_acq_fifo_data(uint32_t idx, uint32_t required_entries, uint32_t timeout_cycles);

/**
 * @brief Controller write transaction with automatic ACQ FIFO cleanup
 *
 * This function performs a controller write operation and then automatically
 * clears the target's ACQ FIFO and TARGET_EVENTS. This is useful for preventing
 * stretch_tx issues in repeated START scenarios.
 *
 * @param controller_idx Controller I2C instance index
 * @param target_idx Target I2C instance index (for ACQ FIFO cleanup)
 * @param target_addr 7-bit target address
 * @param data Pointer to data buffer
 * @param len Number of bytes to write
 * @param send_stop true to send STOP, false for repeated START
 * @return I2C_OK on success, negative error code otherwise
 */
int i2c_write_with_clear(uint32_t controller_idx, uint32_t target_idx, uint8_t target_addr,
                         const uint8_t *data, uint32_t len, bool send_stop);

/**
 * @brief Controller read transaction with automatic ACQ FIFO cleanup
 *
 * This function performs a controller read operation and then automatically
 * drains the target's ACQ FIFO. This is useful for preventing stretch_tx
 * issues in repeated START scenarios.
 *
 * @param controller_idx Controller I2C instance index
 * @param target_idx Target I2C instance index (for ACQ FIFO cleanup)
 * @param target_addr 7-bit target address
 * @param data Pointer to receive buffer
 * @param len Number of bytes to read
 * @param send_stop true to send STOP, false for repeated START
 * @return I2C_OK on success, negative error code otherwise
 */
int i2c_read_with_clear(uint32_t controller_idx, uint32_t target_idx, uint8_t target_addr,
                        uint8_t *data, uint32_t len, bool send_stop);

// ============================================================================
// Target Mode Functions
// ============================================================================

/**
 * @brief Initialize I2C in Target mode
 * @param idx I2C instance index
 * @param config Pointer to target configuration (NULL for defaults with addr 0x10)
 * @return I2C_OK on success, negative error code otherwise
 */
int i2c_target_init(uint32_t idx, const i2c_target_config_t *config);

/**
 * @brief Disable I2C Target mode
 * @param idx I2C instance index
 */
void i2c_target_disable(uint32_t idx);

/**
 * @brief Check if Target is idle
 * @param idx I2C instance index
 * @return true if idle, false otherwise
 */
bool i2c_target_is_idle(uint32_t idx);

/**
 * @brief Set Target address
 * @param idx I2C instance index
 * @param address0 Primary 7-bit address
 * @param mask0 Address mask (0x7F for exact match)
 */
void i2c_target_set_address(uint32_t idx, uint8_t address0, uint8_t mask0);

/**
 * @brief Set Target secondary address
 * @param idx I2C instance index
 * @param address1 Secondary 7-bit address
 * @param mask1 Address mask (0x7F for exact match, 0x00 to disable)
 */
void i2c_target_set_address_secondary(uint32_t idx, uint8_t address1, uint8_t mask1);

/**
 * @brief Target transmit data (for Controller read requests)
 * @param idx I2C instance index
 * @param data Pointer to data buffer
 * @param len Number of bytes to transmit
 * @return Number of bytes written to TX FIFO
 */
uint32_t i2c_target_transmit(uint32_t idx, const uint8_t *data, uint32_t len);

/**
 * @brief Target receive single entry from ACQ FIFO
 * @param idx I2C instance index
 * @param entry Pointer to ACQ entry structure (output)
 * @return I2C_OK if data available, I2C_ERROR otherwise
 */
int i2c_target_receive_entry(uint32_t idx, i2c_acq_entry_t *entry);

/**
 * @brief Target receive complete transaction (with length header)
 * @param idx I2C instance index
 * @param buffer Pointer to receive buffer
 * @param buffer_size Size of receive buffer
 * @param received_len Output: number of bytes actually received
 * @param timeout_cycles Maximum cycles to wait (0 = infinite)
 * @return I2C_OK on success, negative error code otherwise
 */
int i2c_target_receive_transaction(uint32_t idx, uint8_t *buffer, uint32_t buffer_size,
                                   uint32_t *received_len, uint32_t timeout_cycles);

/**
 * @brief Receive one Target transaction, stating the wire framing explicitly.
 *
 * i2c_target_receive_transaction() above is this function with
 * expect_length_header = true, which is correct only for controllers that send
 * a leading length byte. A caller that writes raw payload must pass false, or
 * its first payload byte is consumed as a count and the transfer is reported
 * complete after one byte.
 *
 * @param expect_length_header true  = first data byte is a length header and the
 *                                     receive ends once that many bytes arrive;
 *                             false = no header; drain until STOP and report the
 *                                     full byte count.
 * @return I2C_OK on success, negative error code otherwise
 */
int i2c_target_receive_transaction_framed(uint32_t idx, uint8_t *buffer, uint32_t buffer_size,
                                          uint32_t *received_len, uint32_t timeout_cycles,
                                          bool expect_length_header);

/**
 * @brief Get Target FIFO status
 * @param idx I2C instance index
 * @param tx_level Output: TX FIFO level (can be NULL)
 * @param acq_level Output: ACQ FIFO level (can be NULL)
 */
void i2c_target_get_fifo_status(uint32_t idx, uint32_t *tx_level, uint32_t *acq_level);

/**
 * @brief Check if ACQ FIFO is empty
 * @param idx I2C instance index
 * @return true if empty, false otherwise
 */
bool i2c_target_acq_fifo_empty(uint32_t idx);

/**
 * @brief Check if TX FIFO is full
 * @param idx I2C instance index
 * @return true if full, false otherwise
 */
bool i2c_target_tx_fifo_full(uint32_t idx);

// ============================================================================
// Status and Interrupt Functions
// ============================================================================

/**
 * @brief Get I2C status register
 * @param idx I2C instance index
 * @return STATUS register value
 */
uint32_t i2c_get_status(uint32_t idx);

/**
 * @brief Get interrupt state
 * @param idx I2C instance index
 * @return INTR_STATE register value
 */
uint32_t i2c_get_interrupt_state(uint32_t idx);

/**
 * @brief Clear interrupt(s)
 * @param idx I2C instance index
 * @param intr_mask Bit mask of interrupts to clear
 */
void i2c_clear_interrupts(uint32_t idx, uint32_t intr_mask);

/**
 * @brief Enable interrupt(s)
 * @param idx I2C instance index
 * @param intr_mask Bit mask of interrupts to enable
 */
void i2c_enable_interrupts(uint32_t idx, uint32_t intr_mask);

/**
 * @brief Disable interrupt(s)
 * @param idx I2C instance index
 * @param intr_mask Bit mask of interrupts to disable
 */
void i2c_disable_interrupts(uint32_t idx, uint32_t intr_mask);

/**
 * @brief Get Controller events register
 * @param idx I2C instance index
 * @return CONTROLLER_EVENTS register value
 */
uint32_t i2c_get_controller_events(uint32_t idx);

/**
 * @brief Clear Controller events
 * @param idx I2C instance index
 * @param event_mask Bit mask of events to clear
 */
void i2c_clear_controller_events(uint32_t idx, uint32_t event_mask);

/**
 * @brief Get Target events register
 * @param idx I2C instance index
 * @return TARGET_EVENTS register value
 */
uint32_t i2c_get_target_events(uint32_t idx);

/**
 * @brief Clear Target events
 * @param idx I2C instance index
 * @param event_mask Bit mask of events to clear
 */
void i2c_clear_target_events(uint32_t idx, uint32_t event_mask);

// ============================================================================
// Advanced Configuration Functions
// ============================================================================

/**
 * @brief Configure timeout control
 * @param idx I2C instance index
 * @param timeout_val Timeout value in system clock cycles
 * @param stretch_mode true for stretch timeout, false for bus timeout
 * @param enable Enable timeout
 */
void i2c_config_timeout(uint32_t idx, uint32_t timeout_val, bool stretch_mode, bool enable);

/**
 * @brief Configure Controller NACK handler timeout
 * @param idx I2C instance index
 * @param timeout_val Timeout value in system clock cycles
 * @param enable Enable timeout
 */
void i2c_config_nack_timeout(uint32_t idx, uint32_t timeout_val, bool enable);

/**
 * @brief Enable/disable Line Loopback mode
 * @param idx I2C instance index
 * @param enable Enable loopback
 */
void i2c_set_loopback(uint32_t idx, bool enable);

/**
 * @brief Configure ACK control mode (Target mode)
 * @param idx I2C instance index
 * @param enable true for software ACK control, false for automatic
 * @param nbytes Number of bytes to ACK (for software mode)
 */
void i2c_target_config_ack_ctrl(uint32_t idx, bool enable, uint16_t nbytes);

/**
 * @brief Send NACK (Target ACK control mode)
 * @param idx I2C instance index
 */
void i2c_target_send_nack(uint32_t idx);

// ============================================================================
// SMBus Functions
// ============================================================================

/**
 * @brief Control SMBus Suspend signal (Controller mode)
 * @param idx I2C instance index
 * @param assert true to drive SMBSUS# low, false to release
 */
void i2c_smbus_suspend(uint32_t idx, bool assert);

/**
 * @brief Control SMBus Alert signal (Target mode)
 * @param idx I2C instance index
 * @param assert true to drive SMBALERT# low, false to release
 */
void i2c_smbus_alert(uint32_t idx, bool assert);

/**
 * @brief Get SMBus status
 * @param idx I2C instance index
 * @return SMBUS_STATUS register value
 */
uint32_t i2c_get_smbus_status(uint32_t idx);

/**
 * @brief Calculate SMBus PEC (Packet Error Code) - CRC-8
 * @param data Pointer to data buffer
 * @param len Length of data
 * @param init_crc Initial CRC value (usually 0)
 * @return Calculated CRC-8 value
 */
uint8_t smbus_calculate_pec(const uint8_t *data, uint16_t len, uint8_t init_crc);

/**
 * @brief SMBus Quick Command
 * @param idx I2C instance index
 * @param device_addr 7-bit device address
 * @param write_bit true = write (0), false = read (1)
 * @return I2C_OK on success, negative error code otherwise
 */
int smbus_quick_command(uint32_t idx, uint8_t device_addr, bool write_bit);

/**
 * @brief SMBus Send Byte
 * @param idx I2C instance index
 * @param device_addr 7-bit device address
 * @param data Byte to send
 * @param use_pec Enable PEC
 * @return I2C_OK on success, negative error code otherwise
 */
int smbus_send_byte(uint32_t idx, uint8_t device_addr, uint8_t data, bool use_pec);

/**
 * @brief SMBus Receive Byte
 * @param idx I2C instance index
 * @param device_addr 7-bit device address
 * @param data Pointer to receive buffer
 * @param use_pec Enable PEC
 * @return I2C_OK on success, negative error code otherwise
 */
int smbus_receive_byte(uint32_t idx, uint8_t device_addr, uint8_t *data, bool use_pec);

/**
 * @brief SMBus Write Byte (command + data byte)
 * @param idx I2C instance index
 * @param device_addr 7-bit device address
 * @param command Command code
 * @param data Data byte
 * @param use_pec Enable PEC
 * @return I2C_OK on success, negative error code otherwise
 */
int smbus_write_byte(uint32_t idx, uint8_t device_addr, uint8_t command, uint8_t data,
                     bool use_pec);

/**
 * @brief SMBus Read Byte (command, then read data byte)
 * @param idx I2C instance index
 * @param device_addr 7-bit device address
 * @param command Command code
 * @param data Pointer to receive buffer
 * @param use_pec Enable PEC
 * @return I2C_OK on success, negative error code otherwise
 */
int smbus_read_byte(uint32_t idx, uint8_t device_addr, uint8_t command, uint8_t *data,
                    bool use_pec);

/**
 * @brief SMBus Write Word (command + 2 data bytes, LSB first)
 * @param idx I2C instance index
 * @param device_addr 7-bit device address
 * @param command Command code
 * @param data 16-bit data (sent LSB first)
 * @param use_pec Enable PEC
 * @return I2C_OK on success, negative error code otherwise
 */
int smbus_write_word(uint32_t idx, uint8_t device_addr, uint8_t command, uint16_t data,
                     bool use_pec);

/**
 * @brief SMBus Read Word (command, then read 2 data bytes, LSB first)
 * @param idx I2C instance index
 * @param device_addr 7-bit device address
 * @param command Command code
 * @param data Pointer to receive 16-bit data
 * @param use_pec Enable PEC
 * @return I2C_OK on success, negative error code otherwise
 */
int smbus_read_word(uint32_t idx, uint8_t device_addr, uint8_t command, uint16_t *data,
                    bool use_pec);

/**
 * @brief SMBus Block Write (command + byte count + data bytes)
 * @param idx I2C instance index
 * @param device_addr 7-bit device address
 * @param command Command code
 * @param data Pointer to data buffer
 * @param len Number of bytes (1-32 for SMBus 2.0, up to 255)
 * @param use_pec Enable PEC
 * @return I2C_OK on success, negative error code otherwise
 */
int smbus_block_write(uint32_t idx, uint8_t device_addr, uint8_t command, const uint8_t *data,
                      uint8_t len, bool use_pec);

/**
 * @brief SMBus Block Read (command, then read byte count + data bytes)
 * @param idx I2C instance index
 * @param device_addr 7-bit device address
 * @param command Command code
 * @param data Pointer to receive buffer
 * @param len Pointer to receive actual byte count
 * @param max_len Maximum buffer size
 * @param use_pec Enable PEC
 * @return I2C_OK on success, negative error code otherwise
 */
int smbus_block_read(uint32_t idx, uint8_t device_addr, uint8_t command, uint8_t *data,
                     uint8_t *len, uint8_t max_len, bool use_pec);

/**
 * @brief SMBus Process Call (command + 2 write bytes, then read 2 bytes)
 * @param idx I2C instance index
 * @param device_addr 7-bit device address
 * @param command Command code
 * @param write_data 16-bit data to write
 * @param read_data Pointer to receive 16-bit data
 * @param use_pec Enable PEC
 * @return I2C_OK on success, negative error code otherwise
 */
int smbus_process_call(uint32_t idx, uint8_t device_addr, uint8_t command, uint16_t write_data,
                       uint16_t *read_data, bool use_pec);

/**
 * @brief SMBus Block Process Call (cmd + write count + write data, then read count + read data)
 * @param idx I2C instance index
 * @param device_addr 7-bit device address
 * @param command Command code
 * @param write_data Pointer to write data buffer
 * @param write_len Write data length
 * @param read_data Pointer to read data buffer
 * @param read_len Pointer to receive read data length
 * @param max_read_len Maximum read buffer size
 * @param use_pec Enable PEC
 * @return I2C_OK on success, negative error code otherwise
 */
int smbus_block_process_call(uint32_t idx, uint8_t device_addr, uint8_t command,
                             const uint8_t *write_data, uint8_t write_len, uint8_t *read_data,
                             uint8_t *read_len, uint8_t max_read_len, bool use_pec);

/**
 * @brief SMBus Alert Response Address (ARA) - Read alert source
 * @param idx I2C instance index
 * @param alert_addr Pointer to receive alerting device address
 * @return I2C_OK on success, negative error code otherwise
 */
int smbus_alert_response(uint32_t idx, uint8_t *alert_addr);

// ============================================================================
// PMBus Functions
// ============================================================================

/**
 * @brief PMBus Send Byte (write command only, no data)
 * @param idx I2C instance index
 * @param device_addr 7-bit device address
 * @param command Command code
 * @return I2C_OK on success, negative error code otherwise
 */
int pmbus_send_byte(uint32_t idx, uint8_t device_addr, uint8_t command);

/**
 * @brief PMBus Write Byte (command + 1 data byte)
 * @param idx I2C instance index
 * @param device_addr 7-bit device address
 * @param command Command code
 * @param data Data byte
 * @return I2C_OK on success, negative error code otherwise
 */
int pmbus_write_byte(uint32_t idx, uint8_t device_addr, uint8_t command, uint8_t data);

/**
 * @brief PMBus Write Word (command + 2 data bytes, LSB first)
 * @param idx I2C instance index
 * @param device_addr 7-bit device address
 * @param command Command code
 * @param data 16-bit data
 * @return I2C_OK on success, negative error code otherwise
 */
int pmbus_write_word(uint32_t idx, uint8_t device_addr, uint8_t command, uint16_t data);

/**
 * @brief PMBus Read Byte (command, then read 1 byte)
 * @param idx I2C instance index
 * @param device_addr 7-bit device address
 * @param command Command code
 * @param data Pointer to receive buffer
 * @return I2C_OK on success, negative error code otherwise
 */
int pmbus_read_byte(uint32_t idx, uint8_t device_addr, uint8_t command, uint8_t *data);

/**
 * @brief PMBus Read Word (command, then read 2 bytes, LSB first)
 * @param idx I2C instance index
 * @param device_addr 7-bit device address
 * @param command Command code
 * @param data Pointer to receive 16-bit data
 * @return I2C_OK on success, negative error code otherwise
 */
int pmbus_read_word(uint32_t idx, uint8_t device_addr, uint8_t command, uint16_t *data);

/**
 * @brief PMBus Block Write (command + byte count + data bytes)
 * @param idx I2C instance index
 * @param device_addr 7-bit device address
 * @param command Command code
 * @param data Pointer to data buffer
 * @param len Data length
 * @return I2C_OK on success, negative error code otherwise
 */
int pmbus_block_write(uint32_t idx, uint8_t device_addr, uint8_t command, const uint8_t *data,
                      uint8_t len);

/**
 * @brief PMBus Block Read (command, then read byte count + data)
 * @param idx I2C instance index
 * @param device_addr 7-bit device address
 * @param command Command code
 * @param data Pointer to receive buffer
 * @param len Pointer to receive actual length
 * @param max_len Maximum buffer size
 * @return I2C_OK on success, negative error code otherwise
 */
int pmbus_block_read(uint32_t idx, uint8_t device_addr, uint8_t command, uint8_t *data,
                     uint8_t *len, uint8_t max_len);

/**
 * @brief PMBus Block Write-Read Process Call
 * @param idx I2C instance index
 * @param device_addr 7-bit device address
 * @param command Command code
 * @param write_data Pointer to write data
 * @param write_len Write data length
 * @param read_data Pointer to read buffer
 * @param read_len Pointer to receive read length
 * @param max_read_len Maximum read buffer size
 * @return I2C_OK on success, negative error code otherwise
 */
int pmbus_block_write_read(uint32_t idx, uint8_t device_addr, uint8_t command,
                           const uint8_t *write_data, uint8_t write_len, uint8_t *read_data,
                           uint8_t *read_len, uint8_t max_read_len);

/**
 * @brief PMBus Group Command (send to multiple devices)
 * @param idx I2C instance index
 * @param device_addrs Array of device addresses
 * @param commands Array of command codes
 * @param data_arrays Array of data pointers
 * @param data_lens Array of data lengths
 * @param num_devices Number of devices
 * @return I2C_OK on success, negative error code otherwise
 */
int pmbus_group_command(uint32_t idx, const uint8_t *device_addrs, const uint8_t *commands,
                        const uint8_t **data_arrays, const uint8_t *data_lens, uint8_t num_devices);

// ============================================================================
// PMBus Data Format Conversion Functions
// ============================================================================

/**
 * @brief Convert float to PMBus LINEAR11 format
 * @param value Floating point value
 * @return LINEAR11 formatted data
 */
pmbus_linear11_t pmbus_float_to_linear11(float value);

/**
 * @brief Convert PMBus LINEAR11 format to float
 * @param linear11 LINEAR11 formatted data
 * @return Floating point value
 */
float pmbus_linear11_to_float(pmbus_linear11_t linear11);

/**
 * @brief Convert float to PMBus LINEAR16 format
 * @param value Floating point value
 * @param exponent Exponent value (from VOUT_MODE)
 * @return LINEAR16 formatted data
 */
pmbus_linear16_t pmbus_float_to_linear16(float value, int8_t exponent);

/**
 * @brief Convert PMBus LINEAR16 format to float
 * @param linear16 LINEAR16 formatted data
 * @return Floating point value
 */
float pmbus_linear16_to_float(pmbus_linear16_t linear16);

/**
 * @brief Pack PMBus LINEAR11 to 16-bit word
 * @param linear11 LINEAR11 structure
 * @return 16-bit packed value
 */
uint16_t pmbus_pack_linear11(pmbus_linear11_t linear11);

/**
 * @brief Unpack 16-bit word to PMBus LINEAR11
 * @param packed 16-bit packed value
 * @return LINEAR11 structure
 */
pmbus_linear11_t pmbus_unpack_linear11(uint16_t packed);

// ============================================================================
// Debug and Test Functions
// ============================================================================

/**
 * @brief Override SDA/SCL signals (for debug)
 * @param idx I2C instance index
 * @param enable Enable override
 * @param scl_val SCL value (0=low, 1=high)
 * @param sda_val SDA value (0=low, 1=high)
 */
void i2c_override_signals(uint32_t idx, bool enable, bool scl_val, bool sda_val);

/**
 * @brief Get oversampled signal values
 * @param idx I2C instance index
 * @param scl_samples Output: last 16 SCL samples (can be NULL)
 * @param sda_samples Output: last 16 SDA samples (can be NULL)
 */
void i2c_get_signal_samples(uint32_t idx, uint16_t *scl_samples, uint16_t *sda_samples);

/**
 * @brief Register verification write (write and read back)
 * @param base I2C base address
 * @param offset Register offset
 * @param value Value to write
 * @return I2C_OK if verification passed, I2C_ERROR otherwise
 */
int i2c_reg_verify_write(uint32_t base, uint32_t offset, uint32_t value);

// ============================================================================
// Utility Functions
// ============================================================================

/**
 * @brief Convert error code to string
 * @param error Error code
 * @return Error description string
 */
const char *i2c_error_to_string(int error);

/**
 * @brief Dump I2C registers (for debug)
 * @param idx I2C instance index
 */
void i2c_dump_registers(uint32_t idx);

// ============================================================================
// Easy FIFO Management Functions
// ============================================================================

/**
 * @brief Reset Controller FIFOs (Easy version)
 *
 * Simple FIFO reset that resets all FIFOs at once.
 * Based on i2c_controller_driver.c implementation.
 *
 * @param idx I2C instance index
 */
void i2c_reset_fifos_easy(uint32_t idx);

/**
 * @brief Configure FIFO thresholds (Easy version)
 *
 * Simple threshold configuration for FMT and RX FIFOs.
 * Based on i2c_controller_driver.c implementation.
 *
 * @param idx I2C instance index
 * @param fmt_thresh FMT FIFO threshold
 * @param rx_thresh RX FIFO threshold
 */
void i2c_configure_threshold_easy(uint32_t idx, uint16_t fmt_thresh, uint16_t rx_thresh);

/**
 * @brief Wait for controller to become idle (Easy version)
 *
 * Simple polling loop waiting for hostidle status.
 * Based on i2c_controller_driver.c implementation.
 *
 * @param idx I2C instance index
 * @param timeout Timeout value (0 = use default 10000)
 * @return I2C_OK on success, I2C_ERROR_TIMEOUT on timeout
 */
int i2c_controller_wait_idle_easy(uint32_t idx, uint32_t timeout);

/**
 * @brief Wait for FMT FIFO space (Easy version)
 *
 * Conservative FIFO space checking with dual verification:
 * - Check STATUS.fmtfull flag
 * - Verify fmtlvl < FIFO_DEPTH
 *
 * Includes periodic debug output every 4096 iterations.
 * Based on i2c_controller_driver.c implementation.
 *
 * @param idx I2C instance index
 * @param timeout Timeout value (0 = use default 10000)
 * @return I2C_OK on success, I2C_ERROR_TIMEOUT on timeout
 */
int i2c_controller_wait_fmt_fifo_space_easy(uint32_t idx, uint32_t timeout);

/**
 * @brief Wait for RX FIFO data (Easy version)
 *
 * Simple polling loop waiting for RX FIFO to reach desired level.
 * Includes periodic debug output every 4096 iterations.
 * Based on i2c_controller_driver.c implementation.
 *
 * @param idx I2C instance index
 * @param level Required RX FIFO level
 * @param timeout Timeout value (0 = use default 10000)
 * @return I2C_OK on success, I2C_ERROR_TIMEOUT on timeout
 */
int i2c_controller_wait_rx_fifo_data_easy(uint32_t idx, uint32_t level, uint32_t timeout);

// ============================================================================
// OpenTitan I2C DIF API equivalents
// ============================================================================

/**
 * @brief Clock timeout types
 */
typedef enum {
    I2C_TIMEOUT_DISABLED = 0, // Timeout disabled
    I2C_TIMEOUT_STRETCH = 1,  // Stretch timeout (target stretching limit)
    I2C_TIMEOUT_BUS = 2       // Bus timeout (SCL low limit, SMBus compatible)
} i2c_timeout_type_t;

/**
 * @brief Acquired data structure from target ACQ FIFO
 */
typedef struct {
    uint8_t data;   // Data byte
    uint8_t signal; // Signal flags (START, STOP, NACK, etc.)
} i2c_acq_data_t;

/**
 * @brief Enable clock timeout for controller or target mode
 *
 * @param idx I2C instance index
 * @param timeout_type 0=disabled, 1=stretch timeout, 2=bus timeout
 * @param cycles Timeout duration in clock cycles
 * @return I2C_OK on success, I2C_ERROR_INVALID on invalid parameters
 */
int i2c_enable_clock_timeout(uint32_t idx, uint8_t timeout_type, uint32_t cycles);

/**
 * @brief Set host timeout for target mode
 *
 * @param idx I2C instance index
 * @param duration Timeout duration in clock cycles
 * @return I2C_OK on success
 */
int i2c_set_host_timeout(uint32_t idx, uint32_t duration);

/**
 * @brief Enable or disable ACK Control Mode
 *
 * @param idx I2C instance index
 * @param enable true to enable, false to disable
 * @return I2C_OK on success
 */
int i2c_ack_ctrl_set_enabled(uint32_t idx, bool enable);

/**
 * @brief Enable or disable target TX stretch control
 *
 * @param idx I2C instance index
 * @param enable true to enable, false to disable
 * @return I2C_OK on success
 */
int i2c_target_tx_stretch_ctrl_set_enabled(uint32_t idx, bool enable);

/**
 * @brief Enable or disable line loopback mode
 *
 * @param idx I2C instance index
 * @param enable true to enable, false to disable
 * @return I2C_OK on success
 */
int i2c_line_loopback_set_enabled(uint32_t idx, bool enable);

/**
 * @brief Enable or disable multi-controller monitor
 *
 * @param idx I2C instance index
 * @param enable true to enable, false to disable
 * @return I2C_OK on success
 */
int i2c_multi_controller_monitor_set_enabled(uint32_t idx, bool enable);

/**
 * @brief Enable or disable address NACK after timeout
 *
 * @param idx I2C instance index
 * @param enable true to enable, false to disable
 * @return I2C_OK on success
 */
int i2c_addr_nack_set_enabled(uint32_t idx, bool enable);

/**
 * @brief Get current Auto ACK Counter value
 *
 * @param idx I2C instance index
 * @param count Pointer to store counter value
 * @return I2C_OK on success, I2C_ERROR_INVALID if count is NULL
 */
int i2c_get_auto_ack_count(uint32_t idx, uint16_t *count);

/**
 * @brief Set Auto ACK Counter value
 *
 * @param idx I2C instance index
 * @param count Number of bytes to automatically ACK (0-255)
 * @return I2C_OK on success
 */
int i2c_set_auto_ack_count(uint32_t idx, uint16_t count);

/**
 * @brief Instruct target to NACK current transaction
 *
 * @param idx I2C instance index
 * @return I2C_OK on success
 */
int i2c_nack_transaction(uint32_t idx);

/**
 * @brief Get pending data byte when stretching
 *
 * @param idx I2C instance index
 * @param data Pointer to store pending data byte
 * @return I2C_OK on success, I2C_ERROR_INVALID if data is NULL
 */
int i2c_get_pending_acq_byte(uint32_t idx, uint8_t *data);

/**
 * @brief Enable or disable override mode
 *
 * @param idx I2C instance index
 * @param enable true to enable, false to disable
 * @return I2C_OK on success
 */
int i2c_override_set_enabled(uint32_t idx, bool enable);

/**
 * @brief Drive SCL and SDA pins in override mode
 *
 * @param idx I2C instance index
 * @param scl SCL pin value (true = high, false = low)
 * @param sda SDA pin value (true = high, false = low)
 * @return I2C_OK on success
 */
int i2c_override_drive_pins(uint32_t idx, bool scl, bool sda);

/**
 * @brief Sample SCL and SDA pin values
 *
 * @param idx I2C instance index
 * @param scl_samples Pointer to store SCL samples (may be NULL)
 * @param sda_samples Pointer to store SDA samples (may be NULL)
 * @return I2C_OK on success
 */
int i2c_override_sample_pins(uint32_t idx, uint16_t *scl_samples, uint16_t *sda_samples);

/**
 * @brief Target ID structure for address configuration
 */
typedef struct {
    uint8_t address; // 7-bit I2C address
    uint8_t mask;    // Address mask
} i2c_target_id_t;

/**
 * @brief Set target device ID (addresses) with masks
 *
 * @param idx I2C instance index
 * @param id0 First address/mask pair (may be NULL to disable)
 * @param id1 Second address/mask pair (may be NULL to disable)
 * @return I2C_OK on success
 */
int i2c_set_device_id(uint32_t idx, const i2c_target_id_t *id0, const i2c_target_id_t *id1);

/**
 * @brief Read multiple bytes from RX FIFO
 *
 * @param idx I2C instance index
 * @param buffer Buffer to store read bytes
 * @param size Number of bytes to read
 * @return Number of bytes actually read, or negative error code
 */
int i2c_read_bytes(uint32_t idx, uint8_t *buffer, size_t size);

/**
 * @brief Write multiple raw bytes to FMT FIFO
 *
 * @param idx I2C instance index
 * @param bytes Buffer containing bytes to write
 * @param size Number of bytes to write
 * @param flags Format flags to apply to all bytes
 * @return Number of bytes actually written, or negative error code
 */
int i2c_write_bytes_raw(uint32_t idx, const uint8_t *bytes, size_t size, uint32_t flags);

/**
 * @brief Transmit multiple bytes to target TX FIFO
 *
 * @param idx I2C instance index
 * @param bytes Buffer containing bytes to transmit
 * @param size Number of bytes to transmit
 * @return Number of bytes actually written, or negative error code
 */
int i2c_transmit_bytes(uint32_t idx, const uint8_t *bytes, size_t size);

/**
 * @brief Acquire multiple bytes from target ACQ FIFO
 *
 * @param idx I2C instance index
 * @param buffer Array to store acquired data
 * @param size Maximum number of entries to read
 * @return Number of entries actually read, or negative error code
 */
int i2c_acquire_bytes(uint32_t idx, i2c_acq_data_t *buffer, size_t size);

/**
 * @brief Get comprehensive FIFO status for all FIFOs
 *
 * @param idx I2C instance index
 * @param fmt_level Pointer to store FMT FIFO level (may be NULL)
 * @param rx_level Pointer to store RX FIFO level (may be NULL)
 * @param tx_level Pointer to store TX FIFO level (may be NULL)
 * @param acq_level Pointer to store ACQ FIFO level (may be NULL)
 * @return I2C_OK on success
 */
int i2c_get_all_fifo_levels(uint32_t idx, uint32_t *fmt_level, uint32_t *rx_level,
                            uint32_t *tx_level, uint32_t *acq_level);

/**
 * @brief Write formatted byte to FMT FIFO with explicit flags
 *
 * @param idx I2C instance index
 * @param byte Data byte to write
 * @param start Set START condition before byte
 * @param stop Set STOP condition after byte
 * @param read Interpret byte as read count
 * @param read_cont Continue reading (ACK last byte)
 * @param suppress_nak_irq Suppress NAK interrupt for this byte
 * @return I2C_OK on success, error code on failure
 */
int i2c_write_byte_formatted(uint32_t idx, uint8_t byte, bool start, bool stop, bool read,
                             bool read_cont, bool suppress_nak_irq);

#ifdef __cplusplus
}
#endif

#endif // I2C_OPENTITAN_H
