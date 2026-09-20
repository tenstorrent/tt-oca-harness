# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
#
# KM ROM for sep_cov_km_csr_tb_vuart_test. Stimulus only. No contract is
# asserted; reaching the end of the image means the path was driven, nothing
# more.
#
# The VUART_TX, TB_* , SRAM_EXEC_MODE and IRQ_ENTRY_LOCK registers are on the
# KM CPU bus, so a KM image is the only vehicle that reaches them. Each write
# carries all ones: the regblock keeps the writable bits of every field and
# drops the rest, so one store covers a whole register without a hand-typed
# field literal. SRAM_LOCK takes a single region bit instead, because all ones
# would lock region 0 and the result word lives there.
#
# PicoRV32 is RV32E (x0-x15 only). Do not use x16+.
#
# Result at KM SRAM word0 (0x8000): 0xC0000004.
#
# Build (output committed as ../km_rom_cov_tbvuart.parhex):
#   make -C hw/sys/sep/dv/cocotb/tests/km_fw ../km_rom_cov_tbvuart.parhex

#include "key_manager_addr.h"

    .equ KM_SRAM_BASE,   KEY_MANAGER_SRAM_BASE_ADDR
    # 1 KB SRAM lock regions from the SRAM base; region 0 holds the result word.
    .equ LOCK_REGION,    1
    .equ LOCK_REGION_ADDR, (KEY_MANAGER_SRAM_BASE_ADDR + (LOCK_REGION * 0x400) + 0x100)

    .section .text
    .globl _start
_start:
    addi  x2, x0, -1             # all ones

    li    x1, KEY_MANAGER_KMCSR_VUART_TX_BASE_ADDR
    sw    x2, 0(x1)
    li    x1, KEY_MANAGER_KMCSR_TB_RESULT_BASE_ADDR
    sw    x2, 0(x1)
    li    x1, KEY_MANAGER_KMCSR_TB_SIGNATURE_BASE_ADDR
    sw    x2, 0(x1)
    li    x1, KEY_MANAGER_KMCSR_TB_ERRCODE_BASE_ADDR
    sw    x2, 0(x1)
    li    x1, KEY_MANAGER_KMCSR_TB_SUBTEST_BASE_ADDR
    sw    x2, 0(x1)
    li    x1, KEY_MANAGER_KMCSR_TB_CMD_BASE_ADDR
    sw    x2, 0(x1)
    li    x1, KEY_MANAGER_KMCSR_TB_CMD_ARG_BASE_ADDR
    sw    x2, 0(x1)
    li    x1, KEY_MANAGER_KMCSR_TB_CMD_STATUS_BASE_ADDR
    sw    x2, 0(x1)
    li    x1, KEY_MANAGER_KMCSR_SRAM_EXEC_MODE_BASE_ADDR
    sw    x2, 0(x1)
    li    x1, KEY_MANAGER_KMCSR_IRQ_ENTRY_LOCK_BASE_ADDR
    sw    x2, 0(x1)

    # A store into a write-locked SRAM region raises SRAM_WRITE_LOCK_VIOLATION.
    li    x3, LOCK_REGION_ADDR
    li    x4, KEY_MANAGER_KMCSR_SRAM_LOCK_BASE_ADDR
    addi  x5, x0, (1 << LOCK_REGION)
    sw    x5, 0(x4)
    sw    x2, 0(x3)
    li    x6, KEY_MANAGER_KMCSR_SRAM_WRITE_LOCK_VIOLATION_BASE_ADDR
    lw    x7, 0(x6)

    lui   x8, 0xC0000
    ori   x8, x8, 4
    li    x9, KM_SRAM_BASE
    sw    x8, 0(x9)
1:  j     1b
