/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/**
 * @file i2c_p1_fifo_depth_xfer.c
 * @brief I2C full-FIFO-depth transfer with an interleaved push-and-drain
 *
 * =============================================================================
 * Test Description
 * =============================================================================
 *
 * Moves a 64-byte payload -- the full FIFO depth, where every other I2C test in
 * this suite moves 1 to 5 bytes -- as one write frame, with the controller
 * pushing while the target drains, then compares length and every byte.
 *
 * No DMA is involved; the CPU feeds the FMT FIFO one entry at a time.
 *
 * Test Objective:
 * - Verify I2C can perform a full-FIFO-depth data transfer
 * - Verify data integrity when push and drain overlap
 * - Verify I2C protocol remains valid throughout transfer
 *
 * Expected Result:
 * - The transfer completes and every byte matches
 * - I2C protocol compliance throughout transfer
 *
 * =============================================================================
 */

#include <stdint.h>
#include <stdbool.h>

#include "smc_io.h"
#include "smc_test.h"
#include "i2c_opentitan.h"

#define CONTROLLER_IDX 0
#define TARGET_IDX 1
#define TARGET_ADDR 0x10
#define LARGE_DATA_SIZE 64

#define I2C_REG(idx, REG) (SMC_TOP_SMC_I2C_WRAP_I2C_##REG##_BASE_ADDR(idx))

/* Polls of the controller allowed for one FMT entry to leave the FIFO. A
 * standard-mode byte with its acknowledge occupies the wire for nine SCL
 * periods, about 90 us; a poll is a few hundred nanoseconds, so this is well
 * over ten byte-times at any clk_smc_i period the bench draws. */
#define FMT_ROOM_POLL_BOUND 20000u

/* Polls of the target's ACQ level after the last byte before a short transfer
 * is declared. */
#define TRAILING_DRAIN_POLL_BOUND 200000u

static void i2c_wrapper_enable(uint32_t idx, bool controller_mode) {
    uint32_t wrapper_addr = SMC_TOP_SMC_I2C_WRAP_I2C_CTRL_REGS_I2C_CTRL_BASE_ADDR(idx);

    i2c_ctrl__I2C_CTRL_t ctrl = {.w = 0};
    ctrl.f.I2C_EN = 1;
    ctrl.f.I2C_CONTROLLER_MODE_EN = controller_mode ? 1 : 0;

    write_reg(wrapper_addr, ctrl.w);
}

/* Drain every ACQ entry the target currently holds, appending payload to rx.
 *
 * Classification is by ACQ SIGNAL, deliberately, not by the driver's decoded
 * is_start / is_stop booleans. i2c_target_receive_entry maps the two NACK
 * signals I2C_ACQ_SIGNAL_NACK (4) and I2C_ACQ_SIGNAL_NACK_START (5) onto its
 * `default` leg (i2c_opentitan.c:1638-1642), which clears both booleans -- so a
 * filter written as `if (e.is_start || e.is_stop) continue;` accepts a byte the
 * target NACKed as a good payload byte and feeds it to the comparison. This
 * test asserts "I2C protocol remains valid throughout transfer", so any NACK or
 * NACK_STOP entry has to fail it rather than be laundered into rx.
 *
 * Returns I2C_OK, or an error the caller must propagate to test_fail.
 */
static int drain_acq(uint32_t tgt_idx, uint8_t *rx, uint32_t rx_size, uint32_t *got) {
    while (!i2c_target_acq_fifo_empty(tgt_idx)) {
        i2c_acq_entry_t e;
        if (i2c_target_receive_entry(tgt_idx, &e) != I2C_OK) {
            break; /* FIFO emptied between the poll and the read */
        }
        if (e.signal == I2C_ACQ_SIGNAL_START || e.signal == I2C_ACQ_SIGNAL_RESTART ||
            e.signal == I2C_ACQ_SIGNAL_STOP) {
            continue; /* framing, not payload */
        }
        if (e.signal != I2C_ACQ_SIGNAL_DATA) {
            simputs("  ERROR: target recorded a protocol-error ACQ entry, signal 0x");
            simputshex32("", e.signal);
            simputs(", data 0x");
            simputshex32("", e.data);
            simputs(", at payload index 0x");
            simputshex32("", *got);
            simputs("\n");
            return I2C_ERROR;
        }
        if (*got >= rx_size) {
            simputs("  ERROR: receive buffer overflow\n");
            return I2C_ERROR_OVERFLOW;
        }
        rx[(*got)++] = e.data;
    }
    return I2C_OK;
}

/* Interleaved push and drain: the transfer this test is named for cannot work
 * any other way on a single-threaded CPU.
 *
 * The target stretches SCL as soon as its ACQ FIFO has 2 or fewer free entries
 * (i2c_target_fsm.sv:271 `acq_fifo_plenty_space = remainder > 2`, :674
 * `stretch_rx = !acq_fifo_plenty_space || !can_auto_ack`, whose second term is
 * inactive here because ACK_CTRL mode is off), which with
 * smc_config_pkg::I2C_TARGET_RX_FIFO_DEPTH = 64 means it stretches at ACQ depth
 * 62. That is documented, intended flow control: the RDL describes the
 * ACQ_STRETCH interrupt as asserted "while the target is stretching the clock
 * because the Target RX FIFO is full" (i2c.rdl:116-122).
 *
 * Queueing all 64 bytes and only then waiting for the controller cannot
 * complete: nothing drains the target in between, so the target stretches at
 * the 62-entry threshold, the controller can never retire its FMT entries, and
 * the wait burns its whole budget with the bus still not idle. That is flow
 * control, not an RTL defect.
 *
 * So the payload goes out as one write frame -- START, address, 64 data
 * bytes, STOP -- fed to the FMT FIFO one entry at a time. Before each push the
 * CPU waits until at most one entry is left in the FMT FIFO (the byte on the
 * wire) and drains whatever the target has accepted while it waits. That keeps
 * the bus streaming without an SCL-low gap between bytes and keeps ACQ far
 * below the stretch threshold. Bytes are collected here rather than by a
 * separate receive call, because a blocking receive cannot run while this same
 * CPU has to keep pushing.
 *
 * The frame is written to FDATA directly rather than through
 * i2c_controller_write: that call emits a whole START..data frame per
 * invocation and returns only once the FMT FIFO is empty, so a payload fed
 * through it byte by byte is 64 frames, each with its own START and address
 * byte -- twice the bus time of the payload itself.
 */
static int wait_fmt_room(uint32_t ctrl_idx, uint32_t tgt_idx, uint8_t *rx, uint32_t rx_size,
                         uint32_t *got) {
    uint32_t polls;
    for (polls = 0; polls < FMT_ROOM_POLL_BOUND; polls++) {
        int ret = drain_acq(tgt_idx, rx, rx_size, got);
        if (ret != I2C_OK) {
            return ret;
        }
        i2c__HOST_FIFO_STATUS_t fifo = {.w = read_reg(I2C_REG(ctrl_idx, HOST_FIFO_STATUS))};
        if (fifo.f.FMTLVL <= 1u) {
            return I2C_OK;
        }
    }
    return I2C_ERROR_TIMEOUT;
}

static int push_and_drain(uint32_t ctrl_idx, uint32_t tgt_idx, uint8_t target_addr,
                          const uint8_t *tx, uint32_t len, uint8_t *rx, uint32_t rx_size,
                          uint32_t *rx_len) {
    uint32_t sent;
    uint32_t got = 0;
    uint32_t spins;
    int ret;
    i2c__FDATA_t fdata = {.w = 0};

    *rx_len = 0;

    if (!i2c_controller_is_idle(ctrl_idx)) {
        simputs("  ERROR: controller not idle before the frame\n");
        return I2C_ERROR_BUSY;
    }

    fdata.f.FBYTE = (uint8_t)(target_addr << 1); /* write */
    fdata.f.START = 1;
    write_reg(I2C_REG(ctrl_idx, FDATA), fdata.w);

    for (sent = 0; sent < len; sent++) {
        ret = wait_fmt_room(ctrl_idx, tgt_idx, rx, rx_size, &got);
        if (ret != I2C_OK) {
            i2c__HOST_FIFO_STATUS_t fifo = {.w = read_reg(I2C_REG(ctrl_idx, HOST_FIFO_STATUS))};
            simputs("  ERROR: controller did not take byte 0x");
            simputshex32("", sent);
            simputs(" -- FMTLVL=0x");
            simputshex32("", fifo.f.FMTLVL);
            simputs(", STATUS=0x");
            simputshex32("", i2c_get_status(ctrl_idx));
            simputs(", CONTROLLER_EVENTS=0x");
            simputshex32("", i2c_get_controller_events(ctrl_idx));
            simputs("\n");
            *rx_len = got;
            return ret;
        }
        fdata.w = 0;
        fdata.f.FBYTE = tx[sent];
        fdata.f.STOP = (sent + 1u == len) ? 1 : 0;
        write_reg(I2C_REG(ctrl_idx, FDATA), fdata.w);
    }

    /* Trailing drain: the last bytes and the STOP may still be in flight.
     * Bounded, and reaching the bound short of len is a real failure -- a short
     * transfer must not read as a complete one. The inner drain always empties
     * whatever is queued, so an over-long transfer lands as got > len and is
     * caught by the caller's exact byte-count check just the same. */
    for (spins = 0; spins < TRAILING_DRAIN_POLL_BOUND && got < len; spins++) {
        ret = drain_acq(tgt_idx, rx, rx_size, &got);
        if (ret != I2C_OK) {
            *rx_len = got;
            return ret;
        }
    }
    *rx_len = got;

    /* The STOP has to land: HOSTIDLE is the controller's word that the frame
     * is over, and the residual check in main relies on the bus being quiet. */
    ret = i2c_controller_wait_idle(ctrl_idx, I2C_TIMEOUT_DEFAULT);
    if (ret != I2C_OK) {
        simputs("  ERROR: controller never returned to HOSTIDLE after the STOP\n");
        return ret;
    }
    return I2C_OK;
}

int main(void) {
    int ret = I2C_OK;
    uint8_t write_data[LARGE_DATA_SIZE];
    uint8_t read_buffer[256];
    uint32_t received_len = 0;
    uint32_t i;

    for (i = 0; i < LARGE_DATA_SIZE; i++) {
        write_data[i] = (uint8_t)(i & 0xFF);
    }

    simputs("\n");
    simputs("###################################################\n");
    simputs("##   I2C P1 DMA Interface Verification Test    ##\n");
    simputs("###################################################\n");
    simputs("\n");

    write_scratch(1, 0x00000010);
    simputs("Step 1: Wrapper Control Enable\n");
    i2c_wrapper_enable(CONTROLLER_IDX, true);
    i2c_wrapper_enable(TARGET_IDX, false);
    write_scratch(1, 0x00000011);

    write_scratch(1, 0x00000020);
    simputs("Step 2: I2C Initialization\n");

    i2c_timing_physical_t physical_params = {.speed = I2C_SPEED_STANDARD,
                                             .clock_period_nanos = 5,
                                             .sda_rise_nanos = 300,
                                             .sda_fall_nanos = 100,
                                             .scl_period_nanos = 0};

    i2c_timing_config_t computed_timing;
    ret = i2c_compute_timing_from_physical(&physical_params, &computed_timing);
    if (ret != I2C_OK) {
        i2c_get_default_timing(I2C_SPEED_STANDARD, 100, &computed_timing);
    }

    i2c_controller_config_t ctrlr_cfg = {
        .timing = computed_timing,
        .fifo = {.rx_thresh = 29, .fmt_thresh = 5, .tx_thresh = 0, .acq_thresh = 0},
        .enable_interrupts = false,
        .timeout_cycles = 0};

    ret = i2c_controller_init(CONTROLLER_IDX, &ctrlr_cfg);
    if (ret != I2C_OK) {
        write_scratch(0, 0xBAD00030);
        test_fail(0);
    }

    i2c_target_config_t tgt_cfg = {
        .address0 = TARGET_ADDR,
        .mask0 = 0x7F,
        .address1 = 0,
        .mask1 = 0,
        .timing = computed_timing,
        .fifo = {.tx_thresh = 5, .acq_thresh = 29, .rx_thresh = 0, .fmt_thresh = 0},
        .enable_interrupts = false,
        .ack_ctrl_mode = false,
        .tx_stretch_ctrl = false,
        .timeout_cycles = 0};

    ret = i2c_target_init(TARGET_IDX, &tgt_cfg);
    if (ret != I2C_OK) {
        write_scratch(0, 0xBAD00031);
        test_fail(0);
    }

    write_scratch(1, 0x00000021);

    write_scratch(1, 0x00000030);
    simputs("Step 3: Large Data Transfer (DMA-like)\n");

    // Prepare the target for reception: flush and reset the ACQ FIFO
    simputs("  Flushing and resetting ACQ FIFO...\n");
    uint32_t target_base = i2c_get_base(TARGET_IDX);

    // Flush any existing data in ACQ FIFO
    uint32_t flush_count = 0;
    i2c__STATUS_t status = {
        .w = read_reg(target_base + (SMC_TOP_SMC_I2C_WRAP_I2C_STATUS_BASE_ADDR(0) -
                                     SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)))};
    while (!status.f.ACQEMPTY && flush_count < 100) {
        (void)read_reg(target_base + (SMC_TOP_SMC_I2C_WRAP_I2C_ACQDATA_BASE_ADDR(0) -
                                      SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)));
        status.w = read_reg(target_base + (SMC_TOP_SMC_I2C_WRAP_I2C_STATUS_BASE_ADDR(0) -
                                           SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)));
        flush_count++;
    }

    // Reset ACQ FIFO explicitly
    i2c_reset_fifos(TARGET_IDX, false, false, false, true);
    simputs("  ACQ FIFO reset completed\n");

    /* Wait for the target to become idle -- and fail if it never does.
     * TARGETIDLE is the real ready handshake, so it is polled to a bound rather
     * than stood in for by a fixed delay tied to no spec bound, and expiry fails
     * the test instead of printing "ready" either way.
     */
    simputs("  Waiting for Target to become idle...\n");
    bool target_idle_seen = false;
    uint32_t idle_wait_count;
    const uint32_t IDLE_WAIT_TIMEOUT = 10000;
    for (idle_wait_count = 0; idle_wait_count < IDLE_WAIT_TIMEOUT; idle_wait_count++) {
        status.w = read_reg(target_base + (SMC_TOP_SMC_I2C_WRAP_I2C_STATUS_BASE_ADDR(0) -
                                           SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)));
        if (status.f.TARGETIDLE) {
            target_idle_seen = true;
            break;
        }
    }
    if (!target_idle_seen) {
        uint32_t d_fmt = 0, d_rx = 0, d_tx = 0, d_acq = 0;
        (void)i2c_get_all_fifo_levels(TARGET_IDX, &d_fmt, &d_rx, &d_tx, &d_acq);
        simputs("  ERROR: target never reported TARGETIDLE in 0x");
        simputshex32("", IDLE_WAIT_TIMEOUT);
        simputs(" polls -- last state: TARGETIDLE=0, ACQLVL=0x");
        simputshex32("", d_acq);
        simputs(", TXLVL=0x");
        simputshex32("", d_tx);
        simputs(", controller HOSTIDLE=");
        simputs(i2c_controller_is_idle(CONTROLLER_IDX) ? "1" : "0");
        (void)i2c_get_all_fifo_levels(CONTROLLER_IDX, &d_fmt, &d_rx, &d_tx, &d_acq);
        simputs(", controller FMTLVL=0x");
        simputshex32("", d_fmt);
        simputs("\n");
        write_scratch(0, 0xBAD00042);
        test_fail(0);
    }
    simputs("  Target ready for data reception (TARGETIDLE observed)\n");

    /* No length header is sent: the payload goes on the wire as raw bytes after
     * START+address, so the receive side must not consume the first byte as a
     * count. That is why the drain below reads raw ACQ entries rather than
     * calling i2c_target_receive_transaction, whose framing assumes a header
     * this test never sends -- against this stimulus it took write_data[0] == 0
     * as the length and returned success after a single byte. */

    simputs("  [DEBUG] Pre-transfer status:\n");
    i2c__TARGET_FIFO_STATUS_t fifo_status = {
        .w = read_reg(target_base + (SMC_TOP_SMC_I2C_WRAP_I2C_TARGET_FIFO_STATUS_BASE_ADDR(0) -
                                     SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)))};
    simputs("    - ACQ Level: ");
    simputshex32("", fifo_status.f.ACQLVL);
    simputs(", Idle: ");
    i2c__STATUS_t status_pre = {
        .w = read_reg(target_base + (SMC_TOP_SMC_I2C_WRAP_I2C_STATUS_BASE_ADDR(0) -
                                     SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)))};
    simputs(status_pre.f.TARGETIDLE ? "YES" : "NO");
    simputs("\n");

    // One 64-byte write frame, fed one FMT entry at a time with the ACQ FIFO
    // drained between entries: the target stretches at ACQ depth 62, so a bulk
    // push with nothing draining could not complete (see push_and_drain above).
    simputs("  Transferring 64 bytes in one frame with interleaved ACQ drain...\n");
    ret = push_and_drain(CONTROLLER_IDX, TARGET_IDX, TARGET_ADDR, write_data, LARGE_DATA_SIZE,
                         read_buffer, sizeof(read_buffer), &received_len);
    if (ret != I2C_OK) {
        simputs("  ERROR: interleaved transfer failed\n");
        write_scratch(0, 0xBAD00040);
        test_fail(0);
    }

    simputs("  Received ");
    simputshex32("", received_len);
    simputs(" bytes\n");

    // The transfer is reconciled against the stimulus: both the byte count and
    // every byte are compared, and the expected bytes are recomputed here from
    // the same closed form that produced the stimulus rather than read back
    // from the DUT.
    if (received_len != LARGE_DATA_SIZE) {
        simputs("  ERROR: byte count mismatch -- expected 0x");
        simputshex32("", LARGE_DATA_SIZE);
        simputs(", received 0x");
        simputshex32("", received_len);
        simputs("\n");
        write_scratch(0, 0xBAD00044);
        test_fail(0);
    }
    for (i = 0; i < LARGE_DATA_SIZE; i++) {
        uint8_t expected = (uint8_t)(i & 0xFF);
        if (read_buffer[i] != expected) {
            simputs("  ERROR: data mismatch at index 0x");
            simputshex32("", i);
            simputs(" -- expected 0x");
            simputshex32("", expected);
            simputs(", got 0x");
            simputshex32("", read_buffer[i]);
            simputs("\n");
            write_scratch(0, 0xBAD00045);
            test_fail(0);
        }
    }
    simputs("  All 64 bytes matched the transmitted pattern\n");

    /* Nothing may be left behind in the target's ACQ FIFO.
     *
     * A residual entry after the expected payload has been drained means the
     * target accepted traffic this test has not accounted for, so it fails here
     * instead of being discarded as leftover state.
     *
     * CTRL.ACQ_START_STOP_EN is left at its reset value of 0 (i2c.rdl:580) and
     * i2c_target_init never sets it, so the target writes no START/RESTART/STOP
     * entries into the ACQ FIFO (i2c_target_fsm.sv:429,556,562,639). A healthy
     * transfer therefore leaves the ACQ FIFO holding exactly the 64 payload
     * bytes and nothing else, all of which have just been read out.
     *
     * The frame's last entry carried STOP and push_and_drain returned only
     * after HOSTIDLE, meaning the bus is quiet by the time this runs; the
     * settle poll is there to catch a late arrival, not to wait for an
     * expected one, which is why any nonzero level fails immediately. */
    const uint32_t RESIDUAL_SETTLE_POLLS = 200;
    uint32_t residual_acq = 0;
    for (i = 0; i < RESIDUAL_SETTLE_POLLS; i++) {
        fifo_status.w =
            read_reg(target_base + (SMC_TOP_SMC_I2C_WRAP_I2C_TARGET_FIFO_STATUS_BASE_ADDR(0) -
                                    SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)));
        if (fifo_status.f.ACQLVL != 0) {
            residual_acq = fifo_status.f.ACQLVL;
            break;
        }
    }
    if (residual_acq != 0) {
        simputs("  ERROR: 0x");
        simputshex32("", residual_acq);
        simputs(" residual ACQ entries after the expected payload was drained\n");
        write_scratch(0, 0xBAD00046);
        test_fail(0);
    }
    simputs("  ACQ FIFO empty after the payload was drained -- no residual entries\n");

    write_scratch(1, 0x00000031);

    simputs("\n");
    simputs("###################################################\n");
    simputs("##   DMA Interface Verification Test PASSED    ##\n");
    simputs("###################################################\n");
    write_scratch(1, 0xEBEDEBE4);
    test_pass(0);

    return I2C_OK;
}
