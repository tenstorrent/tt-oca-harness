/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/* Copyright 2026 Tenstorrent Inc. */
/* Key Manager Production Firmware Linker Script */
/* ROM at 0x0000_0000, SRAM at 0x0000_8000, no VROM */

OUTPUT_ARCH( "riscv" )

MEMORY {
    rom(rx):   ORIGIN = 0x00000000, LENGTH = 0x4000  /* 16KB ROM */
    sram(rwx): ORIGIN = 0x00008000, LENGTH = 0x8000  /* 32KB SRAM */
}

ENTRY(_start)

/* The .data load image is stored in ROM for the production (no-VROM) build. */
REGION_ALIAS("DATA_LOAD", rom)

SECTIONS {
    /* Reset vector at 0x0000_0000 — must be exactly 16 bytes */
    .text.reset 0x00000000 : {
        KEEP(*(.text._start))
    } > rom

    /* IRQ vector at 0x0000_0010 */
    .text.irq_vec 0x00000010 : {
        KEEP(*(.text.irq_vec))
    } > rom

    /* IRQ handler */
    .text.irq_handler : {
        KEEP(*(.text.irq_handler))
    } > rom

    /* Code */
    .text : {
        . = ALIGN(4);
        *(.text)
        *(.text.*)
    } > rom

    /* Read-only data goes into ROM in production (no VROM available) */
    .rodata : {
        . = ALIGN(4);
        *(.rodata)
        *(.rodata.*)
        *(.srodata)
        *(.srodata.*)
    } > rom

    /* SRAM: .rom_persist, .bss, .data, stack -- shared with every testbench
     * layout via km_sram_layout.ld. */
    INCLUDE km_sram_layout.ld

    /* Overflow assertion */
    ASSERT(SIZEOF(.text.reset) + SIZEOF(.text.irq_vec) + SIZEOF(.text.irq_handler)
           + SIZEOF(.text) + SIZEOF(.rodata) + SIZEOF(.data) <= LENGTH(rom),
           "ROM overflow: text + rodata + data load image exceeds 16KB ROM")
}
