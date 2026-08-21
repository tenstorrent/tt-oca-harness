# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
#
# KM (PicoRV32) ROM firmware for the SEP OSS ESRC -> DRBG -> CSRNG -> EDN -> KM
# entropy alive smoke. The Key Manager's drbg_sampler only asserts TREADY on the
# EDN->KM stream when its own CPU pulls entropy, so this firmware makes the KM
# genuinely CONSUME one genbits word (a real tvalid && tready handshake).
#
# The DRBG-sampler DATA read blocks until a stream word is available; the
# sampler's read-timeout (CFG.TIMEOUT, reset 256 cycles) would otherwise abort
# the read long before the forced-noise entropy datapath produces a seed
# (~78k cycles), so the timeout is disabled first by writing CFG = 0.
#
#   DRBG sampler base = 0x0000_F000  (km_intf_pkg::DRBG_SAMPLER_BASE_ADDR)
#     DATA @ +0x0  read consumes one EDN stream word
#     CFG  @ +0x4  TIMEOUT[31:16], PREFETCH[0]  (reset 0x0100_0000)
#   KM SRAM base      = 0x0000_4000  word0 used as a consumed-word liveness marker
#
# Build (output committed as ../km_rom_entropy.parhex):
#   riscv64-unknown-elf-gcc -nostdlib -march=rv32i -mabi=ilp32 -Ttext=0 \
#       -o km_rom_entropy.elf km_rom_entropy.S
#   riscv64-unknown-elf-objcopy -O binary km_rom_entropy.elf km_rom_entropy.bin
#   python3 gen_parhex.py km_rom_entropy.bin > ../km_rom_entropy.parhex

    .section .text
    .globl _start
_start:
    lui   x1, 0xF          # x1 = 0x0000_F000 (DRBG sampler base)
    sw    x0, 4(x1)        # CFG = 0 -> disable read timeout (and prefetch)
    lw    x2, 0(x1)        # DATA read: blocks until entropy, KM consumes a word
    lui   x3, 0x4          # x3 = 0x0000_4000 (KM SRAM base)
    sw    x2, 0(x3)        # store consumed word to SRAM word0 (liveness marker)
1:  j     1b               # spin
