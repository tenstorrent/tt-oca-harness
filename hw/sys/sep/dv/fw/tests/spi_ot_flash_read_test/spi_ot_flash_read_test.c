/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/*
 * SPI OT Flash Read Test
 *
 * Issues a Standard Read command (0x03) to the SPI flash device using a
 * two-segment transaction on the OpenTitan SPI controller:
 * Segment 1: TX command byte (0x03) + 24-bit address (4 bytes total), CSAAT=1
 * Segment 2: RX 16 bytes of flash data, CSAAT=0
 *
 * TX byte packing (LITTLE_ENDIAN=1): TXDATA[7:0] is transmitted first.
 * Packing cmd=0x03 + addr=0x000000 into one 32-bit word:
 * byte[0]=cmd, byte[1]=addr[23:16], byte[2]=addr[15:8], byte[3]=addr[7:0]
 * => WRITE_REG(TXDATA, 0x00000003) -> sends 0x03, 0x00, 0x00, 0x00 in order
 *
 * Test Flow:
 * 1. Enable controller
 * 2. JEDEC presence proof (0x9F) against enrolled Winbond W25Q512JV
 * 3. Segment 1: TX 4 bytes (0x03 + addr 0x000000), CSAAT=1
 * 4. Segment 2: RX 16 bytes, CSAAT=0
 * 5. Compare RX words to erased 0xFFFFFFFF (only after JEDEC presence)
 * 6. Verify no SPI controller errors
 *
 * Requires enrolled +spi_device_sel=4 (Winbond W25Q512JV). JEDEC must match
 * EF/40/20 before the erased-page 0xFF golden is trusted — a floating-MISO
 * all-0xFF path fails the presence check.
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
#define READ_LEN_BYTES 16 /* 4 words */

/* Flash commands */
#define FLASH_CMD_READ 0x03
#define FLASH_CMD_JEDEC_ID 0x9F

/* Enrolled +spi_device_sel=4 = Winbond W25Q512JV (see flash_write_read_test). */
#define JEDEC_MFR_WINBOND 0xEF
#define JEDEC_TYPE_W25Q512JV 0x40
#define JEDEC_CAP_W25Q512JV 0x20

/* Read address (start of flash, typically erased = 0xFF) */
#define FLASH_READ_ADDR 0x000000

static void init_spi_controller(void) {
    spi_controller__CONTROL_t ctrl;
    ctrl.w = SPI_CONTROLLER__CONTROL_reset;
    ctrl.f.SPIEN = 1;
    ctrl.f.OUTPUT_EN = 1;
    WRITE_REG(OCH_SEP_TOP_SPI_CONTROLLER_CONTROL_BASE_ADDR, ctrl.w);

    spi_controller__CONFIGOPTS_t cfg;
    cfg.w = 0;
    cfg.f.CLKDIV = SPI_CLKDIV;
    cfg.f.CPOL = 0;
    cfg.f.CPHA = 0;
    cfg.f.CSNIDLE = 2;
    cfg.f.CSNLEAD = 2;
    cfg.f.CSNTRAIL = 2;
    WRITE_REG(OCH_SEP_TOP_SPI_CONTROLLER_CONFIGOPTS_BASE_ADDR, cfg.w);

    WRITE_REG(OCH_SEP_TOP_SPI_CONTROLLER_CSID_BASE_ADDR, 0);
    WRITE_REG(OCH_SEP_TOP_SPI_CONTROLLER_ERROR_STATUS_BASE_ADDR, 0xFFFFFFFF);
}

static int wait_for_ready(int timeout) {
    spi_controller__STATUS_t status;
    while (timeout-- > 0) {
        status.w = READ_REG(OCH_SEP_TOP_SPI_CONTROLLER_STATUS_BASE_ADDR);
        if (status.f.READY) return 0;
    }
    printf("  TIMEOUT waiting for READY\n");
    return -1;
}

static int wait_for_idle(int timeout) {
    spi_controller__STATUS_t status;
    while (timeout-- > 0) {
        status.w = READ_REG(OCH_SEP_TOP_SPI_CONTROLLER_STATUS_BASE_ADDR);
        if (!status.f.ACTIVE) return 0;
    }
    printf("  TIMEOUT waiting for ACTIVE=0\n");
    return -1;
}

int main(void) {
    sep_outbound_filter_init();

    printf("\n========================================\n");
    printf("SPI OT Flash Read Test\n");
    printf("========================================\n\n");

    int pass = 1;
    uint32_t i;

    init_spi_controller();
    printf("SPI controller enabled: CLKDIV=%d\n", SPI_CLKDIV);
    printf("Flash address: 0x%06x, Read length: %u bytes\n\n", FLASH_READ_ADDR, READ_LEN_BYTES);

    spi_controller__COMMAND_t cmd;

    /* ----------------------------------------------------------------
     * Step 0: JEDEC presence (fail closed if no flash peer / wrong device)
     * ---------------------------------------------------------------- */
    printf("Step 0: JEDEC presence (expect Winbond W25Q512JV EF 40 20)\n");
    if (wait_for_ready(TIMEOUT_LIMIT)) {
        pass = 0;
        goto done;
    }
    WRITE_REG(OCH_SEP_TOP_SPI_CONTROLLER_TXDATA_BASE_ADDR(0), FLASH_CMD_JEDEC_ID);
    cmd.w = 0;
    cmd.f.LEN = 0;
    cmd.f.CSAAT = 1;
    cmd.f.SPEED = 0;
    cmd.f.DIRECTION = 2;
    WRITE_REG(OCH_SEP_TOP_SPI_CONTROLLER_COMMAND_BASE_ADDR, cmd.w);
    if (wait_for_ready(TIMEOUT_LIMIT)) {
        pass = 0;
        goto done;
    }
    cmd.w = 0;
    cmd.f.LEN = 2; /* 3 bytes */
    cmd.f.CSAAT = 0;
    cmd.f.SPEED = 0;
    cmd.f.DIRECTION = 1;
    WRITE_REG(OCH_SEP_TOP_SPI_CONTROLLER_COMMAND_BASE_ADDR, cmd.w);
    if (wait_for_idle(TIMEOUT_LIMIT)) {
        pass = 0;
        goto done;
    }
    {
        spi_controller__STATUS_t st;
        st.w = READ_REG(OCH_SEP_TOP_SPI_CONTROLLER_STATUS_BASE_ADDR);
        if (st.f.RXQD < 1) {
            printf("  FAIL: empty RX after JEDEC (no flash peer)\n");
            pass = 0;
            goto done;
        }
        uint32_t jedec = READ_REG(OCH_SEP_TOP_SPI_CONTROLLER_RXDATA_BASE_ADDR(0));
        uint8_t mfr = (uint8_t)(jedec & 0xFF);
        uint8_t typ = (uint8_t)((jedec >> 8) & 0xFF);
        uint8_t cap = (uint8_t)((jedec >> 16) & 0xFF);
        printf("  JEDEC raw=0x%08x -> %02x/%02x/%02x\n", jedec, mfr, typ, cap);
        if (mfr != JEDEC_MFR_WINBOND || typ != JEDEC_TYPE_W25Q512JV || cap != JEDEC_CAP_W25Q512JV) {
            printf("  FAIL: flash presence/ID mismatch (cannot trust 0xFF golden)\n");
            pass = 0;
            goto done;
        }
        printf("  PASS: flash peer present (W25Q512JV)\n");
    }

    /* Drain any residual RX before READ (bounded SW_RST completion). SW_RST is
     * a level, so the release below is what lets the READ segments run. */
    {
        spi_controller__CONTROL_t c;
        spi_controller__STATUS_t st;
        int t = TIMEOUT_LIMIT;
        c.w = READ_REG(OCH_SEP_TOP_SPI_CONTROLLER_CONTROL_BASE_ADDR);
        c.f.SW_RST = 1;
        WRITE_REG(OCH_SEP_TOP_SPI_CONTROLLER_CONTROL_BASE_ADDR, c.w);
        while (t-- > 0) {
            st.w = READ_REG(OCH_SEP_TOP_SPI_CONTROLLER_STATUS_BASE_ADDR);
            if (st.f.RXEMPTY && st.f.TXEMPTY && !st.f.ACTIVE) break;
        }
        c.f.SW_RST = 0;
        WRITE_REG(OCH_SEP_TOP_SPI_CONTROLLER_CONTROL_BASE_ADDR, c.w);
        if (t <= 0) {
            printf("  FAIL: SW_RST drain timeout before READ\n");
            pass = 0;
            goto done;
        }
    }

    /* ----------------------------------------------------------------
     * Segment 1: TX READ command + 24-bit address (4 bytes total)
     *
     * TX byte packing: TXDATA[7:0] first.
     * Pack [cmd=0x03][addr_h=0x00][addr_m=0x00][addr_l=0x00] into 32-bit:
     * byte[0]=0x03, byte[1]=0x00, byte[2]=0x00, byte[3]=0x00
     * => TXDATA = 0x00_00_00_03
     * ---------------------------------------------------------------- */
    printf("Step 1: TX READ cmd (0x03) + addr 0x%06x (4 bytes), CSAAT=1\n", FLASH_READ_ADDR);
    if (wait_for_ready(TIMEOUT_LIMIT)) {
        pass = 0;
        goto done;
    }

    /* cmd byte in [7:0], addr MSB in [15:8], addr mid in [23:16], addr LSB in [31:24] */
    uint32_t tx_word = (FLASH_CMD_READ & 0xFF) | (((FLASH_READ_ADDR >> 16) & 0xFF) << 8) |
                       (((FLASH_READ_ADDR >> 8) & 0xFF) << 16) |
                       (((FLASH_READ_ADDR >> 0) & 0xFF) << 24);
    WRITE_REG(OCH_SEP_TOP_SPI_CONTROLLER_TXDATA_BASE_ADDR(0), tx_word);
    printf("  TXDATA=0x%08x (cmd=0x%02x, addr=0x%06x)\n", tx_word, FLASH_CMD_READ, FLASH_READ_ADDR);

    cmd.w = 0;
    cmd.f.LEN = 3;       /* 4 bytes (LEN+1) */
    cmd.f.CSAAT = 1;     /* keep CS# low for data phase */
    cmd.f.SPEED = 0;     /* Standard SPI */
    cmd.f.DIRECTION = 2; /* TX only */
    WRITE_REG(OCH_SEP_TOP_SPI_CONTROLLER_COMMAND_BASE_ADDR, cmd.w);
    printf("  CMD: DIR=TX, SPEED=Std, LEN=3(4B), CSAAT=1\n");

    /* ----------------------------------------------------------------
     * Segment 2: RX READ_LEN_BYTES bytes of flash data, release CS
     * ---------------------------------------------------------------- */
    printf("\nStep 2: RX %u bytes of flash data, CSAAT=0\n", READ_LEN_BYTES);
    if (wait_for_ready(TIMEOUT_LIMIT)) {
        pass = 0;
        goto done;
    }

    cmd.w = 0;
    cmd.f.LEN = READ_LEN_BYTES - 1; /* 16 bytes */
    cmd.f.CSAAT = 0;                /* release CS# after */
    cmd.f.SPEED = 0;                /* Standard SPI */
    cmd.f.DIRECTION = 1;            /* RX only */
    WRITE_REG(OCH_SEP_TOP_SPI_CONTROLLER_COMMAND_BASE_ADDR, cmd.w);
    printf("  CMD: DIR=RX, SPEED=Std, LEN=%u(%uB), CSAAT=0\n", READ_LEN_BYTES - 1, READ_LEN_BYTES);

    if (wait_for_idle(TIMEOUT_LIMIT)) {
        printf("  FAIL: transaction did not complete (ACTIVE stuck / no SPI device)\n");
        pass = 0;
        goto done;
    }

    /* ----------------------------------------------------------------
     * Read flash data from RX FIFO; erased page expects 0xFFFFFFFF/word.
     * Requires a real flash model — zero RX activity is FAIL.
     * ---------------------------------------------------------------- */
    printf("\nStep 3: Read %u words from RXDATA (expect erased 0xFF)\n", READ_LEN_BYTES / 4);
    spi_controller__STATUS_t status;
    status.w = READ_REG(OCH_SEP_TOP_SPI_CONTROLLER_STATUS_BASE_ADDR);
    printf("  RXQD=%u, RXEMPTY=%u\n", status.f.RXQD, status.f.RXEMPTY);

    uint32_t rx_words[READ_LEN_BYTES / 4];
    uint32_t num_words = READ_LEN_BYTES / 4;
    uint32_t words_read = 0;
    uint32_t mismatch = 0;

    for (i = 0; i < num_words; i++) {
        status.w = READ_REG(OCH_SEP_TOP_SPI_CONTROLLER_STATUS_BASE_ADDR);
        if (!status.f.RXEMPTY) {
            rx_words[i] = READ_REG(OCH_SEP_TOP_SPI_CONTROLLER_RXDATA_BASE_ADDR(0));
            printf("  [%u] 0x%08x  (bytes: %02x %02x %02x %02x)\n", i, rx_words[i],
                   (rx_words[i] >> 0) & 0xFF, (rx_words[i] >> 8) & 0xFF, (rx_words[i] >> 16) & 0xFF,
                   (rx_words[i] >> 24) & 0xFF);
            words_read++;
            if (rx_words[i] != 0xFFFFFFFFu) {
                printf("  FAIL: word[%u] not erased 0xFFFFFFFF\n", i);
                mismatch++;
            }
        } else {
            printf("  [%u] RX FIFO empty (underrun)\n", i);
            mismatch++;
        }
    }
    printf("  Read %u/%u words\n", words_read, num_words);

    if (words_read != num_words) {
        printf("  FAIL: expected %u RX words, got %u (require flash model)\n", num_words,
               words_read);
        pass = 0;
    } else if (mismatch) {
        printf("  FAIL: %u word(s) mismatch vs erased 0xFFFFFFFF\n", mismatch);
        pass = 0;
    } else {
        printf("  PASS: %u erased words verified\n", words_read);
    }

    /* ----------------------------------------------------------------
     * Step 4: Verify no critical SPI controller errors
     * ---------------------------------------------------------------- */
    printf("\nStep 4: Check SPI error status\n");
    spi_controller__ERROR_STATUS_t err;
    err.w = READ_REG(OCH_SEP_TOP_SPI_CONTROLLER_ERROR_STATUS_BASE_ADDR);
    printf("  ERROR_STATUS=0x%08x\n", err.w);
    if (err.f.CMDINVAL) {
        printf("  FAIL: CMDINVAL\n");
        pass = 0;
    }
    if (err.f.CSIDINVAL) {
        printf("  FAIL: CSIDINVAL\n");
        pass = 0;
    }
    if (!err.f.CMDINVAL && !err.f.CSIDINVAL) {
        printf("  No critical controller errors\n");
    }

done:
    printf("\n========================================\n");
    if (pass) {
        printf("=== SPI OT FLASH READ TEST PASSED ===\n");
        test_pass(0);
    } else {
        printf("=== SPI OT FLASH READ TEST FAILED ===\n");
        test_fail(0);
    }
    printf("========================================\n");

    while (1) {
        __asm__("wfi");
    }
    return pass ? 0 : -1;
}
