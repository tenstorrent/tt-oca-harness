/* Copyright (c) 2020 SiFive Inc. */
/* SPDX-License-Identifier: Apache-2.0 */
OUTPUT_ARCH("riscv")

/* SRAM link mode ("scratchpad"): all code and data live in writable testram,
 * with no separate boot ROM. */

ENTRY(_enter)

MEMORY
{
    testram (airwx) : ORIGIN = 0xc0060000, LENGTH = 1M
}

REGION_ALIAS("BOOT_REGION", testram)
REGION_ALIAS("RAM_REGION", testram)

PHDRS
{
    rom PT_LOAD;
    ram_init PT_LOAD;
    tls PT_TLS;
    ram PT_LOAD;
    itim_init PT_LOAD;
    text PT_LOAD;
    lim_init PT_LOAD;
}

SECTIONS
{
    INCLUDE common.ldh
}
