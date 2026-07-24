// SPDX-License-Identifier: Apache-2.0
//
// SEP reset-control driver (EL2 host side).
//
// The SEP reset controller holds the Key Manager (KM) PicoRV32 second core in
// warm reset out of cold reset: SW_RESET_N resets to 0x1E, i.e. km_sw_rst_n
// (bit 0) = 0 while the other crypto cores (otbn/aes/hmac/kmac) come up released.
// The EL2 firmware writes km_sw_rst_n = 1 to release the KM so it boots from its
// ROM responder. (Addresses are SEP fabric facts; meta/registers sep_reset_ctrl.)

#ifndef SEP_RESET_H
#define SEP_RESET_H

#include <stdint.h>

#define SEP_RESET_CTRL_SW_RESET_N   0x10803000u  // SW_RESET_N register
#define SEP_SW_RESET_N_DEFAULT      0x0000001Eu  // reset value: km held (bit0=0),
                                                 // otbn/aes/hmac/kmac released
#define SEP_SW_RESET_N_KM_BIT       (1u << 0)    // km_sw_rst_n: 1 = KM released
#define SEP_SW_RESET_N_OTBN_BIT     (1u << 1)
#define SEP_SW_RESET_N_AES_BIT      (1u << 2)
#define SEP_SW_RESET_N_HMAC_BIT     (1u << 3)
#define SEP_SW_RESET_N_KMAC_BIT     (1u << 4)

static inline uint32_t sep_reset_rd(uint32_t addr)
{
    return *(volatile uint32_t *)addr;
}

static inline void sep_reset_wr(uint32_t addr, uint32_t value)
{
    *(volatile uint32_t *)addr = value;
}

// Release the KM from warm reset (read-modify-write so the other crypto cores'
// reset bits are preserved). After this the KM PicoRV32 boots from its ROM.
static inline void sep_reset_release_km(void)
{
    uint32_t v = sep_reset_rd(SEP_RESET_CTRL_SW_RESET_N);
    sep_reset_wr(SEP_RESET_CTRL_SW_RESET_N, v | SEP_SW_RESET_N_KM_BIT);
}

#endif  // SEP_RESET_H
