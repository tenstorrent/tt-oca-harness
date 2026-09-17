/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/*
 * SPI OT Register Test
 *
 * Verifies reset defaults, write-readback, and special behaviors for all
 * SPI controller registers:
 * - INTR_STATE, INTR_ENABLE, INTR_TEST
 * - CTRL (incl. SW_RST singlepulse), CFG, CSID
 * - STATUS (TXEMPTY, RXEMPTY, BYTEORDER=1, READY=1 at reset)
 * - ERROR_ENABLE, EVENT_ENABLE, ERROR_STATUS
 *
 * Test Flow:
 * 1. Enable controller
 * 2. Verify reset defaults for all readable registers
 * 3. Write-readback for all RW registers
 * 4. Verify SW_RST singlepulse auto-clears to 0
 * 5. Verify STATUS.BYTEORDER=1 (LITTLE_ENDIAN parameter)
 */

#include <stdint.h>
#include <stdio.h>
#include "sep.h"
#include "sep_spi.h"
#include "och_sep_common.h"
#include "test_completion.h"
#include "sep_outbound_filter.h"

#define TIMEOUT_LIMIT 100000

static int check_reg(const char *name, uint32_t actual, uint32_t expected) {
    int ok = (actual == expected);
    printf("  %s: 0x%08x (expected 0x%08x) - %s\n", name, actual, expected, ok ? "PASS" : "FAIL");
    return ok;
}

/* Poll until TXEMPTY after SW_RST (fail-closed). */
static int wait_for_tx_empty(int timeout) {
    spi_controller__STATUS_t status;
    while (timeout-- > 0) {
        status.w = READ_REG(OCH_SEP_TOP_SPI_CONTROLLER_STATUS_BASE_ADDR);
        if (status.f.TXEMPTY) return 0;
    }
    status.w = READ_REG(OCH_SEP_TOP_SPI_CONTROLLER_STATUS_BASE_ADDR);
    printf("  FAIL: TIMEOUT waiting for TXEMPTY after SW_RST (STATUS=0x%08x)\n", status.w);
    return -1;
}

int main(void) {
    sep_outbound_filter_init();

    printf("\n========================================\n");
    printf("SPI OT Register Test\n");
    printf("========================================\n\n");

    int pass = 1;
    spi_controller__CTRL_t ctrl;
    spi_controller__CFG_t cfg;
    spi_controller__STATUS_t status;
    spi_controller__INTR_STATUS_t intr_status;
    spi_controller__INTR_ENABLE_t intr_enable;
    spi_controller__INTR_TEST_t intr_test;
    spi_controller__EVENT_ENABLE_t event_enable;
    spi_controller__ERROR_STATUS_t err_status;
    spi_controller__ERROR_ENABLE_t err_enable;

    /* -------------------------------------------------------------------
     * Step 1: Verify reset defaults
     * ------------------------------------------------------------------- */
    printf("\nStep 1: Reset default verification\n");

    intr_status.w = READ_REG(OCH_SEP_TOP_SPI_CONTROLLER_INTR_STATUS_BASE_ADDR);
    if (!check_reg("INTR_STATUS default", intr_status.w, SPI_CONTROLLER__INTR_STATUS_reset))
        pass = 0;

    intr_enable.w = READ_REG(OCH_SEP_TOP_SPI_CONTROLLER_INTR_ENABLE_BASE_ADDR);
    if (!check_reg("INTR_ENABLE default", intr_enable.w, SPI_CONTROLLER__INTR_ENABLE_reset))
        pass = 0;

    intr_test.w = READ_REG(OCH_SEP_TOP_SPI_CONTROLLER_INTR_TEST_BASE_ADDR);
    if (!check_reg("INTR_TEST default", intr_test.w, SPI_CONTROLLER__INTR_TEST_reset)) pass = 0;

    ctrl.w = READ_REG(OCH_SEP_TOP_SPI_CONTROLLER_CTRL_BASE_ADDR);
    if (!check_reg("CTRL default", ctrl.w, SPI_CONTROLLER__CTRL_reset)) pass = 0;

    cfg.w = READ_REG(OCH_SEP_TOP_SPI_CONTROLLER_CFG_BASE_ADDR);
    if (!check_reg("CFG default", cfg.w, SPI_CONTROLLER__CFG_reset)) pass = 0;

    uint32_t csid_val = READ_REG(OCH_SEP_TOP_SPI_CONTROLLER_CSID_BASE_ADDR);
    if (!check_reg("CSID default", csid_val, SPI_CONTROLLER__CSID_reset)) pass = 0;

    err_enable.w = READ_REG(OCH_SEP_TOP_SPI_CONTROLLER_ERROR_ENABLE_BASE_ADDR);
    if (!check_reg("ERROR_ENABLE default", err_enable.w, SPI_CONTROLLER__ERROR_ENABLE_reset))
        pass = 0;

    event_enable.w = READ_REG(OCH_SEP_TOP_SPI_CONTROLLER_EVENT_ENABLE_BASE_ADDR);
    if (!check_reg("EVENT_ENABLE default", event_enable.w, SPI_CONTROLLER__EVENT_ENABLE_reset))
        pass = 0;

    err_status.w = READ_REG(OCH_SEP_TOP_SPI_CONTROLLER_ERROR_STATUS_BASE_ADDR);
    if (!check_reg("ERROR_STATUS default", err_status.w, SPI_CONTROLLER__ERROR_STATUS_reset))
        pass = 0;

    /* -------------------------------------------------------------------
     * Step 2: STATUS at reset — key flag verification
     * ------------------------------------------------------------------- */
    printf("\nStep 2: STATUS reset flags\n");
    status.w = READ_REG(OCH_SEP_TOP_SPI_CONTROLLER_STATUS_BASE_ADDR);
    printf("  STATUS=0x%08x\n", status.w);
    if (!check_reg("TXEMPTY=1", status.f.TXEMPTY, 1)) pass = 0;
    if (!check_reg("RXEMPTY=1", status.f.RXEMPTY, 1)) pass = 0;
    if (!check_reg("READY=1", status.f.READY, 1)) pass = 0;
    if (!check_reg("ACTIVE=0", status.f.ACTIVE, 0)) pass = 0;
    if (!check_reg("TXFULL=0", status.f.TXFULL, 0)) pass = 0;
    if (!check_reg("RXFULL=0", status.f.RXFULL, 0)) pass = 0;

    /* Step 2.5: STATUS.BYTEORDER = 1 (LITTLE_ENDIAN parameter) */
    printf("\nStep 2.5: STATUS.BYTEORDER check\n");
    if (!check_reg("BYTEORDER=1 (little-endian)", status.f.BYTEORDER, 1)) pass = 0;

    /* -------------------------------------------------------------------
     * Step 3: Write-readback for all RW registers
     * ------------------------------------------------------------------- */
    printf("\nStep 3: Write-readback for RW registers\n");

    /* INTR_ENABLE */
    intr_enable.w = 0;
    intr_enable.f.ERROR = 1;
    intr_enable.f.SPI_EVENT = 1;
    WRITE_REG(OCH_SEP_TOP_SPI_CONTROLLER_INTR_ENABLE_BASE_ADDR, intr_enable.w);
    intr_enable.w = READ_REG(OCH_SEP_TOP_SPI_CONTROLLER_INTR_ENABLE_BASE_ADDR);
    if (!check_reg("INTR_ENABLE.error=1", intr_enable.f.ERROR, 1)) pass = 0;
    if (!check_reg("INTR_ENABLE.spi_event=1", intr_enable.f.SPI_EVENT, 1)) pass = 0;
    /* Restore */
    WRITE_REG(OCH_SEP_TOP_SPI_CONTROLLER_INTR_ENABLE_BASE_ADDR, 0);

    /* INTR_TEST write and readback */
    intr_test.w = 0;
    intr_test.f.ERROR = 1;
    intr_test.f.SPI_EVENT = 1;
    WRITE_REG(OCH_SEP_TOP_SPI_CONTROLLER_INTR_TEST_BASE_ADDR, intr_test.w);
    intr_test.w = READ_REG(OCH_SEP_TOP_SPI_CONTROLLER_INTR_TEST_BASE_ADDR);
    if (!check_reg("INTR_TEST.error=1", intr_test.f.ERROR, 1)) pass = 0;
    if (!check_reg("INTR_TEST.spi_event=1", intr_test.f.SPI_EVENT, 1)) pass = 0;
    /* Clear INTR_TEST */
    WRITE_REG(OCH_SEP_TOP_SPI_CONTROLLER_INTR_TEST_BASE_ADDR, 0);
    intr_test.w = READ_REG(OCH_SEP_TOP_SPI_CONTROLLER_INTR_TEST_BASE_ADDR);
    if (!check_reg("INTR_TEST cleared", intr_test.w, 0)) pass = 0;

    /* CTRL write-readback (enable controller) */
    ctrl.w = SPI_CONTROLLER__CTRL_reset;
    ctrl.f.SPIEN = 1;
    ctrl.f.OUTPUT_EN = 1;
    WRITE_REG(OCH_SEP_TOP_SPI_CONTROLLER_CTRL_BASE_ADDR, ctrl.w);
    ctrl.w = READ_REG(OCH_SEP_TOP_SPI_CONTROLLER_CTRL_BASE_ADDR);
    if (!check_reg("CTRL.spien=1", ctrl.f.SPIEN, 1)) pass = 0;
    if (!check_reg("CTRL.output_en=1", ctrl.f.OUTPUT_EN, 1)) pass = 0;

    /* CFG write-readback */
    cfg.w = 0;
    cfg.f.CLKDIV = 9;
    cfg.f.CPOL = 1;
    cfg.f.CPHA = 1;
    cfg.f.CSNIDLE = 3;
    cfg.f.CSNLEAD = 3;
    cfg.f.CSNTRAIL = 3;
    WRITE_REG(OCH_SEP_TOP_SPI_CONTROLLER_CFG_BASE_ADDR, cfg.w);
    cfg.w = READ_REG(OCH_SEP_TOP_SPI_CONTROLLER_CFG_BASE_ADDR);
    if (!check_reg("CFG.clkdiv=9", cfg.f.CLKDIV, 9)) pass = 0;
    if (!check_reg("CFG.cpol=1", cfg.f.CPOL, 1)) pass = 0;
    if (!check_reg("CFG.cpha=1", cfg.f.CPHA, 1)) pass = 0;
    /* Restore CFG to standard mode */
    cfg.w = 0;
    cfg.f.CLKDIV = 9;
    WRITE_REG(OCH_SEP_TOP_SPI_CONTROLLER_CFG_BASE_ADDR, cfg.w);

    /* CSID write-readback */
    WRITE_REG(OCH_SEP_TOP_SPI_CONTROLLER_CSID_BASE_ADDR, 3);
    csid_val = READ_REG(OCH_SEP_TOP_SPI_CONTROLLER_CSID_BASE_ADDR);
    if (!check_reg("CSID write 3", csid_val, 3)) pass = 0;
    WRITE_REG(OCH_SEP_TOP_SPI_CONTROLLER_CSID_BASE_ADDR, 0);

    /* ERROR_ENABLE write-readback */
    WRITE_REG(OCH_SEP_TOP_SPI_CONTROLLER_ERROR_ENABLE_BASE_ADDR, 0);
    err_enable.w = READ_REG(OCH_SEP_TOP_SPI_CONTROLLER_ERROR_ENABLE_BASE_ADDR);
    if (!check_reg("ERROR_ENABLE all disabled", err_enable.w, 0)) pass = 0;
    WRITE_REG(OCH_SEP_TOP_SPI_CONTROLLER_ERROR_ENABLE_BASE_ADDR,
              SPI_CONTROLLER__ERROR_ENABLE_reset);

    /* EVENT_ENABLE write-readback */
    event_enable.w = 0;
    event_enable.f.RXFULL = 1;
    event_enable.f.TXEMPTY = 1;
    event_enable.f.RXWM = 1;
    event_enable.f.TXWM = 1;
    event_enable.f.READY = 1;
    event_enable.f.IDLE = 1;
    WRITE_REG(OCH_SEP_TOP_SPI_CONTROLLER_EVENT_ENABLE_BASE_ADDR, event_enable.w);
    event_enable.w = READ_REG(OCH_SEP_TOP_SPI_CONTROLLER_EVENT_ENABLE_BASE_ADDR);
    if (!check_reg("EVENT_ENABLE.rxfull", event_enable.f.RXFULL, 1)) pass = 0;
    if (!check_reg("EVENT_ENABLE.txempty", event_enable.f.TXEMPTY, 1)) pass = 0;
    if (!check_reg("EVENT_ENABLE.rxwm", event_enable.f.RXWM, 1)) pass = 0;
    if (!check_reg("EVENT_ENABLE.txwm", event_enable.f.TXWM, 1)) pass = 0;
    if (!check_reg("EVENT_ENABLE.ready", event_enable.f.READY, 1)) pass = 0;
    if (!check_reg("EVENT_ENABLE.idle", event_enable.f.IDLE, 1)) pass = 0;
    WRITE_REG(OCH_SEP_TOP_SPI_CONTROLLER_EVENT_ENABLE_BASE_ADDR, 0);

    /* -------------------------------------------------------------------
     * Step 4: SW_RST drain proof (non-vacuous)
     * SW_RST is a WO singlepulse field — readback is always 0 and cannot
     * prove the pulse fired. Fill TX FIFO first, pulse SW_RST, then poll
     * for TXEMPTY/RXEMPTY drain.
     * ------------------------------------------------------------------- */
    printf("\nStep 4: SW_RST drain proof (pre-fill TX FIFO)\n");
    uint32_t i;
    for (i = 0; i < 8; i++) {
        WRITE_REG(OCH_SEP_TOP_SPI_CONTROLLER_TXDATA_BASE_ADDR, 0xA0000000 | i);
    }
    status.w = READ_REG(OCH_SEP_TOP_SPI_CONTROLLER_STATUS_BASE_ADDR);
    printf("  Pre-SW_RST: TXEMPTY=%u, TXQD=%u\n", status.f.TXEMPTY, status.f.TXQD);
    if (status.f.TXEMPTY != 0) {
        printf("  FAIL: TX FIFO must be non-empty before SW_RST proof\n");
        pass = 0;
        goto done;
    }

    ctrl.w = READ_REG(OCH_SEP_TOP_SPI_CONTROLLER_CTRL_BASE_ADDR);
    ctrl.f.SW_RST = 1;
    WRITE_REG(OCH_SEP_TOP_SPI_CONTROLLER_CTRL_BASE_ADDR, ctrl.w);
    if (wait_for_tx_empty(TIMEOUT_LIMIT)) {
        pass = 0;
        goto done;
    }

    /* -------------------------------------------------------------------
     * Step 5: Post-SW_RST STATUS sanity (meaningful only after Step 4 fill)
     * ------------------------------------------------------------------- */
    printf("\nStep 5: Post-SW_RST STATUS check\n");
    status.w = READ_REG(OCH_SEP_TOP_SPI_CONTROLLER_STATUS_BASE_ADDR);
    printf("  STATUS=0x%08x\n", status.w);
    if (!check_reg("TXEMPTY=1 after SW_RST", status.f.TXEMPTY, 1)) pass = 0;
    if (!check_reg("RXEMPTY=1 after SW_RST", status.f.RXEMPTY, 1)) pass = 0;
    if (!check_reg("TXQD=0 after SW_RST", status.f.TXQD, 0)) pass = 0;

done:

    printf("\n========================================\n");
    if (pass) {
        printf("=== SPI OT REG TEST PASSED ===\n");
        test_pass(0);
    } else {
        printf("=== SPI OT REG TEST FAILED ===\n");
        test_fail(0);
    }
    printf("========================================\n");

    while (1) {
        __asm__("wfi");
    }
    return pass ? 0 : -1;
}
