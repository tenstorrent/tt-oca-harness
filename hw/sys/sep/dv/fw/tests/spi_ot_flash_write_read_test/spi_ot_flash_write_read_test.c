/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/*
 * SPI OT Flash Write+Read Test
 *
 * Verifies a full SPI NOR flash write + read + verify cycle using the
 * OpenTitan SPI controller. Requires a Quad SPI flash model in the testbench.
 *
 * Run with: +spi_device_sel=winbond (Winbond W25Q512JV, JEDEC: EF 40 20)
 * OR +spi_device_sel=0 (Micron N25Q128,   JEDEC: 20 BA 18)
 *
 * Flash commands used:
 * 0x06 - WREN  (Write Enable, 1 byte TX, no address)
 * 0x05 - RDSR  (Read Status Register-1, 1 byte TX + 1 byte RX)
 * 0x02 - PP    (Page Program, 1 byte cmd + 3 byte addr + up to 256 bytes data)
 * 0x03 - READ  (Standard Read, 1 byte cmd + 3 byte addr, then RX data)
 *
 * TX byte packing (LITTLE_ENDIAN=1): TXDATA[7:0] is transmitted first.
 * cmd+addr packed as: byte[0]=cmd, byte[1]=addr[23:16], byte[2]=addr[15:8], byte[3]=addr[7:0]
 *
 * Test Flow:
 * 1. Enable controller
 * 2. WREN: Write Enable (0x06, 1 byte TX)
 * 3. RDSR: Read Status, verify WEL=1 (bit 1) to confirm write enable
 * 4. PP: Page Program (0x02 + addr 0x000000 + 16 bytes pattern), CSAAT
 * 5. RDSR poll: wait for WIP=0 (bit 0) - page program complete
 * 6. READ: Standard Read 16 bytes from 0x000000
 * 7. Verify read data matches written pattern
 *
 * Status Register-1 bits:
 * [0] WIP  (Write In Progress): 1=busy, 0=ready
 * [1] WEL  (Write Enable Latch): 1=write enabled
 *
 * Note: Requires flash model. Without flash model, status poll will timeout.
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
#define STATUS_POLL_LIMIT 500000 /* ~10ms at 50MHz core clock */
#define WRITE_LEN_BYTES 16       /* 4 words */

/* Flash commands */
#define FLASH_CMD_WREN 0x06
#define FLASH_CMD_RDSR 0x05
#define FLASH_CMD_PP 0x02
#define FLASH_CMD_READ 0x03

/* Flash status register bits */
#define FLASH_SR_WIP (1u << 0)
#define FLASH_SR_WEL (1u << 1)

/* Target flash address (page-aligned) */
#define FLASH_TARGET_ADDR 0x000000

static void init_spi_controller(void) {
    spi_controller__CTRL_t ctrl;
    ctrl.w = SPI_CONTROLLER__CTRL_reset;
    ctrl.f.SPIEN = 1;
    ctrl.f.OUTPUT_EN = 1;
    WRITE_REG(OCH_SEP_TOP_SPI_CONTROLLER_CTRL_BASE_ADDR, ctrl.w);

    spi_controller__CFG_t cfg;
    cfg.w = 0;
    cfg.f.CLKDIV = SPI_CLKDIV;
    cfg.f.CPOL = 0;
    cfg.f.CPHA = 0;
    cfg.f.CSNIDLE = 2;
    cfg.f.CSNLEAD = 2;
    cfg.f.CSNTRAIL = 2;
    WRITE_REG(OCH_SEP_TOP_SPI_CONTROLLER_CFG_BASE_ADDR, cfg.w);

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

/*
 * Read Status Register-1 (0x05).
 * Returns status byte, or 0xFF on timeout.
 */
static uint8_t flash_read_status(void) {
    spi_controller__CMD_t cmd;

    if (wait_for_ready(TIMEOUT_LIMIT)) return 0xFF;
    WRITE_REG(OCH_SEP_TOP_SPI_CONTROLLER_TXDATA_BASE_ADDR, 0x00000005);

    cmd.w = 0;
    cmd.f.LEN = 0; /* 1 byte */
    cmd.f.CSAAT = 1;
    cmd.f.SPEED = 0;
    cmd.f.DIRECTION = 2; /* TX */
    WRITE_REG(OCH_SEP_TOP_SPI_CONTROLLER_CMD_BASE_ADDR, cmd.w);

    if (wait_for_ready(TIMEOUT_LIMIT)) return 0xFF;

    cmd.w = 0;
    cmd.f.LEN = 0; /* 1 byte */
    cmd.f.CSAAT = 0;
    cmd.f.SPEED = 0;
    cmd.f.DIRECTION = 1; /* RX */
    WRITE_REG(OCH_SEP_TOP_SPI_CONTROLLER_CMD_BASE_ADDR, cmd.w);

    if (wait_for_idle(TIMEOUT_LIMIT)) return 0xFF;

    spi_controller__STATUS_t spi_status;
    spi_status.w = READ_REG(OCH_SEP_TOP_SPI_CONTROLLER_STATUS_BASE_ADDR);
    if (spi_status.f.RXQD >= 1) {
        uint32_t rxdata = READ_REG(OCH_SEP_TOP_SPI_CONTROLLER_RXDATA_BASE_ADDR);
        return (uint8_t)(rxdata & 0xFF);
    }
    return 0xFF;
}

int main(void) {
    sep_outbound_filter_init();

    printf("\n========================================\n");
    printf("SPI OT Flash Write+Read Test\n");
    printf("Requires: +spi_device_sel=winbond (W25Q512JV)\n");
    printf("========================================\n\n");

    int pass = 1;
    uint32_t i;
    spi_controller__CMD_t cmd;

    init_spi_controller();
    printf("SPI controller enabled: CLKDIV=%d\n\n", SPI_CLKDIV);

    /* ----------------------------------------------------------------
     * Step 1: Write Enable (WREN, 0x06)
     * Single 1-byte TX transaction, CSAAT=0
     * ---------------------------------------------------------------- */
    printf("Step 1: Write Enable (WREN 0x06)\n");
    if (wait_for_ready(TIMEOUT_LIMIT)) {
        pass = 0;
        goto done;
    }

    WRITE_REG(OCH_SEP_TOP_SPI_CONTROLLER_TXDATA_BASE_ADDR, 0x00000006);

    cmd.w = 0;
    cmd.f.LEN = 0;   /* 1 byte */
    cmd.f.CSAAT = 0; /* release CS after */
    cmd.f.SPEED = 0;
    cmd.f.DIRECTION = 2; /* TX */
    WRITE_REG(OCH_SEP_TOP_SPI_CONTROLLER_CMD_BASE_ADDR, cmd.w);

    if (wait_for_idle(TIMEOUT_LIMIT)) {
        pass = 0;
        goto done;
    }
    printf("  WREN issued\n");

    /* ----------------------------------------------------------------
     * Step 2: Read Status Register, verify WEL=1
     * ---------------------------------------------------------------- */
    printf("\nStep 2: Read Status Register, check WEL=1\n");
    uint8_t sr = flash_read_status();
    printf("  Status Register = 0x%02x (WEL=%u, WIP=%u)\n", sr, (sr >> 1) & 1, (sr >> 0) & 1);

    if (sr == 0xFF) {
        printf("  FAIL: Status 0xFF after WREN (no flash model / status unread)\n");
        pass = 0;
        goto done;
    } else if (!(sr & FLASH_SR_WEL)) {
        printf("  FAIL: WEL bit not set after WREN\n");
        pass = 0;
        goto done;
    } else {
        printf("  WEL=1 confirmed\n");
    }

    /* ----------------------------------------------------------------
     * Step 3: Page Program (PP, 0x02)
     * Segment 1: TX cmd+addr (4 bytes), CSAAT=1
     * Segment 2: TX data (16 bytes = 4 words), CSAAT=0
     * ---------------------------------------------------------------- */
    printf("\nStep 3: Page Program 0x02 at addr 0x%06x (%u bytes)\n", FLASH_TARGET_ADDR,
           WRITE_LEN_BYTES);

    if (wait_for_ready(TIMEOUT_LIMIT)) {
        pass = 0;
        goto done;
    }

    /* Pack cmd + address (byte[0]=cmd, byte[1]=addr[23:16], ...) */
    uint32_t pp_hdr = (FLASH_CMD_PP & 0xFF) | (((FLASH_TARGET_ADDR >> 16) & 0xFF) << 8) |
                      (((FLASH_TARGET_ADDR >> 8) & 0xFF) << 16) |
                      (((FLASH_TARGET_ADDR >> 0) & 0xFF) << 24);
    WRITE_REG(OCH_SEP_TOP_SPI_CONTROLLER_TXDATA_BASE_ADDR, pp_hdr);
    printf("  PP header TXDATA=0x%08x (cmd=0x02, addr=0x%06x)\n", pp_hdr, FLASH_TARGET_ADDR);

    cmd.w = 0;
    cmd.f.LEN = 3;   /* 4 bytes */
    cmd.f.CSAAT = 1; /* keep CS# for data */
    cmd.f.SPEED = 0;
    cmd.f.DIRECTION = 2; /* TX */
    WRITE_REG(OCH_SEP_TOP_SPI_CONTROLLER_CMD_BASE_ADDR, cmd.w);

    /* Load data pattern and issue data segment */
    if (wait_for_ready(TIMEOUT_LIMIT)) {
        pass = 0;
        goto done;
    }

    /* Data pattern: 0xCAxx0000 where xx = word index */
    uint32_t tx_data[WRITE_LEN_BYTES / 4];
    uint32_t num_words = WRITE_LEN_BYTES / 4;
    printf("  Writing data pattern:\n");
    for (i = 0; i < num_words; i++) {
        tx_data[i] = 0xCA000000 | ((i & 0xFF) << 16);
        WRITE_REG(OCH_SEP_TOP_SPI_CONTROLLER_TXDATA_BASE_ADDR, tx_data[i]);
        printf("    [%u] 0x%08x\n", i, tx_data[i]);
    }

    cmd.w = 0;
    cmd.f.LEN = WRITE_LEN_BYTES - 1; /* 16 bytes */
    cmd.f.CSAAT = 0;                 /* release CS */
    cmd.f.SPEED = 0;
    cmd.f.DIRECTION = 2; /* TX */
    WRITE_REG(OCH_SEP_TOP_SPI_CONTROLLER_CMD_BASE_ADDR, cmd.w);

    if (wait_for_idle(TIMEOUT_LIMIT)) {
        pass = 0;
        goto done;
    }
    printf("  Page Program command issued\n");

    /* ----------------------------------------------------------------
     * Step 4: Poll Status Register until WIP=0 (page program complete)
     * ---------------------------------------------------------------- */
    printf("\nStep 4: Poll Status Register for WIP=0 (page program done)\n");
    int poll_count = 0;
    int wip_done = 0;
    while (poll_count < STATUS_POLL_LIMIT) {
        sr = flash_read_status();
        poll_count++;
        if (sr == 0xFF) {
            printf("  FAIL: Status 0xFF while polling WIP (no flash model)\n");
            pass = 0;
            goto done;
        }
        if (!(sr & FLASH_SR_WIP)) {
            wip_done = 1;
            break;
        }
        if ((poll_count % 100) == 0) {
            printf("  ... polling (count=%d, SR=0x%02x)\n", poll_count, sr);
        }
    }
    if (!wip_done) {
        printf("  FAIL: Timeout waiting for WIP=0 after page program\n");
        pass = 0;
        goto done;
    }
    printf("  WIP=0 after %d polls (page program complete)\n", poll_count);

    /* ----------------------------------------------------------------
     * Step 5: Standard Read back WRITE_LEN_BYTES bytes
     * Segment 1: TX cmd+addr (4 bytes), CSAAT=1
     * Segment 2: RX 16 bytes, CSAAT=0
     * ---------------------------------------------------------------- */
    printf("\nStep 5: Read back %u bytes from addr 0x%06x\n", WRITE_LEN_BYTES, FLASH_TARGET_ADDR);

    if (wait_for_ready(TIMEOUT_LIMIT)) {
        pass = 0;
        goto done;
    }

    uint32_t read_hdr = (FLASH_CMD_READ & 0xFF) | (((FLASH_TARGET_ADDR >> 16) & 0xFF) << 8) |
                        (((FLASH_TARGET_ADDR >> 8) & 0xFF) << 16) |
                        (((FLASH_TARGET_ADDR >> 0) & 0xFF) << 24);
    WRITE_REG(OCH_SEP_TOP_SPI_CONTROLLER_TXDATA_BASE_ADDR, read_hdr);

    cmd.w = 0;
    cmd.f.LEN = 3; /* 4 bytes */
    cmd.f.CSAAT = 1;
    cmd.f.SPEED = 0;
    cmd.f.DIRECTION = 2; /* TX */
    WRITE_REG(OCH_SEP_TOP_SPI_CONTROLLER_CMD_BASE_ADDR, cmd.w);

    if (wait_for_ready(TIMEOUT_LIMIT)) {
        pass = 0;
        goto done;
    }

    cmd.w = 0;
    cmd.f.LEN = WRITE_LEN_BYTES - 1; /* 16 bytes */
    cmd.f.CSAAT = 0;
    cmd.f.SPEED = 0;
    cmd.f.DIRECTION = 1; /* RX */
    WRITE_REG(OCH_SEP_TOP_SPI_CONTROLLER_CMD_BASE_ADDR, cmd.w);

    if (wait_for_idle(TIMEOUT_LIMIT)) {
        pass = 0;
        goto done;
    }

    /* ----------------------------------------------------------------
     * Step 6: Verify read data matches written pattern
     * ---------------------------------------------------------------- */
    printf("\nStep 6: Verify read data\n");
    spi_controller__STATUS_t spi_status;
    spi_status.w = READ_REG(OCH_SEP_TOP_SPI_CONTROLLER_STATUS_BASE_ADDR);
    printf("  RXQD=%u\n", spi_status.f.RXQD);

    uint32_t verify_fail = 0;
    for (i = 0; i < num_words; i++) {
        if (spi_status.f.RXEMPTY) {
            printf("  [%u] RX FIFO empty (underrun)\n", i);
            verify_fail++;
            spi_status.w = READ_REG(OCH_SEP_TOP_SPI_CONTROLLER_STATUS_BASE_ADDR);
            continue;
        }
        uint32_t rx_word = READ_REG(OCH_SEP_TOP_SPI_CONTROLLER_RXDATA_BASE_ADDR);
        printf("  [%u] expected=0x%08x got=0x%08x %s\n", i, tx_data[i], rx_word,
               (rx_word == tx_data[i]) ? "OK" : "MISMATCH");
        if (rx_word != tx_data[i]) {
            if (rx_word == 0xFFFFFFFF) {
                printf("       (0xFF = erased/no flash model)\n");
            }
            verify_fail++;
        }
        spi_status.w = READ_REG(OCH_SEP_TOP_SPI_CONTROLLER_STATUS_BASE_ADDR);
    }

    if (verify_fail > 0) {
        printf("  FAIL: %u word(s) mismatch\n", verify_fail);
        printf("  NOTE: If no flash model, use +spi_device_sel=winbond for W25Q512JV\n");
        pass = 0;
    } else {
        printf("  All %u words verified\n", num_words);
    }

    /* ----------------------------------------------------------------
     * Final: Check SPI controller errors
     * ---------------------------------------------------------------- */
    printf("\nFinal: Check SPI error status\n");
    spi_controller__ERROR_STATUS_t err;
    err.w = READ_REG(OCH_SEP_TOP_SPI_CONTROLLER_ERROR_STATUS_BASE_ADDR);
    printf("  ERROR_STATUS=0x%08x\n", err.w);
    if (err.f.CMDINVAL || err.f.CSIDINVAL) {
        printf("  FAIL: controller error (cmdinval=%u, csidinval=%u)\n", err.f.CMDINVAL,
               err.f.CSIDINVAL);
        pass = 0;
    } else {
        printf("  No critical controller errors\n");
    }

done:
    printf("\n========================================\n");
    if (pass) {
        printf("=== SPI OT FLASH WRITE+READ TEST PASSED ===\n");
        test_pass(0);
    } else {
        printf("=== SPI OT FLASH WRITE+READ TEST FAILED ===\n");
        test_fail(0);
    }
    printf("========================================\n");

    while (1) {
        __asm__("wfi");
    }
    return pass ? 0 : -1;
}
