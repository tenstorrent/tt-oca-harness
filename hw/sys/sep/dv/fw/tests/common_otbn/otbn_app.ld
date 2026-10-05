/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/* OCAH OTBN Linker Script - Static Version of OpenTitan Layout
 *
 * Based on OpenTitan OTBN memory layout (otbn.hjson):
 * - IMEM: 8KB instruction memory starting at 0x0
 * - DMEM: 4KB total data memory (Harvard architecture)
 *   - Bus-accessible: 3KB (0x000-0xBFF) - accessible via register interface
 *   - Scratchpad: 1KB (0xC00-0xFFF) - internal only, not bus-accessible
 *
 * This provides static offsets matching OpenTitan's dynamic hjson-based layout.
 */

MEMORY
{
    /* OTBN Harvard architecture - separate instruction and data memories */
    imem (rx)           : ORIGIN = 0x00000000, LENGTH = 8K     /* 8KB instruction memory */
    dmem (rw)           : ORIGIN = 0x00000000, LENGTH = 3K     /* 3KB bus-accessible data memory */
    dmem_scratch (rw)   : ORIGIN = 0x00000C00, LENGTH = 1K     /* 1KB scratchpad memory */
}

SECTIONS
{
    /* Instruction memory section */
    .text 0x0 : ALIGN(4)
    {
        _imem_start = .;

        /* Entry point must be first */
        KEEP(*(.text.start))

        /* Any remaining text sections */
        *(.text*)

        . = ALIGN(4);
        _imem_end = .;
        _imem_size = _imem_end - _imem_start;
    } >imem

    /* Data memory section */
    .data 0x0 : ALIGN(32)
    {
        _dmem_data_start = .;
        *(.data*)
        . = ALIGN(4);
        _dmem_data_end = .;
    } >dmem

    .bss : ALIGN(32)
    {
        _dmem_bss_start = .;
        *(.bss*)
        . = ALIGN(4);
        _dmem_bss_end = .;
    } >dmem

    /* Scratchpad section - separate memory region at 0xC00 (matches OpenTitan) */
    .scratchpad 0xC00 (NOLOAD) : ALIGN(32)
    {
        _dmem_scratch_start = .;
        *(.scratchpad*)
        . = ALIGN(4);
        _dmem_scratch_end = .;
    } >dmem_scratch

    /* Calculate memory layout offsets (similar to OpenTitan) */
    _dmem_bss_offset = ADDR(.bss) - ADDR(.data);
    _dmem_scratch_offset = ADDR(.scratchpad);

    /* Remove debug sections to keep binary clean */
    /DISCARD/ :
    {
        *(.debug*)
        *(.comment*)
        *(.note*)
    }
}

/* Set entry point */
ENTRY(_start)
