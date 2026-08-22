/* Copyright (c) 2020 SiFive Inc. */
/* SPDX-License-Identifier: Apache-2.0 */
OUTPUT_ARCH("riscv")

ENTRY(_enter)

MEMORY
{
    testram (airwx) : ORIGIN = 0xc0060000, LENGTH = 1M
    rom (rx) : ORIGIN = 0xc0040000, LENGTH = 128K
}

PHDRS
{
    rom PT_LOAD;
    ram_init PT_LOAD;
    tls PT_TLS;
    ram PT_LOAD;
    itim_init PT_LOAD;
    lim_init PT_LOAD;
}

SECTIONS
{
    __stack_size = DEFINED(__stack_size) ? __stack_size : 0x400;
    PROVIDE(__stack_size = __stack_size);
    __heap_size = DEFINED(__heap_size) ? __heap_size : 0x800;
    PROVIDE(__metal_boot_hart = 0);
    PROVIDE(__metal_chicken_bit = 1);
    PROVIDE(__metal_eccscrub_bit = 0);

    /* Read-only sections in ROM */
    .init : {
        KEEP (*(.text.metal.init.enter))
        KEEP (*(.text.metal.init.*))
        KEEP (*(SORT_NONE(.init)))
        KEEP (*(.text.libgloss.start))
    } >rom AT>rom :rom =0x00100073

    .fini : {
        KEEP (*(SORT_NONE(.fini)))
    } >rom AT>rom :rom =0x00100073

    .preinit_array : ALIGN(8) {
        PROVIDE_HIDDEN (__preinit_array_start = .);
        KEEP (*(.preinit_array))
        PROVIDE_HIDDEN (__preinit_array_end = .);
    } >rom AT>rom :rom =0x00100073

    .init_array : ALIGN(8) {
        PROVIDE_HIDDEN (__init_array_start = .);
        KEEP (*(SORT_BY_INIT_PRIORITY(.init_array.*) SORT_BY_INIT_PRIORITY(.ctors.*)))
        KEEP (*(.init_array EXCLUDE_FILE (*crtbegin.o *crtbegin?.o *crtend.o *crtend?.o ) .ctors))
        PROVIDE_HIDDEN (__init_array_end = .);
        PROVIDE_HIDDEN ( metal_constructors_start = .);
        KEEP (*(SORT_BY_INIT_PRIORITY(.metal.init_array.*)));
        KEEP (*(.metal.init_array));
        PROVIDE_HIDDEN ( metal_constructors_end = .);
    } >rom AT>rom :rom =0x00100073

    .fini_array : ALIGN(8) {
        PROVIDE_HIDDEN (__fini_array_start = .);
        KEEP (*(SORT_BY_INIT_PRIORITY(.fini_array.*) SORT_BY_INIT_PRIORITY(.dtors.*)))
        KEEP (*(.fini_array EXCLUDE_FILE (*crtbegin.o *crtbegin?.o *crtend.o *crtend?.o ) .dtors))
        PROVIDE_HIDDEN (__fini_array_end = .);
        PROVIDE_HIDDEN ( metal_destructors_start = .);
        KEEP (*(SORT_BY_INIT_PRIORITY(.metal.fini_array.*)));
        KEEP (*(.metal.fini_array));
        PROVIDE_HIDDEN ( metal_destructors_end = .);
    } >rom AT>rom :rom =0x00100073

    .ctors : {
        KEEP (*crtbegin.o(.ctors))
        KEEP (*crtbegin?.o(.ctors))
        KEEP (*(EXCLUDE_FILE (*crtend.o *crtend?.o ) .ctors))
        KEEP (*(SORT(.ctors.*)))
        KEEP (*(.ctors))
        KEEP (*(.metal.ctors .metal.ctors.*))
    } >rom AT>rom :rom =0x00100073

    .dtors : {
        KEEP (*crtbegin.o(.dtors))
        KEEP (*crtbegin?.o(.dtors))
        KEEP (*(EXCLUDE_FILE (*crtend.o *crtend?.o ) .dtors))
        KEEP (*(SORT(.dtors.*)))
        KEEP (*(.dtors))
        KEEP (*(.metal.dtors .metal.dtors.*))
    } >rom AT>rom :rom =0x00100073

    .rodata : {
        *(.rdata)
        *(.rodata .rodata.*)
        *(.gnu.linkonce.r.*)
        . = ALIGN(8);
        *(.srodata.cst16)
        *(.srodata.cst8)
        *(.srodata.cst4)
        *(.srodata.cst2)
        *(.srodata .srodata.*)
    } >rom AT>rom :rom =0x00100073

    .text : {
        *(.text.unlikely .text.unlikely.*)
        *(.text.startup .text.startup.*)
        *(.text .text.*)
        *(.gnu.linkonce.t.*)
    } >rom AT>rom :rom =0x00100073

    /* Initialized data sections (loaded from ROM) */
    .data : ALIGN(8) {
        *(.data .data.*)
        *(.gnu.linkonce.d.*)
        . = ALIGN(8);
        PROVIDE( __global_pointer$ = . + 0x800 );
        *(.sdata .sdata.* .sdata2.*)
        *(.gnu.linkonce.s.*)
    } >testram AT>rom :ram_init

    .tdata : ALIGN(8) {
        PROVIDE( __tls_base = . );
        *(.tdata .tdata.* .gnu.linkonce.td.*)
    } >testram AT>rom :tls :ram_init

    PROVIDE( __tdata_source = LOADADDR(.tdata) );
    PROVIDE( __tdata_size = SIZEOF(.tdata) );
    PROVIDE( metal_segment_data_source_start = LOADADDR(.data) );
    PROVIDE( metal_segment_data_target_start = ADDR(.data) );
    PROVIDE( metal_segment_data_target_end = ADDR(.tdata) + SIZEOF(.tdata) );

    .tbss : ALIGN(8) {
        *(.tbss .tbss.* .gnu.linkonce.tb.*)
        *(.tcommon .tcommon.*)
        PROVIDE( __tls_end = . );
    } >testram AT>testram :tls :ram
    PROVIDE( __tbss_size = SIZEOF(.tbss) );
    PROVIDE( __tls_size = __tls_end - __tls_base );

    .tbss_space : ALIGN(8) {
        . = . + __tbss_size;
    } >testram :ram

    .bss (NOLOAD): ALIGN(8) {
        *(.sbss*)
        *(.gnu.linkonce.sb.*)
        *(.bss .bss.*)
        *(.gnu.linkonce.b.*)
        *(COMMON)
    } >testram :ram

    PROVIDE( metal_segment_bss_source_start = LOADADDR(.tbss) );
    PROVIDE( metal_segment_bss_target_start = ADDR(.tbss) );
    PROVIDE( metal_segment_bss_target_end = ADDR(.bss) + SIZEOF(.bss) );

    .itim : ALIGN(8) {
        *(.itim .itim.*)
    } >testram AT>rom :itim_init

    PROVIDE( metal_segment_itim_source_start = LOADADDR(.itim) );
    PROVIDE( metal_segment_itim_target_start = ADDR(.itim) );
    PROVIDE( metal_segment_itim_target_end = ADDR(.itim) + SIZEOF(.itim) );

    .lim : ALIGN(8) {
        *(.lim .lim.*)
    } >testram AT>rom :lim_init

    PROVIDE( metal_segment_lim_source_start = LOADADDR(.lim) );
    PROVIDE( metal_segment_lim_target_start = ADDR(.lim) );
    PROVIDE( metal_segment_lim_target_end = ADDR(.lim) + SIZEOF(.lim) );

    /*
     * Fill all unused ROM after every ROM-loaded section with the 32-bit
     * RISC-V EBREAK instruction. The linker emits 0x73001000 so the
     * little-endian image contains 0x00100073. The trap handler uses these
     * symbols to distinguish padding breakpoints from generic exceptions.
     */
    /* ALIGN(8): objcopy's verilog writer (data width 8) requires the section
     * VMA to be a multiple of the data width. */
    .rom_padding : ALIGN(8) {
        __rom_used_end = .;
        FILL(0x73001000);
        . = ORIGIN(rom) + LENGTH(rom) - 1;
        BYTE(0x00);
    } >rom AT>rom :rom
    __rom_end = ORIGIN(rom) + LENGTH(rom);

    .stack (NOLOAD) : ALIGN(16) {
        PROVIDE(metal_segment_stack_begin = .);
        . += __stack_size; /* Hart 0 */
        PROVIDE( _sp = . );
        . += __stack_size; /* Hart 1 */
        . += __stack_size; /* Hart 2 */
        . += __stack_size; /* Hart 3 */
        PROVIDE(metal_segment_stack_end = .);
    } >testram :ram

    .heap (NOLOAD) : ALIGN(8) {
        PROVIDE( __end = . );
        PROVIDE( __heap_start = . );
        PROVIDE( metal_segment_heap_target_start = . );
        . = DEFINED(__heap_max) ? MIN( LENGTH(testram) - ( . - ORIGIN(testram)) , 0x10000000) : __heap_size;
        PROVIDE( metal_segment_heap_target_end = . );
        PROVIDE( _heap_end = . );
        PROVIDE( __heap_end = . );
    } >testram :ram

    /DISCARD/ : {
        *(.eh_frame .eh_frame.*)
    }
}
