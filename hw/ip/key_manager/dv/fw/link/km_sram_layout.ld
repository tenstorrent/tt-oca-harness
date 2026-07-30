/* Copyright 2026 Tenstorrent Inc. */
/*
 * Key Manager firmware -- shared SRAM layout.
 *
 * Included from inside the SECTIONS{} block of link/modes/vrom.ld (test) and
 * link/km_production.ld so both builds keep an identical SRAM map. Before the
 * INCLUDE, the including script must define the `sram` MEMORY region (0x4000,
 * 16 KB) and map the .data load region with REGION_ALIAS("DATA_LOAD", <rom|vrom>).
 */

.rom_persist ORIGIN(sram) + LENGTH(sram) - 0x200 (NOLOAD) : {
    ROM_PERSIST_START = .;
    KEEP(*(.rom_persist))
    KEEP(*(.rom_persist.*))
    . = ROM_PERSIST_START + 0x200;
    ROM_PERSIST_END = .;
} > sram

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

PROVIDE(__global_pointer$ = DATA_START + 0x800);

STACK  = ADDR(.data);
stack  = STACK;
_stack = STACK;

PROVIDE(__rom_max_stack = 0x600);
KM_FW_LOAD_LIMIT = (STACK - __rom_max_stack) & ~(0x200 - 1);
PROVIDE(__km_fw_load_limit = KM_FW_LOAD_LIMIT);

ASSERT(ROM_PERSIST_END == ORIGIN(sram) + LENGTH(sram),
       "Linker error: warm-persist region must end at top of SRAM (0x8000)")
ASSERT(ADDR(.data) >= ORIGIN(sram),
       "SRAM overflow: data + bss + stack exceed SRAM below warm-persist region")
ASSERT(_stack >= ORIGIN(sram),
       "SRAM overflow: stack underflows SRAM base (0x4000)")
ASSERT(KM_FW_LOAD_LIMIT > ORIGIN(sram),
       "ROM stack budget (__rom_max_stack) leaves no SRAM for mutable firmware")
