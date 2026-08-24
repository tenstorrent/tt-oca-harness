/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

OUTPUT_ARCH("riscv")
ENTRY(_start)

MEMORY
{
    iccm (rx)  : ORIGIN = 0xC0000000, LENGTH = 256K
    dccm (rwx) : ORIGIN = 0xC0040000, LENGTH = 128K
}

SECTIONS
{
    .text : {
        KEEP(*(.text.start))
        *(.text .text.*)
        *(.rodata .rodata.*)
    } > iccm

    .data : ALIGN(4) {
        *(.data .data.*)
        *(.sdata .sdata.*)
    } > dccm

    .bss (NOLOAD) : ALIGN(4) {
        *(.bss .bss.*)
        *(.sbss .sbss.*)
        *(COMMON)
    } > dccm

    PROVIDE(__global_pointer$ = ORIGIN(dccm) + 0x800);
    PROVIDE(_stack_top = ORIGIN(dccm) + LENGTH(dccm) - 16);
}
