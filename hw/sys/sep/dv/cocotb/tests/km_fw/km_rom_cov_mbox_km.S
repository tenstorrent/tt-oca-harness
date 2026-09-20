# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
#
# KM ROM for sep_cov_km_mailbox_km_decode_err_test. Stimulus only. No contract
# is asserted; reaching the end of the image means the path was driven,
# nothing more.
#
# The KM-side mailbox window is on the KM CPU bus, so a KM image is the only
# vehicle. This image does not take a config word, because inbound_underflow
# needs the inbound FIFO empty.
#
#   read  KM_WRITE_DATA (write-only)  -> km_mailbox_km_reg decoded_err, SLVERR
#   write KM_READ_DATA  (read-only)   -> km_mailbox_km_reg decoded_err, SLVERR
#   push MAILBOX_DEPTH+1 words        -> KM_STATUS/KM_IRQ_STATUS outbound_overflow
#   read KM_READ_DATA while empty     -> inbound_underflow
#   W1C KM_STATUS and KM_IRQ_STATUS
#
# PicoRV32 is RV32E (x0-x15 only). Do not use x16+.
#
# Result at KM SRAM word0 (0x8000): 0xC0000100.
#
# Build (output committed as ../km_rom_cov_mbox_km.parhex):
#   make -C hw/sys/sep/dv/cocotb/tests/km_fw ../km_rom_cov_mbox_km.parhex

#include "key_manager_addr.h"

    .equ MBOX_WRITE_DATA, (KEY_MANAGER_MAILBOX_KM_KM_WRITE_DATA_BASE_ADDR - KEY_MANAGER_MAILBOX_KM_BASE_ADDR)
    .equ MBOX_READ_DATA,  (KEY_MANAGER_MAILBOX_KM_KM_READ_DATA_BASE_ADDR - KEY_MANAGER_MAILBOX_KM_BASE_ADDR)
    .equ MBOX_STATUS,     (KEY_MANAGER_MAILBOX_KM_KM_STATUS_BASE_ADDR - KEY_MANAGER_MAILBOX_KM_BASE_ADDR)
    .equ MBOX_IRQ_STATUS, (KEY_MANAGER_MAILBOX_KM_KM_IRQ_STATUS_BASE_ADDR - KEY_MANAGER_MAILBOX_KM_BASE_ADDR)
    .equ KM_SRAM_BASE,    KEY_MANAGER_SRAM_BASE_ADDR
    # sep_crypto.sv sets MAILBOX_DEPTH 16; one more word overflows.
    .equ PUSH_WORDS,      17

    .section .text
    .globl _start
_start:
    li    x1, KEY_MANAGER_MAILBOX_KM_BASE_ADDR

    lw    x5, MBOX_WRITE_DATA(x1)    # write-only register
    sw    x0, MBOX_READ_DATA(x1)     # read-only register

    addi  x6, x0, PUSH_WORDS
1:  sw    x6, MBOX_WRITE_DATA(x1)
    addi  x6, x6, -1
    bnez  x6, 1b

    lw    x7, MBOX_STATUS(x1)
    andi  x8, x7, 0x1                # inbound_empty
    beqz  x8, no_underflow
    lw    x5, MBOX_READ_DATA(x1)     # underflow read
no_underflow:
    lw    x7, MBOX_STATUS(x1)
    addi  x9, x0, -1
    sw    x9, MBOX_STATUS(x1)
    sw    x9, MBOX_IRQ_STATUS(x1)
    lw    x7, MBOX_STATUS(x1)

    lui   x10, 0xC0000
    ori   x10, x10, 0x100
    li    x11, KM_SRAM_BASE
    sw    x10, 0(x11)
2:  j     2b
