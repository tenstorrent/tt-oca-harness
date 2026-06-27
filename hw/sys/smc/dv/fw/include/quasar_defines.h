/* SPDX-License-Identifier: Apache-2.0 */
/* (c) 2026 Tenstorrent USA Inc */

#ifndef __QUASAR_DEFINES_DEFINED__
#define __QUASAR_DEFINES_DEFINED__

// Note:  RISC-V PLIC, interrupt 0 is reserved.
// Specifically, interrupt ID 0 is reserved to represent "no interrupt".
// Therefore, the first interrupt will be mapped to ID 1.
#define SMN_MASTER_INTERRUPT_ID_BASE (1)
#define SMN_SLAVE_INTERRUPT_ID_BASE (2)
#define SMN_MAILBOX_INTERRUPT_ID_BASE (3)
#define NOC_SECURITY_FENCE_INTERRUPT_ID_BASE (4)
#define NIU_MASTER_TRANSACTION_COUNT_INTERRUPT_ID_BASE (5)
#define NIU_TIMEOUT_INTERRUPT_ID_BASE (6)
#define NOC_MEMORY_PARITY_ERROR_INTERRUPT_ID_BASE (7)
#define NOC_HEADER_1BIT_ERROR_INTERRUPT_ID_BASE (8)
#define NOC_HEADER_2BIT_ERROR_INTERRUPT_ID_BASE (9)
#define NEO_RAS_EVENT_INTERRUPT_ID_BASE (10)
#define DM_RAS_EVENT_INTERRUPT_ID_BASE (11)
#define TILE_INTERRUPT_ID_BASE (12)
#define DD_PLL_LOCK_ID_BASE (72)
#define AI_PLL_LOCK_ID_BASE (73)
#define RESERVED_73_88_ID_BASE (74)
#define GPIO_INTERRUPTS_ID_BASE (90)
#define RESERVED_105_127_ID_BASE (106)

#define NUM_TILE_EVENTS_INTERRUPTS (60)

#endif
