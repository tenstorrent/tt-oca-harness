# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
#
# KM ROM for sep_cov_km_drbg_prefetch_read_test. Stimulus only. No contract is
# asserted; reaching the end of the image means the path was driven, nothing
# more.
#
# The DRBG sampler is on the KM CPU bus, so a KM image is the only vehicle.
# The host brings the ESRC/CSRNG/EDN stack up and selects the internal DRBG
# leg first, then posts the config word, so the mailbox handshake is what
# orders the two.
#
# CFG takes prefetch=1 with a wide TIMEOUT. The image polls STATUS.prefetched,
# then reads PREFETCH_DATA and DATA, which is the consume path.
#
# PicoRV32 is RV32E (x0-x15 only). Do not use x16+.
#
# Result at KM SRAM word0 (0x8000): 0xC0000080 with an eight-bit fold of the
# received config word at [23:16].
#
# Build (output committed as ../km_rom_cov_drbg_prefetch.parhex):
#   make -C hw/sys/sep/dv/cocotb/tests/km_fw ../km_rom_cov_drbg_prefetch.parhex

#include "key_manager_addr.h"

    .equ MBOX_READ_DATA, (KEY_MANAGER_MAILBOX_KM_KM_READ_DATA_BASE_ADDR - KEY_MANAGER_MAILBOX_KM_BASE_ADDR)
    .equ MBOX_STATUS,    (KEY_MANAGER_MAILBOX_KM_KM_STATUS_BASE_ADDR - KEY_MANAGER_MAILBOX_KM_BASE_ADDR)
    .equ KM_SRAM_BASE,   KEY_MANAGER_SRAM_BASE_ADDR
    .equ CFG_PREFETCH_WIDE_TIMEOUT, 0xFFFF0001
    .equ STATUS_PREFETCHED_bm, 0x2

    .section .text
    .globl _start
_start:
    li    x1, KEY_MANAGER_MAILBOX_KM_BASE_ADDR
1:  lw    x5, MBOX_STATUS(x1)
    andi  x6, x5, 0x1            # inbound_empty
    bnez  x6, 1b
    lw    x2, MBOX_READ_DATA(x1)

    li    x3, CFG_PREFETCH_WIDE_TIMEOUT
    li    x4, KEY_MANAGER_DRBG_SAMPLER_CFG_BASE_ADDR
    sw    x3, 0(x4)

    li    x7, KEY_MANAGER_DRBG_SAMPLER_STATUS_BASE_ADDR
    li    x8, 0x10000            # bounded: a stalled source must not hang
2:  lw    x9, 0(x7)
    andi  x10, x9, STATUS_PREFETCHED_bm
    bnez  x10, prefetched
    addi  x8, x8, -1
    bnez  x8, 2b
prefetched:
    li    x11, KEY_MANAGER_DRBG_SAMPLER_PREFETCH_DATA_BASE_ADDR
    lw    x12, 0(x11)
    li    x13, KEY_MANAGER_DRBG_SAMPLER_DATA_BASE_ADDR
    lw    x14, 0(x13)

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
    ori   x5, x5, 0x80
    li    x15, KM_SRAM_BASE
    sw    x5, 0(x15)
3:  j     3b
