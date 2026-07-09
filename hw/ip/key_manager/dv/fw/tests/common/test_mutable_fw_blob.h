/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/* Copyright 2026 Tenstorrent Inc. */
/**
 * @file test_mutable_fw_blob.h
 * @brief Minimal mutable-firmware test blob for handover tests.
 *
 * This blob is a hand-assembled RISC-V rv32emc program that:
 *   - Starts executing at offset 0x00 (CPU address 0x4000)
 *   - Jumps past the IRQ handler slot to the main body at offset 0x30
 *   - Places an infinite-loop IRQ handler at offset 0x10 (0x4010)
 *   - In the main body: writes TEST_RESULT=1 and
 *     TEST_SIGNATURE=TEST_PASS_SIGNATURE to the KMCSR test registers,
 *     then spins in an infinite loop
 *
 * This is used by mutable-firmware handover tests to verify the blob
 * executes after CMD_SRAM_LOAD_EXEC and CMD_SRAM_EXEC.
 *
 * Layout (offsets from SRAM base 0x4000):
 *   0x0000  JAL  x0, +48   jump to main at 0x4030
 *   0x0004  NOP             (padding)
 *   0x0008  NOP
 *   0x000C  NOP
 *   0x0010  JAL  x0,  0    IRQ handler: infinite loop
 *   0x0014  NOP             (padding)
 *   0x0018  NOP
 *   0x001C  NOP
 *   0x0020  NOP
 *   0x0024  NOP
 *   0x0028  NOP
 *   0x002C  NOP
 *   0x0030  LUI  x5, 14             x5 = 0x0000_E000
 *   0x0034  ORI  x5, x5, 0x110      x5 = 0x0000_E110 (TB_RESULT_REG_ADDR)
 *   0x0038  ADDI x6, x0,  1         x6 = 1
 *   0x003C  SW   x6,  0(x5)         TEST_RESULT = 1
 *   0x0040  ADDI x5, x5,  4         x5 = 0x0000_E114 (TB_SIGNATURE_REG_ADDR)
 *   0x0044  LUI  x6, 0x600D6        x6 = 0x600D_6000
 *   0x0048  ADDI x6, x6, 13         x6 = 0x600D_600D (TEST_PASS_SIGNATURE)
 *   0x004C  SW   x6,  0(x5)         TEST_SIGNATURE = TEST_PASS_SIGNATURE
 *   0x0050  JAL  x0,  0             halt: infinite loop
 */

#ifndef TEST_MUTABLE_FW_BLOB_H
#define TEST_MUTABLE_FW_BLOB_H

#include <stdint.h>

/**
 * @brief Minimal mutable firmware blob.
 *
 * Each element is one 32-bit instruction word in little-endian order.
 */
static const uint32_t mutable_fw_blob[] = {
    0x0300006F, /* 0x4000: JAL x0, +48 → jump to main at 0x4030            */
    0x00000013, /* 0x4004: NOP                                               */
    0x00000013, /* 0x4008: NOP                                               */
    0x00000013, /* 0x400C: NOP                                               */
    0x0000006F, /* 0x4010: JAL x0, 0  → IRQ handler: infinite loop          */
    0x00000013, /* 0x4014: NOP                                               */
    0x00000013, /* 0x4018: NOP                                               */
    0x00000013, /* 0x401C: NOP                                               */
    0x00000013, /* 0x4020: NOP                                               */
    0x00000013, /* 0x4024: NOP                                               */
    0x00000013, /* 0x4028: NOP                                               */
    0x00000013, /* 0x402C: NOP                                               */
    0x0000E2B7, /* 0x4030: LUI  x5, 14       x5 = 0xE000                   */
    0x1102E293, /* 0x4034: ORI  x5,x5,0x110  x5 = 0xE110 (TB_RESULT)       */
    0x00100313, /* 0x4038: ADDI x6,x0,1      x6 = 1                        */
    0x0062A023, /* 0x403C: SW   x6,0(x5)     TEST_RESULT = 1               */
    0x00428293, /* 0x4040: ADDI x5,x5,4      x5 = 0xE114 (TB_SIGNATURE)    */
    0x600D6337, /* 0x4044: LUI  x6,0x600D6   x6 = 0x600D6000              */
    0x00D30313, /* 0x4048: ADDI x6,x6,13     x6 = 0x600D600D (PASS_SIG)   */
    0x0062A023, /* 0x404C: SW   x6,0(x5)     TEST_SIGNATURE = PASS_SIG    */
    0x0000006F, /* 0x4050: JAL  x0,0         halt: infinite loop           */
};

/** @brief Number of 32-bit words in mutable_fw_blob. */
#define MUTABLE_FW_BLOB_WORDS ((uint32_t)(sizeof(mutable_fw_blob) / sizeof(mutable_fw_blob[0])))

/**
 * @brief Compact 14-word mutable-firmware blob for FIFO-constrained load tests.
 *
 * Functionally identical to mutable_fw_blob but uses a tighter layout that
 * jumps directly to main at offset 0x14 (immediately after the IRQ slot at
 * 0x10), shrinking the image from 21 to 14 words.  This keeps the image frame
 * (14 words + 1 CRC = 15 words) within the 16-word mailbox FIFO depth limit.
 *
 * Layout (offsets from SRAM base 0x4000):
 *   0x0000  JAL  x0, +20   jump to main at 0x4014
 *   0x0004  NOP
 *   0x0008  NOP
 *   0x000C  NOP
 *   0x0010  JAL  x0,  0    IRQ handler: infinite loop
 *   0x0014  LUI  x5, 14    x5 = 0x0000_E000
 *   0x0018  ORI  x5, x5, 0x110   x5 = 0xE110 (TB_RESULT_REG_ADDR)
 *   0x001C  ADDI x6, x0, 1       x6 = 1
 *   0x0020  SW   x6, 0(x5)       TEST_RESULT = 1
 *   0x0024  ADDI x5, x5, 4       x5 = 0xE114 (TB_SIGNATURE_REG_ADDR)
 *   0x0028  LUI  x6, 0x600D6     x6 = 0x600D_6000
 *   0x002C  ADDI x6, x6, 13      x6 = 0x600D_600D (TEST_PASS_SIGNATURE)
 *   0x0030  SW   x6, 0(x5)       TEST_SIGNATURE = TEST_PASS_SIGNATURE
 *   0x0034  JAL  x0, 0           halt: infinite loop
 */
static const uint32_t mutable_fw_blob_small[] = {
    0x0140006F, /* 0x4000: JAL x0, +20 → jump to main at 0x4014           */
    0x00000013, /* 0x4004: NOP                                              */
    0x00000013, /* 0x4008: NOP                                              */
    0x00000013, /* 0x400C: NOP                                              */
    0x0000006F, /* 0x4010: JAL x0, 0  → IRQ handler: infinite loop         */
    0x0000E2B7, /* 0x4014: LUI  x5, 14       x5 = 0xE000                  */
    0x1102E293, /* 0x4018: ORI  x5,x5,0x110  x5 = 0xE110 (TB_RESULT)      */
    0x00100313, /* 0x401C: ADDI x6,x0,1      x6 = 1                       */
    0x0062A023, /* 0x4020: SW   x6,0(x5)     TEST_RESULT = 1              */
    0x00428293, /* 0x4024: ADDI x5,x5,4      x5 = 0xE114 (TB_SIGNATURE)   */
    0x600D6337, /* 0x4028: LUI  x6,0x600D6   x6 = 0x600D6000             */
    0x00D30313, /* 0x402C: ADDI x6,x6,13     x6 = 0x600D600D (PASS_SIG)  */
    0x0062A023, /* 0x4030: SW   x6,0(x5)     TEST_SIGNATURE = PASS_SIG   */
    0x0000006F, /* 0x4034: JAL  x0,0         halt: infinite loop          */
};

/** @brief Number of 32-bit words in mutable_fw_blob_small. */
#define MUTABLE_FW_BLOB_SMALL_WORDS \
    ((uint32_t)(sizeof(mutable_fw_blob_small) / sizeof(mutable_fw_blob_small[0])))

#endif /* TEST_MUTABLE_FW_BLOB_H */
