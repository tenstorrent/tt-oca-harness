/* Copyright 2026 Tenstorrent Inc. */
/*
 * Key Manager test firmware linker script (default; execute from VROM).
 *
 * A minimal bootstrap (reset, IRQ vector, IRQ handler) lives in physical ROM;
 * main code and read-only data live in testbench-only Virtual ROM. The .data
 * initializer image is stored in VROM and copied to SRAM at startup. The SRAM
 * layout is shared with the production linker via km_sram_layout.ld.
 *
 *   ROM   0x0000_0000-0x0000_1FFF  (8 KB)   : bootstrap vectors
 *   SRAM  0x0000_4000-0x0000_7FFF  (16 KB)  : .data, .bss, stack, .rom_persist
 *   VROM  0x1000_0000-0x1000_FFFF  (64 KB)  : code, rodata, .data load image
 */

OUTPUT_ARCH("riscv")

MEMORY {
    rom  (rx)  : ORIGIN = 0x00000000, LENGTH = 0x2000    /* 8 KB ROM */
    sram (rwx) : ORIGIN = 0x00004000, LENGTH = 0x4000    /* 16 KB SRAM */
    vrom (r)   : ORIGIN = 0x10000000, LENGTH = 0x10000   /* 64 KB VROM (testbench only) */
}

ENTRY(_start)

/* The .data load image is stored in VROM for the test (execute-from-VROM) build. */
REGION_ALIAS("DATA_LOAD", vrom)

SECTIONS {
    /* ----- ROM: bootstrap vectors only ----- */
    .text.reset 0x00000000 : { KEEP(*(.text._start)) } > rom
    .text.irq_vec 0x00000010 : { KEEP(*(.text.irq_vec)) } > rom
    .text.irq_handler : { KEEP(*(.text.irq_handler)) } > rom

    /* ----- VROM: code and read-only data ----- */
    .text.alt_irq 0x10000100 : { KEEP(*(.text.alt_irq)) } > vrom

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

    /* ----- SRAM: shared data layout (.rom_persist, .bss, .data, stack) ----- */
    INCLUDE km_sram_layout.ld

    /* ----- ROM / VROM image overflow assertions ----- */
    ASSERT(SIZEOF(.text.reset) + SIZEOF(.text.irq_vec) + SIZEOF(.text.irq_handler)
           <= LENGTH(rom),
           "ROM overflow: bootstrap code exceeds 8KB ROM")
    ASSERT(SIZEOF(.text) + SIZEOF(.rodata) + SIZEOF(.data) <= LENGTH(vrom),
           "VROM overflow: text + rodata + data load image exceeds 64KB VROM")
}
