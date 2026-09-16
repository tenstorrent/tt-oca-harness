/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/*
 * SPI OT Flash Dual Fast Read Test
 *
 * Verifies Flash Fast Read Dual Output (0x3B) using the OpenTitan SPI controller.
 * Requires a Quad SPI flash model (+spi_device_sel=winbond, W25Q512JV).
 *
 * Flash commands used:
 * 0x06 - WREN  (Write Enable)
 * 0x05 - RDSR  (Read Status Register-1)
 * 0x02 - PP    (Page Program, Standard SPI write)
 * 0x3B - DOFR  (Dual Output Fast Read: cmd+addr Standard, 8 dummy clocks, data Dual)
 *
 * Dual Output Fast Read (0x3B) segment breakdown:
 * Seg1: TX 4 bytes (cmd=0x3B + addr[23:0]), SPEED=Standard, CSAAT=1
 * Seg2: Dummy 1 byte (8 SCK clocks), SPEED=Standard, CSAAT=1
 * Seg3: RX 16 bytes, SPEED=Dual (IO0+IO1), CSAAT=0
 *
 * TX byte packing (LITTLE_ENDIAN=1): TXDATA[7:0] sent first.
 * cmd+addr: byte[0]=cmd, byte[1]=addr[23:16], byte[2]=addr[15:8], byte[3]=addr[7:0]
 *
 * Test Flow:
 * 1. PP 16 bytes at 0x002000 with pattern 0xD0xxxxxx
 * 2. WIP poll until page program complete
 * 3. DOFR 16 bytes from 0x002000 using 3-segment dual read
 * 4. Compare RX data against written pattern
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
#define FLASH_CMD_DOFR 0x3B /* Dual Output Fast Read */

/* Flash status bits */
#define FLASH_SR_WIP (1u << 0)

/* Use sector 2 (offset 0x002000) — distinct from other flash tests */
#define FLASH_TARGET_ADDR 0x002000

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

static uint32_t pack_cmd_addr(uint8_t flash_cmd, uint32_t addr) {
    return (uint32_t)flash_cmd | (((addr >> 16) & 0xFF) << 8) | (((addr >> 8) & 0xFF) << 16) |
           (((addr >> 0) & 0xFF) << 24);
}

int main(void) {
    sep_outbound_filter_init();

    printf("\n========================================\n");
    printf("SPI OT Flash Dual Fast Read Test\n");
    printf("Requires: +spi_device_sel=winbond (W25Q512JV)\n");
    printf("Target address: 0x%06x (sector 2)\n", FLASH_TARGET_ADDR);
    printf("========================================\n\n");

    int pass = 1;
    uint32_t i;
    spi_controller__CMD_t cmd;

    init_spi_controller();
    printf("SPI controller enabled (CLKDIV=%d)\n\n", SPI_CLKDIV);

    /* ---------------------------------------------------------------
     * Phase 1: Page Program (Standard SPI 0x02) to seed test data
     * --------------------------------------------------------------- */
    printf("Phase 1: Page Program at 0x%06x (Standard SPI)\n", FLASH_TARGET_ADDR);

    /* WREN */
    if (wait_for_ready(TIMEOUT_LIMIT)) {
        pass = 0;
        goto done;
    }
    WRITE_REG(OCH_SEP_TOP_SPI_CONTROLLER_TXDATA_BASE_ADDR, 0x00000006);
    cmd.w = 0;
    cmd.f.LEN = 0;
    cmd.f.CSAAT = 0;
    cmd.f.SPEED = 0;
    cmd.f.DIRECTION = 2;
    WRITE_REG(OCH_SEP_TOP_SPI_CONTROLLER_CMD_BASE_ADDR, cmd.w);
    if (wait_for_idle(TIMEOUT_LIMIT)) {
        pass = 0;
        goto done;
    }
    printf("  WREN issued\n");

    /* TX cmd+addr segment */
    if (wait_for_ready(TIMEOUT_LIMIT)) {
        pass = 0;
        goto done;
    }
    WRITE_REG(OCH_SEP_TOP_SPI_CONTROLLER_TXDATA_BASE_ADDR,
              pack_cmd_addr(FLASH_CMD_PP, FLASH_TARGET_ADDR));
    cmd.w = 0;
    cmd.f.LEN = 3;
    cmd.f.CSAAT = 1;
    cmd.f.SPEED = 0;
    cmd.f.DIRECTION = 2;
    WRITE_REG(OCH_SEP_TOP_SPI_CONTROLLER_CMD_BASE_ADDR, cmd.w);

    /* Load data pattern and TX data segment */
    if (wait_for_ready(TIMEOUT_LIMIT)) {
        pass = 0;
        goto done;
    }
    uint32_t tx_data[WRITE_LEN_BYTES / 4];
    for (i = 0; i < WRITE_LEN_BYTES / 4; i++) {
        tx_data[i] = 0xD0000000 | ((i & 0xFF) << 16) | ((~i & 0xFF) << 8) | (i & 0xFF);
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
    printf("  PP issued (pattern 0xD0xx~xx)\n");

    /* WIP poll */
    int poll_count = 0;
    while (poll_count < STATUS_POLL_LIMIT) {
        uint8_t sr = flash_read_status();
        poll_count++;
        if (sr == 0xFF) {
            printf("  FAIL: SR=0xFF while polling WIP (no flash model)\n");
            pass = 0;
            goto done;
        }
        if (!(sr & FLASH_SR_WIP)) {
            printf("  WIP=0 after %d polls (page program complete)\n", poll_count);
            break;
        }
        if (poll_count >= STATUS_POLL_LIMIT) {
            printf("  FAIL: Timeout waiting for WIP=0 (page program)\n");
            pass = 0;
            goto done;
        }
    }

    /* ---------------------------------------------------------------
     * Phase 2: Dual Output Fast Read (0x3B)
     * Seg1: TX 4 bytes (0x3B + addr), Standard, CSAAT=1
     * Seg2: Dummy 1 byte (8 clocks), Standard, CSAAT=1
     * Seg3: RX 16 bytes, Dual (SPEED=1), CSAAT=0
     * --------------------------------------------------------------- */
    printf("\nPhase 2: Dual Output Fast Read (0x3B) from 0x%06x\n", FLASH_TARGET_ADDR);

    if (wait_for_ready(TIMEOUT_LIMIT)) {
        pass = 0;
        goto done;
    }

    /* Seg1: TX cmd + addr (4 bytes, standard) */
    WRITE_REG(OCH_SEP_TOP_SPI_CONTROLLER_TXDATA_BASE_ADDR,
              pack_cmd_addr(FLASH_CMD_DOFR, FLASH_TARGET_ADDR));
    cmd.w = 0;
    cmd.f.LEN = 3;       /* 4 bytes */
    cmd.f.CSAAT = 1;     /* keep CS# asserted */
    cmd.f.SPEED = 0;     /* Standard SPI */
    cmd.f.DIRECTION = 2; /* TX */
    WRITE_REG(OCH_SEP_TOP_SPI_CONTROLLER_CMD_BASE_ADDR, cmd.w);
    printf("  Seg1: TX 4B (0x3B + addr), Standard SPI\n");

    if (wait_for_ready(TIMEOUT_LIMIT)) {
        pass = 0;
        goto done;
    }

    /* Seg2: 8 dummy clocks (1 dummy byte at Standard speed) */
    cmd.w = 0;
    cmd.f.LEN = 7;       /* 8 dummy SCK pulses (direction=Dummy: len counts pulses, not bytes) */
    cmd.f.CSAAT = 1;     /* keep CS# asserted */
    cmd.f.SPEED = 0;     /* Standard SPI */
    cmd.f.DIRECTION = 0; /* Dummy */
    WRITE_REG(OCH_SEP_TOP_SPI_CONTROLLER_CMD_BASE_ADDR, cmd.w);
    printf("  Seg2: 8 dummy clocks (Standard SPI)\n");

    if (wait_for_ready(TIMEOUT_LIMIT)) {
        pass = 0;
        goto done;
    }

    /* Seg3: RX 16 bytes, Dual SPI (SPEED=1) */
    cmd.w = 0;
    cmd.f.LEN = WRITE_LEN_BYTES - 1; /* 16 bytes */
    cmd.f.CSAAT = 0;                 /* release CS# */
    cmd.f.SPEED = 1;                 /* Dual SPI */
    cmd.f.DIRECTION = 1;             /* RX */
    WRITE_REG(OCH_SEP_TOP_SPI_CONTROLLER_CMD_BASE_ADDR, cmd.w);
    printf("  Seg3: RX 16B, Dual SPI (SPEED=1)\n");

    if (wait_for_idle(TIMEOUT_LIMIT)) {
        pass = 0;
        goto done;
    }

    /* ---------------------------------------------------------------
     * Phase 3: Verify RX data matches written pattern
     * --------------------------------------------------------------- */
    printf("\nPhase 3: Verify dual-read data\n");

    spi_controller__STATUS_t spi_status;
    spi_status.w = READ_REG(OCH_SEP_TOP_SPI_CONTROLLER_STATUS_BASE_ADDR);
    printf("  RXQD=%u after dual read\n", spi_status.f.RXQD);

    uint32_t verify_fail = 0;
    for (i = 0; i < WRITE_LEN_BYTES / 4; i++) {
        spi_status.w = READ_REG(OCH_SEP_TOP_SPI_CONTROLLER_STATUS_BASE_ADDR);
        if (spi_status.f.RXEMPTY) {
            printf("  [%u] RX FIFO empty (underrun)\n", i);
            verify_fail++;
            continue;
        }
        uint32_t rx = READ_REG(OCH_SEP_TOP_SPI_CONTROLLER_RXDATA_BASE_ADDR);
        int match = (rx == tx_data[i]);
        int nomodel = (rx == 0xFFFFFFFF);
        printf("  [%u] exp=0x%08x got=0x%08x %s\n", i, tx_data[i], rx,
               match ? "OK" : (nomodel ? "WARN(nomodel/erased)" : "MISMATCH"));
        if (!match) verify_fail++;
    }

    if (verify_fail) {
        printf("  FAIL: %u word(s) mismatch (use +spi_device_sel=winbond)\n", verify_fail);
        pass = 0;
    } else {
        printf("  All %u words verified via Dual Output Fast Read\n", WRITE_LEN_BYTES / 4);
    }

    /* Check controller errors */
    spi_controller__ERROR_STATUS_t err;
    err.w = READ_REG(OCH_SEP_TOP_SPI_CONTROLLER_ERROR_STATUS_BASE_ADDR);
    if (err.f.CMDINVAL || err.f.CSIDINVAL) {
        printf("  FAIL: SPI controller error (cmdinval=%u, csidinval=%u)\n", err.f.CMDINVAL,
               err.f.CSIDINVAL);
        pass = 0;
    } else {
        printf("  No controller errors\n");
    }

done:
    printf("\n========================================\n");
    if (pass) {
        printf("=== SPI OT FLASH DUAL READ TEST PASSED ===\n");
        test_pass(0);
    } else {
        printf("=== SPI OT FLASH DUAL READ TEST FAILED ===\n");
        test_fail(0);
    }
    printf("========================================\n");

    while (1) {
        __asm__("wfi");
    }
    return pass ? 0 : -1;
}
