// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// SEP-side (EL2) driver for the KM <-> SEP mailbox, used to coordinate the EL2
// host CPU with the Key Manager's PicoRV32 second core. Header-only. Addresses
// and STATUS bits come from generated sep_addr.h / km_mailbox_sep.h (via sep.h).
// The KM core uses its own KM-local aliases; this header is the host/EL2 view.

#ifndef SEP_KM_MAILBOX_H
#define SEP_KM_MAILBOX_H

#include <stdint.h>

#include "sep.h"

#define SEP_KM_MBOX_WRITE_DATA SEP_TOP_KM_MAILBOX_SEP_SEP_WRITE_DATA_BASE_ADDR
#define SEP_KM_MBOX_WRITE_SEPARATOR SEP_TOP_KM_MAILBOX_SEP_SEP_WRITE_SEPARATOR_BASE_ADDR
#define SEP_KM_MBOX_READ_DATA SEP_TOP_KM_MAILBOX_SEP_SEP_READ_DATA_BASE_ADDR
#define SEP_KM_MBOX_STATUS SEP_TOP_KM_MAILBOX_SEP_SEP_STATUS_BASE_ADDR

#define SEP_KM_MBOX_OUTBOUND_EMPTY KM_MAILBOX_SEP__STATUS_REG__OUTBOUND_EMPTY_bm

static inline uint32_t sep_km_mbox_rd(uint32_t addr) {
    return *(volatile uint32_t *)addr;
}

static inline void sep_km_mbox_wr(uint32_t addr, uint32_t value) {
    *(volatile uint32_t *)addr = value;
}

// Receive one word from the KM (bounded). Returns 0 on success and stores the
// payload in *out; returns -1 on timeout (a wedged KM must surface as a FAIL,
// never a silent pass).
static inline int sep_km_mbox_get(uint32_t *out, int timeout) {
    while (timeout-- > 0) {
        if (!(sep_km_mbox_rd(SEP_KM_MBOX_STATUS) & SEP_KM_MBOX_OUTBOUND_EMPTY)) {
            *out = sep_km_mbox_rd(SEP_KM_MBOX_READ_DATA);
            return 0;
        }
    }
    return -1;
}

// Send one framed word to the KM.
static inline void sep_km_mbox_send(uint32_t value) {
    sep_km_mbox_wr(SEP_KM_MBOX_WRITE_SEPARATOR, 1);
    sep_km_mbox_wr(SEP_KM_MBOX_WRITE_DATA, value);
}

#endif // SEP_KM_MAILBOX_H
