/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/**
 * @file i2c_target_pmbus_test.c
 * @brief I2C_0 in Target mode running a PMBus register model for an external
 *        I2C controller VIP.
 *
 * Checks that I2C_0 in target mode delivers the PMBus commands and payloads
 * an external controller VIP sends, framed by START and STOP, while firmware
 * keeps a PMBus register model with write protection. The firmware publishes
 * what it acquired so the VIP can compare it against an expectation it stated
 * before driving anything; the I2C block is only the transport under that
 * model. I2C_1 and I2C_2 are disabled because all three instances share one
 * bus in the default build, and a second responder would hide which instance
 * answered.
 *
 * The model implements a PMBus subset (PMBus Power System Mgmt Protocol Spec
 * Part II, Rev 1.3.1, Table 31-1). WRITE_PROTECT either disables all writes
 * except to WRITE_PROTECT itself or enables writes to all commands, so this
 * model rejects CLEAR_FAULTS while protection is on, and the sequence
 * exercises CLEAR_FAULTS only with protection off.
 *
 * scratch[2] is the virtual console (simputs) and must not be reused here;
 * publish() defines the record layout the VIP reads.
 */

#include <stdint.h>
#include <stdbool.h>

#include "smc_io.h"
#include "smc_test.h"
#include "i2c_opentitan.h"

//=============================================================================
// Test constants
//=============================================================================

#define TARGET_IDX 0u
#define TARGET_ADDR 0x40u /* PMBus device address used by the VIP */

/* PMBus command codes -- PMBus Part II Rev 1.3.1, Table 31-1. */
#define PMBUS_CMD_CLEAR_FAULTS 0x03u
#define PMBUS_CMD_WRITE_PROTECT 0x10u
#define PMBUS_CMD_VOUT_COMMAND 0x21u
#define PMBUS_CMD_STATUS_BYTE 0x78u
#define PMBUS_CMD_MFR_SPECIFIC_00 0xD0u

/* WRITE_PROTECT data byte values -- PMBus Part II Rev 1.3.1, WRITE_PROTECT. */
#define PMBUS_WP_ALL_BUT_WP 0x80u
#define PMBUS_WP_NONE 0x00u

/* Power-on image of the model. The VIP states these values as its
 * expectations, so they are part of the contract with it. No byte lane is
 * all-zeros or all-ones, so reading them back cannot come from an undriven
 * bus and shows the byte came from this target. */
#define PMBUS_WRITE_PROTECT_RESET 0x80u
#define PMBUS_VOUT_COMMAND_RESET 0x3C5Au
#define PMBUS_STATUS_BYTE_RESET 0x02u /* CML bit preset so CLEAR_FAULTS is observable */

/* Service-loop bound, in iterations. The loop spins for the whole VIP
 * sequence, about 120000 iterations; this bound is about 16x that, so a hang
 * ends in a diagnostic rather than a harness kill. The VIP bounds each
 * operation more tightly, so this is a backstop. */
#define PMBUS_SERVICE_BOUND (10u * I2C_TIMEOUT_DEFAULT)

/* Largest number of acquired data bytes one transaction can carry here:
 * command + two payload bytes for a Write Word. Anything longer is a protocol
 * error and is reported, not silently truncated. */
#define PMBUS_MAX_XACT_BYTES 4u

//=============================================================================
// Model state
//=============================================================================

static uint8_t g_write_protect = PMBUS_WRITE_PROTECT_RESET;
static uint16_t g_vout_command = PMBUS_VOUT_COMMAND_RESET;
static uint8_t g_status_byte = PMBUS_STATUS_BYTE_RESET;

static uint32_t g_accepted_writes;
static uint32_t g_blocked_writes;
static uint32_t g_clear_faults;

static uint32_t g_txn_count;
static uint32_t g_total_data_bytes;
static uint32_t g_stop_detect_count;
static uint32_t g_events_sticky;

static bool g_end_of_test;

//=============================================================================
// Register plumbing
//=============================================================================

static uint32_t i2c_off(uint32_t abs_base_for_idx0) {
    return abs_base_for_idx0 - SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0);
}

static uint32_t tgt_base(void) {
    return i2c_get_base(TARGET_IDX);
}

static void i2c_wrapper_set(uint32_t idx, bool enable, bool controller_mode) {
    uint32_t wrapper_addr = SMC_TOP_SMC_I2C_WRAP_I2C_CTRL_REGS_I2C_CTRL_BASE_ADDR(idx);
    i2c_ctrl__I2C_CTRL_t ctrl = {.w = 0};

    ctrl.f.I2C_EN = enable ? 1 : 0;
    ctrl.f.I2C_CONTROLLER_MODE_EN = (enable && controller_mode) ? 1 : 0;
    write_reg(wrapper_addr, ctrl.w);
}

/* Report a failure and stop. */
__attribute__((noreturn)) static void fail_with(uint32_t code, const char *msg) {
    simputs("  ERROR: ");
    simputs(msg);
    simputs("\n");
    simputshex32("  code=", code);
    write_scratch(0, code);
    test_fail(0);
}

/* Push one byte into the Target TX FIFO.
 *
 * Not i2c_target_transmit(): its optional driver trace writes markers into
 * scratch[1], which is this test's handshake channel with the VIP. */
static void tx_push(uint8_t b) {
    i2c__TXDATA_t txdata = {.w = 0};
    txdata.f.DATA = b;
    write_reg(tgt_base() + i2c_off(SMC_TOP_SMC_I2C_WRAP_I2C_TXDATA_BASE_ADDR(0)), txdata.w);
}

//=============================================================================
// Observation publishing
//=============================================================================

static uint32_t pack_framing(uint8_t start_sig, uint8_t addr_byte, uint8_t stop_sig,
                             uint32_t n_data) {
    return ((uint32_t)start_sig << 24) | ((uint32_t)addr_byte << 16) | ((uint32_t)stop_sig << 8) |
           (n_data & 0xFFu);
}

static uint32_t pack_bytes(const uint8_t *buf, uint32_t n) {
    uint32_t w = 0;
    uint32_t i;
    for (i = 0; i < n && i < 4u; i++) {
        w |= ((uint32_t)buf[i]) << (8u * i);
    }
    return w;
}

/* Publish the record of the transaction that just ended. scratch[3] is written
 * last and is the only field the reader polls, so every other field is already
 * settled by the time the counter it sees has advanced. */
static void publish(uint32_t framing_any, bool data_bearing, uint32_t framing_data,
                    uint32_t bytes_word) {
    if (data_bearing) {
        write_scratch(4, framing_data);
        write_scratch(5, bytes_word);
    }
    write_scratch(6, ((uint32_t)g_write_protect << 24) | ((uint32_t)g_status_byte << 16) |
                         (uint32_t)g_vout_command);
    write_scratch(7, ((g_clear_faults & 0xFFu) << 16) | ((g_blocked_writes & 0xFFu) << 8) |
                         (g_accepted_writes & 0xFFu));
    write_scratch(8, g_total_data_bytes);
    write_scratch(9, framing_any);
    write_scratch(10, ((g_stop_detect_count & 0xFFFFu) << 16) | (g_events_sticky & 0xFFFFu));
    write_scratch(3, g_txn_count);
}

//=============================================================================
// PMBus model
//=============================================================================

/* A transaction that carried the command code and nothing else. In PMBus that
 * is either a Send Byte (executes now, no readback) or the command phase that
 * selects which register the Read transfer immediately after it will fetch. */
static void handle_command_phase(uint8_t cmd) {
    if (cmd == PMBUS_CMD_CLEAR_FAULTS) {
        /* Send Byte: subject to WRITE_PROTECT like any other write. */
        if (g_write_protect != PMBUS_WP_NONE) {
            g_blocked_writes++;
        } else {
            g_status_byte = 0x00u;
            g_clear_faults++;
            g_accepted_writes++;
        }
        return;
    }

    /* Stage the response bytes for the Read that follows. The TX FIFO is reset
     * first so a transfer that ended early cannot leave a stale byte in front
     * of this answer. */
    i2c_reset_fifos(TARGET_IDX, false, false, true, false);

    switch (cmd) {
    case PMBUS_CMD_WRITE_PROTECT:
        tx_push(g_write_protect);
        break;
    case PMBUS_CMD_STATUS_BYTE:
        tx_push(g_status_byte);
        break;
    case PMBUS_CMD_VOUT_COMMAND:
        tx_push((uint8_t)(g_vout_command & 0xFFu));        /* LSB first */
        tx_push((uint8_t)((g_vout_command >> 8) & 0xFFu)); /* then MSB */
        break;
    default:
        /* Unsupported command code. Stage one byte so an unexpected read
         * cannot stretch SCL forever, and record it as a rejected access. */
        g_blocked_writes++;
        tx_push(0xFFu);
        break;
    }
}

/* Apply a PMBus write. buf[0] is the command code, buf[1..] the payload. */
static void apply_write(const uint8_t *buf, uint32_t n) {
    uint8_t cmd = buf[0];
    uint32_t payload = n - 1u;

    switch (cmd) {
    case PMBUS_CMD_WRITE_PROTECT:
        /* WRITE_PROTECT is writable under every WRITE_PROTECT encoding,
         * including 0x80 -- that is what "except to the WRITE_PROTECT command"
         * means in the specification. */
        if (payload != 1u) {
            fail_with(0xBAD00060, "WRITE_PROTECT wrong payload length");
        }
        g_write_protect = buf[1];
        g_accepted_writes++;
        break;

    case PMBUS_CMD_VOUT_COMMAND:
        if (payload != 2u) {
            fail_with(0xBAD00061, "VOUT_COMMAND wrong payload length");
        }
        if (g_write_protect != PMBUS_WP_NONE) {
            g_blocked_writes++; /* protected: the image must not move */
        } else {
            g_vout_command = (uint16_t)(buf[1] | ((uint16_t)buf[2] << 8));
            g_accepted_writes++;
        }
        break;

    case PMBUS_CMD_MFR_SPECIFIC_00:
        /* Vendor sentinel: the VIP has finished its sequence. */
        g_end_of_test = true;
        break;

    default:
        g_blocked_writes++;
        break;
    }
}

//=============================================================================
// ACQ FIFO service loop
//=============================================================================

static bool acq_has_data(void) {
    i2c__STATUS_t st = {
        .w = read_reg(tgt_base() + i2c_off(SMC_TOP_SMC_I2C_WRAP_I2C_STATUS_BASE_ADDR(0)))};
    return st.f.ACQEMPTY ? false : true;
}

/* Snapshot TARGET_EVENTS, fold it into the sticky record, then clear it.
 *
 * An unhandled target event makes the target FSM stretch SCL on the next read,
 * so a pending START_DETECT or STOP_DETECT holds the bus until it is cleared. */
static void service_events(void) {
    i2c__TARGET_EVENTS_t ev = {.w = i2c_get_target_events(TARGET_IDX)};

    if (ev.w == 0u) {
        return;
    }
    g_events_sticky |= ev.w;
    if (ev.f.STOP_DETECT) {
        g_stop_detect_count++;
    }
    if (ev.f.BUS_TIMEOUT) {
        fail_with(0xBAD00070, "TARGET_EVENTS.BUS_TIMEOUT");
    }
    if (ev.f.ARBITRATION_LOST) {
        fail_with(0xBAD00071, "TARGET_EVENTS.ARBITRATION_LOST");
    }
    i2c_clear_target_events(TARGET_IDX, ev.w);
}

static void run_pmbus_target(void) {
    uint8_t buf[PMBUS_MAX_XACT_BYTES];
    uint32_t n_data = 0;
    uint8_t start_sig = 0;
    uint8_t addr_byte = 0;
    bool in_xact = false;
    bool overrun = false;
    uint32_t iter;

    for (iter = 0; iter < PMBUS_SERVICE_BOUND; iter++) {
        i2c_acq_entry_t e;

        service_events();

        if (!acq_has_data()) {
            if (g_end_of_test) {
                return;
            }
            continue;
        }
        if (i2c_target_receive_entry(TARGET_IDX, &e) != I2C_OK) {
            continue;
        }

        switch (e.signal) {
        case I2C_ACQ_SIGNAL_START:
        case I2C_ACQ_SIGNAL_RESTART:
            in_xact = true;
            overrun = false;
            n_data = 0;
            start_sig = e.signal;
            addr_byte = e.data;
            if ((addr_byte >> 1) != TARGET_ADDR) {
                fail_with(0xBAD00072, "ACQ START for a foreign address");
            }
            break;

        case I2C_ACQ_SIGNAL_DATA:
            if (!in_xact) {
                fail_with(0xBAD00073, "ACQ DATA outside a transaction");
            }
            if (n_data < PMBUS_MAX_XACT_BYTES) {
                buf[n_data] = e.data;
            } else {
                overrun = true;
            }
            n_data++;
            g_total_data_bytes++;
            break;

        case I2C_ACQ_SIGNAL_STOP:
        case I2C_ACQ_SIGNAL_NACK_STOP: {
            uint32_t framing;
            bool data_bearing;
            uint32_t bytes_word;

            if (!in_xact) {
                /* STOP with no preceding START for us: ignore rather than
                 * mis-attribute it to the previous transaction. */
                break;
            }
            if (overrun) {
                fail_with(0xBAD00074, "transaction longer than the PMBus model accepts");
            }

            framing = pack_framing(start_sig, addr_byte, e.signal, n_data);
            data_bearing = (n_data > 0u);
            bytes_word = pack_bytes(buf, n_data);

            if ((addr_byte & 0x01u) == 0u) {
                /* Write direction. One data byte is a command with no payload:
                 * either a Send Byte, or the command phase that selects the
                 * register the next Read transfer will fetch. Two or more is a
                 * Write Byte / Write Word. */
                if (n_data == 1u) {
                    handle_command_phase(buf[0]);
                } else if (n_data >= 2u) {
                    apply_write(buf, n_data);
                }
            }
            /* Read direction needs nothing here: the response bytes were
             * staged when the command phase ended, and the target clock-
             * stretched until they were. */

            /* Fold in this transaction's TARGET_EVENTS before publishing it.
             * The STOP sets STOP_DETECT in the same cycle it writes the ACQ
             * STOP entry, which can be after this iteration's top-of-loop
             * sample. Sampling again here keeps stop_detect_count equal to
             * txn_count in every published record. */
            service_events();

            g_txn_count++;
            in_xact = false;
            publish(framing, data_bearing, framing, bytes_word);

            if (g_end_of_test) {
                return;
            }
            break;
        }

        case I2C_ACQ_SIGNAL_NACK:
        case I2C_ACQ_SIGNAL_NACK_START:
            fail_with(0xBAD00075, "target NACKed a byte the VIP sent");

        default:
            fail_with(0xBAD00076, "unknown ACQ signal");
        }
    }

    simputshex32("  TIMEOUT_DIAG bound=", PMBUS_SERVICE_BOUND);
    simputshex32("  TIMEOUT_DIAG txn_count=", g_txn_count);
    simputshex32("  TIMEOUT_DIAG data_bytes=", g_total_data_bytes);
    simputshex32("  TIMEOUT_DIAG STATUS=",
                 read_reg(tgt_base() + i2c_off(SMC_TOP_SMC_I2C_WRAP_I2C_STATUS_BASE_ADDR(0))));
    simputshex32("  TIMEOUT_DIAG TARGET_EVENTS_sticky=", g_events_sticky);
    fail_with(0xBAD00077, "service loop bound expired before end-of-test sentinel");
}

//=============================================================================
// Firmware-side final judgement
//=============================================================================

/* Checks the VIP cannot fake, because they are counters this firmware
 * incremented while enforcing its own model. */
static void check_final_state(void) {
    if (g_clear_faults != 1u) {
        fail_with(0xBAD00080, "CLEAR_FAULTS was not accepted exactly once");
    }
    if (g_status_byte != 0x00u) {
        fail_with(0xBAD00081, "STATUS_BYTE not cleared by CLEAR_FAULTS");
    }
    if (g_blocked_writes != 2u) {
        fail_with(0xBAD00082, "protected VOUT_COMMAND writes not rejected exactly twice");
    }
    if (g_write_protect != PMBUS_WP_ALL_BUT_WP) {
        fail_with(0xBAD00083, "WRITE_PROTECT not back at 0x80 at end of sequence");
    }
    if (g_vout_command == PMBUS_VOUT_COMMAND_RESET) {
        fail_with(0xBAD00084, "VOUT_COMMAND never changed: no unprotected write took effect");
    }
    if (g_stop_detect_count == 0u) {
        fail_with(0xBAD00085, "TARGET_EVENTS.STOP_DETECT never asserted");
    }
    if (g_total_data_bytes == 0u) {
        fail_with(0xBAD00086, "no data byte was ever acquired");
    }
}

//=============================================================================
// Main
//=============================================================================

int main(void) {
    int ret;
    i2c_timing_physical_t physical_params = {.speed = I2C_SPEED_STANDARD,
                                             .clock_period_nanos = 5, /* 200 MHz peripheral clock */
                                             .sda_rise_nanos = 300,
                                             .sda_fall_nanos = 100,
                                             .scl_period_nanos = 0};
    i2c_timing_config_t timing;
    i2c_target_config_t tgt_cfg;
    i2c__CTRL_t tctrl;

    simputs("\n");
    simputs("################################################\n");
    simputs("##   I2C Target PMBus Protect Write/Read     ##\n");
    simputs("##   (external cocotb I2cMaster VIP)         ##\n");
    simputs("################################################\n");

    write_scratch(1, 0x00000010);

    if (TARGET_ADDR < 0x08u || TARGET_ADDR > 0x77u) {
        fail_with(0xBAD00030, "target address outside the legal 7-bit range");
    }

    //-------------------------------------------------------------------------
    // LEVEL 1: wrapper. Only I2C_0 may drive the shared pads.
    //-------------------------------------------------------------------------
    write_scratch(1, 0x00000020);
    i2c_wrapper_set(0, false, true);
    i2c_wrapper_set(1, false, true);
    i2c_wrapper_set(2, false, true);
    i2c_wrapper_set(TARGET_IDX, true, false);
    simputs("Wrapper: I2C_0 Target enabled, I2C_1/I2C_2 disabled\n");
    write_scratch(1, 0x00000021);

    //-------------------------------------------------------------------------
    // LEVEL 2: I2C IP as Target at 0x40.
    //-------------------------------------------------------------------------
    write_scratch(1, 0x00000030);

    ret = i2c_compute_timing_from_physical(&physical_params, &timing);
    if (ret != I2C_OK) {
        i2c_get_default_timing(I2C_SPEED_STANDARD, 100, &timing);
    }

    tgt_cfg.address0 = TARGET_ADDR;
    tgt_cfg.mask0 = 0x7F; /* exact match */
    tgt_cfg.address1 = 0;
    tgt_cfg.mask1 = 0;
    tgt_cfg.timing = timing;
    tgt_cfg.fifo.tx_thresh = 1; /* drain TX FIFO to the FSM as soon as it has a byte */
    tgt_cfg.fifo.acq_thresh = I2C_DEFAULT_ACQ_THRESH;
    tgt_cfg.fifo.rx_thresh = 0;
    tgt_cfg.fifo.fmt_thresh = 0;
    tgt_cfg.enable_interrupts = false;
    tgt_cfg.ack_ctrl_mode = false;
    tgt_cfg.tx_stretch_ctrl = false; /* FSM releases on its own once TX has data */
    tgt_cfg.timeout_cycles = 0;

    if (i2c_target_init(TARGET_IDX, &tgt_cfg) != I2C_OK) {
        fail_with(0xBAD00031, "target init failed");
    }

    /* START/STOP must land in the ACQ FIFO: the transaction framing this test
     * publishes, and the STOP the VIP checks, come from those entries. */
    tctrl.w = read_reg(tgt_base() + i2c_off(SMC_TOP_SMC_I2C_WRAP_I2C_CTRL_BASE_ADDR(0)));
    tctrl.f.ACQ_START_STOP_EN = 1;
    write_reg(tgt_base() + i2c_off(SMC_TOP_SMC_I2C_WRAP_I2C_CTRL_BASE_ADDR(0)), tctrl.w);

    i2c_reset_fifos(TARGET_IDX, false, false, true, true);
    i2c_clear_target_events(TARGET_IDX, 0xFFFFFFFFu);

    /* Publish the reset image before announcing the target is live, so the
     * first thing the VIP can read is already consistent. */
    publish(0u, false, 0u, 0u);

    simputshex32("Target live at address 0x", TARGET_ADDR);
    write_scratch(1, 0x00000031);

    //-------------------------------------------------------------------------
    // Setup complete; hand the bus to the VIP.
    //-------------------------------------------------------------------------
    write_scratch(1, 0xEBEDEBE2);
    simputs("Setup complete - servicing PMBus transactions\n");

    run_pmbus_target();
    check_final_state();

    simputs("\n");
    simputs("Summary:\n");
    simputshex32("  transactions acquired: ", g_txn_count);
    simputshex32("  data bytes acquired:   ", g_total_data_bytes);
    simputshex32("  accepted writes:       ", g_accepted_writes);
    simputshex32("  blocked writes:        ", g_blocked_writes);
    simputshex32("  clear_faults:          ", g_clear_faults);
    simputshex32("  stop_detect events:    ", g_stop_detect_count);
    simputshex32("  final WRITE_PROTECT:   ", g_write_protect);
    simputshex32("  final VOUT_COMMAND:    ", g_vout_command);
    simputshex32("  final STATUS_BYTE:     ", g_status_byte);

    i2c_target_disable(TARGET_IDX);
    i2c_wrapper_set(TARGET_IDX, false, false);

    write_scratch(1, 0xEBEDEBE4);
    simputs("\n################################################\n");
    simputs("##           TEST PASSED                     ##\n");
    simputs("################################################\n");
    test_pass(0);
}
