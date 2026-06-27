/* Copyright 2026 Tenstorrent Inc. */
/* Key Manager Firmware Linker Script - default for tests (execute from VROM) */
/* Minimal bootstrap in ROM (reset, IRQ vec, IRQ handler); main .text and .rodata in VROM (0x1000_0000). */

OUTPUT_ARCH( "riscv" )

MEMORY {
    rom(rx):  ORIGIN = 0x00000000, LENGTH = 0x2000  /* 8KB ROM */
    sram(rwx): ORIGIN = 0x00004000, LENGTH = 0x4000  /* 16KB SRAM */
    vrom(r):  ORIGIN = 0x10000000, LENGTH = 0x10000  /* 64KB Virtual ROM (testbench only) */
}

ENTRY(_start)

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

    /* Pack runtime SRAM from the top down: .bss at the top, .data below it. */
    .bss ORIGIN(sram) + LENGTH(sram) - SIZEOF(.bss) : {
        BSS_START = .;
        . = ALIGN(4);
        *(.bss)
        *(.bss.*)
        *(.sbss)
        *(.sbss.*)
        . = ALIGN(16);
        BSS_END = .;
    } > sram

    .data ADDR(.bss) - SIZEOF(.data) : {
        DATA_START = .;
        . = ALIGN(4);
        *(.data)
        *(.data.*)
        *(.sdata)
        *(.sdata.*)
        . = ALIGN(16);
        DATA_END = .;
    } > sram AT> vrom
    DATA_LOAD_START = LOADADDR(.data);

    /* Anchor for gp-relative small-data accesses. */
    PROVIDE(__global_pointer$ = DATA_START + 0x800);

    /* Main stack grows downward immediately below .data. */
    STACK = ADDR(.data);
    stack = STACK;
    _stack = STACK;

    /* Overflow assertions */
    ASSERT(SIZEOF(.text.reset) + SIZEOF(.text.irq_vec) + SIZEOF(.text.irq_handler)
           <= LENGTH(rom),
           "ROM overflow: bootstrap code exceeds 8KB ROM")
    ASSERT(SIZEOF(.text) + SIZEOF(.rodata) + SIZEOF(.data) <= LENGTH(vrom),
           "VROM overflow: text + rodata + data load image exceeds 64KB VROM")
    ASSERT(ADDR(.data) >= ORIGIN(sram),
           "SRAM overflow: data + bss exceed 16KB SRAM")
    ASSERT(_stack >= ORIGIN(sram) + 16,
           "SRAM overflow: data + bss leave no aligned stack space")
}
