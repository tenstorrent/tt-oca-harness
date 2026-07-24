// ROM mailbox (STDOUT) interface for Phase 1 bring-up.
//
// This is intentionally tiny:
// - Used for text output ("ROM\n") and machine-readable status markers.
// - Works without libc and before full platform integration is available.

#pragma once

#include <stdint.h>

#include "rom_mmio.h"

// SEP STDOUT mailbox (same as dv/sep/tb/tb_uvm/sv/sep_wrap_uvm_top.sv monitor).
enum {
    ROM_MBX_ADDR = 0x80000000u,
};

// Magic words used by DV to detect pass/fail.
enum {
    ROM_FW_MAGIC0 = 0xA5A55A5Au,
    ROM_FW_PASS = 0xCAFEBABEu,
    ROM_FW_FAIL = 0xDEADBEEFu,
};

// Status codes and reporting are now in errors.h (STATUS_OUT / report_status).

static inline void rom_mbx_putc(char c) { mmio_write8(ROM_MBX_ADDR, (uint8_t)c); }
static inline void rom_mbx_putw(uint32_t w) { mmio_write32(ROM_MBX_ADDR, w); }

static inline void rom_mbx_puts(const char *s) {
    while (*s) {
        rom_mbx_putc(*s++);
    }
}

static inline void rom_mbx_put_hex32(uint32_t v) {
    static const char kHex[] = "0123456789abcdef";
    rom_mbx_puts("0x");
    for (int shift = 28; shift >= 0; shift -= 4) {
        rom_mbx_putc(kHex[(v >> shift) & 0xFu]);
    }
}

__attribute__((noreturn)) static inline void rom_mbx_fail_and_hang(uint32_t code) {
    rom_mbx_putw(ROM_FW_MAGIC0);
    rom_mbx_putw(ROM_FW_FAIL);
    rom_mbx_putw(code);
    for (;;) {
        __asm__ volatile("wfi");
    }
}
