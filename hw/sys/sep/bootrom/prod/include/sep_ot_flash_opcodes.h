/*
 * SPI-NOR flash opcode constants for the OpenTitan SPI bootcode driver.
 *
 * Values are the standard JEDEC SPI-NOR opcodes and mirror the set defined in
 * upstream OpenTitan sw/device/lib/testing/spi_device_testutils.h
 * (kSpiDeviceFlashOp*). The numeric opcodes are industry-standard; this header
 * is an independent, project-local restatement for the SEP boot ROM.
 *
 * Upstream reference (Apache-2.0):
 *   Copyright lowRISC contributors (OpenTitan project).
 *   Licensed under the Apache License, Version 2.0, see LICENSE for details.
 *   SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
 */
#ifndef SEP_OT_FLASH_OPCODES_H
#define SEP_OT_FLASH_OPCODES_H

/* Reads (boot uses standard read 0x03 by default — 3-byte addr, 0 dummy). */
#define OT_SPI_OP_READ 0x03u         /* 3-byte addr, 0 dummy                 */
#define OT_SPI_OP_READ_FAST 0x0Bu    /* 3-byte addr, 8 dummy                 */
#define OT_SPI_OP_READ_DUAL 0x3Bu    /* dual-output, 8 dummy                 */
#define OT_SPI_OP_READ_QUAD 0x6Bu    /* quad-output, 8 dummy                 */
#define OT_SPI_OP_READ_4B 0x13u      /* 4-byte addr, 0 dummy                 */
#define OT_SPI_OP_READ_FAST_4B 0x0Cu /* 4-byte addr, 8 dummy                 */

/* Discovery / status. */
#define OT_SPI_OP_RDID 0x9Fu  /* JEDEC ID (RDID)                      */
#define OT_SPI_OP_SFDP 0x5Au  /* read SFDP (3 addr + 8 dummy)         */
#define OT_SPI_OP_RDSR1 0x05u /* read status-1 (WIP=bit0, WEL=bit1)   */

/* Write / erase — NOT used by boot; present for an optional general driver. */
#define OT_SPI_OP_WREN 0x06u
#define OT_SPI_OP_PP 0x02u /* page program                        */
#define OT_SPI_OP_SE 0x20u /* 4 KiB sector erase                  */

#endif /* SEP_OT_FLASH_OPCODES_H */
