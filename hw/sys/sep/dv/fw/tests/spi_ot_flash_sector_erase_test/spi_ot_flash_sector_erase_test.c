/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/*
 * SPI OT Flash Sector Erase Test
 *
 * Verifies 4KB Sector Erase (0x20) using the OpenTitan SPI controller.
 * Requires a Quad SPI flash model (+spi_device_sel=winbond, W25Q512JV).
 *
 * Flash commands used:
 * 0x06 - WREN  (Write Enable)
 * 0x05 - RDSR  (Read Status Register-1)
 * 0x02 - PP    (Page Program)
 * 0x20 - SE    (Sector Erase, 4KB)
 * 0x03 - READ  (Standard Read)
 *
 * Test Flow:
 * 1. PP 16 bytes at sector 0x001000 with pattern 0xBExxxx00
 * 2. WIP poll until program complete
 * 3. READ 16 bytes, verify data matches written pattern
 * 4. WREN + Sector Erase (0x20) at 0x001000
 * 5. WIP poll until erase complete
 * 6. READ 16 bytes, verify all 0xFFFFFFFF
 *
 * TX byte packing (LITTLE_ENDIAN=1): TXDATA[7:0] sent first.
 * cmd+addr: byte[0]=cmd, byte[1]=addr[23:16], byte[2]=addr[15:8], byte[3]=addr[7:0]
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
#define STATUS_POLL_LIMIT 500000
#define WRITE_LEN_BYTES 16

/* Flash commands */
#define FLASH_CMD_WREN 0x06
#define FLASH_CMD_RDSR 0x05
#define FLASH_CMD_PP 0x02
#define FLASH_CMD_SE 0x20
#define FLASH_CMD_READ 0x03

/* Flash status bits */
#define FLASH_SR_WIP (1u << 0)
#define FLASH_SR_WEL (1u << 1)

/* Use sector 1 (offset 0x001000) to avoid collision with flash_write_read_test */
#define FLASH_TARGET_ADDR 0x001000

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
    spi_controller__STATUS_t s;
    while (timeout-- > 0) {
        s.w = READ_REG(OCH_SEP_TOP_SPI_CONTROLLER_STATUS_BASE_ADDR);
        if (s.f.READY) return 0;
    }
    printf("  TIMEOUT waiting for READY\n");
    return -1;
}

static int wait_for_idle(int timeout) {
    spi_controller__STATUS_t s;
    while (timeout-- > 0) {
        s.w = READ_REG(OCH_SEP_TOP_SPI_CONTROLLER_STATUS_BASE_ADDR);
        if (!s.f.ACTIVE) return 0;
    }
    printf("  TIMEOUT waiting for ACTIVE=0\n");
    return -1;
}

/* Read Status Register-1 (0x05); returns 0xFF on error/no model */
static uint8_t flash_read_status(void) {
    spi_controller__CMD_t cmd;

    if (wait_for_ready(TIMEOUT_LIMIT)) return 0xFF;
    WRITE_REG(OCH_SEP_TOP_SPI_CONTROLLER_TXDATA_BASE_ADDR, 0x00000005);

    cmd.w = 0;
    cmd.f.LEN = 0;
    cmd.f.CSAAT = 1;
    cmd.f.SPEED = 0;
    cmd.f.DIRECTION = 2;
    WRITE_REG(OCH_SEP_TOP_SPI_CONTROLLER_CMD_BASE_ADDR, cmd.w);

    if (wait_for_ready(TIMEOUT_LIMIT)) return 0xFF;

    cmd.w = 0;
    cmd.f.LEN = 0;
    cmd.f.CSAAT = 0;
    cmd.f.SPEED = 0;
    cmd.f.DIRECTION = 1;
    WRITE_REG(OCH_SEP_TOP_SPI_CONTROLLER_CMD_BASE_ADDR, cmd.w);

    if (wait_for_idle(TIMEOUT_LIMIT)) return 0xFF;

    spi_controller__STATUS_t s;
    s.w = READ_REG(OCH_SEP_TOP_SPI_CONTROLLER_STATUS_BASE_ADDR);
    if (s.f.RXQD >= 1)
        return (uint8_t)(READ_REG(OCH_SEP_TOP_SPI_CONTROLLER_RXDATA_BASE_ADDR) & 0xFF);
    return 0xFF;
}

/* Issue Write Enable (0x06) */
static int flash_wren(void) {
    spi_controller__CMD_t cmd;
    if (wait_for_ready(TIMEOUT_LIMIT)) return -1;
    WRITE_REG(OCH_SEP_TOP_SPI_CONTROLLER_TXDATA_BASE_ADDR, 0x00000006);
    cmd.w = 0;
    cmd.f.LEN = 0;
    cmd.f.CSAAT = 0;
    cmd.f.SPEED = 0;
    cmd.f.DIRECTION = 2;
    WRITE_REG(OCH_SEP_TOP_SPI_CONTROLLER_CMD_BASE_ADDR, cmd.w);
    return wait_for_idle(TIMEOUT_LIMIT);
}

/* Pack cmd + 24-bit addr into a 32-bit TXDATA word (LITTLE_ENDIAN format) */
static uint32_t pack_cmd_addr(uint8_t flash_cmd, uint32_t addr) {
    return (uint32_t)flash_cmd | (((addr >> 16) & 0xFF) << 8) | (((addr >> 8) & 0xFF) << 16) |
           (((addr >> 0) & 0xFF) << 24);
}

/* Poll WIP bit until clear; returns 0 on success, -1 on timeout / bad status.
 * SR==0xFF means status read failed or no flash model — must fail closed. */
static int flash_wait_wip(const char *op_name) {
    int poll_count = 0;
    while (poll_count < STATUS_POLL_LIMIT) {
        uint8_t sr = flash_read_status();
        poll_count++;
        if (sr == 0xFF) {
            printf("  FAIL: SR=0xFF while waiting for WIP=0 (%s); "
                   "status unread/no flash model — require +spi_device_sel\n",
                   op_name);
            return -1;
        }
        if (!(sr & FLASH_SR_WIP)) {
            printf("  WIP=0 after %d polls (%s complete)\n", poll_count, op_name);
            return 0;
        }
        if ((poll_count % 200) == 0)
            printf("  ... %s polling (count=%d, SR=0x%02x)\n", op_name, poll_count, sr);
    }
    printf("  FAIL: Timeout waiting for WIP=0 (%s)\n", op_name);
    return -1;
}

int main(void) {
    sep_outbound_filter_init();

    printf("\n========================================\n");
    printf("SPI OT Flash Sector Erase Test\n");
    printf("Requires: +spi_device_sel=winbond (W25Q512JV)\n");
    printf("Target address: 0x%06x (sector 1)\n", FLASH_TARGET_ADDR);
    printf("========================================\n\n");

    int pass = 1;
    uint32_t i;
    spi_controller__CMD_t cmd;

    init_spi_controller();
    printf("SPI controller enabled (CLKDIV=%d)\n\n", SPI_CLKDIV);

    /* ---------------------------------------------------------------
     * Phase 1: Page Program 16 bytes to mark the sector as written
     * --------------------------------------------------------------- */
    printf("Phase 1: Write 16 bytes at 0x%06x via Page Program\n", FLASH_TARGET_ADDR);

    if (flash_wren()) {
        pass = 0;
        goto done;
    }
    printf("  WREN issued\n");

    if (wait_for_ready(TIMEOUT_LIMIT)) {
        pass = 0;
        goto done;
    }

    uint32_t pp_hdr = pack_cmd_addr(FLASH_CMD_PP, FLASH_TARGET_ADDR);
    WRITE_REG(OCH_SEP_TOP_SPI_CONTROLLER_TXDATA_BASE_ADDR, pp_hdr);

    cmd.w = 0;
    cmd.f.LEN = 3;
    cmd.f.CSAAT = 1;
    cmd.f.SPEED = 0;
    cmd.f.DIRECTION = 2;
    WRITE_REG(OCH_SEP_TOP_SPI_CONTROLLER_CMD_BASE_ADDR, cmd.w);

    if (wait_for_ready(TIMEOUT_LIMIT)) {
        pass = 0;
        goto done;
    }

    uint32_t tx_data[WRITE_LEN_BYTES / 4];
    for (i = 0; i < WRITE_LEN_BYTES / 4; i++) {
        tx_data[i] = 0xBE000000 | ((i & 0xFF) << 16);
        WRITE_REG(OCH_SEP_TOP_SPI_CONTROLLER_TXDATA_BASE_ADDR, tx_data[i]);
    }

    cmd.w = 0;
    cmd.f.LEN = WRITE_LEN_BYTES - 1;
    cmd.f.CSAAT = 0;
    cmd.f.SPEED = 0;
    cmd.f.DIRECTION = 2;
    WRITE_REG(OCH_SEP_TOP_SPI_CONTROLLER_CMD_BASE_ADDR, cmd.w);

    if (wait_for_idle(TIMEOUT_LIMIT)) {
        pass = 0;
        goto done;
    }
    printf("  PP issued (pattern 0xBExx0000)\n");

    if (flash_wait_wip("page program")) {
        pass = 0;
        goto done;
    }

    /* ---------------------------------------------------------------
     * Phase 2: READ back and verify written data
     * --------------------------------------------------------------- */
    printf("\nPhase 2: READ back 16 bytes, verify written data\n");

    if (wait_for_ready(TIMEOUT_LIMIT)) {
        pass = 0;
        goto done;
    }
    WRITE_REG(OCH_SEP_TOP_SPI_CONTROLLER_TXDATA_BASE_ADDR,
              pack_cmd_addr(FLASH_CMD_READ, FLASH_TARGET_ADDR));

    cmd.w = 0;
    cmd.f.LEN = 3;
    cmd.f.CSAAT = 1;
    cmd.f.SPEED = 0;
    cmd.f.DIRECTION = 2;
    WRITE_REG(OCH_SEP_TOP_SPI_CONTROLLER_CMD_BASE_ADDR, cmd.w);

    if (wait_for_ready(TIMEOUT_LIMIT)) {
        pass = 0;
        goto done;
    }

    cmd.w = 0;
    cmd.f.LEN = WRITE_LEN_BYTES - 1;
    cmd.f.CSAAT = 0;
    cmd.f.SPEED = 0;
    cmd.f.DIRECTION = 1;
    WRITE_REG(OCH_SEP_TOP_SPI_CONTROLLER_CMD_BASE_ADDR, cmd.w);

    if (wait_for_idle(TIMEOUT_LIMIT)) {
        pass = 0;
        goto done;
    }

    uint32_t pre_erase_fail = 0;
    for (i = 0; i < WRITE_LEN_BYTES / 4; i++) {
        spi_controller__STATUS_t s;
        s.w = READ_REG(OCH_SEP_TOP_SPI_CONTROLLER_STATUS_BASE_ADDR);
        if (s.f.RXEMPTY) {
            pre_erase_fail++;
            continue;
        }
        uint32_t rx = READ_REG(OCH_SEP_TOP_SPI_CONTROLLER_RXDATA_BASE_ADDR);
        int match = (rx == tx_data[i]);
        int nomodel = (rx == 0xFFFFFFFF);
        printf("  [%u] exp=0x%08x got=0x%08x %s\n", i, tx_data[i], rx,
               match ? "OK" : (nomodel ? "WARN(nomodel)" : "MISMATCH"));
        if (!match) pre_erase_fail++;
    }
    if (pre_erase_fail) {
        printf("  FAIL: %u word(s) mismatch pre-erase "
               "(require flash model +spi_device_sel=winbond)\n",
               pre_erase_fail);
        pass = 0;
        goto done;
    }
    printf("  Pre-erase data verified OK\n");

    /* ---------------------------------------------------------------
     * Phase 3: Sector Erase (0x20) at FLASH_TARGET_ADDR
     * --------------------------------------------------------------- */
    printf("\nPhase 3: Sector Erase (0x20) at 0x%06x\n", FLASH_TARGET_ADDR);

    if (flash_wren()) {
        pass = 0;
        goto done;
    }
    printf("  WREN issued\n");

    /* Verify WEL=1 — SR==0xFF is not affirmative WEL proof */
    uint8_t sr = flash_read_status();
    if (sr == 0xFF) {
        printf("  FAIL: SR=0xFF after WREN (status unread/no flash model)\n");
        pass = 0;
        goto done;
    }
    if (!(sr & FLASH_SR_WEL)) {
        printf("  FAIL: WEL not set after WREN (SR=0x%02x)\n", sr);
        pass = 0;
        goto done;
    }
    printf("  WEL confirmed (SR=0x%02x)\n", sr);

    if (wait_for_ready(TIMEOUT_LIMIT)) {
        pass = 0;
        goto done;
    }
    WRITE_REG(OCH_SEP_TOP_SPI_CONTROLLER_TXDATA_BASE_ADDR,
              pack_cmd_addr(FLASH_CMD_SE, FLASH_TARGET_ADDR));

    cmd.w = 0;
    cmd.f.LEN = 3; /* 4 bytes: cmd + 3-byte addr */
    cmd.f.CSAAT = 0;
    cmd.f.SPEED = 0;
    cmd.f.DIRECTION = 2; /* TX */
    WRITE_REG(OCH_SEP_TOP_SPI_CONTROLLER_CMD_BASE_ADDR, cmd.w);

    if (wait_for_idle(TIMEOUT_LIMIT)) {
        pass = 0;
        goto done;
    }
    printf("  Sector Erase command issued\n");

    if (flash_wait_wip("sector erase")) {
        pass = 0;
        goto done;
    }

    /* ---------------------------------------------------------------
     * Phase 4: READ back and verify all bytes are 0xFF (erased)
     * --------------------------------------------------------------- */
    printf("\nPhase 4: READ back 16 bytes, verify all 0xFF (erased)\n");

    if (wait_for_ready(TIMEOUT_LIMIT)) {
        pass = 0;
        goto done;
    }
    WRITE_REG(OCH_SEP_TOP_SPI_CONTROLLER_TXDATA_BASE_ADDR,
              pack_cmd_addr(FLASH_CMD_READ, FLASH_TARGET_ADDR));

    cmd.w = 0;
    cmd.f.LEN = 3;
    cmd.f.CSAAT = 1;
    cmd.f.SPEED = 0;
    cmd.f.DIRECTION = 2;
    WRITE_REG(OCH_SEP_TOP_SPI_CONTROLLER_CMD_BASE_ADDR, cmd.w);

    if (wait_for_ready(TIMEOUT_LIMIT)) {
        pass = 0;
        goto done;
    }

    cmd.w = 0;
    cmd.f.LEN = WRITE_LEN_BYTES - 1;
    cmd.f.CSAAT = 0;
    cmd.f.SPEED = 0;
    cmd.f.DIRECTION = 1;
    WRITE_REG(OCH_SEP_TOP_SPI_CONTROLLER_CMD_BASE_ADDR, cmd.w);

    if (wait_for_idle(TIMEOUT_LIMIT)) {
        pass = 0;
        goto done;
    }

    uint32_t erase_fail = 0;
    for (i = 0; i < WRITE_LEN_BYTES / 4; i++) {
        spi_controller__STATUS_t s;
        s.w = READ_REG(OCH_SEP_TOP_SPI_CONTROLLER_STATUS_BASE_ADDR);
        if (s.f.RXEMPTY) {
            printf("  [%u] RX FIFO empty (underrun)\n", i);
            erase_fail++;
            continue;
        }
        uint32_t rx = READ_REG(OCH_SEP_TOP_SPI_CONTROLLER_RXDATA_BASE_ADDR);
        int erased = (rx == 0xFFFFFFFF);
        printf("  [%u] got=0x%08x %s\n", i, rx, erased ? "OK(erased)" : "FAIL(not erased)");
        if (!erased) erase_fail++;
    }
    if (erase_fail) {
        printf("  FAIL: %u word(s) not erased to 0xFF\n", erase_fail);
        pass = 0;
    } else {
        printf("  All %u words read back as 0xFF (erase verified)\n", WRITE_LEN_BYTES / 4);
    }

    /* Check controller errors */
    spi_controller__ERROR_STATUS_t err;
    err.w = READ_REG(OCH_SEP_TOP_SPI_CONTROLLER_ERROR_STATUS_BASE_ADDR);
    if (err.f.CMDINVAL || err.f.CSIDINVAL) {
        printf("  FAIL: SPI controller error (cmdinval=%u, csidinval=%u)\n", err.f.CMDINVAL,
               err.f.CSIDINVAL);
        pass = 0;
    }

done:
    printf("\n========================================\n");
    if (pass) {
        printf("=== SPI OT FLASH SECTOR ERASE TEST PASSED ===\n");
        test_pass(0);
    } else {
        printf("=== SPI OT FLASH SECTOR ERASE TEST FAILED ===\n");
        test_fail(0);
    }
    printf("========================================\n");

    while (1) {
        __asm__("wfi");
    }
    return pass ? 0 : -1;
}
