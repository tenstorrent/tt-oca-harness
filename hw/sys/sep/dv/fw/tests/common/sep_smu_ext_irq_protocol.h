/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */
/*
 * SEP_SMU_008  smu_sep_external_irq_test  -- shared protocol contract.
 *
 * Card OWNER-CORRECTION named PIC source 35 under NUM_INTERNAL_IRQS=34.
 * This RTL has NUM_INTERNAL_IRQS=38, so wrapper pin bit0 concatenates to
 * sep_interrupts[38] -> EL2 PIC source 39. The exact producer is still pin
 * bit0; the source ID is the concat mapping, not a hedged candidate window.
 */
#ifndef SEP_SMU_EXT_IRQ_PROTOCOL_H
#define SEP_SMU_EXT_IRQ_PROTOCOL_H

#define IRQ008_SMC_IMAGE_FIRST_WORD 0x41014081
#define IRQ008_SMC_ENTRY 0x00000000C00601B2ULL
#define IRQ008_FW_POLL_LIMIT 4000000

#define IRQ008_PIN_BIT 0
#define IRQ008_PIC_SOURCE 39
#define IRQ008_MEIPL 1
#define IRQ008_MEIGWCTRL 0x2
#define IRQ008_DISABLED_MCYCLE 256
#define IRQ008_POST_ISR_MCYCLE 32

#define IRQ008_S0_FAIL 0x00820FA1
#define IRQ008_BRINGUP_OK 0x00820000
#define IRQ008_DISABLED_ARMED 0x00820001
#define IRQ008_DISABLED_CLEAN 0x00820002
#define IRQ008_ARMED 0x00820003
#define IRQ008_ISR_SEEN 0x00820004
#define IRQ008_CLEARED 0x00820005

#endif /* SEP_SMU_EXT_IRQ_PROTOCOL_H */
