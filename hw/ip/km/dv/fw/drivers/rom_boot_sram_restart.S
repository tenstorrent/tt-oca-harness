/* Copyright 2026 Tenstorrent Inc. */
/**
 * @file rom_boot_sram_restart.S
 * @brief Enable SRAM scrambler and restart CPU from address 0.
 *
 * Called from C after writing the scrambler key. Uses no symbol references
 * for the jump so it works when .text is in VROM (JAL has ±1MB range).
 * Never returns.
 */

.section .text.rom_boot_sram_restart, "ax", @progbits
.global rom_boot_sram_restart
.type   rom_boot_sram_restart, @function

rom_boot_sram_restart:
    li   t0, 0x0000E018   /* KMCSR_SCRAMBLER_CTRL_REG */
    li   t1, 0x3          /* enable (bit 0) | lock (bit 1) */
    sw   t1, 0(t0)
    fence                 /* ensure store completes before jump */
    lui  t0, 0            /* load 0 for jump target */
    jalr zero, 0(t0)      /* jump to 0 (reset); no return */
    ebreak                /* safety if jump not taken */
.size rom_boot_sram_restart, . - rom_boot_sram_restart
