/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/*
 * SPI OT Interrupt Test
 *
 * Verifies interrupt generation/masking for error and event classes,
 * INTR_TEST register forcing, and EVENT_ENABLE individual control.
 *
 * Test Flow:
 * 1. Enable controller
 * 2. Test INTR_ENABLE defaults and write-readback
 * 3. INTR_TEST injection → verify INTR_STATUS asserts/deasserts (ERROR and SPI_EVENT)
 * 3.5. Real UNDERFLOW event → INTR_STATUS.error functional path
 * 4. EVENT_ENABLE configuration write-readback
 * 4.5. Real TXEMPTY event → INTR_STATUS.spi_event functional path
 * 4.6. EVENT_ENABLE.ready / .idle functional path
 * 5. Masking test: INTR_ENABLE=0 blocks INTR_TEST injection (ERROR and SPI_EVENT)
 */

#include <stdint.h>
#include <stdio.h>
#include "sep.h"
#include "sep_spi.h"
#include "och_sep_common.h"
#include "test_completion.h"
#include "sep_outbound_filter.h"

static int check_reg(const char *name, uint32_t actual, uint32_t expected) {
    int ok = (actual == expected);
    printf("  %s: 0x%08x (expected 0x%08x) - %s\n", name, actual, expected, ok ? "PASS" : "FAIL");
    return ok;
}

int main(void) {
    sep_outbound_filter_init();

    printf("\n========================================\n");
    printf("SPI OT Interrupt Test\n");
    printf("========================================\n\n");

    int pass = 1;
    spi_controller__INTR_STATUS_t intr_status;
    spi_controller__INTR_ENABLE_t intr_enable;
    spi_controller__INTR_TEST_t intr_test;
    spi_controller__EVENT_ENABLE_t event_enable;
    spi_controller__ERROR_STATUS_t err_status;
    spi_controller__CTRL_t ctrl;
    uint32_t dummy_rx;

    /* Enable controller (required for event signals to be valid) */
    ctrl.w = SPI_CONTROLLER__CTRL_reset;
    ctrl.f.SPIEN = 1;
    ctrl.f.OUTPUT_EN = 1;
    WRITE_REG(OCH_SEP_TOP_SPI_CONTROLLER_CTRL_BASE_ADDR, ctrl.w);

    /* Step 1: INTR_STATUS default */
    printf("\nStep 1: INTR_STATUS default\n");
    intr_status.w = READ_REG(OCH_SEP_TOP_SPI_CONTROLLER_INTR_STATUS_BASE_ADDR);
    printf("  INTR_STATUS=0x%08x (ERROR=%u, SPI_EVENT=%u)\n", intr_status.w, intr_status.f.ERROR,
           intr_status.f.SPI_EVENT);

    /* Step 2: INTR_ENABLE write-readback */
    printf("\nStep 2: INTR_ENABLE write-readback\n");
    intr_enable.w = READ_REG(OCH_SEP_TOP_SPI_CONTROLLER_INTR_ENABLE_BASE_ADDR);
    if (!check_reg("INTR_ENABLE default", intr_enable.w, SPI_CONTROLLER__INTR_ENABLE_reset))
        pass = 0;

    intr_enable.w = 0;
    intr_enable.f.ERROR = 1;
    intr_enable.f.SPI_EVENT = 1;
    WRITE_REG(OCH_SEP_TOP_SPI_CONTROLLER_INTR_ENABLE_BASE_ADDR, intr_enable.w);
    intr_enable.w = READ_REG(OCH_SEP_TOP_SPI_CONTROLLER_INTR_ENABLE_BASE_ADDR);
    if (!check_reg("INTR_ENABLE.error", intr_enable.f.ERROR, 1)) pass = 0;
    if (!check_reg("INTR_ENABLE SPI_EVENT", intr_enable.f.SPI_EVENT, 1)) pass = 0;

    /* Step 3: INTR_TEST forcing — verify INTR_TEST injection sets INTR_STATUS
     * RTL: error_intr = (ERROR_STATUS.intr || INTR_TEST.ERROR.wue) && INTR_ENABLE.ERROR.wue
     * INTR_STATUS.ERROR.next = error_intr  (spi_controller.sv:363-365)
     * INTR_ENABLE.error is already set from Step 2.
     */
    printf("\nStep 3: INTR_TEST forcing → INTR_STATUS assertion\n");
    intr_test.w = 0;
    intr_test.f.ERROR = 1;
    WRITE_REG(OCH_SEP_TOP_SPI_CONTROLLER_INTR_TEST_BASE_ADDR, intr_test.w);
    intr_status.w = READ_REG(OCH_SEP_TOP_SPI_CONTROLLER_INTR_STATUS_BASE_ADDR);
    if (!check_reg("INTR_STATUS.error=1 via INTR_TEST injection", intr_status.f.ERROR, 1)) pass = 0;

    /* Release INTR_TEST — INTR_STATUS should deassert (no real error active) */
    intr_test.w = 0;
    WRITE_REG(OCH_SEP_TOP_SPI_CONTROLLER_INTR_TEST_BASE_ADDR, intr_test.w);
    intr_status.w = READ_REG(OCH_SEP_TOP_SPI_CONTROLLER_INTR_STATUS_BASE_ADDR);
    if (!check_reg("INTR_STATUS.error=0 after INTR_TEST release", intr_status.f.ERROR, 0)) pass = 0;

    intr_test.w = 0;
    intr_test.f.SPI_EVENT = 1;
    WRITE_REG(OCH_SEP_TOP_SPI_CONTROLLER_INTR_TEST_BASE_ADDR, intr_test.w);
    intr_status.w = READ_REG(OCH_SEP_TOP_SPI_CONTROLLER_INTR_STATUS_BASE_ADDR);
    if (!check_reg("INTR_STATUS.spi_event=1 via INTR_TEST injection", intr_status.f.SPI_EVENT, 1))
        pass = 0;

    /* Release INTR_TEST — INTR_STATUS should deassert */
    intr_test.w = 0;
    WRITE_REG(OCH_SEP_TOP_SPI_CONTROLLER_INTR_TEST_BASE_ADDR, intr_test.w);
    intr_status.w = READ_REG(OCH_SEP_TOP_SPI_CONTROLLER_INTR_STATUS_BASE_ADDR);
    if (!check_reg("INTR_STATUS.spi_event=0 after INTR_TEST release", intr_status.f.SPI_EVENT, 0))
        pass = 0;

    /* Step 3.5: INTR_STATUS.error functional verification via UNDERFLOW */
    printf("\nStep 3.5: INTR_STATUS.error via UNDERFLOW\n");
    WRITE_REG(OCH_SEP_TOP_SPI_CONTROLLER_ERROR_STATUS_BASE_ADDR, 0xFFFFFFFF); /* clear */
    dummy_rx = READ_REG(OCH_SEP_TOP_SPI_CONTROLLER_RXDATA_BASE_ADDR); /* trigger UNDERFLOW */
    (void)dummy_rx;
    err_status.w = READ_REG(OCH_SEP_TOP_SPI_CONTROLLER_ERROR_STATUS_BASE_ADDR);
    if (!check_reg("UNDERFLOW triggered", err_status.f.UNDERFLOW, 1)) pass = 0;
    intr_status.w = READ_REG(OCH_SEP_TOP_SPI_CONTROLLER_INTR_STATUS_BASE_ADDR);
    if (!check_reg("INTR_STATUS.error=1 on underflow", intr_status.f.ERROR, 1)) pass = 0;
    /* W1C clear ERROR_STATUS → INTR_STATUS.error should deassert */
    WRITE_REG(OCH_SEP_TOP_SPI_CONTROLLER_ERROR_STATUS_BASE_ADDR, err_status.w);
    intr_status.w = READ_REG(OCH_SEP_TOP_SPI_CONTROLLER_INTR_STATUS_BASE_ADDR);
    if (!check_reg("INTR_STATUS.error=0 after clear", intr_status.f.ERROR, 0)) pass = 0;

    /* Step 4: EVENT_ENABLE configuration */
    printf("\nStep 4: EVENT_ENABLE configuration\n");
    event_enable.w = READ_REG(OCH_SEP_TOP_SPI_CONTROLLER_EVENT_ENABLE_BASE_ADDR);
    if (!check_reg("EVENT_ENABLE default", event_enable.w, SPI_CONTROLLER__EVENT_ENABLE_reset))
        pass = 0;

    /* Step 4.5: INTR_STATUS.spi_event via TXEMPTY event */
    printf("\nStep 4.5: INTR_STATUS.spi_event via TXEMPTY\n");
    event_enable.w = 0;
    event_enable.f.TXEMPTY = 1;
    WRITE_REG(OCH_SEP_TOP_SPI_CONTROLLER_EVENT_ENABLE_BASE_ADDR, event_enable.w);
    intr_status.w = READ_REG(OCH_SEP_TOP_SPI_CONTROLLER_INTR_STATUS_BASE_ADDR);
    if (!check_reg("INTR_STATUS.spi_event=1 (txempty)", intr_status.f.SPI_EVENT, 1)) pass = 0;
    /* Disable txempty → spi_event should deassert */
    event_enable.w = 0;
    WRITE_REG(OCH_SEP_TOP_SPI_CONTROLLER_EVENT_ENABLE_BASE_ADDR, event_enable.w);
    intr_status.w = READ_REG(OCH_SEP_TOP_SPI_CONTROLLER_INTR_STATUS_BASE_ADDR);
    if (!check_reg("INTR_STATUS.spi_event=0 (no events)", intr_status.f.SPI_EVENT, 0)) pass = 0;

    /* Step 4.6: EVENT_ENABLE.ready and .idle functional path
     * SPI is in idle state (SPIEN=1, no transaction), so ready and idle events
     * should be asserted immediately when their enables are set.
     */
    printf("\nStep 4.6: EVENT_ENABLE.ready/.idle functional path\n");
    event_enable.w = 0;
    event_enable.f.READY = 1;
    WRITE_REG(OCH_SEP_TOP_SPI_CONTROLLER_EVENT_ENABLE_BASE_ADDR, event_enable.w);
    intr_status.w = READ_REG(OCH_SEP_TOP_SPI_CONTROLLER_INTR_STATUS_BASE_ADDR);
    if (!check_reg("INTR_STATUS.spi_event=1 (ready event)", intr_status.f.SPI_EVENT, 1)) pass = 0;
    event_enable.w = 0;
    WRITE_REG(OCH_SEP_TOP_SPI_CONTROLLER_EVENT_ENABLE_BASE_ADDR, event_enable.w);
    intr_status.w = READ_REG(OCH_SEP_TOP_SPI_CONTROLLER_INTR_STATUS_BASE_ADDR);
    if (!check_reg("INTR_STATUS.spi_event=0 after ready disable", intr_status.f.SPI_EVENT, 0))
        pass = 0;

    event_enable.w = 0;
    event_enable.f.IDLE = 1;
    WRITE_REG(OCH_SEP_TOP_SPI_CONTROLLER_EVENT_ENABLE_BASE_ADDR, event_enable.w);
    intr_status.w = READ_REG(OCH_SEP_TOP_SPI_CONTROLLER_INTR_STATUS_BASE_ADDR);
    if (!check_reg("INTR_STATUS.spi_event=1 (idle event)", intr_status.f.SPI_EVENT, 1)) pass = 0;
    event_enable.w = 0;
    WRITE_REG(OCH_SEP_TOP_SPI_CONTROLLER_EVENT_ENABLE_BASE_ADDR, event_enable.w);
    intr_status.w = READ_REG(OCH_SEP_TOP_SPI_CONTROLLER_INTR_STATUS_BASE_ADDR);
    if (!check_reg("INTR_STATUS.spi_event=0 after idle disable", intr_status.f.SPI_EVENT, 0))
        pass = 0;

    /* Enable all events for write-readback verification */
    event_enable.w = 0;
    event_enable.f.RXFULL = 1;
    event_enable.f.TXEMPTY = 1;
    event_enable.f.RXWM = 1;
    event_enable.f.TXWM = 1;
    event_enable.f.READY = 1;
    event_enable.f.IDLE = 1;
    WRITE_REG(OCH_SEP_TOP_SPI_CONTROLLER_EVENT_ENABLE_BASE_ADDR, event_enable.w);
    event_enable.w = READ_REG(OCH_SEP_TOP_SPI_CONTROLLER_EVENT_ENABLE_BASE_ADDR);
    if (!check_reg("RXFULL enable", event_enable.f.RXFULL, 1)) pass = 0;
    if (!check_reg("TXEMPTY enable", event_enable.f.TXEMPTY, 1)) pass = 0;
    if (!check_reg("RXWM enable", event_enable.f.RXWM, 1)) pass = 0;
    if (!check_reg("TXWM enable", event_enable.f.TXWM, 1)) pass = 0;
    if (!check_reg("READY enable", event_enable.f.READY, 1)) pass = 0;
    if (!check_reg("IDLE enable", event_enable.f.IDLE, 1)) pass = 0;

    /* Step 5: Masking test — INTR_ENABLE=0 blocks INTR_TEST injection from reaching INTR_STATUS
     * RTL: error_intr = (... || INTR_TEST.ERROR.wue) && INTR_ENABLE.ERROR.wue
     * When INTR_ENABLE.error=0, INTR_STATUS.error must remain 0 even if INTR_TEST.error=1.
     */
    printf("\nStep 5: Masking test (INTR_ENABLE=0 blocks INTR_TEST)\n");
    intr_enable.w = 0;
    WRITE_REG(OCH_SEP_TOP_SPI_CONTROLLER_INTR_ENABLE_BASE_ADDR, intr_enable.w);
    intr_enable.w = READ_REG(OCH_SEP_TOP_SPI_CONTROLLER_INTR_ENABLE_BASE_ADDR);
    if (!check_reg("INTR_ENABLE all disabled", intr_enable.w, 0)) pass = 0;

    /* Force INTR_TEST.error=1 with INTR_ENABLE.error=0 — INTR_STATUS must stay 0 */
    intr_test.w = 0;
    intr_test.f.ERROR = 1;
    WRITE_REG(OCH_SEP_TOP_SPI_CONTROLLER_INTR_TEST_BASE_ADDR, intr_test.w);
    intr_status.w = READ_REG(OCH_SEP_TOP_SPI_CONTROLLER_INTR_STATUS_BASE_ADDR);
    if (!check_reg("INTR_STATUS.error=0 when INTR_ENABLE.error=0 (masked)", intr_status.f.ERROR, 0))
        pass = 0;

    /* Release INTR_TEST */
    intr_test.w = 0;
    WRITE_REG(OCH_SEP_TOP_SPI_CONTROLLER_INTR_TEST_BASE_ADDR, intr_test.w);

    /* Step 5b: spi_event masking — INTR_ENABLE.spi_event=0 blocks INTR_TEST.spi_event
     * INTR_ENABLE is still 0 from step 5.
     */
    printf("\nStep 5b: spi_event masking (INTR_ENABLE.spi_event=0)\n");
    intr_test.w = 0;
    intr_test.f.SPI_EVENT = 1;
    WRITE_REG(OCH_SEP_TOP_SPI_CONTROLLER_INTR_TEST_BASE_ADDR, intr_test.w);
    intr_status.w = READ_REG(OCH_SEP_TOP_SPI_CONTROLLER_INTR_STATUS_BASE_ADDR);
    if (!check_reg("INTR_STATUS.spi_event=0 when INTR_ENABLE.spi_event=0 (masked)",
                   intr_status.f.SPI_EVENT, 0))
        pass = 0;
    intr_test.w = 0;
    WRITE_REG(OCH_SEP_TOP_SPI_CONTROLLER_INTR_TEST_BASE_ADDR, intr_test.w);

    /* Disable all events */
    event_enable.w = 0;
    WRITE_REG(OCH_SEP_TOP_SPI_CONTROLLER_EVENT_ENABLE_BASE_ADDR, event_enable.w);
    event_enable.w = READ_REG(OCH_SEP_TOP_SPI_CONTROLLER_EVENT_ENABLE_BASE_ADDR);
    if (!check_reg("EVENT_ENABLE all disabled", event_enable.w, 0)) pass = 0;

    printf("\n========================================\n");
    if (pass) {
        printf("=== SPI OT INTERRUPT TEST PASSED ===\n");
        test_pass(0);
    } else {
        printf("=== SPI OT INTERRUPT TEST FAILED ===\n");
        test_fail(0);
    }
    printf("========================================\n");

    while (1) {
        __asm__("wfi");
    }
    return pass ? 0 : -1;
}
