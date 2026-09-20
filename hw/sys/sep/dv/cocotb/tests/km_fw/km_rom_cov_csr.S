# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
#
# KM ROM shared by sep_cov_km_csr_otp_shadow_walk_test and
# sep_cov_km_csr_otp_lock_test. Stimulus only. No contract is asserted;
# reaching the end of the image means the path was driven, nothing more.
#
# KMCSR is on the KM CPU bus, so a KM image is the only vehicle that reaches
# it. The image reads every word of the KMCSR block, which drives the readback
# mux leg of each OTP shadow, VUART and TB register, then writes the nine
# OTP_READ_LOCK W1S fields and the nine OTP_CHANGE_STATUS W1C fields. The read
# walk precedes the lock so the shadow reads are not gated by it.
#
# A word inside the block with no readable register answers SLVERR. That sets a
# sticky IRQ_STATUS bit and the load returns; it does not stall the KM CPU.
#
# PicoRV32 is RV32E (x0-x15 only). Do not use x16+.
#
# Result at KM SRAM word0 (0x8000): 0xC0000002.
#
# Build (output committed as ../km_rom_cov_csr.parhex):
#   make -C hw/sys/sep/dv/cocotb/tests/km_fw ../km_rom_cov_csr.parhex

#include "key_manager_addr.h"

    .equ KM_SRAM_BASE, KEY_MANAGER_SRAM_BASE_ADDR
    # Nine fields in each of OTP_READ_LOCK and OTP_CHANGE_STATUS.
    .equ OTP_FIELD_MASK, 0x1FF

    .section .text
    .globl _start
_start:
    li    x1, KEY_MANAGER_KMCSR_BASE_ADDR
    li    x2, KEY_MANAGER_KMCSR_BASE_ADDR + KEY_MANAGER_KMCSR_SIZE
    addi  x3, x0, 0
1:  lw    x4, 0(x1)
    xor   x3, x3, x4
    addi  x1, x1, 4
    bltu  x1, x2, 1b

    addi  x6, x0, OTP_FIELD_MASK
    li    x5, KEY_MANAGER_KMCSR_OTP_READ_LOCK_BASE_ADDR
    sw    x6, 0(x5)
    lw    x7, 0(x5)
    li    x5, KEY_MANAGER_KMCSR_OTP_CHANGE_STATUS_BASE_ADDR
    sw    x6, 0(x5)
    lw    x7, 0(x5)

    lui   x8, 0xC0000
    ori   x8, x8, 2
    li    x9, KM_SRAM_BASE
    sw    x8, 0(x9)
2:  j     2b
