/* Linker script for SEP bootcode (self-contained Boot ROM image).
 *
 * Code (.text), metadata, and read-only data (.rodata/.srodata) reside in and
 * are read from Boot ROM (0x10040000): the IFU reaches ROM via its AXI demux,
 * and the LSU reaches ROM via the LSU->ROM demux (sep_cpu.sv) and the boot-ROM
 * AXI mux (sep.sv, u_boot_rom_axi_mux), so read-only data does not consume DCCM.
 *
 * Writable runtime data (.data/.bss) and the stack live in DCCM.  .data's
 * initial image is stored in Boot ROM (LMA via AT> rom) and copied to DCCM by
 * vector.S at boot; .bss is zeroed there.
 *
 * In the DV environment, Boot ROM is preloaded via +BOOT_ROM_VMEM_FILE; DCCM
 * needs no firmware preload (DATA_SIZE=0), only ECC init via init_tcms().
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

  /* Read-only data lives in Boot ROM and is read in place by the LSU (via the
   * LSU->ROM demux / boot-ROM AXI mux), so it does not consume DCCM.  Relaxation
   * is disabled (-mno-relax / --no-relax), so .srodata is addressed absolutely
   * rather than gp-relative and can safely live in ROM. */
  .rodata : ALIGN(4) {
    *(.rodata .rodata.* .srodata .srodata.*)
  } > rom

  /* Switch the VMA location counter to DCCM for writable runtime sections.
   * .data executes from DCCM, but its initial image is stored in Boot ROM
   * (LMA via AT> rom) and copied to DCCM by vector.S at boot.  __data_load_start
   * therefore resolves to a ROM address, making the vector.S copy a real
   * ROM->DCCM copy (it was a no-op self-copy when .data's LMA was in DCCM). */
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
