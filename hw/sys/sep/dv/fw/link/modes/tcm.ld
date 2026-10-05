/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/* Copyright 2025 Tenstorrent Inc.
 *
 * Linker script for VeeR EL2 bare-metal DV environment.
 *
 * Memory Layout:
 *   ICCM (itcm): 0xC0000000 - 0xC003FFFF (256 KiB) - Instructions
 *   DCCM (dtcm): 0xC0040000 - 0xC005FFFF (128 KiB) - Data
 *
 * DCCM Layout (from low to high address):
 *   0xC0040000: .data section start
 *   ...       : .bss section
 *   ...       : Free space (stack grows down into this)
 *   0xC005FBFC: STACK (grows downward)
 *   0xC005FC00: INTVEC_BASE (1KB vector table, 1024-byte aligned)
 *   0xC005FFFF: End of DCCM
 */

OUTPUT_ARCH("riscv")
ENTRY(_start)

MEMORY {
    itcm (x)  : ORIGIN = 0xC0000000, LENGTH = 0x40000  /* 256 KiB - VeeR ICCM */
    dtcm (rw) : ORIGIN = 0xC0040000, LENGTH = 0x20000  /* 128 KiB - VeeR DCCM */
}

SECTIONS {
    /*=========================================================================
     * ICCM: Instruction Tightly Coupled Memory
     *========================================================================*/
    . = ORIGIN(itcm);

    .text : {
        . = ALIGN(4);
        *(.text.init)       /* Startup code first */
        *(.text._start)
        *(.text.init)
        *(.text)
        *(.text.*)
        . = ALIGN(4);
        /* Build identity, ICCM copy (fw_build_id.c): kept against
         * --gc-sections so the instruction image carries it too. */
        KEEP(*(.fw_build_id_itcm))
        . = ALIGN(4);

        /*
         * NMI handler - must be 256-byte aligned for VeeR nmi_vec.
         * Included in .text to ensure contiguous hex file output.
         */
        . = ALIGN(256);
        *(.nmi_handler)
        . = ALIGN(4);
    } > itcm

    /*=========================================================================
     * DCCM: Data Tightly Coupled Memory
     *========================================================================*/
    . = ORIGIN(dtcm);

    .data : {
        . = ALIGN(4);

        /* Global pointer for linker relaxation (placed early in .data) */
        PROVIDE(__global_pointer$ = . + 0x800);

        *(.data)
        *(.data.*)
        . = ALIGN(4);
        *(.sdata)
        *(.sdata.*)
        . = ALIGN(4);
        /* Build identity, DCCM copy (fw_build_id.c). Nothing references
         * it at run time, so it is kept explicitly against --gc-sections; the
         * host reads it out of the image (CHK-FW-IDENTITY). */
        KEEP(*(.fw_build_id_dtcm))
        . = ALIGN(4);
        *(.rodata)
        *(.rodata.*)
        . = ALIGN(4);
        *(.srodata)
        *(.srodata.*)
        . = ALIGN(4);
    } > dtcm

    /*
     * Thread-local storage.
     *
     * picolibc keeps state such as the rand() seed in .tdata/.tbss when it is
     * built with thread-local-storage enabled, and reaches it via tp-relative
     * accesses. Placing the TLS block explicitly gives crt0 a base symbol to
     * point tp at; without it tp stays 0 and the first access traps. When the
     * toolchain emits no TLS the block is empty.
     *
     * This firmware is single-threaded, so the linked .tdata doubles as the
     * initial thread's copy and needs no runtime relocation. .tbss is placed
     * directly ahead of .bss so the existing zeroing loop clears it too.
     */
    .tdata : {
        . = ALIGN(16);
        PROVIDE(__tls_base = .);
        *(.tdata)
        *(.tdata.*)
        . = ALIGN(4);
    } > dtcm

    .tbss (NOLOAD) : {
        . = ALIGN(4);
        BSS_START = .;
        *(.tbss)
        *(.tbss.*)
        *(.tcommon)
        . = ALIGN(4);
        PROVIDE(__tls_end = .);
    } > dtcm

    .bss (NOLOAD) : {
        . = ALIGN(4);
        *(.bss)
        *(.bss.*)
        *(.sbss)
        *(.sbss.*)
        *(COMMON)
        . = ALIGN(4);
        BSS_END = .;
    } > dtcm

    /*=========================================================================
     * Stack and Vector Table Layout
     *
     * The interrupt vector table MUST be at a 1024-byte (0x400) aligned
     * address for the VeeR EL2 meivt CSR. We place it at the END of DCCM
     * to maximize usable data space.
     *
     * Layout:
     *   BSS_END     ... grows upward
     *   STACK       ... grows downward from 0xC005FBFC
     *   INTVEC_BASE ... fixed at 0xC005FC00 (1KB reserved)
     *========================================================================*/

    /* Interrupt vector table for VeeR EL2 fast_interrupt_redirect
     * 256 entries x 4 bytes = 1024 bytes
     * MUST be 1024-byte aligned for meivt CSR */
    INTVEC_BASE = 0xC005FC00;

    /* Stack pointer: just below vector table, word-aligned
     * Stack grows DOWNWARD from here toward BSS_END */
    STACK = INTVEC_BASE - 4;

    /* Stack symbol aliases */
    stack  = STACK;
    _stack = STACK;

    ASSERT(BSS_END < (STACK - 0x1000), "BSS overlaps with minimum stack space!")
}
