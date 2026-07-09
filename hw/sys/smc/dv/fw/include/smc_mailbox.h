/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

#ifndef SMC_MAILBOX_H
#define SMC_MAILBOX_H

#include "smc_reg_access.h"

static inline void write_mailbox(uint8_t mailbox_num, uint8_t is_inbound, uint32_t offset,
                                 uint64_t value) {
    volatile uint64_t *p_addr =
        (volatile uint64_t *)(uintptr_t)(SMC_TOP_SMC_MAILBOX_OUTBOUND_MAILBOX_0_BASE_ADDR +
                                         (mailbox_num * 0x1000 + is_inbound * 0x800) + offset);
    *p_addr = value;
}

static inline uint64_t read_mailbox(uint8_t mailbox_num, uint8_t is_inbound, uint32_t offset) {
    volatile uint64_t *p_addr =
        (volatile uint64_t *)(uintptr_t)(SMC_TOP_SMC_MAILBOX_OUTBOUND_MAILBOX_0_BASE_ADDR +
                                         (mailbox_num * 0x1000 + is_inbound * 0x800) + offset);
    return *p_addr;
}

#endif /* SMC_MAILBOX_H */
