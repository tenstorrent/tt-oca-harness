/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/* BL1 linker script: ICCM code, DCCM data.
 *
 * Memory layout:
 *   ICCM: 0xC0000000 - 0xC003FFFF (256 KiB)  — .text, and the load image
 *   DCCM: 0xC0040000 - 0xC005FEFF (128 KiB minus the ROM's bl0_state reserve)
 *
 * The split is what the hardware allows.  The IFU
 * fetches from ICCM directly, but the LSU cannot reach ICCM at all: ICCM and
 * DCCM share VeeR region 0xC, so el2_lsu_addrcheck faults every 0xCxxxxxxx
 * address that falls outside DCCM's own offset range, and the access never even
 * leaves the core.  A single `lbu` against a string constant would take an
 * unmapped access fault.  So nothing BL1 loads or stores may live in ICCM:
 * .rodata, .data and .bss all have to be in DCCM, and only .text stays behind.
 *
 * rom_handoff_bl1() DMAs ONE flat blob to ONE address, so .rodata/.data are
 * linked with their load address (LMA) in ICCM, directly after .text, and their
 * runtime address (VMA) in DCCM.  _start cannot copy them from that LMA -- same
 * fault -- so it reads them from the SRAM copy the ROM handed to the DMA, whose
 * address arrives in bl0_state.bl1_image_src_addr, at the same offset.  Keeping
 * the LMA in ICCM is therefore what defines that offset, not a real source.
 * .rodata is merged into .data because that makes it one copy with one pair of
 * symbols; the cost is that BL1's read-only data is writable at runtime.
 *
 * The DCCM window stops __bl0_state_reserve (256) bytes short of the top of
 * DCCM.  bl0_state lives up there and BL1 reads it, so BL1's own data must not
 * reach it.  The stack is NOT described here: BL1 inherits the ROM's sp, which
 * starts just below that same reserve and grows down toward this data.
 *
 * IMPORTANT: .text.init MUST come first — _start lives there.
 *
 * The binary MUST be 4-byte aligned (copy width = 4 bytes).
 */

OUTPUT_ARCH("riscv")

MEMORY {
    iccm (rx) : ORIGIN = 0xC0000000, LENGTH = 0x40000   /* 256 KiB */
    dccm (rw) : ORIGIN = 0xC0040000, LENGTH = 0x1FF00   /* 128 KiB - 256 B reserve */
}

ENTRY(_start)

SECTIONS {

    /*=====================================================================
     * Code — fetched from ICCM by the IFU, never loaded or stored by BL1
     *====================================================================*/
    . = ORIGIN(iccm);

    .text : {
        *(.text.init)
        *(.text)
        *(.text.*)
        . = ALIGN(4);
    } > iccm

    /*=====================================================================
     * Read-only and initialized data — runs from DCCM, ships in ICCM
     *====================================================================*/
    . = ORIGIN(dccm);

    .data : ALIGN(4) {
        __data_start = .;
        *(.rodata)
        *(.rodata.*)
        *(.srodata)
        *(.srodata.*)
        *(.data)
        *(.data.*)
        *(.sdata)
        *(.sdata.*)
        . = ALIGN(4);
        __data_end = .;
    } > dccm AT> iccm
    __data_load_start = LOADADDR(.data);

    .bss (NOLOAD) : ALIGN(4) {
        BSS_START = .;
        *(.bss)
        *(.bss.*)
        *(.sbss)
        *(.sbss.*)
        . = ALIGN(4);
        BSS_END = .;
    } > dccm

    /* The load image is .text followed by .data's LMA, so it must fit in ICCM. */
    ASSERT(__data_load_start + (__data_end - __data_start) <= ORIGIN(iccm) + LENGTH(iccm),
           "BL1 load image overflows ICCM")

    /* BSS is the last thing in DCCM, so this is the check that BL1's data has
     * not grown into the ROM's bl0_state reserve. */
    ASSERT(BSS_END <= ORIGIN(dccm) + LENGTH(dccm),
           "BL1 data overflows its DCCM window and would overlap bl0_state")
}
