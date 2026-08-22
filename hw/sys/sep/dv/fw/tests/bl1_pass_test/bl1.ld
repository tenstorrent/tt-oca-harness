/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/* BL1 linker script: single SRAM layout.
 *
 * Memory layout:
 *   SRAM: 0x10020000 - 0x1003FFFF (128 KiB upper half)
 *
 * IFU fetches instructions and LSU loads/stores data from SRAM via the
 * AXI system bus, so all sections live in a single memory region.
 *
 * rom_handoff_bl1() copies the flat binary from its manifest payload
 * position to 0x10020000, then jumps to _start.
 *
 * IMPORTANT: .text.init MUST come first — _start lives there.
 *
 * The binary MUST be 4-byte aligned (copy width = 4 bytes).
 */

OUTPUT_ARCH("riscv")

MEMORY {
    sram (rwx) : ORIGIN = 0x10020000, LENGTH = 0x20000  /* 128 KiB */
}

ENTRY(_start)

SECTIONS {

    /*=====================================================================
     * Code
     *====================================================================*/
    . = ORIGIN(sram);

    .text : {
        *(.text.init)
        *(.text)
        *(.text.*)
        . = ALIGN(4);
    } > sram

    /*=====================================================================
     * Read-only data, initialized data, BSS
     *====================================================================*/
    .rodata : ALIGN(4) {
        *(.rodata)
        *(.rodata.*)
        *(.srodata)
        *(.srodata.*)
        . = ALIGN(4);
    } > sram

    .data : ALIGN(4) {
        *(.data)
        *(.data.*)
        *(.sdata)
        *(.sdata.*)
        . = ALIGN(4);
    } > sram

    .bss (NOLOAD) : ALIGN(4) {
        BSS_START = .;
        *(.bss)
        *(.bss.*)
        *(.sbss)
        *(.sbss.*)
        . = ALIGN(4);
        BSS_END = .;
    } > sram
}
