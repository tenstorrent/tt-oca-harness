/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/*
 * SPI OT Flash JEDEC ID Test
 *
 * Issues a standard JEDEC Read ID command (0x9F) to the SPI flash device
 * using a two-segment transaction on the OpenTitan SPI controller.
 *
 * Signal path: OT SPI Controller -> GPIO pads -> Flash model
 *
 * TX byte packing (LITTLE_ENDIAN=1): TXDATA[7:0] is transmitted first.
 * WRITE_REG(TXDATA, 0x0000009F) -> sends 0x9F on the bus
 * RX byte ordering: RXDATA[7:0] = first byte received from device.
 * byte[0] = manufacturer ID, byte[1] = memory type, byte[2] = capacity
 *
 * Test Flow:
 * 1. Enable controller
 * 2. Segment 1: TX 0x9F (JEDEC ID cmd), CSAAT=1
 * 3. Segment 2: RX 3 bytes (MFR + type + capacity), CSAAT=0
 * 4. Read and log JEDEC response from RXDATA
 * 5. Verify no SPI controller errors (CMDINVAL, CSIDINVAL)
 *
 * Note: Requires SPI flash model (+spi_device_sel=winbond) for PASS.
 * Without flash model the test fails closed on empty/all-0xFF JEDEC response.
 */

#include <stdint.h>
#include <stdio.h>
#include "sep.h"
#include "och_sep_common.h"
#include "test_completion.h"
#include "sep_outbound_filter.h"
#include "spi_clk.h"

#define SPI_CLKDIV spi_clkdiv()
#define TIMEOUT_LIMIT 200000

/* Flash commands */
#define FLASH_CMD_JEDEC_ID 0x9F

/* Expected JEDEC ID for +spi_device_sel=4 (Winbond W25Q512JV): EF 40 20, the
 * same device the other flash tests enrol. */
#define JEDEC_MFR_WINBOND 0xEF
#define JEDEC_TYPE_W25Q512JV 0x40
#define JEDEC_CAP_W25Q512JV 0x20
#define JEDEC_MFR_MICRON 0x20
#define JEDEC_MFR_MACRONIX 0xC2

static void init_spi_controller(void) {
    spi_controller__CONTROL_t ctrl;
    ctrl.w = SPI_CONTROLLER__CONTROL_reset;
    ctrl.f.SPIEN = 1;
    ctrl.f.OUTPUT_EN = 1;
    WRITE_REG(SEP_TOP_SPI_CONTROLLER_CONTROL_BASE_ADDR, ctrl.w);

    spi_controller__CONFIGOPTS_t cfg;
    cfg.w = 0;
    cfg.f.CLKDIV = SPI_CLKDIV;
    cfg.f.CPOL = 0;
    cfg.f.CPHA = 0;
    cfg.f.CSNIDLE = 2;
    cfg.f.CSNLEAD = 2;
    cfg.f.CSNTRAIL = 2;
    WRITE_REG(SEP_TOP_SPI_CONTROLLER_CONFIGOPTS_BASE_ADDR, cfg.w);

    WRITE_REG(SEP_TOP_SPI_CONTROLLER_CSID_BASE_ADDR, 0);
    WRITE_REG(SEP_TOP_SPI_CONTROLLER_ERROR_STATUS_BASE_ADDR, 0xFFFFFFFF);
}

static int wait_for_ready(int timeout) {
    spi_controller__STATUS_t status;
    while (timeout-- > 0) {
        status.w = READ_REG(SEP_TOP_SPI_CONTROLLER_STATUS_BASE_ADDR);
        if (status.f.READY) return 0;
    }
    printf("  TIMEOUT waiting for READY\n");
    return -1;
}

static int wait_for_idle(int timeout) {
    spi_controller__STATUS_t status;
    while (timeout-- > 0) {
        status.w = READ_REG(SEP_TOP_SPI_CONTROLLER_STATUS_BASE_ADDR);
        if (!status.f.ACTIVE) return 0;
    }
    printf("  TIMEOUT waiting for ACTIVE=0\n");
    return -1;
}

int main(void) {
    sep_outbound_filter_init();

    printf("\n========================================\n");
    printf("SPI OT Flash JEDEC ID Test\n");
    printf("========================================\n\n");

    int pass = 1;

    init_spi_controller();
    printf("SPI controller enabled: CLKDIV=%d, CPOL=0, CPHA=0\n\n", SPI_CLKDIV);

    spi_controller__COMMAND_t cmd;

    /* ----------------------------------------------------------------
     * Segment 1: TX JEDEC ID command (0x9F), keep CS low
     * TX byte packing: TXDATA[7:0] sent first -> write 0x0000009F
     * ---------------------------------------------------------------- */
    printf("Step 1: TX JEDEC ID command (0x9F), CSAAT=1\n");
    if (wait_for_ready(TIMEOUT_LIMIT)) {
        pass = 0;
        goto done;
    }

    WRITE_REG(SEP_TOP_SPI_CONTROLLER_TXDATA_BASE_ADDR(0), (uint32_t)FLASH_CMD_JEDEC_ID);

    cmd.w = 0;
    cmd.f.LEN = 0;       /* 1 byte */
    cmd.f.CSAAT = 1;     /* keep CS# low */
    cmd.f.SPEED = 0;     /* Standard SPI */
    cmd.f.DIRECTION = 2; /* TX only */
    WRITE_REG(SEP_TOP_SPI_CONTROLLER_COMMAND_BASE_ADDR, cmd.w);
    printf("  CMD: DIR=TX, SPEED=Std, LEN=0(1B), CSAAT=1\n");

    /* ----------------------------------------------------------------
     * Segment 2: RX 3 bytes (manufacturer + type + capacity), release CS
     * ---------------------------------------------------------------- */
    printf("\nStep 2: RX 3 bytes JEDEC response, CSAAT=0\n");
    if (wait_for_ready(TIMEOUT_LIMIT)) {
        pass = 0;
        goto done;
    }

    cmd.w = 0;
    cmd.f.LEN = 2;       /* 3 bytes */
    cmd.f.CSAAT = 0;     /* release CS# after */
    cmd.f.SPEED = 0;     /* Standard SPI */
    cmd.f.DIRECTION = 1; /* RX only */
    WRITE_REG(SEP_TOP_SPI_CONTROLLER_COMMAND_BASE_ADDR, cmd.w);
    printf("  CMD: DIR=RX, SPEED=Std, LEN=2(3B), CSAAT=0\n");

    if (wait_for_idle(TIMEOUT_LIMIT)) {
        printf("  FAIL: transaction did not complete (ACTIVE stuck / no SPI device)\n");
        pass = 0;
        goto done;
    }

    /* ----------------------------------------------------------------
     * Read and decode JEDEC response from RX FIFO
     * RXDATA[7:0]=MFR, [15:8]=mem_type, [23:16]=capacity
     * ---------------------------------------------------------------- */
    printf("\nStep 3: Read JEDEC response from RXDATA\n");
    spi_controller__STATUS_t status;
    status.w = READ_REG(SEP_TOP_SPI_CONTROLLER_STATUS_BASE_ADDR);
    printf("  RXQD=%u, RXEMPTY=%u\n", status.f.RXQD, status.f.RXEMPTY);

    uint8_t mfr_id = 0xFF, mem_type = 0xFF, capacity = 0xFF;
    if (status.f.RXQD < 1) {
        printf("  FAIL: RX FIFO empty after JEDEC transaction (RXQD=%u)\n", status.f.RXQD);
        pass = 0;
        goto done;
    }
    {
        uint32_t rxdata = READ_REG(SEP_TOP_SPI_CONTROLLER_RXDATA_BASE_ADDR(0));
        mfr_id = (uint8_t)(rxdata & 0xFF);
        mem_type = (uint8_t)((rxdata >> 8) & 0xFF);
        capacity = (uint8_t)((rxdata >> 16) & 0xFF);
        printf("  JEDEC raw: 0x%08x\n", rxdata);
        printf("  Manufacturer ID : 0x%02x", mfr_id);
        if (mfr_id == JEDEC_MFR_WINBOND)
            printf(" (Winbond)");
        else if (mfr_id == JEDEC_MFR_MICRON)
            printf(" (Micron)");
        else if (mfr_id == JEDEC_MFR_MACRONIX)
            printf(" (Macronix)");
        printf("\n");
        printf("  Memory Type     : 0x%02x\n", mem_type);
        printf("  Capacity        : 0x%02x\n", capacity);

        if (mfr_id == 0xFF && mem_type == 0xFF && capacity == 0xFF) {
            printf("  FAIL: All 0xFF JEDEC response (no flash model / incomplete SPI path)\n");
            pass = 0;
        } else if (mfr_id != JEDEC_MFR_WINBOND || mem_type != JEDEC_TYPE_W25Q512JV ||
                   capacity != JEDEC_CAP_W25Q512JV) {
            printf("  FAIL: JEDEC expected Winbond W25Q512JV EF/40/20 "
                   "(+spi_device_sel=4), got %02x/%02x/%02x\n",
                   mfr_id, mem_type, capacity);
            pass = 0;
        } else {
            printf("  PASS: JEDEC matches Winbond W25Q512JV (EF 40 20)\n");
        }
    }

    /* ----------------------------------------------------------------
     * Step 4: Verify no critical SPI controller errors
     * ---------------------------------------------------------------- */
    printf("\nStep 4: Check SPI error status\n");
    spi_controller__ERROR_STATUS_t err;
    err.w = READ_REG(SEP_TOP_SPI_CONTROLLER_ERROR_STATUS_BASE_ADDR);
    printf("  ERROR_STATUS=0x%08x\n", err.w);
    if (err.f.CMDINVAL) {
        printf("  FAIL: CMDINVAL (invalid speed/direction combination)\n");
        pass = 0;
    }
    if (err.f.CSIDINVAL) {
        printf("  FAIL: CSIDINVAL (CSID exceeds NUM_CS)\n");
        pass = 0;
    }
    if (!err.f.CMDINVAL && !err.f.CSIDINVAL) {
        printf("  No critical controller errors\n");
    }

done:
    printf("\n========================================\n");
    if (pass) {
        printf("=== SPI OT FLASH JEDEC ID TEST PASSED ===\n");
        test_pass(0);
    } else {
        printf("=== SPI OT FLASH JEDEC ID TEST FAILED ===\n");
        test_fail(0);
    }
    printf("========================================\n");

    while (1) {
        __asm__("wfi");
    }
    return pass ? 0 : -1;
}
