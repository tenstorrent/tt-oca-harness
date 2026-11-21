/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/*
 * SMC BL1 layout. Code, read-only data and the initial .data image fill the image window,
 * whose bytes the SEP BL1 measures and re-hashes; everything written at run time lives in the
 * RW window. The build preprocesses this file with smc_bl1_layout.h and links with
 * --orphan-handling=error, so no section can land anywhere unlisted.
 */

#include "smc_bl1_layout.h"

OUTPUT_ARCH(riscv)
ENTRY(_start)

MEMORY {
    image (rx) : ORIGIN = SMC_BL1_IMAGE_START, LENGTH = SMC_BL1_IMAGE_END - SMC_BL1_IMAGE_START
    rw (rw) : ORIGIN = SMC_BL1_RW_START, LENGTH = SMC_BL1_RW_END - SMC_BL1_RW_START
}

SECTIONS {
    .text : {
        KEEP(*(.text.start))
        *(.text .text.*)
    } > image

    .rodata : ALIGN(8) {
        *(.rodata .rodata.* .srodata .srodata.*)
    } > image

    .data : ALIGN(8) {
        __data_start = .;
        *(.data .data.*)
        __global_pointer$ = . + 0x800;
        *(.sdata .sdata.*)
        . = ALIGN(8);
        __data_end = .;
    } > rw AT > image
    __data_load = LOADADDR(.data);
    __image_end = __data_load + SIZEOF(.data);

    .bss (NOLOAD) : ALIGN(8) {
        __bss_start = .;
        *(.sbss .sbss.* .bss .bss.* COMMON)
        . = ALIGN(8);
        __bss_end = .;
    } > rw

    .stack (NOLOAD) : ALIGN(16) {
        . += SMC_BL1_STACK_SIZE;
        __stack_top = .;
    } > rw

    .comment 0 : { *(.comment) }
    .riscv.attributes 0 : { KEEP(*(.riscv.attributes)) }
    .debug_info 0 : { *(.debug_info) }
    .debug_abbrev 0 : { *(.debug_abbrev) }
    .debug_line 0 : { *(.debug_line) }
    .debug_line_str 0 : { *(.debug_line_str) }
    .debug_str 0 : { *(.debug_str) }
    .debug_aranges 0 : { *(.debug_aranges) }
    .debug_rnglists 0 : { *(.debug_rnglists) }
    .debug_loclists 0 : { *(.debug_loclists) }
    .debug_frame 0 : { *(.debug_frame) }
    .symtab 0 : { *(.symtab) }
    .strtab 0 : { *(.strtab) }
    .shstrtab 0 : { *(.shstrtab) }

    /DISCARD/ : { *(.eh_frame .eh_frame_hdr .note.* .rela.*) }
}

ASSERT(SMC_BL1_IMAGE_END <= SMC_BL1_RW_START, "the image and RW windows overlap")
ASSERT(ADDR(.text) == SMC_BL1_IMAGE_START, "the entry point is not at the image window base")
ASSERT(__data_start >= SMC_BL1_RW_START && __bss_start >= SMC_BL1_RW_START,
       "a writable section lies outside the RW window")
ASSERT(__stack_top <= SMC_BL1_RW_END, "the stack overruns the RW window")
ASSERT(__image_end <= SMC_BL1_IMAGE_END, "the image overruns its window")
