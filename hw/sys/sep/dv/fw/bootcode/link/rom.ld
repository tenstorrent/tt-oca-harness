/* Linker script for SEP bootcode (Boot ROM + DCCM execution).
 *
 * Code (.text) and metadata execute from Boot ROM (0x10040000) via the IFU
 * AXI demux in sep_cpu.sv.  Read-only data (.rodata), initialized data (.data),
 * and BSS reside in DCCM because the LSU cannot access Boot ROM (ROM is not
 * a crossbar target — only IFU can reach it through the dedicated demux).
 *
 * In the DV environment, Boot ROM is preloaded via +BOOT_ROM_VMEM_FILE and
 * DCCM is preloaded via BACKDOOR_TCM (+DTCM_HEX_FILE).
 */

OUTPUT_ARCH("riscv")
ENTRY(_start)

MEMORY {
  /* Boot ROM: 64KiB read-only instruction memory.
   *   SEP_BOOT_ROM_MEM_BASE_ADDR = 0x10040000
   *   SEP_BOOT_ROM_MEM_SIZE      = 0x00010000 (64KiB)
   *   Hardware: prim_rom 16384×64-bit = 128KiB physical, but address
   *   decode in IFU demux uses SEP_BOOT_ROM_MEM_SIZE (64KiB). */
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

  /* Switch location counter to DCCM for runtime sections.
   *
   * The LSU cannot access Boot ROM addresses (they are only reachable via
   * the IFU demux).  Therefore .rodata and .data must reside in DCCM.
   * DCCM is preloaded by the DV testbench (BACKDOOR_TCM). */
  . = ORIGIN(dccm);

  /* Read-only data in DCCM (LSU cannot read Boot ROM). */
  .rodata : ALIGN(4) {
    *(.rodata .rodata.* .srodata .srodata.*)
  } > dccm

  .data : ALIGN(4) {
    __data_start = .;
    *(.data .data.* .sdata .sdata.*)
    __data_end = .;
  } > dccm
  __data_load_start = LOADADDR(.data);

  /* Global pointer for small data accesses (gp-relative). */
  PROVIDE(__global_pointer$ = __data_start + 0x800);

  .bss (NOLOAD) : ALIGN(4) {
    __bss_start = .;
    *(.bss .bss.* .sbss .sbss.*)
    *(COMMON)
    __bss_end = .;
  } > dccm

  /* BL0 state structure is placed at the very top of DCCM (bl0_state.h:
   *   BL0_STATE_ADDR = OROM_DCCM_BASE + OROM_DCCM_SIZE - BL0_STATE_SIZE).
   * Reserve space so the stack does not overlap with it.
   * bl0_state is ~80 bytes; round up to 128 for alignment + future growth. */
  __bl0_state_reserve = 128;

  /* Stack grows downward from below the BL0 state region toward .bss.
   * __stack_top   = highest stack address (initial sp), below BL0 state.
   * __stack_bottom = lowest usable stack address (just above .bss).
   *
   * C16 stack canary: rom_main writes STACK_CANARY_VALUE at __stack_bottom
   * at init and checks it before PASS.  If the canary is corrupted, it
   * means the stack overflowed into the .bss region — a fatal error. */
  __stack_top = ORIGIN(dccm) + LENGTH(dccm) - __bl0_state_reserve;
  __stack_bottom = ALIGN(__bss_end, 4);

  /* Catch accidental DCCM overflow early at link time. */
  ASSERT(__bss_end <= __stack_top, "DCCM overflow: .data/.bss exceeds available stack space (DCCM minus BL0 state reserve)")

  /DISCARD/ : {
    *(.comment*)
    *(.eh_frame*)
    *(.eh_frame_hdr*)
    *(.note*)
  }
}
