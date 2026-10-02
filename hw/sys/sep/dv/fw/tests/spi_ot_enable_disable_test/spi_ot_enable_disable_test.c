/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/*
 * SPI OT Enable/Disable Test
 *
 * Verifies that the SPI host control resets to zero, that the enable and
 * output-enable bits read back as written, and that software reset reads back
 * while held, drains the FIFOs and reads back clear after release. Status
 * after reset and after enable is logged, not checked.
 */

#include <stdint.h>
#include <stdio.h>
#include "sep.h"
#include "och_sep_common.h"
#include "test_completion.h"
#include "sep_outbound_filter.h"

#define TIMEOUT_LIMIT 100000

static int check_reg(const char *name, uint32_t actual, uint32_t expected) {
    int ok = (actual == expected);
    printf("  %s: 0x%08x (expected 0x%08x) - %s\n", name, actual, expected, ok ? "PASS" : "FAIL");
    return ok;
}

int main(void) {
    sep_outbound_filter_init();

    printf("\n========================================\n");
    printf("SPI OT Enable/Disable Test\n");
    printf("========================================\n\n");

    int pass = 1;
    spi_controller__CONTROL_t ctrl;
    spi_controller__STATUS_t status;

    printf("Step 1: CTRL default check\n");
    ctrl.w = READ_REG(SEP_TOP_SPI_CONTROLLER_CONTROL_BASE_ADDR);
    if (!check_reg("CTRL default", ctrl.w, 0u)) pass = 0;
    if (!check_reg("SPIEN default", ctrl.f.SPIEN, 0)) pass = 0;
    if (!check_reg("OUTPUT_EN default", ctrl.f.OUTPUT_EN, 0)) pass = 0;

    printf("\nStep 2: STATUS when SPIEN=0\n");
    status.w = READ_REG(SEP_TOP_SPI_CONTROLLER_STATUS_BASE_ADDR);
    printf("  STATUS=0x%08x (READY=%u, ACTIVE=%u, TXEMPTY=%u)\n", status.w, status.f.READY,
           status.f.ACTIVE, status.f.TXEMPTY);

    printf("\nStep 3: Enable SPI controller (SPIEN=1)\n");
    ctrl.w = SPI_CONTROLLER__CONTROL_reset;
    ctrl.f.SPIEN = 1;
    ctrl.f.OUTPUT_EN = 1;
    WRITE_REG(SEP_TOP_SPI_CONTROLLER_CONTROL_BASE_ADDR, ctrl.w);

    ctrl.w = READ_REG(SEP_TOP_SPI_CONTROLLER_CONTROL_BASE_ADDR);
    if (!check_reg("SPIEN after enable", ctrl.f.SPIEN, 1)) pass = 0;
    if (!check_reg("OUTPUT_EN after set", ctrl.f.OUTPUT_EN, 1)) pass = 0;

    status.w = READ_REG(SEP_TOP_SPI_CONTROLLER_STATUS_BASE_ADDR);
    printf("  STATUS after enable: 0x%08x (READY=%u, TXEMPTY=%u)\n", status.w, status.f.READY,
           status.f.TXEMPTY);

    /* Software reset is a level: the core stays in reset until software clears
     * it, so the drain is observed while it is held. */
    printf("\nStep 4: Software reset (SW_RST)\n");
    ctrl.w = READ_REG(SEP_TOP_SPI_CONTROLLER_CONTROL_BASE_ADDR);
    ctrl.f.SW_RST = 1;
    WRITE_REG(SEP_TOP_SPI_CONTROLLER_CONTROL_BASE_ADDR, ctrl.w);

    ctrl.w = READ_REG(SEP_TOP_SPI_CONTROLLER_CONTROL_BASE_ADDR);
    if (!check_reg("SW_RST reads 1 while held", ctrl.f.SW_RST, 1)) pass = 0;

    int t = TIMEOUT_LIMIT;
    while (t-- > 0) {
        status.w = READ_REG(SEP_TOP_SPI_CONTROLLER_STATUS_BASE_ADDR);
        if (status.f.TXEMPTY && status.f.RXEMPTY && !status.f.ACTIVE) break;
    }
    if (t <= 0) {
        printf("  FAIL: TIMEOUT draining the FIFOs under SW_RST (STATUS=0x%08x)\n",
               (unsigned)status.w);
        pass = 0;
    }
    printf("  STATUS after SW_RST: TXEMPTY=%u, RXEMPTY=%u, ACTIVE=%u\n", status.f.TXEMPTY,
           status.f.RXEMPTY, status.f.ACTIVE);

    ctrl.f.SW_RST = 0;
    WRITE_REG(SEP_TOP_SPI_CONTROLLER_CONTROL_BASE_ADDR, ctrl.w);
    ctrl.w = READ_REG(SEP_TOP_SPI_CONTROLLER_CONTROL_BASE_ADDR);
    if (!check_reg("SW_RST reads 0 after release", ctrl.f.SW_RST, 0)) pass = 0;

    printf("\nStep 5: Disable SPI controller (SPIEN=0)\n");
    ctrl.w = READ_REG(SEP_TOP_SPI_CONTROLLER_CONTROL_BASE_ADDR);
    ctrl.f.SPIEN = 0;
    ctrl.f.OUTPUT_EN = 0;
    WRITE_REG(SEP_TOP_SPI_CONTROLLER_CONTROL_BASE_ADDR, ctrl.w);

    ctrl.w = READ_REG(SEP_TOP_SPI_CONTROLLER_CONTROL_BASE_ADDR);
    if (!check_reg("SPIEN after disable", ctrl.f.SPIEN, 0)) pass = 0;
    if (!check_reg("OUTPUT_EN after clear", ctrl.f.OUTPUT_EN, 0)) pass = 0;

    printf("\n========================================\n");
    if (pass) {
        printf("=== SPI OT ENABLE/DISABLE TEST PASSED ===\n");
        test_pass(0);
    } else {
        printf("=== SPI OT ENABLE/DISABLE TEST FAILED ===\n");
        test_fail(0);
    }
    printf("========================================\n");

    while (1) {
        __asm__("wfi");
    }
}
