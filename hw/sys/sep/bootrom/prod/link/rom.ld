/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/* Linker script for the SEP Boot ROM image.
 *
 * .text/.metadata/.rodata stay in Boot ROM at 0x10040000 and are read in place,
 * so read-only data does not consume DCCM. .data/.bss and the stack live in
 * DCCM; .data's initial image has a ROM LMA and vector.S copies it at boot. */

OUTPUT_ARCH("riscv")
ENTRY(_start)

MEMORY {
  /* Boot ROM: 64KiB read-only instruction memory. */
  rom  (rx)  : ORIGIN = 0x10040000, LENGTH = 0x00010000  /* 64KiB */

  /* DCCM (aka DTCM) window from EL2 snapshot.
   *   dccm_region=0xC, dccm_offset=0x40000, dccm_size=128 (KiB)
   *   → sadr=0xC0040000, eadr=0xC005FFFF */
  dccm (rwx) : ORIGIN = 0xC0040000, LENGTH = 0x00020000  /* 128KiB */
}

SECTIONS {
  . = ORIGIN(rom);

  .text : ALIGN(4) {
    KEEP(*(.text.init))
    KEEP(*(.text._start))
    *(.text .text.*)
  } > rom

  /* Keep metadata in Boot ROM so it is available to early code. */
  .metadata : ALIGN(4) {
    __metadata_start = .;
    KEEP(*(.metadata .metadata.*))
    __metadata_end = .;
  } > rom

  /* Read-only data lives in Boot ROM and is read in place by the LSU, so it does
   * not consume DCCM.  Relaxation is off (-mno-relax), so .srodata is addressed
   * absolutely rather than gp-relative and can safely live in ROM. */
  .rodata : ALIGN(4) {
    *(.rodata .rodata.* .srodata .srodata.*)
  } > rom

  /* Switch the VMA counter to DCCM. .data executes from DCCM but its initial
   * image is stored in ROM (AT> rom), so vector.S does a real ROM->DCCM copy. */
  . = ORIGIN(dccm);

  .data : ALIGN(4) {
    __data_start = .;
    *(.data .data.* .sdata .sdata.*)
    __data_end = .;
  } > dccm AT> rom
  __data_load_start = LOADADDR(.data);

  /* Global pointer for small data accesses (gp-relative). */
  PROVIDE(__global_pointer$ = __data_start + 0x800);

  .bss (NOLOAD) : ALIGN(4) {
    __bss_start = .;
    *(.bss .bss.* .sbss .sbss.*)
    *(COMMON)
    __bss_end = .;
  } > dccm

  /* Reserve the top of DCCM for bl0_state so the stack cannot overlap it. MUST
   * equal BL0_STATE_RESERVE_BYTES in include/bl0_state.h; rom_main.c compares
   * the pair at boot and fails loudly if they drift. */
  __bl0_state_reserve = 256;

  /* Stack grows downward from below the BL0 state region toward .bss.
   * __stack_top   = highest stack address (initial sp), below BL0 state.
   * __stack_bottom = lowest usable stack address (just above .bss).
   *
   * C16 stack canary: rom_main writes STACK_CANARY_VALUE at __stack_bottom
   * at init and re-checks it just before the BL1 hand-off.  If corrupted, it
   * means the stack overflowed into the .bss region — a fatal error. */
  __stack_top = ORIGIN(dccm) + LENGTH(dccm) - __bl0_state_reserve;
  __stack_bottom = ALIGN(__bss_end, 4);

  /* Catch accidental DCCM overflow early at link time. */
  ASSERT(__bss_end <= __stack_top, "DCCM overflow: .data/.bss exceeds available stack space (DCCM minus BL0 state reserve)")

  /* __stack_bottom is derived from __bss_end, so an output section placed after
   * .bss would move the canary out of the stack window and silently disable the
   * overflow check.  Keep .bss last in dccm. */
  ASSERT(__stack_bottom < __stack_top, "stack window is empty or inverted: __stack_bottom must be below __stack_top")

  /DISCARD/ : {
    *(.comment*)
    *(.eh_frame*)
    *(.eh_frame_hdr*)
    *(.note*)
  }
}
