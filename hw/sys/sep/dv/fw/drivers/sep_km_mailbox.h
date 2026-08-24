// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// SEP-side (EL2) driver for the KM <-> SEP mailbox, used to coordinate the EL2
// host CPU with the Key Manager's PicoRV32 second core. Header-only,
// self-contained (addresses are SEP fabric facts, matching km_mailbox_sep.rdl /
// och_sep_top_reg). The KM core uses its own KM-local aliases; this header is
// the host/EL2 view at the SEP-local 0x1092_0000 aperture.

#ifndef SEP_KM_MAILBOX_H
#define SEP_KM_MAILBOX_H

#include <stdint.h>

// KM<->SEP mailbox, host (SEP/EL2) side.
#define SEP_KM_MBOX_WRITE_DATA 0x10920000u      // EL2 -> KM payload
#define SEP_KM_MBOX_WRITE_SEPARATOR 0x10920004u // write 1 to frame a message
#define SEP_KM_MBOX_READ_DATA 0x10920008u       // KM -> EL2 payload
#define SEP_KM_MBOX_STATUS 0x1092000Cu          // SEP_STATUS

// SEP_STATUS bits.
#define SEP_KM_MBOX_OUTBOUND_EMPTY (1u << 2) // KM->EL2 FIFO empty when set

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
