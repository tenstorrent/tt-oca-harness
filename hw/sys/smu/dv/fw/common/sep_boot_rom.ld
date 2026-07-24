OUTPUT_ARCH("riscv")
ENTRY(_start)

SECTIONS
{
    . = 0x10040000;
    .text : {
        KEEP(*(.text.start))
        *(.text .text.*)
    }
}
