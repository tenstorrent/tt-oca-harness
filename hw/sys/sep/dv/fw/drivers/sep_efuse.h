// SPDX-License-Identifier: Apache-2.0
//
// SEP eFuse host-read driver (EL2 host side).
//
// The EL2 host reaches the eFuse host block through the SEP local crossbar and
// the u_km_efuse_axi_lite_mux (slave port 0). After fuse-sense, the sensed
// shadow registers (MAP block @ 0x1093_0000) are readable; the MMR block
// (@ 0x1093_0500) holds plain RW scratch MMRs the KM owns. (Addresses are SEP
// fabric facts; meta/registers efuse_interface_ctrl / efuse_mmr / sep_efuse_map.)

#ifndef SEP_EFUSE_H
#define SEP_EFUSE_H

#include <stdint.h>

// eFuse MAP shadow block (sensed OTP), CHIPLET_UID at byte offset 0xC8 (8 words).
#define SEP_EFUSE_MAP_BASE      0x10930000u
#define SEP_EFUSE_CHIPLET_UID0  (SEP_EFUSE_MAP_BASE + 0xC8u)  // 0x109300C8 (word0)

// eFuse interface-control STATUS: bit0 = efuse_sense_done.
#define SEP_EFUSE_IFC_STATUS    0x10930400u
#define SEP_EFUSE_SENSE_DONE    (1u << 0)

// eFuse MMR block, RMA_SIP_TOKEN_I[0..1] (sw=rw): used here as KM-owned scratch
// MMRs. The KM writes an owner-tagged incrementing counter; the EL2 reads back.
#define SEP_EFUSE_MMR0          0x10930500u  // RMA_SIP_TOKEN_I[0]
#define SEP_EFUSE_MMR1          0x10930504u  // RMA_SIP_TOKEN_I[1]
#define SEP_EFUSE_MMR2          0x10930508u  // RMA_SIP_TOKEN_I[2]

static inline uint32_t sep_efuse_rd(uint32_t addr)
{
    return *(volatile uint32_t *)addr;
}

static inline void sep_efuse_wr(uint32_t addr, uint32_t value)
{
    *(volatile uint32_t *)addr = value;
}

// Poll the eFuse interface STATUS until sense-done (bounded). Returns 0 on
// sense-done, -1 on timeout (a stuck sense FSM must surface as a test FAIL).
static inline int sep_efuse_wait_sense_done(int timeout)
{
    while (timeout-- > 0) {
        if (sep_efuse_rd(SEP_EFUSE_IFC_STATUS) & SEP_EFUSE_SENSE_DONE) {
            return 0;
        }
    }
    return -1;
}

#endif  // SEP_EFUSE_H
