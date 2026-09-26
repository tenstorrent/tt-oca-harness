/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/* Copyright 2026 Tenstorrent Inc. */
/*
 * Key Manager firmware -- shared SRAM layout.
 *
 * Included from inside the SECTIONS{} block of link/km_production.ld. Before the
 * INCLUDE, the including script must define the `sram` MEMORY region (0x8000,
 * 32 KB) and map the .data load region with REGION_ALIAS("DATA_LOAD", <rom|vrom>).
 *
 * SRAM map (0x8000-0xFFFF, 32 KB), high addresses at the top:
 *
 *  0x10000  +------------------------------+
 *           | .rom_persist (1 KB, NOLOAD)  |  region 31: ROM-owned warm-persist,
 *   0xFC00  +------------------------------+               write-locked before handoff
 *           | .bss                         |  mutable-firmware area: packed downward
 *           +------------------------------+  from below persist
 *           | .data (loaded from DATA_LOAD)|
 *           +------------------------------+  <- DATA_START / stack top
 *           | stack (grows down)           |
 *           |              v               |
 *   0x8000  +------------------------------+  SRAM base
 */

/* Warm-persist region: highest 1 KB of SRAM (region 31, 0xFC00-0xFFFF).
 * Owned exclusively by ROM firmware (the mutable-firmware load area, stack, and
 * BSS/data live below 0xFC00). Cold-initialized by rom_persist_cold_init();
 * survives warm reset. Write-locked (SRAM_LOCK bit 31) before handoff to
 * mutable firmware, after which mutable code cannot write it. */
.rom_persist ORIGIN(sram) + LENGTH(sram) - 0x400 (NOLOAD) : {
    ROM_PERSIST_START = .;
    KEEP(*(.rom_persist))
    KEEP(*(.rom_persist.*))
    . = ROM_PERSIST_START + 0x400;
    ROM_PERSIST_END = .;
} > sram

/* Runtime SRAM, packed downward from just below the warm-persist region:
 * .bss at the top of the usable area, .data below it, stack below .data. */
.bss ADDR(.rom_persist) - SIZEOF(.bss) : {
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
} > sram AT> DATA_LOAD
DATA_LOAD_START = LOADADDR(.data);

/* Anchor for gp-relative small-data accesses. */
PROVIDE(__global_pointer$ = DATA_START + 0x800);

/* Main stack grows downward immediately below .data. */
STACK  = ADDR(.data);
stack  = STACK;
_stack = STACK;

/* --------------------------------------------------------------------------
 * Mutable-firmware load limit (static, worst-case ROM stack bounded).
 *
 * The ROM stack grows DOWN from STACK (= ADDR(.data)); mutable firmware is
 * loaded UP from the SRAM base (0x8000).  After a warm reset that follows
 * mutable-firmware execution the ROM re-runs and its stack may descend deeper
 * than it did when the image was first loaded, so the maximum image size MUST
 * be bounded by the worst-case ROM stack depth, not by the live stack pointer.
 *
 * __rom_max_stack is the worst-case ROM main-stack budget in bytes, supplied
 * via --defsym=__rom_max_stack=<bytes> from the firmware build and validated
 * against the real production ELF by scripts/km_stack_analyze.py.  PROVIDE gives
 * a safe default for ad-hoc links that do not pass it.
 *
 * KM_FW_LOAD_LIMIT is the exclusive upper bound of the load area: the lowest
 * address the ROM stack can reach, aligned DOWN to a 1 KB SRAM write-lock
 * region so the firmware image and the ROM stack never share a lock region.
 * -------------------------------------------------------------------------- */
PROVIDE(__rom_max_stack = 0x600);
KM_FW_LOAD_LIMIT = (STACK - __rom_max_stack) & ~(0x400 - 1);
PROVIDE(__km_fw_load_limit = KM_FW_LOAD_LIMIT);

/* Shared SRAM overflow assertions. */
ASSERT(ROM_PERSIST_END == ORIGIN(sram) + LENGTH(sram),
       "Linker error: warm-persist region must end at top of SRAM (0x10000)")
ASSERT(ADDR(.data) >= ORIGIN(sram),
       "SRAM overflow: data + bss + stack exceed SRAM below warm-persist region")
ASSERT(_stack >= ORIGIN(sram),
       "SRAM overflow: stack underflows SRAM base (0x8000)")
ASSERT(KM_FW_LOAD_LIMIT > ORIGIN(sram),
       "ROM stack budget (__rom_max_stack) leaves no SRAM for the mutable firmware load area")
