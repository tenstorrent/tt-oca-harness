/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

#include <limits.h>
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#include "smc_defines.h"
#include "i2c_target_driver.h"
#include "virt_console.h"

// Fixed parameters: memory layout, number of controller instances, timeout, and default timing.
#define I2C_INSTANCE_STRIDE \
    (SMC_I2C_WRAP_I2C_1__REG_MAP_BASE_ADDR - SMC_I2C_WRAP_I2C_0__REG_MAP_BASE_ADDR)
#define I2C_CONTROLLER_COUNT 2u
#define I2C_DEFAULT_TIMEOUT 10000u

#define debug_mode 1

#define I2C_CLOCK_PERIOD_NS 10u
// Effective SCL period is controlled directly by I2C_SCL_PERIOD_NS.
// In debug_mode, use a 10x shorter period to speed up simulation.
#if debug_mode
#define I2C_SCL_PERIOD_NS 240u
#define I2C_SDA_RISE_NS 20u
#define I2C_SDA_FALL_NS 20u
#else
#define I2C_SCL_PERIOD_NS 4000u
#define I2C_SDA_RISE_NS 120u
#define I2C_SDA_FALL_NS 120u
#endif
#define I2C_INPUT_DELAY_CYCLES 4u
#define I2C_TARGET_TIMEOUT_CYCLES 0xffffffu

#define DEBUG_PRINT 0

// Wrapper that replaces direct simputs() calls with a debug-enabled version.
static inline void log_simputs(const char *msg) {
#if DEBUG_PRINT
    simputs(msg);
#else
    (void)msg;
#endif
}

// Wrapper that replaces direct simputshex16() calls with a debug-enabled version.
static inline void log_simputshex16(const char *msg, uint16_t val) {
#if DEBUG_PRINT
    simputshex16(msg, val);
#else
    (void)msg;
    (void)val;
#endif
}

// Wrapper that replaces direct simputshex32() calls with a debug-enabled version.
static inline void log_simputshex32(const char *msg, uint32_t val) {
#if DEBUG_PRINT
    simputshex32(msg, val);
#else
    (void)msg;
    (void)val;
#endif
}

// This version I2C target must use stop bit for leaving clock stretch state so controller should
// send stop bit after the i2c read/write transaction

static const uintptr_t kCtrlGateAddrs[I2C_CONTROLLER_COUNT] = {
    SMC_I2C_WRAP_I2C_CTRL_REGS_I2C_CTRL_0__REG_ADDR,
    SMC_I2C_WRAP_I2C_CTRL_REGS_I2C_CTRL_1__REG_ADDR,
};

typedef enum {
    kI2cSpeedStandard = 0,
    kI2cSpeedFast,
    kI2cSpeedFastPlus,
} i2c_speed_t;

typedef struct {
    uint16_t scl_time_high_cycles;
    uint16_t scl_time_low_cycles;
    uint16_t rise_cycles;
    uint16_t fall_cycles;
    uint16_t start_signal_setup_cycles;
    uint16_t start_signal_hold_cycles;
    uint16_t data_signal_setup_cycles;
    uint16_t data_signal_hold_cycles;
    uint16_t stop_signal_setup_cycles;
    uint16_t stop_signal_hold_cycles;
} i2c_timing_config_t;

typedef struct {
    uint32_t clock_period_nanos;
    uint32_t scl_period_nanos;
    uint32_t sda_rise_nanos;
    uint32_t sda_fall_nanos;
    i2c_speed_t lowest_target_device_speed;
} i2c_timing_input_t;

typedef enum {
    kI2cSignalNone = 0,
    kI2cSignalStart = 1,
    kI2cSignalStop = 2,
    kI2cSignalRestart = 3,
    kI2cSignalNack = 4,
    kI2cSignalNackStart = 5,
    kI2cSignalNackStop = 6,
} i2c_signal_t;

// ===== Low-level access helpers =====
static inline bool is_valid_controller(uint8_t i2c_id) {
    return i2c_id < I2C_CONTROLLER_COUNT;
}

static inline uintptr_t i2c_reg_addr(uint8_t i2c_id, uint32_t offset) {
    return SMC_I2C_WRAP_I2C_0__REG_MAP_BASE_ADDR + (uintptr_t)i2c_id * I2C_INSTANCE_STRIDE + offset;
}

static inline uint32_t i2c_reg_read(uint8_t i2c_id, uint32_t offset) {
    return read_reg(i2c_reg_addr(i2c_id, offset));
}

static inline void i2c_reg_write(uint8_t i2c_id, uint32_t offset, uint32_t value) {
    write_reg(i2c_reg_addr(i2c_id, offset), value);
}

static uint16_t round_up_divide(uint32_t a, uint32_t b) {
    return (uint16_t)(((a - 1u) / b) + 1u);
}

// ===== Timing computation: derive intervals based on target speed =====
static i2c_timing_config_t default_timing_for_speed(i2c_speed_t speed,
                                                    uint32_t clock_period_nanos) {
    switch (speed) {
    case kI2cSpeedStandard:
        return (i2c_timing_config_t){
            .scl_time_high_cycles = round_up_divide(4000u, clock_period_nanos),
            .scl_time_low_cycles = round_up_divide(4700u, clock_period_nanos),
            .start_signal_setup_cycles = round_up_divide(4700u, clock_period_nanos),
            .start_signal_hold_cycles = round_up_divide(4000u, clock_period_nanos),
            .data_signal_setup_cycles = round_up_divide(250u, clock_period_nanos),
            .data_signal_hold_cycles = 1u,
            .stop_signal_setup_cycles = round_up_divide(4000u, clock_period_nanos),
            .stop_signal_hold_cycles = round_up_divide(4700u, clock_period_nanos),
        };
    case kI2cSpeedFast:
        return (i2c_timing_config_t){
            .scl_time_high_cycles = round_up_divide(600u, clock_period_nanos),
            .scl_time_low_cycles = round_up_divide(1300u, clock_period_nanos),
            .start_signal_setup_cycles = round_up_divide(600u, clock_period_nanos),
            .start_signal_hold_cycles = round_up_divide(600u, clock_period_nanos),
            .data_signal_setup_cycles = round_up_divide(100u, clock_period_nanos),
            .data_signal_hold_cycles = 1u,
            .stop_signal_setup_cycles = round_up_divide(600u, clock_period_nanos),
            .stop_signal_hold_cycles = round_up_divide(1300u, clock_period_nanos),
        };
    case kI2cSpeedFastPlus:
        return (i2c_timing_config_t){
            .scl_time_high_cycles = round_up_divide(260u, clock_period_nanos),
            .scl_time_low_cycles = round_up_divide(500u, clock_period_nanos),
            .start_signal_setup_cycles = round_up_divide(260u, clock_period_nanos),
            .start_signal_hold_cycles = round_up_divide(260u, clock_period_nanos),
            .data_signal_setup_cycles = round_up_divide(50u, clock_period_nanos),
            .data_signal_hold_cycles = 1u,
            .stop_signal_setup_cycles = round_up_divide(260u, clock_period_nanos),
            .stop_signal_hold_cycles = round_up_divide(500u, clock_period_nanos),
        };
    default:
        return (i2c_timing_config_t){0};
    }
}

static bool compute_timing(const i2c_timing_input_t *input, i2c_timing_config_t *config) {
    if (!input || !config) {
        return false;
    }

    const uint32_t kNanosPerKBaud = 1000000u;
    uint32_t lowest_speed_khz;
    switch (input->lowest_target_device_speed) {
    case kI2cSpeedStandard:
        lowest_speed_khz = 100u;
        break;
    case kI2cSpeedFast:
        lowest_speed_khz = 400u;
        break;
    case kI2cSpeedFastPlus:
        lowest_speed_khz = 1000u;
        break;
    default:
        return false;
    }

    *config =
        default_timing_for_speed(input->lowest_target_device_speed, input->clock_period_nanos);
    config->rise_cycles = round_up_divide(input->sda_rise_nanos, input->clock_period_nanos);
    config->fall_cycles = round_up_divide(input->sda_fall_nanos, input->clock_period_nanos);

    uint32_t scl_period_nanos = input->scl_period_nanos;

#if !debug_mode
    const uint32_t slowest_scl_period_nanos = kNanosPerKBaud / lowest_speed_khz;
    if (scl_period_nanos < slowest_scl_period_nanos) {
        scl_period_nanos = slowest_scl_period_nanos;
    }
#else
    (void)lowest_speed_khz;
#endif
    const uint16_t scl_period_cycles = round_up_divide(scl_period_nanos, input->clock_period_nanos);
    int32_t lengthened_high_cycles = (int32_t)scl_period_cycles -
                                     (int32_t)config->scl_time_low_cycles -
                                     (int32_t)config->rise_cycles - (int32_t)config->fall_cycles;
    if (lengthened_high_cycles > (int32_t)config->scl_time_high_cycles) {
        if (lengthened_high_cycles < 0 || lengthened_high_cycles > INT16_MAX) {
            return false;
        }
        config->scl_time_high_cycles = (uint16_t)lengthened_high_cycles;
    }

    if (config->scl_time_high_cycles < I2C_INPUT_DELAY_CYCLES) {
        config->scl_time_high_cycles = I2C_INPUT_DELAY_CYCLES;
    }
    if (config->scl_time_low_cycles < I2C_INPUT_DELAY_CYCLES) {
        config->scl_time_low_cycles = I2C_INPUT_DELAY_CYCLES;
    }

    return true;
}

// ===== Timing programming: write configuration into hardware registers =====
static void program_timing(uint8_t i2c_id, const i2c_timing_config_t *config) {
    I2C_TIMING0_reg_u timing0 = {.val = 0};
    timing0.f.thigh = config->scl_time_high_cycles;
    timing0.f.tlow = config->scl_time_low_cycles;
    i2c_reg_write(i2c_id, SMC_I2C_WRAP_I2C_0__TIMING0_REG_OFFSET, timing0.val);

    I2C_TIMING1_reg_u timing1 = {.val = 0};
    timing1.f.t_r = config->rise_cycles;
    timing1.f.t_f = config->fall_cycles;
    i2c_reg_write(i2c_id, SMC_I2C_WRAP_I2C_0__TIMING1_REG_OFFSET, timing1.val);

    I2C_TIMING2_reg_u timing2 = {.val = 0};
    timing2.f.tsu_sta = config->start_signal_setup_cycles;
    timing2.f.thd_sta = config->start_signal_hold_cycles;
    i2c_reg_write(i2c_id, SMC_I2C_WRAP_I2C_0__TIMING2_REG_OFFSET, timing2.val);

    I2C_TIMING3_reg_u timing3 = {.val = 0};
    timing3.f.tsu_dat = config->data_signal_setup_cycles;
    timing3.f.thd_dat = config->data_signal_hold_cycles;
    i2c_reg_write(i2c_id, SMC_I2C_WRAP_I2C_0__TIMING3_REG_OFFSET, timing3.val);

    I2C_TIMING4_reg_u timing4 = {.val = 0};
    timing4.f.tsu_sto = config->stop_signal_setup_cycles;
    timing4.f.t_buf = config->stop_signal_hold_cycles;
    i2c_reg_write(i2c_id, SMC_I2C_WRAP_I2C_0__TIMING4_REG_OFFSET, timing4.val);
}

// ===== Target-mode shared helper functions =====
static void disable_target(uint8_t i2c_id) {
    I2C_CTRL_reg_u ctrl = {.val = i2c_reg_read(i2c_id, SMC_I2C_WRAP_I2C_0__CTRL_REG_OFFSET)};
    ctrl.f.enablehost = 0;
    ctrl.f.enabletarget = 0;
    i2c_reg_write(i2c_id, SMC_I2C_WRAP_I2C_0__CTRL_REG_OFFSET, ctrl.val);
}

static void enable_target(uint8_t i2c_id) {
    I2C_CTRL_reg_u ctrl = {.val = i2c_reg_read(i2c_id, SMC_I2C_WRAP_I2C_0__CTRL_REG_OFFSET)};
    ctrl.f.enablehost = 0;
    ctrl.f.enabletarget = 1;
    // Enable Software TX Stretch Mode so that READ address causes the target to
    // stretch the clock and assert TARGET_EVENTS.TX_PENDING, allowing firmware
    // to prepare TX data before releasing SCL.
    ctrl.f.tx_stretch_ctrl_en = 0;
    i2c_reg_write(i2c_id, SMC_I2C_WRAP_I2C_0__CTRL_REG_OFFSET, ctrl.val);
}

static void reset_fifos(uint8_t i2c_id) {
    I2C_FIFO_CTRL_reg_u fifo_ctrl = {.val = 0};
    fifo_ctrl.f.rxrst = 1;
    fifo_ctrl.f.txrst = 1;
    fifo_ctrl.f.acqrst = 1;
    fifo_ctrl.f.fmtrst = 1;
    i2c_reg_write(i2c_id, SMC_I2C_WRAP_I2C_0__FIFO_CTRL_REG_OFFSET, fifo_ctrl.val);
}

static void configure_threshold(uint8_t i2c_id, uint16_t tx_thresh, uint16_t acq_thresh) {
    I2C_TARGET_FIFO_CONFIG_reg_u cfg = {.val = 0};
    cfg.f.tx_thresh = tx_thresh;
    cfg.f.acq_thresh = acq_thresh;
    i2c_reg_write(i2c_id, SMC_I2C_WRAP_I2C_0__TARGET_FIFO_CONFIG_REG_OFFSET, cfg.val);
}

static void clear_all_interrupts(uint8_t i2c_id) {
    I2C_INTR_ENABLE_reg_u intr_enable = {.val = 0};
    i2c_reg_write(i2c_id, SMC_I2C_WRAP_I2C_0__INTR_ENABLE_REG_OFFSET, intr_enable.val);

    I2C_INTR_STATE_reg_u intr_state = {.val = 0xFFFFFFFFu};
    i2c_reg_write(i2c_id, SMC_I2C_WRAP_I2C_0__INTR_STATE_REG_OFFSET, intr_state.val);
}

static void clear_target_events(uint8_t i2c_id) {
    I2C_TARGET_EVENTS_reg_u events = {.val = 0};
    // events.f.tx_pending = 1;  // leave TX_PENDING untouched by default
    events.f.bus_timeout = 1;
    events.f.arbitration_lost = 1;
    // Clear start/stop detection flags as well to avoid stale state between transactions.
    events.f.start_detect = 1;
    events.f.stop_detect = 1;
    i2c_reg_write(i2c_id, SMC_I2C_WRAP_I2C_0__TARGET_EVENTS_REG_OFFSET, events.val);
}

static bool wait_for_tx_space(uint8_t i2c_id, uint32_t timeout) {
    uint32_t remaining = timeout ? timeout : I2C_DEFAULT_TIMEOUT;
    while (remaining--) {
        I2C_STATUS_reg_u status = {.val =
                                       i2c_reg_read(i2c_id, SMC_I2C_WRAP_I2C_0__STATUS_REG_OFFSET)};
        if (!status.f.txfull) {
            return true;
        }
    }
    simputs("[I2C_TARGET][wait_for_tx_space] TIMEOUT\n");

    return false;
}

static bool wait_for_acq_data(uint8_t i2c_id, uint32_t timeout) {
    uint32_t remaining = timeout ? timeout : I2C_DEFAULT_TIMEOUT;
    while (remaining--) {
        I2C_STATUS_reg_u status = {.val =
                                       i2c_reg_read(i2c_id, SMC_I2C_WRAP_I2C_0__STATUS_REG_OFFSET)};
        if (!status.f.acqempty) {
            return true;
        }
    }
    return false;
}

static bool wait_for_start(uint8_t i2c_id, uint32_t timeout) {
    uint32_t remaining = timeout ? timeout : I2C_DEFAULT_TIMEOUT;

    while (remaining--) {
        I2C_TARGET_EVENTS_reg_u events = (I2C_TARGET_EVENTS_reg_u){
            .val = i2c_reg_read(i2c_id, SMC_I2C_WRAP_I2C_0__TARGET_EVENTS_REG_OFFSET)};
        if (events.f.start_detect) {
            // Clear the START_DETECT flag (W1C semantics).
            I2C_TARGET_EVENTS_reg_u clr = {.val = 0};
            clr.f.start_detect = 1;
            i2c_reg_write(i2c_id, SMC_I2C_WRAP_I2C_0__TARGET_EVENTS_REG_OFFSET, clr.val);

            simputs("[I2C_TARGET][wait_for_start] START_DETECT seen\n");
            return true;
        }
    }

    simputs("[I2C_TARGET][wait_for_start] START_DETECT TIMEOUT\n");
    return false;
}

// ===== Public API: basic reset and enabling power gating =====
void I2C_release_reset(uint8_t i2c_id) {
    log_simputs("[I2C_TARGET][I2C_release_reset] enter\n");
    if (!is_valid_controller(i2c_id)) {
        simputs("[I2C_TARGET][I2C_release_reset] invalid controller id\n");
        return;
    }

    // i2c_wrapper disable
    I2C_CTRL_I2C_CTRL_reg_u ctrl_gate = {.val = read_reg(kCtrlGateAddrs[i2c_id])};
    ctrl_gate.f.i2c_en = 0;
    ctrl_gate.f.i2c_controller_mode_en = 1;
    write_reg(kCtrlGateAddrs[i2c_id], ctrl_gate.val);

    disable_target(i2c_id);
    reset_fifos(i2c_id);
    clear_all_interrupts(i2c_id);
    clear_target_events(i2c_id);

    log_simputs("[I2C_TARGET][I2C_release_reset] done\n");
}

// ===== Target initialization: configure timing, FIFOs, timeouts, and target addresses =====
I2C_Status init_target(I2C_Driver *drv, uint8_t i2c_addr) {
    simputs("[I2C_TARGET][init_target] enter\n");
    if (!drv || !drv->ctx.initialized || !is_valid_controller(drv->ctx.controller_id)) {
        simputs("[I2C_TARGET][init_target] invalid args or controller\n");
        return I2C_ERR_HW;
    }

    const uint8_t i2c_id = drv->ctx.controller_id;
    log_simputs("[I2C_TARGET][init_target] controller_id=");
    log_simputshex16("", i2c_id);
    log_simputs("[I2C_TARGET][init_target] target_addr=");
    log_simputshex16("", i2c_addr);
    I2C_release_reset(i2c_id);

    // i2c_wrapper enable
    I2C_CTRL_I2C_CTRL_reg_u ctrl_gate = {.val = read_reg(kCtrlGateAddrs[i2c_id])};
    ctrl_gate.f.i2c_en = 1;
    ctrl_gate.f.i2c_controller_mode_en = 0;
    write_reg(kCtrlGateAddrs[i2c_id], ctrl_gate.val);

    static const i2c_timing_input_t kDefaultTiming = {
        .clock_period_nanos = I2C_CLOCK_PERIOD_NS,
        .scl_period_nanos = I2C_SCL_PERIOD_NS,
        .sda_rise_nanos = I2C_SDA_RISE_NS,
        .sda_fall_nanos = I2C_SDA_FALL_NS,
        .lowest_target_device_speed = kI2cSpeedFast,
    };
    i2c_timing_config_t timing = {0};
    if (!compute_timing(&kDefaultTiming, &timing)) {
        simputs("[I2C_TARGET][init_target] compute_timing FAILED\n");
        return I2C_ERR_HW;
    }
    program_timing(i2c_id, &timing);

    reset_fifos(i2c_id);
    configure_threshold(i2c_id, 0u, 0u);
    clear_all_interrupts(i2c_id);
    clear_target_events(i2c_id);

    I2C_TARGET_ID_reg_u target_id = {.val = 0};
    target_id.f.address0 = i2c_addr & I2C_TARGET_ID_ADDRESS0_MASK;
    target_id.f.mask0 = 0x7Fu;
    target_id.f.address1 = 0x10u;
    target_id.f.mask1 = 0x7Fu;
    i2c_reg_write(i2c_id, SMC_I2C_WRAP_I2C_0__TARGET_ID_REG_OFFSET, target_id.val);

    I2C_TIMEOUT_CTRL_reg_u timeout_ctrl = {.val = 0};
    timeout_ctrl.f.val = I2C_TARGET_TIMEOUT_CYCLES;
    timeout_ctrl.f.mode = 1u; // bus timeout
    timeout_ctrl.f.en = 1u;
    i2c_reg_write(i2c_id, SMC_I2C_WRAP_I2C_0__TIMEOUT_CTRL_REG_OFFSET, timeout_ctrl.val);

    I2C_TARGET_TIMEOUT_CTRL_reg_u target_timeout = {.val = 0};
    target_timeout.f.val = I2C_TARGET_TIMEOUT_CYCLES;
    target_timeout.f.en = 1u;
    i2c_reg_write(i2c_id, SMC_I2C_WRAP_I2C_0__TARGET_TIMEOUT_CTRL_REG_OFFSET, target_timeout.val);

    enable_target(i2c_id);

    simputs("[I2C_TARGET][init_target] exit OK\n");
    return I2C_OK;
}

I2C_Status read_target(I2C_Driver *drv, const uint8_t *tx_buf, size_t tx_buf_len,
                       uint32_t timeout) {

    if (!drv || !drv->ctx.initialized || !tx_buf || tx_buf_len == 0 ||
        !is_valid_controller(drv->ctx.controller_id)) {
        simputs("[I2C_TARGET][TX] invalid args or controller\n");
        return I2C_ERR_HW;
    }

    const uint8_t i2c_id = drv->ctx.controller_id;
    simputs("[I2C_TARGET][TX] LEN==");
    simputshex16("", (uint32_t)tx_buf_len);

    I2C_TARGET_FIFO_STATUS_reg_u fifo_dbg = (I2C_TARGET_FIFO_STATUS_reg_u){
        .val = i2c_reg_read(i2c_id, SMC_I2C_WRAP_I2C_0__TARGET_FIFO_STATUS_REG_OFFSET)};

    if (fifo_dbg.f.acqlvl != 0) {
        // ACQ FIFO should be empty when we are about to start a TX flow.
        simputs("[I2C_TARGET][TX] acq fifo should be empty, clearing. acqlvl=");
        simputshex16("", (uint32_t)fifo_dbg.f.acqlvl);

        // Clear (reset) only the ACQ FIFO to avoid disrupting TX/RX/FMT FIFOs.
        I2C_FIFO_CTRL_reg_u fifo_ctrl = {.val = 0};
        fifo_ctrl.f.acqrst = 1;
        i2c_reg_write(i2c_id, SMC_I2C_WRAP_I2C_0__FIFO_CTRL_REG_OFFSET, fifo_ctrl.val);

        fifo_dbg.val = i2c_reg_read(i2c_id, SMC_I2C_WRAP_I2C_0__TARGET_FIFO_STATUS_REG_OFFSET);
        if (fifo_dbg.f.acqlvl != 0) {
            simputs("[I2C_TARGET][TX] WARN: ACQ FIFO not empty after clear. acqlvl=");
            simputshex16("", (uint32_t)fifo_dbg.f.acqlvl);
            return I2C_ERR_HW;
        }
    }

    for (size_t i = 0; i < tx_buf_len; ++i) {

        if (!wait_for_tx_space(i2c_id, timeout * 4)) {
            simputs("[I2C_TARGET][TX] wait_for_tx_space TIMEOUT\n");
            return I2C_ERR_TIMEOUT;
        }
        log_simputs("[I2C_TARGET TX] Sending=");
        log_simputshex16("", tx_buf[i]);

        I2C_TXDATA_reg_u tx_word = {.val = 0};
        tx_word.f.data = tx_buf[i];
        i2c_reg_write(i2c_id, SMC_I2C_WRAP_I2C_0__TXDATA_REG_OFFSET, tx_word.val);
    }

    simputs("[I2C_TARGET][TX] Done----------\n");

    return I2C_OK;
}

// ===== Target-side receive: pull data from ACQ FIFO and check Start/Stop/NACK =====
I2C_Status write_target(I2C_Driver *drv, uint8_t *rx_buf, size_t rx_buf_len, size_t *bytes_received,
                        uint32_t timeout, bool expect_start_det, bool expect_stop_det) {

    if (!drv || !drv->ctx.initialized || !rx_buf || !is_valid_controller(drv->ctx.controller_id) ||
        (bytes_received == NULL)) {
        simputs("[I2C_TARGET][RX] invalid args or controller\n");
        return I2C_ERR_HW;
    }

    const uint8_t i2c_id = drv->ctx.controller_id;
    size_t index = 0;
    bool stop_detect = false;

    simputs("[I2C_TARGET][RX] LEN==");
    simputshex16("", (uint32_t)rx_buf_len);

    log_simputs("[I2C_TARGET][RX] expect_start_det=");
    log_simputshex16("", (uint32_t)expect_start_det);

    log_simputs("[I2C_TARGET][RX] expect_stop_det=");
    log_simputshex16("", (uint32_t)expect_stop_det);

    simputs("[I2C_TARGET][RX] start expect_stop_det=");
    simputshex16("", (uint32_t)expect_stop_det);

    simputs("[I2C_TARGET][RX] start stop_det==");
    simputshex16("", (uint32_t)stop_detect);

    if (expect_start_det) {
        if (!wait_for_start(i2c_id, timeout)) {
            simputs("[I2C_TARGET][RX] wait_for_start TIMEOUT\n");
            return I2C_ERR_TIMEOUT;
        }
    }

    while (index < rx_buf_len) {

        if (!wait_for_acq_data(i2c_id, timeout)) {
            if (bytes_received != NULL) {
                *bytes_received = index;
            }
            simputs("[I2C_TARGET][RX] wait_for_acq_data TIMEOUT\n");
            /* Timeout before receiving expected bytes => INCOMPLETE. */
            return I2C_ERR_INCOMPLETE;
        }

        I2C_ACQDATA_reg_u acq = {.val =
                                     i2c_reg_read(i2c_id, SMC_I2C_WRAP_I2C_0__ACQDATA_REG_OFFSET)};
        uint8_t data_byte = (uint8_t)acq.f.abyte;

        rx_buf[index] = data_byte;
        index++;

        I2C_TARGET_EVENTS_reg_u events = (I2C_TARGET_EVENTS_reg_u){
            .val = i2c_reg_read(i2c_id, SMC_I2C_WRAP_I2C_0__TARGET_EVENTS_REG_OFFSET)};
        if (expect_stop_det) {

            /* Only clear STOP_DETECT when caller expects STOP to end this stage. */
            if (events.f.stop_detect) {
                I2C_TARGET_EVENTS_reg_u clr = {.val = 0};
                clr.f.stop_detect = 1;
                i2c_reg_write(i2c_id, SMC_I2C_WRAP_I2C_0__TARGET_EVENTS_REG_OFFSET, clr.val);
                stop_detect = true;
                log_simputs("[I2C_TARGET][RX] stop_detect \n");
            }
        }
    }

    for (size_t i = 0; i < index; ++i) {
        log_simputs("[I2C_TARGET][RX] received bytes: ");
        log_simputshex16("", rx_buf[i]);
    }

    if (expect_stop_det && !stop_detect) {
        // If we haven't already observed a STOP on the bus, give the hardware a final
        // chance to report it via TARGET_EVENTS.STOP_DETECT before declaring failure.
        uint32_t remaining = timeout ? timeout : I2C_DEFAULT_TIMEOUT;
        while (remaining-- && !stop_detect) {
            I2C_TARGET_EVENTS_reg_u events = (I2C_TARGET_EVENTS_reg_u){
                .val = i2c_reg_read(i2c_id, SMC_I2C_WRAP_I2C_0__TARGET_EVENTS_REG_OFFSET)};
            I2C_TARGET_FIFO_STATUS_reg_u fifo_dbg = (I2C_TARGET_FIFO_STATUS_reg_u){
                .val = i2c_reg_read(i2c_id, SMC_I2C_WRAP_I2C_0__TARGET_FIFO_STATUS_REG_OFFSET)};

            if (events.f.stop_detect) {
                // Clear the STOP_DETECT flag (W1C semantics).
                I2C_TARGET_EVENTS_reg_u clr = {.val = 0};
                clr.f.stop_detect = 1;
                i2c_reg_write(i2c_id, SMC_I2C_WRAP_I2C_0__TARGET_EVENTS_REG_OFFSET, clr.val);

                simputs("[I2C_TARGET][wait_for_stop] STOP_DETECT seen\n");
                stop_detect = true;
            }

            if (fifo_dbg.f.acqlvl > 0) {
                simputs("[I2C_TARGET][RX] overflow\n");
                return I2C_ERR_OVERFLOW;
            }

            if (!stop_detect && (remaining == 0)) {
                simputs("[I2C_TARGET][RX] TIMEOUT\n");
                return I2C_ERR_TIMEOUT; // Timeout waiting for stop condition
            }
        }
    }

    if (expect_stop_det) {

        simputs("[I2C_TARGET][RX] mid stop_det==");
        simputshex16("", (uint32_t)stop_detect);

        for (int i = 0; i < 1000; i++) {
            I2C_TARGET_FIFO_STATUS_reg_u fifo_dbg = (I2C_TARGET_FIFO_STATUS_reg_u){
                .val = i2c_reg_read(i2c_id, SMC_I2C_WRAP_I2C_0__TARGET_FIFO_STATUS_REG_OFFSET)};

            if (i == 0)
                simputshex16("first acqlvl=", (uint16_t)fifo_dbg.f.acqlvl);
            else if (i == 99)
                simputshex16("lastacqlvl=", (uint16_t)fifo_dbg.f.acqlvl);

            if (fifo_dbg.f.acqlvl > 0) {
                simputs("[I2C_TARGET][RX] overflow\n");
                return I2C_ERR_OVERFLOW;
            }
        }
    }

    if (bytes_received != NULL) {
        *bytes_received = index;
    }

    // Oversized packet: we received the expected number of bytes but did not observe STOP.
    // Received expected number of bytes without observing STOP: treat as overflow so upper layers
    // can generate Oversize_msg.
    if (expect_stop_det && !stop_detect && (index == rx_buf_len) && (rx_buf_len > 0)) {
        simputs("[I2C_TARGET][RX] I2C_ERR_OVERFLOW\n");
        return I2C_ERR_OVERFLOW;
    }

    simputs("[I2C_TARGET][RX] Done----------\n");

    simputs("[I2C_TARGET][RX]end stop_det==");
    simputshex16("", (uint32_t)stop_detect);

    return I2C_OK;
}

// ===== Check current ACQ FIFO depth to facilitate polling flow =====
uint32_t check_rx_fifo(I2C_Driver *drv) {
    if (!drv || !drv->ctx.initialized || !is_valid_controller(drv->ctx.controller_id)) {
        return 0;
    }

    I2C_TARGET_FIFO_STATUS_reg_u status = {
        .val = i2c_reg_read(drv->ctx.controller_id,
                            SMC_I2C_WRAP_I2C_0__TARGET_FIFO_STATUS_REG_OFFSET)};
    return status.f.acqlvl;
}

// ===== Singleton getter for driver instances, binding various operation function pointers =====
I2C_Driver *I2C_GetDriverInstance(uint8_t i2c_id) {
    static I2C_Driver i2c_driver_instances[I2C_CONTROLLER_COUNT] = {0};
    static bool initialized[I2C_CONTROLLER_COUNT] = {false};

    if (!is_valid_controller(i2c_id)) {
        return NULL;
    }

    I2C_Driver *i2c_driver_instance = &i2c_driver_instances[i2c_id];

    if (!initialized[i2c_id]) {
        i2c_driver_instance->release_reset = I2C_release_reset;
        i2c_driver_instance->init_target = init_target;
        i2c_driver_instance->read_target = read_target;
        i2c_driver_instance->write_target = write_target;
        i2c_driver_instance->check_rx_fifo = check_rx_fifo;
        i2c_driver_instance->ctx.controller_id = i2c_id;
        i2c_driver_instance->ctx.mode = TARGET_I2C_SLAVE;
        i2c_driver_instance->ctx.initialized = true;
        initialized[i2c_id] = true;
    } else {
        i2c_driver_instance->ctx.controller_id = i2c_id;
    }

    return i2c_driver_instance;
}
