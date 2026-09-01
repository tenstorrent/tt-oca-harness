// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// SEP reset-control driver (EL2 host side).
//
// The SEP reset controller holds the Key Manager (KM) PicoRV32 second core in
// warm reset out of cold reset: SW_RESET_N resets to 0x3E, i.e. km_sw_rst_n
// (bit 0) = 0 while the crypto cores and internal TRNG come up released.
// The EL2 firmware writes km_sw_rst_n = 1 to release the KM so it boots from its
// ROM responder. (Addresses are SEP fabric facts; hw/sys/sep/regs sep_reset_ctrl.)

#ifndef SEP_RESET_H
#define SEP_RESET_H

#include <stdint.h>
#include <stdbool.h>

#define SEP_RESET_CTRL_SW_RESET_N 0x10803000u // SW_RESET_N register
#define SEP_SW_RESET_N_DEFAULT \
    0x0000003Eu                         // reset value: km held (bit0=0),
                                        // otbn/aes/hmac/kmac/trng released
#define SEP_SW_RESET_N_KM_BIT (1u << 0) // km_sw_rst_n: 1 = KM released
#define SEP_SW_RESET_N_OTBN_BIT (1u << 1)
#define SEP_SW_RESET_N_AES_BIT (1u << 2)
#define SEP_SW_RESET_N_HMAC_BIT (1u << 3)
#define SEP_SW_RESET_N_KMAC_BIT (1u << 4)
#define SEP_SW_RESET_N_TRNG_BIT (1u << 5)

static inline uint32_t sep_reset_rd(uint32_t addr) {
    return *(volatile uint32_t *)addr;
}

static inline void sep_reset_wr(uint32_t addr, uint32_t value) {
    *(volatile uint32_t *)addr = value;
}

// Release the KM from warm reset (read-modify-write so the other crypto cores'
// reset bits are preserved). After this the KM PicoRV32 boots from its ROM.
static inline void sep_reset_release_km(void) {
    uint32_t v = sep_reset_rd(SEP_RESET_CTRL_SW_RESET_N);
    sep_reset_wr(SEP_RESET_CTRL_SW_RESET_N, v | SEP_SW_RESET_N_KM_BIT);
}

// Callers must quiesce AES/KMAC/OTBN and KM before asserting this shared
// entropy-domain reset, then fully reinitialize ESRC/CSRNG/EDN before release.
static inline void sep_reset_assert_trng(void) {
    uint32_t v = sep_reset_rd(SEP_RESET_CTRL_SW_RESET_N);
    sep_reset_wr(SEP_RESET_CTRL_SW_RESET_N, v & ~SEP_SW_RESET_N_TRNG_BIT);
}

static inline void sep_reset_release_trng(void) {
    uint32_t v = sep_reset_rd(SEP_RESET_CTRL_SW_RESET_N);
    sep_reset_wr(SEP_RESET_CTRL_SW_RESET_N, v | SEP_SW_RESET_N_TRNG_BIT);
}

// Begin alarm recovery by holding all native-EDN consumers in reset before the
// TRNG request. HMAC is intentionally absent because it has no EDN input.
// Set reset_km when mux leg 0 selects the internal DRBG and KM is not known idle.
// The returned value is restored only after ESRC/CSRNG/EDN reinitialization and
// an observation of fresh endpoint/pool progress.
static inline uint32_t sep_reset_begin_trng_recovery(bool reset_km) {
    uint32_t saved = sep_reset_rd(SEP_RESET_CTRL_SW_RESET_N);
    uint32_t consumer_bits =
        SEP_SW_RESET_N_AES_BIT | SEP_SW_RESET_N_KMAC_BIT | SEP_SW_RESET_N_OTBN_BIT;
    if (reset_km) consumer_bits |= SEP_SW_RESET_N_KM_BIT;

    sep_reset_wr(SEP_RESET_CTRL_SW_RESET_N, saved & ~consumer_bits);
    sep_reset_wr(SEP_RESET_CTRL_SW_RESET_N,
                 saved & ~consumer_bits & ~SEP_SW_RESET_N_TRNG_BIT);
    return saved;
}

static inline void sep_reset_release_trng_for_reinit(void) {
    sep_reset_release_trng();
}

static inline void sep_reset_restore_consumers(uint32_t saved_sw_reset_n) {
    sep_reset_wr(SEP_RESET_CTRL_SW_RESET_N, saved_sw_reset_n);
}

#endif // SEP_RESET_H
