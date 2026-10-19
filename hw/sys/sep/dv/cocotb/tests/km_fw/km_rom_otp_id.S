# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
#
# KM ROM for sep_efuse_km_public_id_test. Not rom_main: no mailbox command
# returns the KMCSR public-ID OTP words, so only code running on the KM CPU
# can read them out.
#
# PicoRV32 is RV32E (x0-x15 only). Do not use x16+.
#
# The image grades nothing. It copies raw words and reduces two groups of
# words to one word each; the host test holds every golden, which it takes
# from the staged eFuse image.
#
#   1. Store 0 to KM SRAM word 0, so a host that waits for the marker after a
#      second release does not read the marker of the first run.
#   2. Copy the 48 KMCSR words OTP_SEP_CHIPLET_ID_VAL_0 .. OTP_SEP_SYS_ID_CPL_7,
#      in address order, to KM SRAM words 1..48.
#   3. For each secret field (OTP_CHIPLET_UID, OTP_SIP_UID, OTP_SYS_UID,
#      OTP_CLASS_KEY, in address order) copy its eight VAL words to KM SRAM
#      words 51..82, and store the AND over k of (VAL_k XOR CPL_k) to KM SRAM
#      words 83..86, one word per field.
#   4. Copy OTP_LIFE_CYCLE and OTP_DEMOTION_STATE to KM SRAM words 87 and 88.
#   5. Set OTP_READ_LOCK.SEP_CHIPLET_ID, .SEP_SIP_ID and .SEP_SYS_ID, and store
#      the register readback to KM SRAM word 50.
#   6. Store the OR of the same 48 public-ID words, read again, to KM SRAM
#      word 49.
#   7. Store DONE_MARKER to KM SRAM word 0, the km_sram_word0_o probe.
#
# Word 0 is written last, so a host that sees the marker reads complete dumps.
# The layout fits the 98 words of km_sram_probe_o. env/sep_km_otp_id.py holds
# the same layout for the host.
#
# Build (output committed as ../km_rom_otp_id.parhex):
#   make -C hw/sys/sep/dv/cocotb/tests/km_fw ../km_rom_otp_id.parhex

#include "key_manager_addr.h"
#include "km_fields.inc"

    .equ ID_BASE,       KEY_MANAGER_KMCSR_OTP_SEP_CHIPLET_ID_VAL_0_BASE_ADDR
    .equ ID_WORDS,      48

    # The copy walks one contiguous window: each field's eight value words,
    # then its eight complement words, the three fields back to back.
    .if KEY_MANAGER_KMCSR_OTP_SEP_CHIPLET_ID_CPL_0_BASE_ADDR != ID_BASE + 32
    .error "OTP_SEP_CHIPLET_ID_CPL_0 does not follow OTP_SEP_CHIPLET_ID_VAL_7"
    .endif
    .if KEY_MANAGER_KMCSR_OTP_SEP_SIP_ID_VAL_0_BASE_ADDR != ID_BASE + 64
    .error "OTP_SEP_SIP_ID_VAL_0 does not follow OTP_SEP_CHIPLET_ID_CPL_7"
    .endif
    .if KEY_MANAGER_KMCSR_OTP_SEP_SYS_ID_VAL_0_BASE_ADDR != ID_BASE + 128
    .error "OTP_SEP_SYS_ID_VAL_0 does not follow OTP_SEP_SIP_ID_CPL_7"
    .endif
    .if KEY_MANAGER_KMCSR_OTP_SEP_SYS_ID_CPL_7_BASE_ADDR != ID_BASE + 4 * (ID_WORDS - 1)
    .error "OTP_SEP_SYS_ID_CPL_7 is not the last word of the public-ID window"
    .endif

    .equ SECRET_BASE,   KEY_MANAGER_KMCSR_OTP_CHIPLET_UID_VAL_0_BASE_ADDR
    .equ SECRET_FIELDS, 4

    # Each secret field is eight value words, then eight complement words, the
    # four fields back to back.
    .if KEY_MANAGER_KMCSR_OTP_CHIPLET_UID_CPL_0_BASE_ADDR != SECRET_BASE + 32
    .error "OTP_CHIPLET_UID_CPL_0 does not follow OTP_CHIPLET_UID_VAL_7"
    .endif
    .if KEY_MANAGER_KMCSR_OTP_SIP_UID_VAL_0_BASE_ADDR != SECRET_BASE + 64
    .error "OTP_SIP_UID_VAL_0 does not follow OTP_CHIPLET_UID_CPL_7"
    .endif
    .if KEY_MANAGER_KMCSR_OTP_SYS_UID_VAL_0_BASE_ADDR != SECRET_BASE + 128
    .error "OTP_SYS_UID_VAL_0 does not follow OTP_SIP_UID_CPL_7"
    .endif
    .if KEY_MANAGER_KMCSR_OTP_CLASS_KEY_VAL_0_BASE_ADDR != SECRET_BASE + 192
    .error "OTP_CLASS_KEY_VAL_0 does not follow OTP_SYS_UID_CPL_7"
    .endif
    .if KEY_MANAGER_KMCSR_OTP_CLASS_KEY_CPL_7_BASE_ADDR != SECRET_BASE + 252
    .error "OTP_CLASS_KEY_CPL_7 is not the last word of the secret window"
    .endif

    .equ ID_LOCKS,      (KM_CSR__OTP_READ_LOCK_REG__SEP_CHIPLET_ID_bm | \
                         KM_CSR__OTP_READ_LOCK_REG__SEP_SIP_ID_bm | \
                         KM_CSR__OTP_READ_LOCK_REG__SEP_SYS_ID_bm)
    .equ DUMP_OPEN,     KEY_MANAGER_SRAM_BASE_ADDR + 4
    .equ LOCKED_OR,     KEY_MANAGER_SRAM_BASE_ADDR + 4 * 49
    .equ LOCK_READBACK, KEY_MANAGER_SRAM_BASE_ADDR + 4 * 50
    .equ SECRET_VAL,    KEY_MANAGER_SRAM_BASE_ADDR + 4 * 51
    .equ SECRET_RAIL,   KEY_MANAGER_SRAM_BASE_ADDR + 4 * 83
    .equ LIFE_CYCLE,    KEY_MANAGER_SRAM_BASE_ADDR + 4 * 87
    .equ DONE_MARKER,   0x1D1D1D1D

    .section .text
    .globl _start
_start:
    # x1  load pointer (KMCSR)
    # x2  KM SRAM store pointer
    # x3  OTP_READ_LOCK, then the rail store pointer
    # x4  lock mask, then its readback; rail accumulator
    # x5  copy count
    # x6  copied word
    # x7  load pointer of copy_ids; complement word
    # x8  field count
    # x9  OR accumulator
    # x13 return address
    li    x2, KEY_MANAGER_SRAM_BASE_ADDR
    sw    x0, 0(x2)

    li    x1, ID_BASE
    li    x2, DUMP_OPEN
    jal   x13, copy_ids

    li    x1, SECRET_BASE
    li    x2, SECRET_VAL
    li    x3, SECRET_RAIL
    li    x8, SECRET_FIELDS
3:  li    x4, -1
    li    x5, 8
4:  lw    x6, 0(x1)
    lw    x7, 32(x1)
    sw    x6, 0(x2)
    xor   x6, x6, x7
    and   x4, x4, x6
    addi  x1, x1, 4
    addi  x2, x2, 4
    addi  x5, x5, -1
    bnez  x5, 4b
    sw    x4, 0(x3)
    addi  x3, x3, 4
    addi  x1, x1, 32
    addi  x8, x8, -1
    bnez  x8, 3b

    li    x2, LIFE_CYCLE
    li    x1, KEY_MANAGER_KMCSR_OTP_LIFE_CYCLE_BASE_ADDR
    lw    x6, 0(x1)
    sw    x6, 0(x2)
    li    x1, KEY_MANAGER_KMCSR_OTP_DEMOTION_STATE_BASE_ADDR
    lw    x6, 0(x1)
    sw    x6, 4(x2)

    li    x3, KEY_MANAGER_KMCSR_OTP_READ_LOCK_BASE_ADDR
    li    x4, ID_LOCKS
    sw    x4, 0(x3)
    lw    x4, 0(x3)
    li    x2, LOCK_READBACK
    sw    x4, 0(x2)

    li    x1, ID_BASE
    li    x5, ID_WORDS
    li    x9, 0
5:  lw    x6, 0(x1)
    or    x9, x9, x6
    addi  x1, x1, 4
    addi  x5, x5, -1
    bnez  x5, 5b
    li    x2, LOCKED_OR
    sw    x9, 0(x2)

    li    x6, DONE_MARKER
    li    x2, KEY_MANAGER_SRAM_BASE_ADDR
    sw    x6, 0(x2)
1:  j     1b

    # Copy ID_WORDS words from the window at x1 to x2. x2 is left one word
    # past the last store.
copy_ids:
    mv    x7, x1
    li    x5, ID_WORDS
2:  lw    x6, 0(x7)
    sw    x6, 0(x2)
    addi  x7, x7, 4
    addi  x2, x2, 4
    addi  x5, x5, -1
    bnez  x5, 2b
    jr    x13
