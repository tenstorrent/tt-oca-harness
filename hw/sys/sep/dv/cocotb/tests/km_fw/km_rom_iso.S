# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
#
# KM ROM for sep_km_isolate_termination_test. Not rom_main: the contract is
# what a KEY MANAGER master transaction receives when its own AXI-Lite path to
# a destination engine is isolated, and only code running on the KM CPU can
# issue that transaction. Every other isolation test in this package drives the
# SEP host port, which reaches the host_* paths and never the km_* ones.
#
# PicoRV32 is RV32E (x0-x15 only). Do not use x16+.
#
# The image is a store server. The host picks the destination and decides
# whether its path is live or isolated; the image only issues the store and
# reports what IRQ_STATUS says about it. One leg per inbound mailbox word:
#
#   word != 0  the word is a KM bus address (a destination key aperture).
#              The image W1Cs the two AXI error bits of IRQ_STATUS, reads
#              IRQ_STATUS back, stores 0 to the address, polls IRQ_STATUS a
#              bounded number of times for an AXI error bit, reads IRQ_STATUS
#              once more and publishes the result.
#   word == 0  the image publishes the park marker and spins on one jump
#              instruction, so it issues no data access while the host resets
#              the Key Manager.
#
# Result in KM SRAM word0 (the km_sram_word0_o probe):
#
#   [31:24]  0xB1 magic
#   [23:16]  leg sequence number, 1 for the first leg, +1 per leg (mod 256)
#   [15:8]   IRQ_STATUS & (AXI_SLVERR | AXI_DECERR) read back after the W1C,
#            before the store (both bits clear = the leg started clean)
#   [7:0]    IRQ_STATUS & (AXI_SLVERR | AXI_DECERR) after the store, or 0xFF
#            for the park marker
#
# The host grades every field. The bits are sticky on the B-handshake pulse,
# so the read after the poll holds every bit the store set.
#
# Build (output committed as ../km_rom_iso.parhex):
#   make -C hw/sys/sep/dv/cocotb/tests/km_fw ../km_rom_iso.parhex

#include "key_manager_addr.h"
#include "km_fields.inc"

    .equ MBOX_READ_DATA,   (KEY_MANAGER_MAILBOX_KM_KM_READ_DATA_BASE_ADDR - KEY_MANAGER_MAILBOX_KM_BASE_ADDR)
    .equ MBOX_STATUS,      (KEY_MANAGER_MAILBOX_KM_KM_STATUS_BASE_ADDR - KEY_MANAGER_MAILBOX_KM_BASE_ADDR)

    # KM SRAM base from the generated map. km_csr.rdl SRAM lock region 0
    # starts at this base.
    .equ KM_SRAM_BASE, KEY_MANAGER_SRAM_BASE_ADDR

    # IRQ_STATUS AXI_SLVERR | AXI_DECERR from the generated field masks.
    # km_csr.h itself is a C header the assembler cannot pull in;
    # km_fields.inc is the assembler-safe extract the km_fw Makefile lifts
    # out of it, so a field that moves at the next RDL regeneration moves here.
    .equ AXI_ERR_BITS, (KM_CSR__IRQ_STATUS_REG__AXI_SLVERR_bm | \
                        KM_CSR__IRQ_STATUS_REG__AXI_DECERR_bm)
    .equ POLL_LIMIT,   32
    .equ PARK_MARK,    0xFF

    .section .text
    .globl _start
_start:
    # x1  mailbox base
    # x2  store address of the current leg
    # x5  leg sequence number
    # x7  IRQ_STATUS error bits before the store
    # x8  IRQ_STATUS error bits after the store
    # x9  IRQ_STATUS
    # x10 KM SRAM base
    # x6,x11-x14 scratch
    li    x1, KEY_MANAGER_MAILBOX_KM_BASE_ADDR
    li    x9, KEY_MANAGER_KMCSR_IRQ_STATUS_BASE_ADDR
    li    x10, KM_SRAM_BASE
    addi  x5, x0, 0

next_leg:
    jal   x13, wait_mbox
    beqz  x6, park
    addi  x2, x6, 0

    addi  x6, x0, AXI_ERR_BITS
    sw    x6, 0(x9)                # W1C both AXI error bits
    lw    x7, 0(x9)
    andi  x7, x7, AXI_ERR_BITS

    sw    x0, 0(x2)                # the store under test

    addi  x12, x0, POLL_LIMIT
poll_loop:
    lw    x6, 0(x9)
    andi  x6, x6, AXI_ERR_BITS
    bnez  x6, poll_done
    addi  x12, x12, -1
    bnez  x12, poll_loop
poll_done:
    lw    x8, 0(x9)
    andi  x8, x8, AXI_ERR_BITS

    addi  x5, x5, 1
    andi  x5, x5, 0xFF
    jal   x13, publish
    j     next_leg

park:
    addi  x5, x5, 1
    andi  x5, x5, 0xFF
    addi  x7, x0, 0
    addi  x8, x0, PARK_MARK
    jal   x13, publish
1:  j     1b

# --- helpers; x13 holds the return address ---------------------------------

    # Block until the inbound mailbox holds a word, then consume it into x6.
wait_mbox:
    lw    x6, MBOX_STATUS(x1)
    andi  x6, x6, KM_MAILBOX_KM__STATUS_REG__INBOUND_EMPTY_bm
    bnez  x6, wait_mbox
    lw    x6, MBOX_READ_DATA(x1)
    jr    x13

    # Publish 0xB1 << 24 | x5 << 16 | x7 << 8 | x8 to KM SRAM word0.
publish:
    lui   x6, 0xB1000              # magic 0xB1 in [31:24]
    slli  x11, x5, 16
    or    x6, x6, x11
    slli  x11, x7, 8
    or    x6, x6, x11
    or    x6, x6, x8
    sw    x6, 0(x10)
    jr    x13
