/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/* Copyright 2026 Tenstorrent Inc. */
/**
 * @file rom_picorv32.h
 * @brief PicoRV32-specific CPU primitives for Key Manager firmware.
 */

#ifndef ROM_PICORV32_H
#define ROM_PICORV32_H

#include <stdint.h>

/** @brief PicoRV32 IRQ bit: EBREAK / illegal instruction trap. */
#define PICORV32_IRQ_EBREAK (1 << 1)
/** @brief PicoRV32 IRQ bit: bus error / misaligned access trap. */
#define PICORV32_IRQ_BUSERR (1 << 2)
/** @brief PicoRV32 IRQ bit: KMCSR sticky errors (level-sensitive). */
#define PICORV32_IRQ_KMCSR (1 << 3)
/** @brief PicoRV32 IRQ bit: mailbox inbound data (level-sensitive). */
#define PICORV32_IRQ_MBOX (1 << 4)
/** @brief PicoRV32 IRQ bit: ABR ML-KEM shared-key ready (latched pulse, bit 5). */
#define PICORV32_IRQ_ABR_SHAREDKEY (1 << 5)

/** @brief Bitmask of all IRQ sources handled by rom_irq(). */
#define PICORV32_IRQ_KNOWN_MASK \
    (PICORV32_IRQ_EBREAK | PICORV32_IRQ_BUSERR | PICORV32_IRQ_KMCSR | PICORV32_IRQ_MBOX | \
     PICORV32_IRQ_ABR_SHAREDKEY)

/**
 * @brief Set IRQ mask and return previous mask.
 *
 * A 1 bit means the corresponding IRQ is DISABLED (masked).
 * Uses PicoRV32 custom instruction (maskirq a0, a0).
 *
 * @param new_mask New IRQ mask value.
 * @return Previous IRQ mask value.
 */
uint32_t rom_picorv32_maskirq(uint32_t new_mask);

/**
 * @brief Halt CPU until an interrupt arrives.
 *
 * Uses PicoRV32 custom instruction (waitirq).
 * Used by the main event loop when the message buffer is empty.
 */
void rom_picorv32_waitirq(void);

/**
 * @brief Execute one CRC-32C word-update custom instruction.
 *
 * Consumes the input word in little-endian byte order and returns the updated
 * CRC-32C chaining state prior to the final XOR.
 *
 * @param state Current CRC-32C chaining state.
 * @param word Next 32-bit input word.
 * @return Updated CRC-32C chaining state.
 */
uint32_t rom_picorv32_crc32c_word_update(uint32_t state, uint32_t word);

/**
 * @brief Execute one CRC-32C byte-update custom instruction.
 *
 * Consumes only `data[7:0]` and returns the updated CRC-32C chaining state
 * prior to the final XOR.
 *
 * @param state Current CRC-32C chaining state.
 * @param data Next input byte in bits [7:0].
 * @return Updated CRC-32C chaining state.
 */
uint32_t rom_picorv32_crc32c_byte_update(uint32_t state, uint32_t data);

/**
 * @brief Execute one CRC-8/ROHC byte-update custom instruction.
 *
 * Consumes only `data[7:0]` and returns the updated CRC-8/ROHC chaining state
 * zero-extended in bits [31:8].
 *
 * @param state Current CRC-8/ROHC chaining state in bits [7:0].
 * @param data Next input byte in bits [7:0].
 * @return Updated CRC-8/ROHC chaining state.
 */
uint32_t rom_picorv32_crc8_rohc_update(uint32_t state, uint32_t data);

/**
 * @brief Permanently halt the CPU via PicoRV32 hardware trap.
 *
 * Masks all IRQs then executes ebreak, which forces PicoRV32 into
 * cpu_state_trap (since the IRQ path requires !irq_mask[1] && !irq_active,
 * neither of which holds after masking).  The trap output is asserted
 * permanently.  A software loop follows as a defense-in-depth fallback.
 */
__attribute__((noreturn)) void rom_picorv32_halt_trap(void);

#endif /* ROM_PICORV32_H */
