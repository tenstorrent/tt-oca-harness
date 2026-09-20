# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
#
# KM ROM for sep_cov_km_csr_fault_irq_test. Stimulus only. No contract is
# asserted; reaching the end of the image means the path was driven, nothing
# more.
#
# Three recoverable KM CPU faults in sequence, each on the KM CPU bus and so
# reachable only from a KM image:
#   rom_write_err   a store into the KM ROM window (km_rom_interface)
#   axi_decerr      an access to 0x16000, which lies between the DRBG sampler
#                   rule and the OTBN rule in km_axi_lite_xbar AddrMap and so
#                   matches no rule
#   exec_violation  a committed fetch from a peripheral address
#
# IRQ_STATUS is W1C-cleared between the first two. The fetch fault parks the
# CPU, so the result word is written before it.
#
# PicoRV32 is RV32E (x0-x15 only). Do not use x16+.
#
# Result at KM SRAM word0 (0x8000): 0xC0000010.
#
# Build (output committed as ../km_rom_cov_fault.parhex):
#   make -C hw/sys/sep/dv/cocotb/tests/km_fw ../km_rom_cov_fault.parhex

#include "key_manager_addr.h"

    .equ KM_SRAM_BASE,  KEY_MANAGER_SRAM_BASE_ADDR
    .equ ROM_WR_ADDR,   (KEY_MANAGER_ROM_BASE_ADDR + 0x800)
    # Between DRBG_SAMPLER (0x15000) and OTBN (0x18000): no AddrMap rule.
    .equ UNMAPPED_ADDR, 0x00016000

    .section .text
    .globl _start
_start:
    li    x9, KEY_MANAGER_KMCSR_IRQ_STATUS_BASE_ADDR
    addi  x6, x0, -1

    li    x5, ROM_WR_ADDR
    sw    x0, 0(x5)
    lw    x7, 0(x9)
    sw    x6, 0(x9)

    li    x5, UNMAPPED_ADDR
    sw    x0, 0(x5)
    lw    x8, 0(x5)
    lw    x7, 0(x9)
    sw    x6, 0(x9)

    lui   x10, 0xC0000
    ori   x10, x10, 0x10
    li    x11, KM_SRAM_BASE
    sw    x10, 0(x11)

    li    x12, KEY_MANAGER_KMCSR_BASE_ADDR
    jalr  x0, x12, 0
