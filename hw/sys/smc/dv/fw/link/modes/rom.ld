/* Copyright (c) 2020 SiFive Inc. */
/* SPDX-License-Identifier: Apache-2.0 */
OUTPUT_ARCH("riscv")

/* ROM link mode: the boot image (init/fini/ctors/rodata/text) is placed in
 * real ROM; .data/.bss/stack/heap still live in testram, loaded from ROM at
 * startup. The shared SECTIONS body lives in modes/common.ldh.
 */

ENTRY(_enter)

MEMORY
{
    testram (airwx) : ORIGIN = 0xc0060000, LENGTH = 1M
    rom (rx) : ORIGIN = 0xc0040000, LENGTH = 64K
}

REGION_ALIAS("BOOT_REGION", rom)
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
