/* Copyright 2026 Tenstorrent Inc. */
/* Key Manager Firmware Linker Script - default for tests (execute from VROM) */
/* Minimal bootstrap in ROM (reset, IRQ vec, IRQ handler); main .text and .rodata in VROM (0x1000_0000). */

OUTPUT_ARCH( "riscv" )

MEMORY {
    rom(rx):  ORIGIN = 0x00000000, LENGTH = 0x4000  /* 16KB ROM */
    sram(rwx): ORIGIN = 0x00004000, LENGTH = 0x4000  /* 16KB SRAM */
    vrom(r):  ORIGIN = 0x10000000, LENGTH = 0x10000  /* 64KB Virtual ROM (testbench only) */
}

ENTRY(_start)

/* The .data load image is stored in VROM for the test (execute-from-VROM) build. */
REGION_ALIAS("DATA_LOAD", vrom)

SECTIONS {
    /* Minimal code in physical ROM (reset, IRQ vector, IRQ handler only). */
    . = ORIGIN(rom);

    .text.reset 0x00000000 : {
        KEEP(*(.text._start))
    } > rom

    .text.irq_vec 0x00000010 : {
        KEEP(*(.text.irq_vec))
    } > rom

    .text.irq_handler : {
        KEEP(*(.text.irq_handler))
    } > rom

    /* Main code and rodata in Virtual ROM. */
    . = ORIGIN(vrom);

    /* Fixed VROM address for alternate IRQ-entry tests (program IRQ_ENTRY_ADDR here). */
    .text.alt_irq 0x10000100 : {
        KEEP(*(.text.alt_irq))
    } > vrom

    .text : {
        . = ALIGN(4);
        *(.text)
        *(.text.*)
    } > vrom

    .rodata : {
        . = ALIGN(4);
        *(.rodata)
        *(.rodata.*)
        *(.srodata)
        *(.srodata.*)
    } > vrom

    /* SRAM: .rom_persist, .bss, .data, stack -- shared with the production
     * build via km_sram_layout.ld. */
    INCLUDE km_sram_layout.ld

    ASSERT(SIZEOF(.text.reset) + SIZEOF(.text.irq_vec) + SIZEOF(.text.irq_handler)
           <= LENGTH(rom),
           "ROM overflow: bootstrap code exceeds 16KB ROM")
    ASSERT(SIZEOF(.text) + SIZEOF(.rodata) + SIZEOF(.data) <= LENGTH(vrom),
           "VROM overflow: text + rodata + data load image exceeds 64KB VROM")
}
