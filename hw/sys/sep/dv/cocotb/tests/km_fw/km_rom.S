# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
#
# KM (PicoRV32) ROM firmware for the SEP OSS KM memory smoke test
# (sep_km_mem_smoke_test). It fetches from the KM ROM and stores one known
# marker word to KM SRAM word0, so the ROM-fetch counter, the SRAM
# request/write counters and the SRAM word0 value-compare all have a source.
#
#   KM SRAM base = 0x0000_8000  (Key Manager specification, KM private memory
#   map: SRAM region 0x0000_8000-0x0000_FFFF, 32 KB, direct R/W. The value is
#   DV-owned here; it is not read back from the design.)
#
# The marker value is mirrored by KM_SMOKE_SRAM_WORD0 in
# cocotb/seq_lib/sep_km_mem_smoke_seq.py; a divergence between the two fails the
# test's value-compare loudly.
#
# Build (output committed as ../km_rom.parhex):
#   riscv64-unknown-elf-gcc -nostdlib -march=rv32i -mabi=ilp32 -Ttext=0 \
#       -o km_rom.elf km_rom.S
#   riscv64-unknown-elf-objcopy -O binary km_rom.elf km_rom.bin
#   python3 gen_parhex.py km_rom.bin > ../km_rom.parhex

    .section .text
    .globl _start
_start:
    lui   x1, 0x8          # x1 = 0x0000_8000 (KM SRAM base, see header)
    li    x2, 0x5A         # marker word (KM_SMOKE_SRAM_WORD0)
    sw    x2, 0(x1)        # store the marker to SRAM word0
1:  j     1b               # spin
