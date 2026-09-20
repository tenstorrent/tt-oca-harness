# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
#
# KM ROM for sep_cov_km_drbg_timeout_test. Stimulus only. No contract is
# asserted; reaching the end of the image means the path was driven, nothing
# more.
#
# The DRBG sampler is on the KM CPU bus, so a KM image is the only vehicle.
# The host selects the ext_trng leg on EXT_TRNG_SRC_SEL and then posts the
# config word, so the mailbox handshake is what orders the two.
#
# Config word from the host:
#   [15:0]  CFG.TIMEOUT, small and non-zero
#
# With the ext_trng leg selected nothing drives TVALID, so each DATA read runs
# the sampler FSM out to StTimeout and answers SLVERR. Three reads advance
# count_bad; the STATUS write then W1C-clears timeout_err, count_bad and
# count_good.
#
# PicoRV32 is RV32E (x0-x15 only). Do not use x16+.
#
# Result at KM SRAM word0 (0x8000): 0xC0000040 with an eight-bit fold of the
# received config word at [23:16].
#
# Build (output committed as ../km_rom_cov_drbg_timeout.parhex):
#   make -C hw/sys/sep/dv/cocotb/tests/km_fw ../km_rom_cov_drbg_timeout.parhex

#include "key_manager_addr.h"

    .equ MBOX_READ_DATA, (KEY_MANAGER_MAILBOX_KM_KM_READ_DATA_BASE_ADDR - KEY_MANAGER_MAILBOX_KM_BASE_ADDR)
    .equ MBOX_STATUS,    (KEY_MANAGER_MAILBOX_KM_KM_STATUS_BASE_ADDR - KEY_MANAGER_MAILBOX_KM_BASE_ADDR)
    .equ KM_SRAM_BASE,   KEY_MANAGER_SRAM_BASE_ADDR

    .section .text
    .globl _start
_start:
    li    x1, KEY_MANAGER_MAILBOX_KM_BASE_ADDR
1:  lw    x5, MBOX_STATUS(x1)
    andi  x6, x5, 0x1            # inbound_empty
    bnez  x6, 1b
    lw    x2, MBOX_READ_DATA(x1)

    slli  x3, x2, 16             # CFG.TIMEOUT at [31:16], prefetch clear
    li    x4, KEY_MANAGER_DRBG_SAMPLER_CFG_BASE_ADDR
    sw    x3, 0(x4)

    li    x7, KEY_MANAGER_DRBG_SAMPLER_DATA_BASE_ADDR
    li    x8, KEY_MANAGER_DRBG_SAMPLER_STATUS_BASE_ADDR
    addi  x9, x0, 3
2:  lw    x10, 0(x7)
    lw    x11, 0(x8)
    addi  x9, x9, -1
    bnez  x9, 2b

    addi  x12, x0, -1
    sw    x12, 0(x8)             # W1C timeout_err, count_bad, count_good
    lw    x11, 0(x8)

    srli  x5, x2, 8
    xor   x5, x5, x2
    srli  x6, x2, 16
    xor   x5, x5, x6
    srli  x6, x2, 24
    xor   x5, x5, x6
    andi  x5, x5, 0xFF
    slli  x5, x5, 16
    lui   x6, 0xC0000
    or    x5, x5, x6
    ori   x5, x5, 0x40
    li    x13, KM_SRAM_BASE
    sw    x5, 0(x13)
3:  j     3b
