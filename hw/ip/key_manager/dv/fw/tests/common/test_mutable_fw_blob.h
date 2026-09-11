/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/* Copyright 2026 Tenstorrent Inc. */
/**
 * @file test_mutable_fw_blob.h
 * @brief Minimal mutable-firmware test blob for handover tests.
 *
 * This blob is a hand-assembled RISC-V rv32emc program that:
 *   - Starts executing at offset 0x00 (CPU address 0x8000)
 *   - Jumps past the IRQ handler slot to the main body at offset 0x30
 *   - Places an infinite-loop IRQ handler at offset 0x10 (0x8010)
 *   - In the main body: writes TEST_RESULT=1 and
 *     TEST_SIGNATURE=TEST_PASS_SIGNATURE to the KMCSR test registers,
 *     then spins in an infinite loop
 *
 * This is used by mutable-firmware handover tests to verify the blob
 * executes after CMD_SRAM_LOAD_EXEC and CMD_SRAM_EXEC.
 *
 * Every instruction is PC-relative or register-only apart from the LUI that
 * forms the KMCSR base, so moving the SRAM only changes the comments; moving
 * the KMCSR changes that one word.
 *
 * Layout (offsets from SRAM base 0x8000):
 *   0x0000  JAL  x0, +48   jump to main at 0x8030
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
 *   0x0030  LUI  x5, 0x14           x5 = 0x0001_4000
 *   0x0034  ORI  x5, x5, 0x110      x5 = 0x0001_4110 (TB_RESULT_REG_ADDR)
 *   0x0038  ADDI x6, x0,  1         x6 = 1
 *   0x003C  SW   x6,  0(x5)         TEST_RESULT = 1
 *   0x0040  ADDI x5, x5,  4         x5 = 0x0001_4114 (TB_SIGNATURE_REG_ADDR)
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
    0x0300006F, /* 0x8000: JAL x0, +48 → jump to main at 0x8030            */
    0x00000013, /* 0x8004: NOP                                               */
    0x00000013, /* 0x8008: NOP                                               */
    0x00000013, /* 0x800C: NOP                                               */
    0x0000006F, /* 0x8010: JAL x0, 0  → IRQ handler: infinite loop          */
    0x00000013, /* 0x8014: NOP                                               */
    0x00000013, /* 0x8018: NOP                                               */
    0x00000013, /* 0x801C: NOP                                               */
    0x00000013, /* 0x8020: NOP                                               */
    0x00000013, /* 0x8024: NOP                                               */
    0x00000013, /* 0x8028: NOP                                               */
    0x00000013, /* 0x802C: NOP                                               */
    0x000142B7, /* 0x8030: LUI  x5, 0x14     x5 = 0x14000                  */
    0x1102E293, /* 0x8034: ORI  x5,x5,0x110  x5 = 0x14110 (TB_RESULT)      */
    0x00100313, /* 0x8038: ADDI x6,x0,1      x6 = 1                        */
    0x0062A023, /* 0x803C: SW   x6,0(x5)     TEST_RESULT = 1               */
    0x00428293, /* 0x8040: ADDI x5,x5,4      x5 = 0x14114 (TB_SIGNATURE)   */
    0x600D6337, /* 0x8044: LUI  x6,0x600D6   x6 = 0x600D6000              */
    0x00D30313, /* 0x8048: ADDI x6,x6,13     x6 = 0x600D600D (PASS_SIG)   */
    0x0062A023, /* 0x804C: SW   x6,0(x5)     TEST_SIGNATURE = PASS_SIG    */
    0x0000006F, /* 0x8050: JAL  x0,0         halt: infinite loop           */
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
 * Layout (offsets from SRAM base 0x8000):
 *   0x0000  JAL  x0, +20   jump to main at 0x8014
 *   0x0004  NOP
 *   0x0008  NOP
 *   0x000C  NOP
 *   0x0010  JAL  x0,  0    IRQ handler: infinite loop
 *   0x0014  LUI  x5, 0x14  x5 = 0x0001_4000
 *   0x0018  ORI  x5, x5, 0x110   x5 = 0x14110 (TB_RESULT_REG_ADDR)
 *   0x001C  ADDI x6, x0, 1       x6 = 1
 *   0x0020  SW   x6, 0(x5)       TEST_RESULT = 1
 *   0x0024  ADDI x5, x5, 4       x5 = 0x14114 (TB_SIGNATURE_REG_ADDR)
 *   0x0028  LUI  x6, 0x600D6     x6 = 0x600D_6000
 *   0x002C  ADDI x6, x6, 13      x6 = 0x600D_600D (TEST_PASS_SIGNATURE)
 *   0x0030  SW   x6, 0(x5)       TEST_SIGNATURE = TEST_PASS_SIGNATURE
 *   0x0034  JAL  x0, 0           halt: infinite loop
 */
static const uint32_t mutable_fw_blob_small[] = {
    0x0140006F, /* 0x8000: JAL x0, +20 → jump to main at 0x8014           */
    0x00000013, /* 0x8004: NOP                                              */
    0x00000013, /* 0x8008: NOP                                              */
    0x00000013, /* 0x800C: NOP                                              */
    0x0000006F, /* 0x8010: JAL x0, 0  → IRQ handler: infinite loop         */
    0x000142B7, /* 0x8014: LUI  x5, 0x14     x5 = 0x14000                 */
    0x1102E293, /* 0x8018: ORI  x5,x5,0x110  x5 = 0x14110 (TB_RESULT)     */
    0x00100313, /* 0x801C: ADDI x6,x0,1      x6 = 1                       */
    0x0062A023, /* 0x8020: SW   x6,0(x5)     TEST_RESULT = 1              */
    0x00428293, /* 0x8024: ADDI x5,x5,4      x5 = 0x14114 (TB_SIGNATURE)  */
    0x600D6337, /* 0x8028: LUI  x6,0x600D6   x6 = 0x600D6000             */
    0x00D30313, /* 0x802C: ADDI x6,x6,13     x6 = 0x600D600D (PASS_SIG)  */
    0x0062A023, /* 0x8030: SW   x6,0(x5)     TEST_SIGNATURE = PASS_SIG   */
    0x0000006F, /* 0x8034: JAL  x0,0         halt: infinite loop          */
};

/** @brief Number of 32-bit words in mutable_fw_blob_small. */
#define MUTABLE_FW_BLOB_SMALL_WORDS \
    ((uint32_t)(sizeof(mutable_fw_blob_small) / sizeof(mutable_fw_blob_small[0])))

/**
 * @brief Mutable-firmware blob that reads the ROM and reports what it got.
 *
 * The ROM lockout engages on the fetch that lands here, so the load at 0x8014
 * must come back as zero rather than as the ROM word really stored at 0x10.
 * That address is used because the IRQ vector lives in physical ROM in every
 * link mode, so it holds real, non-zero, parity-valid code; the host test reads
 * the same word before handing over to establish the contrast.
 *
 * A blocked read is not a trap — zero is a legitimate data value — so the blob
 * survives to report.  TEST_RESULT carries the comparison result, so a readable
 * ROM fails the test instead of hanging it.
 *
 * Layout (offsets from SRAM base 0x8000):
 *   0x0000  JAL   x0, +20      jump to main at 0x8014
 *   0x0004  NOP
 *   0x0008  NOP
 *   0x000C  NOP
 *   0x0010  JAL   x0,  0       IRQ handler: infinite loop
 *   0x0014  LW    x7, 16(x0)   x7 = *(uint32_t *)0x10 (ROM IRQ vector word)
 *   0x0018  LUI   x5, 0x14     x5 = 0x0001_4000
 *   0x001C  ORI   x5, x5, 0x110  x5 = 0x0001_4110 (TB_RESULT_REG_ADDR)
 *   0x0020  SLTIU x6, x7, 1    x6 = (x7 == 0)
 *   0x0024  SW    x6,  0(x5)   TEST_RESULT = ROM read was blocked
 *   0x0028  ADDI  x5, x5,  4   x5 = 0x0001_4114 (TB_SIGNATURE_REG_ADDR)
 *   0x002C  LUI   x6, 0x600D6  x6 = 0x600D_6000
 *   0x0030  ADDI  x6, x6, 13   x6 = 0x600D_600D (TEST_PASS_SIGNATURE)
 *   0x0034  SW    x6,  0(x5)   TEST_SIGNATURE = completion marker
 *   0x0038  JAL   x0,  0       halt: infinite loop
 */
static const uint32_t mutable_fw_blob_rom_read[] = {
    0x0140006F, /* 0x8000: JAL x0, +20 → jump to main at 0x8014           */
    0x00000013, /* 0x8004: NOP                                              */
    0x00000013, /* 0x8008: NOP                                              */
    0x00000013, /* 0x800C: NOP                                              */
    0x0000006F, /* 0x8010: JAL x0, 0  → IRQ handler: infinite loop         */
    0x01002383, /* 0x8014: LW   x7,16(x0)    x7 = ROM word at 0x10        */
    0x000142B7, /* 0x8018: LUI  x5, 0x14     x5 = 0x14000                 */
    0x1102E293, /* 0x801C: ORI  x5,x5,0x110  x5 = 0x14110 (TB_RESULT)     */
    0x0013B313, /* 0x8020: SLTIU x6,x7,1     x6 = (x7 == 0)               */
    0x0062A023, /* 0x8024: SW   x6,0(x5)     TEST_RESULT = read blocked   */
    0x00428293, /* 0x8028: ADDI x5,x5,4      x5 = 0x14114 (TB_SIGNATURE)  */
    0x600D6337, /* 0x802C: LUI  x6,0x600D6   x6 = 0x600D6000             */
    0x00D30313, /* 0x8030: ADDI x6,x6,13     x6 = 0x600D600D (PASS_SIG)  */
    0x0062A023, /* 0x8034: SW   x6,0(x5)     TEST_SIGNATURE = PASS_SIG   */
    0x0000006F, /* 0x8038: JAL  x0,0         halt: infinite loop          */
};

/** @brief Number of 32-bit words in mutable_fw_blob_rom_read. */
#define MUTABLE_FW_BLOB_ROM_READ_WORDS \
    ((uint32_t)(sizeof(mutable_fw_blob_rom_read) / sizeof(mutable_fw_blob_rom_read[0])))

/**
 * @brief Mutable-firmware blob that jumps back into the ROM.
 *
 * Models the code-reuse attack the lockout exists to stop.  The jump target is
 * the ROM reset vector, so if the ROM were still executable the KM would simply
 * restart and the test would fail by timeout rather than by silent success.
 *
 * With the lockout engaged the fetch returns zeros, which CATCH_ILLINSN traps.
 * Handover has already masked every interrupt, so the core takes the trap state
 * directly: it halts, unrecoverable_err asserts, and the KPV is wiped.  No fault
 * code reaches the mailbox, because the ISR that would send one is in the ROM
 * that has just been revoked.
 *
 * Layout (offsets from SRAM base 0x8000):
 *   0x0000  JAL  x0, +20    jump to main at 0x8014
 *   0x0004  NOP
 *   0x0008  NOP
 *   0x000C  NOP
 *   0x0010  JAL  x0,  0     IRQ handler: infinite loop
 *   0x0014  JALR x0, 0(x0)  jump to physical 0x0 (ROM reset vector)
 */
static const uint32_t mutable_fw_blob_rom_fetch[] = {
    0x0140006F, /* 0x8000: JAL x0, +20 → jump to main at 0x8014           */
    0x00000013, /* 0x8004: NOP                                              */
    0x00000013, /* 0x8008: NOP                                              */
    0x00000013, /* 0x800C: NOP                                              */
    0x0000006F, /* 0x8010: JAL x0, 0  → IRQ handler: infinite loop         */
    0x00000067, /* 0x8014: JALR x0,0(x0)     jump into the revoked ROM     */
};

/** @brief Number of 32-bit words in mutable_fw_blob_rom_fetch. */
#define MUTABLE_FW_BLOB_ROM_FETCH_WORDS \
    ((uint32_t)(sizeof(mutable_fw_blob_rom_fetch) / sizeof(mutable_fw_blob_rom_fetch[0])))

#endif /* TEST_MUTABLE_FW_BLOB_H */
