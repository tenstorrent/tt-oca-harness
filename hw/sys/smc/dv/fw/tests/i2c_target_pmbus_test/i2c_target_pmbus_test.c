/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/**
 * @file i2c_target_pmbus_test.c
 * @brief I2C_0 in Target mode running a PMBus register model for an external
 *        cocotb I2cMaster VIP (tb_wrap_cocotb/tests/smc_i2c_target_pmbus.py).
 *
 * =============================================================================
 * Why this file exists
 * =============================================================================
 *
 * Every property the cocotb half judges -- WRITE_PROTECT storage, protection
 * enforcement on VOUT_COMMAND, STATUS_BYTE clearing on CLEAR_FAULTS -- is
 * firmware state, not RTL state. The I2C block is only the transport
 * underneath. This file is that firmware: it services the Target ACQ FIFO byte
 * by byte, maintains the PMBus register image in software, and publishes what
 * it actually acquired so the VIP can compare the received command and payload
 * against an expectation it stated before driving anything.
 *
 * =============================================================================
 * Bus configuration
 * =============================================================================
 *
 * I2C_0 wrapper = Target mode, 7-bit address 0x40. The wrappers of I2C_1 and
 * I2C_2 are explicitly disabled first: in the default (shared-bus) compile
 * BP_GPIO[37]/[41]/[45] all tie to one i2c_scl and BP_GPIO[38]/[42]/[46] to one
 * i2c_sda, so leaving another instance enabled would put a second responder on
 * the same wire and make "who answered" unanswerable. With only I2C_0 enabled,
 * and with this firmware reading I2C_0's *own* ACQ FIFO, the instance identity
 * the log claims is measured rather than assumed.
 *
 * =============================================================================
 * PMBus subset implemented (PMBus Power System Mgmt Protocol Spec Part II,
 * Rev 1.3.1, Section 31 "Command Summary", Table 31-1)
 * =============================================================================
 *
 *   0x03 CLEAR_FAULTS   Send Byte  -- clears STATUS_BYTE
 *   0x10 WRITE_PROTECT  R/W Byte   -- protection control
 *   0x21 VOUT_COMMAND   R/W Word   -- LSB first on the wire
 *   0x78 STATUS_BYTE    Read Byte  -- fault summary
 *   0xD0 MFR_SPECIFIC_00           -- vendor sentinel, ends this test
 *
 * WRITE_PROTECT data-byte semantics, same specification, WRITE_PROTECT command
 * description:
 *   0x80 = disable all writes except to the WRITE_PROTECT command
 *   0x00 = enable writes to all commands
 *
 * Note on CLEAR_FAULTS: the 0x80 encoding above disables *all* writes other
 * than WRITE_PROTECT itself, so this model rejects CLEAR_FAULTS while
 * protection is on rather than treating it as an exemption. Whether this
 * device is meant to exempt CLEAR_FAULTS is a design decision; until it is
 * ruled on, the sequence only exercises CLEAR_FAULTS with protection off, so
 * neither reading is asserted.
 *
 * =============================================================================
 * Scratch protocol with the cocotb half
 * =============================================================================
 *
 * scratch[2] is the virtual console (simputs) and must not be reused here.
 *
 *   [0]  test status: TEST_PASS / TEST_FAIL / 0xBADxxxxx error code
 *   [1]  handshake: 0x00000031 target live -> 0xEBEDEBE2 setup done
 *                   -> 0xEBEDEBE4 test complete
 *   [3]  transaction counter -- number of STOP-framed transactions acquired.
 *        WRITTEN LAST, so a reader that sees this advance may trust [4]..[10].
 *   [4]  last DATA-BEARING transaction framing:
 *          (start_signal << 24) | (address_byte << 16) | (stop_signal << 8) | n_data
 *   [5]  that transaction's first four acquired data bytes, little-endian
 *        (byte 0 is the PMBus command code)
 *   [6]  model image: (WRITE_PROTECT << 24) | (STATUS_BYTE << 16) | VOUT_COMMAND
 *   [7]  (clear_faults_count << 16) | (blocked_write_count << 8) | accepted_write_count
 *   [8]  total ACQ data bytes acquired since target enable
 *   [9]  last transaction framing, data-bearing or not (same packing as [4])
 *   [10] (stop_detect_count << 16) | (sticky TARGET_EVENTS & 0xFFFF)
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

/* Power-on image of the model. These are the values the cocotb half states as
 * its expectations before it drives a single bit, so they are part of the
 * contract, not an implementation detail.
 *
 * None of them is 0x00 or 0xFF on any byte lane. That is deliberate: on this
 * testbench the VIP samples SDA on the same handle it drives, and both a bus
 * nobody drives and a bus the VIP itself last deposited on read back as all-
 * ones (pull-up) or, with COCOTB_RESOLVE_X=ZEROS, as all-zeros. A readback of
 * 0x3C5A or 0x02 cannot be produced by either, so it is a positive control
 * that the byte came from this target. */
#define PMBUS_WRITE_PROTECT_RESET 0x80u
#define PMBUS_VOUT_COMMAND_RESET 0x3C5Au
#define PMBUS_STATUS_BYTE_RESET 0x02u /* CML bit preset so CLEAR_FAULTS is observable */

/* Service-loop bound, in iterations.
 *
 * Derivation, not a guess. The VIP sequence is ~60 bytes on a 100 kHz bus,
 * i.e. ~6 ms of bus time end to end, and this loop spins for the whole of it
 * because the target clock-stretches rather than dropping bytes. One iteration
 * is two register reads, so it costs on the order of 50 ns of simulation --
 * about 120000 iterations to cover the sequence. 2000000 is ~16x that and
 * still finite, so a hang ends in a diagnostic rather than running until the
 * harness kills it. The cocotb half bounds each operation far tighter (see
 * PMBUS_OP_TIMEOUT_NS there), so in practice this is the backstop, not the
 * first thing to fire. */
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

/* Report a failure and stop. This must not return: test_fail() only writes
 * TEST_FAIL into scratch[0], so a fail_with() that fell through would let main
 * carry on and overwrite it with TEST_PASS at the end -- a real failure turned
 * into a green run. Parking in WFI leaves TEST_FAIL standing for
 * monitor_test(), and the 0xBADxxxxx cause on the console. */
__attribute__((noreturn)) static void fail_with(uint32_t code, const char *msg) {
    simputs("  ERROR: ");
    simputs(msg);
    simputs("\n");
    simputshex32("  code=", code);
    write_scratch(0, code);
    test_fail(0);
    while (true) {
        __asm__("wfi");
    }
}

/* Push one byte into the Target TX FIFO.
 *
 * Deliberately not i2c_target_transmit(): that driver helper writes debug
 * markers 0x80..0x85 into scratch[1], which is this test's handshake channel
 * with the cocotb half. Calling it mid-run would corrupt the handshake. */
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
        /* Send Byte. Subject to WRITE_PROTECT like any other write; see the
         * note in the file header about why no exemption is assumed. */
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
            return;
        }
        g_write_protect = buf[1];
        g_accepted_writes++;
        break;

    case PMBUS_CMD_VOUT_COMMAND:
        if (payload != 2u) {
            fail_with(0xBAD00061, "VOUT_COMMAND wrong payload length");
            return;
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
 * Clearing is not housekeeping: i2c_core.sv:1098 feeds TARGET_EVENTS.intr into
 * the target FSM's unhandled_tx_stretch_event, and i2c_target_fsm.sv:677 ORs
 * that into stretch_tx. A pending START_DETECT or STOP_DETECT therefore holds
 * SCL low on the next read until software acknowledges it. */
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
        return;
    }
    if (ev.f.ARBITRATION_LOST) {
        fail_with(0xBAD00071, "TARGET_EVENTS.ARBITRATION_LOST");
        return;
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
                return;
            }
            break;

        case I2C_ACQ_SIGNAL_DATA:
            if (!in_xact) {
                fail_with(0xBAD00073, "ACQ DATA outside a transaction");
                return;
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
                return;
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

            /* Fold in THIS transaction's TARGET_EVENTS before publishing it.
             *
             * service_events() otherwise only runs at the top of the loop,
             * while the STOP entry is popped further down the same iteration.
             * The STOP that ends this transaction sets TARGET_EVENTS.STOP_DETECT
             * in the same RTL cycle that writes the ACQ STOP entry
             * (i2c_core.sv:673,1096), so by the time that entry has been read
             * back over APB the bit is certainly set -- but the top-of-loop
             * sample for this iteration already happened before the pop. Without
             * this call the record published for transaction N carries the
             * stop-detect count as of N-1 whenever the pop lands in the same
             * iteration as the STOP, which is intermittent: an observed run had
             * transaction 6 publish 6 and transaction 7 publish 6.
             *
             * With it, every published record is internally consistent --
             * stop_detect_count equals txn_count -- which is what lets the
             * cocotb half assert the exact equality instead of a weaker
             * "advanced since last time". */
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
            return;

        default:
            fail_with(0xBAD00076, "unknown ACQ signal");
            return;
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
                                             .clock_period_nanos = 10, /* 100 MHz */
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

    while (true) {
        __asm__("wfi");
    }

    return 0;
}
