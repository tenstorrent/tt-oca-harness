/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/* Copyright 2026 Tenstorrent Inc. */
/**
 * @file rom_picorv32.c
 * @brief PicoRV32-specific CPU primitive implementations.
 */

#include "rom_picorv32.h"

#define ROM_PICORV32_CRC32C_WORD_INSN 0x58B5050Bu
#define ROM_PICORV32_CRC32C_BYTE_INSN 0x58B5150Bu
#define ROM_PICORV32_CRC8_ROHC_INSN 0x58B5250Bu

/**
 * @brief Set IRQ mask and return previous mask.
 *
 * A 1 bit means the corresponding IRQ is DISABLED (masked).
 * Uses PicoRV32 custom instruction (maskirq a0, a0).
 *
 * @param[in] new_mask New IRQ mask value.
 * @return Previous IRQ mask value.
 */
uint32_t rom_picorv32_maskirq(uint32_t new_mask) {
    register uint32_t a0 __asm__("a0") = new_mask;
    __asm__ volatile(".word 0x0605650b" /* maskirq a0, a0 */
                     : "+r"(a0)
                     :
                     : "memory");
    return a0;
}

/**
 * @brief Halt CPU until an interrupt arrives.
 *
 * Uses PicoRV32 custom instruction (waitirq).
 * Used by the main event loop when the message buffer is empty.
 */
void rom_picorv32_waitirq(void) {
    __asm__ volatile(".word 0x0100000b" ::: "memory"); /* waitirq x0 */
}

/**
 * @brief Execute one CRC-32C word-update custom instruction.
 *
 * @param[in] state Current CRC-32C chaining state.
 * @param[in] word  Next 32-bit input word.
 * @return Updated CRC-32C chaining state.
 */
uint32_t rom_picorv32_crc32c_word_update(uint32_t state, uint32_t word) {
    register uint32_t a0 __asm__("a0") = state;
    register uint32_t a1 __asm__("a1") = word;

    __asm__ volatile(".word 0x58B5050B" : "+r"(a0) : "r"(a1) :);
    return a0;
}

/**
 * @brief Execute one CRC-32C byte-update custom instruction.
 *
 * @param[in] state Current CRC-32C chaining state.
 * @param[in] data  Next input byte in bits [7:0].
 * @return Updated CRC-32C chaining state.
 */
uint32_t rom_picorv32_crc32c_byte_update(uint32_t state, uint32_t data) {
    register uint32_t a0 __asm__("a0") = state;
    register uint32_t a1 __asm__("a1") = data;

    __asm__ volatile(".word 0x58B5150B" : "+r"(a0) : "r"(a1) :);
    return a0;
}

/**
 * @brief Execute one CRC-8/ROHC byte-update custom instruction.
 *
 * @param[in] state Current CRC-8/ROHC chaining state in bits [7:0].
 * @param[in] data  Next input byte in bits [7:0].
 * @return Updated CRC-8/ROHC chaining state.
 */
uint32_t rom_picorv32_crc8_rohc_update(uint32_t state, uint32_t data) {
    register uint32_t a0 __asm__("a0") = state;
    register uint32_t a1 __asm__("a1") = data;

    __asm__ volatile(".word 0x58B5250B" : "+r"(a0) : "r"(a1) :);
    return a0;
}

/**
 * @brief Permanently halt the CPU via PicoRV32 hardware trap.
 *
 * Masks all IRQs then executes ebreak, which forces PicoRV32 into
 * cpu_state_trap (since the IRQ path requires !irq_mask[1] && !irq_active,
 * neither of which holds after masking).  The trap output is asserted
 * permanently.  A software loop follows as a defense-in-depth fallback.
 */
void rom_picorv32_halt_trap(void) {
    rom_picorv32_maskirq(0xFFFFFFFFu);
    __asm__ volatile("ebreak" ::: "memory");
    for (;;) rom_picorv32_waitirq();
}
