// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// SEP eFuse host-read driver (EL2 host side).
//
// The EL2 host reaches the eFuse host block through the SEP local crossbar and
// the u_km_efuse_axi_lite_mux (slave port 0). After fuse-sense, the sensed
// shadow registers (MAP block @ 0x1093_0000) are readable; the MMR block
// (@ 0x1093_0500) holds plain RW scratch MMRs the KM owns. (Addresses are SEP
// fabric facts; hw/sys/sep/regs efuse_interface_ctrl / efuse_mmr / sep_efuse_map.)

#ifndef SEP_EFUSE_H
#define SEP_EFUSE_H

#include <stdint.h>

#include "sep.h"

// eFuse MAP shadow block (sensed OTP). CHIPLET_UID's offset comes from the generated
// map, not a literal: a hardcoded offset silently follows a stale layout when a
// field is inserted ahead of it, and a model carrying the same stale copy hides it.
#define SEP_EFUSE_MAP_BASE OCH_SEP_TOP_SEP_EFUSE_MAP_BASE_ADDR
#define SEP_EFUSE_CHIPLET_UID0 OCH_SEP_TOP_SEP_EFUSE_MAP_CHIPLET_UID_BASE_ADDR

// eFuse interface-control STATUS: bit0 = efuse_sense_done. Block base from the
// generated map, not a literal, so a relocated block cannot leave this pointing
// at whatever occupies its former address.
#define SEP_EFUSE_IFC_STATUS OCH_SEP_TOP_EFUSE_INTERFACE_CTRL_EFUSE_INTERFACE_CTRL_STATUS_BASE_ADDR
#define SEP_EFUSE_SENSE_DONE EFUSE_INTERFACE_CTRL__EFUSE_INTERFACE_CTRL_STATUS__EFUSE_SENSE_DONE_bm

// eFuse MMR block, RMA_SIP_TOKEN_I[0..1] (sw=rw): used here as KM-owned scratch
// MMRs. The KM writes an owner-tagged incrementing counter; the EL2 reads back.
#define SEP_EFUSE_MMR0 OCH_SEP_TOP_EFUSE_MMR_RMA_SIP_TOKEN_I_BASE_ADDR(0)
#define SEP_EFUSE_MMR1 OCH_SEP_TOP_EFUSE_MMR_RMA_SIP_TOKEN_I_BASE_ADDR(1)
#define SEP_EFUSE_MMR2 OCH_SEP_TOP_EFUSE_MMR_RMA_SIP_TOKEN_I_BASE_ADDR(2)

static inline uint32_t sep_efuse_rd(uint32_t addr) {
    return *(volatile uint32_t *)addr;
}

static inline void sep_efuse_wr(uint32_t addr, uint32_t value) {
    *(volatile uint32_t *)addr = value;
}

// Poll the eFuse interface STATUS until sense-done (bounded). Returns 0 on
// sense-done, -1 on timeout (a stuck sense FSM must surface as a test FAIL).
static inline int sep_efuse_wait_sense_done(int timeout) {
    while (timeout-- > 0) {
        if (sep_efuse_rd(SEP_EFUSE_IFC_STATUS) & SEP_EFUSE_SENSE_DONE) {
            return 0;
        }
    }
    return -1;
}

#endif // SEP_EFUSE_H
