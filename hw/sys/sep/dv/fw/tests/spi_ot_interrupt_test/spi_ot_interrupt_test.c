/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/*
 * SPI OT Interrupt Test
 *
 * Verifies interrupt generation for the error and event classes, INTR_TEST
 * register forcing, and EVENT_ENABLE individual control.
 *
 * ERROR and SPI_EVENT are different OpenTitan interrupt types, so their state
 * bits behave differently: INTR_STATE.ERROR is an Event latch cleared by W1C,
 * while INTR_STATE.SPI_EVENT tracks its source level. INTR_ENABLE qualifies the
 * outgoing interrupt line, not either state bit.
 *
 * Test Flow:
 * 1. Enable controller
 * 2. Test INTR_ENABLE defaults and write-readback
 * 3. INTR_TEST injection → ERROR latches until W1C, SPI_EVENT follows the force
 * 3.5. Real UNDERFLOW event → INTR_STATE.error functional path
 * 4. EVENT_ENABLE configuration write-readback
 * 4.5. Real TXEMPTY event → INTR_STATE.spi_event functional path
 * 4.6. EVENT_ENABLE.ready / .idle functional path
 * 5. INTR_ENABLE=0 still lets both state bits follow their sources
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
    spi_controller__INTR_STATE_t intr_status;
    spi_controller__INTR_ENABLE_t intr_enable;
    spi_controller__INTR_TEST_t intr_test;
    spi_controller__EVENT_ENABLE_t event_enable;
    spi_controller__ERROR_STATUS_t err_status;
    spi_controller__CONTROL_t ctrl;
    uint32_t dummy_rx;

    /* Enable controller (required for event signals to be valid) */
    ctrl.w = SPI_CONTROLLER__CONTROL_reset;
    ctrl.f.SPIEN = 1;
    ctrl.f.OUTPUT_EN = 1;
    WRITE_REG(OCH_SEP_TOP_SPI_CONTROLLER_CONTROL_BASE_ADDR, ctrl.w);

    /* Step 1: INTR_STATE default */
    printf("\nStep 1: INTR_STATE default\n");
    intr_status.w = READ_REG(OCH_SEP_TOP_SPI_CONTROLLER_INTR_STATE_BASE_ADDR);
    printf("  INTR_STATE=0x%08x (ERROR=%u, SPI_EVENT=%u)\n", intr_status.w, intr_status.f.ERROR,
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

    /* Step 3: INTR_TEST forcing.
     *
     * The two sources are different interrupt types and behave differently.
     * INTR_STATE.ERROR is an Event latch: INTR_TEST sets it, a write of 0 to
     * INTR_TEST leaves it set, and only a write of 1 back to INTR_STATE clears
     * it. INTR_STATE.SPI_EVENT is a Status bit that tracks its source level, so
     * releasing the INTR_TEST force does deassert it. Neither is gated by
     * INTR_ENABLE, which qualifies only the outgoing interrupt line.
     */
    printf("\nStep 3: INTR_TEST forcing → INTR_STATE assertion\n");
    WRITE_REG(OCH_SEP_TOP_SPI_CONTROLLER_INTR_STATE_BASE_ADDR, 0xFFFFFFFF); /* W1C the latch */
    intr_test.w = 0;
    intr_test.f.ERROR = 1;
    WRITE_REG(OCH_SEP_TOP_SPI_CONTROLLER_INTR_TEST_BASE_ADDR, intr_test.w);
    intr_status.w = READ_REG(OCH_SEP_TOP_SPI_CONTROLLER_INTR_STATE_BASE_ADDR);
    if (!check_reg("INTR_STATE.error=1 via INTR_TEST injection", intr_status.f.ERROR, 1)) pass = 0;

    /* Releasing INTR_TEST leaves the Event latch set; only W1C clears it. */
    intr_test.w = 0;
    WRITE_REG(OCH_SEP_TOP_SPI_CONTROLLER_INTR_TEST_BASE_ADDR, intr_test.w);
    intr_status.w = READ_REG(OCH_SEP_TOP_SPI_CONTROLLER_INTR_STATE_BASE_ADDR);
    if (!check_reg("INTR_STATE.error holds after INTR_TEST release", intr_status.f.ERROR, 1))
        pass = 0;

    intr_status.w = 0;
    intr_status.f.ERROR = 1;
    WRITE_REG(OCH_SEP_TOP_SPI_CONTROLLER_INTR_STATE_BASE_ADDR, intr_status.w);
    intr_status.w = READ_REG(OCH_SEP_TOP_SPI_CONTROLLER_INTR_STATE_BASE_ADDR);
    if (!check_reg("INTR_STATE.error=0 after W1C", intr_status.f.ERROR, 0)) pass = 0;

    intr_test.w = 0;
    intr_test.f.SPI_EVENT = 1;
    WRITE_REG(OCH_SEP_TOP_SPI_CONTROLLER_INTR_TEST_BASE_ADDR, intr_test.w);
    intr_status.w = READ_REG(OCH_SEP_TOP_SPI_CONTROLLER_INTR_STATE_BASE_ADDR);
    if (!check_reg("INTR_STATE.spi_event=1 via INTR_TEST injection", intr_status.f.SPI_EVENT, 1))
        pass = 0;

    /* Status-type: releasing the force does deassert it. */
    intr_test.w = 0;
    WRITE_REG(OCH_SEP_TOP_SPI_CONTROLLER_INTR_TEST_BASE_ADDR, intr_test.w);
    intr_status.w = READ_REG(OCH_SEP_TOP_SPI_CONTROLLER_INTR_STATE_BASE_ADDR);
    if (!check_reg("INTR_STATE.spi_event=0 after INTR_TEST release", intr_status.f.SPI_EVENT, 0))
        pass = 0;

    /* Step 3.5: INTR_STATE.error functional verification via UNDERFLOW */
    printf("\nStep 3.5: INTR_STATE.error via UNDERFLOW\n");
    WRITE_REG(OCH_SEP_TOP_SPI_CONTROLLER_ERROR_STATUS_BASE_ADDR, 0xFFFFFFFF); /* clear */
    WRITE_REG(OCH_SEP_TOP_SPI_CONTROLLER_INTR_STATE_BASE_ADDR, 0xFFFFFFFF);
    dummy_rx = READ_REG(OCH_SEP_TOP_SPI_CONTROLLER_RXDATA_BASE_ADDR(0)); /* trigger UNDERFLOW */
    (void)dummy_rx;
    err_status.w = READ_REG(OCH_SEP_TOP_SPI_CONTROLLER_ERROR_STATUS_BASE_ADDR);
    if (!check_reg("UNDERFLOW triggered", err_status.f.UNDERFLOW, 1)) pass = 0;
    intr_status.w = READ_REG(OCH_SEP_TOP_SPI_CONTROLLER_INTR_STATE_BASE_ADDR);
    if (!check_reg("INTR_STATE.error=1 on underflow", intr_status.f.ERROR, 1)) pass = 0;
    /* The error event is a pulse into the latch: clearing ERROR_STATUS does not
     * clear INTR_STATE, so both have to be cleared to leave a clean state. */
    WRITE_REG(OCH_SEP_TOP_SPI_CONTROLLER_ERROR_STATUS_BASE_ADDR, err_status.w);
    intr_status.w = READ_REG(OCH_SEP_TOP_SPI_CONTROLLER_INTR_STATE_BASE_ADDR);
    if (!check_reg("INTR_STATE.error holds after ERROR_STATUS clear", intr_status.f.ERROR, 1))
        pass = 0;
    WRITE_REG(OCH_SEP_TOP_SPI_CONTROLLER_INTR_STATE_BASE_ADDR, 0xFFFFFFFF);
    intr_status.w = READ_REG(OCH_SEP_TOP_SPI_CONTROLLER_INTR_STATE_BASE_ADDR);
    if (!check_reg("INTR_STATE.error=0 after W1C", intr_status.f.ERROR, 0)) pass = 0;

    /* Step 4: EVENT_ENABLE configuration */
    printf("\nStep 4: EVENT_ENABLE configuration\n");
    event_enable.w = READ_REG(OCH_SEP_TOP_SPI_CONTROLLER_EVENT_ENABLE_BASE_ADDR);
    if (!check_reg("EVENT_ENABLE default", event_enable.w, SPI_CONTROLLER__EVENT_ENABLE_reset))
        pass = 0;

    /* Step 4.5: INTR_STATE.spi_event via TXEMPTY event */
    printf("\nStep 4.5: INTR_STATE.spi_event via TXEMPTY\n");
    event_enable.w = 0;
    event_enable.f.TXEMPTY = 1;
    WRITE_REG(OCH_SEP_TOP_SPI_CONTROLLER_EVENT_ENABLE_BASE_ADDR, event_enable.w);
    intr_status.w = READ_REG(OCH_SEP_TOP_SPI_CONTROLLER_INTR_STATE_BASE_ADDR);
    if (!check_reg("INTR_STATE.spi_event=1 (txempty)", intr_status.f.SPI_EVENT, 1)) pass = 0;
    /* Disable txempty → spi_event should deassert */
    event_enable.w = 0;
    WRITE_REG(OCH_SEP_TOP_SPI_CONTROLLER_EVENT_ENABLE_BASE_ADDR, event_enable.w);
    intr_status.w = READ_REG(OCH_SEP_TOP_SPI_CONTROLLER_INTR_STATE_BASE_ADDR);
    if (!check_reg("INTR_STATE.spi_event=0 (no events)", intr_status.f.SPI_EVENT, 0)) pass = 0;

    /* Step 4.6: EVENT_ENABLE.ready and .idle functional path
     * SPI is in idle state (SPIEN=1, no transaction), so ready and idle events
     * should be asserted immediately when their enables are set.
     */
    printf("\nStep 4.6: EVENT_ENABLE.ready/.idle functional path\n");
    event_enable.w = 0;
    event_enable.f.READY = 1;
    WRITE_REG(OCH_SEP_TOP_SPI_CONTROLLER_EVENT_ENABLE_BASE_ADDR, event_enable.w);
    intr_status.w = READ_REG(OCH_SEP_TOP_SPI_CONTROLLER_INTR_STATE_BASE_ADDR);
    if (!check_reg("INTR_STATE.spi_event=1 (ready event)", intr_status.f.SPI_EVENT, 1)) pass = 0;
    event_enable.w = 0;
    WRITE_REG(OCH_SEP_TOP_SPI_CONTROLLER_EVENT_ENABLE_BASE_ADDR, event_enable.w);
    intr_status.w = READ_REG(OCH_SEP_TOP_SPI_CONTROLLER_INTR_STATE_BASE_ADDR);
    if (!check_reg("INTR_STATE.spi_event=0 after ready disable", intr_status.f.SPI_EVENT, 0))
        pass = 0;

    event_enable.w = 0;
    event_enable.f.IDLE = 1;
    WRITE_REG(OCH_SEP_TOP_SPI_CONTROLLER_EVENT_ENABLE_BASE_ADDR, event_enable.w);
    intr_status.w = READ_REG(OCH_SEP_TOP_SPI_CONTROLLER_INTR_STATE_BASE_ADDR);
    if (!check_reg("INTR_STATE.spi_event=1 (idle event)", intr_status.f.SPI_EVENT, 1)) pass = 0;
    event_enable.w = 0;
    WRITE_REG(OCH_SEP_TOP_SPI_CONTROLLER_EVENT_ENABLE_BASE_ADDR, event_enable.w);
    intr_status.w = READ_REG(OCH_SEP_TOP_SPI_CONTROLLER_INTR_STATE_BASE_ADDR);
    if (!check_reg("INTR_STATE.spi_event=0 after idle disable", intr_status.f.SPI_EVENT, 0))
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

    /* Step 5: INTR_ENABLE qualifies the outgoing interrupt line only. With the
     * enable clear, both state bits still follow their sources; the line itself
     * is not visible from these registers, so it is checked in the SEP
     * interrupt-delivery tests rather than here.
     */
    printf("\nStep 5: INTR_ENABLE=0 does not gate INTR_STATE\n");
    intr_enable.w = 0;
    WRITE_REG(OCH_SEP_TOP_SPI_CONTROLLER_INTR_ENABLE_BASE_ADDR, intr_enable.w);
    intr_enable.w = READ_REG(OCH_SEP_TOP_SPI_CONTROLLER_INTR_ENABLE_BASE_ADDR);
    if (!check_reg("INTR_ENABLE all disabled", intr_enable.w, 0)) pass = 0;

    WRITE_REG(OCH_SEP_TOP_SPI_CONTROLLER_INTR_STATE_BASE_ADDR, 0xFFFFFFFF);
    intr_test.w = 0;
    intr_test.f.ERROR = 1;
    WRITE_REG(OCH_SEP_TOP_SPI_CONTROLLER_INTR_TEST_BASE_ADDR, intr_test.w);
    intr_status.w = READ_REG(OCH_SEP_TOP_SPI_CONTROLLER_INTR_STATE_BASE_ADDR);
    if (!check_reg("INTR_STATE.error=1 with INTR_ENABLE.error=0", intr_status.f.ERROR, 1)) pass = 0;

    intr_test.w = 0;
    WRITE_REG(OCH_SEP_TOP_SPI_CONTROLLER_INTR_TEST_BASE_ADDR, intr_test.w);
    WRITE_REG(OCH_SEP_TOP_SPI_CONTROLLER_INTR_STATE_BASE_ADDR, 0xFFFFFFFF);

    /* Step 5b: same for spi_event. INTR_ENABLE is still 0 from step 5. */
    printf("\nStep 5b: spi_event with INTR_ENABLE.spi_event=0\n");
    intr_test.w = 0;
    intr_test.f.SPI_EVENT = 1;
    WRITE_REG(OCH_SEP_TOP_SPI_CONTROLLER_INTR_TEST_BASE_ADDR, intr_test.w);
    intr_status.w = READ_REG(OCH_SEP_TOP_SPI_CONTROLLER_INTR_STATE_BASE_ADDR);
    if (!check_reg("INTR_STATE.spi_event=1 with INTR_ENABLE.spi_event=0",
                   intr_status.f.SPI_EVENT, 1))
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
