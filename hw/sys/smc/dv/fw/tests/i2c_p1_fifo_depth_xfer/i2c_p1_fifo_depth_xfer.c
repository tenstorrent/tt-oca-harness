/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/**
 * @file i2c_p1_fifo_depth_xfer.c
 * @brief I2C full-FIFO-depth transfer with an interleaved push-and-drain
 *
 * Verifies a 64-byte write, the full FIFO depth, from the I2C_0 controller to
 * the I2C_1 target as one frame, with the CPU feeding the controller while it
 * drains the target. Fails on any NACK or other non-data entry at the target,
 * checks the received length and every byte, and checks that the target holds
 * no residual entries afterwards. No DMA is involved.
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
 * Entries are classified by their signal, not by the decoder's is_start and
 * is_stop flags: the decoder leaves both flags false for a NACKed byte, so a
 * flag-based filter would accept it as payload. Any entry that is neither
 * framing nor data fails the transfer.
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

/* Interleaved push and drain: a single-threaded CPU can move the full FIFO
 * depth in one frame only this way.
 *
 * With ACK control off, the target stretches SCL once its ACQ FIFO is within
 * two entries of full; this is intended flow control. If all 64 bytes were
 * queued before anything drained the target, the target would stretch near
 * full, the controller could never retire its FMT entries, and the transfer
 * would not complete.
 *
 * So the frame -- START, address, 64 data bytes, STOP -- is fed to the FMT FIFO
 * one entry at a time. Before each push the CPU waits until at most one entry
 * is left in the FMT FIFO (the byte on the wire) and drains whatever the target
 * has accepted meanwhile. This keeps the bus streaming without an SCL-low gap
 * between bytes and keeps the ACQ FIFO far below the stretch threshold. Bytes
 * are collected here because a blocking receive cannot run while the same CPU
 * has to keep pushing.
 *
 * The frame is written to the FMT FIFO directly rather than through
 * i2c_controller_write, which emits a whole START..data frame per call, so
 * feeding it byte by byte would produce 64 frames, each with its own START and
 * address byte.
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
     * The drain is bounded; a short or over-long transfer is returned as is
     * and fails the caller's exact byte-count check. */
    for (spins = 0; spins < TRAILING_DRAIN_POLL_BOUND && got < len; spins++) {
        ret = drain_acq(tgt_idx, rx, rx_size, &got);
        if (ret != I2C_OK) {
            *rx_len = got;
            return ret;
        }
    }
    *rx_len = got;

    /* Wait for the controller to go idle after the STOP; the residual check in
     * main relies on a quiet bus. */
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

    i2c_reset_fifos(TARGET_IDX, false, false, false, true);
    simputs("  ACQ FIFO reset completed\n");

    /* Wait for the target to go idle; expiry fails the test. */
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

    /* The payload follows START and address with no length header, so the
     * drain reads raw ACQ entries rather than calling
     * i2c_target_receive_transaction, which takes the first data byte as a
     * length. */

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

    // One 64-byte frame with the target drained between entries (see wait_fmt_room)
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

    // Compare the byte count and every byte with the stimulus pattern, recomputed
    // here rather than read back from the DUT.
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

    /* Nothing may be left in the target's ACQ FIFO.
     *
     * A residual entry means the target accepted traffic this test has not
     * accounted for. In its reset mode, which i2c_target_init keeps, the target
     * records no START, RESTART or STOP entries, so a healthy transfer leaves
     * exactly the 64 payload bytes, all already read out. The bus is quiet by
     * now, so the settle poll only catches a late arrival and any nonzero level
     * fails at once. */
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
}
