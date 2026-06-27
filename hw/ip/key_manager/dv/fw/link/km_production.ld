/* Copyright 2026 Tenstorrent Inc. */
/* Key Manager Production Firmware Linker Script */
/* ROM at 0x0000_0000, SRAM at 0x0000_4000, no VROM */

OUTPUT_ARCH( "riscv" )

MEMORY {
    rom(rx):   ORIGIN = 0x00000000, LENGTH = 0x2000  /* 8KB ROM */
    sram(rwx): ORIGIN = 0x00004000, LENGTH = 0x4000  /* 16KB SRAM */
}

ENTRY(_start)

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
    } > sram AT> rom
    DATA_LOAD_START = LOADADDR(.data);

    /* Anchor for gp-relative small-data accesses. */
    PROVIDE(__global_pointer$ = DATA_START + 0x800);

    /* Main stack grows downward immediately below .data. */
    STACK = ADDR(.data);
    stack = STACK;
    _stack = STACK;

    /* Overflow assertions */
    ASSERT(SIZEOF(.text.reset) + SIZEOF(.text.irq_vec) + SIZEOF(.text.irq_handler)
           + SIZEOF(.text) + SIZEOF(.rodata) + SIZEOF(.data) <= LENGTH(rom),
           "ROM overflow: text + rodata + data load image exceeds 8KB ROM")
    ASSERT(ADDR(.data) >= ORIGIN(sram),
           "SRAM overflow: data + bss exceed 16KB SRAM")
    ASSERT(_stack >= ORIGIN(sram) + 16,
           "SRAM overflow: data + bss leave no aligned stack space")
}
