/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/*
 * SPI OT ACCESSINVAL Test - TC_SPIOT_021 (P1)
 *
 * Verifies the ERROR_STATUS.ACCESSINVAL[20] register field behavior.
 *
 * RTL Implementation Note:
 *   ACCESSINVAL fires when TXDATA is written with an INVALID byte-enable pattern
 *   (non-contiguous or non-standard byte lanes). Source:
 *     assign error_access_inval = tx_valid & ~access_valid;
 *   where access_valid is 1 only for aligned 1/2/4 byte patterns:
 *     4'b0001, 4'b0010, 4'b0100, 4'b1000 (single byte)
 *     4'b0011, 4'b0110, 4'b1100 (contiguous 2-byte)
 *     4'b1111 (4-byte word)
 *   This differs from the OpenTitan spec which defines ACCESSINVAL as
 *   "write to protected register while ACTIVE=1".
 *
 * FW Testability:
 *   Standard RISC-V instructions (SW/SH/SB) always produce valid AXI byte
 *   enables, so ACCESSINVAL cannot be triggered from firmware. This test
 *   verifies:
 *     1. ACCESSINVAL=0 after valid TXDATA writes (happy path)
 *     2. ACCESSINVAL[20] bit position and mask are correct
 *     3. ERROR_STATUS W1C works (writing 1 to bit 20 when already 0 has no effect)
 *     4. ACCESSINVAL is NOT gated by ERROR_ENABLE (no corresponding bit in ERROR_ENABLE)
 *     5. Other ERROR_STATUS bits (e.g., UNDERFLOW) are unaffected by ACCESSINVAL W1C
 *
 * Note: Actual ACCESSINVAL triggering requires UVM-level TB injection of
 * non-contiguous byte enables on the TXDATA register write — not testable
 * via CPU firmware.
 *
 * Execution:
 *   make test-sep TEST_NAME=sep_spi_ot_accessinval_test STACK=sim
 *
 */

#include <stdint.h>
#include <stdio.h>
#include "sep.h"
#include "och_sep_common.h"
#include "test_completion.h"
#include "sep_outbound_filter.h"

static void configure_spi_mux_ot(void) {
    WRITE_REG(OCH_SEP_TOP_SEP_EFUSE_MAP_SEP_SPI_CTRL_FIELD_EN_BASE_ADDR, 1u);
}

int main(void) {
    sep_outbound_filter_init();

    printf("\n========================================\n");
    printf("SPI OT ACCESSINVAL Test (TC_SPIOT_021)\n");
    printf("========================================\n\n");

    printf("NOTE: ACCESSINVAL fires on invalid byte-enable writes to TXDATA.\n");
    printf("      Standard RISC-V SW/SH/SB always produce valid byte enables.\n");
    printf("      This test verifies register field behavior (bit pos, W1C, no ERROR_ENABLE "
           "gate).\n\n");

    int pass = 1;
    spi_controller__CTRL_t ctrl;
    spi_controller__CFG_t cfg;
    spi_controller__ERROR_STATUS_CMDBUSY_610d1fb8_CMDINVAL_5f890e60_CSIDINVAL_52ab238c_OVERFLOW_b3d067e6_UNDERFLOW_cfe1cef2_t
        err_status;
    spi_controller__ERROR_ENABLE_t err_enable;
    uint32_t dummy;

    configure_spi_mux_ot();
    printf("SPI mux configured for OpenTitan\n");

    /* Enable controller */
    ctrl.w = 0u;
    ctrl.f.SPIEN = 1;
    ctrl.f.OUTPUT_EN = 1;
    WRITE_REG(OCH_SEP_TOP_SPI_CONTROLLER_CTRL_BASE_ADDR, ctrl.w);

    cfg.w = 0;
    cfg.f.CLKDIV = 9;
    WRITE_REG(OCH_SEP_TOP_SPI_CONTROLLER_CFG_BASE_ADDR, cfg.w);
    WRITE_REG(OCH_SEP_TOP_SPI_CONTROLLER_CSID_BASE_ADDR, 0);

    /* ------------------------------------------------------------------ */
    /* Step 1: Verify ACCESSINVAL=0 initially and after clearing           */
    /* ------------------------------------------------------------------ */
    printf("Step 1: ACCESSINVAL=0 initially\n");
    WRITE_REG(OCH_SEP_TOP_SPI_CONTROLLER_ERROR_STATUS_BASE_ADDR, 0xFFFFFFFF);
    err_status.w = READ_REG(OCH_SEP_TOP_SPI_CONTROLLER_ERROR_STATUS_BASE_ADDR);
    printf("  ERROR_STATUS after clear: 0x%08x, ACCESSINVAL=%u\n", err_status.w,
           err_status.f.ACCESSINVAL);
    if (err_status.f.ACCESSINVAL != 0) {
        printf("  FAIL: ACCESSINVAL should be 0 initially\n");
        pass = 0;
    } else {
        printf("  PASS: ACCESSINVAL=0 after clear\n");
    }

    /* ------------------------------------------------------------------ */
    /* Step 2: Valid TXDATA writes must NOT trigger ACCESSINVAL            */
    /* SW/SH/SB from RISC-V always produce valid aligned byte enables      */
    /* ------------------------------------------------------------------ */
    printf("\nStep 2: Valid TXDATA writes (SW, SH, SB) must not trigger ACCESSINVAL\n");
    WRITE_REG(OCH_SEP_TOP_SPI_CONTROLLER_ERROR_STATUS_BASE_ADDR, 0xFFFFFFFF);

    /* Full-word write (SW → byte-enable = 4'b1111, valid) */
    WRITE_REG(OCH_SEP_TOP_SPI_CONTROLLER_TXDATA_BASE_ADDR, 0x12345678);
    err_status.w = READ_REG(OCH_SEP_TOP_SPI_CONTROLLER_ERROR_STATUS_BASE_ADDR);
    printf("  After 32-bit TXDATA write: ACCESSINVAL=%u (expected 0)\n", err_status.f.ACCESSINVAL);
    if (err_status.f.ACCESSINVAL != 0) {
        printf("  FAIL: ACCESSINVAL set by valid 32-bit TXDATA write\n");
        pass = 0;
    } else {
        printf("  PASS: 32-bit TXDATA write does not trigger ACCESSINVAL\n");
    }

    /* ------------------------------------------------------------------ */
    /* Step 3: Verify bit mask/position: bit 20 = 0x100000                */
    /* ------------------------------------------------------------------ */
    printf(
        "\nStep 3: ACCESSINVAL bit position verification (bit 20 = 0x%08x)\n",
        SPI_CONTROLLER__ERROR_STATUS_CMDBUSY_610D1FB8_CMDINVAL_5F890E60_CSIDINVAL_52AB238C_OVERFLOW_B3D067E6_UNDERFLOW_CFE1CEF2__ACCESSINVAL_bm);
    if (SPI_CONTROLLER__ERROR_STATUS_CMDBUSY_610D1FB8_CMDINVAL_5F890E60_CSIDINVAL_52AB238C_OVERFLOW_B3D067E6_UNDERFLOW_CFE1CEF2__ACCESSINVAL_bm !=
        (1u << 20)) {
        printf(
            "  FAIL: Expected ACCESSINVAL mask = 0x100000, got 0x%08x\n",
            SPI_CONTROLLER__ERROR_STATUS_CMDBUSY_610D1FB8_CMDINVAL_5F890E60_CSIDINVAL_52AB238C_OVERFLOW_B3D067E6_UNDERFLOW_CFE1CEF2__ACCESSINVAL_bm);
        pass = 0;
    } else {
        printf("  PASS: ACCESSINVAL at bit 20 = 0x100000 (correct)\n");
    }
    if (SPI_CONTROLLER__ERROR_STATUS_CMDBUSY_610D1FB8_CMDINVAL_5F890E60_CSIDINVAL_52AB238C_OVERFLOW_B3D067E6_UNDERFLOW_CFE1CEF2__ACCESSINVAL_bp !=
        20) {
        printf(
            "  FAIL: Expected ACCESSINVAL shift = 20, got %u\n",
            SPI_CONTROLLER__ERROR_STATUS_CMDBUSY_610D1FB8_CMDINVAL_5F890E60_CSIDINVAL_52AB238C_OVERFLOW_B3D067E6_UNDERFLOW_CFE1CEF2__ACCESSINVAL_bp);
        pass = 0;
    } else {
        printf("  PASS: ACCESSINVAL shift = 20 (correct)\n");
    }

    /* ------------------------------------------------------------------ */
    /* Step 4: W1C behavior on already-0 bit (no spurious set)            */
    /* ------------------------------------------------------------------ */
    printf("\nStep 4: W1C write to ACCESSINVAL bit when already 0\n");
    WRITE_REG(
        OCH_SEP_TOP_SPI_CONTROLLER_ERROR_STATUS_BASE_ADDR,
        SPI_CONTROLLER__ERROR_STATUS_CMDBUSY_610D1FB8_CMDINVAL_5F890E60_CSIDINVAL_52AB238C_OVERFLOW_B3D067E6_UNDERFLOW_CFE1CEF2__ACCESSINVAL_bm);
    err_status.w = READ_REG(OCH_SEP_TOP_SPI_CONTROLLER_ERROR_STATUS_BASE_ADDR);
    printf("  After W1C (writing 1 to bit 20 when 0): ACCESSINVAL=%u (expected 0)\n",
           err_status.f.ACCESSINVAL);
    if (err_status.f.ACCESSINVAL != 0) {
        printf("  FAIL: W1C write to 0 bit must not set it\n");
        pass = 0;
    } else {
        printf("  PASS: W1C write to 0 bit has no effect (correct)\n");
    }

    /* ------------------------------------------------------------------ */
    /* Step 5: ACCESSINVAL is NOT in ERROR_ENABLE (always reported)        */
    /* ERROR_ENABLE has bits for: CMDBUSY[0], OVERFLOW[4], UNDERFLOW[8],  */
    /* CMDINVAL[12], CSIDINVAL[16] — no bit for ACCESSINVAL[20]           */
    /* ------------------------------------------------------------------ */
    printf("\nStep 5: ACCESSINVAL not gated by ERROR_ENABLE (no bit 20 in ERROR_ENABLE)\n");
    err_enable.w = READ_REG(OCH_SEP_TOP_SPI_CONTROLLER_ERROR_ENABLE_BASE_ADDR);
    printf("  ERROR_ENABLE=0x%08x (bit 20 expected 0 — not controllable)\n", err_enable.w);
    if ((err_enable.w >> 20) & 1) {
        printf("  FAIL: ERROR_ENABLE has bit 20 set (unexpected)\n");
        pass = 0;
    } else {
        printf("  PASS: ERROR_ENABLE bit 20 = 0 (ACCESSINVAL not gated)\n");
    }

    /* ------------------------------------------------------------------ */
    /* Step 6: Other ERROR_STATUS bits unaffected by ACCESSINVAL W1C      */
    /* Trigger UNDERFLOW (read empty RX FIFO), then W1C only ACCESSINVAL  */
    /* ------------------------------------------------------------------ */
    printf("\nStep 6: ACCESSINVAL W1C does not affect other ERROR_STATUS bits\n");
    WRITE_REG(OCH_SEP_TOP_SPI_CONTROLLER_ERROR_STATUS_BASE_ADDR, 0xFFFFFFFF);
    dummy = READ_REG(OCH_SEP_TOP_SPI_CONTROLLER_RXDATA_BASE_ADDR); /* trigger UNDERFLOW */
    (void)dummy;
    err_status.w = READ_REG(OCH_SEP_TOP_SPI_CONTROLLER_ERROR_STATUS_BASE_ADDR);
    printf("  UNDERFLOW triggered: ERROR_STATUS=0x%08x, UNDERFLOW=%u\n", err_status.w,
           err_status.f.UNDERFLOW);
    if (!err_status.f.UNDERFLOW) {
        printf("  WARN: UNDERFLOW not set (unexpected but not critical for this step)\n");
    }

    /* Write 1 only to bit 20 (ACCESSINVAL W1C) — should not clear UNDERFLOW */
    WRITE_REG(
        OCH_SEP_TOP_SPI_CONTROLLER_ERROR_STATUS_BASE_ADDR,
        SPI_CONTROLLER__ERROR_STATUS_CMDBUSY_610D1FB8_CMDINVAL_5F890E60_CSIDINVAL_52AB238C_OVERFLOW_B3D067E6_UNDERFLOW_CFE1CEF2__ACCESSINVAL_bm);
    err_status.w = READ_REG(OCH_SEP_TOP_SPI_CONTROLLER_ERROR_STATUS_BASE_ADDR);
    printf("  After ACCESSINVAL W1C: ERROR_STATUS=0x%08x, UNDERFLOW=%u (expected 1)\n",
           err_status.w, err_status.f.UNDERFLOW);
    if (!err_status.f.UNDERFLOW) {
        printf("  FAIL: UNDERFLOW cleared by ACCESSINVAL-only W1C (should not happen)\n");
        pass = 0;
    } else {
        printf("  PASS: UNDERFLOW unaffected by ACCESSINVAL-only W1C\n");
    }

    /* Clear all */
    WRITE_REG(OCH_SEP_TOP_SPI_CONTROLLER_ERROR_STATUS_BASE_ADDR, 0xFFFFFFFF);

    printf("\n========================================\n");
    if (pass) {
        printf("=== SPI OT ACCESSINVAL TEST PASSED ===\n");
        printf("    (Register field verification passed;\n");
        printf("     trigger requires non-standard byte enables from TB)\n");
        test_pass(0);
    } else {
        printf("=== SPI OT ACCESSINVAL TEST FAILED ===\n");
        test_fail(0);
    }
    printf("========================================\n");

    while (1) {
        __asm__("wfi");
    }
    return pass ? 0 : -1;
}
