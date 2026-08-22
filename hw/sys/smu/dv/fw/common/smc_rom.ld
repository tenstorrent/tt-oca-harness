/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

OUTPUT_ARCH("riscv")
ENTRY(_start)

MEMORY
{
    rom (rx)  : ORIGIN = 0xC0040000, LENGTH = 64K
    ram (rwx) : ORIGIN = 0xC0060000, LENGTH = 1M
}

SECTIONS
{
    .text : {
        KEEP(*(.text.start))
        *(.text .text.*)
        *(.rodata .rodata.*)
    } > rom

    .data : ALIGN(8) {
        *(.data .data.*)
        *(.sdata .sdata.*)
    } > ram AT > rom

    .bss (NOLOAD) : ALIGN(8) {
        *(.bss .bss.*)
        *(.sbss .sbss.*)
        *(COMMON)
    } > ram

    PROVIDE(__global_pointer$ = ORIGIN(ram) + 0x800);
    PROVIDE(_stack_top = ORIGIN(ram) + 0x4000);
}
