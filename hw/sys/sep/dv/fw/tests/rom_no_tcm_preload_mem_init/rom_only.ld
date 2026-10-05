/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

OUTPUT_ARCH("riscv")
ENTRY(_start)

MEMORY {
    rom (rx) : ORIGIN = 0x10040000, LENGTH = 0x00010000
}

SECTIONS {
    . = ORIGIN(rom);

    .text : ALIGN(4) {
        KEEP(*(.text.init))
        *(.text .text.*)
    } > rom

    /DISCARD/ : {
        *(.comment*)
        *(.eh_frame*)
        *(.note*)
    }
}
