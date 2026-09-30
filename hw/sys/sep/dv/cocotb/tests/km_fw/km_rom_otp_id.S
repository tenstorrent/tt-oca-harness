# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
#
# KM ROM for sep_efuse_km_public_id_test. Not rom_main: no mailbox command
# returns the KMCSR public-ID OTP words, so only code running on the KM CPU
# can read them out.
#
# PicoRV32 is RV32E (x0-x15 only). Do not use x16+.
#
# This image copies raw words and grades nothing. Every golden lives in the
# host test, which takes it from the staged eFuse image.
#
#   1. Copy the 48 KMCSR words OTP_SEP_CHIPLET_ID_VAL_0 .. OTP_SEP_SYS_ID_CPL_7,
#      in address order, to KM SRAM words 1..48.
#   2. Set OTP_READ_LOCK.SEP_CHIPLET_ID, .SEP_SIP_ID and .SEP_SYS_ID, and read
#      the register back.
#   3. Copy the same 48 words again, to KM SRAM words 49..96.
#   4. Store the OTP_READ_LOCK readback to KM SRAM word 97.
#   5. Store DONE_MARKER to KM SRAM word 0, the km_sram_word0_o probe.
#
# Word 0 is written last, so a host that sees the marker reads complete dumps.
# env/sep_km_otp_id.py holds the same layout for the host.
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

    .equ ID_LOCKS,      (KM_CSR__OTP_READ_LOCK_REG__SEP_CHIPLET_ID_bm | \
                         KM_CSR__OTP_READ_LOCK_REG__SEP_SIP_ID_bm | \
                         KM_CSR__OTP_READ_LOCK_REG__SEP_SYS_ID_bm)
    .equ DUMP_OPEN,     KEY_MANAGER_SRAM_BASE_ADDR + 4
    .equ DONE_MARKER,   0x1D1D1D1D

    .section .text
    .globl _start
_start:
    # x1  KMCSR public-ID window
    # x2  KM SRAM store pointer
    # x3  OTP_READ_LOCK
    # x4  lock mask, then its readback
    # x5  copy count
    # x6  copied word
    # x7  load pointer
    # x13 return address
    li    x1, ID_BASE
    li    x2, DUMP_OPEN
    jal   x13, copy_ids

    li    x3, KEY_MANAGER_KMCSR_OTP_READ_LOCK_BASE_ADDR
    li    x4, ID_LOCKS
    sw    x4, 0(x3)
    lw    x4, 0(x3)

    jal   x13, copy_ids
    sw    x4, 0(x2)

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
