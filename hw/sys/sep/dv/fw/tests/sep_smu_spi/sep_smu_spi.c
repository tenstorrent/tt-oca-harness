/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/*
 * sep_smu_spi - SMU-level SEP SPI command / address / receive test.
 *
 * Run a minimal OpenTitan SPI command sequence in SMU SEP_RTL mode without
 * requiring an external flash model, read the received word back out of the
 * RX FIFO, then park the CPU in explicit pass/fail loops so the cocotb test
 * can classify the result by SEP PC. The OT SPI host reaches the pads only
 * on the SMC LSIO primary plane and no select steers it, so this image
 * programs no pad path.
 *
 * The bench grades the pins: it counts the SCK edges and checks the chip
 * select and output enables at the pads, and it drives the receive data pad
 * with a seeded pattern and grades the received word this image pops. Keep
 * the segment lengths, chip-select holds and transmit bytes in step with
 * hw/sys/smu/dv/cocotb_wrapper/seq_lib/smu_sep_spi_seq.py.
 */

#include <stdint.h>

#include "och_sep_common.h"
#include "sep.h"
#include "sep_outbound_filter.h"

#define SPI_TIMEOUT 100000
#define SPI_OK 0
#define SPI_ERR_WAIT_READY_CMD 1
#define SPI_ERR_WAIT_IDLE_CMD 2
#define SPI_ERR_WAIT_READY_ADDR 3
#define SPI_ERR_WAIT_READY_RX 4
#define SPI_ERR_WAIT_IDLE_RX 5
#define SPI_ERR_STATUS 6
#define SPI_ERR_RX_DEPTH 7
#define SPI_ERR_RX_DRAIN 8

/*
 * The RX segment requests four bytes, which the controller delivers as one
 * 32-bit word. The word is the bench's receive pattern, not device content,
 * and the bench grades it at the RX FIFO read port, so this image checks only
 * that exactly one word lands and that the FIFO then drains.
 */
#define SPI_RX_EXPECTED_WORDS 1u

static void spi_controller_init(void) {
    spi_controller__CONTROL_t ctrl = {.w = SPI_CONTROLLER__CONTROL_reset};
    spi_controller__CONFIGOPTS_t cfg = {.w = 0};

    ctrl.f.SPIEN = 1;
    ctrl.f.OUTPUT_EN = 1;
    WRITE_REG(SEP_TOP_SPI_CONTROLLER_CONTROL_BASE_ADDR, ctrl.w);

    cfg.f.CLKDIV = 9;
    cfg.f.CPOL = 0;
    cfg.f.CPHA = 0;
    cfg.f.CSNIDLE = 2;
    cfg.f.CSNLEAD = 2;
    cfg.f.CSNTRAIL = 2;
    WRITE_REG(SEP_TOP_SPI_CONTROLLER_CONFIGOPTS_BASE_ADDR, cfg.w);

    WRITE_REG(SEP_TOP_SPI_CONTROLLER_CSID_BASE_ADDR, 0);
    WRITE_REG(SEP_TOP_SPI_CONTROLLER_ERROR_STATUS_BASE_ADDR, 0xFFFFFFFFu);
}

static int wait_ready(void) {
    spi_controller__STATUS_t status;
    int t = SPI_TIMEOUT;
    while (t-- > 0) {
        status.w = READ_REG(SEP_TOP_SPI_CONTROLLER_STATUS_BASE_ADDR);
        if (status.f.READY) return 0;
    }
    return -1;
}

static int wait_idle(void) {
    spi_controller__STATUS_t status;
    int t = SPI_TIMEOUT;
    while (t-- > 0) {
        status.w = READ_REG(SEP_TOP_SPI_CONTROLLER_STATUS_BASE_ADDR);
        if (!status.f.ACTIVE) return 0;
    }
    return -1;
}

/* The RX queue depth can lag while a transfer is active, so poll for the word. */
static int wait_rx_word(void) {
    spi_controller__STATUS_t status;
    int t = SPI_TIMEOUT;
    while (t-- > 0) {
        status.w = READ_REG(SEP_TOP_SPI_CONTROLLER_STATUS_BASE_ADDR);
        if (status.f.RXQD != 0) return 0;
    }
    return -1;
}

/*
 * ERROR_STATUS's generated union type name carries a property hash, so bind to
 * it through the address-map struct member instead of spelling the hash out.
 */
typedef __typeof__(((spi_controller_t *)0)->ERROR_STATUS) spi_error_status_t;

static int run_spi_txrx_sequence(void) {
    spi_controller__COMMAND_t cmd = {.w = 0};
    spi_controller__STATUS_t status = {.w = 0};
    spi_error_status_t err = {.w = 0};

    spi_controller_init();

    /*
     * The TX FIFO holds exactly the bytes each segment sends: TXDATA takes
     * byte enables, so the 1-byte segment pushes one byte with a byte store,
     * and the 4-byte segment pushes one word. The host sends the low byte of a
     * word first.
     */

    /* Step 1: TX a single-byte command. */
    if (wait_ready() != 0) return SPI_ERR_WAIT_READY_CMD;
    *(volatile uint8_t *)(uintptr_t)SEP_TOP_SPI_CONTROLLER_TXDATA_BASE_ADDR(0) = 0x9Fu;
    cmd.w = 0;
    cmd.f.LEN = 0; /* one byte */
    cmd.f.CSAAT = 0;
    cmd.f.SPEED = 0;     /* standard */
    cmd.f.DIRECTION = 2; /* TX */
    WRITE_REG(SEP_TOP_SPI_CONTROLLER_COMMAND_BASE_ADDR, cmd.w);
    if (wait_idle() != 0) return SPI_ERR_WAIT_IDLE_CMD;

    /* Step 2: TX a read opcode and a 24-bit address, with CS held. */
    if (wait_ready() != 0) return SPI_ERR_WAIT_READY_ADDR;
    WRITE_REG(SEP_TOP_SPI_CONTROLLER_TXDATA_BASE_ADDR(0), 0x00100003u);
    cmd.w = 0;
    cmd.f.LEN = 3;   /* four bytes */
    cmd.f.CSAAT = 1; /* hold CS */
    cmd.f.SPEED = 0;
    cmd.f.DIRECTION = 2; /* TX */
    WRITE_REG(SEP_TOP_SPI_CONTROLLER_COMMAND_BASE_ADDR, cmd.w);

    /* Step 3: RX 4 bytes and release CS. */
    if (wait_ready() != 0) return SPI_ERR_WAIT_READY_RX;
    cmd.w = 0;
    cmd.f.LEN = 3;   /* four bytes */
    cmd.f.CSAAT = 0; /* release CS */
    cmd.f.SPEED = 0;
    cmd.f.DIRECTION = 1; /* RX */
    WRITE_REG(SEP_TOP_SPI_CONTROLLER_COMMAND_BASE_ADDR, cmd.w);
    if (wait_idle() != 0) return SPI_ERR_WAIT_IDLE_RX;

    /* Fail on a malformed command or an invalid chip select. */
    err.w = READ_REG(SEP_TOP_SPI_CONTROLLER_ERROR_STATUS_BASE_ADDR);
    if (err.f.CMDINVAL || err.f.CSIDINVAL) return SPI_ERR_STATUS;

    /* Step 4: the RX segment lands exactly one word; pop it and drain. */
    if (wait_rx_word() != 0) return SPI_ERR_RX_DEPTH;
    status.w = READ_REG(SEP_TOP_SPI_CONTROLLER_STATUS_BASE_ADDR);
    if (status.f.RXQD != SPI_RX_EXPECTED_WORDS) return SPI_ERR_RX_DEPTH;
    (void)READ_REG(SEP_TOP_SPI_CONTROLLER_RXDATA_BASE_ADDR(0));
    status.w = READ_REG(SEP_TOP_SPI_CONTROLLER_STATUS_BASE_ADDR);
    if (status.f.RXQD != 0 || !status.f.RXEMPTY) return SPI_ERR_RX_DRAIN;

    return SPI_OK;
}

/*
 * The bench classifies the result by the PC of these named loops; keep the
 * names in step with smu_sep_spi_seq.py.
 */
__attribute__((used, noinline, noreturn)) void smu_sep_spi_pass_loop(void) {
    while (1) {
        __asm__ volatile("wfi");
    }
}

__attribute__((used, noinline, noreturn)) void smu_sep_spi_fail_loop(void) {
    while (1) {
        __asm__ volatile("wfi");
    }
}

__attribute__((used, noinline, noreturn)) void smu_sep_spi_fail_wait_ready_cmd_loop(void) {
    while (1) {
        __asm__ volatile("wfi");
    }
}

__attribute__((used, noinline, noreturn)) void smu_sep_spi_fail_wait_idle_cmd_loop(void) {
    while (1) {
        __asm__ volatile("wfi");
    }
}

__attribute__((used, noinline, noreturn)) void smu_sep_spi_fail_wait_ready_addr_loop(void) {
    while (1) {
        __asm__ volatile("wfi");
    }
}

__attribute__((used, noinline, noreturn)) void smu_sep_spi_fail_wait_ready_rx_loop(void) {
    while (1) {
        __asm__ volatile("wfi");
    }
}

__attribute__((used, noinline, noreturn)) void smu_sep_spi_fail_wait_idle_rx_loop(void) {
    while (1) {
        __asm__ volatile("wfi");
    }
}

__attribute__((used, noinline, noreturn)) void smu_sep_spi_fail_error_status_loop(void) {
    while (1) {
        __asm__ volatile("wfi");
    }
}

__attribute__((used, noinline, noreturn)) void smu_sep_spi_fail_rx_depth_loop(void) {
    while (1) {
        __asm__ volatile("wfi");
    }
}

__attribute__((used, noinline, noreturn)) void smu_sep_spi_fail_rx_drain_loop(void) {
    while (1) {
        __asm__ volatile("wfi");
    }
}

int main(void) {
    sep_outbound_filter_init();

    int rc = run_spi_txrx_sequence();

    if (rc == SPI_OK) smu_sep_spi_pass_loop();
    if (rc == SPI_ERR_WAIT_READY_CMD) smu_sep_spi_fail_wait_ready_cmd_loop();
    if (rc == SPI_ERR_WAIT_IDLE_CMD) smu_sep_spi_fail_wait_idle_cmd_loop();
    if (rc == SPI_ERR_WAIT_READY_ADDR) smu_sep_spi_fail_wait_ready_addr_loop();
    if (rc == SPI_ERR_WAIT_READY_RX) smu_sep_spi_fail_wait_ready_rx_loop();
    if (rc == SPI_ERR_WAIT_IDLE_RX) smu_sep_spi_fail_wait_idle_rx_loop();
    if (rc == SPI_ERR_STATUS) smu_sep_spi_fail_error_status_loop();
    if (rc == SPI_ERR_RX_DEPTH) smu_sep_spi_fail_rx_depth_loop();
    if (rc == SPI_ERR_RX_DRAIN) smu_sep_spi_fail_rx_drain_loop();

    smu_sep_spi_fail_loop();
}
