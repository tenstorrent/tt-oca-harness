/* Copyright 2026 Tenstorrent Inc. */
/* Minimal linker script for KM test mutable firmware images loaded into SRAM. */

ENTRY(_mutable_fw_entry)

MEMORY {
    mutable_sram (rwx) : ORIGIN = 0x00004000, LENGTH = 0x00001800
}

SECTIONS {
    .text.mutable_entry 0x00004000 : {
        KEEP(*(.text.mutable_entry))
        . = ALIGN(4);
        . = 0x00004010;
    } > mutable_sram

    .text.mutable_irq 0x00004010 : {
        KEEP(*(.text.mutable_irq))
        . = ALIGN(4);
        . = 0x00004020;
    } > mutable_sram

    .text 0x00004020 : {
        *(.text .text.*)
        *(.rodata .rodata.*)
        . = ALIGN(4);
    } > mutable_sram

    .data : {
        *(.data .data.*)
        *(.sdata .sdata.*)
        . = ALIGN(4);
    } > mutable_sram

    _mutable_fw_load_end = .;

    .bss (NOLOAD) : {
        *(.bss .bss.*)
        *(.sbss .sbss.*)
        . = ALIGN(4);
    } > mutable_sram

    _mutable_fw_load_words = (_mutable_fw_load_end - 0x00004000 + 3) / 4;
}
