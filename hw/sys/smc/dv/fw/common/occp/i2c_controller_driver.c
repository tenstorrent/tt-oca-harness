/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

#include "occp_test_common.h"
#include "virt_console.h"

/* The I2C wrapper has no native generated block header, so its register
 * offsets and field unions come from this extracted subset. */
#include "smc_i2c_regs.h"

#define I2C_INSTANCE_STRIDE 0x200u
#define I2C_MAX_CONTROLLERS 2u
#define I2C_DEFAULT_TIMEOUT 10000u

#define debug_mode 1

#define I2C_CLOCK_PERIOD_NS 10u
// Effective SCL period is controlled directly by I2C_SCL_PERIOD_NS.
// debug_mode shortens the SCL period to speed up simulation.
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
#define I2C_CONTROLLER_TIMEOUT_CYCLES 0xffffffu

#define I2C_PARAM_FIFO_DEPTH 64u

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

static uint8_t g_target_addr[I2C_MAX_CONTROLLERS];
static const uintptr_t kCtrlGateAddrs[I2C_MAX_CONTROLLERS] = {
    SMC_I2C_WRAP_I2C_CTRL_REGS_I2C_CTRL_0__REG_ADDR,
    SMC_I2C_WRAP_I2C_CTRL_REGS_I2C_CTRL_1__REG_ADDR,
};

static inline bool is_valid_controller(uint8_t i2c_id) {
    return i2c_id < I2C_MAX_CONTROLLERS;
}

static inline uintptr_t i2c_reg_base(int i2c_id) {
    return SMC_I2C_WRAP_I2C_0__REG_MAP_BASE_ADDR + (uintptr_t)i2c_id * I2C_INSTANCE_STRIDE;
}

static inline uintptr_t i2c_reg_addr(int i2c_id, uint32_t offset) {
    return i2c_reg_base(i2c_id) + offset;
}

static inline void write_i2c_reg(int i2c_id, uint32_t offset, uint32_t val) {
    write_reg(i2c_reg_addr(i2c_id, offset), val);
}

static inline uint32_t read_i2c_reg(int i2c_id, uint32_t offset) {
    return read_reg(i2c_reg_addr(i2c_id, offset));
}

static uint16_t round_up_divide(uint32_t a, uint32_t b) {
    return (uint16_t)(((a - 1u) / b) + 1u);
}

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

    {
        uint32_t active_cycles =
            (uint32_t)config->scl_time_high_cycles + (uint32_t)config->scl_time_low_cycles;
        uint16_t half = (uint16_t)(active_cycles / 2u);
        if (half < I2C_INPUT_DELAY_CYCLES) {
            half = I2C_INPUT_DELAY_CYCLES;
        }
        uint16_t other = (uint16_t)(active_cycles - half);
        if (other < I2C_INPUT_DELAY_CYCLES) {
            half = I2C_INPUT_DELAY_CYCLES;
            other = I2C_INPUT_DELAY_CYCLES;
        }
        config->scl_time_high_cycles = half;
        config->scl_time_low_cycles = other;
    }

    return true;
}

static void program_controller_timing(uint8_t i2c_id, const i2c_timing_config_t *config) {
    simputs("[I2C_CTRL][program_timing] enter\n");

    I2C_TIMING0_reg_u timing0 = {.val = 0};
    timing0.f.thigh = config->scl_time_high_cycles;
    timing0.f.tlow = config->scl_time_low_cycles;
    simputshex32("[I2C_CTRL][program_timing] TIMING0 write begin: ", timing0.val);
    write_i2c_reg(i2c_id, SMC_I2C_WRAP_I2C_0__TIMING0_REG_OFFSET, timing0.val);
    simputs("[I2C_CTRL][program_timing] TIMING0 write done\n");

    I2C_TIMING1_reg_u timing1 = {.val = 0};
    timing1.f.t_r = config->rise_cycles;
    timing1.f.t_f = config->fall_cycles;
    simputshex32("[I2C_CTRL][program_timing] TIMING1 write begin: ", timing1.val);
    write_i2c_reg(i2c_id, SMC_I2C_WRAP_I2C_0__TIMING1_REG_OFFSET, timing1.val);
    simputs("[I2C_CTRL][program_timing] TIMING1 write done\n");

    I2C_TIMING2_reg_u timing2 = {.val = 0};
    timing2.f.tsu_sta = config->start_signal_setup_cycles;
    timing2.f.thd_sta = config->start_signal_hold_cycles;
    simputshex32("[I2C_CTRL][program_timing] TIMING2 write begin: ", timing2.val);
    write_i2c_reg(i2c_id, SMC_I2C_WRAP_I2C_0__TIMING2_REG_OFFSET, timing2.val);
    simputs("[I2C_CTRL][program_timing] TIMING2 write done\n");

    I2C_TIMING3_reg_u timing3 = {.val = 0};
    timing3.f.tsu_dat = config->data_signal_setup_cycles;
    timing3.f.thd_dat = config->data_signal_hold_cycles;
    simputshex32("[I2C_CTRL][program_timing] TIMING3 write begin: ", timing3.val);
    write_i2c_reg(i2c_id, SMC_I2C_WRAP_I2C_0__TIMING3_REG_OFFSET, timing3.val);
    simputs("[I2C_CTRL][program_timing] TIMING3 write done\n");

    I2C_TIMING4_reg_u timing4 = {.val = 0};
    timing4.f.tsu_sto = config->stop_signal_setup_cycles;
    timing4.f.t_buf = config->stop_signal_hold_cycles;
    simputshex32("[I2C_CTRL][program_timing] TIMING4 write begin: ", timing4.val);
    write_i2c_reg(i2c_id, SMC_I2C_WRAP_I2C_0__TIMING4_REG_OFFSET, timing4.val);
    simputs("[I2C_CTRL][program_timing] TIMING4 write done\n");
    simputs("[I2C_CTRL][program_timing] exit\n");
}

static void reset_controller_fifos(uint8_t i2c_id) {
    I2C_FIFO_CTRL_reg_u fifo_ctrl = {.val = 0};
    fifo_ctrl.f.rxrst = 1;
    fifo_ctrl.f.fmtrst = 1;
    fifo_ctrl.f.txrst = 1;
    simputshex32("[I2C_CTRL][reset_fifos] FIFO_CTRL write begin: ", fifo_ctrl.val);
    write_i2c_reg(i2c_id, SMC_I2C_WRAP_I2C_0__FIFO_CTRL_REG_OFFSET, fifo_ctrl.val);
    simputs("[I2C_CTRL][reset_fifos] FIFO_CTRL write done\n");
}

static void configure_threshold(uint8_t i2c_id, uint16_t fmt_thresh, uint16_t rx_thresh) {
    I2C_HOST_FIFO_CONFIG_reg_u host_cfg = {.val = 0};
    host_cfg.f.fmt_thresh = fmt_thresh;
    host_cfg.f.rx_thresh = rx_thresh;
    simputshex32("[I2C_CTRL][threshold] HOST_FIFO_CONFIG write begin: ", host_cfg.val);
    write_i2c_reg(i2c_id, SMC_I2C_WRAP_I2C_0__HOST_FIFO_CONFIG_REG_OFFSET, host_cfg.val);
    simputs("[I2C_CTRL][threshold] HOST_FIFO_CONFIG write done\n");
}

static void clear_controller_interrupts(uint8_t i2c_id) {
    write_i2c_reg(i2c_id, SMC_I2C_WRAP_I2C_0__INTR_ENABLE_REG_OFFSET, 0);
    write_i2c_reg(i2c_id, SMC_I2C_WRAP_I2C_0__INTR_STATE_REG_OFFSET, 0xFFFFFFFF);
}

static void disable_controller(uint8_t i2c_id) {
    I2C_CTRL_reg_u ctrl = {.val = read_i2c_reg(i2c_id, SMC_I2C_WRAP_I2C_0__CTRL_REG_OFFSET)};
    ctrl.f.enablehost = 0;
    ctrl.f.enabletarget = 0;
    write_i2c_reg(i2c_id, SMC_I2C_WRAP_I2C_0__CTRL_REG_OFFSET, ctrl.val);
}

static void enable_controller(uint8_t i2c_id) {
    simputs("[I2C_CTRL][enable_controller] CTRL read begin\n");
    I2C_CTRL_reg_u ctrl = {.val = read_i2c_reg(i2c_id, SMC_I2C_WRAP_I2C_0__CTRL_REG_OFFSET)};
    simputshex32("[I2C_CTRL][enable_controller] CTRL read value: ", ctrl.val);
    ctrl.f.enabletarget = 0;
    ctrl.f.enablehost = 1;
    ctrl.f.tx_stretch_ctrl_en = 1;
    simputshex32("[I2C_CTRL][enable_controller] CTRL write begin: ", ctrl.val);
    write_i2c_reg(i2c_id, SMC_I2C_WRAP_I2C_0__CTRL_REG_OFFSET, ctrl.val);
    simputs("[I2C_CTRL][enable_controller] CTRL write done\n");
}

static void configure_controller_timeout(uint8_t i2c_id) {
    simputshex32("[I2C_CTRL][timeout] HOST_TIMEOUT_CTRL write begin: ",
                 I2C_CONTROLLER_TIMEOUT_CYCLES);
    write_i2c_reg(i2c_id, SMC_I2C_WRAP_I2C_0__HOST_TIMEOUT_CTRL_REG_OFFSET,
                  I2C_CONTROLLER_TIMEOUT_CYCLES);
    simputs("[I2C_CTRL][timeout] HOST_TIMEOUT_CTRL write done\n");

    I2C_TIMEOUT_CTRL_reg_u timeout_ctrl = {.val = 0};
    timeout_ctrl.f.val = I2C_CONTROLLER_TIMEOUT_CYCLES;
    timeout_ctrl.f.mode = 1;
    timeout_ctrl.f.en = 1;
    simputshex32("[I2C_CTRL][timeout] TIMEOUT_CTRL write begin: ", timeout_ctrl.val);
    write_i2c_reg(i2c_id, SMC_I2C_WRAP_I2C_0__TIMEOUT_CTRL_REG_OFFSET, timeout_ctrl.val);
    simputs("[I2C_CTRL][timeout] TIMEOUT_CTRL write done\n");
}

static I2C_Status wait_for_host_idle(uint8_t i2c_id, uint32_t timeout) {
    // timeout == 0 means "no timeout" (infinite poll).
    if (timeout == 0) {
        uint32_t spin = 0;
        while (1) {
            I2C_STATUS_reg_u status = {
                .val = read_i2c_reg(i2c_id, SMC_I2C_WRAP_I2C_0__STATUS_REG_OFFSET)};
            if (status.f.hostidle) {
                return I2C_OK;
            }
            if (((++spin) & 0xFFFu) == 0u) {
                simputs("[I2C_CTRL][wait_for_host_idle] polling (no-timeout)...\n");
            }
        }
    }

    uint32_t remaining = timeout;
    while (remaining--) {
        I2C_STATUS_reg_u status = {.val =
                                       read_i2c_reg(i2c_id, SMC_I2C_WRAP_I2C_0__STATUS_REG_OFFSET)};
        if (status.f.hostidle) {
            return I2C_OK;
        }
    }

    simputs("[I2C_CTRL][wait_for_host_idle] TIMEOUT\n");
    return I2C_TIMEOUT;
}

static I2C_Status wait_for_fmt_space(uint8_t i2c_id, uint32_t timeout) {
    // timeout == 0 means "no timeout" (infinite poll).
    if (timeout == 0) {
        uint32_t spin = 0;
        while (1) {
            I2C_STATUS_reg_u status = {
                .val = read_i2c_reg(i2c_id, SMC_I2C_WRAP_I2C_0__STATUS_REG_OFFSET)};
            if (!status.f.fmtfull) {
                I2C_HOST_FIFO_STATUS_reg_u fifo = {
                    .val = read_i2c_reg(i2c_id, SMC_I2C_WRAP_I2C_0__HOST_FIFO_STATUS_REG_OFFSET)};
                if (fifo.f.fmtlvl < I2C_PARAM_FIFO_DEPTH) {
                    return I2C_OK;
                }
            }
            if (((++spin) & 0xFFFu) == 0u) {
                simputs("[I2C_CTRL][wait_for_fmt_space] polling (no-timeout)...\n");
                simputs("STATUS.fmtfull=");
                simputshex16("", status.f.fmtfull);
            }
        }
    }

    uint32_t remaining = timeout;
    uint32_t initial = remaining;
    while (remaining--) {
        I2C_STATUS_reg_u status = {.val =
                                       read_i2c_reg(i2c_id, SMC_I2C_WRAP_I2C_0__STATUS_REG_OFFSET)};
        if (!status.f.fmtfull) {
            I2C_HOST_FIFO_STATUS_reg_u fifo = {
                .val = read_i2c_reg(i2c_id, SMC_I2C_WRAP_I2C_0__HOST_FIFO_STATUS_REG_OFFSET)};
            if (fifo.f.fmtlvl < I2C_PARAM_FIFO_DEPTH) {
                return I2C_OK;
            }
        }

        uint32_t elapsed = initial - remaining;
        if ((elapsed & 0xFFFu) == 0u) {
            simputs("[I2C_CTRL][wait_for_fmt_space] polling...\n");
            simputs("STATUS.fmtfull=");
            simputshex16("", status.f.fmtfull);
        }
    }

    simputs("[I2C_CTRL][wait_for_fmt_space] TIMEOUT\n");
    return I2C_TIMEOUT;
}

static I2C_Status wait_for_rx_level(uint8_t i2c_id, size_t level, uint32_t timeout) {
    // timeout == 0 means "no timeout" (infinite poll).
    if (timeout == 0) {
        uint32_t spin = 0;
        while (1) {
            I2C_HOST_FIFO_STATUS_reg_u fifo = {
                .val = read_i2c_reg(i2c_id, SMC_I2C_WRAP_I2C_0__HOST_FIFO_STATUS_REG_OFFSET)};
            if (fifo.f.rxlvl >= level) {
                return I2C_OK;
            }
            if (((++spin) & 0xFFFu) == 0u) {
                simputs("[I2C_CTRL][wait_for_rx_level] polling (no-timeout)...\n");
                simputs("  HOST_FIFO.rxlvl=");
                simputshex16("", fifo.f.rxlvl);
            }
        }
    }

    uint32_t remaining = timeout;
    uint32_t initial = remaining;
    while (remaining--) {
        I2C_HOST_FIFO_STATUS_reg_u fifo = {
            .val = read_i2c_reg(i2c_id, SMC_I2C_WRAP_I2C_0__HOST_FIFO_STATUS_REG_OFFSET)};
        if (fifo.f.rxlvl >= level) {
            return I2C_OK;
        }

        uint32_t elapsed = initial - remaining;
        if ((elapsed & 0xFFFu) == 0u) {
            simputs("[I2C_CTRL][wait_for_rx_level] polling...\n");
            simputs("  HOST_FIFO.rxlvl=");
            simputshex16("", fifo.f.rxlvl);
        }
    }

    simputs("[I2C_CTRL][wait_for_rx_level] TIMEOUT\n");
    return I2C_TIMEOUT;
}

static uint8_t compose_address_byte(uint8_t target_addr, bool read) {
    return (uint8_t)(((target_addr & 0x7Fu) << 1) | (read ? 1u : 0u));
}

void I2C_release_reset(uint8_t i2c_id) {
    simputs("[I2C_CTRL][I2C_release_reset] enter\n");
    if (!is_valid_controller(i2c_id)) {
        simputs("[I2C_CTRL][I2C_release_reset] invalid controller id\n");
        return;
    }

    I2C_CTRL_I2C_CTRL_reg_u ctrl_gate = {.val = read_reg(kCtrlGateAddrs[i2c_id])};
    ctrl_gate.f.i2c_en = 0;
    ctrl_gate.f.i2c_controller_mode_en = 1;
    write_reg(kCtrlGateAddrs[i2c_id], ctrl_gate.val);

    disable_controller(i2c_id);
    reset_controller_fifos(i2c_id);
    clear_controller_interrupts(i2c_id);

    simputs("[I2C_CTRL][I2C_release_reset] done\n");
}

I2C_Status init_i2c_ctrlr(I2C_Driver *drv, uint8_t i2c_addr) {
    log_simputs("[I2C_CTRL][init_i2c_ctrlr] enter\n");
    if (!drv || !is_valid_controller(drv->ctx.controller_id)) {
        simputs("[I2C_CTRL][init_i2c_ctrlr] invalid args or controller\n");
        return I2C_ERR_HW;
    }

    const uint8_t i2c_id = drv->ctx.controller_id;
    log_simputs("[I2C_CTRL][init_i2c_ctrlr] controller_id=");
    log_simputshex16("", i2c_id);
    log_simputs("[I2C_CTRL][init_i2c_ctrlr] target_addr=");
    log_simputshex16("", i2c_addr);
    I2C_release_reset(i2c_id);
    // i2c_wrapper enable, controller mode
    I2C_CTRL_I2C_CTRL_reg_u ctrl_gate = {.val = read_reg(kCtrlGateAddrs[i2c_id])};
    ctrl_gate.f.i2c_en = 1;
    ctrl_gate.f.i2c_controller_mode_en = 1;
    write_reg(kCtrlGateAddrs[i2c_id], ctrl_gate.val);

    static const i2c_timing_input_t kDefaultTiming = {
        .clock_period_nanos = I2C_CLOCK_PERIOD_NS,
        .scl_period_nanos = I2C_SCL_PERIOD_NS,
        .sda_rise_nanos = I2C_SDA_RISE_NS,
        .sda_fall_nanos = I2C_SDA_FALL_NS,
        .lowest_target_device_speed = kI2cSpeedFast,
    };

    i2c_timing_config_t timing = {0};
    simputs("[I2C_CTRL][init_i2c_ctrlr] DEBUG: I2C_SCL_PERIOD_NS=");
    simputshex32("", I2C_SCL_PERIOD_NS);
    simputs(" I2C_SDA_RISE_NS=");
    simputshex32("", I2C_SDA_RISE_NS);
    simputs(" I2C_SDA_FALL_NS=");
    simputshex32("\n", I2C_SDA_FALL_NS);
    if (!compute_timing(&kDefaultTiming, &timing)) {
        simputs("[I2C_CTRL][init_i2c_ctrlr] compute_timing FAILED\n");
        return I2C_ERR_HW;
    }
    simputs("[I2C_CTRL][init_i2c_ctrlr] DEBUG: computed scl_period_cycles=");
    simputshex32("\n", (uint32_t)((timing.scl_time_high_cycles + timing.scl_time_low_cycles)));
    simputs("[I2C_CTRL][init_i2c_ctrlr] program_controller_timing begin\n");
    program_controller_timing(i2c_id, &timing);
    simputs("[I2C_CTRL][init_i2c_ctrlr] program_controller_timing done\n");

    simputs("[I2C_CTRL][init_i2c_ctrlr] reset_controller_fifos begin\n");
    reset_controller_fifos(i2c_id);
    simputs("[I2C_CTRL][init_i2c_ctrlr] reset_controller_fifos done\n");
    simputs("[I2C_CTRL][init_i2c_ctrlr] configure_threshold begin\n");
    configure_threshold(i2c_id, 0, 0);
    simputs("[I2C_CTRL][init_i2c_ctrlr] configure_threshold done\n");
    simputs("[I2C_CTRL][init_i2c_ctrlr] configure_controller_timeout begin\n");
    configure_controller_timeout(i2c_id);
    simputs("[I2C_CTRL][init_i2c_ctrlr] configure_controller_timeout done\n");

    g_target_addr[i2c_id] = i2c_addr & 0x7Fu;
    simputshex16("[I2C_CTRL][init_i2c_ctrlr] target_addr latched: ", g_target_addr[i2c_id]);
    simputs("[I2C_CTRL][init_i2c_ctrlr] enable_controller begin\n");
    enable_controller(i2c_id);
    simputs("[I2C_CTRL][init_i2c_ctrlr] enable_controller done\n");

    simputs("[I2C_CTRL][init_i2c_ctrlr] exit OK\n");
    return I2C_OK;
}

I2C_Status ctrlr_send_data_w_timeout(I2C_Driver *drv, const uint8_t *tx_buf, size_t tx_buf_len,
                                     int timeout) {

    if (!drv || !drv->ctx.initialized || !is_valid_controller(drv->ctx.controller_id) ||
        tx_buf == NULL) {
        simputs("[I2C_CTRL][TX TIMEOUT] invalid args or controller\n");
        return I2C_ERR_HW;
    }
    uint32_t effective_timeout = (timeout > 0) ? (uint32_t)timeout : I2C_DEFAULT_TIMEOUT;

    if (tx_buf_len == 0) {
        return I2C_TX_BUF_UNDERRUN;
    }

    const uint8_t i2c_id = drv->ctx.controller_id;

    simputs("[I2C_CTRL][TX] LEN==");
    simputshex16("", (uint32_t)tx_buf_len);
    I2C_Status status = wait_for_fmt_space(i2c_id, effective_timeout);
    if (status != I2C_OK) {
        return status;
    }

    I2C_FDATA_reg_u addr_cmd = {.val = 0};
    addr_cmd.f.fbyte = compose_address_byte(g_target_addr[i2c_id], false);
    addr_cmd.f.start = 1;
    addr_cmd.f.stop = (tx_buf_len == 0);
    write_i2c_reg(i2c_id, SMC_I2C_WRAP_I2C_0__FDATA_REG_OFFSET, addr_cmd.val);
    log_simputs("[I2C_CTRL][TX] addr_cmd=");
    log_simputshex16("", addr_cmd.val);

    for (size_t i = 0; i < tx_buf_len; ++i) {
        status = wait_for_fmt_space(i2c_id, effective_timeout);
        if (status != I2C_OK) {
            return status;
        }
        I2C_FDATA_reg_u data_cmd = {.val = 0};
        data_cmd.f.fbyte = tx_buf[i];
        data_cmd.f.stop = (i == tx_buf_len - 1);
        if (data_cmd.f.stop) simputs("[I2C_CTRL][TX] stop bit\n");
        write_i2c_reg(i2c_id, SMC_I2C_WRAP_I2C_0__FDATA_REG_OFFSET, data_cmd.val);
        log_simputs("[I2C_CTRL][TX] data_cmd=");
        log_simputshex16("", data_cmd.val);
    }

    I2C_Status final_status = wait_for_host_idle(i2c_id, effective_timeout);
    if (final_status != I2C_OK) {
        simputs("[I2C_CTRL][TX] wait_for_host_idle TIMEOUT/ERR\n");
    } else {
        simputs("[I2C_CTRL][TX] exit OK\n");
    }
    simputs("[I2C_CTRL][TX] DONE----------\n");
    I2C_HOST_FIFO_STATUS_reg_u fifo_dbg = {
        .val = read_i2c_reg(i2c_id, SMC_I2C_WRAP_I2C_0__HOST_FIFO_STATUS_REG_OFFSET)};
    simputs("fmtlvl=");
    simputshex16("", fifo_dbg.f.fmtlvl);
    simputs("rxlvl=");
    simputshex16("", fifo_dbg.f.rxlvl);

    return final_status;
}

I2C_Status ctrlr_send_data(I2C_Driver *drv, const uint8_t *tx_buf, size_t tx_buf_len) {
    log_simputs("[I2C_CTRL][ctrlr_send_data] enter\n");
    return ctrlr_send_data_w_timeout(drv, tx_buf, tx_buf_len, 0);
}

I2C_Status ctrlr_receive_data_w_timeout(I2C_Driver *drv, uint8_t *rx_buf, size_t rx_buf_len,
                                        size_t *bytes_received, int timeout) {

    simputs("[I2C_CTRL][RX] enter++++++++++\n");

    if (!drv || !drv->ctx.initialized || !is_valid_controller(drv->ctx.controller_id) ||
        rx_buf == NULL) {
        simputs("[I2C_CTRL][RX OUT] invalid args or controller\n");
        if (bytes_received != NULL) {
            *bytes_received = 0;
        }
        return I2C_ERR_HW;
    }

    const uint8_t i2c_id = drv->ctx.controller_id;

    // timeout semantics:
    //  - timeout  < 0 : use default timeout
    //  - timeout == 0 : no timeout (infinite poll)
    //  - timeout  > 0 : timeout in polling iterations
    uint32_t effective_timeout = (timeout < 0) ? I2C_DEFAULT_TIMEOUT : (uint32_t)timeout;

    if (rx_buf_len == 0) {
        if (bytes_received != NULL) {
            *bytes_received = 0;
        }
        return I2C_OK;
    }

    simputs("[I2C_CTRL][RX] LEN==");
    simputshex16("", (uint32_t)rx_buf_len);

    // Ensure there is room in the FMT FIFO before writing address / read commands.
    I2C_Status status = wait_for_fmt_space(i2c_id, effective_timeout);
    if (status != I2C_OK) {
        if (bytes_received != NULL) {
            *bytes_received = 0;
        }
        return status;
    }

    // Address phase: repeated START + 7-bit address with READ bit set.
    I2C_FDATA_reg_u addr_cmd = {.val = 0};
    addr_cmd.f.fbyte = compose_address_byte(g_target_addr[i2c_id], true);
    addr_cmd.f.start = 1;
    // Do not generate STOP here when rx_buf_len > 0: STOP will be handled by the
    // subsequent READ command(s), after all bytes have been received.
    addr_cmd.f.stop = 0;
    write_i2c_reg(i2c_id, SMC_I2C_WRAP_I2C_0__FDATA_REG_OFFSET, addr_cmd.val);
    log_simputs("[I2C_CTRL][RX] addr_cmd=");
    simputshex16("", addr_cmd.val);

    // Issue one or more READ commands that tell the controller how many bytes to read.
    // HW will then clock out the requested bytes and ACK every byte. This helper
    // does not explicitly generate a NACK or a STOP; a higher layer is responsible
    // for terminating the transaction as needed.
    //
    // NOTE: FDATA.FBYTE is only 8 bits, where 0 encodes 256 bytes. For lengths
    // larger than 256, we program multiple READ commands, each requesting up to
    // 256 bytes, until the full rx_buf_len is covered.
    size_t remaining = rx_buf_len;
    size_t received = 0;

    while (remaining > 0) {
        size_t chunk_len = (remaining > 256u) ? 256u : remaining;
        bool is_last_chunk = (remaining <= 256u);

        status = wait_for_fmt_space(i2c_id, effective_timeout);
        if (status != I2C_OK) {
            if (bytes_received != NULL) {
                *bytes_received = 0;
            }
            return status;
        }

        I2C_FDATA_reg_u read_cmd = {.val = 0};
        // 0 encodes 256 bytes in hardware.
        read_cmd.f.fbyte = (uint8_t)(chunk_len & 0xFF);
        read_cmd.f.readb = 1; // "read N bytes" command
        read_cmd.f.rcont = is_last_chunk ? 0 : 1;
        read_cmd.f.stop = 0; // do NOT generate STOP here (higher layer terminates)
        write_i2c_reg(i2c_id, SMC_I2C_WRAP_I2C_0__FDATA_REG_OFFSET, read_cmd.val);

        if (!is_last_chunk) {
            simputs("[I2C_CTRL][RX] remaining=");
            simputshex16("", remaining);
        } else {
            simputs("[I2C_CTRL][RX] last remaining=");
            simputshex16("", remaining);
        }

        log_simputs("[I2C_CTRL][RX] read_cmd=");
        log_simputshex32("", read_cmd.val);
        for (size_t i = 0; i < chunk_len; ++i) {
            status = wait_for_rx_level(i2c_id, 1, effective_timeout);
            if (status != I2C_OK) {
                if (bytes_received != NULL) {
                    *bytes_received = received;
                }
                return status;
            }
            I2C_RDATA_reg_u rdata = {
                .val = read_i2c_reg(i2c_id, SMC_I2C_WRAP_I2C_0__RDATA_REG_OFFSET)};
            log_simputs("[I2C_CTRL][RX] data_byte=");
            log_simputshex16("", (uint32_t)rdata.f.data);
            rx_buf[received++] = (uint8_t)rdata.f.data;
        }

        remaining -= chunk_len;
    }

    log_simputs("[I2C_CTRL][RX] read loop done\n");

    if (bytes_received != NULL) {
        *bytes_received = received;
    }

    log_simputs("[I2C_CTRL][RX] Received bytes: ");
    for (size_t i = 0; i < rx_buf_len; i++) {
        log_simputshex16("", rx_buf[i]);
        log_simputs(" ");
    }
    log_simputs("\n");

    simputs("[I2C_CTRL][RX] DONE-----------\n");

    I2C_HOST_FIFO_STATUS_reg_u fifo_dbg = {
        .val = read_i2c_reg(i2c_id, SMC_I2C_WRAP_I2C_0__HOST_FIFO_STATUS_REG_OFFSET)};
    simputs("fmtlvl=");
    simputshex16("", fifo_dbg.f.fmtlvl);
    simputs("rxlvl=");
    simputshex16("", fifo_dbg.f.rxlvl);

    return I2C_OK;
}

I2C_Status ctrlr_receive_data(I2C_Driver *drv, uint8_t *rx_buf, size_t rx_buf_len,
                              size_t *bytes_received) {
    log_simputs("[I2C_CTRL][ctrlr_receive_data] enter\n");
    return ctrlr_receive_data_w_timeout(drv, rx_buf, rx_buf_len, bytes_received, 0);
}

void wait_for_i2c_target_ready(I2C_Driver *drv) {
    if (!drv || !drv->ctx.initialized) {
        return;
    }
    log_simputs("[I2C_CTRL][wait_for_i2c_target_ready] enter\n");
    (void)wait_for_host_idle(drv->ctx.controller_id, I2C_DEFAULT_TIMEOUT);
}

I2C_Driver *I2C_GetDriverInstance(uint8_t i2c_id) {
    static I2C_Driver i2c_driver_instances[I2C_MAX_CONTROLLERS];
    static bool initialized[I2C_MAX_CONTROLLERS] = {false};

    if (!is_valid_controller(i2c_id)) {
        simputshex16("I2C_GetDriverInstance: Invalid i2c_id\n", i2c_id);
        return NULL;
    }

    I2C_Driver *i2c_driver_instance = &i2c_driver_instances[i2c_id];

    if (!initialized[i2c_id]) {
        simputs("[I2C_CTRL][I2C_GetDriverInstance] init new instance\n");
        i2c_driver_instance->init_i2c_ctrlr = init_i2c_ctrlr;
        i2c_driver_instance->ctrlr_send_data = ctrlr_send_data;
        i2c_driver_instance->ctrlr_send_data_w_timeout = ctrlr_send_data_w_timeout;
        i2c_driver_instance->ctrlr_receive_data = ctrlr_receive_data;
        i2c_driver_instance->ctrlr_receive_data_w_timeout = ctrlr_receive_data_w_timeout;
        i2c_driver_instance->release_reset = I2C_release_reset;
        i2c_driver_instance->ctx.controller_id = i2c_id;
        i2c_driver_instance->ctx.mode = TARGET_I2C_MASTER;
        i2c_driver_instance->ctx.initialized = true;
        initialized[i2c_id] = true;
    } else {
        simputs("[I2C_CTRL][I2C_GetDriverInstance] reuse existing instance\n");
        i2c_driver_instance->ctx.controller_id = i2c_id;
    }

    return i2c_driver_instance;
}
