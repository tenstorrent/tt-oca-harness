// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// SEP reset-control driver (EL2 host side).
//
// The SEP reset controller holds the Key Manager (KM) PicoRV32 second core in
// warm reset out of cold reset: SW_RESET_N resets with km_sw_rst_n (bit 0) = 0
// while the crypto cores, Adams Bridge and the internal TRNG come up released.
// The EL2 firmware writes km_sw_rst_n = 1 to release the KM so it boots from
// its ROM responder.
// Addresses and field masks come from generated sep_addr.h / sep_reset_ctrl.h
// (via sep.h).

#ifndef SEP_RESET_H
#define SEP_RESET_H

#include <stdint.h>
#include <stdbool.h>

#include "sep.h"

#define SEP_RESET_CTRL_SW_RESET_N SEP_TOP_SEP_RESET_CTRL_SW_RESET_N_BASE_ADDR
#define SEP_SW_RESET_N_DEFAULT SEP_RESET_CTRL__SW_RESET_N_reset
#define SEP_SW_RESET_N_KM_BIT SEP_RESET_CTRL__SW_RESET_N__KM_SW_RST_N_bm
#define SEP_SW_RESET_N_OTBN_BIT SEP_RESET_CTRL__SW_RESET_N__OTBN_SW_RST_N_bm
#define SEP_SW_RESET_N_AES_BIT SEP_RESET_CTRL__SW_RESET_N__AES_SW_RST_N_bm
#define SEP_SW_RESET_N_HMAC_BIT SEP_RESET_CTRL__SW_RESET_N__HMAC_SW_RST_N_bm
#define SEP_SW_RESET_N_KMAC_BIT SEP_RESET_CTRL__SW_RESET_N__KMAC_SW_RST_N_bm
#define SEP_SW_RESET_N_TRNG_BIT SEP_RESET_CTRL__SW_RESET_N__TRNG_SW_RST_N_bm
#define SEP_SW_RESET_N_ABR_BIT SEP_RESET_CTRL__SW_RESET_N__ABR_SW_RST_N_bm

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
// TRNG request. HMAC is absent: it has no EDN input.
// Set reset_km when mux leg 0 selects the internal DRBG and KM is not known idle.
// The returned value is restored only after ESRC/CSRNG/EDN reinitialization and
// an observation of fresh endpoint/pool progress.
static inline uint32_t sep_reset_begin_trng_recovery(bool reset_km) {
    uint32_t saved = sep_reset_rd(SEP_RESET_CTRL_SW_RESET_N);
    uint32_t consumer_bits =
        SEP_SW_RESET_N_AES_BIT | SEP_SW_RESET_N_KMAC_BIT | SEP_SW_RESET_N_OTBN_BIT;
    if (reset_km) consumer_bits |= SEP_SW_RESET_N_KM_BIT;

    sep_reset_wr(SEP_RESET_CTRL_SW_RESET_N, saved & ~consumer_bits);
    sep_reset_wr(SEP_RESET_CTRL_SW_RESET_N, saved & ~consumer_bits & ~SEP_SW_RESET_N_TRNG_BIT);
    return saved;
}

static inline void sep_reset_release_trng_for_reinit(void) {
    sep_reset_release_trng();
}

static inline void sep_reset_restore_consumers(uint32_t saved_sw_reset_n) {
    sep_reset_wr(SEP_RESET_CTRL_SW_RESET_N, saved_sw_reset_n);
}

#endif // SEP_RESET_H
