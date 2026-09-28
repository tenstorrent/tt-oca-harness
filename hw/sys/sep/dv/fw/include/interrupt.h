/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/*
 * VeeR EL2 PIC interrupt utilities
 *
 * PIC register addresses are derived from RDL (see el2_pic.rdl)
 * PIC base: 0x1080_0000 (from sep_top.rdl)
 */

#ifndef INTERRUPT_H
#define INTERRUPT_H

#include <stdint.h>

// Handler function type - must be declared with __attribute__((interrupt("machine")))
typedef void (*pic_handler_t)(void);

// Register handler in vector table
void pic_register_handler(uint32_t source_id, pic_handler_t handler);

// Set interrupt priority (0 = disabled, 1-15 = enabled)
void pic_set_priority(uint32_t source_id, uint32_t priority);

// Configure gateway (type: 0=level, 1=edge; polarity: 0=active-high, 1=active-low)
void pic_set_gateway(uint32_t source_id, uint32_t type, uint32_t polarity);

// Enable/disable individual source
void pic_enable_source(uint32_t source_id);
void pic_disable_source(uint32_t source_id);

// Enable/disable global interrupts (mstatus.mie + mie.meie + thresholds)
void pic_enable_interrupts(void);
void pic_disable_interrupts(void);

#endif
