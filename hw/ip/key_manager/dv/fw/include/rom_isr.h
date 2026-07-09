/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/* Copyright 2026 Tenstorrent Inc. */
/**
 * @file rom_isr.h
 * @brief ISR dispatch framework for Key Manager firmware
 *
 * Declares the interrupt dispatch entry points: KMCSR sticky-error
 * handler, mailbox FIFO drain/fill, EBREAK/illegal-instruction
 * handler, bus-error handler, and fault trigger utilities.
 */

#ifndef ROM_ISR_H
#define ROM_ISR_H

#include <stdint.h>

/**
 * @brief PicoRV32 IRQ frame visible to C code.
 *
 * The assembly IRQ wrapper in `crt0.s` saves q-register interrupt context plus
 * RV32E GPR state into this frame before calling `rom_irq()`.
 */
typedef struct rom_irq_frame {
    uint32_t ret_addr; /**< Saved q0 return address (bit0 encodes instruction width). */
    uint32_t irq_mask; /**< Saved q1 IRQ pending bitmask. */
    uint32_t x1_ra;
    uint32_t x2_sp;
    uint32_t x3_gp;
    uint32_t x4_tp;
    uint32_t x5_t0;
    uint32_t x6_t1;
    uint32_t x7_t2;
    uint32_t x8_s0;
    uint32_t x9_s1;
    uint32_t x10_a0;
    uint32_t x11_a1;
    uint32_t x12_a2;
    uint32_t x13_a3;
    uint32_t x14_a4;
    uint32_t x15_a5;
} rom_irq_frame_t;

/**
 * @brief Top-level interrupt handler (called from crt0.s).
 *
 * Dispatches by IRQ bitmask in `frame->irq_mask`: EBREAK/illegal, bus error,
 * KMCSR sticky errors, mailbox. Any unrecognised IRQ bits trigger an
 * unrecoverable fault. Overrides the weak symbol in startup code.
 *
 * @param frame Saved interrupt frame. `ret_addr` can be edited by
 *                      handlers to adjust post-IRQ execution.
 */
void rom_irq(rom_irq_frame_t *frame);

/**
 * @brief Decode KMCSR sticky errors and route to unrecoverable fault handlers.
 */
void rom_isr_kmcsr(void) __attribute__((cold));

/**
 * @brief Handle EBREAK or illegal instruction trap.
 *
 * @param frame Saved IRQ frame.
 */
void rom_isr_ebreak(rom_irq_frame_t *frame) __attribute__((cold));

/**
 * @brief Handle AXI bus-error trap (always unrecoverable).
 *
 * @param frame Saved IRQ frame (unused).
 */
void rom_isr_buserr(rom_irq_frame_t *frame) __attribute__((cold));

/**
 * @brief Service the mailbox interrupt (drain inbound, fill outbound).
 */
void rom_isr_mailbox(void);

/**
 * @brief Service the ABR ML-KEM shared-key IRQ (ack sticky status + flag notify).
 */
void rom_isr_abr_sharedkey(void);

/**
 * @brief Notify-pending flag for the ABR ML-KEM shared-key IRQ.
 *
 * Set by the ISR (rom_isr_abr_sharedkey), sampled and cleared by the main
 * loop under a maskirq critical section.  Declared volatile to prevent
 * compiler caching across the ISR/main-loop boundary.
 */
extern volatile uint8_t g_abr_sk_notify_pending;

/**
 * @brief Enable the outbound write-space-available mailbox IRQ.
 */
void rom_mailbox_enable_outbound_drain_irq(void);

/**
 * @brief Disable the outbound write-space-available mailbox IRQ.
 */
void rom_mailbox_disable_outbound_drain_irq(void);

/**
 * @brief Enable the inbound data-available mailbox IRQ.
 */
void rom_mailbox_enable_inbound_irq(void);

/**
 * @brief Disable the inbound data-available mailbox IRQ.
 */
void rom_mailbox_disable_inbound_irq(void);

/**
 * @brief Enter the unrecoverable fault path (report fault and halt).
 *
 * @param fault_code Fault identifier (ROM_KM_UFAULT_*).
 */
void rom_trigger_unrecoverable(int8_t fault_code) __attribute__((noreturn, cold));

/**
 * @brief Signal a recoverable fault (set KMCSR flag, send response).
 *
 * @param fault_code Fault identifier (ROM_KM_RFAULT_*).
 */
void rom_trigger_recoverable(int8_t fault_code) __attribute__((cold));

/**
 * @brief Shred all SRAM with pseudorandom data and halt (assembly, noreturn).
 *
 * Implemented in rom_wipe.S. Called from rom_trigger_unrecoverable()
 * when shred gating is enabled.
 */
void rom_wipe_shred_sram(void) __attribute__((noreturn));

#endif /* ROM_ISR_H */
