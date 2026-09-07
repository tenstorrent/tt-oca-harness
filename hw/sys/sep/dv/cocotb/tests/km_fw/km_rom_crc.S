# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
#
# KM ROM for sep_km_crc_pcpi_kat_test. Not rom_main: the CRC engine has no
# register interface at all. It is a PicoRV32 PCPI co-processor reached by a
# custom-0 instruction, so KM firmware is the only way to activate it, and
# rom_main never issues one on demand.
#
# PicoRV32 is RV32E (x0-x15 only). Do not use x16+.
#
# This image is a service loop, not a checker: it applies one CRC instruction
# per request and hands the raw result back. Every golden, chain and cross-
# check lives in the host test, where it is reviewable and independent of the
# hardware being graded.
#
# Request, three words over the KM mailbox:
#   word 0  mode: 0 = CRC-32C word, 1 = CRC-32C byte, 2 = CRC-8/ROHC,
#                 0xFFFFFFFF = halt
#   word 1  rs1, the chaining state
#   word 2  rs2, the data operand
# Response, one word: the raw rd result. No initial value and no final
# inversion are applied here or in the engine; both belong to the caller.
#
# The three encodings are the ones the KM firmware driver already uses, with
# rd = rs1 = a0 and rs2 = a1. Both registers are in the lower half, so this
# image cannot reach a register the RV32E core does not have.
#
# Build (output committed as ../km_rom_crc.parhex):
#   make -C hw/sys/sep/dv/cocotb/tests/km_fw ../km_rom_crc.parhex

    .equ CRC32C_WORD, 0x58B5050B
    .equ CRC32C_BYTE, 0x58B5150B
    .equ CRC8_ROHC,   0x58B5250B

    .section .text
    .globl _start
_start:
    # x1  mbox base
    # x2  mode
    # x5  status scratch
    # x6  scratch
    # x10 (a0) chaining state in, result out
    # x11 (a1) data operand
    lui   x1, 0x10              # mbox 0x00010000

next_req:
    # mode
1:  lw    x5, 0xC(x1)
    andi  x6, x5, 0x1           # inbound_empty
    bnez  x6, 1b
    lw    x2, 0x8(x1)
    addi  x6, x0, -1
    beq   x2, x6, halt

    # rs1 (state)
2:  lw    x5, 0xC(x1)
    andi  x6, x5, 0x1
    bnez  x6, 2b
    lw    x10, 0x8(x1)

    # rs2 (data)
3:  lw    x5, 0xC(x1)
    andi  x6, x5, 0x1
    bnez  x6, 3b
    lw    x11, 0x8(x1)

    beqz  x2, do_word
    addi  x6, x0, 1
    beq   x2, x6, do_byte

do_rohc:
    .word CRC8_ROHC
    j     send
do_word:
    .word CRC32C_WORD
    j     send
do_byte:
    .word CRC32C_BYTE

send:
    # Separator marks the NEXT written word as the last of the frame, so it is
    # written before the result, not after.
    addi  x6, x0, 1
    sw    x6, 0x4(x1)
    sw    x10, 0x0(x1)
    j     next_req

halt:
    j     halt
