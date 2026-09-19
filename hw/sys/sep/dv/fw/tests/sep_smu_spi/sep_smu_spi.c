/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/*
 * sep_smu_spi - SMU-level SEP SPI write/read command test.
 *
 *   Run a minimal OpenTitan SPI command sequence in SMU SEP_RTL mode without
 *   requiring an external flash model, then park the CPU in explicit pass/fail
 *   loops so the cocotb test can classify the result by SEP PC. The open DUT
 *   has no SPI pad mux, so this image does not program one. A companion
 *   wrapper mux belongs with that wrapper's firmware.
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

static void spi_controller_init(void) {
    spi_controller__CONTROL_t ctrl = {.w = SPI_CONTROLLER__CONTROL_reset};
    spi_controller__CONFIGOPTS_t cfg = {.w = 0};

    ctrl.f.SPIEN = 1;
    ctrl.f.OUTPUT_EN = 1;
    WRITE_REG(OCH_SEP_TOP_SPI_CONTROLLER_CONTROL_BASE_ADDR, ctrl.w);

    cfg.f.CLKDIV = 9;
    cfg.f.CPOL = 0;
    cfg.f.CPHA = 0;
    cfg.f.CSNIDLE = 2;
    cfg.f.CSNLEAD = 2;
    cfg.f.CSNTRAIL = 2;
    WRITE_REG(OCH_SEP_TOP_SPI_CONTROLLER_CONFIGOPTS_BASE_ADDR, cfg.w);

    WRITE_REG(OCH_SEP_TOP_SPI_CONTROLLER_CSID_BASE_ADDR, 0);
    WRITE_REG(OCH_SEP_TOP_SPI_CONTROLLER_ERROR_STATUS_BASE_ADDR, 0xFFFFFFFFu);
}

static int wait_ready(void) {
    spi_controller__STATUS_t status;
    int t = SPI_TIMEOUT;
    while (t-- > 0) {
        status.w = READ_REG(OCH_SEP_TOP_SPI_CONTROLLER_STATUS_BASE_ADDR);
        if (status.f.READY) return 0;
    }
    return -1;
}

static int wait_idle(void) {
    spi_controller__STATUS_t status;
    int t = SPI_TIMEOUT;
    while (t-- > 0) {
        status.w = READ_REG(OCH_SEP_TOP_SPI_CONTROLLER_STATUS_BASE_ADDR);
        if (!status.f.ACTIVE) return 0;
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
    spi_error_status_t err = {.w = 0};

    spi_controller_init();

    /* Step 1: TX single-byte command (0x9F). */
    if (wait_ready() != 0) return SPI_ERR_WAIT_READY_CMD;
    WRITE_REG(OCH_SEP_TOP_SPI_CONTROLLER_TXDATA_BASE_ADDR(0), 0x9F000000u);
    cmd.w = 0;
    cmd.f.LEN = 0; /* one byte */
    cmd.f.CSAAT = 0;
    cmd.f.SPEED = 0;     /* standard */
    cmd.f.DIRECTION = 2; /* TX */
    WRITE_REG(OCH_SEP_TOP_SPI_CONTROLLER_COMMAND_BASE_ADDR, cmd.w);
    if (wait_idle() != 0) return SPI_ERR_WAIT_IDLE_CMD;

    /* Step 2: TX address phase (4 bytes) with CS held. */
    if (wait_ready() != 0) return SPI_ERR_WAIT_READY_ADDR;
    WRITE_REG(OCH_SEP_TOP_SPI_CONTROLLER_TXDATA_BASE_ADDR(0), 0x03001000u);
    cmd.w = 0;
    cmd.f.LEN = 3;   /* four bytes */
    cmd.f.CSAAT = 1; /* hold CS */
    cmd.f.SPEED = 0;
    cmd.f.DIRECTION = 2; /* TX */
    WRITE_REG(OCH_SEP_TOP_SPI_CONTROLLER_COMMAND_BASE_ADDR, cmd.w);

    /* Step 3: RX 4 bytes and release CS. */
    if (wait_ready() != 0) return SPI_ERR_WAIT_READY_RX;
    cmd.w = 0;
    cmd.f.LEN = 3;   /* four bytes */
    cmd.f.CSAAT = 0; /* release CS */
    cmd.f.SPEED = 0;
    cmd.f.DIRECTION = 1; /* RX */
    WRITE_REG(OCH_SEP_TOP_SPI_CONTROLLER_COMMAND_BASE_ADDR, cmd.w);
    if (wait_idle() != 0) return SPI_ERR_WAIT_IDLE_RX;

    /* Hard failures: malformed command / invalid CSID. */
    err.w = READ_REG(OCH_SEP_TOP_SPI_CONTROLLER_ERROR_STATUS_BASE_ADDR);
    if (err.f.CMDINVAL || err.f.CSIDINVAL) return SPI_ERR_STATUS;

    return SPI_OK;
}

/*
 * Exported labels for cocotb PC-based pass/fail classification.
 * Do not rename without updating smu_sep_spi_test.py symbol lookup.
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

int main(void) {
    /*
     * Keep outbound filter init aligned with other SMU SEP tests. This test
     * does not rely on STDOUT for completion; cocotb keys off SEP PC symbols.
     */
    sep_outbound_filter_init();

    int rc = run_spi_txrx_sequence();

    if (rc == SPI_OK) smu_sep_spi_pass_loop();
    if (rc == SPI_ERR_WAIT_READY_CMD) smu_sep_spi_fail_wait_ready_cmd_loop();
    if (rc == SPI_ERR_WAIT_IDLE_CMD) smu_sep_spi_fail_wait_idle_cmd_loop();
    if (rc == SPI_ERR_WAIT_READY_ADDR) smu_sep_spi_fail_wait_ready_addr_loop();
    if (rc == SPI_ERR_WAIT_READY_RX) smu_sep_spi_fail_wait_ready_rx_loop();
    if (rc == SPI_ERR_WAIT_IDLE_RX) smu_sep_spi_fail_wait_idle_rx_loop();
    if (rc == SPI_ERR_STATUS) smu_sep_spi_fail_error_status_loop();

    smu_sep_spi_fail_loop();
}
